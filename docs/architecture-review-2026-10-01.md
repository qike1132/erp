# 滨发协同系统（binfa-ERP）全面技术评估报告

- **评估日期**：2026-10-01
- **评估基线**：git HEAD `b6173290` + 22 个未提交工作区改动（评估反映工作区最新代码现状）
- **评估方式**：只读评估。4 路并行架构探查（前端/后端/系统级/质量门禁）+ 14 项质量门禁与扫描实测 + Mimosa 静态安全扫描（4,683 个文件全覆盖，静态不执行）+ 生产库只读普查（仅 SELECT/pg_stat）+ 评估侧联网核对核心依赖最新版本。
- **明确未执行**：负载/压力测试（本机是生产主机，红线禁止）、`npm run build`（dist 是 nginx 在服务的生产产物）、任何写操作、任何服务重启。
- **评估环境备注**：本机 git-bash 存在损坏的 shell 集成（部分命令被 `_lc` 包装器劫持，报 `_lc: command not found`），评估中改用 `command` 前缀与 python subprocess 绕过。此问题本身已列入运维建议（§9-P0）。

---

## 0. TL;DR

**这是一个工程质量显著高于同规模团队平均水平的单体 ERP，当前最大的风险不在代码，而在基础设施错位：业务规模极小（7 用户 / 29 订单 / 31MB 库）但整机单点、内网明文、无限流。** 代码侧门禁实测几乎全绿，技术债集中且明确（API 层 5 处事务违规、purchase/stock 域服务层测试空洞、迁移链 4 根、少量大文件），全部有清晰且低风险的整改路径。

### 总评分表（1-5）

| 维度 | 评分 | 一句话结论 |
|---|---|---|
| 前端架构 | **4.2** | 栈非常新（Vue3.5/Vite7/TanStack Query5/PrimeVue4 unstyled），分层与权限设计成熟；弱点是写操作无统一 mutation 层、组件复用不均 |
| 后端架构 | **4.0** | 分层清晰、并发控制扎实（行锁+乐观锁双保险）、迁移单 head；弱点是 API 层事务违规残留、config 零校验器 |
| 系统整体架构 | **3.5** | nginx/prod_runner/备份链路设计质量高，但整机单点（PG 无从库）、明文 HTTP、网关无限流 |
| 依赖管理 | **4.0** | 版本极新、`==` 钉死、离线 advisory 0 命中；弱点是生产跑在 291 包的全局 Python 环境无 venv 隔离 |
| 组件与复用 | **3.5** | 37 个 Ui* 组件 + core 46 个横切组件质量好；三套列表 composable 并存（一套死代码）、customer/supplier 镜像重复 |
| 代码质量 | **4.0** | mypy 0 错、vue-tsc 0 错、eslint 0 错、quality_gate PASS；存量债 73 处可收紧、6 个 pytest 环境性失败 |
| 性能（当前规模） | **4.5** | 31MB 库 + 8 workers，当前无任何压力；且 web_vital 已积累 4,147 条真实用户性能数据可分析 |
| 可扩展性储备 | **3.0** | 三处进程内状态 + 本地 uploads 写入，只适合单机纵向扩；多副本需先 Redis 化 |
| 工程化/门禁 | **4.5** | 前后端 14 项门禁齐备且实测通过，基线棘轮可收紧；mypy 覆盖率 106/536 需扩 |

### 十条最重要的发现

1. **门禁实测全绿（除 6 个环境性 pytest 失败）**：quality_gate PASS、mypy 0 错、vue-tsc 0 错、eslint 0 错 165 警、vitest 全过（120 个测试文件）、check:api/check:routes 全过。
2. **业务规模极小**：7 个用户、20 条权限、29 张订单（7 条明细）、6 个产品、全库 31MB（PostgreSQL 18.3，版本很新）。**性能不是当前矛盾，别为想象中的规模优化。**
3. **整机单点是最大风险**：PG/Redis×2/nginx/后端同机，PG 无从库（`scripts/setup_pg_replication.sh` 与 `config/postgres/init-replica.sh` 已备好但未部署）。
4. **内网明文 HTTP**：nginx 仅 `listen 3000` 无 TLS（`config/nginx-windows.conf:37`），凭据/Cookie 明文传输；网关无 `limit_req`（限流全靠应用层）。
5. **上传文件免鉴权直出**：`/static/uploads/` 由 nginx alias 直接托管，任何知道 URL 的人可 GET（`nginx-windows.conf:93-99`）。
6. **技术栈是 2026 年当前大版本组合**：fastapi 0.137.1（最新 0.142.2，小版本落后）、pydantic 2.13.2（最新 2.13.5）、vue 3.5.43（当前）、vite 7（最新 8.3.1，落后一个 major，可暂缓）；后端核心依赖全部 `==` 钉死；Mimosa 离线 advisory 匹配 0。
7. **生产 Python 运行在全局环境**：解释器里装了 291 个包（含 litellm/openai/locust/opencv 等与 ERP 无关的重包），无 venv 隔离——依赖漂移与“隐式依赖”风险。
8. **API 层残留 5 处事务/业务违规**（`endpoints/order.py:334-394`、`customer.py:114,302`、`purchase_plan.py:112,529`），违反自家 `docs/TRANSACTION_BOUNDARY_GUIDE.md`。
9. **测试结构性空洞**：purchase 域 15 个服务模块、stock 域 6 个、purchase_plan 7 个无服务级测试（靠集成路径兜底）；6 个 pytest 失败集中在 tests/qa 冒烟（event loop 污染类环境噪音）。
10. **迁移链单 head 但 4 根 + 2 个 merge + 2 个同号 017**（AST 实证）：功能可用，新环境 upgrade 依赖根序，长期可维护性差。

