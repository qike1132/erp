# 调研报告（RESEARCH）

> 调研员（researcher）· run `完整的审核一下我这个项目-060103`
> 范围：`D:\erp_system`（滨发协同系统 binfa-erp，**内网生产 ERP**）
> 方法：**只读**。Python 结构一律 `ast` 解析；配置/脚本读原文；迁移图用等价于 `alembic ScriptDirectory` 的解析（含 `AnnAssign`）。
> **口径声明**：本报告以**代码与工作区**为准。`docs/`、`deliverables/`、`*.md` 报告可能过期。
> ⚠️ **审计对象是工作区（working tree），不是 `HEAD`** —— 见 §6 P0-1。

---

## 1. 项目全貌

### 1.1 是什么
内网部署的**生产** ERP，覆盖采购、客户订单、库存、出货计划、生产、板房、审批、备份、系统管理。
`AGENTS.md` 第 0 条：「**这台机器既是生产主机，也是运维主机。没有独立的测试/预发环境**」。任何改动直接影响在用业务。

### 1.2 技术栈与版本
| 层 | 技术 | 版本（真源） |
|---|---|---|
| 语言 | Python | **3.13.13**（`C:\Users\Administrator\AppData\Local\Programs\Python\Python313\python.exe`） |
| Web | FastAPI / Starlette / uvicorn | 0.137.1 / >=1.0.1 / 0.46.0[standard] |
| 校验与序列化 | Pydantic + pydantic-settings、**msgspec** | 2.13.2 / 2.14.2 / 0.21.1（替代 orjson 做 `MsgspecResponse`） |
| ORM / 驱动 | SQLAlchemy(async)、asyncpg、psycopg[binary] | 2.0.49 / 0.31.0 / 3.3.3（同步驱动供 Alembic） |
| 迁移 | Alembic | 1.16.0 |
| 缓存/队列 | Redis[hiredis]、**ARQ** | 5.3.1 / 0.28.0 |
| 认证 | PyJWT(RS256)、argon2-cffi | 2.13.0 / 25.1.0 |
| 限流/观测 | slowapi、structlog、prometheus-client、OpenTelemetry、sentry-sdk | 0.1.9 / 25.5.0 / 0.21.0 / 1.30.0 / 2.29.1[fastapi] |
| 数据处理 | polars、openpyxl、XlsxWriter、Pillow | 1.35.2 / 3.1.5 / 3.2.2 / >=12.3,<13 |
| 前端 | Vue / TS / Vite / vue-router / Pinia / PrimeVue / vue-query / axios / ECharts / Tailwind / Vitest / ESLint | 3.5 / 6.0 / 7.1 / 5.0 / 3.0 / 4.5 / 5.100 / 1.18 / 6.0 / 4.2 / 4.1 / 9.28 |
| 前端运行时 | Node | **>= 22**（`package.json` engines 硬约束） |
| 数据库 | PostgreSQL | README 写 18；CI 用 `postgres:16-alpine` → **口径不一致**（见 §6 P2-2） |
| 服务托管 | NSSM（Windows 原生） | `server_manager/`，版本 `v5.33` |

- 依赖唯一来源是 `requirements/*.txt`（`base.txt` 钉版 + `dev/test/ocr/migration/s3/desktop.txt` 可选分拆）。
  `pyproject.toml` **刻意不含** `[build-system]`/`[project]`，只承载 `[tool.code-quality]` 阈值。
- 仓库**无任何 Flask 依赖**；`flask_legacy` 只是 CI 的反选口径残留。

### 1.3 进程/端口拓扑与 5 个 NSSM 服务
```
浏览器 / Capacitor
   │
   ▼
nginx :3000  (config/nginx-windows.conf, root = frontend-vite/dist)      ← erp-web
   │  /api、/ws、/static 反代
   ▼
uvicorn 127.0.0.1:5002  （仅绑回环；API 不直接暴露局域网）                ← erp-prod
   ├── PostgreSQL :5432
   └── Redis :6379（缓存/限流/事件/WebSocket ticket）                    ← erp-redis
ARQ worker（独立进程，非 API 子进程）── Redis :6380（broker）            ← erp-arq / erp-redis-broker
```

**服务真源 `server_manager/constants.py`**：`_SVC_ALL`（:40 附近）、`_SVC_API=erp-prod`、`_SVC_ARQ=erp-arq`、`_SVC_WEB=erp-web`、`_SVC_REDIS_CACHE=erp-redis`、`_SVC_REDIS_BROKER=erp-redis-broker`；`_REDIS_PORT=6379`、`_REDIS_BROKER_PORT=6380`、`_API_PORT=5002`、`_WEB_PORT=3000`；`_VERSION=v5.33`。
- `_SVC_DEPENDS = {erp-prod: [erp-redis], erp-arq: [erp-redis-broker]}` —— 缺 `DependOnService` 时 `erp-arq` 抢跑 6380 造成**无限重启循环**（2026-09-16 实测事故）。
- `_SVC_UVICORN_WORKERS = (erp-prod, erp-arq)`，**刻意不含 erp-web**。
- `_PROD_STATUS_FILE = logs\prod_runner.json`（原子写入；健康需 `ready: true` 且 `frontend_ok: true`）。
- `_HTTP_DIRECT` 绕开系统代理（系统代理曾致 prod_runner 误判后端崩溃并反复重启）。
- 服务启停**唯一通道**是 `server_manager.py`；**唯一启动入口**是 `python start.py`（`run.py` 已归档）。
- 端口口径陷阱：`package.json` 的 dev 脚本写 `--port 5173`，但 `start.py:111` 追加 `--port 3000`，`vite.config.ts:144` 的 `server.port` 也是 3000 → **只有裸跑 `npm run dev` 才落 5173**。

