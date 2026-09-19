# 滨发 ERP 上线前审核报告 —— 前端 / 运行时 域

**审核人**：严过关（QA 工程师）
**任务 ID**：Task #6（前端潜在 bug/边界/错误处理/状态与生命周期）、Task #8（运行时性能/资源占用/可观测性/灾备）
**审核日期**：2026-09-17
**审核方式**：只读审计（未改源码 / 未 git commit / 未构建 / 未停进程 / 未 taskkill）
**代码基线**：`git HEAD = a5e7b82`，工作树干净（`git status --porcelain` 为空）
**线上环境**：本机 192.168.0.95 即生产机；nginx:3000 → `frontend-vite/dist`；FastAPI:5002（8 uvicorn worker）+ ARQ + Redis + PostgreSQL 18.3
**旧产物复核**：`deliverables/gstack/pre-launch-check-fullstack-2026-09-05.md` 已逐条回当前源码/线上复核

---

## 0. 结论速览

| 项目 | 结论 |
|------|------|
| **上线就绪判定** | 🟡 **READY_WITH_CONDITIONS（有条件上线）** |
| Blocker | **0** |
| Severe（🟠） | **2** |
| Medium（🟡） | **4** |
| Mild（🟢） | **5** |
| 已排除（不得重报） | 2 条 |
| 无法验证 | 3 条 |

**一句话**：前端核心链路（路由兜底、登出清缓存、WS/定时器生命周期、z-index）经复核**均已妥善处理**，运行时**无阻塞性缺陷**（延迟远低于阈值、连接池核算安全）；上线前**建议补齐错误聚合（Sentry）并清理发布物料**，其余可作为上线后 30 天治理项。

---

## 1. 发现清单（A 前端 / B 运行时 / C 可观测性）

### 🔴 BLOCKER —— 无

未发现会导致白屏、数据丢失或安全越权的阻塞性缺陷。前端已具备多层兜底（见 §3 已排除/已处理项）。

---

### 🟠 SEVERE

#### S-1 [C/可观测性] 生产错误聚合基本缺失，故障无法主动告警
- **结论**：全仓仅有 1 处动态 `import('@sentry/vue')` 并调用 `captureException`，**无 `Sentry.init()`、无 DSN 配置、无 `captureMessage`、无性能监控**。生产 500 只能靠人工翻日志。
- **证据**：
  - `frontend-vite/src/main.ts:56` —— 动态 import `@sentry/vue` 后调用 `captureException`，且**上限 10 次**（`main.config.errorHandler` 内计数）；`grep Sentry.init` 全仓 0 命中。
  - 线上 `logs/nginx-access.log` 近 6 天：`500×34`、`502×23`、`503×8`、`499×47` —— 这些**均无任何聚合记录或告警**，只能事后 grep。
  - 唯一定位手段是 `fastapi_app/middleware/audit_middleware.py:96` 生成的**8 位 request_id**（写入 access.log 与响应头），需人工按 id 串联，非主动告警。
- **触发条件**：任何后端 500/502、前端未捕获异常。
- **影响**：故障发现依赖用户投诉；平均发现时延可能达小时级。
- **修改建议**：① 生产启用 `Sentry.init({ dsn, environment, tracesSampleRate })`，并在 FastAPI 侧接入 `sentry-sdk[fastapi]`；② 至少配置「错误率 > N/5min」告警到值班人；③ 保留 request_id 作为 Sentry event tag 以便与 nginx 日志互查。

