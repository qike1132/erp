# 滨发协同系统 · 代码与架构全面评审（第 3 轮）

- 评审对象：`D:\erp_system`（内网生产 ERP；本机同时是生产主机与运维主机，无独立测试/预发环境）
- 取证基线：`HEAD = 546401ec`（2026-10-01 15:10:43 +0800，508 个提交，最早 2026-04-15），工作区无代码改动
- 方法：`ocr scan --preview` 界定文件宇宙（2325 文件 / will_review 1377 / 可审代码 1171）→ `ocr delegate rule` 取审查口径 → 6 路只读并行分析（既有审计 digest、后端、前端、数据层/领域、运维/安全、开源 ERP 对标）+ Lead 逐条交叉核验（AST/实跑门禁/实读配置/ACL/端口/计划任务）
- 规则：只读；任何结论必须带 `路径:行号`；`precision over recall`（上下文不清即沉默）；口径冲突禁止合成，逐条标注
- 本轮对既有报告的修正：见 §7

---

## 1. 一句话结论

**不是最优，但也绝不属于"重写"范畴。**主方向（api→services→core/shared_models 单向分层）正确，事务/权限/缓存/异常/健康判据这些"纪律性资产"明显强于同规模内网 ERP；真正的差距**不是架构选型错了，而是三类错位**：①能力已具备但未收尾；②门禁存在却抓错对象（抓"当前零错的文件"，不抓真正的重灾区）；③有方案但无任何执行状态记录，导致方案漂移。

一句话概括风险画像：**它最怕的两件事——"库存静默错账"和"备份看似有实则无"——恰好都还没上保险。**

### 分维度评分（1–5，Lead 自评，非 ISO 评级）

| 维度 | 分 | 依据（要点） |
|---|---|---|
| 分层与模块化 | 3.5 | 主方向正确、零孤儿路由；但 5 个上帝对象、87 个超 80 行函数、2 条纵切反向边 |
| 事务一致性 | 4.0 | 端点层 commit/rollback = 0，服务层 9 处 = 文档基线；但门禁可被一行注释绕过 |
| 库存/领域正确性 | 2.5 | 余额就地改 54 处、流水另写 26 处，无结存无成本、无仓库维度、DB 无 `CHECK(>=0)` |
| 数据层/迁移 | 4.0 | 单 head（99 迁移）、SQLAlchemy 2.0、Numeric 选型正确；时区/约束/审计字段有欠账 |
| 安全与暴露面 | 2.5 | `/metrics` fail-closed、ES256+jti、Argon2id 是亮点；但 5 服务全 LocalSystem、`.env` 对所有本机用户可读、PG 监听 0.0.0.0（**pg_hba 仅放行本机，故非未授权访问**，见 §9）、无 TLS、**限流键可伪造绕过**、**主动告警通道为零** |
| 可观测性与运维 | 3.0 | request_id 全链路、Prometheus 埋点、`logs/prod_runner.json` 健康真源；但**主动告警通道为零**（Sentry/OTEL/BACKUP_ALERT 全关、watchdog 任务未注册）、恢复演练断档 39 天、备份包不完整且无异地副本（**备份本身由 ARQ cron 正常在跑**，Windows 计划任务是 Disabled 的死任务，见 §9） |
| 前端工程 | 3.5 | 路由守卫 fail-closed 且有单测、跨层对齐脚本齐全；7 个超 400 行组件、双 UI 组件库并存 |
| 门禁与 CI | 4.0 | CI 4 个 job 覆盖迁移校验/质量棘轮/秘密扫描/文件体积/前端对齐；无部署 job、无 `check:api`、mypy 只收零错文件 |
| 性能与容量 | 3.5 | Redis+LRU 双层缓存、keyset 分页、ARQ；N+1 与循环内 DB 调用、连接池未接线 |
| **综合** | **3.3** | 「良好但不最优」：工程纪律强、模块粒度失控、执行台账缺位 |

---

## 2. 值得肯定（这些不要动）

1. **事务纪律**：`python scripts/check_service_commit.py` 实测 `[FAIL]` 9 处 = 文档基线，棘轮零余量；端点层 commit/rollback **0 处**（`docs/TRANSACTION_BOUNDARY_GUIDE.md` §2.3 被严格执行）；全仓 `db.begin()` 0 处。
2. **迁移链健康**：`python -m alembic heads` → 唯一 head `pg_standalone_060_fix_updated_at_varchar_columns`；99 个版本文件、4 个 root 已收敛、无断链；CI 有独立校验 job（`.github/workflows/ci-cd.yml:63` 等）。这一点五家主流开源 ERP 无一等价。
3. **编号序列内核**：`fastapi_app/services/numbering_sequence.py:30-46` 用单语句 `INSERT … ON CONFLICT DO UPDATE … RETURNING` 原子取号，跨进程不重号，另有 reconcile/audit。**优于多数开源实现**（差距只在格式不可配置）。
4. **权限与身份**：`fastapi_app/core/deps.py:279/300/328` 三件套唯一实现（无平行实现）；业务写端点权限覆盖率高（outsource 26/16、purchase_plan 24/10、order_routes 20/13…）；`notification.py:76` 用身份而非权限授权，属正确设计；user/permission 路由刻意 fail-open 且有注释说明理由。
5. **缓存与一致性工具**：`fastapi_app/core/cache.py` 具备 L1+L2、防击穿分布式锁、Redis 熔断、L1 pub/sub 广播失效；统一失效入口 `fastapi_app/core/cache_invalidation.py:30`。
6. **异常与可观测性**：`fastapi_app/main.py:275/302/322/344/364` 统一异常处理；裸 except 0 处；X-Request-ID 中间件（`core/middleware.py:98-116`）；`/metrics` 在未配置 `METRICS_BEARER_TOKEN` 时返回 503（`core/health.py:200-211`、`core/config.py:260-262`）——**fail-closed 而非 fail-open**。
7. **恢复演练的"设计"很认真**（只是没在跑）：真建库、manifest SHA256 全量校验、"约束数为 0"判失败、finally 强制清理（`fastapi_app/services/backup/orchestration/recovery_test_service.py:161-224/356-408/911-919/152-159`）。
8. **前端守卫 fail-closed**：`frontend-vite/src/router/navAccess.ts:115-159` `resolveNavAccess` 在导航数据加载失败时 `return false`/`return buildLoginRedirect`，并有单测 `frontend-vite/src/test/routerNavAccess.test.ts`。

---

## 3. 结构性短板（"不是最优"的具体所指）