### 1.4 数据流（启动编排真源 `fastapi_app/main.py` lifespan）
`setup_logging` → `_setup_database`（连接验证 + 池预热）→ **编号水位对账 `reconcile_numbering_counters`（失败只记 ERROR，不阻断启动）** → `db_health_checker.start()` → `setup_telemetry` → `_setup_redis_caches` → 通知管理器 `start_redis_listener` + `_register_domain_event_subscriptions` → `start_purchase_cache_listener` → `start_l1_broadcast_listener` → `sync_backup_records` → 后台任务 `_warm_inventory_cache` / `_audit_flush_loop` / `warmup_cache`。
关闭：`flush_audit_buffer` → cancel 后台任务 → 停监听 → dispose engines。
`SENTRY_DSN` 存在时初始化 `sentry_sdk`。

请求链路：`nginx:3000` → `/api/v1/*` → `api/v1/router.py`（34 次 `include_router`）→ 端点（薄层）→ `services/` → `shared_models/` → PostgreSQL；异步任务经 Redis(6379) 事件 / Redis(6380) broker → `fastapi_app/tasks/`（ARQ）。

---

## 2. 规模度量（全部为 `ast`/`fs` 实测，非估算）

| 指标 | 数值 |
|---|---|
| 后端 `fastapi_app/**/*.py` | **527 个文件 / 113 227 行** |
| 后端端点模块 | **48 个**（32 顶层 + `endpoints/backup/` 8 + `endpoints/purchase_center/` 8） |
| `router.py` `include_router` 次数 | **34**（与 32+2 个包完全对齐 → **零孤儿**） |
| 服务层模块 | **165 个**（含 `backup/` 32 项） |
| `core/` 模块 | **45 个** |
| `shared_models/` 模型 | **45 个** |
| `schemas/` I/O 模型 | **26 个** |
| 前端 `frontend-vite/src/` | `.vue` **284 个 / 47 734 行**；`.ts` **281 个 / 41 708 行** |
| 前端 `src/views/` | **275 个文件** |
| 前端单测 | **110 个** `*.test.ts`/`*.spec.ts`（`src/test/` + `src/utils/__tests__/`） |
| 迁移 `migrations/versions/` | **99 个 .py / 99 个 revision**；**head 数 = 1**；**root 数 = 4**；悬空 parent = 0；解析失败 = 0 |
| ↳ 唯一 head | `pg_standalone_060_fix_updated_at_varchar_columns` |
| ↳ 4 个 root | `add_product_factory`、`add_product_price`、`add_pp_composite_idx`、`pg_standalone_001` |
| 测试文件 | **299 个 .py**（`tests/` 144 + `fastapi_app/tests/` 155） |
| 测试用例（`test_` 函数） | **3 338 个**（`tests/` 1 395 + `fastapi_app/tests/` 1 943） |
| 文档 | `docs/` **209 个 .md**；全仓 `.md` **576 个** |
| 全仓文件（排除 `node_modules/.git/dist/__pycache__/.venv/backups/logs`/缓存） | **6 705 个** |
| ↳ `.py` 1 237 · `.md` 576 · `.ts` 298 · `.vue` 296 · `.js` 256 · `.json` 233 · `.ps1` 40 | |
| git 已跟踪文件 | **2 254 个** |
| 顶层目录体积（文件数） | `_qa_tmp` 1 683 · `.workbuddy` 1 504 · `frontend-vite` 998 · `fastapi_app` 533 · `docs` 271 · `scripts` 219 · `tests` 183 · `deliverables` 106 · `migrations` 106 · `config` 25 · `server_manager` 11 · `utils` 9 · `requirements` 7 |
| `scripts/` | 约 **200 项**（含 `prod_audit/` l1–l12 分层审计 + 自带 tests） |
| `mypy.ini` 类型棘轮白名单 | **106 条**（core 16 + shared 2 + shared_models 5 + services 82） |
| `gate_baseline.json` 基线 | n_plus_one 0 · bare_except 9 · function_length 52 · vue_component_length 7 · service_commit 9 · bom 0 · alembic_heads 0 · env_drift 0 |

**BOM 现状**：对 `fastapi_app/`、`scripts/`、`tests/`、`utils/` 全量二进制头扫描 → **UTF-8 BOM 文件数 = 0**（2026-09-30 S10 已剥离）。

---

## 3. 模块地图

### 3.1 分层
```
api/v1/router.py            34 次 include_router（端点挂载 + 认证依赖真源）
api/v1/endpoints/           48 个薄端点模块（→ services）
schemas/                    26 个 Pydantic I/O 模型
services/                   165 个业务模块（+ backup/ purchase/ order/ case/ staging/ ocr/ dashboard/ ...）
shared/                     shipment_calc / report_data_service / customer_status / stock_concurrency
shared_models/              45 个 SQLAlchemy 模型（表定义真源）
core/                       45 个横切模块（配置/日志/安全/限流/缓存/健康/ARQ/prod_runner/production_scope/pg_locks/state_machine）
tasks/                      ARQ 任务：backup / batch / maintenance / numbering_audit / plan / report
utils/(根) + fastapi_app/utils/   跨层工具（**红线：勿删**）
```

