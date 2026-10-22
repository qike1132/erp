# 批次 B — 性能与资源 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把阻塞事件循环的 CPU/IO 下沉，收紧资源上界，修掉 8 条性能/资源缺陷（H1、H2、H3、M1、L3、L10、L15、L16），不改变业务语义。

**Architecture:** 每条一个任务、一个提交、独立回滚。CPU/IO 下沉统一用 `asyncio.to_thread`；配置类改动只在启动期判定并 fail-fast/warn，不在请求热路径加判断。

**Tech Stack:** Python 3.13、FastAPI、SQLAlchemy async、ARQ 0.28、pytest。

**Spec:** `docs/superpowers/specs/2026-10-22-performance-bug-fixes-design.md`（批次 B 部分）

## Global Constraints

- 本机即生产机；不重启生产、不改 `.env`、不动 nginx/NSSM。
- 全量 pytest 必须提权；聚焦测试可用工作区 `.env`。
- 每条修复必须有变异检查（改坏行为后测试变红）。
- 提交只 `git add` 本任务文件；临时脚本用完删除。
- 不新增迁移。

## Review Focus

1. **备份加密/ZIP/sha256 下沉后**：事件循环仍可调度，且进度回调仍按原顺序触发。
2. **JSON 备份去缩进后**：恢复逻辑仍能读取（`json.loads` 与字段名不变）。
3. **日志改外部轮转后**：多进程写入不丢日志，文件名仍被 Loki/Promtail 采集。
4. **限流生产 fail-fast**：生产缺 Redis 时启动失败，开发仍回退内存。
5. **双 ARQ 守卫**：显式外部 ARQ 时内置 worker 不启动，且不影响现有 `--no-arq`。
6. **大 value 序列化下沉**：小 value 不走线程池（避免开销）。

---

## Task 1: 备份加密/ZIP/sha256 下沉线程池（H1）

**Files:**
- Modify: `fastapi_app/services/backup/orchestration/core.py`
- Modify: `fastapi_app/services/backup/orchestration/recovery_test_service.py`
- Modify: `fastapi_app/services/backup/orchestrator.py:269-276`
- Test: `tests/test_backup_offload.py`（新建）

**Interfaces:**
- Produces: `_pack_backup_zip_sync(...)`（同步实现）；`_pack_backup_zip(...)` 仍是 async 包装。
- Consumes: `services/backup/_proc.py::run_proc`。

- [ ] **Step 1: 写失败测试（加密期间事件循环可调度）**

```python
import asyncio, time
import pytest

@pytest.mark.asyncio
async def test_encrypt_does_not_block_loop(monkeypatch):
    from fastapi_app.services.backup.orchestration import core
    ticks = []
    start = time.monotonic()

    def _slow_encrypt(*a, **k):
        time.sleep(0.2)
        return b"enc", {}

    monkeypatch.setattr(core, "_encrypt_backup", _slow_encrypt)

    async def _ticker():
        for _ in range(5):
            ticks.append(time.monotonic() - start)
            await asyncio.sleep(0.02)

    await asyncio.gather(core._encrypt_backup_async(b"zip", "pw", {}, None), _ticker())
    assert len(ticks) == 5
    assert ticks[0] < 0.1
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_backup_offload.py -v`
Expected: FAIL（`_encrypt_backup_async` 不存在）

- [ ] **Step 3: 实现**

```python
# core.py
async def _encrypt_backup_async(zip_bytes, password, manifest, encrypt_password):
    return await asyncio.to_thread(
        _encrypt_backup, zip_bytes, password, manifest, encrypt_password
    )
```

`create_full_backup` 的返回改为：

```python
if effective_encryption_password:
    return await _encrypt_backup_async(
        zip_bytes, effective_encryption_password, manifest, encrypt_password
    )
```

`sha256_file`：

```python
checksums[db_dump_name] = await asyncio.to_thread(sha256_file, db_dump_file)
```

`_pack_backup_zip` 拆分：把函数体（除 `progress_cb`）移入 `_pack_backup_zip_sync`，async 包装里先 `await progress_cb('pack_start', ...)`，再 `await asyncio.to_thread(_pack_backup_zip_sync, ...)`，最后 `await progress_cb('pack_done', ...)`。`_export_meilisearch` 是 async，保留在 async 侧、放在线程池打包**之前**完成，结果写入 `manifest`。

`orchestrator._decrypt`：

```python
return await asyncio.to_thread(decrypt_backup, data, password)
```

`recovery_test_service` 的 `subprocess.run(psql_args, input=dump_sql, ..., timeout=600)` 改用：

