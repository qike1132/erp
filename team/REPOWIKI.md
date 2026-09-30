# REPOWIKI —— 滨发协同系统（binfa-erp）项目知识库

> 本 run（`完整的审核一下我这个项目-060103`）**唯一权威的项目知识源**。
> 生成方式：**只读**调研 —— Python 结构一律用 `ast` 解析，配置/脚本读原文，结论以**代码**为准。
> 口径提醒：`docs/`、`deliverables/`、`*.md` 报告**可能已过期**，与代码冲突时以代码为准。
> 工作目录 `D:\erp_system`；本机 Python 3.13.13；Node >= 22。

---

## 0. 跨项目复用（可迁移到其他仓库的经验）

本仓库特有的约定不写在此处。以下 6 条是**跨项目**可复用的：

1. **解析 Python 结构必须用 `ast`**（导入关系、迁移依赖图、`__init__.py` 聚合）。正则/文本匹配会产生"伪影级"错误结论，且伪影会写进报告并污染后续所有决策。
2. **判断死代码要按全仓导入判断**，不能只看"是否被入口文件直接引用"。包通过 `__init__.py` 聚合时，子模块天然不会被入口直接 import。
3. **"基线棘轮"质量门禁**比"一刀切清零"更适合存量债仓库：只拦新增违规，清理后可收紧基线（`--update-baseline`）。见 `scripts/quality_gate.py`。
4. **CI 与本地 hook 必须同源**：本地 hook 可被 `--no-verify` 绕过，因此密钥扫描等硬门禁必须**在 CI 全树重跑一遍**。见 `.githooks/pre-commit` 与 `.github/workflows/ci-cd.yml` 的 `scan_secrets.py` 步骤。
5. **审计豁免要留"可复核凭证"**：`# noqa`、`# nosec`、allowlist 条目都必须写明理由，否则会被后续的自动修复（如 RUF100）静默删除，豁免变成永久盲区。
6. **生产主机 == 开发主机**时的纪律：改动小步、可回滚；任何"顺手启动服务"都会影响在用业务。

---

## 1. 项目定位与业务域

**内网部署的生产 ERP**（非演示项目）。业务域与落地位置：

| 业务域 | 后端端点 | 后端服务 | 前端视图 |
|---|---|---|---|
| 采购（采购单/BOM/供应商/来料） | `endpoints/purchase_center/`（8 模块）、`purchase_plan.py`、`supplier.py` | `services/purchase/`、`purchase_plan_*.py`、`purchase_order_*.py`、`purchase_bom_copy_service.py`、`purchase_customer_service.py`、`purchase_history_service.py`、`bom_service.py` | `views/purchase/`、`views/purchase-plan/`、`views/material/`、`views/material-calculator/` |
| 客户订单 | `endpoints/order.py`、`order_batch.py`、`staging_order.py`、`customer.py`、`beile`(在 order 内) | `services/order/`、`order_batch_service.py`、`order_deduction_service.py`、`staging/order.py` | `views/customer-order/`、`views/beile-order/`、`views/customer/`、`views/hubei/` |
| 库存 | `endpoints/stock.py`、`staging_stockin.py`、`staging_stockout.py` | `services/stock_*.py`（common/in/out/return/event/inventory）、`fifo_allocation.py`、`staging/` | `views/stock/` |
| 出货计划 | `endpoints/purchase_plan.py` | `services/purchase_plan_*.py`（crud/inventory/order_quota/staging/common/service）、`plan_utils.py` | `views/purchase-plan/` |
| 生产 | `endpoints/daily_production.py`、`production_plan.py`、`production_summary.py`、`dashboard.py` | `services/daily_production_service.py`、`production_plan.py`、`production_summary_service.py`、`dashboard/`、`core/production_scope.py` | `views/production/`、`views/dashboard/` |
| 板房（客户打样/板房师傅） | `endpoints/pattern_maker.py`、`customer_sampling.py` | `services/pattern_maker_service.py`、`services/customer_sampling/`（7 模块） | `views/pattern-room/` |
| 审批 | `endpoints/approval.py` | `services/approval_*.py`、`order/approval_flow.py`、`core/state_machine.py` | `views/approval/` |
| 备份/恢复 | `endpoints/backup/`（8 模块） | `services/backup/`（32 项）、`tasks/backup_tasks.py` | `views/backup/` |
| 系统管理（用户/权限/任务/通知/编号/监控） | `endpoints/user.py`、`permission.py`、`tasks.py`、`notification.py`、`numbering_audit.py`、`monitoring.py`、`dead_letter.py`、`auxiliary.py`、`auth.py` | `services/user*`、`auth_service.py`、`notification_service.py`、`numbering*.py`、`services/case/` | `views/user/`、`views/permission/`、`views/settings/`、`views/notifications/`、`views/login/` |
| 外协/加工 | `endpoints/outsource.py` | `services/outsource/`（4 模块） | `views/outsource/` |
| 报表/导入导出 | `endpoints/report.py`、`ocr_import.py`、`batch.py` | `services/report.py`、`ocr/`（7 模块）、`batch_import_*.py`、`export_limits.py`、`serializers/` | `views/report/`、`views/ocr-import/`、`views/batch/` |
| 箱包/箱单（case） | `endpoints/case_endpoint.py` | `services/case/`（5 模块） | `views/case/` |

---

## 2. 技术栈与版本（真源：`requirements/*.txt`、`frontend-vite/package.json`）

**后端**：Python **3.13**、FastAPI **0.137.1**、Starlette >=1.0.1、uvicorn[standard] **0.46.0**、Pydantic **2.13.2** + pydantic-settings **2.14.2**、SQLAlchemy **2.0.49**（async）、asyncpg **0.31.0** + psycopg[binary] **3.3.3**（同步，供 Alembic）、Alembic **1.16.0**、Redis[hiredis] **5.3.1**、**ARQ 0.28.0**、msgspec **0.21.1**（替代 orjson 做响应序列化）、slowapi **0.1.9**（限流）、structlog **25.5.0**、prometheus-client **0.21.0**、OpenTelemetry **1.30.0**、sentry-sdk[fastapi] **2.29.1**、PyJWT **2.13.0**（RS256）、argon2-cffi **25.1.0**、cryptography **50.0.1**、polars **1.35.2**、openpyxl **3.1.5** / XlsxWriter **3.2.2**、Pillow >=12.3,<13、httpx **0.28.1**。
> ⚠️ 仓库**无任何 Flask 依赖**（`flask_legacy` 只是历史反选口径）。

**前端**：Vue **3.5** + TypeScript **6.0** + Vite **7.1**、vue-router **5.0**、Pinia **3.0**、PrimeVue **4.5** + reka-ui、@tanstack/vue-query **5.100**、axios **1.18**、ECharts **6.0**、Tailwind **4.2**、Vitest **4.1**、ESLint **9.28**、@sentry/vue **10.56**。**Node >= 22**（engines 硬约束）。