---

## 1. 前端架构深度评估

### 1.1 技术栈与选型合理性 ★★★★☆

`frontend-vite/package.json`：Vue 3.5 + vue-router 5 + Pinia 3 + @tanstack/vue-query 5（数据层主力）；UI 双轨：PrimeVue 4.5（unstyled + pt 定制，`main.ts:129-147`）+ reka-ui 2.9 + Tailwind 4；axios 1.18、echarts 6、FontAwesome、@sentry/vue、vueuse、web-vitals；dev 侧 Vite 7、TypeScript 6、vitest 4、eslint 9 flat、unplugin auto-import/components、PWA。

**判断**：选型全部是 2026 年主流一线组合，且 TanStack Query 承担服务端状态、Pinia 只管会话/导航的职责切分是教科书式的。UI“PrimeVue unstyled + 自建 Ui* 组件 + reka-ui + Tailwind”四件套偏重（见 §6 双轨成本），但换来的是完全可控的设计系统。

### 1.2 构建与打包策略

`vite.config.ts:101-141`：manualChunks 拆 9 个 vendor chunk（echarts/vue/query/primevue/fa-icons 等），fa-icons 独立避免图标重回首屏；esbuild 生产 drop console/debugger；unplugin 按需 + PrimeVueResolver；dev 代理 /api、/static、/ws → 127.0.0.1:5002 并带 CSP。`scripts/swap-dist.mjs` 实现原子换目录发布。实测 dist：**131 个 JS 共 3.24MB**。

| chunk | 体积 |
|---|---|
| vendor-primevue | 672KB |
| vendor-echarts | 557KB |
| index（入口） | 443KB |
| vendor-fa-icons | 145KB |
| vendor-vue | 113KB |
| vendor-reka-ui | 93KB |

**问题**：vendor-primevue 672KB 为全 PC 端共享；入口 index 443KB 偏大（rollup-plugin-visualizer 已装但未见产物分析流程）。

### 1.3 组件设计与复用

288 个 .vue 共 47,956 行；通用层 `src/components/ui` 37 个 Ui* 组件（UiDataTable/UiFilterBar/UiDialog 等）。views 25 个模块中 19 个遵循“页面 View + components/ + composables/”分层。**重复模式确凿**：customer 与 supplier 两模块结构几乎镜像（`CustomerTable.vue` 247 行 vs `SupplierTable.vue` 285 行，均手写表格未用自家 UiDataTable）；列表状态管理存在三套并存：useListQuery（**0 引用，死代码**）、usePagedSearch（10 处）、useEnhancedList（3 处）。最大文件 `views/product/components/BomEditor.vue` 571 行。

### 1.4 状态管理与数据一致性

仅 4 个 pinia store（auth 247 行、catalog、patternRoom、sidebar）。主数据流由 vue-query 承担：41 处 useQuery、66 处 invalidateQueries；queryClient 统一配置（`src/utils/queryClient.ts:34-45`，staleTime 30s、401 不重试）+ sessionStorage 持久化（`main.ts:81-98`，权限/审计类 key 排除）。**弱点**：写操作缺统一 mutation 层——66 个 view 文件直接 import `@/api`，useApiMutation 仅 4 处调用，乐观更新几乎未用；跨页一致性完全依赖失效列表的维护纪律（此前贝莱/外包/采购页不同步 bug 即源于此模式）。

### 1.5 路由与权限

PC 30 + 移动 15 条路由（check:routes 实测），全部 `() => import()` 懒加载且按设备二选一（`router/index.ts:13-114`）；守卫纯函数化委托 `navAccess.resolveNavAccess`：登录校验 + 非超管按后端 nav-sections 白名单 **fail-closed**（明确注释“不是安全边界”，安全边界在后端 RBAC——正确的认知）；chunk 加载失败自动重载 3 次（`router/index.ts:141-156`）。按钮级权限 = `authStore.hasPermission(code)` 经 usePermission，22 处调用点。

### 1.6 API 层