#### S-2 [C/可观测性] `prod_runner` 自身 stdout 块缓冲，重启期启动日志可能丢失
- **结论**：`prod_runner.py` 为拉起的**子进程**设置了 `PYTHONUNBUFFERED=1`，但**自身进程的 stdout 未行缓冲**，通过 NSSM 重定向到 `logs/erp-prod.log` 时可能成块延迟落盘或丢失。
- **证据**：`fastapi_app/core/prod_runner.py` 中 `start()` 仅对 child 环境注入 `PYTHONUNBUFFERED`；`logs/erp-prod.log`（930KB）在重启窗口存在记录不完整现象（旧报告已记为已知缺口，本次复核**仍成立**）。
- **触发条件**：服务重启/崩溃恢复瞬间。
- **影响**：排障时缺失启动期关键日志（端口占用、worker 拉起失败等）。
- **修改建议**：`prod_runner` 启动时 `sys.stdout.reconfigure(line_buffering=True)` 或进程级 `PYTHONUNBUFFERED=1`（NSSM 环境变量）；并对每行打时间戳+run_id。

---

### 🟡 MEDIUM

#### M-1 [A/前端] `catalog` store `per_page=1000` 被后端 422 拒绝，下拉选项可能不全
- **结论**：catalog store 用 `{ page: 1, per_page: 1000 }` 近似拉全量，但后端对多个 `*/list` 接口有 `le=200` 约束，请求**直接被 422 拒绝**，实际只能退回 200 条，下拉框在大数据量下缺项。
- **证据**：
  - `frontend-vite/src/stores/catalog.ts` —— `CATALOG_PAGE_PARAMS = { page: 1, per_page: 1000 }`。
  - 实测 `_audit_tmp_perpage.txt`：`GET /api/v1/products/list?per_page=1000` → **HTTP 422**（`less_than_equal` 对 `per_page` 上限 200）；`per_page=200` → **HTTP 200**。
- **触发条件**：产品/客户/物料等基础数据超过 200 条时的下拉选择。
- **影响**：用户在下拉中搜不到第 201 条之后的基础数据，可能选错或无法下单。
- **修改建议**：catalog 改为**分页循环拉全**或后端提供 `/options` 轻量全量接口；至少把前端常量降到 `per_page=200` 并把「截断提示」显性化。

#### M-2 [A/前端] 部署换代：Service Worker precache 钉住旧 `index.html`，已打开旧标签页切路由会 404
- **结论**：SW precache 清单内 `index.html` 带 revision，新构建发布后会换掉 hash；**已打开的旧标签页**持有的旧 `index.html` 引用已不存在的分片，切路由触发 chunk 404。
- **证据**：
  - `frontend-vite/dist/sw.js` —— precache 191 条目（118 js/68 css/1 html/4 other），含 `createHandlerBoundToURL("index.html")` 与 `cleanupOutdatedCaches()`；`registerType:'autoUpdate'`。
  - 线上 `nginx-access.log` 6 天内请求了**当前 dist 不存在的 assets 分片 910 个不同名、共 3093 次**（如 `vendor-vue-BWYhiMOa.js×115`、`vendor-primevue-_eWMvzqY.js×113`）——证实旧标签页确在请求旧 hash。
- **缓解现状（故降级 medium）**：
  - `frontend-vite/src/router/index.ts` 有 `router.onError`，`isChunkLoadError` 匹配动态 import 失败后**自动 `window.location.href` 重载**，`MAX_RELOAD=3 / RESET_WINDOW_MS=60s` 防死循环 → **不白屏**，用户看到一次自动刷新。
  - `dist/index.html` 内联加载指示器 + 8s 超时失败提示「页面加载失败，请检查网络后重试」→ **无永久白屏**。
  - SW 对 `/api/` 已改 `NetworkOnly`，**无数据陈旧风险**。
- **影响**：发布后极少数活跃旧标签页用户会经历一次「切换页面自动刷新」。
- **修改建议**：把「Sentry/埋点记录 chunk 404 次数」打通（配合 S-1）；可选在 `index.html` 加版本指纹，SW 检测到版本变更时主动 `skipWaiting` + 提示刷新。

