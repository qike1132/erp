# 订单号体系统一 —— 设计文档

- 日期：2026-09-29
- 状态：待评审
- 作者：Claude（与用户共同确认）

## 1. 背景与审核结论

2026-09-29 对生产库做了一次只读审核（脚本：`_audit_order_no.py`）。审核对象确认为
`localhost:5432/erp_system` —— 本机 9 个库中唯一处在最新迁移 `pg_standalone_058` 的库，
运行时配置来自仓库根 `.env`（`prod_runner._load_dotenv` 与 `core/config.py` 均加载它），
nginx 把 `127.0.0.1:5002` 反代到它（`config/nginx-windows.conf:26`）。

**结论：编号机制在生产是生效的。**

| 实体 | 前缀 | 生产行数 | 格式合规 | 重复 | NULL |
|---|---|---|---|---|---|
| 客户订单 `order` | PO | 7 | ✓ | 无 | 无 |
| 采购订单 `purchase_order` | CG | 4 | ✓ | 无 | 无 |
| 备货入库 `stock_in` | BH | 1 | ✓ | 无 | 无 |
| 出货 `stock_out` | SO | 1 | ✓ | 无 | 无 |
| 客户打样 `customer_sampling_project` | CS | 2 | ✓ | 无 | 无 |

`numbering_counter` 有 13 行、水位正常推进。数据量小属正常：`backups/pre-launch-purge/purge_report_20260924_094417.json`
显示 2026-09-24 上线前清过数据（删 3733 张订单、并把 `numbering_counter` 的 34 行一并清零），
系统 9-24 才上线。

同时发现 4 类问题：

### P0 —— E2E 写路径测试直打生产库，并绕过归档裸删订单

- `tests/e2e_api/conftest.py:72` 默认 `BASE_URL=http://127.0.0.1:5002`，即生产后端。
- `tests/e2e_api/conftest.py:88` 在**收集期**把 `ERP_E2E_REAL_DATABASE_URL` 固化为生产 DSN，
  刻意绕过 `tests/conftest.py:204-234` 往 `erp_system_test` 的重定向。
- `tests/e2e_api/test_write_paths.py:176` 的 `_cleanup` 用裸 SQL `DELETE FROM "order"` 删生产行，
  不走 API 删除路径，因此不写 `backups/server/order_deletions/` 归档。

生产库内的抓现行证据：

- `backups/server/order_deletions/order_68825_*.json` 中被删订单的客户名是
  `__e2e_wp__客户_1790476746921`，正是该测试的造数前缀 `_PREFIX = "__e2e_wp__"`。
- 09-28 那天 PO 计数表已走到 45，而订单表只剩 1 行（`PO-20260928-0001`）——
  44 个号被造单消耗、再被裸删清掉，只归档了 1 条。

### P1 —— 两套编号实现争同一段号空间（潜在重号）

同一组 `(PO, Order, order_no)` 被两条**活的**路径同时使用：

- 批量导入 → `fastapi_app/shared/stock_crud_service.py:25` → `core/number_generator.py`（同步、内存计数、advisory lock）
- 入口 `fastapi_app/api/v1/endpoints/tasks.py:161,186` 入队 →
  `fastapi_app/tasks/batch_tasks.py:148,173` → 同上
- 正常下单 / 批量建单 → `fastapi_app/services/numbering.py:105` → `numbering_counter` 原子表（异步）

`(BH, StockIn, stockin_no)` 同样重叠。而 `services/numbering.py` 的 `generate_number_async`
**不取** core 用的那把 advisory lock（`numbering.py:95-100` 只有 `asyncio.Lock`），两条路径之间零互斥。
两套水位**已经分叉**：生产 09-28 计数表 = 45 而 `order` 表 max = 1。core 从表 max 往上爬（2,3,4…），
services 从计数表往上走（46,47…），迟早撞同一个号。唯一索引会把它变成「插入失败 / 500」而非静默重号——
有兜底，但会报错。

### P2 —— 时区口径分裂（潜伏未爆发）

`services/numbering.py` 用 **UTC** 日期（`:60,:93,:142`），`core/number_generator.py` 用**本地（北京）**
日期（`:107,:152`）。北京时间 00:00–08:00 这 8 小时里两条路径对同一时刻给出不同日期段，而 PO/BH 同时受两套影响。

生产目前 7 单都不在该窗口（北京 00:00–07:59 下单数 = 0），故为潜伏。