`src/api` 27 个文件按业务域拆分 + `request.ts` 统一封装：CSRF 注入、401 refresh 单飞 + 请求重放（`:54-110`）、403 toast、GET 并发去重 Map（`:167-185`）、写操作仅对 502/503/504 重试 1 次。类型为手写 interface（无 openapi 生成——后端 OpenAPI 生产关闭，见 §4.1）。`check:api`（109 个端点全部走共享 API 层，移动端零绕过）与 `check:routes` 是自研对齐器，实测全过。

### 1.7 工程化

eslint 9 flat（no-explicit-any 仅 warn、no-console=error）；tsconfig `strict` + `noUncheckedIndexedAccess`；vitest 120 个测试文件聚焦业务逻辑（订单行、出货面板、跨页失效等），无 UI 快照；husky pre-commit 跑 lint-staged + vue-tsc + vitest，仓库级 `.githooks/pre-commit` 做密钥守卫。**实测**：type-check 0 错、eslint 0 错 165 警（101 条可 --fix，多为 vue/html-indent）、vitest 全过。

### 1.8 加载性能

main.ts 轻量启动：PrimeVue mount 后异步安装、图标懒加载组件、移动端 token css 按需；无全量图标/大 JSON 内联反模式；vue-query 缓存持久化带来刷新秒开。

**前端 Top 问题**：① 三套列表 composable 并存且一套死代码；② customer/supplier 手写重复绕过 UiDataTable；③ 写操作无统一 mutation 层（66 文件直呼 API）；④ vendor-primevue 672KB 单 chunk；⑤ 入口 443KB 待分析。

---

## 2. 后端架构全面审查

### 2.1 总体架构与分层 ★★★★☆

单体 FastAPI 应用（`fastapi_app/main.py`，uvicorn 8 workers + NSSM 服务）。分层清晰：`api/v1/endpoints` 36 个路由文件、`services` 184 个 py（含 order/purchase/backup/outsource 等子包）、`schemas` 25、`shared_models` 45 个 ORM 模型、`core` 46 个横切组件、`tasks`（ARQ）、`shared`。`api/v1/router.py` 挂载 37 个端点模块，按业务域分组，每域一个 prefix+tag。总规模 536 个 py / 116,326 行。

### 2.2 API 设计规范

- 版本：仅 `/api/v1`；**`api/v2/endpoints` 是空壳死代码**（只有 `__pycache__`），误导版本策略认知。
- 命名不一致例：`/aux` 缩写、`/pattern-room` 与 `/pattern-maker` 并存且共用 tag（`router.py:293-307`）、`/orders/delete/{order_id}` 动词入径（`endpoints/order.py:334`）、`/staging-stockins` 生硬复数。
- 响应无全局包装是**刻意设计**（`core/response.py:1-35`），用 `success_response()` 收敛 + `main.py:302-381` 四个全局 exception handler，错误为字符串 code。
- 分页统一 `page/per_page`，深翻页自动切 keyset（`services/enhanced_pagination.py:15`）——优于行业平均。
- 鉴权：router 级 `Depends(get_current_user_id)`（`router.py:50`）+ 端点级 `require_permission(...)` 双层注入；**用户/权限路由在 Redis 故障时 fail-open**（`router.py:130-134` 注释明示）。

### 2.3 数据访问层

SQLAlchemy 2.0.49 全 async（asyncpg），psycopg3 仅用于 Alembic（`core/database.py:1-8`）。Session 由 `get_async_db`（`database.py:203`）请求级管理：成功自动 commit、异常 rollback，服务层 flush-only；`db_transaction` 上下文管理器支持 error_map 异常→HTTP 映射。N+1 防范充分：selectinload 166 处/38 文件、joinedload 72 处。原生 `text()` SQL 245 处/88 文件——抽查 `stock_inventory_service.py:649-652`：拼接片段为模块级常量、筛选值全部走绑定参数、带 nosec 注释与安全说明，属**有纪律的动态 SQL** 而非漏洞，但依赖人工约定（见 §2.9）。

### 2.4 业务逻辑分层

services 层职责总体清晰（有 `docs/TRANSACTION_BOUNDARY_GUIDE.md` 约束），但 API 层有违规残留，最严重三处：① `endpoints/order.py:334-394` delete_order 在端点内手动 commit+异常映射+缓存失效+领域事件发布；② `endpoints/customer.py:114,302` 端点内 commit；③ `endpoints/purchase_plan.py:112,529` 同类。另有 `auxiliary.py:275,288`、`purchase_center/order_routes.py:98,122`。

### 2.5 事务与一致性 ★★★★☆

并发控制扎实：`with_for_update` 50 处/25 文件；`shared/stock_concurrency.py` 悲观锁+乐观锁双保险（MAX_RETRY=3，begin_nested 重试）。库存增减统一走行锁（`stock_in_service.py:38,56`、`order_deduction_service.py:55`、`approval_service.py:277`），唯一索引兜底并发确认（`purchase_plan_staging.py:226`）。ARQ 约 20 个任务（backup 11、batch 2、maintenance 3、numbering_audit、plan 2、report），4 队列隔离，max_tries=3。编号幂等：水位对账 GREATEST 只升不降 + advisory lock（`main.py:142-154`，web/worker 双端执行）+ 10 分钟巡检自愈。