**数据库**：PostgreSQL（README 写 18，CI 用 postgres:16-alpine → 版本口径不一致，见 §7.4）。
**Python 结构**：`pyproject.toml` **刻意不含 `[build-system]`/`[project]`** —— 依赖唯一来源是 `requirements/*.txt`；`pyproject.toml` 只承载 `[tool.code-quality]` 阈值。

---

## 3. 目录职责表

| 路径 | 职责 | 备注 |
|---|---|---|
| `fastapi_app/main.py` | 应用装配：lifespan 编排、中间件、异常处理 | 见 §4 |
| `fastapi_app/api/v1/router.py` | **端点挂载真源**（324 行，34 次 `include_router`） | 绝对导入，**零孤儿** |
| `fastapi_app/api/v1/endpoints/` | 48 个端点模块（32 顶层 + `backup/` 8 + `purchase_center/` 8） | 薄层，转发到 services |
| `fastapi_app/core/` | 45 个模块：配置、日志、安全、限流、缓存、健康、ARQ 应用、`prod_runner.py`、`production_scope.py`、`pg_locks.py`、`state_machine.py`、`telemetry.py` | S8 已拆除服务定位器 `container` |
| `fastapi_app/services/` | 165 个模块（含 `backup/` 32 项、`purchase/`、`order/`、`case/`、`staging/`、`ocr/`、`dashboard/`、`customer_sampling/`、`material_registration/`、`outsource/`、`product/`、`serializers/`） | 业务主体 |
| `fastapi_app/shared_models/` | 45 个 SQLAlchemy 模型 | 表定义真源 |
| `fastapi_app/schemas/` | 26 个 Pydantic I/O 模型 | |
| `fastapi_app/shared/` | `shipment_calc.py`、`report_data_service.py`、`customer_status.py`、`stock_concurrency.py` | 跨域共用 |
| `fastapi_app/tasks/` | ARQ 任务：backup / batch / maintenance / numbering_audit / plan / report | |
| `fastapi_app/utils/` | `scope_order.py`（部门范围） | **勿删** |
| `utils/`（仓库根） | `redis_cache.py`、`logger.py`、`sanitizer.py`、`password_validator.py`、`report_exporter.py`、`batch_upload_utils.py`、`log_rotation.py`、`performance_monitor.py` | **勿删**（`main.py` 直接 import） |
| `frontend-vite/` | Vue 3 PC + 移动端；`src/views/` 275 个文件 | 见 §7.4 vite.config 双份 |
| `migrations/versions/` | 99 个 Alembic 迁移，**单 head** | 见 §5、§7.1 |
| `server_manager.py` + `server_manager/` | NSSM 五服务管理（PyInstaller 入口），**唯一生产启停通道** | |
| `scripts/` | 约 200 项运维/质量脚本 + `ops/`、`diag/`、`database/`、`prod_audit/`(l1–l12 分层审计) | |
| `config/` | nginx、redis、pgbouncer、prometheus/grafana、otel、jwt | |
| `tests/` + `fastapi_app/tests/` | 回归测试（299 个 .py，`pytest.ini` 的 testpaths **同时**包含两者） | |
| `docs/` | 209 个 .md（adr/、decisions/、runbooks/、reports/…） | |
| `deliverables/` | 历史交付物归档（100+ 项） | **不是现行真相** |
| `_ops/credentials/` | 凭据存放（`.gitignore` 覆盖，永不入库） | 见 §6 红线 |
| `backups/`、`logs/`、`evidence/`、`_qa_tmp/` | 运行期/过程数据 | 不入库 |

---

## 4. 运行拓扑与端口

```
浏览器 / Capacitor
   │
   ▼
nginx :3000  (config/nginx-windows.conf, root = frontend-vite/dist)   ← erp-web
   │  /api、/ws、/static 反代
   ▼
uvicorn 127.0.0.1:5002  (仅回环；API 不直接暴露局域网)                 ← erp-prod
   ├── PostgreSQL :5432
   └── Redis :6379 (缓存/限流/事件)                                   ← erp-redis
ARQ worker（独立进程）── Redis :6380 (broker)                        ← erp-arq / erp-redis-broker
```

**5 个 NSSM 服务**（真源 `server_manager/constants.py:40` `_SVC_ALL`）：

| 服务 | 角色 | 端口 |
|---|---|---|
| `erp-web` | nginx 静态站 | 3000 |
| `erp-prod` | `python -m fastapi_app.core.prod_runner --no-arq` | 5002（回环） |
| `erp-arq` | ARQ worker | 6380（连 broker） |
| `erp-redis` | 缓存 Redis | 6379 |
| `erp-redis-broker` | broker Redis | 6380 |

- `_SVC_DEPENDS = {erp-prod: [erp-redis], erp-arq: [erp-redis-broker]}` —— 缺 DependOnService 会让 `erp-arq` 抢跑 broker 造成**无限重启循环**（2026-09-16 实测事故）。
- `_SVC_UVICORN_WORKERS = (erp-prod, erp-arq)`，**刻意不含 erp-web**。
- 健康真源：`logs/prod_runner.json`（原子写入），需 `ready: true` 且 `frontend_ok: true`。
- **唯一启动入口 `python start.py`**（`run.py` 已归档）。默认 `--dev`；`--prod` 走 `core/prod_runner.main`。手工起 uvicorn/vite 会与生产抢端口。
- 端口口径陷阱：`package.json` 的 dev 脚本写 `--port 5173`，但 `start.py:111` 追加 `--port 3000`，`vite.config.ts:144` 的 `server.port` 也是 3000 → **裸跑 npm run dev 才会落 5173**。

**数据流（启动编排，`fastapi_app/main.py` lifespan）**：
`setup_logging` → `_setup_database`（连接验证 + 池预热）→ 编号水位对账 `reconcile_numbering_counters`（失败只记 ERROR 不阻断）→ `db_health_checker.start()` → `setup_telemetry` → `_setup_redis_caches` → 通知管理器 `start_redis_listener` + `_register_domain_event_subscriptions` → `start_purchase_cache_listener` → `start_l1_broadcast_listener` → `sync_backup_records` → 后台任务 `_warm_inventory_cache` / `_audit_flush_loop` / `warmup_cache`。
关闭：`flush_audit_buffer` → cancel 后台任务 → 停监听 → dispose engines。
响应层用 **msgspec**（`MsgspecResponse`）替代 orjson。

---

## 5. 质量门禁与命令

### 5.1 命令

```powershell
python scripts/quality_gate.py --verbose     # 基线棘轮总门禁（8 个子门禁）
ruff check fastapi_app tests fastapi_app/tests utils
python -m mypy --config-file mypy.ini
python -m pytest -q                          # testpaths = tests + fastapi_app/tests
python scripts/scan_secrets.py --verbose     # 全树密钥扫描
python scripts/file_size_gate.py --all       # 文件/函数/组件体积
# frontend-vite/
npm run lint; npm run type-check; npm test; npm run build; npm run check:api; npm run check:routes
```