### 3.2 主要业务域落点
| 业务域 | 端点 | 服务 | 前端 |
|---|---|---|---|
| **采购** | `endpoints/purchase_center/`（customer_routes / export_utils / misc_routes / order_routes / print_routes / product_routes / role_routes / schemas / __init__）、`purchase_plan.py`、`supplier.py`、`bom`(在 product/purchase) | `services/purchase/`（_common/_completed/_factory/_list/_supplier/_unprocessed）、`purchase_plan_{common,crud,inventory,order_quota,staging,service}.py`、`purchase_order_{query,query_helpers,service}.py`、`purchase_bom_copy_service.py`、`purchase_customer_service.py`、`purchase_history_service.py`、`bom_service.py` | `views/purchase/`、`views/purchase-plan/`、`views/material/`、`views/material-calculator/` |
| **客户订单** | `order.py`、`order_batch.py`、`staging_order.py`、`customer.py` | `services/order/`（approval_flow / commands / deduction / queries / _common）、`order_batch_service.py`、`order_deduction_service.py`、`order_utils.py`、`staging/order.py` | `views/customer-order/`、`views/beile-order/`、`views/customer/`、`views/hubei/` |
| **库存** | `stock.py`、`staging_stockin.py`、`staging_stockout.py` | `stock_common.py`、`stock_in_service.py`、`stock_out_service.py`、`stock_return_service.py`、`stock_event_service.py`、`inventory.py`、`fifo_allocation.py`、`staging/{stockin,stockout,_generic}.py` | `views/stock/` |
| **出货计划** | `purchase_plan.py` | `purchase_plan_*.py`（见上）、`plan_utils.py` | `views/purchase-plan/` |
| **生产** | `daily_production.py`、`production_plan.py`、`production_summary.py`、`dashboard.py` | `daily_production_service.py`、`production_plan.py`、`production_summary_service.py`、`dashboard/`（activities/customer/nav/stats）、`core/production_scope.py` | `views/production/`、`views/dashboard/` |
| **板房/打样** | `pattern_maker.py`、`customer_sampling.py` | `pattern_maker_service.py`、`customer_sampling/`（common/crud/parts/projects/roles/upload/version_diff） | `views/pattern-room/` |
| **审批** | `approval.py` | `approval_*.py`、`order/approval_flow.py`、`core/state_machine.py`、`shared_models/approval.py` | `views/approval/` |
| **备份** | `endpoints/backup/`（actions/export/records/restore/settings/validation/_deps/_mutex） | `services/backup/` **32 项**、`tasks/backup_tasks.py`、`core/backup_encryption.py`、`core/backup_progress.py` | `views/backup/` |
| **系统管理** | `user.py`、`permission.py`、`tasks.py`、`notification.py`、`numbering_audit.py`、`monitoring.py`、`dead_letter.py`、`auxiliary.py`、`auth.py` | `user`/`auth_service.py`、`notification`、`numbering{,_reconcile,_sequence}.py`、`auxiliary.py` | `views/user/`、`views/permission/`、`views/settings/`、`views/notifications/`、`views/login/` |
| **外协** | `outsource.py` | `services/outsource/`（_order_processes/_queries/…） | `views/outsource/` |
| **箱包/箱单** | `case_endpoint.py` | `services/case/`（commands/queries/_common/_serializers） | `views/case/` |
| **报表/导入** | `report.py`、`ocr_import.py`、`batch.py` | `report.py`、`ocr/`（7 模块）、`batch_import_{service,dedup}.py`、`batch_pipeline.py`、`batch_service.py`、`export_limits.py`、`serializers/` | `views/report/`、`views/ocr-import/`、`views/batch/` |
| **来料登记** | `material_registration.py` | `material_registration/`（_commands/_export/_queries） | `views/material/` |

---

## 4. 现有质量资产

### 4.1 总门禁：`scripts/quality_gate.py`（基线棘轮）
读 `pyproject.toml [tool.code-quality]`（`max_function_length=80`、`max_vue_component_length=400`、`max_file_size=1600`）。
**语义：违规数【超过】`scripts/gate_baseline.json` 才失败**（只拦新增，不阻断存量）。退出码 0/1/2。
8 个子门禁：`n_plus_one`(0) · `bare_except`(9) · `function_length`(52) · `vue_component_length`(7) · `service_commit`(9) · `bom`(0) · `alembic_heads`(0) · `env_drift`(0)。

### 4.2 门禁脚本清单与**实际**检查范围
| 脚本 | 实际检查范围 |
|---|---|
| `scripts/quality_gate.py` | 上述 8 项，读 `gate_baseline.json` 做棘轮 |
| `scripts/check_alembic_heads.py` | **alembic ScriptDirectory** 解析迁移图；`EXPECTED_MAX_BASES=4`；检测多 head / 悬空 parent。文件内文档串明确警告朴素 `ast.Assign` 会得出「5 roots / 4 heads / dangling `pg_standalone_003,007`」伪影 |
| `scripts/file_size_gate.py` | 文件 >1600 行 / 函数 >80 行 / Vue 组件 >400 行；**默认只扫 git 变更文件**（`--all` 全量） |
| `scripts/scan_secrets.py` | 私钥头、云凭据、口令赋值；`# secret-scan:allow` / `-next-line`；CI **全树**跑 |
| `scripts/check_nosec_budget.py` | `# nosec` 用量预算（防豁免膨胀） |
| `scripts/audit_tx_patterns.py` | 事务边界反模式 |
| `scripts/contract_snapshot.py` | 端点契约快照（`tests/contract/snapshots/`） |
| `scripts/restore_drill.py` | 备份恢复演练 |
| `scripts/ops/check_env_drift.py` | 生产 .env 与模板漂移（S3） |
| `scripts/ops/watchdog.py` | 运行看门狗（S2，+ `watchdog_task.cmd`/`install_watchdog_task.ps1`） |
| `scripts/prod_audit/` | l1_static→l12_report 十二层审计 + `orchestrator.py` + `rules_registry.yaml` + 自带 tests（CI 独立进程跑） |
| `bandit.yaml` | 跳过 B101/B105/B106/B107/B108；B608 **不再全局跳过**，改为逐行 `# nosec B608` |