### 3.1 库存没有单一真相 —— 最该动的一块
- 【事实】`current_stock` 写点 **54 处 / 24 文件**（其中 17 处在测试）；非测试热点：`fastapi_app/services/case/commands.py` 6、`batch_import_service.py` 4、`stock_out_service.py` 4、`batch_import_core.py` 3、`stock_in_service.py` 3、`order/deduction.py` 3。
- 【事实】`InventoryLog(...)` 构造点 **26 处**（`approval_service.py:334/385/417`、`batch_import_core.py:384/470/569`、`batch_import_service.py:258/497`…），而 `fastapi_app/shared_models/inventory_log.py:20` **只有位移没有结存**（无 running_balance、无成本列）。
- 【事实】DB 层兜底几乎为零：`fastapi_app/shared_models` 内 `CheckConstraint` 仅 `customer_sampling.py:323-324` 两条；`shared_models/product.py:37` `current_stock` **无 `CHECK(>=0)`**。
- 【事实】负库存不变式被复制在 3 处：`fastapi_app/shared/stock_concurrency.py:86`、`fastapi_app/services/batch_import_service.py:333` 与 `:575`、`fastapi_app/services/case/commands.py:313`。
- 【事实】乐观锁名存实亡：`stock_concurrency.py:44-109` 依赖 `product.version`，但扣减路径直接改 `current_stock` 不碰 version（`order_deduction_service.py:120`、`order/deduction.py:129/181/194`）。
- 【事实】无仓库/库位维度（`shared_models` 内 warehouse/仓库/location 仅 1 处命中），库存无批次/序列号追溯。
- 【结论】"余额可被 54 处就地改写、且数据库不设下限"是**唯一一类不可事后追回的数据损坏**。参考 ERPNext：SLE 只追加、作废打标记、余额表 `Bin` 只是派生缓存、估值从改动点向后重算。

### 3.2 备份/恢复能力是"假设"而非"事实"
- 【事实】计划任务 `ERP_Database_Backup`、`ERPSystem` 当前状态 **Disabled**（`Get-ScheduledTask` 实测）；`logs/watchdog_state.json` 与 `watchdog.log` 最后写入停在 `2026-09-30 18:10:22`。
- 【事实】最近一次演练产物是 `backups/server/recovery_tests/m5_drill_raw_20260823.json`（2026-08-23）。
- 【事实】`scripts/restore_drill.py:36` 用 `glob('erp_backup_*.zip')` 选产物，而实际加密产物为 `*.zip.enc` → 选不到。
- 【事实】口令缺失时按"不加密"处理：`fastapi_app/services/backup/crypto.py:57-68` 返回 `None` + warning；`fastapi_app/api/v1/endpoints/backup/_deps.py:150-170` `_resolve_encryption` 显式设计为 `(False, None)` 并注明「fail-safe：宁可明文可还原，不可密文打不开」。
- 【判断】这不是"意外写入明文"，而是**一个有理由的降级被静默接受**：warning 不构成告警，接口也不回告"本次未加密"。在内网生产环境，这需要升级为"显式确认或直接失败"。

### 3.3 静默数据丢失缺信号（需修正既有描述）
- 【事实】`fastapi_app/core/database.py:226-240`：注释明写「FastAPI 0.106+ 语义：依赖收尾在响应发送之后执行，commit 失败时客户端已收到成功响应」，随后 `logger.error(...)` → `await session.rollback()` → **`raise`**。
- 【修正】既有报告称"仅 logger.error、无抛出"不准确——代码**有 raise**；真正的问题是 ①响应已发出、②没有计数器/指标，无法告警与统计。

### 3.4 模块粒度失控 + 门禁抓错对象
- 【事实】上帝对象：`recovery_test_service.py:29` 单类 1322 行（占 `max_file_size=1600` 的 85%）、`services/backup/cleanup/service.py:48` 783 行（全文件仅 3 个顶层单元）、`server_manager/app.py:170` 1328 行、`fastapi_app/tasks/backup_tasks.py` 1008 行、`api/v1/endpoints/backup/validation.py` 857 行（内含 201 行的 `validate_backup_file@377` 与 160 行的 `validate_backup_integrity@584`，业务逻辑写在端点层）。
- 【事实】87 个函数超 80 行门槛，最大 `fastapi_app/services/backup/orchestration/core.py:149` `_do_create_full_backup`（320 行）。
- 【事实】质量门禁是"只拦新增"的棘轮（`scripts/gate_baseline.json`：`bare_except 5 / function_length 51 / vue_component_length 7 / service_commit 9 / bom 0 / alembic_heads 0 / env_drift 0`）→ 存量永不偿还。
- 【事实】类型门禁只收"当前零错"的文件（`mypy.ini:13-20`，约 110 项），而 `fastapi_app/services/` 单独全量仍约 387 errors（arg-type 97 / assignment 60 / attr-defined 49），重灾区不在门禁视野内；白名单里还留着 3 个死模块（`mypy.ini:50/:60/:130`）。
- 【事实】门禁存在**注释旁路**：`scripts/check_service_commit.py:32-39` 的 `ALLOWED_PATTERNS` 含 `r"#\s*independent[-_]transaction"`，与 `docs/TRANSACTION_BOUNDARY_GUIDE.md:48`「脚本**不会**因为该注释而跳过」**直接矛盾**；行尾写该注释即可静默通过。

### 3.5 反向边与纵切依赖
- `fastapi_app/api/v1/endpoints/backup/validation.py:80` 直接导入 ARQ 任务私有函数 `_do_integrity_check`（api→tasks 越层）。
- `fastapi_app/core/event_bus.py:25/:34` 在事件总线热路径导入 `services/notification_service`；`core/health.py:62`、`core/arq_app.py:161` 同类。
- 根 `utils/` 反向依赖应用层（`utils/redis_cache.py:538/:542`、`utils/batch_upload_utils.py:89`），破坏 `server_manager`/`prod_runner` 的"utils 可独立打包"前提。
- 死代码约 1,100 行 / 8 个模块：`core/alert_rules.py`(37)、`core/domains.py`(86)、`schemas/purchase.py`(39)、`services/batch_pipeline.py`(128)、`services/purchase_order_service.py`(65)、`services/backup/_stream.py`(14)、`shared_models/base.py`(6)、`services/purchase_order_spare.py`(249)、`utils/batch_upload_utils.py`(501)、`utils/logger.py`(164)。