### 5.2 `scripts/quality_gate.py` —— 8 个子门禁 + 基线

读 `pyproject.toml` 的 `[tool.code-quality]`（`max_function_length=80`、`max_vue_component_length=400`、`max_file_size=1600`）。
**语义：违规数【超过】`scripts/gate_baseline.json` 才失败**（棘轮，只拦新增）。退出码 0/1/2。

| 子门禁 | 检查内容 | 当前基线 |
|---|---|---|
| `n_plus_one` | 循环内查询（AST） | 0 |
| `bare_except` | 裸 `except:` | 9 |
| `function_length` | 函数 > 80 行 | 52 |
| `vue_component_length` | .vue > 400 行 | 7 |
| `service_commit` | service 层自行 commit | 9 |
| `bom` | UTF-8 BOM | 0 |
| `alembic_heads` | 迁移多 head | 0 |
| `env_drift`（`--ci`） | .env 模板与代码读取键漂移 | 0 |

### 5.3 其他门禁脚本（各自**实际**范围）

| 脚本 | 实际检查范围 |
|---|---|
| `check_alembic_heads.py` | 用 **alembic ScriptDirectory** 解析迁移图；`EXPECTED_MAX_BASES=4`；检测多 head / 悬空 parent |
| `file_size_gate.py` | 文件 >1600 行 / 函数 >80 行 / Vue 组件 >400 行；**仅对 git 变更文件生效**（`--all` 全量） |
| `scan_secrets.py` | 私钥头、云凭据、口令赋值；支持 `# secret-scan:allow` / `-next-line`；CI 全树跑（本地 hook 可被 `--no-verify` 绕过） |
| `check_nosec_budget.py` | `# nosec` 用量预算（防豁免膨胀） |
| `audit_tx_patterns.py` | 事务边界反模式 |
| `contract_snapshot.py` | 端点契约快照（`tests/contract/snapshots/`） |
| `restore_drill.py` | 备份恢复演练 |
| `scripts/ops/check_env_drift.py` | 生产 .env 与模板漂移（S3） |
| `scripts/ops/watchdog.py` | 运行看门狗（S2） |
| `scripts/prod_audit/` | l1_static → l12_report 十二层生产审计 + `orchestrator.py` + 自带 tests（CI 独立进程跑） |

### 5.4 CI（`.github/workflows/ci-cd.yml`，3 个 job）

- **test**（ubuntu + postgres:16-alpine；`TEST_DATABASE_URL` 显式给出以绕开 conftest 的 `{DB_NAME}_test` 派生；`COVERAGE_MIN=40`）：
  `alembic upgrade head` + `alembic check` → `pytest tests fastapi_app/tests --ignore=tests/{qa,e2e,stress,performance} --cov=fastapi_app --cov=utils` → **独立进程** `pytest scripts/prod_audit/tests -q`（不加 `--cov`）→ `bandit -r fastapi_app/ utils/ -ii` → `pip-audit` → 覆盖率阈值就地判定。
- **lint**：`fetch-depth: 0` → `scan_secrets.py`（全树）→ `quality_gate.py` → `ruff check` → `mypy` → `file_size_gate.py`（PR 用 `--base`，push 用 `--all`）。
- **frontend**：Node 22 → `npm ci` → lint → `npx vitest run --reporter=junit --outputFile.junit=test-results.xml`（**必须绕开 `npm run test --`**，npm 会吞掉 `--outputFile`）→ build → 跨端对齐检查。
- 已删除：codecov 上传、playwright install、`npm run test:e2e`（脚本不存在）。

### 5.5 测试与覆盖率口径

- `pytest.ini`：`testpaths = tests fastapi_app/tests`；`asyncio_mode=auto`；`--strict-markers`；`filterwarnings=error`（忽略 UserWarning/DeprecationWarning）。
- marker：unit / integration / functional / boundary / slow / api / model / db / **contract**（contract 需真实后端 `CONTRACT_BASE_URL`，未设则整文件跳过）。
- `.coveragerc`：`source = fastapi_app`，omit tests/migrations/scripts/frontend。
- `mypy.ini` 的 `files` 是**棘轮白名单（106 条）**：core 16 + shared 2 + shared_models 5 + services 156 中已零错误的 82。**services 层仍有 74 文件 / 400 error 未纳管**。

---

## 6. 关键约定与红线

### 6.1 协作契约
`AGENTS.md` 是**唯一**契约；`.windsurfrules`、`GEMINI.md`、`.github/copilot-instructions.md` 只是指针。

### 6.2 红线（会打挂生产）
1. **不要删**根 `utils/`、`fastapi_app/utils/`、`server_manager.py` + `server_manager/`。
2. **不要**把 `config/pgbouncer/userlist.txt` 或 `_ops/credentials/**` 加回版本库。
3. **不要**让 uvicorn 绑 `0.0.0.0`（绕过 nginx 并把 `/metrics` 暴露给同网段）。
4. **不要**让 `.env` 的 `BACKUP_ENCRYPTION_PASSWORD` 为空：`BACKUP_ENCRYPTION_ENABLED=true` 时会**静默降级为不加密备份**。
5. **不要**修改/删除 `frontend-vite/vite.config.js` —— 它是 `vue-tsc -b` 编译 `vite.config.ts` 的**设计产物**，且 `fastapi_app/tests/test_qa_prod_stack_regression.py` 断言二者一致。
6. **不要**改 `core.hooksPath`（指到 husky 目录会废掉 `.githooks` 的密钥扫描）。
7. Alembic 迁移只做结构/数据变更，不夹带业务逻辑；**保持单 head**。

### 6.3 提交与豁免纪律
- 提交信息写**为什么**；一个提交只做一件事；提交前 `git status --porcelain` 确认没卷进 AI 痕迹或运行期数据。
- 密钥误报的**正确**处置：命中行尾加 `secret-scan:allow <理由>`，或上一行加 `secret-scan:allow-next-line`；`.githooks/allowlist.txt` 是逐文件豁免，新增条目**必须在提交信息里说明理由**。
- ruff `external = ["BLE001"]` 的原因：RUF100 会自动删除 `# noqa: BLE001`，而它是质量门禁的**审计豁免凭证**。新代码请用 `# defensive: <理由>`。
- `ruff.toml` 为 `services/backup/__init__.py` 关掉 `I001`：Redis 还原锁三件套**必须**排在所有星号导入之后，否则被 `query_service` 的 advisory 版遮蔽 → 端点 finally 抛 TypeError。

