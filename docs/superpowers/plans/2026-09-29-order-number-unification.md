# 订单号体系统一 —— 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把订单/采购/备货/出货等业务编号收敛为单一异步实现（`numbering_counter` 表为唯一水位源），日期段统一北京时间，修取号种子缺陷，加巡检监控，隔离 E2E 对生产库的直写。

**Architecture:** 删除 `core/number_generator.py` 与 `shared/stock_crud_service.py` 双实现，全部取号走 `services/numbering.py` → `numbering_sequence.py` 的原子 upsert；批量导入任务（ARQ）从事务内同步取号改为调用异步生成器；`read_daily_max` 从「日期列过滤 + 字符串降序」改为「编号日期段过滤 + 数值 max + 正则守卫」；部署对账在 FastAPI lifespan 内幂等执行。

**Tech Stack:** FastAPI + SQLAlchemy 2.0 async + asyncpg + PostgreSQL（advisory lock / `split_part` / `ON CONFLICT`）+ ARQ + pytest（asyncio_mode=auto）。

**Spec:** `docs/superpowers/specs/2026-09-29-order-number-unification-design.md`（提交 85759a76）

## Global Constraints

- 日期段口径：北京时间 `Asia/Shanghai`（spec §3）；非编号用途的 `YYYYMMDD`（logger 文件名、备份时间戳、存储路径前缀）**不动**（spec §4.1）。
- 编号格式恒为 `PREFIX-YYYYMMDD-SEQ`，序号 `zfill(4)` 不截断（过 9999 变 5 位）；**允许跳号、绝不允许重号**（spec §1/§5）。
- 存量 15 个编号不回填不重置；`numbering_counter` 不清零（spec §5）。
- 引用副本列不加唯一约束（spec §4.5）。
- `pytest.ini`：`asyncio_mode = auto`、`asyncio_default_fixture_loop_scope = function`、`--strict-markers`。
- 本机 shell 陷阱：`cat`/`head`/`git` 等被 `_lc` 别名劫持，shell 命令一律 `command X` 前缀；`timeout` 不能带 `command`（见项目记忆）。
- 测试跑法：`PYTHONUTF8=1 python -m pytest <path> -v`（pytest-asyncio auto 模式，无需标记）。
- 每个任务结束必须全绿提交；提交信息结尾加 `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`。
- **任务 1–4 期间 `core/number_generator.py` 与 `shared/stock_crud_service.py` 必须仍然可导入**（批量导入还在用它们）——删除只发生在任务 6 的同提交内（spec §4.2 C1 论证）。

## Review Focus

1. **三位前缀 CSO/CSI 的 split_part 取段**——任何按「位置」截编号的代码（substring from 4）对三位前缀错位；`split_part('-', 2)` 不受前缀长度影响。测试：Task 4 用 `CSO-20260929-0001` 断言 `read_daily_max` 取到序号 1。
2. **序号 >9999 的数值序**——字符串降序会取 `'9999'` 当 max，漏掉 `'10000'`；cast bigint 的数值 max 必须取到 10000。测试：Task 4 边界用例。
3. **同日部署键碰撞**——UTC 日期==北京日期时 `allocate_sequence` 的 INSERT/seed 分支不触发，若 `data_max > last_seq` 会连续撞唯一索引；对账必须 GREATEST 只升不降且幂等。测试：Task 6 幂等用例（连跑两次结果不变）。
4. **批量导入语义保真**——50 行批量提交、行级失败 continue 不回滚整批、`skipped_uncommitted` 计数、抛异常时保留文件；任何一个丢了都会在生产写路径出事故。测试：Task 5 的 mock 语义测试逐条断言。
5. **E2E 守卫顺序**——指纹检查必须在探活 skip **之前**，否则「生产库在跑但后端探活失败」时守卫被短路。测试：Task 2 单测直接调用收集钩子函数断言顺序。

---

### Task 1: 锁工具迁移（纯搬家，零行为变更）

**Files:**
- Create: `fastapi_app/core/pg_locks.py`
- Modify: `fastapi_app/services/case/commands.py:11,56`
- Test: `fastapi_app/tests/test_pg_locks.py`

**Interfaces:**
- Consumes: 无（自包含）。
- Produces: `acquire_advisory_lock_async(db, lock_key: int) -> None`、`number_lock_key(scope: str, key: str) -> int`（Task 6 的启动对账复用 `number_lock_key`）。

- [ ] **Step 1: 写失败测试**

```python
"""core/pg_locks 的 advisory lock 键与 core/number_generator 逐位一致（搬家不改行为）。"""
import hashlib

from fastapi_app.core.pg_locks import number_lock_key


def test_number_lock_key_value_unchanged_from_legacy():
    # 与 core/number_generator._number_lock_key 的 md5 前 15 位十六进制方案逐位一致
    legacy = int(hashlib.md5(f"{'CASE_PRODUCT'}:{'42'}".encode(), usedforsecurity=False).hexdigest()[:15], 16)
    assert number_lock_key('CASE_PRODUCT', '42') == legacy


def test_number_lock_key_scope_sensitive():
    assert number_lock_key('A', '1') != number_lock_key('B', '1')


def test_number_lock_key_within_bigint():
    key = number_lock_key('PO', '20260929')
    assert 0 <= key < 2 ** 63
```

- [ ] **Step 2: 跑测试确认失败**

Run: `PYTHONUTF8=1 command python -m pytest fastapi_app/tests/test_pg_locks.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fastapi_app.core.pg_locks'`

- [ ] **Step 3: 创建 `fastapi_app/core/pg_locks.py`**

从 `fastapi_app/core/number_generator.py:35-56` 原样搬入 `_number_lock_key` → 改名 `number_lock_key(prefix, date_str)` → 参数改名 `(scope, key)`；`_acquire_advisory_lock_async` → 改名 `acquire_advisory_lock_async`。**同步版不搬**（spec §4.3：删 core 后无同步消费方）。md5 取键算法逐字节不变：

```python
"""PostgreSQL advisory lock 工具（编号与业务锁共用）。

自 core/number_generator.py 迁出：该模块删除后，CASE 创建锁等业务用途
仍需要同一把事务级 advisory lock。md5 取键方案保持不变，lock key 与
迁移前逐位一致，无运行时行为变更。
"""
import hashlib
import logging

from sqlalchemy import func, select

logger = logging.getLogger(__name__)


def number_lock_key(scope: str, key: str) -> int:
    """为 (scope, key) 生成 64 位 PostgreSQL advisory lock key。"""
    raw = f"{scope}:{key}".encode()
    hex_key = hashlib.md5(raw, usedforsecurity=False).hexdigest()[:15]
    return int(hex_key, 16)


async def acquire_advisory_lock_async(db, lock_key: int) -> None:
    """获取 PostgreSQL 事务级 advisory lock；非 PG 环境则忽略。"""
    try:
        await db.execute(select(func.pg_advisory_xact_lock(lock_key)))
    except Exception:  # defensive: 非PG或测试环境可降级为无advisory lock
        logger.debug("advisory lock 获取失败，降级为无锁模式", exc_info=True)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `PYTHONUTF8=1 command python -m pytest fastapi_app/tests/test_pg_locks.py -v`
Expected: PASS（3 个用例）

- [ ] **Step 5: 切换 `case/commands.py` 的导入并回归**

`fastapi_app/services/case/commands.py:11` 删 `from fastapi_app.core.number_generator import _acquire_advisory_lock_async, _number_lock_key`，改为：

```python
from fastapi_app.core.pg_locks import acquire_advisory_lock_async, number_lock_key
```

`:56` 调用改为：

```python
    await acquire_advisory_lock_async(db, number_lock_key('CASE_PRODUCT', str(product_id)))
```

Run: `PYTHONUTF8=1 command python -m pytest fastapi_app/tests/test_pg_locks.py -v -q --no-header 2>&1 | command tail -2; PYTHONUTF8=1 command python -m pytest fastapi_app/tests -k "case" -q 2>&1 | command tail -3`
Expected: pg_locks 测试 PASS；case 相关测试无新增失败（存量有红请先对照 git stash 前基线，见「本机测试假信号」记忆：policy 测试必红属 env 差异）。

- [ ] **Step 6: 提交**

```bash
command git add fastapi_app/core/pg_locks.py fastapi_app/services/case/commands.py fastapi_app/tests/test_pg_locks.py
command git commit -m "refactor(core): advisory lock 工具迁至 core/pg_locks，与编号实现解耦"
```

---

### Task 2: E2E 隔离（P0）

**Files:**
- Modify: `tests/e2e_api/conftest.py:55-161`（BASE_URL 默认值、指纹拦截、docstring）
- Modify: `tests/e2e_api/test_write_paths.py:85-210`（_cleanup 纵深防御）
- Test: `tests/e2e_api/test_guard.py`（新建）

**Interfaces:**
- Consumes: 无。
- Produces: `BASE_URL: str | None`（None 时整目录 skip）；`_production_fingerprint_hit() -> tuple[bool, str]`（Task 内测试直接调用）；`real_database_url()`（既有，不变）。

- [ ] **Step 1: 写失败测试**

`tests/e2e_api/test_guard.py`（新文件）：

```python
"""E2E 生产指纹守卫：指向生产库/生产端口必须拒绝运行（fail-fast）。"""
import os
from unittest import mock