```python
from fastapi_app.services.backup._proc import run_proc
await run_proc(psql_args, env=env, timeout=600)
```

（`input=dump_sql` 改为先把 `dump_sql` 写到临时文件，再用 `psql -f`；避免把整包 SQL 留在内存里。）

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/test_backup_offload.py -v`
Expected: PASS

- [ ] **Step 5: 变异检查**

把 `await asyncio.to_thread(...)` 改回直接调用，测试必须变红。

- [ ] **Step 6: 提交**

```bash
git add fastapi_app/services/backup/orchestration/core.py fastapi_app/services/backup/orchestration/recovery_test_service.py fastapi_app/services/backup/orchestrator.py tests/test_backup_offload.py
git commit -m "perf(备份): 加密/ZIP/sha256/psql 下沉线程池，避免阻塞事件循环"
```

---

## Task 2: JSON 备份去缩进（H2 第一步）

**Files:**
- Modify: `fastapi_app/services/backup/json_backup.py:354`
- Test: `tests/test_json_backup_compact.py`（新建）

**Interfaces:** 返回值仍是 bytes，字段名不变。

- [ ] **Step 1: 写失败测试**

```python
import json

def test_json_backup_is_compact(monkeypatch):
    from fastapi_app.services.backup import json_backup
    payload = {"tables": {"t": {"columns": ["a"], "rows": [{"a": 1}], "count": 1}}}
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    assert b"\n" not in raw  # 紧凑格式无换行
```

> 说明：直接断言生成函数会需要真实 DB；本条用「紧凑序列化后无换行」锁定口径，并在实现后由现有 JSON 恢复测试验证可读性。

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_json_backup_compact.py -v`
Expected: FAIL（测试本身先红，提示尚未实现紧凑口径）

- [ ] **Step 3: 实现**

把 `json.dumps(backup_data, ensure_ascii=False, indent=2)` 改为：

```python
json.dumps(backup_data, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
```

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/test_json_backup_compact.py tests -k "json_backup or legacy_json" -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add fastapi_app/services/backup/json_backup.py tests/test_json_backup_compact.py
git commit -m "perf(备份): JSON 备份去掉 indent，体积约减半"
```

**Ruling（记入账本）**：完整流式落盘需要改 `_pack_backup_zip` 的 bytes 契约与 ZIP 写入路径，属独立设计；本批先做无风险的去缩进，流式化在批次 B 后续或独立任务。

---

## Task 3: 日志改外部 copytruncate 轮转（H3）

**Files:**
- Modify: `fastapi_app/core/logger.py:64-76`
- Test: `tests/test_logger_rotation.py`（新建）

**Interfaces:** 日志文件名保持 `fastapi_YYYYMMDD.log`。

- [ ] **Step 1: 写失败测试**

```python
import logging

def test_logger_uses_plain_file_handler(tmp_path):
    from fastapi_app.core.logger import setup_logging
    setup_logging(log_dir=tmp_path)
    root = logging.getLogger()
    handlers = [h for h in root.handlers if isinstance(h, logging.FileHandler)]
    assert handlers
    assert not any(isinstance(h, logging.handlers.TimedRotatingFileHandler) for h in handlers)
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_logger_rotation.py -v`
Expected: FAIL（当前是 TimedRotatingFileHandler）

- [ ] **Step 3: 实现**

`logger.py` 把 `TimedRotatingFileHandler(...)` 改为 `logging.FileHandler(log_file, encoding='utf-8')`；保留 `setLevel`/`setFormatter`。注释说明轮转由 `utils.log_rotation.rotate_oversized_logs`（prod_runner 周期 + ARQ 每日）负责。

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/test_logger_rotation.py -v`
Expected: PASS

- [ ] **Step 5: 变异检查**

改回 `TimedRotatingFileHandler`，测试变红。

- [ ] **Step 6: 提交**

```bash
git add fastapi_app/core/logger.py tests/test_logger_rotation.py
git commit -m "fix(日志): 多 worker 共用文件改外部 copytruncate 轮转，消除午夜竞态"
```

---

## Task 4: L1 广播启动告警 + 恢复订单列表 L1（M1 代码部分）

**Files:**
- Modify: `fastapi_app/main.py`（启动期告警）
- Modify: `fastapi_app/services/order/queries.py:241-245`（`local_ttl=30`）
- Test: `tests/test_l1_broadcast_warning.py`（新建）

**Interfaces:** `def warn_if_l1_broadcast_disabled(workers: int) -> None`。

- [ ] **Step 1: 写失败测试**