### 6.4 认证约定（易被误判为漏洞）
`api/v1/router.py`：**`user` 与 `permission` 刻意用 `get_current_user_id`（fail-open）** —— strict 变体在"Redis 启动即不可用"时会永久 401。**只有 `/backup` 用 `get_current_user_id_strict`**。`/auth` 无认证依赖。`/monitoring` 不加认证（POST `/vitals` 走 `sendBeacon` 无法带 header），需认证的 `GET /vitals/summary` 在 `monitoring.py` 内**单独声明**。

---

## 7. 已知坑

### 7.1 解析陷阱（本仓库踩过，已形成"伪影"级错误）
1. **迁移依赖图**：只用 `ast.Assign` 找 `revision`/`down_revision` 会漏掉 `revision: str = ...`（**AnnAssign**），从而得出伪影「4 heads（含 null）+ missing parents `pg_standalone_003`/`pg_standalone_007` + 5 roots」。补上 AnnAssign 后 → **单 head（`pg_standalone_060_fix_updated_at_varchar_columns`）、零悬空、4 roots（`add_product_factory`、`add_product_price`、`add_pp_composite_idx`、`pg_standalone_001`）**。
   → 正解：用 `alembic ScriptDirectory`（`scripts/check_alembic_heads.py` 就是这么做的）。
2. **端点孤儿**：只用"是否被 `router.py` 直接引用"判断，会得出「48 个端点模块未接线」的伪影。真相是 `router.py` 34 次 `include_router` 覆盖全部 32+2 个端点模块，**零孤儿**。
3. **死代码**：`backup/`、`purchase_center/` 通过 `__init__.py` 聚合，子模块天然不被入口直接 import → 必须按**全仓导入**判断。
4. **`__init__.py` 聚合顺序敏感**：见 §6.3 的 `backup/__init__.py` 案例（导入顺序即语义）。

### 7.2 编码陷阱
- `scripts/prod_audit/` 下部分 `.py` 与 `tests/qa/__init__.py` **曾带 UTF-8 BOM**，`ast.parse` 会报 `SyntaxError: invalid non-printable character U+FEFF`。
  **现状（2026-09-30 S10 已剥离）**：对 `fastapi_app/`、`scripts/`、`tests/`、`utils/` 全量扫描，**BOM 文件数 = 0**。遇到旧报告说"有 BOM"时按此为准。
- 仓库根 `alembic.ini` **必须纯 ASCII**（alembic 用 locale 编码读文件，zh-CN Windows 默认 GBK，中文注释会炸）。
- `.gitignore` 已忽略 `frontend-vite/dist/`，但仓库里实际存在 `dist/`、`dist-old-swap/`、`dist_prev_20260929-203959/` 三个构建产物目录。

### 7.3 shell 陷阱（Windows PowerShell **5.1**，不是 pwsh 7）
- `-Encoding utf8` 会**写 BOM**。
- **没有** `Get-Content -AsByteStream`。
- 把内联 `if(){...}else{...}` 塞进字符串插值会触发 `MissingEndParenthesisInExpression`，并让**整段脚本一行都不执行** → 分步、先赋值再输出。
- git-bash（`C:\Program Files\Git\bin\bash.exe`）里 `python` 常常不在 PATH，钩子靠绝对路径兜底。

### 7.4 「看起来像问题但其实是设计」（**不要当缺陷报**）
| 现象 | 真相 |
|---|---|
| `logs/prod_runner.json` 里 `arq.status = "external"` | **正常设计**。ARQ 由 `erp-arq` 单独托管，不在 prod_runner 进程树内 → `pid` 恒为 None、`status` 恒为 "external"（`fastapi_app/core/prod_runner.py:440-443`） |
| `user`/`permission` 端点认证是 fail-open | 刻意的可用性取舍（`router.py` 注释），strict 会让 Redis 不可用时永久 401 |
| `/monitoring` 无认证依赖 | `sendBeacon` 无法带 header；敏感读端点在模块内单独声明 |
| `config/nginx.conf` 里 `root /app/frontend-vite/dist;`（:107） | **死配置**，Windows 永不生效；真源是 `config/nginx-windows.conf` |
| `pyproject.toml` 没有 `[project]`/`[build-system]` | 刻意：依赖真源是 `requirements/*.txt` |
| `frontend-vite/vite.config.js` 与 `vite.config.ts` 并存 | **设计产物**：`.js` 是 `vue-tsc -b` 编译 `.ts` 的结果，有回归测试断言一致 |
| `mypy.ini` 注释里"发现的两个真实缺陷" | **均已修复**：`services/ocr/_extractors.py:22-24` 已显式声明三个单例（原为 `global` 未声明 → NameError）；`services/batch_import_dedup.py:32` 已把 `Container[Hashable]` 收窄为 `Iterable`。把 mypy.ini 注释当现状会误报 |
| `git log` 里的 `core.hooksPath` 事故 | **已修复**：`.githooks/` 目录已存在且 pre-commit 三层守卫在位 |
| `pyproject.toml` 的 `max_file_size=1600` 看似太松 | 有依据：受扫 777 个 .py 中仅 2 个超 1200（`test_purchase_center.py` 1497、`recovery_test_service.py` 1353） |

---

## 8. 关键文件索引

| 路径 | 一句话职责 |
|---|---|
| `AGENTS.md` | 唯一协作契约：拓扑、红线、门禁、解析方法论 |
| `fastapi_app/main.py` | 应用装配与 lifespan 编排（启动/关闭顺序真源） |
| `fastapi_app/api/v1/router.py` | 34 次 `include_router`，端点挂载与认证依赖真源 |
| `fastapi_app/core/config.py` | Settings（pydantic-settings），环境变量真源 |
| `fastapi_app/core/prod_runner.py` | 生产启动监督器；写 `logs/prod_runner.json` 健康快照 |
| `fastapi_app/core/production_scope.py` | 部门范围解析（权限码命名与范围收窄的单一事实来源） |
| `fastapi_app/core/pg_locks.py` | advisory lock 工具（与编号实现解耦） |
| `fastapi_app/services/numbering_sequence.py` | 单一取号内核（`numbering_counter` 为唯一水位源） |
| `fastapi_app/services/numbering_reconcile.py` | 启动水位对账 / 巡检落库 |
| `fastapi_app/services/backup/__init__.py` | 备份域聚合出口；导入顺序即语义（还原锁三件套） |
| `fastapi_app/services/backup/format_strategy.py` | 备份格式与加密策略；`BACKUP_ENCRYPTION_PASSWORD` 读取点 |
| `server_manager/constants.py` | 五服务/端口/依赖真源（`_SVC_ALL`、`_SVC_DEPENDS`） |
| `server_manager/service_ops.py` | NSSM 启停实现（唯一生产启停通道） |
| `start.py` | 统一启动入口（`--dev/--prod/--backend-only/--frontend-only/--check`） |
| `scripts/quality_gate.py` | 基线棘轮总门禁（8 子门禁） |
| `scripts/gate_baseline.json` | 各门禁当前基线值 |
| `scripts/check_alembic_heads.py` | 迁移图门禁（ScriptDirectory，`EXPECTED_MAX_BASES=4`） |
| `scripts/scan_secrets.py` | 密钥扫描（CI 全树） |
| `scripts/file_size_gate.py` | 文件/函数/Vue 组件体积门禁 |
| `scripts/ops/check_env_drift.py` | 生产配置漂移门禁（S3） |
| `scripts/ops/watchdog.py` | 运行看门狗（S2） |
| `scripts/prod_audit/orchestrator.py` | 十二层生产审计编排 |
| `migrations/_legacy_base_guard.py` | 空库守卫：让假定"表已存在"的历史迁移在空库重放时变 no-op |
| `migrations/env.py` | Alembic 运行时（`:56` 用 `get_sync_engine()` 覆盖 `sqlalchemy.url`） |
| `alembic.ini`（仓库根） | 2026-09-30 补入；`script_location=migrations`，必须纯 ASCII |
| `.githooks/pre-commit` | 三层提交守卫（危险路径 / 密钥扫描 / 既有门禁） |
| `.github/workflows/ci-cd.yml` | CI：test / lint / frontend 三 job |
| `pytest.ini` / `ruff.toml` / `mypy.ini` / `pyproject.toml` | 测试、lint、类型棘轮、质量阈值 |
| `frontend-vite/package.json` | 前端脚本与依赖（Node >= 22） |
| `config/nginx-windows.conf` | **生效**的 nginx 配置（`config/nginx.conf` 是死配置） |
| `.env.example` | 环境变量模板（`PG_SUPER_PASSWORD` 应用代码从不读取） |
| `tests/contract/endpoints.yaml` | 端点契约清单 |

