# P1 收口批独立验证台账（2026-10-01，attempt 3 / 最终）

- **任务**：t26（kind=verification）。attempt 3 = `fc0a21fa-ac59-4e64-a361-7e6c9e4dcf30`（本轮）；attempt 2 = `ac40e45a-2b2e-42da-bf69-00bae1e6123d`（failed，发现 F-06）；attempt 1 = `5590f6d8-da95-4771-a397-3bbd165e7b1b`（failed，发现 F-01/F-02）
- **验证人**：verifier —— 与 P1 批次实现者无重叠，全程不采信成员自述
- **基线（frozen 快照）**：HEAD = `73b3a93cc85a5dc6fec352a8d599679ec02df18f`；验证前后 `git diff HEAD --shortstat` 恒为 `47 files changed, 1964 insertions(+), 625 deletions(-)`，`git status --porcelain` 恒为 66 项、`git diff HEAD --name-only` 恒为 47 个 tracked 文件
- **被验证的新增测试文件指纹**：`fastapi_app/tests/test_order_deduction_completeness.py`（未跟踪）SHA256 = `456853641DDF8CCF9CC295B42C4F64550A05610BD70D9EE4CAB2AE947F899AC5` / 26120 B，验证全程未变（与 captain 声明的指纹一致）
- **范围**：无实现文件改动（见 §7）；探针脚本与命令输出全部落在仓库外 `%TEMP%\t26-verifier3\`（只读复用 `%TEMP%\t26-verifier2\` 的既有探针）

## 结论（TL;DR）

| 维度 | 实测结论 |
| --- | --- |
| `python -m pytest -q --ignore=tests/stress` | **exit 0** ✔ `3786 passed, 268 skipped in 383.05s`（0 failed / 0 errors） |
| `scripts/quality_gate.py` | **exit 0** `[PASS]`，10 个门禁与 `gate_baseline.json` 逐项一致 |
| `python -m mypy --config-file mypy.ini` | **exit 0**，`Success: no issues found in 144 source files` |
| attempt 1 的 F-01（blocker：6 例确定性代码回归） | **已修复** ✔ 6 failed → 0 failed |
| attempt 1 的 F-02（medium：内联负库存硬拒未收口） | **已修复** ✔ 统一入口调用点已就位 |
| attempt 2 的 F-06（high：本批新增测试 `_test_db_url()` 双后缀） | **已修复并复核关闭** ✔ t43 落地；`probe_f06.py` 独立复算幂等性 + 全量套件 exit 0 |
| 总判定 | **达标，可收口**：三门禁全 exit 0，未达标项 **0**；残留风险 3 条（F-03/F-04/F-05）+ 1 条低危提示（F-07） |

> **对 attempt 1 的自我更正（仍有效）**：attempt 1 把 F-06 那 2 例 ERROR 归为「环境抖动（WinError 64）」。attempt 2 用两次全量运行 + 独立复现**证伪**该归因；attempt 3 用 `probe_f06.py` 复算修复前后的三种输入行为，确认它是**确定性缺陷**且已修好（§4）。

## 0 验证方法与纪律

1. **独立复算优先于复述**：所有数字（门禁 10 类计数、mypy 文件数、ruff 违规数、FAIL 计数、负库存判定点集合、守卫条件所属 if、迁移/ORM 约束一致性）均由我在当前工作树上重跑或探针复现。
2. **探针**（仓库外，只用 `.venv` 现有依赖，未新增包、未写入仓库）：
   - `probe_static.py`：AST + 词界正则静态扫描（`.query(` 残留、`current_stock` 比较/写入、守卫条件所属 if、迁移与 ORM 约束一致性、mypy.ini 条目计数、gate_baseline 计数、.env.example 键）
   - `probe_runtime.py`：运行时行为（策略函数语义、CommitBatcher 提交次数、JobIdempotency 键空间、审计批量 INSERT 形状、对账语句编译与分类）
   - `probe_controls.py`：前端契约检查器的**灵敏度反证**（注入缺陷后必须非零退出）
   - `probe_counts.py` / `probe_db.py`：门禁计数复算 / 只读 DB 核对（仅 SELECT）
   - `probe_f02.py`（本次新增）：F-02 专项 AST 复算（内联 `new_current_stock < 0` 是否仍有残留、统一入口调用点与 import 绑定）
   - `probe_dburl.py` / `probe_conn.py`（attempt 2 新增，本轮复跑）：F-06 根因复现（URL 推导 + 直连实测）
   - `probe_f06.py`（本轮新增）：F-06 **修复**的独立复算 —— 直接加载被测模块调 `_test_db_url()`，对照「conftest 改写后 / 生产库名 / 显式 TEST_DATABASE_URL」三种输入，并用旧公式复现 `erp_system_test_test`
3. **串行纪律**：按 captain 要求把 `pytest` 放在最前（吃到 PG 连接余量），三门禁在**单个**后台作业内串行执行（pytest → quality_gate → mypy）；开跑前用 `Get-CimInstance Win32_Process` 确认当时只有本次 pytest、无其它并发套件。本轮全量**一次性通过**，未触发「仅并发建连类失败可重跑」的例外条款。
4. **只读 DB**：`probe_db.py` 只发 SELECT；`probe_conn.py` 只做连接尝试（含一次预期失败），未建库/删库、未写任何表。
5. **纪律**：未 `git add/commit/checkout/stash`；未重启服务；未执行 `icacls/sc/schtasks`；未改 `.env`；未改 `scripts/gate_baseline.json`。

## 1 三门禁实测记录

命令均在 `D:\erp_system` 下、由 `D:\erp_system\.venv\Scripts\python.exe` 串行执行（2026-10-01 23:02:05 起跑、23:10 前全部结束），输出落盘 `%TEMP%\t26-verifier3\`。

| # | 命令 | exit code | 关键输出 |
| --- | --- | --- | --- |
| 1 | `python -m pytest -q --ignore=tests/stress`（23:02:05→23:08:33） | **0** | `3786 passed, 268 skipped in 383.05s (0:06:23)`，无 failed、无 errors |
| 2 | `python scripts/quality_gate.py` | **0** | `[PASS]`；十类逐行 `OK … 与基线一致`：N+1=0 / bare_except=5 / function_length=51 / Vue=7 / service_commit=12 / BOM=0 / alembic_heads=0 / env_drift=0 / ruff=60 / pip_audit=0 |
| 3 | `python -m mypy --config-file mypy.ini` | **0** | `Success: no issues found in 144 source files`（与 `mypy.ini` 条目计数 144 独立吻合） |
| 4 | `python -m pytest tests/test_stock.py tests/test_stock_concurrency.py fastapi_app/tests/test_order_deduction_completeness.py -q` | **0** | `47 passed in 3.27s`（F-01 两文件 + F-06 文件同批通过） |
| 5 | `python scripts/quality_gate.py --self-test` | **0** | `[SELFTEST] 全部通过：48 项` |
| 6 | `python scripts/check_service_commit.py --self-test` | **0** | `[SELFTEST] PASS 真实服务层扫描非空且命中可回溯（实扫 12 处）` / `全部通过：14 项` |
| 7 | `python scripts/check_orphan_modules.py` | **0** | `PASS`；`mypy.ini 白名单条目：144（有入边 144）` |
| 8 | `node frontend-vite/scripts/check-route-alignment.mjs --json` | **0** | `status=consistent`（pcPaths=30 / mobilePaths=15 / sharedPaths=12 / sharedFeatures=10 / unpairedMobileRoutes=4） |
| 9 | `python scripts/check_openapi_frontend_alignment.py --strict-allowlist --json` | **0** | `status=pass`，`specSource=app.openapi()`、`backendPaths=343`、`frontendLiteral=132`、`frontendTemplate=103`、`missing=[]`、`allowlisted=[]`、`staleAllowlist=[]` |

补充：
- 与 attempt 2 对比：`errors 2 → 0`、`passed 3783 → 3786`、`skipped 268 → 268`、exit `1 → 0`；与 attempt 1 对比 `failed 6 → 0`。
- 10 类门禁中 `pip_audit` 因本机未安装 pip-audit 只输出 WARN（计划 §6.5 已披露），不构成红灯。
- 本轮**未**出现 `tests/test_numbering_sequence_integration.py::test_concurrent_allocation_unique` 或任何建连期 `ConnectionDoesNotExistError` / `WinError 64` 失败，故未启用 captain 给出的 re-run 条款，也无需引用 PG 日志；PG 连接预算的调整（idle_session_timeout / 后端回收）只作为环境背景记录，验证结论不依赖它。

## 2 F-01 复核（attempt 1 blocker）：已修复，且是**真修不是放宽**

### 2.1 修复落在测试题面侧，实现侧零改动

`git diff HEAD --numstat`（本次复核）：

| 文件 | +/− | mtime | 归属 |
| --- | --- | --- | --- |
| `tests/test_stock.py` | +79/−1 | 19:29:40 | t41 |
| `tests/test_stock_concurrency.py` | +27/−2 | 19:29:56 | t41 |
| `fastapi_app/services/product_service.py` | +11/−4 | 19:30:48 | t42（F-02） |
| `fastapi_app/shared/stock_concurrency.py` | 226+/31− | 18:58:28 | **本次未再改动** |
| `fastapi_app/services/stock_out_service.py` | 33+/12− | 18:50:37 | **本次未再改动** |

⇒ 修复方式与 attempt 1 的诊断一致：不是回退 P1-3/P1-6 的实现，而是把既有 mock 题面**显式建模**成新的调用序列。

### 2.2 修复内容（我逐行读 diff 判定）

- `tests/test_stock.py`：新增 `_empty_result()` 与 `_wire_stock_write(db, row, *, new_stock, pre_results=())`，把「SELECT 当前行（rowcount 视角）→ 条件 UPDATE → refresh 回读」两步序列显式建模，返回 `state={'calls','consumed'}`；4 个用例改为调用它并**新增**断言：`state['consumed'] == 2/3`、`len(state['calls']) == 2/4`、`product.current_stock == 150/220/130`、`product.version == 2`。
- `tests/test_stock_concurrency.py`：两例的 `db.execute` `side_effect` 扩为 `[select, conflict, classify_result, select, success]` / `[select, conflict, classify, select, conflict, classify]`，其中 `classify_result.scalar_one_or_none` 返回 `MagicMock(id=1, current_stock=100, version=2)`（2 ≠ 1 ⇒ 判版本冲突）；**新增**断言 `db.execute.await_count == 5/6`、`classify_result.scalar_one_or_none.call_count == 1/2`、`db.begin_nested.call_count == 2`。
- **未削弱证据（非自述）**：`git diff` 对这两个文件统计「新增 assert 行 = 18、删除 assert 行 = 0」；全工作树 diff 中**没有**新增 `skip/xfail/skipif/filterwarnings`（正则命中仅出现在本台账对 `--ignore=` 的引用文本里）。
- **独立复现（本轮）**：`pytest tests/test_stock.py tests/test_stock_concurrency.py fastapi_app/tests/test_order_deduction_completeness.py -q` → `47 passed in 3.27s`，rc=0（attempt 1 同命令含 6 failed）；全量运行该集合 0 失败。

## 3 F-02 复核（attempt 1 medium）：已修复

`probe_f02.py`（AST + 词界正则，仓库外）本轮复跑实测（结果与 attempt 2 逐字相同）：

```json
{
 "inline_lt0_lines": [],
 "assert_stock_available_lines": [
  "20: from fastapi_app.shared.stock_concurrency import assert_stock_available, get_product_for_update",
  "266: assert_stock_available（策略开关见 ALLOW_NEGATIVE_STOCK），不再内联比较",
  "299: assert_stock_available(product.current_stock, stock_change,"
 ],
 "update_product_lineno": 255,
 "assert_call_sites": [{"lineno": 299, "nargs": 2, "kwargs": ["message"]}],
 "current_stock_cmp_non_test": [
  "fastapi_app/services/inventory_reconcile.py:6: 清单，再谈 P1-6 的 ``CHECK(current_stock >= 0)``。",
  "fastapi_app/services/dashboard/stats.py:208: .where(Product.current_stock <= 10)"
 ]
}
```

- attempt 1 的缺口行 `product_service.py:292-298`（内联 `if new_current_stock < 0: raise ValueError(...)`）**已不存在**：`inline_lt0_lines = []`。
- 统一入口调用点 = `fastapi_app/services/product_service.py:299`（`nargs=2` + `message=` 关键字），import 绑定在 `:20`，函数 `update_product` 起点 `:255`。
- 残余 `current_stock` 比较只剩两处且均非判定点：`inventory_reconcile.py:6`（docstring 文本）、`dashboard/stats.py:208`（`.where(Product.current_stock <= 10)` 只读低库存阈值，tests 内已具名豁免）。
- 说明：`product_service.py:207` 仍有 `if initial_stock < 0:` —— 这是**入参校验**（入参不能为负），不是库存写入判定点，与 F-02 无关，逐条核对后不计为残留。

## 4 F-06（attempt 2 发现，high）：已由 t43 修复 —— 本轮独立复算关闭

**这是 attempt 1 那 2 例 ERROR 的真根因；本轮确认修复点正确，且不是「靠放宽断言过关」。**

### 4.1 修复内容（我读源码逐行确认，非采信自述）

`fastapi_app/tests/test_order_deduction_completeness.py`（未跟踪，SHA256 `456853641DDF8CCF9CC295B42C4F64550A05610BD70D9EE4CAB2AE947F899AC5` / 26120 B，验证全程未变）：

- `:453` 新增 `_is_test_db_url(raw_url: str) -> bool`：`urlparse(raw_url).path.lstrip('/').endswith('_test')`
- `:458-475` `_test_db_url()` 改为三级判定：① 显式 `TEST_DATABASE_URL` 优先；② `settings.ASYNC_DATABASE_URL` 已经是测试库则**原样复用**，绝不再二次替换；③ 否则才按 `DB_NAME` 追加一次 `_test`
- `:478-493` 新增 `_connection_error_types()` / `_CONNECTION_ERROR_TYPES`：在 `OSError / ConnectionError / sqlalchemy InterfaceError、OperationalError` 之外显式纳入 `asyncpg.PostgresConnectionError` 与 `asyncpg.InterfaceError`
- `:519-525` `deduct_engine` fixture：仅探测连接（`SELECT 1`）的 `except _CONNECTION_ERROR_TYPES` 才 `pytest.skip`；**建表/DDL 在探测之后、且不在 skip 分支内** ⇒ schema 类错误仍必须冒泡为失败（未放宽断言）

### 4.2 本轮独立复算（`probe_f06.py`：直接加载被测模块调 `_test_db_url()`）

```json
{
 "module_file": "D:\\erp_system\\fastapi_app\\tests\\test_order_deduction_completeness.py",
 "is_test_db_url": {"erp_system": false, "erp_system_test": true, "erp_system_test_custord": false},
 "A_after_conftest_rewrite": "postgresql+asyncpg://u:p@127.0.0.1:5432/erp_system_test",
 "A_ok": true,
 "B_from_prod_name": "postgresql+asyncpg://u:p@127.0.0.1:5432/erp_system_test",
 "C_env_override": "postgresql+asyncpg://u:p@127.0.0.1:5432/erp_override_lib",
 "D_old_behaviour": "postgresql+asyncpg://u:p@127.0.0.1:5432/erp_system_test_test",
 "CDNE_is_OSError": false, "CDNE_is_SQLAlchemyError": false, "CDNE_caught": true
}
```

- **A（原缺陷场景）**：把全局单例改写成 `.../erp_system_test`（模拟 `tests/conftest.py:225-243` 的会话 fixture 副作用）后调用 `_test_db_url()` → 返回**原值**，不再拼出 `erp_system_test_test`。
- **B（单文件场景）**：URL 仍是生产库名 `erp_system` → 正确追加一次得 `.../erp_system_test`（能力未被削弱）。
- **C**：显式 `TEST_DATABASE_URL` 仍优先。
- **D（旧公式对照）**：按 attempt 2 的原逻辑复算，仍复现 `.../erp_system_test_test` ⇒ 证明根因判定正确、修复点正是该公式。
- `asyncpg.ConnectionDoesNotExistError`：`isinstance OSError=False`、`isinstance SQLAlchemyError=False`，但 `CDNE_caught=True` ⇒ 现在会被判为「库不可达 → skip」，不再是 setup ERROR。
- 第二组独立证据（沿用 attempt 2 探针、在本轮工作树重跑）：`probe_dburl3.out` 的 `DERIVED_FS = .../erp_system_test`（attempt 2 同脚本为 `.../erp_system_test_test`）—— URL 推导侧同样已修正。

### 4.3 端到端复证

- 全量 `pytest -q --ignore=tests/stress`：**exit 0**，`3786 passed, 268 skipped`；该文件两例真实库用例由 `ERROR at setup` 变为 **PASSED**（计入 3786）。
- 定向 `pytest tests/test_stock.py tests/test_stock_concurrency.py fastapi_app/tests/test_order_deduction_completeness.py -q` → `47 passed in 3.27s`，rc=0。
- 未削弱证据：工作树 diff 中新增 `skip/xfail/skipif/filterwarnings` 命中 **0**；该文件断言一条未删（正则命中仅出现在本台账对 `--ignore=` 的引用文本里）。

### 4.4 残留（非阻断，登记为 F-07）

`_is_test_db_url()` 只识别「库名以 `_test` 结尾」。若把全局 URL 指到 `erp_system_test_custord` 这类派生库（既有库列表中确实存在），旧追加分支仍会算出不存在的库名；但**后果已从 setup ERROR 降级为 skip**（连接类异常被 `_CONNECTION_ERROR_TYPES` 捕获），不再阻塞套件，仅在 `pytest -rs` 下表现为跳过。建议后续改以 `TEST_DATABASE_URL` 为唯一真源。

### 4.5 attempt 2 的原始事实链（保留作对照）

1. `tests/conftest.py:225-243` 会话级 autouse fixture `app_on_test_db` 把 `settings.ASYNC_DATABASE_URL` 全局改写为 `TEST_DATABASE_URL`，即 `.../erp_system_test`（`tests/conftest.py:128` 由 `_build_test_db_url()` 得出）。
2. 本批**新增**（未跟踪）文件 `fastapi_app/tests/test_order_deduction_completeness.py:451-460` 的 `_test_db_url()`：当 `TEST_DATABASE_URL` 环境变量为空时，读 `settings.ASYNC_DATABASE_URL` 并把路径里 `/erp_system` 再替换为 `/erp_system_test`。
3. 在全量运行（`tests/` 的 conftest 已生效）语境下，替换得到 **`.../erp_system_test_test`** —— 该库不存在。
4. `probe_dburl.py`（仓库外，只读）实测：
   ```text
   MAIN       = postgresql+asyncpg://...@localhost:5432/erp_system
   CONFTEST   = postgresql+asyncpg://...@localhost:5432/erp_system_test
   DERIVED_FS = postgresql+asyncpg://...@localhost:5432/erp_system_test_test   <- 全量语境
   DERIVED_STANDALONE = postgresql+asyncpg://...@localhost:5432/erp_system_test  <- 单文件语境
   DATABASES: [... 'erp_system', 'erp_system_drill', 'erp_system_test', 'erp_system_test_custord' ...]  # 无 erp_system_test_test
   max_connections: 100
   ```
5. `probe_conn.py`（直连实测，只做连接尝试）：
   ```text
   erp_system_test_test FAIL asyncpg.exceptions.ConnectionDoesNotExistError | connection was closed in the middle of operation
      isinstance OSError: False
      isinstance SQLAlchemyError: False
   erp_system_test CONNECT OK erp_system_test
   erp_system CONNECT OK erp_system
   ```
6. pytest 侧堆栈与之一致：`ERROR at setup of ...` → `fastapi_app\tests\test_order_deduction_completeness.py:486: in deduct_engine / async with engine.begin() as conn:`（首次连接即失败）。异常**既不是 `OSError` 也不是 `SQLAlchemyError`**，因此逃过了 fixture 的 `except (OSError, SQLAlchemyError)` 跳过分支（`:495-497`），被 pytest 记为 setup ERROR。
7. 单文件运行（不加载 `tests/conftest.py`）⇒ 推导 URL 恰为 `erp_system_test`（存在）⇒ `12 passed in 0.97s`，rc=0。

### 4.6 attempt 2 的原始定性（保留作对照）

- **确定性**：三次全量运行（attempt 1 一次 + attempt 2 两次，19:46 与 19:53）失败集合逐字相同；单文件恒 pass。**不是环境抖动**。
- **归属**：`fastapi_app/tests/test_order_deduction_completeness.py` 为**本批新增文件**（`git ls-files --error-unmatch` 报 pathspec 不匹配 = 未跟踪；mtime 18:45:51）；`tests/conftest.py` 未改动。
- **影响面**：仅测试/门禁口径（生产代码无影响），但它使**契约命令无法 exit 0** ⇒ 阻塞 P1 收口。
- **建议修复（1 行级，属实现者写域）**：`_test_db_url()` 在替换后若路径已以 `_test` 结尾则不再追加；或直接优先采用已生效的 `TEST_DATABASE_URL`（如 `tests/conftest.py:128` 导出的同名常量）。另建议把 fixture 的 `except` 放宽到「任何连接失败即 skip」，避免同类问题再次变成 ERROR。

## 5 未达标项与残留风险（独立单列）

| ID | 级别 | 项 | 事实与证据 | 建议处置 |
| --- | --- | --- | --- | --- |
| ~~**F-06**~~ | ~~high~~ → **已关闭** | 契约命令曾非绿（attempt 1/2） | t43 已修；本轮全量 `3786 passed, 268 skipped` **exit 0** + `probe_f06.py` 四场景复算（§4.2）+ 定向 `47 passed` ⇒ 关闭 | 无需动作 |
| **F-07** | low | `_is_test_db_url()` 判定面偏窄 | 只认「以 `_test` 结尾」；`probe_f06.py` 实测 `erp_system_test_custord` → false，仍会走追加分支算出不存在的库名（§4.4）。但与 F-06 不同：连接类异常已被 `_CONNECTION_ERROR_TYPES` 捕获 ⇒ 后果仅为 `skip`，不再阻塞套件 | 后续改以 `TEST_DATABASE_URL` 为唯一真源；非阻断 |
| F-01 | ~~blocker~~ → **已关闭** | 6 例确定性代码回归 | `tests/test_stock.py`+`tests/test_stock_concurrency.py` → `35 passed` rc=0；全量 0 FAILED；新增断言 18 行、删 0 行 | 无需动作 |
| F-02 | ~~medium~~ → **已关闭** | 内联负库存硬拒未收口 | `probe_f02.py`：`inline_lt0_lines=[]`，统一入口调用点 `product_service.py:299`（§3） | 无需动作 |
| F-03 | low | 迁移 061 未上库 | 只读 DB 探针：`alembic_version` 仍为 `pg_standalone_060_fix_updated_at_varchar_columns`；`pg_constraint` 查 `ck_product_current_stock_nonneg` 为空；`product.current_stock` min=0（无脏数据） | 生产机/运维动作：发布单含 `alembic upgrade head`；脏数据环境需 `VALIDATE CONSTRAINT` 收尾 |
| F-04 | low | pip-audit 未安装 | 门禁第 10 类只 WARN；计划 §6.5 已披露 | 保持披露，或 CI 安装后转硬门禁 |
| F-05 | info | 覆盖范围声明 | 契约命令显式排除 `tests/stress`；本次未评估该目录 | 若 stress 属交付范围，需另派验证 |

## 6 逐项 P1 结论（结论 / 证据命令 / 实测输出 / 缺口）

证据强度标注：**复算** = 我独立重算或探针复现；**运行复现** = 我亲自运行定向用例得到结果。

### P1-1 库存只读对账（t13，另含 t29）
- **结论：达标（复算）**
- 实测：`fastapi_app/services/inventory_reconcile.py` 内 `commit/add/delete/flush/rollback` 调用数 = 0，循环体内 `db` 调用数 = 0；`build_reconcile_statement()` 编译为**单条集合式 SQL**：`SELECT product.id, product.name, product.initial_stock, product.current_stock, coalesce(sum(inventory_log.change_quantity), 0) AS log_sum FROM product LEFT OUTER JOIN inventory_log ON inventory_log.product_id = product.id GROUP BY product.id, product.name, product.initial_stock, product.current_stock ORDER BY product.id`；`classify_diff(-5/0/7)` = negative/matched/positive；`summarize_rows(4 行, diff_limit=2)` → checked_products=4、matched=1、diff_count=3、positive=1、negative=2、net_diff=-4、abs_diff_total=8、truncated=true。`.env.example` 含 `INVENTORY_RECONCILE_ENABLED`（:202）。
- 缺口：无（调度注册属运维半）。

### P1-2 参数化负库存策略（t14）
- **结论：达标（复算）**
- 实测：`allow_negative_stock()` 在 env 缺省 / `'false'` / 空串 → False，`'true'` → True；`check_stock_available(3, -5)` → `'库存不足！当前库存: 3，需要: 5'`，可放行时 → None；`assert_stock_available(3, -5)` 抛同文案 `ValueError`，显式 `message` 时抛自定义文案。
- 缺口：无（attempt 1 的 F-02 已关闭）。

### P1-2b 剩余内联判定接入统一入口（t31，t39 收敛，t42 收口）
- **结论：达标（复算）**（attempt 1 此处为「未完全达标 → F-02」）
- 证据：`probe_f02.py`（AST + 词界正则，`fastapi_app/services` + `fastapi_app/shared` 非测试）
- 实测：内联 `new_current_stock < 0` 命中 **0**；直接 `current_stock` 比较仅 2 处且均非判定点（`inventory_reconcile.py:6` docstring、`dashboard/stats.py:208` 只读阈值）；守卫随策略在 `fastapi_app/shared/stock_concurrency.py:199`（其 `if not allow_negative_stock():` 在 :198）与 `:278`（if 在 :277）；`product_service.py:299` 走 `assert_stock_available(...)`。
- 缺口：无。

### P1-3 扣减统一乐观锁（t15；评审 t32）
- **结论：达标（复算 + 运行复现）**（attempt 1 的 F-01 根因 A 已关闭）
- 实测：`stock_out_service.py:66` 等写点统一走 `update_stock_with_optimistic_lock` / `apply_stock_delta_locked`；`stock_concurrency.py:255-298` 为 savepoint + SELECT + 条件 UPDATE + `rowcount` 分流，`retries` 耗尽抛 `StockConcurrentError`；`assert_stock_available` 在 UPDATE 之前。既有 4 例用例经 t41 重写桩后通过（`tests/test_stock.py` 全绿）。
- 缺口：无。

### P1-4 编号计数单调性（t16）
- **结论：达标（复算）**
- 实测：`fastapi_app/services/numbering_sequence.py` 逐字含 `GREATEST(numbering_counter.last_seq, CAST(:seed AS BIGINT)) + 1` 与 `... + :count`（并发不回退、seed 只作下限）。
- 缺口：无。

### P1-5 批量创建锁顺序（t17）
- **结论：达标（复算）**
- 实测：`order_batch_create.py` 的 `_lock_products` 内为 `.order_by(Product.id)` + `.with_for_update()`（全组统一顺序）；`:339` `async with db.begin_nested():`；`locked_ids.update(locked_here)` 位于 savepoint 正常退出之后；例外分支完整。
- 缺口：无。

### P1-6 DB CHECK 约束 + 原子守卫（t22 迁移；t39 条件化守卫；评审 t40）
- **结论：代码半达标（复算）；DB 半未上线（F-03，属运维）**
- 实测：`alembic heads` 单 head = `pg_standalone_061_add_product_stock_check`（符合单 head 红线）；`alembic upgrade 060:061 --sql` rc=0 且输出 `ALTER TABLE "product" ADD CONSTRAINT ck_product_current_stock_nonneg CHECK (current_stock >= 0);`；ORM `product.py` 的 `CheckConstraint('current_stock >= 0', name='ck_product_current_stock_nonneg')` 与迁移常量逐字一致；迁移 `revision='pg_standalone_061_add_product_stock_check'` / `down_revision='pg_standalone_060_fix_updated_at_varchar_columns'`；两处原子守卫仅在策略拒绝负库存时附加（§P1-2b）。
- 缺口：dev 库仍停 060、无该约束（F-03）。

### P1-7 ARQ 幂等键 + 循环 commit 批量化（t23）
- **结论：达标（复算）**
- 实测：`CommitBatcher` 提交次数 == `ceil(n/bs)`：n=450,bs=200 → 3；n=200,bs=200 → 1；n=0 → 0；n=1,bs=1 → 1；`after_commit` 仅在提交成功后按 1,2,3 递增触发；空 flush 返回 False 且不提交。`JobIdempotency`：键形如 `arq:idem:<ns>:<job_id>`；`mark(['a','b'])` 后 `load()` = `['a','b']`；跨 job / 跨 namespace 隔离为空；`mark([])` no-op；缺 job_id → `arq:idem:ns:anonymous`，`{'job_id': 42}` → `arq:idem:ns:42`。DB 侧无 `job_idempotency` 表（设计用 Redis 集合）。
- 缺口：无。

### P1-8 抵扣完整性校验（t33）
- **结论：达标（运行复现）**（attempt 2 此处为「用例达标但触发 F-06」）
- 实测：全量语境下该文件两例真实库用例（`test_real_db_failed_deduction_leaves_no_partial_writes` / `test_real_db_success_reports_actual_and_round_trips`）由 attempt 2 的 setup ERROR 变为 **PASSED**（计入 `3786 passed`）；定向 `pytest tests/test_stock.py tests/test_stock_concurrency.py fastapi_app/tests/test_order_deduction_completeness.py -q` → `47 passed in 3.27s` rc=0。用例断言覆盖「失败不留半成品」「成功回报实际值并往返一致」「部分生效绝不返回 success」，本次未删改任何断言。
- 缺口：无（F-06 已由 t43 关闭；仅余非阻断的 F-07）。

### P1-9 审计写入移出请求热路径（t18）
- **结论：达标（复算）**
- 实测：`_submit_audit_entry` 只把条目放入 `request.state.audit_pending_entries`；`_flush_request_audit_entries` 每请求至多一次直写；`_buffer_audit_entries` 走 Redis 列表，pushed=0 或异常时整批一次 `_write_audit_direct`；后者输出 `INSERT INTO audit_log (user_id, username, action, resource_type, resource_id, detail, ip_address, user_agent, request_id, status_code, created_at) VALUES (:..._0),(:..._1)` —— insert_count=1、params=22（11 列 × 2 行）、单次 execute + 单次 commit。
- 缺口：无。

### P1-10 门禁硬化（t19 AST 判定 / t20 mypy 扩面 / t30 ruff 棘轮）
- **结论：达标（复算）**
- 实测：`check_service_commit.py --self-test` → rc=0，14/14 PASS；`--json` → rc=1（命中即非零）`total=12`（keys: `scan_dir/total/violations`），与探针、`scripts/gate_baseline.json` 的 `service_commit=12` **三方一致**；独立 `ruff check scripts/ server_manager/ --output-format json --no-cache`（不经 `--select/--ignore`，与 `quality_gate.py` 同口径）→ 诊断 **60** 条、10 个文件（`scripts/diag/runtime_mode_probe.py` 23、`server_manager/app.py` 15、`windows_ops.py` 7、`service_ops.py` 4、`scripts/quality_gate.py` 3…；码分布 UP031=21、S110=18、F841=5、S112=4、RUF059=3），与基线 ruff=60 一致；`mypy` 实际检查 144 个文件，与 `mypy.ini` 条目计数吻合。
- 缺口：无（pip-audit 见 F-04）。

### P1-11 遗留 `.query(` 清理（t21；t37 follow-up）
- **结论：达标（复算）**
- 实测：`fastapi_app/` 非测试 `.py` 内 `.query(` 命中 **0**（唯一提及在 `fastapi_app/ARCHITECTURE_IMPROVEMENT_REPORT.md:90/93` 文档）；`SyncSelectQuery|build_search_query_sync|search_sync|search_for_bom_copy_sync` 在代码内仅剩同一文档提及 ⇒ 兼容层删除彻底。
- 缺口：无。

### P1-12 前端契约真校验（t24；t34 follow-up）
- **结论：达标（复算 + 灵敏度反证）**
- 实测：`node frontend-vite/scripts/check-route-alignment.mjs --json` → rc=0、`status=consistent`（pcPaths=30 / mobilePaths=15 / sharedPaths=12 / sharedFeatures=10 / unpairedMobileRoutes=4）；`python scripts/check_openapi_frontend_alignment.py --strict-allowlist --json` → rc=0，`specSource=app.openapi()`、`backendPaths=343`、`frontendLiteral=132`、`frontendTemplate=103`、`missing=[]`、`allowlisted=[]`、`staleAllowlist=[]`。**灵敏度反证（3 组）**：① 移动端路由改名 → node rc=**1** 且 `mobileOnlyPaths` 含改动名；② router 文件不存在 → node rc=**2**；③ api 目录注入未声明端点 → python 检查器 rc=**1** 并逐条列出 `missing`（allowlisted=false），api 目录不存在 → rc=**2**。
- 缺口：无。

### P1-residual 备份残留（t25 / t38）
- **结论：达标（运行复现 + 复算）**
- 实测：`_delete_backup_sidecars(filepath, errors)` 的失败已接入 `_execute_cleanup` 的错误聚合（`fastapi_app/services/backup/cleanup/service.py:547`，`:569-571` 的 `error_count/success` 公式未变）；伴随文件（`.meta` 含 `.zip.enc.meta`、`.record`）随主文件清理；用例断言 `Path.unlink` 抛 `OSError('模拟占用')` 时 `success is False`、`error_count==1`、文案含「伴随文件清理失败」+ 文件名。
- 缺口：下游影响已在 t38 披露（`backup_tasks.py:601` 因 `success=False` 走 ERROR 分支），属设计预期。

### 其他 follow-up
- **t35**（alembic 替身缺 `context`）：全量运行中该文件无 setup error —— **达标（运行复现）**。
- **t36**（清 `check_orphan_modules` 唯一 WARN）：`python scripts/check_orphan_modules.py` → rc=0 PASS，`mypy.ini` 条目 144 == 有入边 144，WARN 归零 —— **达标（复算）**。
- **t37 / t38**：见 P1-11 / P1-residual —— 达标。
- **t39 / t40**：见 P1-6（t39 条件化守卫经 AST 复核成立；t40 的 F-02「061 未上库」由我的只读 DB 探针独立确认）。
- **t41（F-01 修复）/ t42（F-02 修复）**：见 §2 / §3 —— 复核通过。

## 7 改动声明（未修改任何实现文件）

- **验证窗口内**（23:02–23:10）`git diff HEAD --shortstat` 与 `git status --porcelain` 三次取样恒定：`47 files changed, 1964 insertions(+), 625 deletions(-)` / 66 项 / `git diff HEAD --name-only` 47 个 tracked 文件 —— 无一项由本次验证产生；`HEAD = 73b3a93cc85a5dc6fec352a8d599679ec02df18f` 全程未变。
- **收尾复核（台账最后一次保存后）**：`git diff HEAD --shortstat` 已变为 `47 files changed, 1970 insertions(+), 625 deletions(-)`，而 `git status --porcelain` 仍 66 项、tracked 文件数仍 47、HEAD 仍 `73b3a93c` ⇒ 新增的 6 行来自**其它并发写者**（本台账为未跟踪文件，不落入任何 tracked 计数），不改变「本次验证零实现改动」的结论。
- 本次验证的写入仅两处：本台账 `docs/p1-verification-2026-10-01.md`（改写）+ 仓库外 `%TEMP%\t26-verifier3\`（本轮）与 `%TEMP%\t26-verifier2\`（attempt 2 探针复跑）下的探针脚本与命令输出。未 `git add/commit/stash`，未改 `scripts/gate_baseline.json`。
- 未执行任何服务重启 / `icacls` / `sc` / `schtasks`；未改 `.env`；DB 侧只发 SELECT 与连接尝试。

## 附：证据文件清单（仓库外）

**本轮（attempt 3）** `%TEMP%\t26-verifier3\`：`pytest.out/.rc`（3786 passed，rc=0）、`qg.out/.rc`（[PASS]，rc=0）、`mypy.out/.rc`（144 files，rc=0）、`directed.out`（47 passed）、`qg_self.out`（48 项）、`sc_self.out`（14 项）、`orphan.out`、`route.out`、`openapi.out`、`probe_f06.py` + `probe_f06.json`。
**attempt 2 探针在本轮工作树重跑** `%TEMP%\t26-verifier2\`：`static3.out`、`f023.out`、`counts3.out` + `probe_counts.json`、`runtime3.out` + `probe_runtime.json`、`controls3.out` + `probe_controls.json`、`db3.out` + `probe_db.json`、`probe_dburl3.out`、`probe_conn3.out`，以及 `probe_static.py` / `probe_f02.py` / `probe_counts.py` / `probe_runtime.py` / `probe_controls.py` / `probe_db.py`。