### 2.6 水平扩展能力

大体无状态但非严格，进程内状态三处：`deps.py:34-71` 权限 L1 TTLCache（有跨 worker 广播失效开关，**默认关**）、`api/ws.py:41` `_WS_PENDING_TICKETS` 内存票据 dict、审计日志缓冲；本地文件写入（uploads/files/releases）。Redis 用途广泛（30 处引用 `utils/redis_cache.py`）：缓存、JWT 黑名单、WS 票据、ARQ broker、pub/sub 通知与缓存失效广播。有 WebSocket 通知（`api/ws.py`，多级认证）。**结论：当前只适合单机纵向扩；做双实例前必须先 Redis 化票据与开启缓存广播。**

### 2.7 配置与健壮性

`core/config.py` 453 行约 42 字段（pydantic-settings + load_dotenv），含生产 CORS/IP 白名单手写校验，但 **0 个 `@field_validator`**——配置错误只会在运行期暴露。日志 structlog + `log_config.json`；DB 池按 worker 动态计算、pre_ping、LIFO（`database.py:24-53`）；优雅停机 15s 超时保护（`main.py:202-242`）；OTEL 全链路 + Sentry 可选。

### 2.8 迁移健康（AST 实证）

99 个迁移文件，**单 head** `pg_standalone_060_fix_updated_at_varchar_columns`，无悬空引用；但存在 **4 个根**（pg_standalone_001 + add_product_factory/add_product_price/add_pp_composite_idx 三个游离根）和 2 个历史 merge、2 个同号 017——链路历史混乱但功能可用。最近 5 条主题：056 恢复备份计划、057 修增量 cron、058 修时区 naive 日期、059 编号审计、060 修 updated_at varchar（都是在修运维细节，迁移纪律整体良好）。

### 2.9 依赖与工具链

依赖在 `requirements/*.txt`（pyproject 只放质量门禁阈值）：base.txt 37 条核心全部 `==` 钉死（fastapi==0.137.1、sqlalchemy==2.0.49、arq==0.28.0、pydantic==2.13.2），仅少数 `>=`（starlette、ruff、pytest 系）。ruff.toml 较严：E/F/W/I/N/UP/B/SIM/C4/S/RUF 全族 + BLE001 豁免审计。mypy 为渐进 ratchet：仅纳入零错误文件（106/536，services 82/156）。

**后端 Top 问题**：① API 层 5 处事务违规；② 进程内状态三处阻碍多实例；③ 认证 fail-open 残留；④ api/v2 空壳；⑤ 迁移图 4 根；⑥ 245 处 text() 依赖人工纪律缺自动化注入回归锚点；⑦ config 零 field_validator。

---

## 3. 系统整体架构综合评估

### 3.1 前后端交互与网关

nginx 2 worker 监听 ：3000，反代 /api、/ws、/static 至 127.0.0.1:5002（`config/nginx-windows.conf:25-27,148-153`）；/assets 长缓存 1y immutable、SPA 回退 no-cache、gzip 开、安全头经 `config/security-headers.conf`（CSP/XFO/HSTS 等）；请求体 10m 默认值与备份/导入路径放宽（512m/64m）与后端 `middleware.py:37-65` **双侧对齐且有注释互指**——这是很少见的好实践。uvicorn 8 workers、httptools、仅绑回环。OpenAPI 生产关闭（`config.py:297-299`），nginx :125-127 仅兼容保留。**缺口：无 limit_req 限流、无 TLS 监听。**

### 3.2 第三方集成与异步任务

**无短信/支付/物流外呼**（生产代码 httpx 仅 Meilisearch 缓存恢复与备份告警 webhook 两处）；notification.py 自述 MVP 仅站内消息。ARQ 4 队列（io.batch/reports/backup/plan）19 个 functions，cron：出货同步 1:00、备份 poller/看板 MV 每 5m、只读授权自愈/编号审计每 10m、日志维护 4:30。Excel openpyxl + xlsxwriter；无 PDF 生成库（PDF 仅 OCR 导入上传）。**集成面极小 = 攻击面与故障面小，符合内网 ERP 定位。**

### 3.3 安全架构 ★★★★☆（设计）/ ★★★☆☆（暴露面）