配套缺陷：`fastapi_app/services/numbering_sequence.py:110-113` 的 `read_daily_max` 用 UTC 日期去比
`func.date(order_date)`，而该列是 `timestamptz`，PG 按会话时区（Asia/Shanghai）求值，同类错配;
同处 `:114` 用**字符串降序**取 max，序号过 9999 后 `'9999' > '10000'`，字典序失效。

### P3 —— 死代码里的错误编号

`fastapi_app/services/order_purchase_sync.py:55` 硬编码 `order_no=f'PO-PENDING-{order_id}'`——
绕过生成器、前缀错（采购单应为 CG）、无日期段。全仓无任何调用者，仅在
`fastapi_app/core/domains.py:59` 的 `DOMAIN_SERVICE_MAP` 里被列为字符串；全仓无测试引用它。
一旦复活即产出不合规编号。

## 2. 目标与非目标

**目标**

1. 编号只保留**一套**实现、**一张**水位表。
2. 编号日期段统一为**北京时间**（Asia/Shanghai），与业务日历、报表、`pg_standalone_058` 的时区修正口径一致。
3. 取号种子（seed）正确，杜绝口径切换期与序号 >9999 时的重号。
4. 可观测：编号异常可被监控发现并告警。
5. 消除 P0 运行风险与 P3 死代码。

**非目标**

- 不回填、不重置存量编号（见 §5）。
- 不给「引用副本列」加唯一约束（语义上允许多行引用同一单号）。
- 不处理 `stock_in.stockin_date` 等**日期列**的 8 小时偏差问题——那是日期口径问题，不是编号问题，
  已单独记录，本次不混范围。
- 不新建 E2E 专用环境（本次只做拦截；是否建环境见 §10）。

## 3. 已确认决策

| 决策点 | 选择 |
|---|---|
| 改造范围 | 全量：统一 + 时区 + 约束/监控加固 |
| 编号日期段口径 | **北京时间**（Asia/Shanghai） |
| 两套实现收敛方式 | **A：全收敛到异步实现**（`services/numbering.py`） |
| 编号水位偏差告警 | **做** |
| `order_purchase_sync.py` | **删除** |
| E2E 隔离 | **默认不指生产 + 生产指纹拦截** |

## 4. 设计

### 4.1 单一取号内核与唯一时间口径

`fastapi_app/services/numbering_sequence.py` 成为唯一取号实现，新增唯一口径函数：

```python
from zoneinfo import ZoneInfo

_BUSINESS_TZ = ZoneInfo('Asia/Shanghai')

def business_date_str() -> str:
    """业务口径（北京时间）的 YYYYMMDD —— 编号日期段的唯一来源。"""
    return datetime.now(_BUSINESS_TZ).strftime('%Y%m%d')
```

改动：

- 编号日期段的**全部**生产点改为 `business_date_str()`（已全仓枚举）：
  - `services/numbering.py:93`、`:142` —— 覆盖 PO/BH/SO/CSO/CSI/CG/CS/FH 全部前缀；
  - `services/purchase_plan_common.py:79` —— PP 前缀，原为 UTC，**易漏，须一并改**；
  - `services/numbering.py:60`、`core/number_generator.py:68,108,153` —— 随各自所属机械被删除而消失；
  - 非编号用途的 `YYYYMMDD`（`core/logger.py:66` 日志文件名、`services/backup/metrics/service.py:187`
    备份时间戳、`services/storage_service.py:164` 存储路径前缀）**保持不动**。
- 删除 `AsyncNumberGenerator` 类（`numbering.py:45-70`）及其 `_counters` / `_cleanup_old_entries` /
  `_last_cleanup_date`——异步路径从不读写计数器字典，只调清理，是死机械。保留的必要状态缩为模块级一把
  `asyncio.Lock()`（降低同进程争用，非正确性依赖；跨进程正确性由 `numbering_counter` 的原子 upsert 保证）。
- 删除 `fastapi_app/core/number_generator.py`。
- 删除 `services/numbering.py:26-30` 对 core 的 re-export 块。
- `services/stock_return_service.py:21,32` 的 SR 取号改调 `services/numbering`。
- `scripts/concurrency_stress_test.py:28` 从 core 导入 `AsyncNumberGenerator`（非生产脚本，但删 core 会连带
  破坏它），改为从 `services/numbering` 取等价的并发压测目标。