### 3.6 安全与暴露面（最需要立刻处理的一组）
- 【事实】5 个 NSSM 服务（erp-web / erp-prod / erp-arq / erp-redis / erp-redis-broker）**全部以 LocalSystem 运行、启动类型 Auto**。Web 层任何 RCE = 本机 SYSTEM。
- 【事实】根 `D:\erp_system\.env`（8643 字节）含 `DB_PASSWORD`、`REDIS_PASSWORD`、`SECRET_KEY`、`PG_SUPER_PASSWORD`、`BACKUP_ENCRYPTION_PASSWORD`、`METRICS_BEARER_TOKEN`、`JWT_PRIVATE_KEY_PATH` 等；其实测 ACL 为 `NT AUTHORITY\Authenticated Users:(I)(M)` + `BUILTIN\Users:(I)(RX)` → **任何本机已认证用户可读**。
- 【事实】`_ops/credentials/` 内含 `_backup_encryption_password.txt`(827B)、`_metrics_bearer_token.txt`(43B)、`.env.bak-20260911`、`.env.bak-20260927-085022`（该目录 ACL 较紧，无 Authenticated Users）。
- 【事实】端口实测：nginx `:3000` 监听 `0.0.0.0` 且**无 TLS**（`config/nginx-windows.conf` 无 `ssl_certificate`）、**无 `limit_req`**（OPT-17/18 未实施）；uvicorn `:5002` 仅 `127.0.0.1`（正确，符合红线）；**PostgreSQL `:5432` 监听 `0.0.0.0`**；Redis `:6379/:6380` 仅回环。
- 【事实】**限流键可被伪造绕过（已定位完整机制）**：`fastapi_app/main.py:256-271` 未登录时速率限制键回落 `get_remote_address(request)`；`fastapi_app/core/prod_runner.py:267-268` 给 uvicorn 传 `--proxy-headers --forwarded-allow-ips=*`，`.venv/Lib/site-packages/uvicorn/middleware/proxy_headers.py:163-164` 在 `always_trust` 下取 `X-Forwarded-For` **最左值**并覆盖 `request.client.host`，而 `config/nginx-windows.conf:60` 用 `$proxy_add_x_forwarded_for` 把客户端自带头保留在最左 ⇒ 换头即换桶。**对照：审计 IP 不可伪造**（`fastapi_app/core/audit_middleware.py:134-138`/`:202-205` 取 XFF 最右值 = nginx 追加的真实地址）。
- 【事实】`fastapi_app/api/v1/endpoints/customer_sampling.py:63` `router = APIRouter()` 无 `dependencies=`，权限点只挂在写端点（`:126/:149/:182/:199/:215/:261/:294/:312`）→ 9 个 GET 无模块级权限校验，且 `:4` docstring 自称"需登录"。
- 【事实】`scripts/restart_backend.py:66` 使用 `--host 0.0.0.0`。
- 【事实】`config/pgbouncer/pgbouncer.ini:15` `listen_addr = 0.0.0.0`（Windows 版）。

### 3.7 领域正确性零散但真实的坑
- 【事实】`shared_models/approval.py:56` `default=_utcnow` 与 `:61` `default=datetime.now`（另 `:128` 对 `:130` 同款）→ 同表两套时钟，差 8 小时，审批/审计时间不可作证据。
- 【事实】`fastapi_app/services/stock_common.py:9-19` 用 `datetime.now(UTC)` 的时分秒拼 naive 业务日期 → 与北京时间差 8 小时，影响业务日归属。
- 【事实】17 个 naive DateTime 与 124 个 timestamptz 并存，且同表混用（`shared_models/order.py:92-95`：`deleted_at` naive、`order_date` timestamptz）。
- 【事实】`shared_models/stock_return.py:32` `stockout_id ondelete='CASCADE'` 与 `fastapi_app/services/order/deduction.py:189` 的硬删组合 → **退货历史随扣减被级联删除**。
- 【事实】`fastapi_app/services/numbering_sequence.py:61` 仅首次 INSERT 用 `seed+1`、`:34` 的 ON CONFLICT 分支忽略 seed → counter 落后于数据表最大号时连续撞唯一索引报 500；`:115-127` `read_daily_max` 用正则 + `split_part` 全表扫，唯一索引不可用。
- 【事实】`fastapi_app/services/order_batch_create.py:326-327` 一次 IN + `with_for_update` 锁产品集合并贯穿整个批量循环，且无 `ORDER BY` → 商品集合重叠的并发批量有死锁风险。
- 【事实】`fastapi_app/services/order/deduction.py:204` 结尾无 `remaining>0` 校验、`:254` 仍返回"抵扣数量修改成功" → 静默部分完成。
- 【事实】审计字段覆盖率低：46/67 表无 `created_at`、26/67 表无 `updated_at`；67 张表中仅 `order.py:92`、`stock_in.py:36` 有软删除；出货/退货/皮套单据走物理删除，且 `ModificationLog` 只覆盖 BOM/产品角色/采购订单。
- 【事实】`shared_models/daily_production_record.py:19-24` 无 `UniqueConstraint(department, production_date, product_id)`，而生产量按 product_id 跨三部门求和（`fifo_allocation.py:377-392`）→ 重复录入即翻倍。

### 3.8 性能与容量
- 【事实】循环内 DB 调用热点（AST 检出）：`services/bom_service.py:429`（循环@427 `save_bom`）、`batch_import_service.py:256`、`order_batch_create.py:184`、`purchase_order_crud.py:197`（`_upsert_order_items` 逐条 `db.get`）、`purchase_supplier_service.py:153`、`shared/stock_concurrency.py:76` 等。
- 【事实】连接池**已接线**（`fastapi_app/core/database.py:25-53` `_get_pool_config()` 由 `UVICORN_WORKERS`×`DB_MAX_CONNECTIONS` 计算：pool_size=5、max_overflow=3，8 并发 worker 下 8×(5+3)=64 < `max_connections=100`，并配 `pool_timeout/pool_pre_ping/pool_use_lifo`）；**但 `.env` 的 `DB_POOL_SIZE`/`DB_MAX_OVERFLOW`/`DB_POOL_RECYCLE` 是死键**（从不读取，"改了不生效"），且**缺 `pool_recycle`**。
- 【事实】`fastapi_app/core/audit_middleware.py:300` 在请求热路径循环内 `session.execute`；`tasks/batch_tasks.py:142`、`tasks/backup_tasks.py:320` 循环内 commit。
- 【事实】ARQ 无幂等键（`core/arq_app.py:201` `max_tries=3`），重试会重复执行写操作。
- 【事实】遗留 SQLAlchemy 1.x `.query(` 非测试 9 处：`fastapi_app/shared/report_data_service.py:110/127/181/190/231/243/286/295`、`fastapi_app/services/base_search_service.py:89`。
- 【事实】`core/middleware.py:409-411` `body += chunk` 对 bytes 做 O(n²) 拼接（仅无 Content-Length 路径，low）。

### 3.9 前端
- 【事实】依赖 16 个：`primevue@^4.5.5`（15 处 import/12 文件）与 `reka-ui@^2.9.7`（16 处/14 文件）**并存**且都在用；图标只有 `@fortawesome/*` 一族（**不存在双图标包**，dist 里 `vendor-fa-icons` 145KB 与 `vendor-fontawesome` 77KB 是同一族按 `vite.config.ts:125/128` 拆的两个 chunk）；无 element-plus；`echarts@^6.0.0`。
- 【事实】`frontend-vite/dist/assets` 196 个文件合计 3.60MB，Top：vendor-primevue 672KB、vendor-echarts 557KB、index-*.js 443KB、vendor-fa-icons 145KB。
- 【事实】超 400 行组件 7 个：`views/product/components/BomEditor.vue` 571、`views/purchase/components/CompletedOrdersPanel.vue` 496、`views/backup/BackupView.vue` 465、`mobile/views/dashboard/DashboardMobile.vue` 455、`views/purchase-plan/components/ImportPanel.vue` 427、`mobile/views/login/MLoginView.vue` 409、`views/user/components/UserPermissionDialog.vue` 405。
- 【事实】守卫显式豁免面：`meta.navExempt` 出现在 `router/index.ts:26,71,92,97,99,102,106`，`navAccess.ts:89` `if (options.navExempt === true) return true` → **任何被标 `navExempt` 的路由绕过导航权限检查**，需定期核对这份清单。
- 【事实】`package.json` scripts 已有 `type-check / lint / test / check:routes / check:api / check:dto` 全套，CI 前端 job（`ci-cd.yml:225-246`）已跑 lint+vitest+build+对齐检查。