import pytest

import tests.e2e_api.conftest as e2e_conftest


def test_unset_target_guards_trigger_skip_marker(monkeypatch):
    # 未显式指定目标 → 指纹不命中，允许走到探活 skip 分支
    monkeypatch.setattr(e2e_conftest, 'BASE_URL', 'http://127.0.0.1:9999')
    monkeypatch.setenv('ERP_E2E_REAL_DATABASE_URL', 'postgresql://u:p@localhost/erp_system_test')
    hit, reason = e2e_conftest._production_fingerprint_hit()
    assert not hit, reason


def test_port_5002_is_fingerprint():
    hit, _ = e2e_conftest._production_fingerprint_hit(
        base_url='http://127.0.0.1:5002', db_url='postgresql://u:p@localhost/erp_system_test')
    assert hit


def test_db_erp_system_is_fingerprint():
    hit, _ = e2e_conftest._production_fingerprint_hit(
        base_url='http://127.0.0.1:9999', db_url='postgresql+psycopg://u:p@localhost:5432/erp_system')
    assert hit


def test_fingerprint_checked_before_backend_alive(monkeypatch):
    # 守卫必须先于探活：生产库+死端口 → fail-fast 而不是静默 skip
    # （探活结果由模块级 _backend_alive() 固化，这里直接验证钩子函数逻辑）
    monkeypatch.setattr(e2e_conftest, '_ALIVE', False)
    monkeypatch.setattr(e2e_conftest, '_ALIVE_REASON', 'unreachable')
    monkeypatch.setattr(e2e_conftest, 'BASE_URL', 'http://127.0.0.1:5002')
    monkeypatch.setenv('ERP_E2E_REAL_DATABASE_URL', 'postgresql://u:p@localhost/erp_system')

    class _Item:
        own_markers = []

        def add_marker(self, m):
            self.own_markers.append(m)

    import pytest as _pytest
    with pytest.raises(_pytest.exit.Exception) as excinfo:
        e2e_conftest.pytest_collection_modifyitems(None, [_Item()])
    assert '生产' in str(excinfo.value) or 'production' in str(excinfo.value)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `PYTHONUTF8=1 command python -m pytest tests/e2e_api/test_guard.py -v`
Expected: FAIL — `AttributeError: module has no attribute '_production_fingerprint_hit'`

- [ ] **Step 3: 实现 conftest 守卫**

`tests/e2e_api/conftest.py` 三处修改（**不新增同名 hook**，在既有 `pytest_collection_modifyitems` 函数体内追加，且指纹检查排在探活判断之前——spec §4.6）：

(a) BASE_URL 去默认值（`:72`）：

```python
# 必须显式指定目标后端；未设置时 BASE_URL 为 None，收集钩子整目录 skip。
# 绝不给默认值 127.0.0.1:5002 —— 那是生产后端（nginx upstream）。
BASE_URL: str | None = os.environ.get("E2E_API_BASE_URL")
if BASE_URL:
    BASE_URL = BASE_URL.rstrip("/")
```

(b) 新增指纹函数（放在 `_backend_alive` 定义之前）：

```python
def _production_fingerprint_hit(
    base_url: str | None = None,
    db_url: str | None = None,
) -> tuple[bool, str]:
    """目标命中生产指纹 → (True, 原因)。无绕过开关（fail-fast 是刻意的）。"""
    from urllib.parse import urlparse

    url = base_url if base_url is not None else BASE_URL
    dsn = db_url if db_url is not None else os.environ.get(_REAL_DB_ENV_KEY, "")

    if url:
        try:
            if urlparse(url).port == 5002:
                return True, f"E2E_API_BASE_URL 端口指向生产后端: {url}"
        except ValueError:
            pass
    try:
        if urlparse(dsn).path.lstrip('/') == 'erp_system':
            return True, "ERP_E2E_REAL_DATABASE_URL 指向生产库 erp_system"
    except ValueError:
        pass
    return False, ""


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """指纹命中 → 终止整个 pytest 会话；后端不可达 → 跳过本目录所有用例。

    指纹检查必须在探活之前：否则「生产库在跑但后端探活失败」时先走 skip
    分支，守卫被短路。pytest.exit 终止的是整个会话而非单目录 —— 有意为之。
    """
    hit, reason = _production_fingerprint_hit()
    if hit:
        pytest.exit(
            f"拒绝运行 E2E：{reason}。E2E 不得指向生产。请同时设置 "
            "E2E_API_BASE_URL（非 5002 的临时后端）与 "
            "ERP_E2E_REAL_DATABASE_URL（测试库 DSN）。",
            returncode=2,
        )
    if not BASE_URL:
        skip = pytest.mark.skip(reason="未设置 E2E_API_BASE_URL，跳过 API 层 E2E")
        for item in items:
            item.add_marker(skip)
        return
    if _ALIVE:
        return
    skip = pytest.mark.skip(
        reason=(
            f"API 层 E2E 需要真实后端（{BASE_URL}），当前不可达：{_ALIVE_REASON}。"
            "请先启动专用后端并设置 E2E_API_BASE_URL"
        )
    )
    for item in items:
        item.add_marker(skip)
```

注意：既有 `:150-161` 的 `pytest_collection_modifyitems` 函数体**整体替换**为上面这段（函数只有一个）；`_ALIVE, _ALIVE_REASON = _backend_alive()`（`:147`）需加 `BASE_URL` 空值守卫——`_backend_alive` 开头加 `if not BASE_URL: return False, "E2E_API_BASE_URL 未设置"`。

(c) docstring（文件头）运行说明追加：

```
运行条件（2026-09-29 起）：
    必须显式设置两个环境变量，否则整目录 skip 或 fail-fast：
    - E2E_API_BASE_URL：指向专用临时后端（禁止 5002 —— 生产）
    - ERP_E2E_REAL_DATABASE_URL：测试库 DSN（禁止 erp_system —— 生产库）
    生产指纹命中时 pytest.exit(returncode=2) 终止整个会话，无绕过开关。
```

- [ ] **Step 4: 跑守卫测试确认通过**

Run: `PYTHONUTF8=1 command python -m pytest tests/e2e_api/test_guard.py -v`
Expected: PASS（4 个用例）

- [ ] **Step 5: `_cleanup` 纵深防御**

`tests/e2e_api/test_write_paths.py:85` 的 `_cleanup` 在 `engine = _sync_engine()` 之前插入：

```python
    from tests.e2e_api.conftest import real_database_url

    dsn = real_database_url()
    if '/erp_system' in dsn and 'erp_system_test' not in dsn:
        raise RuntimeError(f"E2E 清理拒绝连接生产库: {dsn}")
```

- [ ] **Step 6: 验证 E2E 目录在默认环境下整目录 skip（不连生产）**

Run: `PYTHONUTF8=1 command python -m pytest tests/e2e_api -q 2>&1 | command tail -3`
Expected: 全部 skip（`E2E_API_BASE_URL` 未设置）；绝无 `__e2e_wp__` 前缀数据写往 5002。

- [ ] **Step 7: 提交**

```bash
command git add tests/e2e_api/conftest.py tests/e2e_api/test_write_paths.py tests/e2e_api/test_guard.py
command git commit -m "test(e2e): E2E 与生产隔离——去默认地址、指纹 fail-fast、清理纵深防御"
```

---

### Task 3: 删除死代码 order_purchase_sync（P3）

**Files:**
- Delete: `fastapi_app/services/order_purchase_sync.py`
- Modify: `fastapi_app/core/domains.py:59`

**Interfaces:**
- Consumes: 无。
- Produces: 无（纯删除）。

- [ ] **Step 1: 复核零引用**

Run: `command grep -rn "order_purchase_sync" --include=*.py . 2>/dev/null | command grep -v "^./.archive/" | command grep -v "docs/"`
Expected: 仅 `fastapi_app/core/domains.py:59` 一处（DOMAIN_SERVICE_MAP 字符串项）。若出现其他引用，**停下**报告，不得删除。

- [ ] **Step 2: 删除文件与注册项**

```bash
command git rm fastapi_app/services/order_purchase_sync.py
```

`fastapi_app/core/domains.py:59`：