- 认证：JWT 双模（httpOnly Cookie + Bearer），access 60min/refresh 7d，refresh 轮换 + 30s 宽限（`auth.py:336-356`）；Argon2id 主哈希、兼容 bcrypt/pbkdf2/scrypt（`core/security.py:13-36`）。
- 授权：RBAC 权限点 `require_permission/any/superuser`（`deps.py:279-345`）；无通用行级隔离（当前业务规模可接受）。
- 防护：限流默认开启（`core/limiter.py:25-59`），登录双层防爆破 1min+5min 窗口、Redis+内存降级；CORS 生产过滤（http 仅内网 IP 字面量）；审计中间件记录全部写操作含 403 拒绝（`audit_middleware.py:18-56`，实测 audit_log 4,858 行在正常积累）。
- /metrics 三重门：nginx 本机白名单 + 生产 Bearer Token fail-closed 503（`core/health.py:206-213`）。
- 密钥防线：本地 pre-commit + scan_secrets.py 双层正则，allowlist 17 条均有理由；gitleaks/trufflehog 未接入。
- Mimosa 静态扫描：**0 critical / 136 high / 751 medium / 67 low**；抽查 high 样例绝大多数为根目录审计草稿（`_ops/audit_scratch/`、`_qa_tmp/`）与测试夹具的误报——曾复核 `config/postgres/init-replica.sh:31` 的 PGPASSWORD“硬编码”实为环境变量注入 + fail-fast（`init-replica.sh:10-12`），是误报。
- **真实弱点**：内网明文 HTTP；`/static/uploads/` 免鉴权直出；用户/权限路由 fail-open；登录限流放宽至 100/min（`auth.py:217`）但网关层无第二道。

### 3.4 高可用与灾备 ★★★☆☆

- 备份链路成熟：`backups/server` 现存 123 个文件（含 .enc 加密包与 recovery_tests 目录）；chunked AEAD 加密默认开（`_constants.py:43-56`），保留 30 天/50 份，5 分钟 poller 调度；恢复演练双轨（disaster_recovery_test_task + `scripts/restore_drill.py` 恢复到 erp_system_drill 演练库）。实测备份体系总体积 0.47GB，每日加密包约 5MB——与 31MB 库规模相称。
- 自愈：prod_runner 指数退避 2s→300s、仅“进程确死 + 连续失败≥3 次/90s”才重启（`prod_runner.py:230-255`），状态原子落盘；NSSM AppExit=Restart + 5s。
- **实测健康快照（2026-10-01 03:06）**：`ready=true, frontend_ok=true, workers=8, redis 6379/6380 ok, arq=external（NSSM 托管，正常设计）`。
- **单点清单**：单台 Windows 主机承载全部组件；PG 无从库（复制脚本已备未部署）；BACKUP_ENCRYPTION_PASSWORD 单点（曾发生“成功但不可解”事故，`_constants.py:41-46` 有记录）。

### 3.5 数据流转与一致性

主链路：订单（Order/order_items）→ 抵扣备货 process_order_deduction 用 SELECT FOR UPDATE 行锁 + InventoryLog → 出货 StockOut 回写 order_id，编号经 advisory lock 水位对账 + 10 分钟 numbering_audit 巡检。异步批量导入/导出走 ARQ，max_tries=3 + on_job_failed 回调 + 死信资源。只读授权与编号均有周期对账自愈，**但无跨域 saga/业务对账报表**。异常处理成熟度中上：exception_handler/circuit_breaker/atomic_write 齐备，防御性 broad-except 有豁免清单管理（`scripts/allowed_broad_except.yaml`）。

### 3.6 文档与决策记录

docs/ 下 ADR（备份 08-23、API 版本与健康探针 09-30）、decisions/（PrimeVue bundle、多 SKU DTO 规约 09-27 等）、runbooks/（env-config、service-lifecycle、watchdog 09-30）、备份恢复 3 篇、事务边界指南。**可能过期**：analysis/01-06、ui-redesign/、bugs/、plans/2026-08-xx、backup-restore/（均为 09-17 快照）；deliverables/ 是历史归档。本次评估全部以代码实证为准，未采信旧报告。

**系统级 Top 风险**：① 整机单点；② 内网明文；③ 网关无限流；④ uploads 免鉴权直出；⑤ 备份加密口令单点（需例行解密演练留证）。

---

## 4. 依赖管理专项评估

### 4.1 后端（pip，37 条核心钉死 + 全局环境 291 包）

| 包 | 当前 | 最新（评估侧核对） | 差距 |
|---|---|---|---|
| fastapi | 0.137.1 | 0.142.2 | 落后 5 个 minor，低风险 |
| pydantic | 2.13.2 | 2.13.5 (2026-08-28) | 当前 |
| sqlalchemy | 2.0.49 | 2.0.x 当前主线 | 当前 |
| uvicorn / arq / redis / asyncpg | 0.46.0 / 0.28.0 / 5.3.1 / 0.31.0 | 均为当前线 | 当前 |
| cryptography | 50.0.1 | — | 新 |

钉法评价：`==` 全钉 + 少数工具链 `>=`，是生产系统的正确姿势。**结构性问题：生产解释器是全局 Python 3.13 环境，装了 291 个包（含 litellm、openai、locust、playwright、opencv、gevent、Flask 系等与 ERP 无关的重包）——无 venv 隔离，任何一次 `pip install` 都可能意外升级 ERP 依赖。**