## 9. 各维度审计起始索引（D01–D12）

> 用途：让 T07–T14 各角色**不必重做全仓发现**，直接从本节文件与锚点入手；这是本 run 上下文预算的关键杠杆。
> 锚点格式：`<相对路径> · <符号或唯一字符串> @ <行号>`。行号为 2026-09-30 只读实测值；工作区有 19 个未提交修改（见 D10 节），**以锚点字符串为准，行号仅作定位辅助**。
> 白名单：W1–W8 见 SPEC §6.3；**W9–W14 由本索引提出，lead 已采纳补入 SPEC §6.3**。命中任一 W 的模式**不得**作为 finding 出现（SPEC A20）。
> 未知项：U1–U12 全文见 `team/完整的审核一下我这个项目-060103/RESEARCH.md` §7。

### D01 架构与模块边界（建议主责 architect）

**建议起点文件**

| 文件 | 为什么从这里入手 |
|---|---|
| `fastapi_app/api/v1/router.py` | 端点挂载唯一真源（实测 34 次 `include_router`）；判断"孤儿模块"必须连各端点包的 `__init__.py` 一起看（W5） |
| `fastapi_app/main.py` | 应用装配与生命周期：`lifespan` @ 136、`app.include_router(api_router, prefix=settings.API_PREFIX)` @ 393；启动期副作用全在这条链上 |
| `fastapi_app/core/` | 45 个核心模块（deps/config/middleware/event_bus/cache/limiter/telemetry）；S8 已拆除 core→services 反向依赖，重点查是否复发 |
| `fastapi_app/services/` | 165 个服务模块（12 个子包），分层与事务边界的主要问题面 |
| `fastapi_app/shared_models/` · `fastapi_app/schemas/` | ORM 模型（45）与 Pydantic 契约（26）的分界，字段漂移入口 |
| `AGENTS.md` §2 | 官方目录职责表；"没被引用就删模块"是明文禁止 |
| `scripts/prod_audit/orchestrator.py` | 十二层静态审计编排，可复用其分层口径 |

**已知存量事实**

- 后端 `fastapi_app/**/*.py` = 527 文件 / 113,227 行（ast 实测）；端点模块 48 = 32 顶层 + `backup/` 8 + `purchase_center/` 8；`fastapi_app/api/v1/endpoints/` 顶层 .py 实测 33（含 `__init__.py`）。
- 迁移 99 revision / **单 head** / 4 root / 悬空 0。
- `fastapi_app/api/v2/` 已于 S7 删除且从未接线——勿再报"v2 未挂载"。

**最可能的误报陷阱**：W5（端点包聚合，历史上曾误报 48 个孤儿模块）、W3（`config/nginx.conf` 死配置）、W11（`pyproject.toml` 无 `[project]`）。
**明确未知项**：U11（19 个未提交改动的归属与意图）。

### D02 后端代码（建议主责 backend）

**建议起点文件**

| 文件 | 为什么从这里入手 |
|---|---|
| `fastapi_app/services/order/queries.py` | 订单查询构造核心：`_build_order_filters` @ 101、`_parse_date_condition` @ 84、`_serialize_orders` @ 178；**工作区已改** |
| `fastapi_app/services/daily_production_service.py` | 生产日报域服务，**工作区已改**（生产驾驶舱主线） |
| `fastapi_app/shared_models/daily_production_record.py` | 对应 ORM 模型，**工作区已改** |
| `fastapi_app/services/purchase_order_query.py` · `fastapi_app/services/purchase/` | 采购域查询与业务，**工作区已改** |
| `fastapi_app/core/config.py` | 设置与启动校验：`BACKUP_ENCRYPTION_*` 默认值注释 @ 133-134、校验逻辑 @ 211-215 |
| `fastapi_app/core/deps.py` | `get_current_user_id` @ 221 / `get_current_user_id_strict` @ 235 |
| `fastapi_app/api/v1/endpoints/backup/_deps.py` | `require_backup_permission` @ 102、`_get_encryption_password` @ 121 |
| `fastapi_app/core/exceptions.py` · `fastapi_app/core/exception_handler.py` · `fastapi_app/core/response.py` | 统一错误与响应契约 |
| `mypy.ini` | 棘轮白名单 106 条；**注释里举的两个"真实缺陷"已修复**，属历史记录（照抄会报过期 finding） |

**已知存量事实**

- services 层 mypy 仍有 74 文件 / 400 error（P1-1，棘轮白名单尚未收口）。
- `ruff.toml` 仅对 `fastapi_app/services/backup/__init__.py` 关闭 I001（保护契约，见 W13）。
- `fastapi_app/core/limiter.py`：`limiter_enabled_from_env` @ 25、`MemorySlidingWindowLimiter` @ 62。

**最可能的误报陷阱**：W12/W13（ruff 刻意豁免）、W9（fail-open 是设计不是漏洞）、`mypy.ini` 注释过期。
**明确未知项**：U11、U2（`_ops` 凭据与 ACL）。

### D03 前端代码（建议主责 frontend）

**建议起点文件**