### 4.3 CI（`.github/workflows/ci-cd.yml`，3 job）
- **test**（ubuntu + `postgres:16-alpine`；`TEST_DATABASE_URL` 显式给出以绕开 conftest 的 `{DB_NAME}_test` 派生；`COVERAGE_MIN=40`）：
  `alembic upgrade head` + `alembic check` → `pytest tests fastapi_app/tests --ignore=tests/{qa,e2e,stress,performance} --cov=fastapi_app --cov=utils` → **独立进程** `pytest scripts/prod_audit/tests -q`（不加 `--cov`）→ 上传报告 → `bandit -r fastapi_app/ utils/ -ii` → `pip-audit` → 覆盖率阈值就地判定。
- **lint**：`fetch-depth: 0` → `scan_secrets.py --verbose`（全树）→ `quality_gate.py --verbose` → `ruff check` → `mypy` → `file_size_gate.py`（PR 用 `--base`，push 用 `--all`）。
- **frontend**：Node 22 → `npm ci` → lint → `npx vitest run --reporter=junit --outputFile.junit=test-results.xml`（**必须绕开 `npm run test --`**，npm 会吞掉 `--outputFile`）→ build → 跨端对齐检查。
- 已删除：codecov 上传、`playwright install`、`npm run test:e2e`（脚本不存在）。

### 4.4 测试与覆盖率口径
- `pytest.ini`：`testpaths = tests fastapi_app/tests`；`asyncio_mode=auto`；`--strict-markers --tb=short`；`filterwarnings=error`（忽略 UserWarning/DeprecationWarning）。
- marker：unit / integration / functional / boundary / slow / api / model / db / **contract**（contract 需真实后端 `CONTRACT_BASE_URL`，未设则**整文件跳过**）。
- `.coveragerc`：`source = fastapi_app`，omit tests/migrations/scripts/frontend。
- `mypy.ini` `files` 是**棘轮白名单 106 条**；注释记录 **services 层仍有 74 文件 / 400 error 未纳管**。

### 4.5 测试覆盖粗判（按业务域；口径 = 测试文件命名 + 全量文件清单）
**强覆盖**：备份（`test_backup_*` 约 25 个 + `services/test_backup_*` 5 个，覆盖 m0–m6/p0、健康、校验、加密、恢复锁、计划回调、完整性）、编号（`test_numbering_*` 6+）、认证与用户权限（`test_auth*`、`test_user*`、`test_strict_auth_wiring`、`test_ws_ticket_auth`）、订单（`test_order*` 12+）、采购（`test_purchase_*` 12+）、库存（`test_stock*` 8）、生产（`test_daily_production_*` 7 + `test_production_*` 6）、OCR（`test_ocr_*` 9）、批量导入/暂存（`test_batch*`、`test_staging`）、server_manager（`test_server_manager_*` 8 + `test_sm_*` 8）。
**有覆盖**：审批、箱包(case)、来料登记、客户、供应商、外协、通知、报表、看板、迁移（`test_migration_*` 4）。
**零专用测试（后端）**：
- **板房 / 板房师傅**：`fastapi_app/api/v1/endpoints/pattern_maker.py`、`fastapi_app/services/pattern_maker_service.py`、`shared_models/pattern_maker.py` —— 299 个后端测试文件中**无任何 pattern 命名的测试文件**（前端有 `src/test/patternRoom*.test.ts` 8 个）。
- **死信队列**：`fastapi_app/api/v1/endpoints/dead_letter.py` —— 无同名测试。
- **（弱）前端 e2e**：`frontend-vite/package.json` 声明 `playwright ^1.60.0`，但仓库**无 `playwright.config.*`、无 e2e 目录、无 `test:e2e` 脚本**，CI 也已删除 playwright 步骤。

---

## 5. 已知风险与历史坑

### 5.1 历史事故（有据可查）
| 时间 | 事故 | 根因 | 现状 |
|---|---|---|---|
| 2026-09-17 | **428 个 Edge 浏览器凭据文件入库并推到 main** | `core.hooksPath = .githooks` 但该目录**不存在**，且 `.git/hooks/pre-commit` 也没有 → 所有 hook 长期从未运行 | **已修复**：`.githooks/` 已存在，pre-commit 三层守卫在位（`.githooks/pre-commit:1-30` 有完整事故记录） |
| 2026-09-16 | **`erp-arq` 无限重启循环** | 无 `DependOnService`，arq 抢跑 broker 6380 | **已修复**：`_SVC_DEPENDS` 已声明 |
| 2026-09-14 | **OCR 功能整体不可用** | `ocr/_extractors.py` 三个提取器单例模块级从未声明，`global X` 不创建变量 → 首次调用必抛 `NameError` | **已修复**（由 mypy 门禁发现）：`fastapi_app/services/ocr/_extractors.py:22-24` 已显式声明 |
| （更早） | 系统代理导致 prod_runner 误判后端崩溃并重启 | 走系统代理探测健康 | **已修复**：`_HTTP_DIRECT` |
| （更早） | 「15 个迁移 head」「48 个孤儿端点模块」 | 纯解析伪影（正则/朴素 AST） | **已澄清**：真相是单 head、零孤儿 |