独立前端深审（本轮第 6 路，只读）补充事实：
- 【事实】**门禁临界**：`scripts/gate_baseline.json:7` 的 `vue_component_length: 7` 与实跑 `scripts/check_vue_component_length.py` 完全相等（恰好 7 个超 400 行，exit=1）→ 新增第 8 个巨型组件即被拦。.ts 侧真正的巨型是 `views/purchase/composables/useSummaryModal.ts` **1083 行**（含 HTML 字符串拼装 `:135/:234/:287`、直接建 `a` 标签导出的 `:304-310`、113 行的 `applyLossRate` `:738-850`）。
- 【事实】**前后端没有契约校验**：后端 373 条路由（ast，44 文件）vs 前端 api 层 109 个字面端点，而 `scripts/check-api-alignment.mjs` 只做前端自比对（`:54` 显式跳过含模板插值的动态 URL）；`scripts/check-pc-api-bypass.mjs:81` 只扫 `src/views`；`check:dto` **未接入 CI**。
- 【事实】`scripts/check-route-alignment.mjs:75-83` 是**永久橡皮图章**：sharedPc/sharedMobile 恒等于同一交集 ⇒ mismatched 恒空 ⇒ `:82` 的 `process.exit(1)` 不可达，该检查永不会失败。
- 【事实】`vite.config.ts:131` `'vendor-primevue': ['primevue']` 子串匹配把所有 primevue 模块并成一个 chunk，叠加 `main.ts:120-151` 在非移动端**无条件** `import('primevue/config')` ⇒ PC 每个页面（含登录页）都要下载这个 672KB 包（`docs/decisions/frontend-primevue-bundle.md` 记录了该决策）。`chunkSizeWarningLimit: 600`（`vite.config.ts:103`）已低于该 chunk 体积。
- 【事实】API 类型契约在 4 处被击穿：`api/request.ts:179/205/209/213` 统一 `as Promise<T>`，全仓无 `declare module 'axios'` ⇒ 双重断言 `as unknown as` **131 处（非测试 42 处）**；`: any` 仅 1 处、`as any` 0 处——"表面干净、逃逸集中"。
- 【事实】customer/supplier 是复制粘贴级同构：`views/customer/CustomerView.vue`(131) vs `views/supplier/SupplierView.vue`(148)、`composables/useCustomer.ts`(177) vs `useSupplier.ts`(189)、`CustomerTable.vue`(239) vs `SupplierTable.vue`(191) 的 `onPageChange`（各自 98-100 行）逐行相同。
- 【事实】虚拟滚动**三套并存**：`components/ui/VirtualList.vue`(8 消费者)、`composables/useVirtualScrollList.ts`(0)、`composables/useTableVirtualScroll.ts`(UiDataTable 使用)；死代码另有 `composables/useEventDelegation.ts:9`、`api/auxiliary.ts:30`（`api/index.ts:46` 再导出但零使用）与 `components/ui` 中 7 个零引用组件。
- 【事实】测试分布失衡：118 个前端测试文件，但 **11/27 域零测试**（approval、batch、case、customer、dashboard、login、notifications、ocr-import、permission、settings、user）；`vitest.config.ts` 配了 coverage 但 CI 未接线。
- 【事实】`stores/auth.ts:209-212` `hasPermission` 用 `permissions.includes` 线性扫描（16 处调用），而已维护的 `permissionSet`(`:53`) 只被 `hasAnyPermission`(`:214-217`) 使用 → 热点路径上 Set 白建。
- 【事实】`router/index.ts:113` `const useMobile = isMobileDevice()` 是**模块期一次性判定**，运行期不重算（切设备/旋转屏不切换分流）；12 条路径在 PC 与移动端各写一遍。
- 【事实】`vite.config.ts:143-144` dev server `host '0.0.0.0'` + `port 3000`，与 `package.json` 的 `dev --host 0.0.0.0 --port 5173` 冲突，且 3000 正是 nginx 生产端口（`start.py` 覆盖为 3000 有记录，但两处配置仍互相矛盾）。
- 【事实】PWA 两条字体 `runtimeCaching`（`vite.config.ts:52-68`）全仓无消费方（`fonts.googleapis`/`@font-face` 0 命中）= 死配置；生产 `drop` 全部 console（`vite.config.ts:32-34`），唯一上报 Sentry 在未配 `VITE_SENTRY_DSN` 时是 no-op（`main.ts:103`）→ 生产故障可能既无 console 也无上报。
- 【事实】`vitest`/`vite` 侧不可改 `vite.config.js`（AGENTS.md §5.5 + `fastapi_app/tests/test_qa_prod_stack_regression.py:448-465` 断言其与 `.ts` 一致），任何 chunk 策略变更必须改 `.ts` 后重跑 `vue-tsc -b` 重新生成。

### 3.10 工程流程
- 【事实】CI（`.github/workflows/ci-cd.yml`）共 4 个 job：`test`(:10)、`lint`(:144)、`frontend`(:197)、`build`(:264)，全部 `ubuntu-latest`；`test` 内含迁移校验(:63)、门控测试(:68)、prod_audit 自测(:97)、Bandit(:124)、依赖漏洞扫描(:128)、覆盖率阈值(:140)；`lint` 内含全树秘密扫描(:168)、quality_gate(:173)、ruff(:177)、scoped mypy(:179)、文件体积门禁(:182)。**无部署 job**——名为 CI/CD 实为 CI。
- 【事实】近 30 天 396 个提交、近 90 天 465 个（占 508 个历史提交的约 78%）→ 高速 AI 辅助产出的直接证据，也解释了"存量债永不偿还 + 文档漂移"。
- 【事实】round2 方案（`docs/optimization-plan-2026-10-01-round2.md`，132.4KB/1040 行）自 2026-10-01 起 **0 个提交**：批一/批二/批三一项未开工；22 项 OPT 中 9 项已落地、4 项进行中、9 项未开工。

---

## 4. 提升空间（按"收益/成本"排序，可直接排期）