### 4.2 批量导入改异步（风险集中点）

`fastapi_app/tasks/batch_tasks.py`：

- `_run_batch_import_sync` → `_run_batch_import_async`，改用 `require_async_session_local()` 的异步会话。
- **`parse_excel_file`（阻塞的 Excel 解析）仍包在 `asyncio.to_thread` 里**，只把行循环改异步。
- **逐字保留**现有语义（`batch_tasks.py:79-98`）：
  - 每 50 行提交一次（`BATCH_COMMIT_SIZE`）、`last_committed_count` 跟踪已提交批次；
  - `ValueError/TypeError/OSError` → `rollback()` + 计入 `skipped_uncommitted`，不回滚已提交批次；
  - 行级校验失败 → 记录 errors 后 `continue`，不影响其他行；
  - 这三类异常向上抛出时 `delete_file = False`，保留文件供 ARQ 重试；
  - 非法上传路径的拒绝逻辑（`ALLOWED_UPLOAD_DIRS` 校验）不变。
- `_resolve_product_locked`（同步 `.with_for_update()`）→ 异步等价实现。
- 两个任务入口 `batch_import_orders_task` / `batch_import_stockins_task` 改为直接 `await`，不再
  `asyncio.to_thread(_run_batch_import_sync, ...)`。
- `build_row` 闭包（`_orders_row` / `_stockins_row`）改异步，取号改调 `generate_order_number(db)` /
  `generate_stockin_number(db)`。
- 顺带把 `order_date` / `stockin_date` 的 `datetime.now()`（naive 本地）改成 `datetime.now(UTC)`
  （aware UTC），与 `order/commands.py:109`、`order_batch_create.py:142`、`batch_import_core.py:371`
  的既有约定一致。当前写法在「服务器时区 = 上海」的前提下结果正确，但属于第三种约定，一并收口。
- 删除 `fastapi_app/shared/stock_crud_service.py`（4 个同步别名失去全部消费方）。

### 4.3 锁工具重新安家

`fastapi_app/services/case/commands.py:11,56` 借用了 core 的 `_number_lock_key` /
`_acquire_advisory_lock_async`，但那**不是编号用途**，是 `product_id` 级的 CASE 创建锁。

- 新建 `fastapi_app/core/pg_locks.py`，把这两个函数原样搬入，参数名由 `(prefix, date_str)` 改为中性的
  `(scope, key)`。
- `case/commands.py` 改从此导入。md5 取键方案不变，故 `pg_advisory_xact_lock` 的 lock key 不变，
  **无运行时行为变更**。
- 仅保留异步版本（删掉 core 的同步取号后，无同步消费方）。

### 4.4 取号种子修正（口径切换的安全前提）

日期段从 UTC 改北京后，`numbering_counter` 的键从「UTC 日期」变为「北京日期」。新键首次分配时
`seed` 由 `read_daily_max` 提供（`allocate_sequence` 的 INSERT 分支使用，已有行时忽略）。**seed 错 → 新键从错误
起点开始 → 重号**，这是本次唯一能真正制造重号的环节。

`numbering_sequence.py::read_daily_max` 改为**基于编号自身的日期段**取种子，不再依赖 `func.date(日期列)`：

```python
async def read_daily_max(db, model, number_field: str, date_str: str) -> int:
    """当日已落库的最大序号（按数值排序）。date_str 为业务口径 YYYYMMDD。"""
    seq = func.cast(func.split_part(getattr(model, number_field), '-', 3), BigInteger)
    result = await db.execute(
        select(func.max(seq)).where(func.split_part(getattr(model, number_field), '-', 2) == date_str)
    )
    return int(result.scalar() or 0)
```

好处有三：① 消除「UTC 日期 vs timestamptz 会话时区」错配；② 用 `max()` 数值聚合替代字符串降序，
根除 9999/10000 字典序缺陷；③ 不再需要 `date_field` 参数。

- 更新两个调用方：`services/numbering.py:98` 与 `:146`。
- `services/purchase_plan_common.py::_generate_plan_no`（`:63-96`）目前自己做
  `LIKE 'PP-日期-%'` + `order_by(plan_no.desc())`，同样是字符串降序（同样有 9999 缺陷），
  改为复用 `read_daily_max`，口径与实现一并收口。