```python
    Domain.ORDER: ['order_service', 'order_batch_service'],
```

- [ ] **Step 3: 回归**

Run: `PYTHONUTF8=1 command python -m pytest fastapi_app/tests -k "domain or order" -q 2>&1 | command tail -3; PYTHONUTF8=1 command python -c "from fastapi_app.core.domains import DOMAIN_SERVICE_MAP; print(DOMAIN_SERVICE_MAP)"`
Expected: 测试无新增失败；DOMAIN_SERVICE_MAP 打印正常。

- [ ] **Step 4: 提交**

```bash
command git add fastapi_app/core/domains.py
command git commit -m "chore(order): 删除死代码 order_purchase_sync（硬编码 PO-PENDING 编号，零调用者）"
```

---

### Task 4: read_daily_max 修正（数值排序 + 编号日期段过滤 + 正则守卫）

**Files:**
- Modify: `fastapi_app/services/numbering_sequence.py:105-124`
- Modify: `fastapi_app/services/numbering.py:98,146`（调用点传 date_str；`generate_number_async`/`generate_number_batch` 去掉 `date_field` 形参）
- Modify: `fastapi_app/services/purchase_plan_common.py:63-96`（PP 复用 read_daily_max）
- Modify: `fastapi_app/tests/test_numbering_batch.py:33`（fake 签名同步）
- Modify: `docs/tickets/tools/verify_iter2_numbering.py:100`（fake 签名同步）
- Test: `tests/test_numbering_unified.py`（新建，注意在 `tests/` 下——复用 `db_and_factory` 模式）

**Interfaces:**
- Consumes: `allocate_sequence(prefix, date_str, seed)`（既有，不变）、`allocate_sequence_range`（既有，不变）。
- Produces: `async read_daily_max(db: AsyncSession, model, number_field: str, date_str: str) -> int`（**4 参新签名**，Task 5/6 依赖）；`generate_number_async(prefix, model, number_field, db)`（去 `date_field`）；`generate_number_batch(prefix, model, number_field, db, count)`（去 `date_field`）。

- [ ] **Step 1: 写失败测试**

`tests/test_numbering_unified.py`（新建）：

```python
"""订单号统一后的种子算法与口径测试（spec §6.2/§6.4）。"""
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from fastapi_app.services.numbering_sequence import read_daily_max
from fastapi_app.shared_models import CaseStockOut, Order


@pytest.mark.asyncio
async def test_read_daily_max_numeric_order_beats_lexicographic(db):
    # 同日 9999 与 10000 并存：字符串降序取 '9999'，数值 max 必须取 10000
    db.add_all([
        Order(order_no='PO-20260929-9999', customer='c', quantity=1,
              order_date=datetime(2026, 9, 29, tzinfo=UTC)),
        Order(order_no='PO-20260929-10000', customer='c', quantity=1,
              order_date=datetime(2026, 9, 29, tzinfo=UTC)),
    ])
    await db.flush()
    assert await read_daily_max(db, Order, 'order_no', '20260929') == 10000


@pytest.mark.asyncio
async def test_read_daily_max_filters_by_number_date_segment(db):
    # 种子只看编号自身的日期段，与日期列的时区口径无关
    db.add_all([
        Order(order_no='PO-20260929-0001', customer='c', quantity=1,
              order_date=datetime(2026, 9, 28, 20, 0, tzinfo=UTC)),  # 北京 09-29 凌晨
        Order(order_no='PO-20260928-0005', customer='c', quantity=1,
              order_date=datetime(2026, 9, 29, 5, 0, tzinfo=UTC)),  # 北京 09-29 下午
    ])
    await db.flush()
    assert await read_daily_max(db, Order, 'order_no', '20260929') == 1
    assert await read_daily_max(db, Order, 'order_no', '20260928') == 5


@pytest.mark.asyncio
async def test_read_daily_max_three_char_prefix_cso(db):
    # 三位前缀 CSO：split_part 不受前缀长度影响（substring 按位截取会错位）
    db.add(CaseStockOut(stockout_no='CSO-20260929-0007', case_id=1, product_id=1,
                        quantity=1, stockout_date=datetime(2026, 9, 29, tzinfo=UTC)))
    await db.flush()
    assert await read_daily_max(db, CaseStockOut, 'stockout_no', '20260929') == 7


@pytest.mark.asyncio
async def test_read_daily_max_malformed_rows_are_guards_not_crashes(db):
    # 脏行（序号段非数字）必须被正则守卫过滤，cast 不抛 invalid input syntax
    db.add_all([
        Order(order_no='PO-20260929-0002', customer='c', quantity=1,
              order_date=datetime(2026, 9, 29, tzinfo=UTC)),
        Order(order_no='PO-20260929-XX', customer='c', quantity=1,
              order_date=datetime(2026, 9, 29, tzinfo=UTC)),
    ])
    await db.flush()
    assert await read_daily_max(db, Order, 'order_no', '20260929') == 2


@pytest.mark.asyncio
async def test_read_daily_max_empty_returns_zero(db):
    assert await read_daily_max(db, Order, 'order_no', '20991231') == 0
```

测试基座：**本仓无通用 `db` fixture**——`fastapi_app/tests/conftest.py` 只有 mock 系 fixture。
带真库的编号测试用的是 `tests/test_numbering_sequence_integration.py:45-63` 的自包含模式：
`db_and_factory`（函数级 `create_async_engine(_test_db_url())` + `Base.metadata.create_all`
+ 事务回滚 + monkeypatch `_AsyncSessionLocal`）。**新建测试文件放 `tests/`（不是
`fastapi_app/tests/`），逐字复用该 fixture**（`pytestmark = pytest.mark.integration`，
直接把 `:45-63` 的 fixture 抄进新文件，或 conftest 化共用）。下文测试代码中 `db`
均指该 fixture 的 session；`db_and_factory` 展开为 `session, factory`。

- [ ] **Step 2: 跑测试确认失败**

Run: `PYTHONUTF8=1 command python -m pytest tests/test_numbering_unified.py -v`
Expected: FAIL — `TypeError: read_daily_max() takes 4 positional arguments but 5 were given`（旧签名是 `db, model, date_field, number_field`，新调用传 `date_str`）

- [ ] **Step 3: 重写 `read_daily_max`**

`fastapi_app/services/numbering_sequence.py:105-124` 整体替换：

```python
async def read_daily_max(db: AsyncSession, model, number_field: str, date_str: str) -> int:
    """当日已落库的最大序号（按数值排序，无锁读，仅作连续性种子）。

    以编号自身的日期段过滤（split_part 第 2 段），与日期列的时区口径无关；
    正则守卫保证进入 cast 的序号段必为数字（脏行不抛 invalid input syntax）。
    """
    col = getattr(model, number_field)
    seq = func.cast(func.split_part(col, '-', 3), BigInteger)
    result = await db.execute(
        select(func.max(seq)).where(col.op('~')(f'^[A-Z]+-{date_str}-[0-9]+$'))
    )
    return int(result.scalar() or 0)
```

文件头 import 区加 `from sqlalchemy import BigInteger`（`func, select, text` 已有）。

- [ ] **Step 4: 更新 `services/numbering.py` 调用点与签名**

- `:73-100` `generate_number_async(prefix, model, number_field, db)`：删 `date_field` 形参；`:98` 改
  `db_max = await read_daily_max(db, model, number_field, date_str)`（`date_str` 仍来自 `:93` 的
  `datetime.now(UTC).strftime('%Y%m%d')`——**本任务不切口径**，Task 6 才换 `business_date_str()`）。
- `:108-149` `generate_number_batch(prefix, model, number_field, db, count)`：删 `date_field`；`:146` 同上。
- 8 个 helper（`:103-200`）调用处删去 `'order_date'` / `'stockin_date'` / `'create_time'` / `'created_at'` 等
  date_field 实参。
- `:26-30` 的 re-export 块**本任务不动**（Task 6 删）。

- [ ] **Step 5: 更新 `purchase_plan_common.py`**

`_generate_plan_no`（`:63-96`）：删除 `:82-94` 的 seed_session/LIKE 查询块，改为：

```python
async def _generate_plan_no() -> str:
    """生成计划编号：PP-YYYYMMDD-NNNN

    序号经 numbering_counter 原子分配（allocate_sequence）；种子由
    read_daily_max 按编号日期段数值读取（spec §4.4 收口）。
    """
    from fastapi_app.core.database import require_async_session_local
    from fastapi_app.services.numbering import allocate_sequence, read_daily_max

    today_str = datetime.now(UTC).strftime('%Y%m%d')  # Task 6 统一换 business_date_str()
    session_factory = require_async_session_local()
    async with session_factory() as seed_session:
        seed = await read_daily_max(seed_session, PurchasePlan, 'plan_no', today_str)
    next_seq = await allocate_sequence('PP', today_str, seed=seed)
    return f'PP-{today_str}-{next_seq:04d}'
```