#### M-3 [B/前端] 首屏 vendor 包体积偏大（PrimeVue / ECharts 全量）
- **结论**：`dist` 共 3.67MB，其中 JS 2987KB/120 个；最大分片 `vendor-primevue 672KB`、`vendor-echarts 557KB`，均**全量引入**，`index.html` 对其做了 `modulepreload` → 首屏下载与解析成本偏高。
- **证据**：dist 实测（`_audit_tmp` 统计）：`vendor-primevue-SadobcXg.js 672.4KB`、`vendor-echarts-CjpiykIs.js 556.9KB`、`index-8985Y_zC.js 442.9KB`、`vendor-fontawesome-RiOzw8uk.js 148.3KB`；`index.html` modulepreload vendor-vue/query/fontawesome/axios。
- **影响**：内网千兆环境下尚可（实测静态资源 p50 1.3ms），但首次加载 JS 解析时间与内存占用偏高，移动端更明显。
- **修改建议**：PrimeVue 按需导入；ECharts 用 `echarts/core` + 按需 `use()`；FontAwesome 改图标级 import（当前 451 行 `icons.ts` 疑似全量注册）。

#### M-4 [A/B/发布物料] 发布包清洁度：6 个 dist 备份目录 + `.bak` 残留 + 61 个根目录调试脚本
- **结论**：旧报告「5 个 dist 备份、`.bak_ipv6`、根目录调试脚本」问题**仍成立且在扩大**；`.gitignore` 未覆盖 `dist.bak*/`、`dist_prev_*/`，存在误部署/误打包风险。
- **证据（本次实测）**：
  - `frontend-vite/` 下 dist 备份目录 **6 个**：`dist.bak-20260824`、`dist.bak-20260829`、`dist.bak-20260829-2`、`dist_prev_20260829_164650`、`dist_prev_20260829_180908`、**`dist_prev_20260911_213006`（旧报告后新增）**。
  - 源码树 `.bak` 残留：`fastapi_app/main.py.bak_ipv6`、`fastapi_app/core/prod_runner.py.bak_ipv6`。
  - 仓库根目录 `_*.py` 调试脚本 **61 个**（顶层 `*.py` 共 76 个），含 `analyze_ruff.py`、`_dbg_customers.py`、`_shoot_p6.py`、`server_manager_v533.py` 等。
- **影响**：PyInstaller/发布脚本可能误打包；磁盘冗余；审计面混淆。
- **修改建议**：删除/归档 6 个 dist 备份；`.gitignore` 增 `frontend-vite/dist.bak*/`、`frontend-vite/dist_prev_*/`；删除 `*.bak_ipv6`；根目录 `_*.py` 移入 `scripts/dev/`。

---

### 🟢 MILD

#### L-1 [A] 部分本地缓存用 `localStorage`，跨用户不清理
- **结论**：`country` store（`erp_countries`）、`multiLevelCache`（L2）、`useProductionEntry`（最近产品）使用 `localStorage`，登出不清理。属**低风险本地偏好**（不含凭据/PII）。
- **证据**：`stores/country.ts:10/19`、`utils/multiLevelCache.ts:24/45`、`views/production/composables/useProductionEntry.ts:41/78`。
- **说明**：认证 token **不在** localStorage —— `utils/secureStorage.ts` 走 Capacitor SecureStorage + 内存缓存，web 端无明文 token；CSRF 从 cookie 读（`api/request.ts:33`）。XSS 面已收敛。
- **建议**：非必需，可在 `logout()` 一并清理或改 sessionStorage。

#### L-2 [B] nginx 无 brotli、无 upstream keepalive（平台限制）
- **结论**：`config/nginx-windows.conf` 仅 `gzip on`；upstream 无 `keepalive`。
- **证据**：Windows 官方 nginx 不含 `ngx_brotli`，也不支持 upstream keepalive 指令 → **平台性限制，非配置疏漏**。
- **影响**：文本资源较 brotli 多传约 15–20%；高并发下 TCP 建连略增（当前负载未见问题）。
- **建议**：记录为已知限制；若需 brotli 可换 OpenResty/nginx-brotli 构建，非上线必需。