- **签名变更的连带影响**：`read_daily_max` 还被两处以旧的 4 参数签名 monkeypatch，须同步更新——
  `fastapi_app/tests/test_numbering_batch.py:33` 与 `docs/tickets/tools/verify_iter2_numbering.py:100`
  的 `fake_daily_max(db, model, date_field, number_field)`。
- `split_part` + `cast(..., BigInteger)` 是**本仓首次引入**的 SQL 写法（全仓无先例）。可接受：
  整套代码已深度绑定 PostgreSQL（advisory lock、`INSERT ... ON CONFLICT`），本无跨库诉求。

### 4.5 约束与监控加固

**约束**：生成类编号列实测已有 13 个 DB 唯一索引（`order_order_no_key`、`purchase_order_order_no_key`、
`stock_in_stockin_no_key`、`stock_out_stockout_no_key`、`case_stock_*`、`customer_sampling_project_sequence_no_key`、
`outsource_shipment`、`stock_return_return_no_key`、`purchase_plans_plan_no_key`、`shipment_records` 等），
无需新增。**不**给 `material_registration.purchase_order_no` / `order_sync_record.order_no` /
`sync_retry_queue.order_no` / `order_status_log.order_no` / `order_batch_audit_log.batch_no` 加唯一约束——
它们是引用副本列，多行引用同一单号是合法语义。

**监控**：新增一个 ARQ cron 任务（参照 `core/arq_app.py:56,147` 的 `backup_metrics_report_task` 模式），
周期性做两项不变量检查，经 `fastapi_app/core/metrics.py`（`prometheus_client`，`/metrics` 已被
`config/prometheus.yml:18-21` 抓取）暴露指标：

| 指标 | 含义 | 触发条件 |
|---|---|---|
| `erp_numbering_counter_behind`（Gauge, label: prefix） | 计数表水位**落后于**当日实际最大序号 | `counter.last_seq < data_max` → 置 1 |
| `erp_numbering_format_violations`（Gauge, label: table.column） | 当日编号列中不合 `^[A-Z]+-\d{8}-\d+$` 或前缀与实体不符的行数 | > 0 时报警 |

**`config/alert_rules.yml` 新增两条**（沿用既有 `ERP_*` 命名与 `erp_slo` 组）：
`ERP_NumberingCounterBehindData`（持续 10m）、`ERP_NumberingFormatViolation`（> 0）。

**重要设计约束**：**不**对「正向偏差」（`counter.last_seq > data_max`）告警。该方向由订单删除
（归档于 `backups/server/order_deletions/`）与业务事务回滚造成，是文档化的「允许跳号」语义，
属于正常现象——生产 09-28 的 45 vs 1 就属此类。只有**反向**偏差（数据里的号比计数表更靠前）才说明
存在绕过计数器的取号路径，那才是真信号。

### 4.6 E2E 隔离（P0）

`tests/e2e_api/conftest.py`：

- `BASE_URL` **去掉默认值**：`os.environ.get("E2E_API_BASE_URL")`。未设置 → 在收集期 `pytest.skip`
  整个目录，并给出明确提示（照抄该文件既有的「环境缺失则整目录跳过」约定）。
- **生产指纹拦截**（fail-fast，不设绕过开关）：在收集钩子（`pytest_collection_modifyitems`）里校验目标——
  ① `BASE_URL` 的端口为 5002，或 ② `real_database_url()` 指向的库名为 `erp_system`，
  命中任一即 `pytest.exit(..., returncode=2)` 终止整目录，提示改用专用后端。
- `_cleanup` 的裸 SQL 保留（不再可能落到生产），但在执行任何 `DELETE` 前补一道断言目标库名不等于
  `erp_system`（纵深防御）。
- 更新文件 docstring 的运行说明：必须先起一个**非 5002** 的临时后端并显式设 `E2E_API_BASE_URL`。

### 4.7 死代码删除（P3）

- `git rm fastapi_app/services/order_purchase_sync.py`。
- 删除 `fastapi_app/core/domains.py:59` `DOMAIN_SERVICE_MAP[Domain.ORDER]` 中的 `'order_purchase_sync'` 项。
- 核验：全仓（含 `tests/`、`fastapi_app/tests/`、`scripts/`）无该模块/函数的引用 —— 已 grep 确认，
  实施时再跑一次并跑相关测试。

## 5. 存量数据处理：不回填、不重置