（保留原 docstring 的跳号语义说明；`from contextlib import suppress` 若不再使用则删。）

- [ ] **Step 6: 同步两处 monkeypatch fake 签名**

- `fastapi_app/tests/test_numbering_batch.py:31`：`async def fake_daily_max(db, model, number_field, date_str):`（`:35` setattr 不变）
- `docs/tickets/tools/verify_iter2_numbering.py:100`：同上改 4 参。

- [ ] **Step 7: 跑全部编号相关测试**

Run: `PYTHONUTF8=1 command python -m pytest tests/test_numbering_unified.py fastapi_app/tests/test_numbering_batch.py fastapi_app/tests/test_numbering.py tests/test_numbering_sequence_integration.py -q 2>&1 | command tail -4`
Expected: PASS（`test_numbering.py` 若因 mock 签名需同步 patch 目标——`patch('fastapi_app.services.numbering.generate_number_async')` 不受影响——见失败详情再微调）。

- [ ] **Step 8: 提交**

```bash
command git add fastapi_app/services/numbering_sequence.py fastapi_app/services/numbering.py fastapi_app/services/purchase_plan_common.py fastapi_app/tests/test_numbering_batch.py tests/test_numbering_unified.py docs/tickets/tools/verify_iter2_numbering.py
command git commit -m "fix(numbering): read_daily_max 改数值排序+编号日期段过滤+正则守卫，根除 9999 字典序缺陷"
```

---

### Task 5: 批量导入改异步 + 删 stock_crud_service（消灭双水位）

**Files:**
- Modify: `fastapi_app/tasks/batch_tasks.py`（全文重写行循环）
- Delete: `fastapi_app/shared/stock_crud_service.py`
- Modify: `scripts/concurrency_stress_test.py`（重写取号调用）
- Modify: `mypy.ini:49`
- Test: `fastapi_app/tests/test_batch_tasks_semantics.py`（新建）

**Interfaces:**
- Consumes: `generate_order_number(db)` / `generate_stockin_number(db)`（Task 4 后的 4 参签名）、`parse_excel_file_async`（`fastapi_app/services/batch_import_parser.py:32`，既有）、`require_async_session_local()`（既有）。
- Produces: `async _run_batch_import_async(file_path, job_id, task_label, build_row) -> dict`；`build_row` 为 `async def(db, row, i) -> str | None`（Task 6 无新增依赖）。

- [ ] **Step 1: 写失败测试（语义保真逐条断言）**

`fastapi_app/tests/test_batch_tasks_semantics.py`（新建；不连真实库——`_run_batch_import_async` 与解析全部打桩，只验行循环语义）：

```python
"""批量导入异步骨架的语义保真测试（spec §4.2：逐字保留 batch_tasks 原语义）。

全部打桩：Excel 解析返回固定行，async session 用 MagicMock 记录
commit/rollback 调用序。验证目标不是数据落库，而是：
50 行批量提交 / 行级失败 continue / 异常批回滚计数 skipped_uncommitted /
抛出时保留文件（delete_file=False）。
"""
from unittest import mock

import pytest

import fastapi_app.tasks.batch_tasks as bt


def _row(i: int) -> dict:
    return {'产品名称': f'P{i}', '客户名称': 'c', '数量': 1}


class _SessionRecorder:
    def __init__(self):
        self.commits = 0
        self.rollbacks = 0

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


@pytest.mark.asyncio
async def test_fifty_row_batch_commit_semantics(monkeypatch, tmp_path):
    rows = [_row(i) for i in range(110)]
    monkeypatch.setattr(bt, '_parse_rows_async', mock.AsyncMock(return_value=(True, rows, '')))
    session = _SessionRecorder()
    monkeypatch.setattr(bt, '_open_import_session', mock.AsyncMock(return_value=session))
    build = mock.AsyncMock(return_value=None)

    result = await bt._run_batch_import_async(str(tmp_path / 'f.xlsx'), 'job', '订单', build)

    # 110 行 = 2 次满批提交 + 尾批；imported_count 按行计
    assert result['imported_count'] == 110
    assert build.await_count == 110
    assert session.commits >= 3          # 50+50+尾批10
    assert session.rollbacks == 0
    assert result['errors'] == []


@pytest.mark.asyncio
async def test_row_level_error_continues_without_rollback(monkeypatch, tmp_path):
    rows = [_row(0), _row(1), _row(2)]
    monkeypatch.setattr(bt, '_parse_rows_async', mock.AsyncMock(return_value=(True, rows, '')))
    session = _SessionRecorder()
    monkeypatch.setattr(bt, '_open_import_session', mock.AsyncMock(return_value=session))
    build = mock.AsyncMock(side_effect=[None, '产品不存在', None])

    result = await bt._run_batch_import_async(str(tmp_path / 'f.xlsx'), 'job', '订单', build)

    assert result['imported_count'] == 2   # 第 2 行失败，1、3 行照常
    assert result['errors'] == [{'row': 3, 'error': '产品不存在'}]
    assert session.rollbacks == 0


@pytest.mark.asyncio
async def test_exception_rolls_back_batch_and_counts_skipped(monkeypatch, tmp_path):
    rows = [_row(0), _row(1), _row(2)]
    monkeypatch.setattr(bt, '_parse_rows_async', mock.AsyncMock(return_value=(True, rows, '')))
    session = _SessionRecorder()
    monkeypatch.setattr(bt, '_open_import_session', mock.AsyncMock(return_value=session))
    build = mock.AsyncMock(side_effect=[None, ValueError('boom'), None])

    result = await bt._run_batch_import_async(str(tmp_path / 'f.xlsx'), 'job', '订单', build)

    assert result['imported_count'] == 1   # 已提交 1 行（行号 2 前无满批）
    assert session.rollbacks == 1
    assert result['errors'][0]['skipped_uncommitted'] == 1  # 行 2 失败时未提交的 1 行被跳过


@pytest.mark.asyncio
async def test_parse_failure_short_circuits(monkeypatch, tmp_path):
    monkeypatch.setattr(bt, '_parse_rows_async', mock.AsyncMock(return_value=(False, [], 'Excel 文件为空')))
    build = mock.AsyncMock()
    result = await bt._run_batch_import_async(str(tmp_path / 'f.xlsx'), 'job', '订单', build)
    assert result == {'success': False, 'error': 'Excel 文件为空', 'imported_count': 0, 'task_id': 'job'}
    build.assert_not_awaited()
```

（`_parse_rows_async` 与 `_open_import_session` 是本任务在 batch_tasks.py 内新拆的两个可桩点——见 Step 3 结构；桩点必须真实存在于实现里，测试才有意义。）

- [ ] **Step 2: 跑测试确认失败**

Run: `PYTHONUTF8=1 command python -m pytest fastapi_app/tests/test_batch_tasks_semantics.py -v`
Expected: FAIL — `AttributeError: module 'fastapi_app.tasks.batch_tasks' has no attribute '_run_batch_import_async'`

- [ ] **Step 3: 重写 `batch_tasks.py`**

保留：`ALLOWED_UPLOAD_DIRS`、`_is_allowed_upload_path`、`_resolve_row_product`（改 async）。删除：`_SyncSession`、`get_sync_engine` 导入、`_run_batch_import_sync`。新结构（关键代码全文）：