### 批一：零设计决策，1–3 人日总量（建议本周内集中做）
1. **收紧 `.env` 与凭据**：移除 `Authenticated Users:(M)`/`BUILTIN\Users:(RX)` 继承，`_ops/credentials/` 移出工作区，轮换 `SECRET_KEY`/`DB_PASSWORD`/`REDIS_PASSWORD`/`METRICS_BEARER_TOKEN`（0.5 人日）。
2. **让备份重新真实**：启用 `ERP_Database_Backup` 计划任务（当前 Disabled）、`scripts/restore_drill.py:36` 改选 `*.zip.enc`、恢复 watchdog 与"季度演练"记录（1.5 人日）。
3. **给静默失败装仪表**：`core/database.py:228-240` 增加 `db_commit_failures_total` 计数并在关键实体上告警（0.5 人日，不改提交语义）。
4. **统一时钟**：`shared_models/approval.py:56/:61`、`:128/:130` 全部走 `_utcnow`；`services/stock_common.py:9-19` 改北京时间口径（0.5 人日）。
5. **补权限与限流口子**：`customer_sampling.py:63` 加 router 级 `dependencies`；`main.py:265` 限流键改用可信代理链或固定桶；`scripts/restart_backend.py:66`、`config/pgbouncer/pgbouncer.ini:15` 收口到回环（1 人日）。
6. **封门禁旁路**：删掉 `check_service_commit.py:32-39` 的 `independent[-_]transaction` 白名单，改为显式 `# tx-exempt: <理由>` 并纳入棘轮（0.5 人日）。
7. **机械校验白名单**：CI 增加"mypy files ⊆ 导入图"检查 + 删除 8 处死代码（约 1,100 行）（1 人日）。
8. **零碎卫生**：9 处 `.query(` 改 `select()`；`core/middleware.py:411` 改 `bytearray`（0.5 人日）。
9. **前端契约门禁（低成本高收益）**：新增“前端 api 层字面端点 ⊆ FastAPI openapi paths”的只读校验脚本并接入 CI；同时修掉 `scripts/check-route-alignment.mjs:75-83` 恒不失败的死逻辑、把 `check:dto` 接入 CI（1 人日）。

### 批二：小改造，约 8–12 人日
9. **参数化负库存策略**：把 3 处不变式收口为一个函数 + 一个配置（参考 Dolibarr `STOCK_DISALLOW_NEGATIVE_TRANSFER`、ERPNext `allow_negative_stock`）。
10. **库存对账（不改写路径）**：用现有 ARQ 做只读"流水↔余额"差异报告，先在无风险前提下暴露漂移。
11. **数据库兜底**：`shared_models/product.py:37` 加 `CHECK(current_stock >= 0)` 或用 `UPDATE … WHERE current_stock >= n` 原子扣减；`daily_production_record` 加 `(department, production_date, product_id)` 唯一约束。
12. **编号健壮化**：`numbering_sequence.py:34` upsert 改 `GREATEST(counter.last_seq, seed)+1`；`read_daily_max` 维护 (prefix,date) 水位。
13. **批量锁序**：`order_batch_create.py:326-327` 加 `ORDER BY Product.id` 并分批。
14. **抵扣完整性**：`order/deduction.py:204/:254` 校验 `remaining` 并返回实际生效量。
15. **ARQ 幂等**：任务入口加 `job_id + 业务主键` 幂等键；循环 commit 改分批。
16. **连接池接线**：接回 `pool_size/max_overflow/pool_recycle` 并出压测证据。
17. **内网 TLS + nginx `limit_req`**（OPT-17/18），并在 nginx 侧只信任自身回环来源。
18. **审计与软删除**：单据表补 `created_at/created_by/deleted_at`；`stock_return.stockout_id` 改 `RESTRICT` 或改软删 + 写审计。
19. **mypy 分批 ratchet**：先把 21 个零错模块零成本并入，再按模块分批啃 services/。
20. **前端首屏减重与类型钉死**：收敛 `vite.config.ts:131` 的 vendor-primevue 单包并把 `primevue/config` 延迟到首个 PrimeVue 组件挂载；用 axios 第二泛型替换 `api/request.ts:179/205/209/213` 的断言，消解 131 处双重断言（1–1.5 人日，须重生成 `vite.config.js` 并回归表格页）。
21. **消灭 customer/supplier 双份同构**：抽 `useCrudList<T>` + 配置化 `EntityTable`，约折叠 600 行（2–3 人日，两块均有测试兜底）。
22. **前端测试补口与死代码清理**：优先补 approval/user/settings 等零测试域；删 4 处死代码 + 7 个零引用 ui 组件 + 三套虚拟滚动收敛为一套；确认生产已配 `VITE_SENTRY_DSN`（1–2 人日）。
20. **前端首屏减重与类型钉死**：收敛 `vite.config.ts:131` 的 vendor-primevue 单包并把 `primevue/config` 延迟到首个 PrimeVue 组件挂载；用 axios 第二泛型替换 `api/request.ts:179/205/209/213` 的断言，消解 131 处双重断言（1–1.5 人日，须重生成 `vite.config.js` 并回归表格页）。
21. **消灭 customer/supplier 双份同构**：抽 `useCrudList<T>` + 配置化 `EntityTable`，约折叠 600 行（2–3 人日，两块均有测试兜底）。
22. **前端测试补口与死代码清理**：优先补 approval/user/settings 等零测试域；删 4 处死代码 + 7 个零引用 ui 组件 + 三套虚拟滚动收敛为一套；确认生产已配 `VITE_SENTRY_DSN`（1–2 人日）。

### 批三：结构性改造（需专门排期与评审）
23. **库存单一真相**：流水（SLE）为真相、余额降级为派生缓存、补 running_balance/成本列，先双写双校验再切读（借鉴 ERPNext）。
24. **拆分上帝对象**：`recovery_test_service.py`(1322) 按 prepare/execute/validate/cleanup 四阶段拆；`cleanup/service.py`(783)、`tasks/backup_tasks.py`(1008)、`endpoints/backup/validation.py`(857)、前端 `useSummaryModal.ts`(1083) 同批瘦身，业务逻辑下沉 services。
25. **状态与流程数据化**：`core/state_machine.py:29-40` 的 TRANSITIONS 移到配置/表，保留 fail-closed 语义。
26. **字段级审计**：`shared_models/audit_log.py:16` 的 detail 固化 old→new 契约（先只覆盖 Order/Product）。
27. **行级权限**：把 `core/production_scope.py:45` 的部门域模式推广到订单/客户 scope。
28. **模块边界数据化**：`api/v1/router.py:7-40` 的 34 条绝对导入改为"模块清单"（前缀/权限码/开关同处声明），支持灰度关闭。

---

## 5. 与开源 ERP 对标：可借鉴的 15 条与不建议的 5 条

对标对象（源码级取证）：Odoo 17.0、Frappe/ERPNext version-15、Frappe framework、Dolibarr、Tryton、metasfresh、OpenBoxes、Apache OFBiz、OCA 组织。

