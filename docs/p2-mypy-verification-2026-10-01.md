# P2-A5 类型注解批 独立验证报告（4 片 mypy 修复 + t52 跨片注解 + backup-eng 修复）

> 验证人：verifier（独立验证，未参与任何实现）｜任务：t50（attempt 1 + attempt 2 复验）｜日期：2026-10-02
> 验证对象（round 1）：HEAD `7c8b5ce3` 工作树上的未提交改动（103 个已修改文件 + 1 个新增测试文件）
> 验证对象（round 2）：HEAD `85aaa7c8` 工作树上的同批改动 + t53 修复（104 个已修改文件 + 2 个新增/未跟踪文件）；**最终判定见 §0b**
> 证据根目录：`%TEMP%\t50-verifier\`（全部命令的原始输出落盘，见 §7）

## §0 结论（verdict）

| 验收项 | 结果 | 摘要 |
|---|---|---|
| ① 四片显式路径 mypy 各 exit 0、0 error | **达标** | 24/24/25/24 文件全部 `Success: no issues found`，495 error → 0 |
| ② 改动集合 ⊆ t46–t49 inScope 并集，mypy.ini/scripts/tests 未改 | **达标** | 103 = 93∈97 union + 9（t52）+ 1（ocr，裁决 A）；mypy.ini / `scripts/**` / `tests/**` / `docs/**` 零改动 |
| ③ 新增 `# type: ignore` = 0 或逐条书面理由 | **达标** | 新增 0；全树现存 2 处均 HEAD 已有（§3.5） |
| ④ 全量 `pytest -q --ignore=tests/stress` exit 0 | **未达标（round 1 记录；round 2 已修复并全绿，见 §0b）** | `1 failed, 3792 passed, 268 skipped in 356.61s`；唯一失败 `tests/test_numbering_sequence_integration.py:104` 的 UTC/北京口径日期断言，隔离复现 + 机制已证（§5.4/§5.5），详见 §6 R-t50-1 |
| ⑤ `mypy --config-file mypy.ini`（144）exit 0 | **达标** | `Success: no issues found in 144 source files` |
| ⑥ `quality_gate.py --verbose` exit 0 且十类与基线一致 | **达标** | `[PASS]`，N+1=0 / bare except=5 / 函数长度=51 / Vue=7 / service_commit=12 / BOM=0 / Alembic=0 / env 漂移=0 / ruff=60 / pip-audit=0 |
| ⑦ 产出本文档 | **达标** | 本文件 |

**总判定：类型注解批本身达标**（97 模块 495 error 全部清零、226 路径零回归、反掩盖检查干净、语义复核未发现行为回归）。
**唯一红灯**是全量 pytest 的 1 个用例，已定位为「测试用 UTC 日期 / 产品用北京口径日期」的午夜边界缺陷，落在本批之外（§5.5/§5.6），建议一行测试修正（§6 R-t50-1）。

## §0b round 2 复验结论（t53 修复后，最终判定）

- 触发：captain 重派 t50 为 attempt 2（`attempt_id = 219c0c7d-430e-4ba2-bdbe-1b4149553ea6`），依赖 t46/t47/t48/t49/t52 均 completed；round-1 的唯一红灯由 **t53** 修复：`tests/test_numbering_sequence_integration.py`（7+/4−）删去 `from datetime import UTC, datetime`，改为 `from fastapi_app.services.numbering_sequence import allocate_sequence, business_date_str`，两处（`test_concurrent_allocation_unique`、`test_generate_number_async_batch_unique_and_continuous`）`date_str = datetime.now(UTC).strftime('%Y%m%d')` → `date_str = business_date_str()`，断言逐字未动。
- HEAD 变化：`7c8b5ce3` → `85aaa7c8`（docs(p2): P2-A 四片 + t52 全部落地（§6.32），仅 `docs/optimization-plan-2026-10-01-final.md` +13 行）；`git merge-base --is-ancestor 7c8b5ce3 HEAD` rc=0。
- **复验时钟窗口（关键）**：本轮全量 pytest 起止 2026-10-02 00:48:15 → 00:54:20（+08:00）= UTC 2026-10-01 16:48 → 16:54，**正处于 round-1 假红窗口（本地 00:00–08:00）之内**，故本轮绿色具有判别力（不是靠时间偏移“躲过”红灯）。

| 复验项 | 命令（python = `D:\erp_system\.venv\Scripts\python.exe`） | exit | 末行/摘要 |
|---|---|---|---|
| ① 全量串行 pytest | `-m pytest -q --ignore=tests/stress` | **0** | `3793 passed, 268 skipped in 358.72s (0:05:58)`；`FAILED`/`ERROR` 头部行 0 条 |
| ①′ 四片（片级复跑） | `-m mypy --config-file mypy.ini --cache-dir .mypy_cache/verify <shard1..4 路径>` | **0 / 0 / 0 / 0** | 各 `Success: no issues found in 24 / 24 / 25 / 24 source files`（error 0；基线 124/124/124/123 = 495） |
| ② ratchet 144 | `-m mypy --config-file mypy.ini`（`--cache-dir .mypy_cache/verify144`） | **0** | `Success: no issues found in 144 source files` |
| ③ 226 路径回归 | mypy 显式路径（`logs/_cap_mypy_shards.json` 的 shards ∪ clean = 226 项） | **0** | `Success: no issues found in 226 source files`（基线 495 error / 97 个非零文件 → 0） |
| ④ 门禁 | `scripts\quality_gate.py --verbose` | **0** | `[PASS]`；十类 = N+1 0 / bare except 5 / 函数长度 51 / Vue 7 / service_commit 12 / BOM 0 / Alembic 0 / env 漂移 0 / ruff 60 / pip-audit 0（与基线逐项一致；pip-audit 未安装仍为 WARN） |

- **用例总量核算**：round 2 `3793 passed + 268 skipped = 4061` = round 1 `3792 passed + 1 failed + 268 skipped = 4061` ⇒ 收集集合完全一致，仅 round-1 那 1 例状态由 failed 翻转为 passed（无新增/删除用例）。
- round-1 红灯用例本轮实测：`tests/test_numbering_sequence_integration.py::test_generate_number_async_batch_unique_and_continuous PASSED [ 17%]`（同文件 `test_concurrent_allocation_unique PASSED [ 17%]`）。
- **范围差异（与 round 1 对比，numstat 归一化口径）**：`git diff HEAD --numstat` = **104 files, 677(+), 405(−)**；`git status --porcelain -uall` = 104 `M` + 2 `??`（`docs/p2-mypy-verification-2026-10-01.md`＝本报告、`fastapi_app/tests/test_staging_import_extra_validations.py`＝t48 交付物）；与 round-1 的 103 条清单比对：**ADDED = `tests/test_numbering_sequence_integration.py`（7+/4−）、REMOVED = ∅**；`git diff HEAD --numstat -- mypy.ini scripts docs ruff.toml .pre-commit-config.yaml fastapi_app/tests` 输出为空。
- **反掩盖复扫（对 677 行新增行）**：`# type: ignore` 0 / `cast(Any` 0 / `setattr(` 0 / 裸 `X: Any =` 0 / `skip|xfail` 0 / `ignore-errors` 0；`noqa` 5（全 `S101`）、`assert ` 13、`cast(` 13（与 round 1 为同一批，逐条见 §3.2）；`REMOVED_CAST` = 0、`REMOVED_ASSERT` = 0；全文件级 `# type: ignore` 仍仅 HEAD 已有的 2 处（§3.5）。
- **最终判定：达标（verdict = pass）**。round-1 的 R-t50-1 已由 t53 关闭（见 §6）；残余观察项 R-t50-2 / R-t50-3 仍为 low，不阻塞。
- mypy 缓存说明：本轮片级与 226 路径复用了 round-1 的 `--cache-dir .mypy_cache/verify` / `verify226`（mypy 缓存按源码哈希校验；t53 仅改 `tests/**`，不在任何 mypy 清单内，不影响结论），ratchet 使用 `verify144`。

## §1 验证对象与基线

### 1.1 被验证的工作

| 片 | 任务 | 范围 |
|---|---|---|
| shard1 | t46 | 24 模块 / 基线 124 error |
| shard2 | t47 | 24 模块 / 基线 124 error |
| shard3 | t48 | 25 模块 / 基线 124 error |
| shard4 | t49 | 24 模块 / 基线 123 error |
| 跨片 | t52 | 9 个 clean 文件的注解真修复（`shared_models/*` + `services/approval_log_service.py`） |
| backup-eng | t48 裁决 f | `shared/stock_concurrency.py` cast 收窄、`services/backup/records.py` 函数长度（≤80） |

### 1.2 基线数据（只读，来源 `logs/_cap_mypy_shards.json` + `logs/_cap_mypy_residual_list.txt`）

- 四片 sizes = **24 / 24 / 25 / 24**，union = **97 个唯一模块、互不重叠**；
- 每片载荷 loads = **124 / 124 / 124 / 123**；counts 共 97 条，合计 **495 个 mypy error**；
- clean = **129** 个本就零错文件；97 + 129 = **226**（= residual_list 行数），union ⊆ residual 成立。

### 1.3 范围合规性（工作树实测，HEAD = `7c8b5ce3`）

- `git status --porcelain -uall` = **104 项** = 103 `M` + 1 `??`（`fastapi_app/tests/test_staging_import_extra_validations.py`，新增，经 captain 认可为本批合法新增）；无 `D`、无 `A`；
- `git diff HEAD --numstat` = **103 files, 670 insertions(+), 401 deletions(-)**（`git diff HEAD --shortstat` 同）；
- `mypy.ini`、`scripts/**`、`tests/**`、`docs/**`、`ruff.toml`、`scripts/gate_baseline.json` **均无改动**；
- 归属：
  - **93 个** ∈ 97 union（t46–t49 inScope）；
  - **9 个** = t52 的 9 文件（均不在 97 内、属 clean129）：`fastapi_app/shared_models/{craft_work,daily_production_record,material_registration,packaging_record,production_plan,purchase_order,purchase_plan,approval}.py` + `fastapi_app/services/approval_log_service.py`；
  - **1 个** = `fastapi_app/services/ocr_fuzzy_match.py`（6+/2−，t48 裁决 A 认可）；
  - 97 union 中**未改动 4 个**（本就零错）：`services/order/approval_flow.py`、`services/purchase_plan_crud_ops.py`、`api/v1/endpoints/backup/restore.py`、`services/backup/__init__.py`；
- EOL 口径（`core.autocrlf=true` 下用 numstat 判定，不做字节比对）：抽查 `shared/stock_concurrency.py` / `services/bom_service.py` / `services/purchase_order_crud.py` / `services/backup/records.py` / `shared_models/purchase_order.py` 均 `i/lf w/crlf` ⇒ numstat 归一化口径正确。

## §2 逐片实跑结果（本人执行）

| 片 | 模块数 | 基线 error | 本次实测 error | 输出末行 | exit |
|---|---|---|---|---|---|
| shard1 | 24 | 124 | **0** | `Success: no issues found in 24 source files` | 0 |
| shard2 | 24 | 124 | **0** | `Success: no issues found in 24 source files` | 0 |
| shard3 | 25 | 124 | **0** | `Success: no issues found in 25 source files` | 0 |
| shard4 | 24 | 123 | **0** | `Success: no issues found in 24 source files` | 0 |
| **合计** | **97** | **495** | **0** | — | **0** |
| 补：226 路径（97 union + 129 clean） | 226 | 0 | **0** | `Success: no issues found in 226 source files` | 0 |
| 补：ratchet（`mypy.ini` 全量） | 144 | 0 | **0** | `Success: no issues found in 144 source files` | 0 |

命令原文（`D:\erp_system`，python 一律 `.venv\Scripts\python.exe`）：

```powershell
# 每片（模块清单取自 logs/_cap_mypy_shards.json 的 shards[i]，逐片显式路径）
.venv\Scripts\python.exe -m mypy --config-file mypy.ini --cache-dir .mypy_cache/verify <shard_i 的 N 个模块>
# ratchet
.venv\Scripts\python.exe -m mypy --config-file mypy.ini
# 226 路径回归（clean129 + 四片 union）
.venv\Scripts\python.exe -m mypy --config-file mypy.ini --cache-dir .mypy_cache/verify226 <226 个模块>
```

mypy 版本：**2.3.1 (compiled: yes)**。证据：`shard1..4.out`、`ratchet144.out`、`mypy226.out`（尾部各含 `MYPPY_EXIT=0` 等退出码行）。

## §3 反掩盖审查（防止用 Any / ignore 把错误“捂住”）

### 3.1 计数表（对 670 行新增行逐行正则统计）

| 模式 | 新增计数 | 判定 |
|---|---|---|
| `# type: ignore` | **0** | 达标 |
| `cast(Any` | **0** | 达标 |
| 直接 `setattr(` | **0** | 达标 |
| 直接变量注解 `X: Any =`（非泛型实参） | **0** | 达标 |
| 新增 `assert ` | 13 | 全部为收窄断言，未替换错误处理（§3.4） |
| 新增 `noqa` | 5（全为 `S101`） | 与上面 assert 配对，理由见 §3.4 |
| 新增 `cast(` | 13 | 逐条见 §3.2 |
| 新增行含 `Any` | 66 行（其中 48 行是泛型实参 `...Any]`） | 详见 §3.3 |
| 直接返回值 `-> Any` | **1** | `services/backup/restore.py` 的 `_task_value`，理由见 §3.3 |
| `ignore-errors` 模块级指令 | 0 | 达标 |

### 3.2 13 处 `cast(` 逐条

| 类别 | 数量 | 位置 |
|---|---|---|
| `cast(CursorResult, result).rowcount`（DML rowcount） | 7 | `shared/stock_concurrency.py`（:205、:285）、`services/staging/order.py`、`services/staging/stockin.py`、`services/staging/stockout.py`、`services/notification_service.py`、`services/order_batch_service.py` |
| IO / zip 类型收窄 | 6 | `main.py`（`cast(QueuePool, async_engine.pool)`）、`services/backup/dump.py` ×4（`cast(IO[bytes], …)`）、`services/backup/format_strategy.py`（`cast(zipfile.ZipExtFile, self._zf.open(name))`） |

说明：`typing.cast` 在运行期是恒等函数，**不改变任何行为**；`CursorResult` 是 SQLAlchemy 对 DML 执行结果的实际类型，原先的 `result.rowcount` 在运行期本就由驱动提供，故等价。

### 3.3 `Any` 使用面

- 新增行中出现的 `Any` 共 66 行，绝大多数是**容器元素类型**（`dict[str, Any]` / `list[dict[str, Any]]` / `dict[str, dict[str, Any]]`），集中在 `api/v1/endpoints/{customer,material_registration,order,purchase_center/export_utils,purchase_plan}.py`、`services/{bom_service,daily_production_service,customer_sampling/grouping}.py`、`services/backup/**` 等原本返回裸 dict 的接口层/汇总层——这些函数的返回值在注解前是「未注解（隐式 Any）」，加注解后至少明确了容器形状，**不是**把具体类型退化为 Any。
- 唯一的**非泛型** Any：`fastapi_app/services/backup/restore.py` 的 `def _task_value(pair: tuple[str, Any]) -> Any:`——该辅助函数从异构任务对里取值，元素类型确实无法收敛为具体类型，属可接受用法（书面理由即本行）。
- 未发现 `Any` 被用于吞掉本可收敛的类型（对比：同一批中 `services/backup/records.py` 用 `TypedDict`、`services/backup/{metrics,orchestration}` 用 `TypedDict`、`shared_models/*` 用 `Mapped[date]/Mapped[Decimal]` 收敛，属「能收敛就收敛」的做法）。

### 3.4 13 处新增 `assert` 与 5 处 `noqa: S101`

- `fastapi_app/api/ws.py` ×2：`assert engine is not None`（`async_engine` 在模块导入期初始化，此处仅为向 mypy 收窄 Optional，附带注释说明）；
- `fastapi_app/services/backup/orchestrator.py`：`assert manifest_dict is not None`（同一模式）；
- `fastapi_app/tasks/batch_tasks.py` ×2：`assert product is not None`（同一模式，配 `# noqa: S101`）；
- `fastapi_app/services/batch_import_service.py` ×7：`assert data_list is not None` / `assert case is not None`，注释明确契约「`_read_excel_sheets` 失败时返回 None，而 err 已在上一行判空」（即断言条件前置已保证，运行时不会触发）。
- 均为「契约已由前置分支保证」的收窄断言，**没有**把 `raise`/错误处理替换成断言，也没有删除异常分支。

### 3.5 全树现存的 `# type: ignore`（103 个改动文件内全文件扫描）

共 **2** 处，均为 **HEAD 已存在**（新增行统计为 0，即本批未新增）：

| 位置 | 内容 | 归属 |
|---|---|---|
| `fastapi_app/core/prod_runner.py:401` | `os.killpg(os.getpgid(pid), signal.SIGTERM)  # type: ignore[attr-defined]` | HEAD 已有；该文件本批仅 :83 加了 2 行（日志流初始化） |
| `fastapi_app/services/order_batch_create.py:136` | `if not product.factory:  # type: ignore[union-attr]` | HEAD 已有；本批仅新增 `def _fail(...) -> NoReturn` 帮助 mypy 在调用点收窄 |

## §4 语义等价复核（AST + 语句级 + 关键 hunk 人工复核）

### 4.1 机械方法

1. **去注解 AST 对比**（`ast` 解析 HEAD 版本 vs 工作树版本，剥除 `Import/ImportFrom`、`AnnAssign` 注解、`arg.annotation`、`returns`、`if TYPE_CHECKING:` 块后比较 `ast.dump`）：28 个文件完全一致；2 个仅差 assert；73 个仍有差异（**限制**：标识符改名会被判为差异，故只能当筛选器，不能当结论）；
2. **语句级规范化 diff**（同上剥除后 `ast.unparse` 再逐行 diff，消除排版噪声）：75 个文件、**599 行语句级差异**，分桶 = 赋值 240 / 其他 136 / return-raise-await-assert 120 / 控制流 103；
3. 对其中**含 `cast(` / `isinstance` / `raise` / `getattr` / `noqa` / `type: ignore` 的 35 行高风险项**做逐条人工核对，并对 t52 九文件与 backup-eng 三个文件读完整 hunk。

### 4.2 t52 九文件（跨片注解真修复）

- `shared_models/{craft_work,daily_production_record,material_registration,packaging_record,production_plan,purchase_plan}.py`：`Mapped[datetime]` → `Mapped[date]`（对应 `Date` 列）+ `from datetime import UTC, date, datetime`；
- `shared_models/purchase_order.py`：另将 5 处 `Mapped[float|None]` / `Mapped[float]` 改为 `Decimal`（对应 `Numeric` 列）+ `from decimal import Decimal`；
- `shared_models/approval.py`：新增 `if TYPE_CHECKING: logs: Mapped[list[ApprovalLog]]`（`TYPE_CHECKING` 已在 :7 导入，:14/:71 已有两个同类块）；
- `services/approval_log_service.py`：`db: AsyncSession` → `AsyncSession | Session` + `from sqlalchemy.orm import Session`；
- 结论：**全部为注解/导入层面**，无运行期语句变化（`Mapped[...]` 仅是类属性注解，SQLAlchemy 在映射期由显式 `mapped_column` 决定列类型）。

### 4.3 行为等价的关键 hunk 逐条

| 位置 | 改动 | 等价性判定 |
|---|---|---|
| `fastapi_app/shared/stock_concurrency.py:205,:285` | `result.rowcount` → `cast(CursorResult, result).rowcount` | 等价：cast 运行期恒等，DML `execute` 结果本就是 `CursorResult`；这也是 t49 首版用 `isinstance` 后破坏测试替身（MagicMock）的修正版，回归到与 HEAD 等价的写法 |
| `fastapi_app/services/backup/records.py` | 新增模块级 `class _BackupRecord(TypedDict)`；`errors: list[str] = []`、`backups: list[_BackupRecord] = []`；`if b['is_incremental'] and (base_timestamp := b['base_timestamp']):` + `normalized_base = normalize_backup_ts(base_timestamp)` | 等价：TypedDict 在运行期只是 `dict` 的子类声明，不改数据形状；walrus 仅把「先判空再取值」合并为一次取值，收窄后调用 `normalize_backup_ts`，函数长度回到 ≤80（门禁函数长度仍为基线 51） |
| `fastapi_app/services/bom_service.py` | `~model_cls.id.in_(ids) if ids else True` → `... else true()`（2 处）；`item`→`row`/`filling_row` 改名；`bom_data: dict[str, Any]` 注解 | 等价：`true()` 是 SQLAlchemy 2.0 推荐的布尔字面量构造（Python `True` 作 where 条件在 2.0 走同一路径并已废弃告警），生成的 `WHERE true` 语义相同；改名与注解无运行期影响 |
| `fastapi_app/services/purchase_order_crud.py`（裁决 f，恰 4 处） | `_apply_item_fields` 返回值改为 `Decimal`（`line_total = item.unit_price * item.quantity; item.total_price = line_total; return line_total`），调用点改 `line_total = _apply_item_fields(...)` 与 `total_amount += line_total` | 等价：原先 `total_amount += item.total_price` 读的正是刚赋值的同一 Decimal 对象；改为直接用局部变量不再经 ORM 属性回读。**注意**：若将来有事件监听器在 `unit_price/quantity` 赋值时改 `total_price`，两者会分叉——当前代码没有这类监听器，全量用例未见差异 |
| `fastapi_app/services/ocr_fuzzy_match.py`（裁决 A） | 新增 `if TYPE_CHECKING: from fastapi_app.shared_models import Customer, Product`；两处返回注解 `tuple[object | None, float]` → `tuple['Product | None', float]` / `tuple['Customer | None', float]` | 等价：字符串前向注解 + TYPE_CHECKING 导入在运行期完全不执行 |
| `fastapi_app/api/ws.py:121` | `await _consume_ws_ticket(ticket)` → `await _consume_ws_ticket(ticket) if ticket else None` | 等价：`_consume_ws_ticket` 自身首行即 `if not ticket: return None`（`ws.py:61-62`），短路后结果相同 |
| `fastapi_app/services/approval_service.py` | `dict(stats_result.all())` → `{status: count for status, count in stats_result.all()}`；`json.loads(approval.operation_data)` → 先取 `raw_operation_data`、`None` 则 `raise TypeError`（由既有 `except (json.JSONDecodeError, TypeError)` 转成 `ValueError`） | 等价：`dict(rows)` 与字典推导对两列 Row 结果相同；`json.loads(None)` 原本也是 `TypeError`，被同一 except 捕获，错误语义一致 |

### 4.4 本批新增的 10 处 `raise` / 10 处 `None` 守卫（**运行时新分支，须登记**）

| 文件 | 新增守卫 → 行为 |
|---|---|
| `services/approval_service.py` | `if raw_operation_data is None: raise TypeError('审批数据为空')` → 由既有 except 归一为 `ValueError`（与旧行为一致） |
| `services/approval_service.py` | `if product_id is None: raise ValueError(f'产品ID {product_id} 不存在')` → 旧代码把 `None` 传给 `get_product_for_update` |
| `services/order/commands.py` | 同上（`product_id is None`） |
| `services/order/deduction.py` ×2 | `if order_product_id is None: raise ValueError(...)` |
| `services/stock_out_service.py` | `if product_id is None: raise ValueError(...)` |
| `services/staging/order.py` | `if staging_product_id is None: raise ValueError(...)` |
| `services/staging/stockin.py` | `if product_id is None: raise ValueError('备货…产品不存在(ID:…)')` |
| `services/staging/stockout.py` | `if product_id is None: raise ValueError('出货…确认失败: 产品不存在')` |
| `api/v1/endpoints/backup/records.py` | `if not isinstance(func, FunctionType): raise HTTPException(500, '定时任务配置无效')` |
| `services/order_batch_service.py` / `notification_service.py` / `staging/*` | `cast(CursorResult, …).rowcount`（含 `or 0`）——非新分支 |

判定：9 处是「可空外键属性 → 先判空再 fail-fast」的收窄；在旧代码里 `None` 会流入 `WHERE id = NULL` 的查询或无意义的库存写入，属**从静默错误变为显式错误**，方向正确。风险等级 **low**（若某业务流程允许 `product_id` 为空且依赖旧行为，则会改为报错；全量用例 3792 passed 未出现该类失败）。

## §5 门禁与测试（全部本人实跑）

### 5.1 `quality_gate.py --verbose`

```powershell
.venv\Scripts\python.exe scripts\quality_gate.py --verbose
# exit 0  [PASS]
```

十类与基线逐项一致：N+1 查询=0 / 裸 except=5 / 函数长度=51 / 前端 Vue=7 / service 层裸 commit=12 / UTF-8 BOM=0 / Alembic 单 head·多 root=0 / 环境键漂移=0 / ruff 违规=60 / pip-audit=0；`pip-audit` 未安装仅输出 WARN（与基线一致，无新增忽略项）。证据：`qg.out`（尾部 `QG_EXIT=0`）。

### 5.2 mypy ratchet（`mypy.ini` 口径）

```powershell
.venv\Scripts\python.exe -m mypy --config-file mypy.ini
# Success: no issues found in 144 source files   (exit 0)
```

### 5.3 全量 pytest（串行，无并发）

```powershell
.venv\Scripts\python.exe -m pytest -q --ignore=tests/stress
# 1 failed, 3792 passed, 268 skipped in 356.61s (0:05:56)   → exit 1
```

- 起始 `2026-10-02T00:36:32`（本机时间，UTC+8），证据 `pytest.out`（UTF-16 原始输出 + 尾部 `PYTEST_EXIT=1` / `PYTEST_END`）、`pytest_meta.txt`；
- 用例总量核算：上一轮 P1 验收基线 `3786 passed + 268 skipped = 4054`；本轮新增测试文件 `fastapi_app/tests/test_staging_import_extra_validations.py` 带来 **+7** ⇒ 应收集 **4061**，实测 `3792 + 268 + 1 = 4061` **完全对上**，即除下述 1 例外**无任何回归/新增失败**；
- 唯一失败：

  ```
  FAILED tests/test_numbering_sequence_integration.py::test_generate_number_async_batch_unique_and_continuous
  tests\test_numbering_sequence_integration.py:104: in test_generate_number_async_batch_unique_and_continuous
      assert all(n.startswith(f'{prefix}-{date_str}-') for n in numbers)
  E   assert False
  ---
  1 failed, 3792 passed, 268 skipped in 356.61s (0:05:56)
  ```

### 5.4 该失败的定位（隔离复现）

```powershell
.venv\Scripts\python.exe -m pytest -q "tests/test_numbering_sequence_integration.py::test_generate_number_async_batch_unique_and_continuous"
# 1 failed in 2.43s          → exit 1（100% 复现）
.venv\Scripts\python.exe -m pytest -q tests/test_numbering_sequence_integration.py
# 1 failed, 1 passed in 3.10s → exit 1（同文件内 test_concurrent_allocation_unique 通过）
```

同一用例内 **:101-:103 三条实质断言（批内不重复 / 单调 / 恰为 1..5）全部通过**，只有 **:104 的日期前缀断言**失败 ⇒ 取号内核本身正确，失败点纯粹是「日期串口径」。

### 5.5 机制证明（UTC vs 北京口径）

```text
本机时钟（同一时刻）：
  local    20261002 00:42:55      (东八区)
  utc      20261001 16:42:55
  biznow   20261002 00:42:55      (business_now())
  test 计算出的 date_str = datetime.now(UTC).strftime('%Y%m%d') = 20261001
```

- 测试侧：`tests/test_numbering_sequence_integration.py:94` `date_str = datetime.now(UTC).strftime('%Y%m%d')`（**UTC**）；
- 产品侧：`fastapi_app/services/numbering_sequence.py:31-33` `def business_date_str() -> str: ... return datetime.now(_BUSINESS_TZ).strftime('%Y%m%d')`（**北京口径**，由 commit `0b2b124f feat(numbering): 统一北京口径+单一取号内核+启动对账` 引入）；
- 两者在本地时间 **00:00–08:00** 之间必然相差一天，此时间段内该断言必红；本地 08:00–24:00 之间 UTC 日期与北京日期相同，断言才通过；
- 这解释了为什么上一轮 P1 验收（`2026-10-01T23:41:34` 起跑，UTC 仍在 10-01）是 **0 failed**，而本轮（`00:36:32` 起跑）红了 1 条。

### 5.6 归属证明（与本批无关）

- `tests/**` 与 `fastapi_app/services/numbering_sequence.py` **均不在** 本批 104 项改动清单中（§1.3）；
- `git log` 溯源：`business_date_str` 由 `0b2b124f`（编号北京口径统一）引入，测试文件最近三次修改为 `e96a1631` / `d6530409` / `e430ddf9`，**都早于**本批；
- 本批 103 个文件中没有任何编号/取号实现文件（`git diff HEAD --numstat | grep number` 为空）。
⇒ 该失败是**既有的测试日期口径缺陷**在午夜时间窗暴露，不是本批引入的回归。

## §6 未达标项与残余风险

### R-t50-1（medium，**本批之外，建议尽快修**）午夜全量测试必红

- 现象：本地时间 00:00–08:00 之间跑全量 pytest，`tests/test_numbering_sequence_integration.py::test_generate_number_async_batch_unique_and_continuous` 必失败（:104 日期前缀断言）；
- 根因：测试用 `datetime.now(UTC)`，产品用北京口径 `business_date_str()`（`fastapi_app/services/numbering_sequence.py:31-33`）；
- 建议修复（**一行测试改动，不在 t50 的 inScope 内，需另开任务**）：把 `tests/test_numbering_sequence_integration.py:94`（及同类位置 :80）的 `datetime.now(UTC).strftime('%Y%m%d')` 换成 `business_date_str()`（`from fastapi_app.services.numbering_sequence import business_date_str`）；
- 影响面：仅测试断言，生产取号逻辑正确；但会让任何夜间执行的门禁/验收出现假红（captain 的最终验收若跨过午夜同样会踩到）。

**状态更新（round 2）**：本项已由 **t53** 修复并关闭 —— `tests/test_numbering_sequence_integration.py` 改用产品口径 `business_date_str()`（7+/4−，断言未削弱）；round 2 全量 pytest 在同一「本地 00:00–08:00」窗口内 `3793 passed / 0 failed`（见 §0b）。以下为 round-1 原始记录，保留追溯。
### R-t50-2（low）10 处新增 fail-fast 守卫

见 §4.4：9 处可空外键 `is None → raise ValueError`、1 处 `isinstance(func, FunctionType) → HTTPException(500)`。方向正确（把静默错误变显式），但属**运行期新分支**，若存在「允许空产品 ID 且依赖旧行为」的冷门流程会由“静默”变“报错”。当前全量用例未出现该类失败。

### R-t50-3（low）唯一 `-> Any`

`fastapi_app/services/backup/restore.py` 的 `def _task_value(pair: tuple[str, Any]) -> Any:`（异构任务对取值），已给书面理由；不计入反掩盖违规。

### 其它观察（非本批，仅供台账留档）

- `fastapi_app/services/purchase_order_crud.py` 的 `total_amount += line_total` 不再经 ORM 属性回读，若将来引入 `total_price` 的事件监听器需重新评估（当前无）；
- 本批未触碰 `mypy.ini`，ratchet 覆盖面仍为 144 文件；~96 个未纳入模块仍是 P2/P3 余量（与既有台账一致）。

## §7 附录：证据与命令清单

### 7.1 证据文件（`%TEMP%\t50-verifier\`）

| 文件 | 内容 |
|---|---|
| `shard1.out` … `shard4.out` | 四片 mypy 原始输出 + `MYPPY_EXIT=0` |
| `ratchet144.out` | `mypy --config-file mypy.ini` + `RATCHET_EXIT=0` |
| `mypy226.out` | 226 路径 mypy + `MYPPY226_EXIT=0 paths=226` |
| `qg.out` | `quality_gate.py --verbose` 十类输出 + `QG_EXIT=0` |
| `pytest.out` / `pytest.u8.txt` | 全量 pytest 原始输出（1 failed, 3792 passed, 268 skipped）+ `PYTEST_EXIT=1` |
| `pytest_numbering_single.out` / `pytest_numbering_file.out`（+`.u8.txt`） | 隔离复现（1 failed / 1 failed+1 passed） |
| `scope\porcelain_all.u8.txt`、`scope\numstat.u8.txt` | 104 项状态清单、103 文件 numstat |
| `probe\diff_u0.txt`、`probe\diff_full.txt` | 全量 diff（-U0 / 带上下文） |
| `probe\scan2.txt`、`probe\scan3.txt` | 反掩盖扫描（Any / type: ignore / noqa / assert 溯源） |
| `probe\ast_equiv2.json` | 去注解 AST 对比原始结果 |
| `probe\stmt_diff.json`、`probe\stmt_digest.txt`、`probe\risky_only.txt` | 语句级规范化 diff（599 行）与 35 行高风险清单 |
| `probe\raises_scan.u8.txt` | 新增 raise / None 守卫清单 |
| `probe\ws_appr_diff.u8.txt`、`probe\bom_po_diff.u8.txt`、`probe\raises.u8.txt` | 关键 hunk 原文 |
| `%TEMP%\t50-verifier-shards.json` | 基线分片数据副本（= `logs/_cap_mypy_shards.json`） |
| `r2_pytest.out` | **round 2** 全量 pytest 原始输出（UTF-16，3366062 B / 18756 行）+ `R2_PYTEST_EXIT=0` / `R2_PYTEST_START` / `R2_PYTEST_END` |
| `r2\mypy_battery.out.json`、`r2\mypy_battery.log` | **round 2** 六项 mypy（shard1–4 / ratchet144 / paths226）的 exit、error 数、基线、耗时、末行 + 原始输出 |
| `r2\qg.out`、`r2\qg.excode.txt` | **round 2** `quality_gate.py --verbose` 十类输出 + `R2_QG_EXIT=0` |
| `r2\scan_r2.py`、`r2\scan_r2.out` | **round 2** 反掩盖复扫脚本与结果（FILES_CHANGED/ADDED/REMOVED 计数 + 各类模式命中） |
| `r2\numstat.txt` | **round 2** `git diff HEAD --numstat` 原始清单（104 行） |
| `r2\mypy_battery.py`、`r2\read_pytest.py`、`r2\readbattery.py`、`r2\readqg.py` | **round 2** 驱动与读取脚本（可复算） |

### 7.2 新增测试文件元数据（本批唯一新增文件）

- 路径：`fastapi_app/tests/test_staging_import_extra_validations.py`（未跟踪 `??`）
- 大小 9681 B｜mtime `2026-10-02 00:17:33`｜SHA256 `757C08F96D7AE171E8742C3C5C5227465B6AE86E276A4B6D0A3934C79E979F88`
- 7 个用例：`test_async_validator_errors_are_collected` / `test_empty_validation_keeps_row` / `test_validator_value_error_is_row_failure` / `test_generic_source_awaits_validator` / `test_stockin_import_surfaces_validator_message` / `test_stockout_import_surfaces_validator_message` / `test_valid_row_still_imported`
- 覆盖对象正是本批 staging 相关收窄改动的行为面（导入校验失败信息传递），已随全量 pytest 通过。

### 7.3b round 2 证据与纪律补充

- round 2 的全部证据见 §7.1 中 `r2_*` / `r2\*` 各条，均为本轮实跑落盘（未引用 round-1 输出作为本轮结论依据）。
- round 2 同样未执行任何 git 写操作，未修改实现/测试/配置/基线文件（唯一写入为本报告自身）；未重启服务，未使用 `sandbox_permissions`；跑 pytest 前已确认无并发 pytest 进程（仅 uvicorn `127.0.0.1:5002 --workers 8`、arq worker、prod_runner 在运行）。
### 7.3 纪律声明

本验证仅只读业务代码 + 运行验证命令；**未**执行 `git add/commit/checkout/stash`，**未**修改任何实现/测试/配置/基线文件，唯一写入即是本文件；未重启服务，未执行 `icacls/sc/schtasks`，未使用 `sandbox_permissions`；python 一律 `D:\erp_system\.venv\Scripts\python.exe`；数据库仅用于既有测试夹具，无生产库写入；未改 `scripts/gate_baseline.json`（单写者 gatekeeper）。