```python
"""批量导入异步任务

Excel 批量导入耗时操作由 ARQ Worker 执行。行循环使用异步会话
（numbering_counter 原子取号，spec 2026-09-29 订单号统一 §4.2）。
"""
import asyncio
import contextlib
import os
import tempfile

from sqlalchemy import or_, select as sa_select

from fastapi_app.core.logger import logger
from fastapi_app.shared_models import Product
from fastapi_app.shared_models.order import ORDER_STATUS_PENDING_STOCK

ALLOWED_UPLOAD_DIRS = [...]  # 原样保留


def _is_allowed_upload_path(file_path: str) -> bool:  # 原样保留
    ...


async def _parse_rows_async(file_path: str) -> tuple[bool, list, str]:
    """解析 Excel（阻塞解析仍在 executor 里跑，不阻塞 worker 事件循环）。"""
    from fastapi_app.services.batch_import_parser import parse_excel_file_async

    return await parse_excel_file_async(file_path)


async def _open_import_session():
    from fastapi_app.core.database import require_async_session_local

    return require_async_session_local()()


async def _resolve_product_locked(db, product_identifier: str) -> Product | None:
    result = await db.execute(
        sa_select(Product).where(
            or_(Product.name == product_identifier, Product.barcode == product_identifier)
        ).with_for_update()
    )
    return result.scalar_one_or_none()


async def _resolve_row_product(db, row: dict) -> tuple[Product | None, str | None]:
    product_identifier = row.get('产品名称', row.get('产品编号', ''))
    customer = row.get('客户名称', '')
    quantity = row.get('数量', 0)
    if not all([product_identifier, customer, quantity]):
        return None, '缺少必填字段'
    product = await _resolve_product_locked(db, product_identifier)
    if not product:
        return None, f"产品 '{product_identifier}' 不存在"
    return product, None


async def _run_batch_import_async(file_path: str, job_id: str, task_label: str, build_row) -> dict:
    """订单/备货批量导入共享骨架（异步版）。

    语义与同步版逐字一致（50 行一批提交 / 行级失败 continue /
    ValueError/TypeError/OSError 回滚当前未提交批并计 skipped_uncommitted /
    抛出时保留文件供重试）。
    """
    real_path = os.path.realpath(file_path)
    if not any(os.path.commonpath([real_path, d]) == d for d in ALLOWED_UPLOAD_DIRS if os.path.exists(d)):
        logger.error(f'批量导入{task_label}任务拒绝非法文件路径: {file_path}')
        return {'success': False, 'error': '非法文件路径', 'imported_count': 0, 'task_id': job_id}
    delete_file = True
    try:
        success, data_list, error = await _parse_rows_async(file_path)
        if not success:
            return {'success': False, 'error': error, 'imported_count': 0, 'task_id': job_id}
        db = await _open_import_session()
        try:
            imported_count = 0
            last_committed_count = 0
            errors = []
            BATCH_COMMIT_SIZE = 50
            for i, row in enumerate(data_list, start=2):
                try:
                    row_error = await build_row(db, row, i)
                except (ValueError, TypeError, OSError) as e:
                    await db.rollback()
                    uncommitted_in_batch = imported_count - last_committed_count
                    imported_count = last_committed_count
                    errors.append({'row': i, 'error': str(e), 'skipped_uncommitted': uncommitted_in_batch})
                    logger.error(f'批量导入{task_label}行{i}失败: {e}')
                    continue
                if row_error:
                    errors.append({'row': i, 'error': row_error})
                    continue
                imported_count += 1
                if imported_count % BATCH_COMMIT_SIZE == 0:
                    await db.commit()
                    last_committed_count = imported_count
            await db.commit()
            return {'success': True, 'imported_count': imported_count, 'errors': errors, 'task_id': job_id}
        finally:
            await db.close()
    except (ValueError, TypeError, OSError) as exc:
        logger.error(f'批量导入{task_label}任务失败: {exc}', exc_info=True)
        delete_file = False
        raise exc
    finally:
        if delete_file and file_path and os.path.exists(file_path):
            with contextlib.suppress(OSError):
                os.unlink(file_path)


async def batch_import_orders_task(ctx, file_path: str, original_filename: str, user_id: int):
    job_id = ctx['job_id']

    async def _orders_row(db, row: dict, i: int) -> str | None:
        from datetime import UTC, datetime

        from fastapi_app.services.numbering import generate_order_number
        from fastapi_app.shared_models import InventoryLog, Order
        product, row_error = await _resolve_row_product(db, row)
        if row_error:
            return row_error
        order = Order(
            order_no=await generate_order_number(db),
            product_id=product.id, customer=row.get('客户名称', ''),
            quantity=int(row.get('数量', 0)),
            order_date=datetime.now(UTC),  # aware UTC：order_date 为 timestamptz
            status=ORDER_STATUS_PENDING_STOCK, note=row.get('备注', ''))
        db.add(order)
        await db.flush()
        log = InventoryLog(product_id=product.id, change_type='订单创建',
                           change_quantity=int(row.get('数量', 0)),
                           change_date=datetime.now(UTC), customer=row.get('客户名称', ''),
                           related_id=str(order.id), note=f'批量导入订单 {order.order_no}')
        db.add(log)
        return None

    return await _run_batch_import_async(file_path, job_id, '订单', _orders_row)


async def batch_import_stockins_task(ctx, file_path: str, original_filename: str, user_id: int):
    job_id = ctx['job_id']

    async def _stockins_row(db, row: dict, i: int) -> str | None:
        from datetime import UTC, datetime

        from fastapi_app.services.numbering import generate_stockin_number
        from fastapi_app.shared_models import InventoryLog, StockIn
        product, row_error = await _resolve_row_product(db, row)
        if row_error:
            return row_error
        quantity = int(row.get('数量', 0))
        stockin = StockIn(
            stockin_no=await generate_stockin_number(db),
            product_id=product.id, customer=row.get('客户名称', ''),
            quantity=quantity, stockin_date=datetime.now(UTC),
            note=row.get('备注', ''))
        db.add(stockin)
        await db.flush()
        product.current_stock += quantity
        log = InventoryLog(product_id=product.id, change_type='备货入库',
                           change_quantity=quantity, change_date=datetime.now(UTC),
                           customer=row.get('客户名称', ''), related_id=str(stockin.id),
                           note=f'批量导入备货 {stockin.stockin_no}')
        db.add(log)
        return None

    return await _run_batch_import_async(file_path, job_id, '备货', _stockins_row)
```

`asyncio` 导入仅在 `batch_import_*_task` 不再需要 `to_thread` 后删除（若文件内无其他使用）。

- [ ] **Step 4: 跑语义测试确认通过**

Run: `PYTHONUTF8=1 command python -m pytest fastapi_app/tests/test_batch_tasks_semantics.py -v`
Expected: PASS（4 个用例）

- [ ] **Step 5: 删 `stock_crud_service.py` 并同步引用（同提交）**

```bash
command git rm fastapi_app/shared/stock_crud_service.py
```

- `mypy.ini:49` 删除 `fastapi_app/shared/stock_crud_service.py,` 行。
- 全仓复核实无导入残留：`command grep -rn "stock_crud_service" --include=*.py . | command grep -v "^./.archive/" | command grep -v test_` → 期望空。

- [ ] **Step 6: 重写压测脚本取号调用**

`scripts/concurrency_stress_test.py`：删除 `from fastapi_app.core.number_generator import AsyncNumberGenerator`（`:28`）与 `generator.generate(...)` 调用（`:61,69,114`），改调：

```python
from fastapi_app.services.numbering import generate_number_async
number = await generate_number_async('PO', Order, 'order_no', db)
```

（非生产脚本，只求可运行、口径正确。）

- [ ] **Step 7: 全量编号/批量回归**

Run: `PYTHONUTF8=1 command python -m pytest fastapi_app/tests -k "numbering or batch" -q 2>&1 | command tail -4; PYTHONUTF8=1 command python -c "import fastapi_app.tasks.batch_tasks; import fastapi_app.core.arq_app; print('import ok')"`
Expected: 测试 PASS；导入 OK（ARQ functions 列表引用 `batch_import_orders_task` 等名字，导入成功即注册不破）。

- [ ] **Step 8: 提交**

```bash
command git add fastapi_app/tasks/batch_tasks.py fastapi_app/tests/test_batch_tasks_semantics.py mypy.ini scripts/concurrency_stress_test.py
command git commit -m "refactor(batch): 批量导入改异步取号——消灭双水位，numbering_counter 成为唯一水位源"
```

（`git rm` 的 stock_crud_service 已在暂存区，随本提交一起进。）

---

### Task 6: 统一北京口径 + 删 core/number_generator + 启动对账

**Files:**
- Modify: `fastapi_app/services/numbering_sequence.py`（新增 `business_date_str`）
- Modify: `fastapi_app/services/numbering.py`（删 AsyncNumberGenerator / re-export；日期段换 business_date_str；模块级 asyncio.Lock）
- Modify: `fastapi_app/services/stock_return_service.py:21,32`（SR 改调 services/numbering）
- Modify: `fastapi_app/services/purchase_plan_common.py`（today_str 换 business_date_str）
- Modify: `fastapi_app/tasks/batch_tasks.py`（无——Task 5 后取号已走 services，日期口径自动随内核切换）
- Delete: `fastapi_app/core/number_generator.py`
- Modify: `requirements/base.txt`（加 tzdata）
- Create: `fastapi_app/services/numbering_reconcile.py`（启动对账）
- Modify: `fastapi_app/main.py:141` 附近（lifespan 调对账）
- Test: `tests/test_numbering_unified.py`（追加）；`tests/test_numbering_reconcile.py`（新建）

**Interfaces:**
- Consumes: `number_lock_key(scope, key)`（Task 1）；`read_daily_max`（Task 4 新签名）。
- Produces: `business_date_str() -> str`（全系统编号日期段唯一来源）；`async reconcile_numbering_counters(db) -> dict`（lifespan 调用；Task 7 巡检复用其扫描逻辑思想但独立实现）。