### 5.1 最值得抄的 Top 15（借鉴什么 → 为何适配 → 成本）
1. **SLE 只追加 + 余额降级为缓存 + 事后重算**（ERPNext：`set_as_cancel` 打标记、`update_bin_qty` 派生、`update_entries_after` 从改动点重算）→ 本项目 54 处就地改余额是最大结构性风险 → L。
2. **参数化负库存策略**（ERPNext `allow_negative_stock` / Dolibarr 常量）→ 把 3 处硬编码收口 → S。
3. **Repost 思路先做成只读对账**（ERPNext 分批 + `REPOST_SLE_BATCH_SIZE=500`）→ 已有 ARQ，零改写风险 → M。
4. **`ir.sequence` 可配置格式 + 周期子序列**（Odoo：standard=PG nextval / no_gap=FOR UPDATE NOWAIT，date_range 建子序列）→ 只把 prefix/padding/周期搬进配置表，保留现有 ON CONFLICT 原子性 → S/M。风险：`numbering_sequence.py:115` 的正则 `'^[A-Z]+-日期-数字$'` 会失效。
5. **状态与迁移数据化**（Frappe Workflow 把状态与迁移做成文档）→ 本项目只有审批一处状态机，数据化即可，不引入引擎 → S/M。
6. **字段级变更留痕**（Odoo `mail.tracking.value`）→ 在现有 `audit_log.detail` 里固化 old/new 契约，只覆盖关键字段 → S。
7. **影子历史表按表启用**（Tryton `_history`）→ 只为 order/product 启用，避免全库膨胀 → M。
8. **模块描述符内聚**（Dolibarr 模块内聚 numero/depends/const/rights）→ 把路由平铺换成模块清单，顺带得到功能开关 → S/M。已有 `npm run check:routes` 作为对齐护栏。
9. **显式覆盖层**（ERPNext `override_whitelisted_methods`）→ 二次开发集中在 overrides 文件，缩小评审面 → S。
10. **触发器 + 定时动作限定子集**（Odoo `base_automation` 的 on_time/on_state_set）→ 用现有 ARQ 定时任务加"配置化超时提醒/审批升级"，不做通用自动化 → M。
11. **幂等键推广**（本项目已有 `order_routes.py:113` 的 `X-Idempotency-Key` + `uq_po_pending_dedup`）→ 复制到备货/出货写接口 → M。
12. **API 契约校验进 CI**（AGENTS.md §4 的 `check:api`/`check:routes`）→ 成本最低、收益最高：前后端错配在提交时暴露 → S。
13. **迁移↔发布范围文档化**（Dolibarr 逐版本 SQL 脚本）→ 单 head 已具备，补"版本→迁移区间"清单即可支撑回滚决策 → S。
14. **部署就绪判据自动化**（OFBiz/metasfresh 可脚本化安装）→ 把 `logs/prod_runner.json` 扩展为启动前 preflight（DB/Redis/迁移 head/前端 dist）→ S。
15. **缓存失效精确化**（参照 ERPNext"最小重算范围"）→ `fifo_allocation.py:56` 已从 PATTERN 改精确键，可推广到 `cache_invalidation` 全部调用点 → S/M。风险：漏删比多删贵，需加陈旧值观测。

### 5.2 不建议借鉴
1. **整体迁移/重写到 Odoo/ERPNext/metasfresh**：本机即生产、无预发；99 个迁移 + 3689 个测试用例是既有资产，重写等于把库存风险放大成停摆。
2. **Odoo/Frappe 式隐式猴补丁扩展**（`make_create/make_write`、`override_doctype_class`）：控制流不可见，与显式依赖 + mypy/ruff/quality_gate 的工程约定冲突。
3. **完整工作流引擎 + 可视化流程设计器**：全仓真正的状态机只有审批一处，维护成本远超收益。
4. **微服务化 / Java 三层**（OFBiz、metasfresh）：Windows NSSM 单机 + 小团队 + 无预发，拆服务的运维复杂度无处消化。
5. **全库默认启用影子历史表**（Tryton）：99 个迁移规模下存储与维护负担过高，应按表启用。

---

## 6. 口径与核验边界（防止误引用）

- **路由数三口径并存**：装饰器 grep = 373（本次采用）、历史报告 385 / 382；三者统计口径不同，**禁止合成**。
- **测试文件/用例**：`pytest -q --collect-only` = 3689 用例（双树 `tests` + `fastapi_app/tests`，这是既有事实非配置错误）；"148&163" vs "110&161" 是不同统计口径。
- **`env_drift=0` 与「.env.production 92/94 键缺失」**并存不矛盾：门禁只覆盖已纳入检查的键。
- 本轮**未跑**：全量 pytest、压测、空库重放迁移、恢复演练；`idx_scan` 因数据量小不可信。
- 前端维度由 Lead 直接取证；运维/安全/可观测性维度先由 Lead 取证、后由第 5 路子代理独立复核并补强（其结论单列 §9，与前文冲突处以 §9 为准）。Lead 侧证据为 `package.json`/`vite.config.ts` 实读、`icacls` 实测、`Get-CimInstance Win32_Service`、`Get-NetTCPConnection`、`Get-ScheduledTask`、`Select-String` nginx 配置。
- 未取证领域（标【推断】）：Odoo 报表引擎、ERPNext Query Report、metasfresh 接口细节、OFBiz entity engine、多币/税/i18n。

## 7. 本轮对既有报告的修正（引用旧文档前必读）

| 既有说法 | 本轮实证 | 结论 |
|---|---|---|
| `core/database.py:229-232` "仅 logger.error，无抛出" | 实读 `:228-240`：logger.error → rollback → **raise** | 描述需改写：风险在"响应已发送 + 无指标"，不是"没抛" |
| `docs/...` "只读副本已写未用" | `daily_production.py:18` 导入 + 六处 `Depends(get_async_read_db)` | 已过期，实际已用 |
| "useApiMutation 仅 4 处" | 实测 30 处（定义 `composables/useApiMutation.ts:23`） | 已过期 |
| "`DeviceToken` 未导入" | `shared_models` 0 命中，类已不存在 | 无从核验 |
| "`mypy.ini:17-20` 记录 82 个文件" | 注释未随扩容更新 | 文档漂移 |
| "全仓无 SQLAlchemy 1.x 混用" | 非测试 9 处 `.query(` | 需改写为"残留 9 处" |
| "PrimeVue 与 Reka 双库、FontAwesome 与 fa-icons 双图标包并存（疑似重复依赖）" | 双 UI 库确实并存且都在用；图标只有 `@fortawesome` 一族（两个 chunk 是配置拆分） | 图标"重复依赖"说法**不成立** |
| `docs/TRANSACTION_BOUNDARY_GUIDE.md` §4 基线行号 | 实测已漂移（`incremental.py:397`、`restore.py:267`、`records.py:757/769/788`、`recovery_test_service.py:573`） | 文档需随代码更新 |
| "备份加密会静默降级" | `_deps.py:150-170` 有明确设计与 docstring（`fail-safe：宁可明文可还原`） | 应改写为"有意降级 + 缺显式告警"，而非"意外漏加密" |
| 本轮（自纠）"限流键伪造不成立" | 我曾据 slowapi `get_remote_address` 只读 `request.client.host` 判其不成立 | **结论成立**：`prod_runner.py:267-268` 的 `--forwarded-allow-ips=*` 让 uvicorn 用 XFF 最左值**重写**了 `request.client.host`（见 §9 第 1 条） |
| 本轮（自纠）"连接池未接线" | 我曾判 `pool_size/max_overflow` 未接线 | **部分成立**：`database.py:25-53` 已接线；真问题是 `.env` 三个池键为死键、且缺 `pool_recycle`（见 §9 第 10 条） |