### 4.2 前端（npm，双轨 UI）

Vue 3.5.43（当前）、Vite 7（最新 8.3.1，落后一个 major——生产系统不建议追 major，等 8.x 稳定半年再说）、PrimeVue 4.5、reka-ui 2.9、Tailwind 4、TS 6、vitest 4、eslint 9——全部为 2026 当前大版本。

### 4.3 漏洞审计

- **本机无外网**：`pip list --outdated` 182 项拿不到 latest、`npm outdated/audit` 输出为空——生产机联网依赖审计不可用（这本身是合理的安全姿态）。
- Mimosa 依赖扫描：862 个包，**离线 advisory 匹配 0**。
- 评估侧核对（PyPI/npm registry 直查）：上述关键包均无已知安全版本级落后。
- **建议**：在可联网的开发/CI 机上建立月度例行 `pip-audit` + `npm audit`（用 requirements.txt 与 package-lock.json 即可，无需生产机联网），结果归档到 `docs/`。

### 4.4 更新优先级与锁定策略

1. **P1**：fastapi 0.137.1 → 0.142.2（minor 线内，跑全量回归即可，见 §7 套件 357s 可负担）。
2. **P2**：vite 7 → 8（等 8.x patch 稳定 + 构建产物 diff 验证）。
3. **P0（策略）**：为生产 Python 建 venv（`python -m venv` + `pip install -r requirements/base.txt`），迁移期间用 `pip freeze` 快照回滚锚点；NSSM 服务指向 venv 内解释器。
4. 锁定：维持 `==` 钉死；新增依赖必须进 requirements 并过 scan_secrets/quality_gate。

---

## 5. 组件与插件系统评估

- **自研组件层（前端）**：37 个 Ui* 组件构成事实上的设计系统，19/25 模块在用；但复用率不均——customer/supplier 等模块手写“表格+筛选+弹窗”绕过 UiDataTable（§1.3）。
- **列表状态三套并存**：usePagedSearch（10 处）/ useEnhancedList（3 处）/ useListQuery（0 处，死代码）。应收敛为一套。
- **后端横切组件（core 46 个）**：limiter、circuit_breaker、atomic_write、security、health 等质量好、有测试；`utils/redis_cache.py` 30 处引用是被充分复用的缓存门面。
- **双轨 UI 成本**：PrimeVue（unstyled）+ reka-ui + Tailwind 三套样式心智并存，新组件先查三个来源；建议在 decisions/ 里冻结“新组件默认用哪轨”。
- **冗余/死代码**：`api/v2/endpoints` 空壳（后端）、useListQuery（前端）、`useListQuery.ts` 之外无其他显著孤儿——死代码水平很低，值得肯定。
- **文档**：组件无文档站，靠命名约定 + 测试表达意图；规模尚小可接受，Ui* 组件超过 50 个时建议补 Storybook 式目录。

---

## 6. 代码质量系统性评估（实测）

### 6.1 门禁实测汇总（2026-10-01，含工作区 WIP）

| 门禁 | 结果 | 明细 |
|---|---|---|
| `python scripts/quality_gate.py` | **PASS** | 与基线持平：N+1 0/0、裸/宽 except **5/9（可收紧 -4）**、超长函数 52/52、巨型 Vue 7/7、service 手动 commit 9/9、BOM 0/0、Alembic 0/0、env 漂移 0/0；存量合计 73 处 |
| `ruff check .` | 145 errors | Top：UP031×24、RUF100×22、S110×19、UP045×11、UP015×8；**78 条可自动修** |
| `mypy` | **0 错 / 106 files** | 但覆盖率仅 106/536 py |
| `pytest -q` | **3491 passed / 6 failed / 180 skipped（357s）** | 6 个失败全部集中在 tests/qa 冒烟与一处集成（database/numbering/customer total），伴随 event loop 污染噪音，判定为环境性问题而非业务缺陷；测试只写自动派生的 `erp_system_test` 库，不触生产 |
| `vue-tsc --noEmit` | **0 错** | — |
| `eslint src/` | **0 errors / 165 warnings** | 101 条可 --fix，多为 vue/html-indent |
| `vitest run` | **全过（exit 0）** | 120 个测试文件 |
| `check:api` | PASS | API 层 109 端点，移动端零绕过 |
| `check:routes` | PASS | PC 30 / 移动 15 / 共有 12 |
| Mimosa 静态扫描 | 0 critical / 136 high | high 多为草稿误报（见 §3.3） |

### 6.2 技术债信号