- [ ] **Step 1: 写失败测试（口径 + 对账幂等）**

追加到 `tests/test_numbering_unified.py`：

```python
@pytest.mark.asyncio
async def test_business_date_str_beijing_boundary(monkeypatch):
    # UTC 16:30 = 北京 00:30（次日）——冻结时钟验证口径
    from datetime import datetime as _dt
    from unittest import mock

    import fastapi_app.services.numbering_sequence as ns

    class _Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            base = _dt(2026, 9, 29, 16, 30, tzinfo=UTC)
            return base.astimezone(tz) if tz else base.replace(tzinfo=None)

    monkeypatch.setattr(ns, 'datetime', _Frozen)
    assert ns.business_date_str() == '20260930'  # 北京已过午夜


@pytest.mark.asyncio
async def test_generated_number_uses_beijing_date_segment(db, monkeypatch):
    from fastapi_app.services import numbering

    async def _no_seed(db_, model, field, date_str):
        return 0

    monkeypatch.setattr(numbering, 'read_daily_max', _no_seed)
    monkeypatch.setattr(numbering, 'allocate_sequence', mock.AsyncMock(return_value=1))
    number = await numbering.generate_number_async('PO', Order, 'order_no', db)
    assert number.startswith('PO-2026') and number.endswith('-0001')
```

新建 `tests/test_numbering_reconcile.py`：

```python
"""启动对账：GREATEST 只升不降、补插缺行、幂等（spec §5）。"""
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from fastapi_app.services.numbering_reconcile import reconcile_numbering_counters
from fastapi_app.shared_models import NumberingCounter, Order


@pytest.mark.asyncio
async def test_reconcile_raises_watermark_and_inserts_missing(db):
    db.add(Order(order_no='PO-20260929-0007', customer='c', quantity=1,
                 order_date=datetime(2026, 9, 29, tzinfo=UTC)))
    await db.flush()

    result = await reconcile_numbering_counters(db)

    row = (await db.execute(
        select(NumberingCounter).where(
            NumberingCounter.prefix == 'PO', NumberingCounter.number_date == '20260929'))).scalar_one()
    assert row.last_seq >= 7          # GREATEST 只升不降
    assert result['raised'] >= 1 or result['inserted'] >= 1


@pytest.mark.asyncio
async def test_reconcile_never_lowers_watermark(db):
    db.add(NumberingCounter(prefix='PO', number_date='20260929', last_seq=99))
    await db.flush()
    await reconcile_numbering_counters(db)
    row = (await db.execute(
        select(NumberingCounter).where(
            NumberingCounter.prefix == 'PO', NumberingCounter.number_date == '20260929'))).scalar_one()
    assert row.last_seq == 99         # 数据 max=0 也不降


@pytest.mark.asyncio
async def test_reconcile_is_idempotent(db):
    db.add(Order(order_no='PO-20260929-0007', customer='c', quantity=1,
                 order_date=datetime(2026, 9, 29, tzinfo=UTC)))
    await db.flush()
    first = await reconcile_numbering_counters(db)
    second = await reconcile_numbering_counters(db)
    assert second['raised'] == 0 and second['inserted'] == 0   # 第二次无变化
```

- [ ] **Step 2: 跑测试确认失败**

Run: `PYTHONUTF8=1 command python -m pytest tests/test_numbering_unified.py tests/test_numbering_reconcile.py -q 2>&1 | command tail -4`
Expected: FAIL — `AttributeError: ... no attribute 'business_date_str'` / `No module named 'numbering_reconcile'`

- [ ] **Step 3: 实现 `business_date_str` 与内核切换**

`fastapi_app/services/numbering_sequence.py`：

```python
from zoneinfo import ZoneInfo

_BUSINESS_TZ = ZoneInfo('Asia/Shanghai')


def business_date_str() -> str:
    """业务口径（北京时间）的 YYYYMMDD —— 编号日期段的唯一来源（spec §4.1）。"""
    return datetime.now(_BUSINESS_TZ).strftime('%Y%m%d')
```

`fastapi_app/services/numbering.py`：

- `:93`、`:142` 的 `datetime.now(UTC).strftime('%Y%m%d')` → `business_date_str()`（import 自 numbering_sequence）。
- 删除 `AsyncNumberGenerator` 类（`:45-70`）与 `_async_number_generator` 实例，行内锁改为模块级：

```python
_allocate_lock = asyncio.Lock()


async def generate_number_async(prefix: str, model, number_field: str, db: AsyncSession) -> str:
    date_str = business_date_str()
    async with _allocate_lock:
        db_max = await read_daily_max(db, model, number_field, date_str)
        current_seq = await allocate_sequence(prefix, date_str, seed=db_max)
        return '-'.join((prefix, date_str, str(current_seq).zfill(4)))
```

（`generate_number_batch` 同构改法。）

- 删除 `:26-30` 对 `core.number_generator` 的 re-export 块；模块 docstring 删「UTC 时间」「与 core/number_generator 的区别」段，改述为「北京口径、单一水位源」。
- `services/stock_return_service.py:21,32`：删 `from fastapi_app.core.number_generator import generate_number_async`，改 `from fastapi_app.services.numbering import generate_number_async`，调用改 4 参 `generate_number_async('SR', StockReturn, 'return_no', db)`。
- `services/purchase_plan_common.py`：`today_str = datetime.now(UTC).strftime('%Y%m%d')` → `business_date_str()`。
- `requirements/base.txt` 在 `python-dotenv==1.2.2` 行后加 `tzdata>=2025.1`（带注释 `# Windows 无系统 tz 库，ZoneInfo('Asia/Shanghai') 依赖此包（编号北京口径）`）。

- [ ] **Step 4: 删 `core/number_generator.py`（同提交）**

```bash
command git rm fastapi_app/core/number_generator.py
```

复核实无导入残留：

Run: `command grep -rn "core.number_generator\|core import number_generator" --include=*.py . | command grep -v "^./.archive/" | command grep -v "/tests/\|test_"`
Expected: 空（Task 5 已迁移 batch_tasks 与压测脚本；case/commands.py 在 Task 1 已切 pg_locks）。

- [ ] **Step 5: 实现启动对账**

`fastapi_app/services/numbering_reconcile.py`（新建）：

```python
"""部署对账：numbering_counter 水位 GREATEST(水位, 数据max)，只升不降。

关闭 spec §5 的同日键碰撞窗口：日期段从 UTC 切北京当天，两条路径共用同一
日期字符串而 seed 分支被忽略——若 data_max > last_seq，后续取号会连续撞
唯一索引。对账在 FastAPI lifespan 幂等执行；4 个 worker 并发触发由
advisory lock 串行化（GREATEST 语义本身安全，锁防交错报错）。
"""
import logging
from datetime import UTC, datetime

from sqlalchemy import BigInteger, func, insert, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.pg_locks import acquire_advisory_lock_async, number_lock_key

logger = logging.getLogger(__name__)

# (prefix, model 表名, 编号列名) —— 覆盖全部生成类编号实体（spec §4.5 前缀表）
_NUMBERED_ENTITIES = [
    ('PO', 'order', 'order_no'),
    ('CG', 'purchase_order', 'order_no'),
    ('BH', 'stock_in', 'stockin_no'),
    ('SO', 'stock_out', 'stockout_no'),
    ('CSO', 'case_stock_out', 'stockout_no'),
    ('CSI', 'case_stock_in', 'stockin_no'),
    ('CS', 'customer_sampling_project', 'sequence_no'),
    ('FH', 'outsource_shipment', 'shipment_no'),
    ('SR', 'stock_return', 'return_no'),
    ('PP', 'purchase_plans', 'plan_no'),
]

_RECONCILE_LOCK = number_lock_key('NUMBERING_RECONCILE', 'startup')


async def reconcile_numbering_counters(db: AsyncSession) -> dict:
    """对账并提交。返回 {'raised': n, 'inserted': n}。幂等：重复执行无变化。"""
    await acquire_advisory_lock_async(db, _RECONCILE_LOCK)
    raised = inserted = 0
    for prefix, table, column in _NUMBERED_ENTITIES:
        col = text(f'"{column}"')
        seq = func.cast(func.split_part(col, '-', 3), BigInteger)
        rows = (await db.execute(
            text(
                f'SELECT split_part("{column}", \'-\', 2) AS number_date, '
                f'MAX(CAST(split_part("{column}", \'-\', 3) AS BIGINT)) AS mx '
                f'FROM "{table}" '
                f'WHERE "{column}" ~ \'^[A-Z]+-[0-9]{{8}}-[0-9]+$\' '
                f'GROUP BY 1'
            )
        )).fetchall()
        for number_date, mx in rows:
            existing = (await db.execute(
                select(func.now()).where(text(
                    f"prefix = '{prefix}' AND number_date = '{number_date}'"
                ))
            )).scalar()  # placeholder —— 见下方真实实现说明
    return {'raised': raised, 'inserted': inserted}
```