---

## 8. 建议的下一步

1. **先做批一（8 项，1–3 人日）**：全部零设计决策、全部可回滚，且覆盖本轮 Top 风险的 6 项。
2. **建执行台账** `docs/optimization-status-2026-10-01.md`：项号 | 标题 | 状态 | 证据 `文件:行` | 核验日期 | 责任人 | 下一动作（0.5 人日）。这是 round2 方案"漂移"的直接解药。
3. **把"门禁抓错对象"改成"门禁抓重灾区"**：mypy 按模块分批纳入 services/；文件体积门禁对存量给偿还期限而非永久豁免。
4. **批三的库存单一真相单独立项**：先只读对账，拿到真实差异数据后再决定是否改写入路径。
5. **前端门禁先补“真检查”**：当前 `check:routes`/`check:api` 都有橡皮图章或覆盖盲区（见 §3.9），应在批一里换成能失败的真校验，否则“对齐检查通过”是假信号。
6. **运维面按 §9 的三条 high 先行**：代理信任链一行修复 → 告警出口 → 演练产物新鲜度门禁；DR 的 blocker（备份包不完整 + 无异地副本）须单独立项。

---

## 9. 第 5 路（运维/安全/可观测性/供应链）补充取证（2026-10-01 增补）

> 本节为第 5 路子代理回报后的追加核验：凡与前文冲突处**以本节为准**；同时修正了本轮初稿中我自己的两处误判（见 §7 修正表末两行）。

1. 【事实】**限流键可伪造成立**：`core/prod_runner.py:267-268` 传 `--proxy-headers --forwarded-allow-ips=*`；`.venv/Lib/site-packages/uvicorn/middleware/proxy_headers.py:163-164` 在 `always_trust` 下返回 XFF **最左值**并覆盖 `request.client.host`；`config/nginx-windows.conf:60` 用 `$proxy_add_x_forwarded_for`（客户端自带头保留在最左）⇒ `main.py:256-271` 未登录路径的 IP 桶可换值绕过。审计 IP 取最右值（`audit_middleware.py:134-138`/`:202-205`）**不可伪造**。**high**；修复=把 `*` 改为 `127.0.0.1`（uvicorn 从右往左取第一个不可信地址，即 nginx 追加的真实客户端）。
2. 【事实】**主动告警通道为零**：`.env` 无 `SENTRY_DSN`、`OTEL_ENABLED=false`、`BACKUP_ALERT_EMAIL_ENABLED=false`、`BACKUP_ALERT_WEBHOOK_ENABLED=false` 且 URL 空；9090/3001/3100/8888/4317 均未监听；watchdog 计划任务未注册（`scripts/ops/watchdog.py`、`install_watchdog_task.ps1` 都在仓库里）；`config/prometheus.yml` targets 全是 docker 服务名；`config/alertmanager.yml` 出口被注释。**high**
3. 【事实】**备份在跑，断的是演练与告警**：调度来自 erp-arq 的 ARQ cron（`BACKUP_FULL_CRON=0 2 * * *`、`BACKUP_INCREMENTAL_CRON=0 */1 * * *`），产物 `erp_auto_daily_20261001_020013.zip.enc`（4.5MB）+`.meta`；Windows 计划任务 `\ERPSystem`、`\ERP_Database_Backup` **均 Disabled（死任务，不要以其状态判断备份健康）**；`backups/server/recovery_tests` 仅 1 份（2026-08-23）、`cleanup_reports` 停 2026-08-20，与 `BACKUP_RECOVERY_TEST_FREQUENCY=7` 不符 ⇒ 演练断档 39 天。**high**
4. 【事实】**DR 无法闭环（blocker）**：备份包白名单 `fastapi_app/services/backup/_constants.py:89-104` 缺**生效的** `nginx-windows.conf`、`security-headers.conf`、`redis-broker.conf` 与 NSSM 定义；`BACKUP_DIR=backups/server` 与生产同机同盘、无异地副本 ⇒ 主机/磁盘故障同时丢生产与备份。
5. 【事实】`scripts/restore_drill.py:35-39` 只 glob `erp_backup_*.zip`，对当前 `*.zip.enc` 生产格式必然 SystemExit（应用内演练 `backup/recovery_test_service.py:245-248/:330-337` 已 enc 感知，两条链路口径不一致）。
6. 【事实】保留策略双来源：`services/backup/records.py:563-640` 硬编码 30 天/50 份 vs `policy_service.py:49-52`、`cleanup/service.py:60-63` 读 env 30 天/100 份；`.zip.enc.meta` 不在清理匹配内 ⇒ 删 `.enc` 后 `.meta` 永久残留。增量包 mtime 比文件名时间戳晚约 8 小时（疑 UTC 命名 vs 本地时间，待人工确认）。
7. 【事实】**PostgreSQL 暴露面应下调**：`listen_addresses=*` + 0.0.0.0:5432 确在监听，但 `pg_hba.conf` 非注释行仅 `local`/`127.0.0.1`/`::1` scram-sha-256 与 replication ⇒ 局域网无认证路径，**不构成未授权访问**；Windows 防火墙三 profile 全关因此风险为 low（纵深仍缺失）。
8. 【事实】上传校验不统一：只有备份恢复有魔数（`fastapi_app/api/v1/backup/restore.py:115-117`），`production_plan.py:245`、`production_summary.py:304`、`auth.py:516`、`ocr_import.py:67/:109/:156`、`backup/validation.py:56` 仅按后缀判定；`core/middleware.py:392-417` 无 `Content-Length` 时逐块累积 ⇒ chunked 512MB 上传内存放大。
9. 【本项已在 P0 执行期更正，原判断部分不成立】原文称「`itsdangerous 2.2.0` 已装但无声明、`core/middleware.py:254` 的 `except ImportError` 依赖它 ⇒ 静默降级」——**取证后前提不成立**：全仓 `fastapi_app/**` **0 处** `itsdangerous` import（只有注释与日志文本）；`core/middleware.py:146` 的 `try:` 内只有 `:147 import ipaddress`、`:148 import secrets`；CSRF token 由 `:262` 的 `secrets.token_urlsafe(32)` 生成 ⇒ `:296 except ImportError` 是**不可达死分支**（连带 `:45 CSRF_DEGRADED_ITSDANGEROUS` 与 `:206-219` 的 503 fail-closed 块）。P0 批的处置因此改为「删除死分支 + 撤回声明」，而非「加声明 + 转生产拒绝启动」。真实成立的部分只有两条：① `.venv`（OPT-08 切换后的生产解释器）缺 `itsdangerous`/`aiosqlite` 等包而全局 `Python313` 有 ⇒ 此前「已装」只在全局解释器成立；② `mypy.ini` 注释记录的两个真实缺陷——`services/ocr/_extractors.py` 的 `global _pdf_extracter` 未声明（首次调用必 NameError ⇒ OCR 不可用）、`batch_import_dedup.py` 的 `Container` 未导入。**high（功能级）**
10. 【事实】`.env` 的 `DB_POOL_SIZE`/`DB_MAX_OVERFLOW`/`DB_POOL_RECYCLE` 是死键（`core/database.py:25-53` 由 `UVICORN_WORKERS`×`DB_MAX_CONNECTIONS` 计算，实测 pool_size=5/max_overflow=3）；缺 `pool_recycle`。
11. 【事实】门禁脆弱点：`scripts/quality_gate.py:122-123` 用正则抠子脚本 stdout 的违规数（改输出即静默失效）；本机未装 pre-commit；CI ruff 仅覆盖 `.github/workflows/ci-cd.yml:176-177` 所列范围（`server_manager/`、`scripts/` 不进 lint）；`pip-audit` 无 `--ignore-vuln` 白名单。前端 `prepare=husky` 在本机空转（无 `.husky/`），`core.hooksPath` 已是 `.githooks`（两套钩子机制并存）。
12. 【事实】其他运维细节：生效 nginx 6 处 include 硬编码 `D:/erp_system/config/security-headers.conf`（`:44/:89/:98/:106/:175/:181`，换机即失效）；明文 HTTP（`nginx-windows.conf:37-38`）下 HSTS 不生效；`prod_runner.py:556` 的 `started_at` 每次写盘刷新 ⇒ 无法算 uptime；`core/logger.py:19-83` 无脱敏 processor；`config/log_policy.json`（7 天/300MB）与 `logger.py` backupCount=14 两套保留策略；`quality_gate.py:8` docstring 仍写旧基线数（11/14）。
13. 【亮点，避免误伤】生产强校验到位（`core/config.py:394-430`/`:218-228`：SECRET_KEY<32、ALLOWED_HOSTS 空或 `*`、RS256 缺钥、CORS 含 null、加密口令为空 → 拒绝启动）；生产关闭 docs/redoc/openapi（`config.py:297-299`）；`/metrics` 未配 token 返回 503 fail-closed（`core/health.py:200-214`）+ nginx `allow 127.0.0.1/::1`、`deny all`（`nginx-windows.conf:139-145`）；`git ls-files` 无 `.env*`/`_ops/`/`config/jwt/*.pem`（但 `_ops/credentials/_backup_encryption_password.txt`、`_metrics_bearer_token.txt` **明文落盘**）；CSRF 生产不豁免内网且用 `secrets.compare_digest`（`middleware.py:178-231`）；prod_runner 监督语义保守正确（`:244-255` 三条件齐备才重启、`:585-591` 原子写 status）；`/api/health` 匿名只暴露 `{status, app, backup}`（`core/health.py:82-162`）。