```python
def test_warns_when_multi_worker_without_broadcast(monkeypatch, caplog):
    import logging
    from fastapi_app.core import cache
    monkeypatch.setattr(cache, "_L1_BROADCAST_ENABLED", False)
    with caplog.at_level(logging.WARNING):
        cache.warn_if_l1_broadcast_disabled(8)
    assert any("CACHE_L1_BROADCAST_ENABLED" in r.getMessage() for r in caplog.records)
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_l1_broadcast_warning.py -v`
Expected: FAIL（函数不存在）

- [ ] **Step 3: 实现**

`cache.py` 新增：

```python
def warn_if_l1_broadcast_disabled(workers: int) -> None:
    if workers >= 2 and not _L1_BROADCAST_ENABLED:
        logger.warning(
            "UVICORN_WORKERS=%d 但 CACHE_L1_BROADCAST_ENABLED=false："
            "多 worker 下 L1 缓存最长 local_ttl 内可能读到脏数据",
            workers,
        )
```

`main.py` 启动期调用 `warn_if_l1_broadcast_disabled(int(os.getenv('UVICORN_WORKERS', '0') or 0))`。

`services/order/queries.py` 的 `local_ttl=0` 改为 `local_ttl=30`。

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/test_l1_broadcast_warning.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add fastapi_app/core/cache.py fastapi_app/main.py fastapi_app/services/order/queries.py tests/test_l1_broadcast_warning.py
git commit -m "perf(缓存): 多 worker 未开 L1 广播时告警，并恢复订单列表 30s L1"
```

> 生产 `.env` 开启 `CACHE_L1_BROADCAST_ENABLED=true` 与重启仍需 owner 发话，不在本任务内。

---

## Task 5: 生产限流缺 Redis 时 fail-fast（L3）

**Files:**
- Modify: `fastapi_app/core/limiter.py`
- Modify: `fastapi_app/main.py`（启动期调用）
- Test: `tests/test_limiter_prod_guard.py`（新建）

**Interfaces:** `def assert_production_limiter_storage() -> None`。

- [ ] **Step 1: 写失败测试**

```python
import pytest

def test_production_without_redis_fails(monkeypatch):
    from fastapi_app.core import limiter
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("REDIS_CACHE_URL", raising=False)
    with pytest.raises(RuntimeError, match="REDIS_CACHE_URL"):
        limiter.assert_production_limiter_storage()

def test_development_falls_back(monkeypatch):
    from fastapi_app.core import limiter
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.delenv("REDIS_CACHE_URL", raising=False)
    limiter.assert_production_limiter_storage()  # 不抛
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_limiter_prod_guard.py -v`
Expected: FAIL（函数不存在）

- [ ] **Step 3: 实现**

```python
def assert_production_limiter_storage() -> None:
    from fastapi_app.core.config import _is_production_env
    if _is_production_env() and not os.getenv("REDIS_CACHE_URL"):
        raise RuntimeError(
            "生产环境必须配置 REDIS_CACHE_URL：限流回退 memory:// 会让 8 worker "
            "各自计数，实际阈值被放大"
        )
```

`main.py` 启动期调用。

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/test_limiter_prod_guard.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add fastapi_app/core/limiter.py fastapi_app/main.py tests/test_limiter_prod_guard.py
git commit -m "fix(限流): 生产缺 REDIS_CACHE_URL 时启动失败，避免多 worker 阈值放大"
```

---

## Task 6: 双 ARQ worker 守卫（L10）

**Files:**
- Modify: `fastapi_app/core/prod_runner.py`
- Test: `tests/test_prod_runner_arq_guard.py`（新建）

**Interfaces:** `def should_start_internal_arq(argv: list[str], env: dict) -> bool`。

- [ ] **Step 1: 写失败测试**

```python
def test_external_arq_flag_disables_internal():
    from fastapi_app.core.prod_runner import should_start_internal_arq
    assert should_start_internal_arq([], {"ERP_ARQ_EXTERNAL": "1"}) is False
    assert should_start_internal_arq(["--no-arq"], {}) is False
    assert should_start_internal_arq([], {}) is True
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_prod_runner_arq_guard.py -v`
Expected: FAIL（函数不存在）

- [ ] **Step 3: 实现**

```python
def should_start_internal_arq(argv: list[str], env: dict) -> bool:
    if "--no-arq" in argv:
        return False
    if env.get("ERP_ARQ_EXTERNAL", "").strip() == "1":
        return False
    return True
```