**实现说明（执行者按此落地，不要照抄上面的伪段）**：真实实现用一条核心 SQL（对齐 spec §5 草案、参数化表名/列名拼接安全因值全部来自上面白名单常量）：

```python
async def reconcile_numbering_counters(db: AsyncSession) -> dict:
    await acquire_advisory_lock_async(db, _RECONCILE_LOCK)
    raised = inserted = 0
    for prefix, table, column in _NUMBERED_ENTITIES:
        sql = text(
            f'SELECT split_part("{column}", \'-\', 2) AS number_date, '
            f'CAST(MAX(CAST(split_part("{column}", \'-\', 3) AS BIGINT)) AS INTEGER) AS mx '
            f'FROM "{table}" '
            f'WHERE "{column}" ~ \'^[A-Z]+-[0-9]{{8}}-[0-9]+$\' '
            f'GROUP BY 1'
        )
        for number_date, mx in (await db.execute(sql)).fetchall():
            upd = text(
                'UPDATE numbering_counter SET last_seq = GREATEST(last_seq, :mx), '
                'updated_at = now() WHERE prefix = :p AND number_date = :d'
            )
            res = (await db.execute(upd, {'mx': mx, 'p': prefix, 'd': number_date})).rowcount
            if res == 0:
                await db.execute(
                    text('INSERT INTO numbering_counter (prefix, number_date, last_seq, updated_at) '
                         'VALUES (:p, :d, :mx, now())'),
                    {'p': prefix, 'd': number_date, 'mx': mx},
                )
                inserted += 1
            elif res == 1:
                raised += 1
    await db.commit()
    return {'raised': raised, 'inserted': inserted}
```

（`res == 1` 仅在确实发生 GREATEST 抬升时计——注意 UPDATE rowcount 在值未变时也为 1，幂等断言 `second['raised'] == 0` 会红；正确做法是先 SELECT 当前值、比较后再 UPDATE，或把断言放宽为「第二次调用后表内容不变」。**执行者选择：先 SELECT 后比对再 UPDATE**，保证 `raised` 语义精确为「实际抬升的行数」。）

`fastapi_app/main.py` lifespan（`:141` `await _setup_database()` 之后）插入：

```python
    # 编号水位对账（spec 2026-09-29 §5）：GREATEST 只升不降，幂等，失败不阻断启动
    try:
        from fastapi_app.core.database import get_async_session_local
        from fastapi_app.services.numbering_reconcile import reconcile_numbering_counters
        async with get_async_session_local()() as recon_db:
            result = await reconcile_numbering_counters(recon_db)
        if result['raised'] or result['inserted']:
            logger.info('编号水位对账: 抬升 %d 行, 补插 %d 行', result['raised'], result['inserted'])
    except Exception as e:  # defensive: 对账失败不得阻断应用启动
        logger.warning('编号水位启动对账失败（不影响启动）: %s', e)
```

（`get_async_session_local` 的真实名字先 `command grep -n "session_local\|def get_async" fastapi_app/core/database.py` 确认——numbering_sequence.py:45 用的是 `require_async_session_local()`，lifespan 侧沿用同一个。）

- [ ] **Step 6: 跑口径与对账测试**

Run: `PYTHONUTF8=1 command python -m pytest tests/test_numbering_unified.py tests/test_numbering_reconcile.py -q 2>&1 | command tail -4`
Expected: PASS

- [ ] **Step 7: 全量回归（编号/批量/订单/采购计划）**

Run: `PYTHONUTF8=1 command python -m pytest fastapi_app/tests -k "numbering or batch or purchase_plan or stock_return" -q 2>&1 | command tail -4; PYTHONUTF8=1 command python -c "import fastapi_app.main; print('app import ok')"`
Expected: PASS；app 导入 OK（lifespan 内 lazy import，导入期不触发对账）。

- [ ] **Step 8: 提交**

```bash
command git add fastapi_app/services/numbering_sequence.py fastapi_app/services/numbering.py fastapi_app/services/stock_return_service.py fastapi_app/services/purchase_plan_common.py fastapi_app/services/numbering_reconcile.py fastapi_app/main.py requirements/base.txt tests/test_numbering_unified.py tests/test_numbering_reconcile.py
command git commit -m "feat(numbering): 统一北京口径+单一取号内核+启动对账，删除 core/number_generator"
```

（`git rm` 的 core/number_generator.py 已在暂存区，随本提交进。）

---

### Task 7: 编号巡检（落库 + 端点暴露）

**Files:**
- Create: `fastapi_app/shared_models/numbering_audit.py`
- Modify: `fastapi_app/shared_models/__init__.py`（导出）
- Create: `fastapi_app/tasks/numbering_audit_task.py`
- Modify: `fastapi_app/core/arq_app.py`（cron + functions 注册）
- Create: `fastapi_app/api/v1/endpoints/numbering_audit.py`（只读端点）
- Modify: `fastapi_app/api/v1/endpoints/__init__.py` 或路由注册处（按既有模式）
- Test: `tests/test_numbering_audit.py`

**Interfaces:**
- Consumes: `_NUMBERED_ENTITIES` 常量（Task 6 的 `numbering_reconcile.py`，import 复用）；`business_date_str()`。
- Produces: `NumberingAudit` ORM 模型（表 `numbering_audit`）；ARQ 任务 `numbering_audit_task(ctx)`；端点 `GET /api/v1/numbering-audit`（返回最近一轮巡检 JSON）。

- [ ] **Step 1: 写失败测试**

`tests/test_numbering_audit.py`：

```python
"""编号巡检：counter_behind 只对反向偏差报警，正向跳号不报（spec §4.5）。"""
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from fastapi_app.tasks.numbering_audit_task import compute_audit
from fastapi_app.shared_models import NumberingAudit, NumberingCounter, Order


@pytest.mark.asyncio
async def test_behind_reported(db):
    # 数据 max=7 > 水位 3 → behind
    db.add_all([
        Order(order_no='PO-20260929-0007', customer='c', quantity=1,
              order_date=datetime(2026, 9, 29, tzinfo=UTC)),
        NumberingCounter(prefix='PO', number_date='20260929', last_seq=3),
    ])
    await db.flush()
    report = await compute_audit(db)
    po = next(r for r in report['prefixes'] if r['prefix'] == 'PO')
    assert po['counter_behind'] is True


@pytest.mark.asyncio
async def test_ahead_is_not_reported(db):
    # 水位 45 > 数据 max=1（跳号/删除正常态）→ 不报
    db.add_all([
        Order(order_no='PO-20260929-0001', customer='c', quantity=1,
              order_date=datetime(2026, 9, 29, tzinfo=UTC)),
        NumberingCounter(prefix='PO', number_date='20260929', last_seq=45),
    ])
    await db.flush()
    report = await compute_audit(db)
    po = next(r for r in report['prefixes'] if r['prefix'] == 'PO')
    assert po['counter_behind'] is False


@pytest.mark.asyncio
async def test_format_violation_reported(db):
    db.add(Order(order_no='PO-PENDING-42', customer='c', quantity=1,
                 order_date=datetime(2026, 9, 29, tzinfo=UTC)))
    await db.flush()
    report = await compute_audit(db)
    assert any(v['table'] == 'order' for v in report['violations'])
```

- [ ] **Step 2: 跑测试确认失败**

Run: `PYTHONUTF8=1 command python -m pytest tests/test_numbering_audit.py -v`
Expected: FAIL — `ModuleNotFoundError: fastapi_app.tasks.numbering_audit_task`

- [ ] **Step 3: 实现模型、任务、端点**

`fastapi_app/shared_models/numbering_audit.py`（参照 `numbering_counter.py` 的声明式风格）：

```python
"""编号巡检结果（拉取式暴露：ARQ 周期计算，端点读取，spec §4.5）。"""
from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from fastapi_app.shared_models import Base


class NumberingAudit(Base):
    __tablename__ = 'numbering_audit'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scope: Mapped[str] = mapped_column(String(64), nullable=False, comment='PO/BH/... 或 order.order_no')
    counter_behind: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment='1=水位落后数据')
    detail: Mapped[str] = mapped_column(String(255), nullable=False, default='', comment='偏差描述')
    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, comment='巡检时间')
```

`fastapi_app/tasks/numbering_audit_task.py`：