### 5.2 「看起来像问题但其实是设计」——**不要当缺陷报**
| 现象 | 真相（证据） |
|---|---|
| `logs/prod_runner.json` 里 `arq.status = "external"` | **正常设计**。ARQ 由 `erp-arq` 单独托管，不在 prod_runner 进程树内 → `pid` 恒为 None、`status` 恒为 "external"（`fastapi_app/core/prod_runner.py:440-443`、`:469`） |
| `user`/`permission` 端点认证是 fail-open（`get_current_user_id`） | 刻意取舍：strict 变体在"Redis 启动即不可用"时会**永久 401**。**只有 `/backup` 用 `get_current_user_id_strict`**（`api/v1/router.py`） |
| `/monitoring` 无认证依赖 | POST `/vitals` 走 `sendBeacon` 无法带 header；需认证的 `GET /vitals/summary` 在 `monitoring.py` 内**单独声明** |
| `config/nginx.conf:107` 有 `root /app/frontend-vite/dist;` | **死配置**，Windows 永不生效；生效的是 `config/nginx-windows.conf` |
| `pyproject.toml` 无 `[project]`/`[build-system]` | 刻意：依赖真源是 `requirements/*.txt` |
| `frontend-vite/vite.config.js` 与 `vite.config.ts` 并存 | **设计产物**：`.js` 是 `vue-tsc -b` 编译 `.ts` 的结果；`fastapi_app/tests/test_qa_prod_stack_regression.py` 断言二者一致。**删了会打挂构建** |
| `mypy.ini` 注释里的两个"真实缺陷" | **均已修复**：`_extractors.py:22-24` 已显式声明；`services/batch_import_dedup.py:32` 已把 `Container[Hashable]` 收窄为 `Iterable`（`:136-139` 有说明）。**把 mypy.ini 注释当现状会误报** |
| `_ops/credentials/` 下有 `.env.bak-*`、`_backup_encryption_password.txt`、`_metrics_bearer_token.txt` | **设计**：这是指定的凭据存放处，已被 `.gitignore` 覆盖（`git check-ignore` 确认 `_ops` = ignored）。**磁盘明文属预期**，需验证的是 ACL（→ §7 sec） |
| `ruff.toml` `external = ["BLE001"]` | 刻意：RUF100 会自动删 `# noqa: BLE001`，而它是质量门禁的**审计豁免凭证** |
| `ruff.toml` 给 `services/backup/__init__.py` 关 `I001` | 刻意：Redis 还原锁三件套**必须**排在所有星号导入之后，否则被 `query_service` 的 advisory 版遮蔽 → 端点 finally 抛 TypeError |
| `pyproject.toml` `max_file_size=1600` 看似太松 | 有依据：受扫 777 个 .py 中仅 2 个超 1200（`test_purchase_center.py` 1497、`recovery_test_service.py` 1353） |
| `deliverables/`（106 项）、`evidence/`（190）、`mockups/`（10）已入库 | `deliverables/` 是 `AGENTS.md` 明示的历史归档（**不是现行真相**）；`evidence/`、`mockups/` 属过程件，见 §6 P3 |
| `config/nginx.conf` 与 `nginx-windows.conf` 并存 | 前者是 Linux 容器版残留，Windows 生产用后者 |

### 5.3 方法论坑（写进团队知识库）
- **解析 Python 结构必须用 `ast`**：只用 `ast.Assign` 找迁移 `revision`/`down_revision` 会漏 `revision: str = ...`（**AnnAssign**），从而伪造出「4 heads + missing parents `pg_standalone_003`/`pg_standalone_007` + 5 roots」。正解用 `alembic ScriptDirectory`。
- **死代码按全仓导入判断**：`backup/`、`purchase_center/` 通过 `__init__.py` 聚合，子模块天然不被入口直接 import。
- **Windows PowerShell 5.1**（非 pwsh 7）：`-Encoding utf8` 会写 BOM；无 `Get-Content -AsByteStream`；把内联 `if(){...}else{...}` 塞进字符串插值会触发 `MissingEndParenthesisInExpression` 并让**整段脚本一行都不执行**（分步、先赋值再输出）。
- git-bash 里 `python` 常不在 PATH，钩子靠绝对路径兜底。

---

## 6. 现状缺口清单（P0 / P1 / P2 / P3）

> 每条给 `文件路径 · 锚点 @ 行号` + 证据。**未标"已验证"的均为"代码推断"，需对应角色复核。**

### P0

**P0-1 · 工作区不干净：19 个已修改文件 + 3 个未跟踪文件（审计基线风险）**
- 证据：`git status --porcelain`（只读）共 22 行：
  `M` 19 个 —— `fastapi_app/services/daily_production_service.py`、`fastapi_app/services/order/queries.py`、`fastapi_app/services/purchase_order_query.py`、`fastapi_app/shared_models/daily_production_record.py`、`fastapi_app/tests/test_daily_production_records_filter.py`、`frontend-vite/src/test/fontAwesomeLazy.test.ts`、`frontend-vite/src/test/recordFilterBar.render.test.ts`、`frontend-vite/src/utils/fontAwesomeLoader.ts`、`frontend-vite/src/utils/queryKeys.ts`、`frontend-vite/src/views/customer-order/composables/{useOrderDelete,useOrderDetailEdit,useStagedItems}.ts`、`frontend-vite/src/views/hubei/HubeiView.vue`、`frontend-vite/src/views/outsource/components/OutsourceOrderTab.vue`、`frontend-vite/src/views/production/components/RecordFilterBar.vue`、`frontend-vite/src/views/purchase/composables/usePurchaseActions.ts`、`frontend-vite/src/views/stock/{StockOutTab,StockView}.vue`；
  `??` 3 个 —— `fastapi_app/tests/test_order_derived_cache_no_l1.py`、`frontend-vite/src/test/crossPageRealtimeWebSocket.test.ts`、`frontend-vite/src/test/customerOrderCrossPageInvalidation.test.ts`。
- 影响：① 本 run 的审计对象**必须**是工作区；以 `HEAD` 为准会漏掉正在进行的改动（含生产记录筛选、跨页实时失效、订单删除/编辑、fontAwesome 懒加载）；② 生产主机上的未提交改动一旦被 `git checkout/reset` 或部署脚本覆盖即**永久丢失**。
- 归属：**devops + pm**（决定提交、丢弃还是保留）。