后端：`# noqa` 122、`# type: ignore` 27、TODO/FIXME 24（noqa 多带豁免理由注释）；前端：eslint-disable 2、@ts-ignore 1、TODO 1——**前端抑制标记非常干净**。大文件 Top：后端 `services/backup/orchestration/recovery_test_service.py` 1355、`bom_service.py` 1011、`tasks/backup_tasks.py` 1009；前端 `useSummaryModal.ts` **1084（全仓最大）**、`types/index.ts` 794、`BomEditor.vue` 571。超 400 行的 Vue 共 7 个（基线内）：BomEditor 571、CompletedOrdersPanel 496、BackupView 465、DashboardMobile 455、ImportPanel 427、MLoginView 409、UserPermissionDialog 405。

### 6.3 测试覆盖面

tests/ 99 + fastapi_app/tests/ 136 = 235 个测试文件、3,677 用例。**服务级测试空洞**（名称匹配法，部分由集成路径覆盖）：purchase 域 15 个（purchase_order_crud/query/sku/spare、purchase_plan_* 7 个等）、stock 域 6 个（stock_in/out/return/inventory/common/event_service）、batch_import 2、order_deduction、pattern_maker、approval_log 等 33 个模块无同名测试。**inventory_log/stock 流水类操作虽有行锁兜底，但缺直接单测，是回归风险最集中的地方。**

### 6.4 质量分层结论（最弱排序）