| 文件 | 为什么从这里入手 |
|---|---|
| `frontend-vite/src/utils/queryKeys.ts` | `ORDER_DERIVED_QUERY_KEYS` @ 28、`invalidateOrderDerivedQueries` @ 44；**工作区已改**，跨页缓存失效的关键 |
| `frontend-vite/src/views/customer-order/composables/useOrderDelete.ts` | 客户订单删除 composable，**工作区已改**（同批还有 `useOrderDetailEdit.ts` / `useStagedItems.ts`） |
| `frontend-vite/src/views/stock/StockView.vue` · `frontend-vite/src/views/stock/StockOutTab.vue` | 库存与出库页，**工作区已改** |
| `frontend-vite/src/views/outsource/components/OutsourceOrderTab.vue` | 外发订单页，**工作区已改** |
| `frontend-vite/src/views/purchase/composables/usePurchaseActions.ts` | 采购操作 composable，**工作区已改** |
| `frontend-vite/src/views/production/components/RecordFilterBar.vue` | 通用筛选条：`defineProps` @ 79、`defineEmits` @ 87、`watch(` @ 117；**工作区已改** |
| `frontend-vite/src/views/hubei/HubeiView.vue` | 湖北视图，**工作区已改** |
| `frontend-vite/src/utils/fontAwesomeLoader.ts` | 图标动态装载（`export const iconLoaders` @ 265）；**工作区已改**，曾因 CJS 互操作导致图标空白 |
| `frontend-vite/src/router/index.ts` | 导航白名单守卫：`resolveNavAccess` @ 166、`meta.navExempt` 约定 @ 165（S9） |
| `frontend-vite/vite.config.ts` | `server.port: 3000` @ 144、`preview.port: 3000` @ 186 |

**已知存量事实**

- `frontend-vite/src` 实测 .vue 284 / 47,734 行、.ts 281 / 41,708 行；`frontend-vite/src/views/` 下 .vue 190 个；`*.test.ts` 109 个。
- `frontend-vite/package.json` 的 `dev` 脚本是 `vite --host 0.0.0.0 --port 5173`，而 `start.py` @ 111 会追加 `--port 3000` 覆盖它——**只有裸跑 `npm run dev` 才落 5173**。
- 已删除：`npm run test:e2e`、playwright 脚手架（依赖仍在，见 P1-4）。

**最可能的误报陷阱**：W4（`frontend-vite/vite.config.js` 是 `vue-tsc -b` 的设计产物，红线 5 禁删禁改，有回归测试断言二者一致）。
**明确未知项**：U6（移动端数据层残留）。

### D04 数据库与迁移（建议主责 dba）

**建议起点文件**

| 文件 | 为什么从这里入手 |
|---|---|
| `migrations/versions/` | 99 个 revision；唯一 head = `pg_standalone_060_fix_updated_at_varchar_columns.py` |
| `scripts/check_alembic_heads.py` | 迁移图门禁：`EXPECTED_MAX_BASES = 4` @ 45；@ 17 明文"必须走 ScriptDirectory，不能用朴素 AST"，`from alembic.script import ScriptDirectory` @ 50 |
| `migrations/env.py` | Alembic 运行时：`get_sync_engine()` 覆盖 `sqlalchemy.url` @ 56 |
| `migrations/_legacy_base_guard.py` | 空库守卫：`_BASE_SCHEMA_MARKERS = ('product','customer')` @ 35、`base_schema_absent()` @ 38；设计说明 @ 18-22 |
| `migrations/add_fabric_color_no.py` | **裸脚本**（不在 `versions/`）：`information_schema.columns` @ 16、`ALTER TABLE customer_sampling_part` @ 23（P2-1） |
| `alembic.ini`（仓库根） | 2026-09-30 补入；`script_location=migrations`，必须纯 ASCII（alembic 按 locale 编码读，zh-CN 是 GBK） |
| `migrations/alembic.ini` | `script_location=%(here)s`；注释警告不能 `cd migrations` |
| `fastapi_app/core/database.py` · `fastapi_app/core/db_health.py` | 连接池与健康检查 |

**已知存量事实**

- 迁移 99 revision / 单 head / 4 root / 悬空 0（**用 ast 找 head 必须同时处理 `ast.AnnAssign`**，只找 `ast.Assign` 会得到"4 heads + 悬空 parent"的纯伪影）。
- `pg_standalone_054_sync_schema_with_orm_metadata` 之下混着自包含建库迁移与假定表已存在的增量迁移 → 空库 `upgrade head` 靠 `_legacy_base_guard` 变 no-op，而非报错。

**最可能的误报陷阱**：W5 同段（历史伪影"15 个迁移 head"）；B4（与既有简报不一致时以 ast 为准，且须写明两种方法结果）。
**明确未知项**：U3（PG 版本口径与 `alembic current` 实测）、U4（`fabric_color_no` 是否已手工 DDL）。

### D05 安全（建议主责 sec）

**建议起点文件**

| 文件 | 为什么从这里入手 |
|---|---|
| `fastapi_app/core/deps.py` | `get_current_user_id` @ 221（fail-open）与 `get_current_user_id_strict` @ 235（strict） |
| `fastapi_app/api/v1/router.py` | `/users` fail-open @ 130-134、`/permissions` fail-open @ 261-265、全仓唯一 strict 的 `/backup` @ 273 |
| `fastapi_app/api/v1/endpoints/monitoring.py` | 无认证说明 @ 46-47、`POST /vitals` @ 205-207（sendBeacon）、`GET /vitals/summary` @ 225-228（单独 Depends） |
| `fastapi_app/core/security.py` | 三代口令兼容：`hash_password` @ 28、`_verify_bcrypt` @ 39、`_verify_legacy_pbkdf2` @ 52、`_verify_legacy_scrypt` @ 75 |
| `fastapi_app/core/sanitizer.py` | `escape_like` @ 34、`sanitize_for_log` @ 44、`safe_exception_message` @ 85 |
| `fastapi_app/core/limiter.py` | `limiter_enabled_from_env` @ 25、`MemorySlidingWindowLimiter` @ 62 |
| `fastapi_app/services/backup/_constants.py` | `BACKUP_ENCRYPTION_ENABLED` 默认 true @ 43、`BACKUP_ENCRYPTION_PASSWORD` 默认 '' @ 44 |
| `fastapi_app/services/backup/crypto.py` · `fastapi_app/services/backup/incremental.py` | 空密码→不加密（crypto.py @ 57/60/62）vs 未配密码→`raise BackupError`（incremental.py @ 116） |
| `scripts/scan_secrets.py` | `dangerous_path_reason` @ 110、`content_secret_reason` @ 142 |
| `.githooks/pre-commit` | 抑制标记约定 @ 28-29、`secret-scan:allow` @ 173；2026-09-17 凭据入库事故的修复点 |
| `config/security-headers.conf` · `config/jwt/` | 安全响应头与 JWT 密钥对（private_v2.pem / public_v2.pem） |

**已知存量事实**