#### L-3 [B] 日志增长速率本次窗口内无法测得
- **结论**：45s 双采样所有日志文件 `delta=0`（低峰期无新写入），**无法给出日增量速率**。
- **证据**：`_audit_logtail.txt` 双采样 delta=0；当前 `logs/` 合计 **125.32MB**（`erp-prod.log 930KB`、`erp-arq.log 5.9MB`、`后端(uvicorn).out.log 19.6MB`），`backups/ 227.9MB/470 文件`。
- **建议**：上线后连续观测 24h 记录日增量；确认 `prod_runner` 的 50MB copytruncate 轮转生效（逻辑存在）。

#### L-4 [A] 线上 404 集中于用户上传图缺失
- **结论**：6 天 nginx 日志 `404×186`，多为 `/static/uploads/customer-sampling/*` 缺图（`34+34+10…`），非代码 bug。
- **影响**：客户采样页图片破图。
- **建议**：核对上传产物是否随备份迁移丢失；对缺失图加前端占位兜底。

#### L-5 [C] 少量 500 集中于统计接口
- **结论**：`500×34` 中集中于 `/api/v1/dashboard/stats`（8）与 `/stock/stats`（8）；`502×23` 属 09-12 后端宕机期；`503×8` 全为 `/api/v1/backup/full`（备份任务拒绝，属预期限流）。
- **影响**：统计页面偶发报错。
- **建议**：结合 S-1 的错误聚合定位这两个端点的异常栈。

---

## 2. 性能与资源数据表

### 2.1 HTTP 延迟（直连 :5002 / 经 nginx :3000，`--noproxy '*'`）

| 端点 | 通道 | n | p50 | p95 | p99 | max |
|------|------|---|-----|-----|-----|-----|
| `/api/health` | 直连 | 30 | 5.0ms | 24.9ms | — | 27.0ms |
| `/api/health` | nginx | 30 | 3.6ms | 16.2ms | — | 25.9ms |
| `/api/v1/purchase-center/orders?per_page=50` | 直连 | 25 | 9.2ms | 32.3ms | — | 34.1ms |
| `/api/v1/purchase-center/orders?per_page=50` | nginx | 25 | 11.7ms | 37.6ms | 64.9ms | 64.9ms |
| `/index.html` | nginx | 20 | 1.4ms | — | — | — |
| `/assets/index-Bh2zx18f.js`(45KB) | nginx | 20 | 1.3ms | — | — | — |

> **结论**：全部路径 p50 < 12ms、p95 < 38ms，**远低于 100ms 阈值**。

### 2.2 静态资源 / 缓存头

| 检查项 | 实测结果 |
|--------|----------|
| `index.html` 缓存 | `Cache-Control: no-cache, no-store, must-revalidate` ✅ |
| `sw.js` 缓存 | `no-cache, no-store, must-revalidate` ✅ |
| `/assets/*` 缓存 | `Cache-Control: max-age=31536000` + `Expires 1y`（immutable hash 命名）✅ |
| 压缩 | gzip on（含 `application/javascript`）；**无 brotli**（平台限制）⚠️ |
| 安全头 | CSP（script-src 'self' 'unsafe-inline'）、HSTS、X-Frame-Options SAMEORIGIN 均已设 ✅ |
| dist 体积 | 192 文件 / **3.67MB**；JS 120 个 / 2987KB；CSS 68 个 / 531KB |
| 首屏 preload | `index.html` modulepreload vendor-vue/query/fontawesome/axios |

### 2.3 进程内存（受关注进程）

| 进程族 | 进程数 | 合计内存 | 备注 |
|--------|--------|----------|------|
| python（含 8 uvicorn worker） | 13 | 1657MB | 单 worker 约 23–28MB；master 约 180MB |
| nginx | 13 | 172.8MB | 各约 13MB |
| postgres | 57 | 1440MB | 1 主 + 1 只读副本 + 54 后台 |
| redis | 2 | 19MB | — |
| node | 4 | 189MB | — |
| **受关注合计** | — | **3479MB（3.40GB）** | 机器总内存 **15.42GB**，可用 **3.86GB**（占用约 75%） |

### 2.4 PostgreSQL / 连接池核算