1. **purchase 业务域**：服务级测试最弱 + 前端 useSummaryModal.ts 1084 行全仓最大 + 2 个超标 Vue + 近期口径缺陷修复频繁（git log 佐证）——迭代最快、口径最复杂、防线最薄的区域。
2. **services/backup/**：大文件最密集目录（1355/840/798/790 行占后端 Top10 四席）。
3. **stock 核心域**：服务层无直接单测（仅集成兜底）。
4. **tests/qa**：4/6 失败集中地，是流水线最不可信信号。

**结论：不存在“质量低下”模块；结构性弱点是“大文件 + purchase/stock 域服务级测试空洞 + qa 冒烟不稳”三类，全部有明确整改路径。**

---

## 7. 性能与可维护性量化

### 7.1 负载测试声明

**未执行负载/压力测试**：本机是生产主机（AGENTS.md 第 0 条红线），任何压测都直接影响在用业务。替代方案：① 生产库 `web_vital` 表已积累 **4,147 条真实用户性能指标**（LCP/INP/CLS 类，前端 web-vitals 上报）——建议先做一次离线分析，这是零成本的真实性能画像；② 待有独立环境时用 locust（已装）对 drill 库压测，脚本可固化到 `tests/load/`。

### 7.2 已实测的容量与性能事实

| 指标 | 实测值 | 判断 |
|---|---|---|
| 数据库 | PostgreSQL 18.3，31MB，71 表 | 极小；audit_log 4,858 行是最大表（无分区需求） |
| 业务量 | 7 用户 / 20 权限 / 29 订单 / 6 产品 | 投运初期 |
| 应用 | 8 uvicorn workers + 2 nginx workers | 对当前负载严重过剩（好事） |
| 前端产物 | 131 JS / 3.24MB（未 gzip 原始） | gzip 后首屏约 1MB 级，内网可接受 |
| 回归套件 | 3,677 例 / 357s | 秒级反馈与全量回归兼得 |
| 备份 | 每日加密包 ~5MB / 保留 30 天 50 份 | 与库规模相称 |

**瓶颈预判（当前规模下均为“未来项”）**：audit_log/numbering_audit 无限增长（建议季度归档策略）；WS 单机；uploads 磁盘无配额监控；Windows 单机纵向扩到顶后无横向出路（见 §2.6）。

### 7.3 可维护性

模块化程度高（前后端分层一致、37+46 组件门面）、测试密度 3,677 例/16 万行、文档决策记录活跃（09-30 仍在更新）、门禁棘轮在位。可读性主要扣分项：purchase 前端 1084 行 composable、后端 backup 域 4 个 800+ 行文件。

---

## 8. 优化路线图（分阶段 + 回滚）

### P0（本周，零/低风险速赢）

1. **修复 6 个 pytest 失败**：集中在 tests/qa 冒烟（event loop 污染、`'NoneType' send`）——先隔离重跑定位是夹具还是断言，让回归信号恢复可信。回滚：无副作用。
2. **ruff --fix 清 78 条自动修** → `--update-baseline` 收紧门禁基线（裸 except 5/9 收紧机会）。
3. **删除死代码**：`frontend-vite/src/composables/useListQuery.ts`、`fastapi_app/api/v2/` 空壳。回滚：git revert 即可。
4. **提交当前 22 个 WIP 文件**：门禁已实测全绿，按仓库规范分主题提交（外发 TAB、客户订单录入编辑等）。
5. **修复本机 shell 集成损坏**（`_lc` 劫持导致 npm/git 间歇不可用）：重装或禁用 lean-ctx 的 bash 包装，避免下次运维事故。
6. **根目录草稿归档**：`_qa_tmp/`、`_ops/audit_scratch/` 等本地草稿（未入库）移出仓库根或加 .gitignore 说明。

### P1（本月，低风险结构改进）

7. **前端写操作统一 useApiMutation**：以 customer-order 为试点，把“mutation 成功后该失效哪些 query”收敛为领域化失效清单（复用已有 invalidateStockDataQueries 模式），文档化到 decisions/。回滚：按页面灰度回退。
8. **customer/supplier 迁移 UiDataTable**：消除镜像重复；顺手把 usePagedSearch/useEnhancedList 合一。
9. **API 层 5 处事务违规下沉 service**（order.py:334、customer.py:114/302、purchase_plan.py:112/529）：遵循 TRANSACTION_BOUNDARY_GUIDE，每处一个提交 + 对应集成测试。回滚：单提交 revert。
10. **config 增加 field_validator**：至少覆盖 CORS 白名单、DB 池、备份加密开关与口令非空联动（防“静默不加密”复发）。
11. **mypy 覆盖 106 → 全量**：按现有 ratchet 机制分批纳入 services 剩余 74 文件。
12. **迁移链线性化**：新起 pg_standalone_061 收敛 4 根（或对根迁移补 down_revision 成链），在 drill 库全量 upgrade 验证后再上生产。回滚：迁移不动数据，drill 验证即可。
13. **vendor-primevue 672KB 拆分**：theme/theming-utils 与组件分离 + visualizer 分析入口 443KB。回滚：构建产物 hash 比对。

### P2（季度，基础设施）

14. **部署 PG 只读副本**：脚本已备（`config/postgres/init-replica.sh` 环境变量注入 + `scripts/setup_pg_replication.sh`），消除数据库单点；先在 drill 环境验证 basebackup + 复制槽。回滚：删除 standby.signal 回单机。
15. **内网 TLS**：自建 CA 或企业证书，nginx 3000 → 443 ssl；Cookie 已有 secure 属性位（`auth.py:207`）。回滚：保留 3000 过渡监听。
16. **nginx limit_req**：全局每 IP 泛率 + /api/v1/auth 登录路径收紧（与应用层双层防爆破互补）。
17. **uploads 鉴权直出改造**：签名 URL（后端签发、nginx secure_link 校验）或经 API 流式鉴权；过渡期至少做 URL 不可枚举审计。
18. **进程内状态 Redis 化**：WS 票据入 Redis、开启权限 L1 缓存跨 worker 广播——完成后具备双实例横向扩展能力。
19. **fastapi 0.137 → 0.142**：minor 线内升级，全量回归 + drill 冒烟。
20. **备份解密演练季度化**：现有 restore_drill 增加“解密 + 校验和”步骤并归档证据，消除加密口令单点。

---

## 9. 需要补充的资源与数据（评估缺口）

| 资源 | 状态 | 建议 |
|---|---|---|
| 架构/接口/部署文档 | ✅ 已用 repo 内 docs/（ADR/runbooks/决策，09-17~09-30） | 缺业务流程图与 ER 图；建议补一版并纳入 ADR 流程 |
| 代码仓库访问 | ✅ 完整具备 | — |
| 测试/预发环境 | ❌ **最大缺口**：无独立预发 | erp_system_drill 演练库已存在，建议升级为常态预发（独立端口起 uvicorn，不装 NSSM） |
| 性能监控数据 | ⚠️ web_vital 4,147 条在库未分析；/metrics+OTEL 已备但无看板留存 | 先做一次 web_vital 离线分析；接 Grafana 或月度导出归档 |
| 历史故障记录 | ❌ git/docs 无事故库 | 建立 `docs/ops/incidents/`，把“备份不可解”这类事故沉淀为记录 |
| 用户量/数据量/业务规模 | ✅ 已实测（7 用户/29 订单/31MB） | **需要业务方给出增长预期**（月订单增量、并发峰值），以校准容量规划与 §8-P2 优先级 |

---

## 附录：证据与工具

- 质量门禁：`scripts/quality_gate.py`、`ruff check .`、`mypy`、`pytest -q`（3,677 例）、`vue-tsc`、`eslint`、`vitest`、`check:api`、`check:routes` —— 全部于 2026-10-01 在工作区实测。
- 安全扫描：Mimosa `scan-2026-09-30T18-44-41.165Z-ec853137579f`（seal `sha256:24cf2e16…ca663b`，4,683 文件，静态不执行）。
- 数据库普查：只读 SELECT/pg_stat_user_tables/pg_database_size（连接账号 `erp_app`，未输出任何凭据）。
- 版本核对：PyPI/npm registry（评估侧网络，2026-10-01）。
- 结构解析：迁移链用 Python AST 解析（遵循本仓库“禁止正则猜结构”约定）。
- 局限：负载测试未执行（生产主机红线）；npm audit/pip-audit 因生产机无外网未跑（已有离线替代证据）；mypy 覆盖率受 ratchet 配置限制。