- 根 `.env.production` 的 `BACKUP_ENCRYPTION_PASSWORD` 为空、`SECRET_KEY` 仅 13 字符（P0-2）；根 `.env` 当前安全（43 / 64 字符）。
- **全量备份空密码静默不加密，增量硬失败**——同一开关两种语义（P0-2/P2-3）。
- 34 个挂载中只有 `/backup` 用 strict；`/auth` 无认证依赖。

**最可能的误报陷阱**：W9（fail-open 是设计）、W10（`/monitoring` 无全局认证是设计）、W7（AI 痕迹目录已被 `.gitignore` 覆盖）。
**明确未知项**：U2（`_ops/credentials` 与轮换）、U10（备份加密产物核验）、U12（bandit / pip-audit 现状）。

### D06 运维部署与 CI（建议主责 devops）

**建议起点文件**

| 文件 | 为什么从这里入手 |
|---|---|
| `server_manager/constants.py` | `_VERSION = 'v5.33'` @ 13、`_SVC_DEPENDS` @ 31、`_SVC_UVICORN_WORKERS` @ 45（刻意不含 erp-web） |
| `start.py` | 唯一入口：参数定义 @ 28-45、`--web-port` 默认 3000 @ 45、追加 `--port` @ 111 |
| `fastapi_app/core/prod_runner.py` | `arq.status` 恒为 `external` 的设计注释 @ 440 / 443 / 469 |
| `.github/workflows/ci-cd.yml` | 三 job：`name:` @ 1、`runs-on: ubuntu-latest` @ 11、`COVERAGE_MIN: "40"` @ 39 |
| `config/nginx-windows.conf` · `config/nginx.conf` | 前者**生效**（root = `frontend-vite/dist`），后者 root `/app/...` 在 Windows 永不生效（死配置） |
| `scripts/ops/check_env_drift.py` | `parse_env_file` @ 108、`scan_code_refs` @ 148（S3 配置漂移门禁） |
| `scripts/ops/watchdog.py` | `CheckResult` @ 71、`load_env_file` @ 82（S2 运行看门狗） |
| `logs/prod_runner.json` | 健康真源：需 `ready:true` 且 `frontend_ok:true` |
| `.env.production` · `.env.example` | 环境变量真源与模板（`PG_SUPER_PASSWORD` 应用代码从不读取） |

**已知存量事实**

- 5 个 NSSM 服务：erp-prod / erp-arq / erp-web / erp-redis / erp-redis-broker；`erp-prod` 以 `python -m fastapi_app.core.prod_runner --no-arq` 启动，ARQ 由 erp-arq 单独托管。
- uvicorn 只绑 `127.0.0.1:5002`（红线 3）；端口 6379 / 6380 / 5002 / 3000。
- `_SVC_DEPENDS` 缺失时 erp-arq 会抢跑 6380 → 无限重启循环（2026-09-16 实测）。

**最可能的误报陷阱**：W1 / W2 / W8（`external` 状态是设计，`ready:true`+`frontend_ok:true` 即健康）、W3（nginx 死配置可作 P3 技术债）、W7。
**明确未知项**：U1（生产实际加载哪个 env）、U9（看门狗计划任务是否真的注册）、U8（压测报告时效）。

### D07 文档（建议主责 docs）

**建议起点文件**

| 文件 | 为什么从这里入手 |
|---|---|
| `docs/` | 209 个 .md（全仓 576 个 .md）；**历史归档，可能过期**，以代码为准 |
| `AGENTS.md` | 唯一协作契约（§0 无测试/预发环境、§2 目录职责、§3 拓扑、§4 门禁、§5 红线 7 条、§6 分析坑、§7 AI 痕迹治理） |
| `README.md` | 架构图与快速开始；**写 PostgreSQL 18，与 CI 的 postgres:16 口径不一致**（P2-2） |
| `team/完整的审核一下我这个项目-060103/SPEC.md` | 本次审核的规格真源（12 维度 / 26 条验收 / §6.3 白名单 / §7 边界 B1–B11 / §11 对照起点） |
| `team/完整的审核一下我这个项目-060103/TASKS.json` · `DECISIONS.md` · `任务看板.md` | 任务与决策记录 |
| `team/REPOWIKI.md`（本文件） | 团队共享项目知识库，本 run 唯一权威项目知识源 |

**已知存量事实**

- `deliverables/`、`docs/` 是历史归档，不得当现行真相（AGENTS §6）。
- `AGENTS.md`、`.windsurfrules`、`GEMINI.md`、`.github/copilot-instructions.md` 刻意**不**忽略；其余 AI 工具目录已忽略（W7）。

**最可能的误报陷阱**：W6（中文乱码/终端编码不算 finding）、W3 / W4（文档里描述的"问题"可能正是设计）。
**明确未知项**：U11（未提交改动归属）。

### D08 UI-UX（建议主责 ui）

**建议起点文件**

| 文件 | 为什么从这里入手 |
|---|---|
| `frontend-vite/src/views/` | 190 个 .vue；按业务域（production / purchase / stock / customer-order / hubei）逐个看信息密度与一致性 |
| `frontend-vite/src/components/` | 通用组件层，PrimeVue 4.5.5 + Tailwind 4.2.4 的封装边界 |
| `frontend-vite/src/views/production/components/RecordFilterBar.vue` | 生产驾驶舱筛选条（近期重构重点），`defineProps` @ 79 / `watch(` @ 117 |
| `scripts/prod_audit/layers/fix_a11y.py` | 专门的 a11y 修复层，可作已查项基线 |
| `frontend-vite/src/router/index.ts` | 导航可达性与 `meta.navExempt` 白名单（S9） |
| `frontend-vite/vite.config.ts` | PWA 插件、chunk 切分与 `server.port` @ 144 |

**已知存量事实**

- 生产驾驶舱近期重构：趋势面板、部门排行、KPI 环比、明细抽屉、单行快捷录入、部门范围权限收窄（6 个权限点种子）。
- `gate_baseline.json` 中 `vue_component_length` = 7（7 个超长组件已被基线承认，新增会失败）。

**最可能的误报陷阱**：W4（`vite.config.js` 禁删禁改）、W6。
**明确未知项**：U5（a11y 与首屏）、U6（移动端数据层）。

### D09 测试与质量门禁（建议主责 qa）

**建议起点文件**