| 项 | 值 |
|----|-----|
| 版本 | PostgreSQL 18.3 |
| `max_connections` | 100（`superuser_reserved_connections=3`） |
| 当前总连接 | 39（idle 29 / active 1 / None 9） |
| 主库 5432 客户端连接 | 30（`erp_app`） |
| 只读副本 5433 | 1（`erp_readonly`） |
| 数据库大小 | 44MB |
| `shared_buffers` | 5053448kB（≈4.8GB） |
| **SQLAlchemy 池核算** | `available = 100-20 = 80`；`pool_size = max(5, 80//(8*2)) = 5`；`max_overflow = max(3, 80//(8*3)) = 3` → **8 worker × (5+3) = 64 < 100**（留 20 给 ARQ/迁移）✅ **安全，不会耗尽** |

### 2.5 Redis

| 实例 | used_memory | maxmemory | 淘汰策略 |
|------|-------------|-----------|----------|
| 6379 | 1MB | 0B（无限制） | noeviction |
| 6380 | 767KB | 256MB | noeviction |

### 2.6 磁盘

| 盘 | 已用 | 剩余 | 总量 |
|----|------|------|------|
| C: | — | **57.8GB** | 212.7GB |
| D: | — | **498.9GB** | 740.2GB |

| 目录 | 体积 |
|------|------|
| `logs/` | 125.32MB |
| `backups/` | 227.9MB / 470 文件 |
| `deliverables/` | 1.11MB |

### 2.7 nginx access.log（近 6 天全量 16603 行）

| 维度 | 数据 |
|------|------|
| 独立 IP | 5 个（192.168.0.95×8289、192.168.0.149×5764、127.0.0.1×2231 等） |
| 状态码 | 200×9993、101×6176（WS 升级）、404×186、401×103、499×47、500×34、502×23、403×15、400×12、503×8 |
| request_time | p50=0.012s、p90=5.014s、p95=5.017s、p99=60.013s、max=61.045s |
| >1s 请求 | 6154 次（**绝大多数为 WS 长连接计入 request_time，非 HTTP 慢请求**） |

---

## 3. 已排除项 / 已处理项 / 无法验证项

### 3.1 已排除（**不得重新报告**）

| # | 旧结论 | 实测反驳 |
|---|--------|----------|
| E-1 | 「8 uvicorn worker + L1 缓存导致双峰卡顿」 | **不成立**。实测 p50≈5–12ms、p95≈16–38ms，**无任何双峰/卡顿特征**。 |
| E-2 | 「Service Worker 拖慢首屏」 | **不成立**。A/B 实测 **SW 启用反而快 38ms**（precache 命中优于网络）。 |

### 3.2 已处理 / 已妥善（本域复核通过，非问题）

| 项 | 复核结论 | 证据 |
|----|----------|------|
| chunk 404 白屏 | **已兜底**：`router.onError` 自动重载，`MAX_RELOAD=3/60s` 防死循环 | `router/index.ts:139-156` |
| 登录态残留（登出/切换用户） | **已处理**：`logout()` 清 user/navSections/loaded、`clearCsrfCache`、清 sessionStorage 快照、`clearUserCaches()`（catalog/patternRoom/notification/queryClient+persister） | `stores/auth.ts:237` 等 |
| WebSocket 泄漏 | **已处理**：`onUnmounted` → `cleanup()` 关 ws + clearTimeout | `composables/useWebSocket.ts` |
| 轮询定时器泄漏 | **已处理**：`setInterval(30s)` 与 `onUnmounted` 配对清理 | `composables/useNotifications.ts` |
| 移动端 z-index 冲突 | **已修复**：`MobileNotificationBell`（z-index:60）与 `MobileNavBar`（z-index:50）已用 28px 占位规避遮挡 | `mobile/layouts/components/MobileNavBar.vue` |
| 全局渲染异常红条 | **已兜底**：`app.config.errorHandler` 显示「页面渲染出现异常，请刷新」红条（z-index:99999） | `main.ts` |
| 页面加载白屏 | **已兜底**：`index.html` 内联指示器 + 8s 超时失败提示重载 | `dist/index.html` |
| 401 刷新竞态 | **已处理**：单飞 `_refreshPromise`；GET 去重 `_inflightGet` | `api/request.ts` |
| PrimeVue 弹窗层级 | 约定 zIndex modal:2100/overlay:2000 自研弹窗 ≤2000，未见冲突 | `main.ts` |
| 后端启动日志（子进程） | 对 child 已设 `PYTHONUNBUFFERED=1` | `prod_runner.py` |