**P0-2 · 生产环境变量文件中 `BACKUP_ENCRYPTION_PASSWORD` 为空、`SECRET_KEY` 仅 13 字符（若被误用则静默不加密备份 + 弱密钥）**
- 证据（**只读键存在性检查，未打印任何值**）：
  - 根 `.env`：`BACKUP_ENCRYPTION_PASSWORD` = **已设置（43 字符）**、`SECRET_KEY` = 64 字符 → **当前生效配置是安全的**。
  - 根 `.env.production`：`BACKUP_ENCRYPTION_PASSWORD` = **EMPTY**、`SECRET_KEY` = **13 字符**、`ALLOWED_HOSTS` = **1 字符**（疑似 `*`）。
  - `.env.example`：`BACKUP_ENCRYPTION_PASSWORD` EMPTY、`SECRET_KEY` EMPTY（模板，正常）。
- 代码路径（**静默降级确凿**）：
  - `fastapi_app/services/backup/_constants.py:43-44` —— `BACKUP_ENCRYPTION_ENABLED` 默认 `'true'`；`BACKUP_ENCRYPTION_PASSWORD` 默认 `''`。
  - `fastapi_app/services/backup/crypto.py:57-62` —— `if not BACKUP_ENCRYPTION_ENABLED: return None`；`if BACKUP_ENCRYPTION_PASSWORD: return ...`（**空则落到返回 None = 不加密**）。
  - `fastapi_app/tasks/backup_tasks.py:638-640` —— `logger.info('自动全量备份未配置 BACKUP_ENCRYPTION_PASSWORD，本次备份不加密')`（**只记 INFO，不报错**）。
  - `fastapi_app/services/backup/incremental.py:116` —— 增量路径反而是**硬失败**（`raise BackupError`）→ 全量与增量语义不一致。
- 影响：若生产改用/误用 `.env.production`，备份将**静默明文**，且 JWT/会话签名密钥仅 13 字符。
- 归属：**sec + devops**（核对生产实际加载的是哪个文件；统一全量/增量的加密缺失语义；建议把"启用加密但密码为空"改为启动期硬失败）。

### P1

**P1-1 · services 层类型未纳管：74 文件 / 400 个 mypy error**
- 证据：`mypy.ini` 的 `files` 棘轮白名单共 **106 条**（core 16 + shared 2 + shared_models 5 + services 82），注释明确「services 层仍有 74 文件 / 400 error」。
- 佐证门禁有效：mypy 曾真实发现 OCR 的 `NameError`（现已在 `services/ocr/_extractors.py:22-24` 修复）。
- 归属：**backend**（继续按域纳管）。

**P1-2 · 板房/板房师傅域后端零专用测试**
- 证据：299 个后端测试文件（`tests/` 144 + `fastapi_app/tests/` 155）中**无任何 pattern 命名文件**；被测对象为 `fastapi_app/api/v1/endpoints/pattern_maker.py`、`fastapi_app/services/pattern_maker_service.py`、`fastapi_app/shared_models/pattern_maker.py`。前端侧有 8 个 `src/test/patternRoom*.test.ts`。
- 影响：板房是本项目**强业务特色域**（客户打样/版本差异/图片上传），却是唯一零后端测试的主要域。
- 归属：**qa + backend**。

**P1-3 · 死信队列端点零测试**
- 证据：`fastapi_app/api/v1/endpoints/dead_letter.py`；299 个后端测试文件中无 `dead_letter` 命名文件。
- 归属：**qa + backend**。

**P1-4 · 前端 e2e 能力形同虚设（依赖声明但无任何脚手架）**
- 证据：`frontend-vite/package.json` devDeps 含 `playwright ^1.60.0`；仓库无 `playwright.config.*`、无 e2e 目录、`scripts` 中无 `test:e2e`；`.github/workflows/ci-cd.yml` 注释明确"已删除 playwright install / npm run test:e2e（脚本不存在）"。
- 影响：跨页实时失效、WebSocket 断线重连等前端行为只能靠单测覆盖。
- 归属：**qa + frontend**。

**P1-5 · CI 覆盖率门槛 40% 且排除了 qa/e2e/stress/performance**
- 证据：`.github/workflows/ci-cd.yml` `COVERAGE_MIN=40`，pytest 带 `--ignore=tests/{qa,e2e,stress,performance}`；`.coveragerc` `source = fastapi_app`。
- 影响：40% 的线覆盖率不足以支撑"生产 ERP"的回归信心；被 ignore 的目录本身也大量是脚本而非用例。
- 归属：**qa**（先给出按域覆盖率报告，再谈提门槛）。

### P2

**P2-1 · `migrations/add_fabric_color_no.py` 是裸脚本，不是 Alembic 迁移**
- 证据：该文件位于 `migrations/` 根（非 `versions/`），内容为顶层 `create_engine(settings.DATABASE_URL)` + `ALTER TABLE customer_sampling_part ADD COLUMN fabric_color_no VARCHAR(50)`，**无 `revision`/`down_revision`**，且用 `Settings()` 直接连库。
- 影响：这是一条绕过迁移链的手工 DDL 路径；`fabric_color_no` 在 `versions/` 中是否有对应迁移需核对（99 个 revision 中未见同名）。
- 归属：**dba**。

**P2-2 · PostgreSQL 版本口径不一致**
- 证据：`README.md`（架构概览）写 `PostgreSQL 18`；`.github/workflows/ci-cd.yml` 用 `postgres:16-alpine`。
- 影响：CI 与生产的 PG 大版本不一致，索引/查询计划/DDL 行为可能不同（本仓库有大量 trgm/CTE/覆盖索引迁移）。
- 归属：**devops + dba**。