| 文件 | 为什么从这里入手 |
|---|---|
| `scripts/quality_gate.py` | 基线棘轮总闸：`GATES` @ 67、`main` @ 202（8 个子门禁，退出码 0/1/2） |
| `scripts/gate_baseline.json` | 当前基线：n_plus_one 0 / bare_except 9 / function_length 52 / vue_component_length 7 / service_commit 9 / bom 0 / alembic_heads 0 / env_drift 0 |
| `scripts/file_size_gate.py` | `_threshold_from_pyproject` @ 56（阈值 1600，见 W14） |
| `scripts/check_bare_except.py` · `scripts/check_alembic_heads.py` | BLE001 豁免凭证的消费方与迁移图门禁 |
| `pytest.ini` | `testpaths` @ 3、`asyncio_mode = auto` @ 9、`addopts` @ 13（含 `--strict-markers` 与 `filterwarnings=error`） |
| `.coveragerc` | `source = fastapi_app` @ 2、`omit` @ 3 |
| `ruff.toml` · `mypy.ini` · `pyproject.toml` | lint / 类型棘轮 / 质量阈值（`[tool.code-quality]` @ 13） |
| `tests/` · `fastapi_app/tests/` | 144 + 155 个测试文件（顶层 132 个 .py） |
| `tests/contract/endpoints.yaml` | 端点契约清单（无 `CONTRACT_BASE_URL` 时整个 contract 文件跳过） |
| `frontend-vite/src/**/*.test.ts` | 109 个前端单测 |

**已知存量事实**

- 测试 299 文件 / 3,338 用例；CI 覆盖率门槛 40，且 `--ignore` 掉 qa/e2e/stress/performance。
- CI `lint` job：`fetch-depth:0` → `scripts/scan_secrets.py` 全树 → `quality_gate.py` → ruff → mypy → `file_size_gate`。
- 板房域后端零专用测试（P1-2）、`dead_letter` 零测试（P1-3）、前端 playwright 有依赖无脚手架（P1-4）。

**最可能的误报陷阱**：W6；**不要用"测试是否 import 某模块"判覆盖率**——大量测试经 TestClient 走 HTTP，该启发式曾误判 `auth_service.py` / `bom_service.py` / `stock_in_service.py` 未覆盖。
**明确未知项**：U7（真实覆盖率分布）、U12（bandit / pip-audit 现状）。

### D10 需求一致性（建议主责 pm / reviewer）

**建议起点文件**

| 文件 | 为什么从这里入手 |
|---|---|
| `team/完整的审核一下我这个项目-060103/SPEC.md` | §2.1 十二维度、§4 验收 A01–A26（A20 白名单 / A25 门禁顺序 / A08 撤销率 >40%）、§7 边界 B1–B11、§11 对照起点 |
| `team/完整的审核一下我这个项目-060103/TASKS.json` | 20 个任务与依赖；核对 inScope 与验收是否自洽 |
| `team/完整的审核一下我这个项目-060103/POLICY.md` · `DECISIONS.md` | 澄清上限 5 问、代决策须留行 |
| `docs/` | 需求侧历史文档（须与代码对照，冲突以代码为准） |
| `git status --porcelain` | 工作区 19 M + 3 ??（P0-1）：**审计对象必须是工作区而非 HEAD** |

**已知存量事实**

- 19 个修改文件横跨后端 `fastapi_app/services/`、`fastapi_app/shared_models/`、前端 `frontend-vite/src/`（详见 D02/D03 起点表）。
- 3 个未跟踪新增：`fastapi_app/tests/test_order_derived_cache_no_l1.py`、`frontend-vite/src/test/crossPageRealtimeWebSocket.test.ts`、`frontend-vite/src/test/customerOrderCrossPageInvalidation.test.ts`。

**最可能的误报陷阱**：B1（代码与文档冲突以代码为准）、B4（以 ast 为准并写明两种方法）。
**明确未知项**：U11（未提交改动属于哪个需求）。

### D11 性能与可观测性（建议主责 devops / backend）

**建议起点文件**

| 文件 | 为什么从这里入手 |
|---|---|
| `fastapi_app/core/metrics.py` | `METRICS_AVAILABLE` @ 10（降级开关）、`_get_or_create_counter` @ 39 |
| `fastapi_app/core/slow_query.py` | `_SlowQueryCounter` @ 29、`_get_threshold` @ 51、`setup_slow_query_listener` @ 78 |
| `fastapi_app/core/telemetry.py` | `setup_telemetry` @ 17、`get_tracer` @ 107、`attach_trace_context` @ 126 |
| `fastapi_app/api/v1/endpoints/monitoring.py` | Web Vitals 上报与汇总（批次 + IP 限流），`POST /vitals` @ 205-207 |
| `config/prometheus.yml` | `scrape_configs` @ 16、`job_name: 'fastapi'` @ 18、targets `app:5002` @ 21 |
| `config/alert_rules.yml` | `ERP_QueryLatencyP95High` @ 6、`ERP_WriteLatencyP95High` @ 17 |
| `config/otel-collector.yaml` · `config/promtail.yml` · `config/grafana/` | 链路、日志采集与看板 |

**已知存量事实**

- `fastapi_app/core/metrics.py` 有 `METRICS_AVAILABLE` 降级路径——指标不可用时不应报"监控缺失"。
- `/monitoring` 的上报端点无认证是设计（W10）。

**最可能的误报陷阱**：W10、W1 / W2（`external` 状态）。
**明确未知项**：U8（压测报告时效与口径）。

### D12 数据一致性与并发（建议主责 dba / backend）

**建议起点文件**

| 文件 | 为什么从这里入手 |
|---|---|
| `fastapi_app/core/pg_locks.py` | `number_lock_key` @ 15（PG advisory lock 取号） |
| `fastapi_app/core/state_machine.py` | `ApprovalState` @ 9、`get_allowed_actions` @ 46（审批状态机） |
| `fastapi_app/main.py` | 启动对账：`reconcile_numbering_counters` @ 145-147（失败只记 ERROR 不阻断） |
| `fastapi_app/services/backup/incremental.py` | `create_incremental_backup` @ 31、`create_wal_incremental_backup` @ 157（增量备份一致性） |
| `fastapi_app/core/cache_invalidation.py` · `fastapi_app/core/cache.py` | 缓存失效与 L1/L2 一致性 |
| `fastapi_app/services/daily_production_service.py` | 生产日报写入路径，**工作区已改** |
| `migrations/versions/` | 编号水位与唯一约束的 schema 依据 |

**已知存量事实**

- 编号体系已统一北京口径 + 单一取号内核 + 启动对账，`core/number_generator` 已删除；`numbering_counter` 是唯一水位源。
- 批量导入改异步取号消灭双水位；`read_daily_max` 改数值排序 + 日期段过滤，根除 9999 字典序缺陷。
- `services/backup/__init__.py` 的导入顺序是 Redis 还原锁的保护契约（W13）。

**最可能的误报陷阱**：W9（fail-open 影响撤销缓存路径，属设计取舍）、W13。
**明确未知项**：U10（备份加密产物核验）、U4（`fabric_color_no` 手工 DDL 是否已执行）。

---

**维护约定**：本节只增不改；新增 W/U 编号必须同步 `team/完整的审核一下我这个项目-060103/SPEC.md` §6.3 与 `team/完整的审核一下我这个项目-060103/RESEARCH.md` §5/§7，避免两侧编号漂移。