### 9.1 上线前必须做（据本节结论）

① 按频率真跑恢复演练并落产物；② 至少接入一个告警出口（注册 watchdog 任务 + webhook/邮件）；③ 备份包补齐 `nginx-windows.conf`/`security-headers.conf`/`redis-broker.conf`/NSSM 定义；④ 建立异机或离线副本；⑤ 修正代理信任链（`--forwarded-allow-ips=*` → `127.0.0.1`）；⑥ 顺带：补 `itsdangerous` 声明、修 OCR 的 `NameError`、加固门禁本体（详见 `docs/optimization-plan-2026-10-01-round3.md` 的 P0-2/P0-6/P0-9～P0-12）。

### 9.2 第 5 路之后的三条新发现（2026-10-01 复核 `docs/optimization-plan-2026-10-01-round2.md` 时实测）

核查 round2 方案的 71 条断言时，得到三条既不在 round2、也不在本报告前文的新结论；详细取证与全量判定见 `docs/round2-claim-verification-2026-10-01.md`。

**N1｜JWT payload 缓存短路不是漏洞（反驳 round2 OPT-R2-35）。** 链路属实：`fastapi_app/core/deps.py:126`（Bearer）/ `:147`（Cookie）写 `request.state._jwt_payload`，`:195-199` 命中即 `return`，早于 `:214 is_token_revoked` 与 `:217 _verify_user_active`。但它**触发不了绕过**：`request.state` 每请求新建；唯一可能提前写缓存的 `fastapi_app/main.py:292 app.add_middleware(SlowAPIMiddleware)` 会对已装饰路由主动豁免（`.venv/Lib/site-packages/slowapi/middleware.py:110-111`），且装饰器包装层在依赖解析**之后**才调 key_func（`slowapi/extension.py:720-734`）；探针实测请求顺序恒为 `dep → check(middleware=False) → key_func`。**真正该改的是**：`core/deps.py:176 _USER_ACTIVE_CACHE = _TTLCache(ttl=10)`（禁用用户最长 10s 仍放行）与 `:71 _PERMISSION_CACHE = _TTLCache(ttl=5)`（权限回收最长 5s 滞后）；另建议 `:195` 早退加 `and not fail_closed`，否则 `get_current_user_id_strict` 的 fail-closed 语义在"同请求内先跑过一次非严格依赖"时会被静默抹掉。

**N2｜`limiter.key_func` 覆盖对已装饰路由无效，限流键必然是 IP。** `fastapi_app/main.py:271 limiter.key_func = _rate_limit_key`（`:269-270` 注释宣称"覆盖后所有端点立即生效"）实际无效：slowapi 在**装饰时**绑定键（`slowapi/extension.py:663 keyfunc = key_func or self._key_func`），而 5 处 `@limiter.limit` 在模块导入时执行，早于 `main.py:271`。探针实测：装饰后再改 `lim.key_func`，实际仍用旧键（输出 `decorated route keys used -> ['BEFORE(ip)']`）。受影响端点：`api/v1/endpoints/auth.py:217`、`monitoring.py:206`、`daily_production.py:328`、`report.py:154`、`stock.py:349`；`core/limiter.py:7-8` docstring 的"线上 key_func 已按 user_id 限流"不成立。叠加 §9 第 1 条的 `core/prod_runner.py:267-268 --proxy-headers --forwarded-allow-ips=*`（uvicorn 用 XFF 最左值覆盖 `request.client.host`）⇒ **限流键可被伪造**，且与用户身份无关。修复：装饰处显式传 `key_func`，并把 `--forwarded-allow-ips` 收紧到 `127.0.0.1`。

**N3｜`SlowAPIMiddleware` 在当前配置下整体空转。** `main.py:292` 虽注册了中间件，但装饰路由被豁免（`slowapi/middleware.py:110-111`），未装饰路由又只能靠 application/default limits，而 `core/limiter.py:45` 从 `RATE_LIMIT_DEFAULT` 取值、`.env`（204 行）无该键 ⇒ `default_limits=[]`。探针显示中间件层一次检查都没发生。**结论：限流只有"端点内装饰器"一条路径，没有中间件兜底**；把它当安全网会误判。二选一：配置 `RATE_LIMIT_DEFAULT` 让中间件真正生效（观察期），或删除该中间件以免误导。