**P2-3 · 全量与增量的加密缺失语义不一致（可观测性缺口）**
- 证据：`fastapi_app/tasks/backup_tasks.py:638-640`（全量：INFO 日志 + 继续）vs `fastapi_app/services/backup/incremental.py:116`（增量：`raise BackupError`）。
- 影响：运维看到"备份成功"但产物是明文；且两种路径对同一配置的反应不同，易误判。
- 归属：**sec + devops + backend**。

**P2-4 · `tests/contract/` 在无真实后端时整文件跳过**
- 证据：`pytest.ini` marker `contract`（需真实后端）+ `tests/contract/test_api_contract.py`；CI 未提供 `CONTRACT_BASE_URL`。
- 影响：端点契约快照（`tests/contract/snapshots/`、`tests/contract/endpoints.yaml`）在 CI 中**不产生保护**。
- 归属：**qa + backend**。

### P3

**P3-1 · 已入库的过程件/归档物**（体积与噪声，非缺陷）
- `evidence/`（**TRACKED**，190 个文件，含 `gate_logs/`、`coverage_reports/`、大量 `*_e2e` 目录）
- `mockups/`（**TRACKED**，10 项）
- `deliverables/`（**TRACKED**，106 项 —— `AGENTS.md` 声明为历史归档，保留即可，但不应被当作现行真相）
- `check_workspace_acl.py`（**TRACKED**，根目录一次性 ACL 检查脚本）
- 证据：`git ls-files` + `git check-ignore -v` 逐路径判定。
- 归属：**devops**。

**P3-2 · 未跟踪的根目录调试产物（已被 .gitignore 覆盖，但仍在磁盘）**
- `_probe2.py`、`_probe3.py`、`_tmp_env_probe.py`、`_beile_detail_align_check.py`、`_beile_detail_meta_check.py`、`_proc5002.json`、`_uvicorn_restart_{err,out}.log`、`_scan_asar.mjs`、`_asar_node_modules_dsh-desktop-market-installer_generations_{installer,projection}.mjs`、`dsh-web-dump-config.txt`、`nul`、`_dsh_research/`、`_dsh_research_awesome1.md`、`.brooks-lint-history.json`、`.agent-commit-receipts.log`、`start`（空壳）
- 证据：`git check-ignore -v` 全部判定为 `ignored`，`git status --porcelain` 中不出现 → **无入库风险**，仅属磁盘噪声。
- 归属：**devops**。

**P3-3 · 顶层大体积过程目录**
- `_qa_tmp/`（1 683 个文件）、`.workbuddy/`（1 504）、`temp/`、`build/`、`dist/` —— 均已被 `.gitignore` 覆盖（`git check-ignore` 确认）。
- 归属：**devops**。

**P3-4 · `config/nginx.conf` 死配置留存**
- 证据：`config/nginx.conf:107` `root /app/frontend-vite/dist;`（Windows 永不生效）；生效文件是 `config/nginx-windows.conf`。
- 影响：误导排障者。建议加显式"仅 Linux 容器版，Windows 不生效"注释或移除。
- 归属：**devops**。

**P3-5 · `.gitignore` 未覆盖 `.workbuddy-ai/`**
- 证据：`AGENTS.md` §7 的忽略清单含 `.workbuddy/` 但**不含** `.workbuddy-ai/`；根目录存在 `.workbuddy-ai/`。
- 影响：若未来 `git add -A`，该目录有被卷库风险（同 2026-09-30 `3f542bc6` 治理同类）。
- 归属：**devops**。

---

## 7. 未知项（需其他角色深挖）

| # | 问题 | 归属角色 | 建议核实方式（只读） |
|---|---|---|---|
| U1 | 生产运行时实际加载的是哪个 env 文件（`.env` vs `.env.production` vs NSSM AppEnvironment）？`BACKUP_ENCRYPTION_PASSWORD` 在**运行进程**里是否非空？ | **sec / devops** | 读 NSSM 服务参数（`nssm get erp-prod AppEnvironment`，只读）+ `logs/prod_runner.json`；**不要**重启服务 |
| U2 | `_ops/credentials/` 的 NTFS ACL 是否确实只对管理员开放？`.env.bak-*`、`_backup_encryption_password.txt`、`_metrics_bearer_token.txt` 是否已轮换（2026-09-30 `1e67e247` 提到"加密备份为移动靶"）？ | **sec** | `Get-Acl`（只读）+ 对照 `docs/ops/` 凭据轮换手册 |
| U3 | 生产 PostgreSQL 大版本、`pg_stat_statements`/pgaudit 是否启用、慢查询现状；99 个迁移在**生产库**的实际 `alembic current` 是否 == `head` | **dba** | 只读 SQL：`SHOW server_version`、`SELECT * FROM alembic_version` |
| U4 | `migrations/add_fabric_color_no.py` 的手工 DDL 是否已在生产执行、是否与 `versions/` 中任一迁移重复 | **dba** | `information_schema.columns` 查 `customer_sampling_part.fabric_color_no` |
| U5 | 前端 PC 与移动端在真机/真浏览器下的可访问性（a11y）与首屏性能（`docs/decisions/frontend-primevue-bundle.md` 已有体积评估，是否仍成立？`scripts/prod_audit/layers/fix_a11y.py` 的存在暗示曾有 a11y 缺口） | **ui / frontend** | 跑 `l10_frontend.py` 层审计（只读）+ 检查 `frontend-vite/dist` 实际产物体积 |
| U6 | 移动端（`src/mobile/`、Capacitor）与 PC 端的数据层在 S12 统一后是否仍有字段重映射残留；`android/` 构建产物是否需清理 | **frontend** | 读 `src/mobile/` + `src/types/` |
| U7 | 覆盖率真实分布：哪些业务域 <40%、哪些 0%？CI 的 40% 门槛是否为"通过而通过" | **qa** | 本地跑 `pytest --cov=fastapi_app --cov-report=term-missing`（**只读、不写库**；注意需测试库） |
| U8 | `tests/stress/`（20+ 脚本）与 `tests/performance/` 的历史报告是否仍代表当前性能？有无 `PERFORMANCE_REPORT.md` 结论过期 | **qa / devops** | 读报告日期 + 对照 `git log` |
| U9 | 看门狗（`scripts/ops/watchdog.py` + 计划任务）是否真的在跑？S2 声称已接线，需确认计划任务存在 | **devops** | `schtasks /query`（只读） |
| U10 | 备份恢复演练（`scripts/restore_drill.py`）最近一次成功的证据；`backups/` 下实际产物是否加密（扩展名/魔数） | **devops + sec** | 只读列目录 + 文件头魔数判断 |
| U11 | 19 个未提交改动是"功能未完成"还是"已上线但没提交"？与生产实际运行的代码是否一致 | **pm + devops** | 与 `git diff` 对照 + 询问业务方 |
| U12 | `bandit`/`pip-audit` 最近一次结果是否干净；`# nosec` 预算（`check_nosec_budget.py`）当前余量 | **sec** | 跑只读扫描 |