- 存量 15 个编号保持原样。实测客户订单的日期段**已全部是北京日期**（编号日≠北京日 = 0），无需回填。
- `numbering_counter` 不重置：水位高于数据是跳号语义的正常结果；重置反而会与存量编号撞号。
- 日期段口径切换后，北京日期的计数器键与历史 UTC 键可能并存（例如 09-30 北京键首用时，
  09-29 的 UTC 键仍在表里）。这是无害的——键不同即水位独立，且新键的 seed 由 §4.4 的 `read_daily_max`
  从**编号自身日期段**读得，与旧键无关。

## 6. 测试策略

新增 `fastapi_app/tests/test_numbering_unified.py`：

1. **两路径不重号**：交错调用「订单创建（异步路径）」与「批量导入（原同步路径）」取号，断言编号集合无交集、
   且计数表为唯一水位来源。
2. **`read_daily_max` 数值排序**：构造同日序号 9999 与 10000 的行，断言返回 10000（字符串降序会返回 9999）。
3. **口径边界**：冻结时间在 UTC 16:30 / 北京 00:30，断言 `business_date_str()` 返回北京日期，
   且生成的编号日期段与之相同。
4. **新键种子连续性**：清空某 `(prefix, 北京日期)` 计数行、留下当日已有编号，断言下次分配从「已有最大 + 1」起，
   不重号。

回归：

- 批量导入语义：50 行提交批次、`skipped_uncommitted` 计数、行级失败 `continue` —— 逐条对照
  `batch_tasks.py:79-98` 的既有行为加断言。
- `tests/e2e_api`：新增一条断言「指向生产时守卫拒绝运行」的用例。

## 7. 风险与回滚

| 风险 | 等级 | 缓解 |
|---|---|---|
| §4.2 批量导入事务模型重写（生产 Excel 导入写路径） | 高 | 语义逐条保真 + 回归测试；单独提交，便于单点回滚 |
| §4.4 seed 修正若错 → 重号 | 高 | 边界测试（9999/10000）+ 并发测试；唯一索引兜底为报错而非脏数据 |
| 日期段口径切换当日编号日期跳变 | 低 | 仅 15 个存量号，且已核验为北京日期；切换在北京午夜边界后自然生效 |
| §4.5 新告警误报 | 低 | 只对反向偏差与格式违规告警，刻意排除正常的正向跳号 |
| §4.6 让 E2E 不再「开箱能跑」 | 低 | 属预期；docstring 写明新运行方式 |

**回滚**：全部改动为代码改动，无数据迁移；回滚 = 还原提交。`numbering_counter` 表结构不变。

## 8. 验收标准

1. 编号只剩一套实现：`core/number_generator.py` 不存在，`generate_number_sync` 无消费方，
   `shared/stock_crud_service.py` 不存在。
2. 所有生成类编号的日期段均为北京时间；§6.3 的边界测试通过。
3. `read_daily_max` 为数值排序、以编号日期段为过滤；9999→10000 测试通过。
4. 订单创建与批量导入共用同一水位，§6.1 并发测试通过。
5. §4.5 两条告警就位，人工注入「计数表落后」与「格式违规」时可触发。
6. E2E 套件在未显式指定目标时整目录跳过；指向生产时 fail-fast（§6 回归用例通过）。
7. `order_purchase_sync.py` 已删除，全仓无引用，相关测试全绿。
8. 复跑 `_audit_order_no.py`：无重复、无格式违规、计数表不落后于数据。

## 9. 实施顺序

按「无行为变更 → 独立可验证 → 高风险」排序，逐步可停：

1. §4.3 锁工具迁移（纯搬家，零行为变更）
2. §4.6 E2E 隔离（P0，独立可验证）
3. §4.7 删死代码
4. §4.4 `read_daily_max` 修正 + 边界测试（口径切换的前提）
5. §4.1 单一内核 + 北京口径
6. §4.2 批量导入改异步（风险最高，单独提交）
7. §4.5 监控与告警
8. 存量核验：复跑 `_audit_order_no.py`

## 10. 默认取舍（如需变更请在评审时提出）

1. §4.5 的告警**仅**进 Prometheus / Alertmanager，不走 `notification_service` 站内通知——
   编号不变量属运维信号而非业务通知，且站内通知会多引入一条会写库的路径。
2. §4.6 **只做拦截**，本次不新建「专用临时后端 + 测试库」的启停脚本；若后续 E2E 需常态化运行，另起任务。