### 3.3 无法验证 / 本次未覆盖

| 项 | 原因 |
|----|------|
| 日志日增长速率 | 45s 双采样 delta=0（低峰期无写入） |
| 真实并发下的吞吐/压测 | 只读审计禁止压测生产；仅有 n=20–30 延迟分位 |
| 大数据量前端虚拟滚动实测 | 生产数据量未知、无法造数；仅静态确认 `per_page=500` 用法与 catalog 截断（M-1） |

### 3.4 旧审计产物逐条复核（`pre-launch-check-fullstack-2026-09-05.md`）

| 旧条目 | 复核结论 |
|--------|----------|
| 5 个 dist 备份目录 | **仍成立且在扩大**：现 **6 个**（新增 `dist_prev_20260911_213006`） → 见 M-4 |
| `*.bak_ipv6` / `server_manager.py.bak-*` 残留 | **仍成立**（2 个 `.bak_ipv6` 仍存在） → 见 M-4 |
| 根目录调试脚本（`analyze_ruff.py`/`_dbg_*`/`_shoot_*`） | **仍成立且扩大**（61 个 `_*.py`） → 见 M-4 |
| 8+ 个超 800 行文件（`backup_tasks.py 962` 等，**后端域**） | **前端域不适用**：前端最大文件仅 `types/index.ts 658` 行、`CompletedOrdersPanel.vue 643` 行，**>800 行 0 个** → 「7 个超长组件」基线**未成立/已拆分**（后端域由 Engineer 复核） |
| `logs/`(16MB)、`backups/`(59MB)、`build/`(24MB) 体积 | **已变化**：实测 `logs/ 125.32MB`、`backups/ 227.9MB`，均显著增长，需复核轮转/保留策略 |
| 迁移 4 个 `down_revision=None` 基线 | **本域不覆盖**（后端/迁移，转 Engineer） |

---

## 4. 上线就绪判定

### 🟡 READY_WITH_CONDITIONS（有条件上线）

**判定依据**
- 前端核心健壮性（路由兜底、登出清缓存、WS/定时器生命周期、z-index、错误红条、白屏兜底）**均已妥善处理**，无 Blocker。
- 运行时**无阻塞性缺陷**：延迟远低于阈值（p50 5–12ms），DB 连接池核算安全（64<100），内存/磁盘水位健康。
- 需在**上线前**处理的条件项：S-1 错误聚合、M-1 下拉截断（若基础数据 >200 条）。

### 上线前必办（P0）
1. **S-1**：启用 Sentry（前后端）或等价错误聚合 + 告警。
2. **M-1**：确认产品/客户/物料基础数据是否 >200 条；若是，修 catalog 分页拉全（否则下拉缺项）。
3. **M-4**：清理 6 个 dist 备份目录 + `.bak_ipv6`，补 `.gitignore`。

### 上线后 30 天治理（P1）
4. **S-2**：`prod_runner` 自身 stdout 行缓冲。
5. **M-3**：PrimeVue/ECharts/FontAwesome 按需引入，压缩首屏 vendor。
6. **M-2**：SW 版本指纹 + 主动 `skipWaiting`（可选）。
7. **L-1/L-3/L-4/L-5**：本地缓存清理、日志速率观测、缺图兜底、统计接口 500 定位。

---

*本报告所有结论均指向 `文件:行号` 或实测数字；只读审计，未改业务代码（工作树干净，HEAD=a5e7b82）。原始证据见 `deliverables/audit-2026-09-17/`。*