---

## 附录 A · 相关文件与调用链（原模板小节）

**请求主链**
`nginx:3000` → `/api/*` → `fastapi_app/main.py`（中间件：CORS/TrustedHost/CSRF/GZip/审计/限流）→ `api/v1/router.py`（`include_router` ×34）→ `api/v1/endpoints/<域>.py` → `services/<域>/*.py` → `shared_models/*.py`（SQLAlchemy）→ PostgreSQL。
**异步链**：端点 → `tasks/*_tasks.py`（ARQ 入队，Redis 6380）→ `erp-arq` worker → 回写 + 事件（Redis 6379 pub/sub）→ `core/event_bus.py` / `core/domain_events.py` → WebSocket（`api/ws.py`）/ 通知。
**启动链**：`start.py` →（prod）`core/prod_runner.main` → uvicorn（127.0.0.1:5002）→ `main.py` lifespan（见 §1.4）→ 写 `logs/prod_runner.json`。
**NSSM 链**：`server_manager.py` → `server_manager/service_ops.py` → `nssm` → 5 个服务。

## 附录 B · 关键依赖（原模板小节）
- **硬运行时依赖**：PostgreSQL（结构变更唯一通道 = Alembic）、Redis 6379（缓存/限流/事件/WS ticket）、Redis 6380（ARQ broker）。
- **可选依赖**：`ocr.txt`（rapidocr 系列，约 500MB）、`migration.txt`（bcrypt）、`s3.txt`（boto3）、`desktop.txt`（pystray）。
- **前端**：Node >= 22 是硬约束（Vite 7 + TS 6）。
- **外部服务**：Sentry（可选）、Prometheus/Grafana/Alertmanager/OTel/Promtail（`config/` 下均有配置）。

## 附录 C · 环境现状（原模板小节）
- 本机：Windows + Python **3.13.13**；shell 为 **PowerShell 5.1**；git-bash 在 `C:\Program Files\Git\bin\bash.exe`。
- 生产：**无独立测试/预发环境**，本机即生产（`AGENTS.md` §0）。
- 配置：根 `.env`（生效，密钥齐备）、根 `.env.production`（`BACKUP_ENCRYPTION_PASSWORD` 空 / `SECRET_KEY` 13 字符）、`config/.env.production`、`.env.example`（模板）。
- 凭据：`config/jwt/{private_v2.pem,public_v2.pem}`（`.gitignore` 覆盖 `config/jwt/*.pem`）；`_ops/credentials/`（ignored）。
- 迁移：根 `alembic.ini` 已于 2026-09-30 补入（此前 `alembic current/upgrade` 实际不可用），必须纯 ASCII。
- 工作区：**19 个已修改 + 3 个未跟踪**（见 P0-1）；git 跟踪文件 2 254 个。

## 附录 D · 历史坑 / 存量约束
见 §5（历史事故 5 条 + 「其实是设计」12 条 + 方法论坑 4 条）。

## 附录 E · 给 architect / 实现者的约束与建议
1. **不要删**根 `utils/`、`fastapi_app/utils/`、`server_manager.py`+`server_manager/`、`frontend-vite/vite.config.js`。
2. **不要**动 `core.hooksPath`；**不要**把 `_ops/credentials/**` 或 `config/pgbouncer/userlist.txt` 加回版本库。
3. **不要**让 uvicorn 绑 `0.0.0.0`；**不要**在 `.env` 里把 `BACKUP_ENCRYPTION_PASSWORD` 留空。
4. 迁移**只做结构/数据变更**，保持**单 head**；新增迁移前先跑 `scripts/check_alembic_heads.py`。
5. 新增代码：函数 ≤80 行、Vue 组件 ≤400 行、文件 ≤1600 行；裸 `except` 会抬高 `bare_except` 基线；service 层**不要自行 commit**（`service_commit` 门禁）。
6. 豁免写法：`# noqa: BLE001` 已被 `external` 保护，新代码用 `# defensive: <理由>`；`# nosec` 有预算门禁。
7. 分析本仓库时：**用 `ast`**、**按全仓导入判死代码**、**迁移图用 ScriptDirectory**；不要相信 `deliverables/` 与旧 `*.md` 的结论。
8. 任何"顺手启动服务"的动作都会与生产抢端口 —— 本轮调研**未启动任何服务、未写任何数据库**。