```python
"""编号不变量巡检（ARQ cron）：counter_behind 与 format_violations 落库。

只对反向偏差（数据号 > 水位）记录 behind；正向跳号（删除/回滚）是文档化
的正常语义（spec §4.5 重要设计约束）。
"""
import logging
from datetime import UTC, datetime

from sqlalchemy import BigInteger, func, select, text

from fastapi_app.core.database import require_async_session_local
from fastapi_app.services.numbering_reconcile import _NUMBERED_ENTITIES
from fastapi_app.services.numbering_sequence import business_date_str
from fastapi_app.shared_models import NumberingAudit, NumberingCounter

logger = logging.getLogger(__name__)


async def compute_audit(db) -> dict:
    """计算一轮巡检结果（不落库；测试直接调用）。"""
    today = business_date_str()
    prefixes, violations = [], []
    for prefix, table, column in _NUMBERED_ENTITIES:
        seq = func.cast(func.split_part(text(f'"{column}"'), '-', 3), BigInteger)
        data_max = (await db.execute(
            text(f'SELECT COALESCE(MAX(CAST(split_part("{column}", \'-\', 3) AS BIGINT)), 0) '
                 f'FROM "{table}" '
                 f'WHERE "{column}" ~ \'^[A-Z]+-[0-9]{{8}}-[0-9]+$\' '
                 f'AND split_part("{column}", \'-\', 2) = \'{today}\'')
        )).scalar() or 0
        counter = (await db.execute(
            select(NumberingCounter.last_seq).where(
                NumberingCounter.prefix == prefix,
                NumberingCounter.number_date == today)
        )).scalar()
        behind = counter is not None and data_max > counter
        # 缺行不算 behind：新键首用前计数行不存在是正常态，seed 机制兜底
        prefixes.append({'prefix': prefix, 'data_max': int(data_max),
                         'counter': counter, 'counter_behind': behind})
        bad = (await db.execute(
            text(f'SELECT COUNT(*) FROM "{table}" '
                 f'WHERE "{column}" !~ \'^[A-Z]+-[0-9]{{8}}-[0-9]+$\'')
        )).scalar() or 0
        if bad:
            violations.append({'table': table, 'column': column, 'count': int(bad)})
    return {'checked_at': datetime.now(UTC).isoformat(), 'prefixes': prefixes,
            'violations': violations}


async def numbering_audit_task(ctx) -> dict:
    """ARQ cron 入口：计算并落库。"""
    session_factory = require_async_session_local()
    async with session_factory() as db:
        report = await compute_audit(db)
        db.add_all([
            NumberingAudit(scope=p['prefix'], counter_behind=1 if p['counter_behind'] else 0,
                           detail=f"data_max={p['data_max']} counter={p['counter']}",
                           checked_at=datetime.now(UTC))
            for p in report['prefixes']
        ] + [
            NumberingAudit(scope=f'{v["table"]}.{v["column"]}', counter_behind=0,
                           detail=f'format violations={v["count"]}', checked_at=datetime.now(UTC))
            for v in report['violations']
        ])
        await db.commit()
    return report
```

`fastapi_app/core/arq_app.py`：`functions` 列表加 `numbering_audit_task`（import 自 `fastapi_app.tasks.numbering_audit_task`）；`cron_schedules` 加：

```python
    {
        'func': numbering_audit_task,
        'name': 'numbering_audit',
        'cron': {'minute': set(range(0, 60, 10))},   # 每 10 分钟
        'timeout': 60,
    },
```

端点 `fastapi_app/api/v1/endpoints/numbering_audit.py`（只读，参照既有 endpoint 的鉴权与响应风格——先看一个最简端点如 `fastapi_app/api/v1/endpoints/health.py` 的模式）：

```python
"""编号巡检只读端点（spec §4.5 拉取式暴露）。"""
from fastapi_app.core.database import get_db
from fastapi_app.shared_models import NumberingAudit

router = APIRouter(prefix='/numbering-audit', tags=['numbering'])


@router.get('')
async def latest_audit(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(
        select(NumberingAudit).order_by(NumberingAudit.checked_at.desc()).limit(200)
    )).scalars().all()
    return {
        'items': [
            {'scope': r.scope, 'counter_behind': bool(r.counter_behind),
             'detail': r.detail, 'checked_at': r.checked_at.isoformat()}
            for r in rows
        ]
    }
```

（路由注册：找到既有 router 挂载点 `command grep -n "include_router" fastapi_app/api/v1/__init__.py fastapi_app/main.py`，按同模式追加。鉴权策略对齐同目录相邻端点——执行者先读一个带鉴权的端点确认 dependency 写法。）

- [ ] **Step 4: 跑巡检测试**

Run: `PYTHONUTF8=1 command python -m pytest tests/test_numbering_audit.py -v`
Expected: PASS（3 个用例）

- [ ] **Step 5: 提交**

```bash
command git add fastapi_app/shared_models/numbering_audit.py fastapi_app/shared_models/__init__.py fastapi_app/tasks/numbering_audit_task.py fastapi_app/core/arq_app.py fastapi_app/api/v1/endpoints/numbering_audit.py tests/test_numbering_audit.py
command git commit -m "feat(numbering): 巡检落库+只读端点——反向偏差与格式违规可见，正向跳号不报"
```

（若 router 注册在 api/v1/__init__.py，一并 add。**注意**：新表 `numbering_audit` 需要建表——生产用 alembic 迁移；测试库由 conftest 建表。执行者在 Step 3 后补一条 alembic 迁移 `pg_standalone_059_numbering_audit.py`（`op.create_table` 参照 pg_standalone_034 的写法，down 为 drop_table），纳入本提交。）

---

### Task 8: 存量核验（复跑审计脚本）

**Files:**
- 无代码改动（验证任务）

**Interfaces:**
- Consumes: `_audit_order_no.py`（根目录既有探针脚本）；Tasks 1-7 全部产出。
- Produces: 核验结论（写入本任务提交的信息或 PR 描述）。

- [ ] **Step 1: 跑编号测试全集**

Run: `PYTHONUTF8=1 command python -m pytest fastapi_app/tests -k "numbering or batch or pg_locks or guard" -q 2>&1 | command tail -4`
Expected: PASS

- [ ] **Step 2: 复跑生产审计（只读）**

Run: `PYTHONUTF8=1 command python _audit_order_no.py 2>&1 | command tail -30`
Expected: 与改造前对照——无重复、无格式违规、**计数表不落后于数据**（§7 节的「偏差」标记应只剩正向方向或消失；注意脚本第 7 节的偏差输出没有方向性，人工判读：counter >= max 即安全）。

- [ ] **Step 3: 验收清单逐项打勾（spec §8 的 9 条）**

逐条核对并记录：core/number_generator.py 不存在 / stock_crud_service.py 不存在 / tzdata 在 base.txt / 9999 测试绿 / E2E 守卫测试绿 / order_purchase_sync 无引用 / 巡检端点可查 / 对账幂等测试绿。

- [ ] **Step 4: 提交核验结论（如有文档性变更）**

无代码改动则不产生提交；`_audit_order_no.py` 保持未跟踪（一次性探针，不纳入版本库）。

---

## Self-Review 记录

- **Spec 覆盖**：§4.1→Task 6；§4.2→Task 5；§4.3→Task 1；§4.4→Task 4；§4.5→Task 7（alert_rules 暂缓，符合 §10 取舍）；§4.6→Task 2；§4.7→Task 3；§5 对账→Task 6；§6 四项测试→Task 4/6（1、2、4）+ Task 5（语义回归）+ Task 2（守卫用例）；§9 八步→Task 1-8 一一对应。§6.1「两路径并发不重号」由 Task 5 消灭双路径后结构性成立（单一水位源），Task 5 语义测试 + Task 4 种子测试共同覆盖。
- **占位符扫描**：Task 6 Step 3 的对账函数首段是显式标注的「伪段 + 真实实现说明」，执行者按说明落地（先 SELECT 后比对再 UPDATE）——这是刻意的防照抄设计，不是 TBD。Task 5 的 `ALLOWED_UPLOAD_DIRS = [...]` 与 `_is_allowed_upload_path` 标注「原样保留」，指从现有文件复制，非占位。
- **类型一致性**：`read_daily_max(db, model, number_field, date_str)` 4 参签名在 Task 4 定义、Task 6 测试与 Task 7 无直接调用（巡检自算）；`generate_number_async(prefix, model, number_field, db)` 在 Task 4 定义、Task 6 使用；`number_lock_key/acquire_advisory_lock_async` Task 1 定义、Task 6 使用；`_NUMBERED_ENTITIES` Task 6 定义、Task 7 复用。
- **Review Focus 落点**：①三位前缀→Task 4 用例 3；②9999→Task 4 用例 1；③键碰撞幂等→Task 6 对账三用例；④批量语义→Task 5 四用例；⑤守卫顺序→Task 2 用例 4。