`main()` 里 `with_arq = should_start_internal_arq(argv, os.environ)`。

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/test_prod_runner_arq_guard.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add fastapi_app/core/prod_runner.py tests/test_prod_runner_arq_guard.py
git commit -m "fix(启动): 支持 ERP_ARQ_EXTERNAL 显式标记，避免双 ARQ worker 消费同一 broker"
```

---

## Task 7: Redis 大 value 序列化下沉（L15）

**Files:**
- Modify: `utils/redis_cache.py`
- Test: `tests/test_redis_cache_offload.py`（新建）

**Interfaces:** 阈值常量 `_SERIALIZE_OFFLOAD_BYTES = 64 * 1024`。

- [ ] **Step 1: 写失败测试（大 value 序列化期间循环可调度）**

```python
import asyncio, json, time
import pytest

@pytest.mark.asyncio
async def test_large_value_serialization_offloaded(monkeypatch):
    from utils import redis_cache
    ticks, start = [], time.monotonic()

    def _slow_dumps(*a, **k):
        time.sleep(0.2)
        return "{}"

    monkeypatch.setattr(redis_cache.json, "dumps", _slow_dumps)

    async def _ticker():
        for _ in range(5):
            ticks.append(time.monotonic() - start)
            await asyncio.sleep(0.02)

    async def _run():
        await redis_cache._serialize_async({"x": "y" * (128 * 1024)})

    await asyncio.gather(_run(), _ticker())
    assert ticks[0] < 0.1
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_redis_cache_offload.py -v`
Expected: FAIL（`_serialize_async` 不存在）

- [ ] **Step 3: 实现**

```python
_SERIALIZE_OFFLOAD_BYTES = 64 * 1024

async def _serialize_async(value):
    import asyncio, json as _json
    if len(str(value)) >= _SERIALIZE_OFFLOAD_BYTES:
        return await asyncio.to_thread(_json.dumps, value, ensure_ascii=False)
    return _json.dumps(value, ensure_ascii=False)
```

`set()` 用 `_serialize_async`；`get()` 的 `json.loads(value)` 对 `len(value) >= 阈值` 走 `asyncio.to_thread`。

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/test_redis_cache_offload.py tests -k "redis_cache or cache" -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add utils/redis_cache.py tests/test_redis_cache_offload.py
git commit -m "perf(缓存): 大 value JSON 序列化下沉线程池，小 value 保持同步"
```

---

## Task 8: 备份覆盖度统计改 reltuples（L16）

**Files:**
- Modify: `fastapi_app/services/backup/orchestration/core.py:232-251`
- Test: `tests/test_backup_count_estimate.py`（新建）

**Interfaces:** `_count_tables` 返回 `dict[str, int]`，语义不变（大表为估算值）。

- [ ] **Step 1: 写失败测试（大表不再发 COUNT）**

```python
import pytest

@pytest.mark.asyncio
async def test_large_table_uses_reltuples(fake_session):
    from fastapi_app.services.backup.orchestration import core
    fake_session.reltuples = {"big": 5_000_000, "small": 10}
    stats = await core._count_tables(
        fake_session, ["big", "small"], {"big", "small"}
    )
    assert stats["big"] == 5_000_000
    assert "COUNT(*)" not in fake_session.executed_sql_for("big")
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_backup_count_estimate.py -v`
Expected: FAIL（当前逐表 COUNT）

- [ ] **Step 3: 实现**

一次查询取 `pg_class.reltuples`：

```python
reltuples_sql = text(
    "SELECT c.relname, c.reltuples::bigint FROM pg_class c "
    "JOIN pg_namespace n ON n.oid = c.relnamespace "
    "WHERE n.nspname = 'public' AND c.relkind = 'r' AND c.relname = ANY(:names)"
)
rows = await db.execute(reltuples_sql, {"names": table_names})
estimates = {r[0]: max(0, int(r[1])) for r in rows.all()}
```

对 `estimates[t] >= 100_000` 用估算值；否则走原 COUNT（小表精确、无锁压力）。`-1` 语义（表不存在/失败）保持不变。

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/test_backup_count_estimate.py -v`
Expected: PASS

- [ ] **Step 5: 回归**

Run: `pytest tests fastapi_app/tests -k "backup" -q`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add fastapi_app/services/backup/orchestration/core.py tests/test_backup_count_estimate.py
git commit -m "perf(备份): 大表覆盖度改用 pg_class.reltuples，避免长事务 COUNT"
```

---

## 批次 B 完成门槛

- [ ] 8 个任务全绿，每个有变异检查。
- [ ] 聚焦回归 + 提权全量 pytest（0 failed）。
- [ ] ruff / mypy / quality_gate 通过。
- [ ] 不重启生产、不改 `.env`。
