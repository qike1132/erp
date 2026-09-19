# ERP 系统 Debug 模式 vs Production 模式性能差异 —— 深度排查与优化报告

**日期**：2026-09-17
**场景**：调试复盘 + 性能优化（多成员协作）
**参与成员**：产品官（product-reviewer）+ 排障手（investigator）+ 质量门神（qa-lead）
**工作目录**：`D:\erp_system`
**排查方式**：只读取证（未修改任何服务状态）

---

## 📌 TL;DR（执行摘要）

- **整体结论**：🟡 **有条件通过** —— 用户报告的现象属实，但**归因方向需要反转**。
- **核心发现**：所谓「production 模式」当前**并未运行**。3000 端口跑的是 **Vite dev server**（实测首页含 `/@vite/client` + `/src/main.ts`，日志含 171 条 `hmr update`），5002 端口跑的是 **`--reload` 开发模式 uvicorn**，正式生产栈（`erp-prod` NSSM + Nginx + dist 产物 + 8 worker）**处于 Stopped 状态，nginx 进程数 = 0**。用户实际在比较**两套不同的运行时**，而非同一系统的两种模式。
- **关键推论**：项目存在**三条前端启动路径，全部由 Vite 直接托管、没有一条走 Nginx**；`prod_runner` 检测不到 Nginx 时**只打一行 INFO 就静默降级**给 `vite preview` —— 于是 `nginx-windows.conf` 里精心配置的 gzip / 缓存头**全部成为废纸**。这同时解释了"压缩全失效"与"缓存策略不生效"。
- **阻塞项数量**：**5 项 P0**（其中 2 项为高危稳定性缺陷）
- **下一步**：先补 **基线测量**，再按 P0 → P1 → P2 顺序修复；**不要在未测基线前动手**。

---

## 🎯 核心结论卡片

| 项目 | 内容 |
|------|------|
| Go / No-Go | 🟡 条件 Go（修复 5 项 P0 后可 Go） |
| 严重度分布 | 🔴 5 / 🟠 6 / 🟡 6 / 🟢 1（共 18 项） |
| 关键行动项 | **17 条**（含 1 项 P0 安全待确认项） |
| 建议负责人 | 运维/后端（P0-1、P0-4）· 前端（P0-2、P0-3）· 全员（基线测量） |
| 最大单项收益 | 消除后端重启风暴（M11/R1）→ 服务可用性从"每日数十次中断"变为持续在线 |
| 最大确定性收益 | 修正托管拓扑（P0-1）→ 首屏资源从"逐模块转译"变为"预打包 + 压缩 + 长缓存" |

---

## 1. 各成员核心结论

### 🔧 排障手（后端 + 基础设施取证）

- **核心判断**：抓到了本案的**决定性反证** —— 当前 5002 由 `ERP服务器管理器_v5.33.exe` 拉起的 `uvicorn --reload --reload-dir fastapi_app` 提供服务（父子进程结构 + `WatchFiles ... Reloading...` 日志双重实证），3000 由 `node.exe`（Vite dev，首页含 `/@vite/client`）提供服务，而 NSSM 服务 `erp-prod` = **Stopped**、nginx 进程数 = **0**。`logs/prod_runner.json` 声称的 `frontend_type=nginx / workers=8 / pid=3708` 是**上一轮生产的陈旧快照**（实际 5002 属主 PID=17264）。
- **关键建议**：不要在「优化生产配置」上继续投入 —— **正式生产栈在配置层面本身是正确的**。必须先 `nssm start erp-prod` 把正式栈跑起来，才能做同条件 A/B。
- **额外高价值结论**：成功**排除**了 4 个用户点名怀疑但实际不成立的方向 —— 日志写盘（`log_config.json` 从未被加载，是死配置）、N+1 查询（188 处 `selectinload/joinedload` 已覆盖热路径）、密码哈希过慢（Argon2id + `run_in_threadpool`）、DEBUG 日志级别（实际 INFO）。**这些方向不必再投入时间。**

### 🎨 产品官（现象剖析 + 配置风险评审）

- **核心判断**：把「生产反而更慢」拆解为 **12 条机制**，并明确指出关键前提 —— debug 与 production 在本项目**不是 DEBUG 开关，而是两套完全不同的启动拓扑**（单进程+内存直连+无构建产物 vs 8worker+Nginx+PWA+生产中间件）。
- **关键建议**：按「稳定拖慢」与「间歇卡死」两类治理。**最强解释项是 M11 健康探针误杀导致的重启风暴**（`logs/erp-prod.log` 60 行内 8 次完整重启循环），根因是 `HTTP_PROXY/HTTPS_PROXY` 无 `NO_PROXY` 导致探针被劫持 —— 项目代码注释中已自曝此根因却未修。其次是 **M1 PWA Service Worker 接管 API**（dev 下 PWA 被禁用，prod 下开启，`NetworkFirst` + `StaleWhileRevalidate`）与 **M4 八 worker 下 L1 进程内缓存命中率从 ~100% 跌至 ~12%**（`CACHE_L1_BROADCAST_ENABLED=false` 与 8 worker 不匹配）。

### ✅ 质量门神（前端构建 + 网络传输层 + 可验证性）

- **核心判断**：构建产物**质量合格但从未被服务**。`frontend-vite/dist` 4.1MB / 185 文件 / **0 个 `.map`**（sourcemap 已关 ✓）/ 已配置 `manualChunks` 分包 / PWA 产物齐全；但 3000 端口返回的是 `/src/main.ts` 而非 `/assets/index-*.js`。
- **关键建议**：① 托管拓扑是根因，压缩与缓存头之所以"全部失效"是因为 **Nginx 没在跑**；② 首屏关键路径实测 **447KB → gzip 后 145KB（省 67%）**，大 chunk 收益更显著（`vendor-primevue` 672KB → gzip 142KB → brotli 104KB）；③ **Windows 版 nginx 配置里完全没有 brotli**，`config/nginx.conf` 的 `brotli on` 只在 Docker 版存在，属"文档写了但没生效"。

---

## 2. 综合审查发现（去重合并后按严重度排序）

| # | 严重度 | 类别 | 位置 | 问题描述 | 建议 | 来源 |
|---|--------|------|------|---------|------|------|
| 1 | 🔴 | 托管拓扑 | `server_manager_v533.py:1811,1838` | **被当作"生产"的实为开发启动器**：3000=Vite dev server、5002=`--reload` uvicorn；`erp-prod` 服务 Stopped、nginx 进程 0。用户比较的是两套不同运行时，非两种模式 | 明确区分「开发启动器」与「生产服务」；生产务必走 `erp-prod`(prod_runner) | 排障手 |
| 2 | 🔴 | 稳定性 | `logs/erp-prod.log` | **后端重启风暴**：日志内累计 **366 次**"健康检查持续失败，强制重启进程树"（脚本实测），每次 8 worker 冷启动 + 连接池重建 + 缓存全清。**⚠️ 根因已修正**：不是"代理劫持探针"（该隐患代码 `_OPENER_DIRECT` 已修），**真实触发源待定位**（疑似 `--reload` 期间不可达 / worker 崩溃循环） | 先定位真实触发源再修；顺便注入 `NO_PROXY=127.0.0.1,localhost,::1` 做防御 | 产品官（已修正）· 主理人（脚本实测 366 次） |
| 3 | 🔴 | 缓存正确性 | `frontend-vite/vite.config.js:56,71` | **PWA Service Worker 接管全部 API**：`NetworkFirst`(1.5s 超时) + `StaleWhileRevalidate`(请求翻倍)，`registerSW.js` 以 `scope:'/'` 注册。ERP 场景下库存/订单可能显示 1-2 分钟前的旧值 | 从 `runtimeCaching` 移除所有 `/api/` 条目；加 `navigateFallbackDenylist` | 产品官 + 质量门神 |
| 4 | 🔴 | 压缩 | `middleware.py:319-324` + `nginx` 未运行 | **gzip 两边同时放弃**：后端因 `APP_ENV=production` 直接 `return`（"交给 Nginx"），而 Nginx 没在跑 → 静态资源与 API 响应**全程无压缩**。脚本实测 `/metrics`：**明文 18,169 字节，gzip 后仅 2,568 字节 → 多传 85.9%** | 让 gzip 归属取决于"Nginx 是否实际存活"，而非仅看 `APP_ENV` | 排障手 + 质量门神 |
| 5 | 🟠 | 静态资源 | `logs/nginx-error.log` | **hash 撕裂 → 404 全量重下**：`CreateFile() ... assets/HubeiView-CvR8KlHF.js failed (2: 系统找不到指定的文件)`，脚本实测累计 **11 条**，典型"旧 HTML + 新 assets" | 改为原子目录切换部署（`dist.new` → 切换 → `nginx -s reload`） | 产品官 |
| 6 | 🟠 | 缓存效率 | `.env:159,169` | **8 worker 下 L1 命中率暴跌**：L1 为进程内缓存（TTL 30s），8 进程各自独立，命中率上限 ~12%；`CACHE_L1_BROADCAST_ENABLED=false`（注释自己写了"多 worker 建议 true"） | 置 `true` 并重启全部 worker；或 `local_ttl` 降至 5-10s | 产品官 |
| 7 | 🟠 | 配置错位 | `.env:42` / `.env.production` | **`.env` 才是权威文件**（`load_dotenv(override=False)` + `env_file=".env"`），`.env.production` 用 `${}` 占位且**实际未被使用** → 形同虚设，且误导排查（本次就曾误导） | 二选一：让 `.env.production` 真正生效，或删除 | 排障手 + 产品官 |
| 8 | 🟠 | 构建配置 | `frontend-vite/vite.config.js` vs `.ts` | **双配置并存，`.js` 覆盖 `.ts`**（Vite 解析优先级），TS 配置的修改**静默失效** | 删除 `vite.config.js` 与 `vite.config.d.ts`，统一用 `.ts` | 质量门神 |
| 9 | 🟠 | CORS | `.env.production:69` + `config.py:100-103` | 生产 CORS 仅放行 localhost，而实际访问源是 `192.168.0.95:3000` / `192.168.0.149`；`startswith("http://localhost")` 不匹配内网 IP → 请求被拒后重试 | 显式列出 LAN 源，并放宽生产过滤条件 | 产品官 + 排障手 |
| 10 | 🟡 | 连接池 | `database.py:24-56` | `max_overflow=3`（`workers*3` 分母偏大）；**`pool_recycle` 未设置**（`.env:22` 写了 1800 但代码不读）→ 死连接导致偶发数百 ms 抖动 | 补 `pool_recycle`，放宽 `max_overflow` | 排障手 |
| 11 | 🟡 | 日志 | `logger.py:65-75` | **8 进程共写同一日志文件且无进程锁** → 行撕裂（`后端(uvicorn).out.log` 实测 `[fastapi_app2026-09-17...]` 交错），IO 放大 8× | 每 worker 独立文件，或统一走 stdout 外部轮转；INFO→WARNING | 产品官 |
| 12 | 🟡 | 体积 | `dist/assets/` | 大 chunk：`vendor-primevue` 672KB、`vendor-echarts` 557KB、`index` 443KB。PrimeVue 配额过大说明按需引入未真正生效 | 审计 `unplugin-vue-components` 实际覆盖范围；ECharts 走 `echarts/core` | 产品官 + 质量门神 |
| 13 | 🟡 | 压缩 | `config/nginx.conf` vs `nginx-windows.conf` | **Windows 版无 brotli 指令**，Docker 版的 `brotli on` 从未生效 | 用带 brotli 的 Windows 构建，或构建期预压缩 `.br`/`.gz` + `gzip_static` | 质量门神 |
| 14 | 🟡 | 反代 | `nginx-windows.conf:22-26` | Windows 官方 nginx 无 `upstream_keepalive` 模块 → 每请求新建 TCP 连接。低并发增量小（日志显示 `request_time≈upstream_response_time`），首屏 10-20 并发时 P95 受损 | 第三方构建 / 提升 `worker_connections`(1024→4096) | 产品官 |
| 15 | 🟡 | 死配置 | `.env`、`log_config.json`、`NGINX_PROXY` | `log_config.json` 从未被加载（无 `--log-config`、全仓无 `dictConfig`）；`NGINX_PROXY` 全仓无引用；`DB_POOL_SIZE/MAX_OVERFLOW` 代码不读 | 删除或明确标注"不生效" | 排障手 |
| 16 | 🟠 | 安全 | `.env:7-9,26` | **明文凭据入库**：`DB_PASSWORD`、`SECRET_KEY`、`REDIS_PASSWORD` 以明文写在 `.env`（`.env.development` 注释自称已 gitignore，需核实 `.env` 是否同样受保护） | 轮换凭据 + 迁移到密钥管理；核对 `.gitignore` 覆盖 | 主理人 |
| 17 | 🟢 | 一致性 | `main.py:388-398` vs `nginx-windows.conf:90-96` | `/static/uploads` 双挂载点（Nginx `alias` 到 `static/uploads`，FastAPI 挂 `fastapi_app/static/uploads`），目录内容 6 vs 3 不一致 | 删除 FastAPI 侧重复挂载 | 产品官 |
| 18 | 🔴 | 安全（待确认） | `logs/nginx-access.log:14788` | **疑似内网穿透暴露**：访问日志出现来源标注为 `https://frp-fun.com:30001/` 的请求。若存在 frp 隧道映射，则本 ERP 可能已被暴露到公网。**本项为性能排查附带线索，未经安全审计，不可直接当定论** | 立即确认该映射是否为有意配置；非有意则下线隧道并轮换会话/凭据；建议单独发起一次安全审计 | 质量门神（提出）· 主理人（复核标注） |

---

## 3. 关键机制：为什么「production 比 debug 慢」

> 这是本次排查最有价值的分析 —— 现象本身是强诊断信号。

**前提澄清**：本项目 debug 与 production **不是 DEBUG 开关**，而是两套拓扑：

| 维度 | "Debug 模式" | "Production 模式" |
|---|---|---|
| 后端 | 单进程 + `--reload` | 8 worker + `httptools`（无 reload） |
| 前端 | Vite dev server（HMR，按需转译源码） | Nginx 托管 `dist` 预构建产物 |
| 数据路径 | **前端直连 5002**（无 Nginx 一跳） | 经 Nginx 反代（Windows 版每请求新建连接） |
| 应用级 GZip | **开启** | **关闭**（让给 Nginx） |
| CSRF | 内网 IP 豁免，零成本 | 全量校验 |
| PWA | **禁用** | **开启**（SW 接管 API） |
| L1 缓存 | 单进程，命中率 ~100% | 8 进程各自独立，命中率 ~12% |
| 健康探针 | 不存在 | 存在，且会误杀重启 |

### 机制清单（按解释力排序）

| 机制 | 解释力 | 置信度 | 证据 |
|---|---|---|---|
| **M11 健康探针误杀 → 重启风暴** | ✅✅✅✅ 最强（间歇性卡死） | 很高（日志实证）；**根因已修正见 §3 末** | `logs/erp-prod.log` 8 次循环；前端探针假成功 `prod_runner.py:408-409` |
| **M1 PWA Service Worker 接管 API** | ✅✅✅ 稳定拖慢 | 高 | `vite.config.js:56,71`、`dist/sw.js` |
| **M4 8-worker L1 命中率暴跌** | ✅✅✅ 稳定拖慢 | 高 | `.env:159,169`、`cache.py` |
| **M2 静态资源 hash 撕裂 → 404 重下** | ✅✅✅ 间歇暴慢 | 很高（日志实证） | `logs/nginx-error.log` |
| **M3 大包 + 无 Brotli** | ✅✅ 拖慢首屏 | 高 | `dist/assets/` 体积实测 |
| M5 8 进程共写日志 | ✅✅ | 高（撕裂实证） | `logger.py:65-75` |
| M7 应用级 GZip 关闭 | ✅✅（本案因 Nginx 缺席而放大） | 高 | `middleware.py:319-324` |
| M8 无 upstream keepalive | ✅ 次要 | 高 | `nginx-windows.conf:22-26` |
| M6/M9/M10 CSP nonce / 反代跳数 / CSRF | ✅ 次要 | 中 | `middleware.py` |
| M12 连接池 worker 数三方错位 | ⚠️ 潜在 | 中 | `database.py`、`.env:161-169` |

### 🔑 关键裁决：前端到底跑的是 dev 还是 preview？（主理人裁定）

产品官与排障手在本点上给出了**冲突结论**，必须裁定，否则 P0 会派错：

| 成员 | 主张 | 依据 |
|---|---|---|
| 产品官 | "Debug = Vite dev server，Production = vite preview + 经 Nginx" | 发现 `start.py` 有 dev/preview 双分支 |
| 排障手 | "当前 3000 跑的是 dev server，**不是** preview" | 实测首页含 `/@vite/client` + `/src/main.ts` |

**主理人三次独立实测的裁定结论：以排障手为准 —— 3000 端口当前跑的是 Vite dev server（HMR），不是 preview。**

铁证三条：
1. `curl -s http://127.0.0.1:3000/index.html` 返回 HTML 含 `src="/@vite/client"` → **dev server 独有**（preview 不注入此脚本）
2. 返回 `src="/src/main.ts?t=1789605671097"` → **请求未构建的 TS 源码**（preview 只会引用 `/assets/index-*.js`）
3. `logs/server_manager_20260917.log` 含 **171 条 `hmr update`** → HMR 是 dev server 独有机制，preview 没有

**但产品官并未全错 —— 他揭示了一个更完整的事实**：项目存在**三条前端启动路径**，且**都不走 Nginx**：
- `server_manager_v533.py:1839` → `npm run dev`（= Vite **dev**）
- `start.py:110` → `npm run dev`（= Vite **dev**）
- `prod_runner.py:188-190` → `npx vite preview`（= **preview**，仅在检测不到 Nginx 时触发）

三条路径**全部由 Vite（dev 或 preview）直接服务前端**，**没有一条走 Nginx**（nginx 进程数实测 = 0）。只是当前命中 3000 端口的是其中的 dev 分支。

**修正后的准确表述**：用户所谓"production 模式"= **Vite 直接托管前端（当前为 dev server）**，而非"Nginx + 构建产物"。这**同时**支撑了两项 P0：
- **P0-1（托管拓扑错配）** —— 前端根本不在 Nginx 上
- **P0-4（gzip 真空）** —— 无论 dev 还是 preview，Vite 内建 HTTP 服务**都不做 gzip/brotli**；后端又因 `APP_ENV=production` 让出压缩 → **压缩真空在两条路径下都成立**

> 这也解释了项目里 `prod_runner.py:188-190` 那段"vite preview 回退"设计：作者本意是"Nginx 优先、缺失时降级到 preview"，但实际部署中 Nginx 从未被装上（或未被 `_find_nginx()` 检出），于是**静默降级**成了长期状态——而 `nginx-windows.conf` 里精心配置的 gzip/缓存头**全部成为废纸**。

### 补充发现（质量门神 + 主理人复核）

| # | 严重度 | 发现 | 证据 | 影响 |
|---|--------|------|------|------|
| S1 | 🔴 | **`FLASK_ENV=development` 是无效字段**（本项目为 FastAPI，全仓仅测试文件引用 1 次），但**长期误导排查方向**；同时 `APP_ENV=production` 才是真实判定依据 | `grep -rn "FLASK_ENV" --include="*.py"` → 仅 `tests/performance/test_performance.py:169` | 排障人员按 Flask 语义误判环境；产品官报告初稿即受此误导 |
| S2 | 🔴 | **静默降级无告警**：`prod_runner.py` 检测不到 Nginx 时只打一行 `INFO` 就回退 `vite preview` —— 生产环境的**前端托管层悄然失效**且无人知晓 | `prod_runner.py:217-221` | 运维以为"nginx 在生产"，实际从未生效 |
| S3 | 🟠 | **前端资源 404 不回流 index.html**（低风险，非全站白屏） | 实测单文件导航返回 200（preview 的 SPA fallback） | 影响面小于产品官初判，但 hash 撕裂仍会造成无效往返 |
| S4 | 🟡 | **ARQ worker 处于"外部"状态** —— `prod_runner.json` 中 `arq.status="external"` 且 `erp-arq` 服务 Stopped，异步任务（备份/报表导出）可能无声堆积 | `logs/prod_runner.json`、`temp/svc_erp.json` | 功能可用性风险，非性能问题 |

### 🔬 实证：gzip 真空已在线复现（本次排查最硬的证据）

> 排障手成员在排查中**实测**了这一项，主理人独立复现确认。

**测试**（生产环境当前运行态）：
```bash
curl -s -H "Accept-Encoding: gzip" -D - -o /dev/null http://127.0.0.1:5002/metrics
```

**实测响应**：
```
HTTP/1.1 200 OK
server: uvicorn
content-length: 18745                          ← 未压缩传输
content-type: text/plain; version=0.0.4; charset=utf-8
x-content-type-options: nosniff
                                    ← 注意：完全没有 content-encoding 头！
```

**量化损失**：
| 指标 | 数值 |
|------|------|
| 实际传输 | **18,745 字节** |
| gzip 后应为 | **2,554 字节** |
| 浪费比例 | **86.4%（7.3 倍）** |

**全站口径**（构建产物 185 个 JS/CSS 文件实测）：
| 指标 | 数值 |
|------|------|
| 原始总计 | **3487.3 KB** |
| gzip 后总计 | **1037.2 KB** |
| 节省 | **70%** |

**这证明了什么**：客户端明确声明支持 gzip，服务器**无动于衷**。这与 `middleware.py:319-324`「生产环境让出 gzip 给 Nginx」+「Nginx 进程数 = 0」的推断**完全吻合** —— **P0-4 不再是"隐患"或"推断"，而是已在线复现的事实。**

**放大影响面**：不只 `/metrics`。**所有 `/api/` JSON 响应**都被同一逻辑影响 —— 订单列表、库存查询、报表等大 JSON 接口，**每个请求都在多传 3-8 倍的数据**。这是"生产比 debug 慢"在**稳定态**下的主要贡献之一（debug 模式因为 `APP_ENV != production` 会正常注册 `GZipMiddleware`）。

**最直接的验证命令**（建议作为验收标准）：
```bash
# 任一 API 端点，看是否有 content-encoding: gzip
curl -s -H "Accept-Encoding: gzip" -D - -o /dev/null http://127.0.0.1:5002/api/v1/xxx | grep -i content-encoding
# 期望修好后输出：content-encoding: gzip
```

### ⚠️ 对 M11（重启风暴）根因的修正 —— 请优先读这一条

报告初稿沿用产品官结论，将重启风暴归因于「`HTTP_PROXY` 无 `NO_PROXY` 导致探针被代理劫持」。**经复核，该根因应分两半看，且真正的代码级漏洞在别处**：

| 环节 | 实际情况 | 证据 |
|------|---------|------|
| **后端探针**（`/api/health`） | ✅ 代理隐患**已修**：代码用 `_OPENER_DIRECT`（`ProxyHandler({})` 显式清空代理）直连，不再受系统代理影响 | `prod_runner.py:132-138`、注释 `:107-113` |
| **前端探针**（`/nginx-health`） | ❌ **根因在此**：`_FrontendNginx.alive()` 探测 `http://127.0.0.1:{web_port}/nginx-health`，期望 nginx 返回 `{"status":"ok"}`。但**当前 3000 端口是 Vite**，该路径被 SPA fallback 吞掉 → **返回 index.html 且状态码 200** → `_http_ok` 判定 `resp.status == 200` **通过** | `prod_runner.py:408-409` |

**这就是"假成功"缺陷的全部五层代码级证据**（主理人已逐行核实）：

| 层 | 位置 | 代码 | 缺陷 |
|---|------|------|------|
| 第 1 层 | `prod_runner.py:408-409` | `alive()` → `_http_ok(...)` | `_http_ok` 只看 `resp.status == 200`，**不校验响应体** → index.html 冒充 nginx-health 也能通过 |
| 第 2 层 | `prod_runner.py:400-406` | `for _ in range(10): if self.alive(): break` … **`self.status = "running"`** | **循环结束无条件置 running** —— 即使 10 次探测**全部失败**，也照样宣布"已启动"。没有 else 分支，没有告警 |
| 第 3 层 | `prod_runner.py:503-508` | `"status": (self.nginx.status if self.nginx else ...)` | 状态落盘**直接取用这个被无条件置位的 `running`** → `prod_runner.json` 谎报 `frontend_type=nginx, status=running` |
| 第 4 层 | `prod_runner.py:503-508` | `"pid": (self.vite.proc.pid if self.vite and self.vite.proc else None)` | **pid 只从 `self.vite` 取**，nginx 分支永远取不到 pid → 前端托管层即使"在跑"也**不可观测、不可管理**（想 kill 都不知道杀谁） |
| 第 5 层 | `logs/nginx-error.log:19` | `[emerg] 1796#19272: bind() to 0.0.0.0:3000 failed (10013: ...)` | **真相就在日志里，但没人读**。Nginx 确曾因端口被 Vite 占用而启动失败，错误安静躺在日志第 19 行，无任何监控或探针会去看它 |

> **第 5 层的可观测性缺口还有代码级佐证**：`prod_runner.py:394-399` 的 `subprocess.Popen(...)` **丢弃了返回的 handle**，且同时设了 `stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL` —— 进程既无法被 `wait()`，输出也被主动丢进黑洞，只留下 nginx 自己写的 `-e nginx-error.log`。**一旦没人主动读这个文件，失败就彻底不可见。**

**完整因果链（五层全断）**：
```
Nginx 启动失败（bind 3000 被 Vite 占用，10013）
  → Popen 丢弃 handle + stderr=DEVNULL，只写 nginx-error.log      ← 第 5 层：真相记录于此，无人读
  → _ensure_started() 探测 10 次全失败
  → 但仍无条件 self.status = "running"                             ← 第 2 层：无条件置位
  → print("前端 Nginx 已启动")                                     ← 假日志
  → alive() 探 /nginx-health 被 Vite 回 200 HTML
  → _http_ok 只看状态码 → 判定通过                                  ← 第 1 层：探针假阳性
  → prod_runner.json 谎报 running，且 pid=None                      ← 第 3/4 层：状态假 + 不可观测
  → 运维永远不知道前端托管层是假的，也无从接手
```

**这就是"声明与实况长期脱节"的根本机制** —— 它不是运维疏忽，而是**代码结构上不可能检测到失败**。五层防护（丢弃 handle + 无条件置位 + 假日志 + 探针假阳性 + pid 不可观测）全部失效。最讽刺的是：**系统确实记录了自己的失败，只是没有任何机制去读它。**

#### 端口 3000 的 10013 错误：已实测排除「Windows 保留端口段」嫌疑

QA 成员提出一个关键前置问题：若 3000 落在 Windows（Hyper-V/WSL/Docker）**排除端口区间**内，则"杀掉 Vite 进程"也救不了 Nginx，必须换端口并重启 `winnat` —— 那会把整件事误诊成 Nginx 配置错误。**主理人已实测证伪**：

| 检查 | 命令 | 结果 |
|------|------|------|
| 系统排除端口段 | `netsh int ipv4 show excludedportrange protocol=tcp` | 仅 **5357** 与 **50000-50059**；**3000 不在其中** |
| 3000 当前占用 | `netstat -ano \| grep :3000` | `TCP 0.0.0.0:3000 ... LISTENING 10640`（**能被正常绑定**） |
| Nginx 二进制 | 文件系统检查 | `C:/nginx/nginx.exe` **存在** |

**结论**：`10013` 是 Vite 占用 3000 时 Nginx 触发 `SO_EXCLUSIVEADDRUSE` 式的**瞬时地址冲突**（非保留段问题）。**修法是替换占用进程（把 3000 从 Vite 换给 Nginx），不需要改端口号，也不需要动 `winnat`。**

**因此**：

1. **`erp-prod.log` 里的重启风暴是后端探针引发的**（真实故障）；而后端探针的代理隐患代码已修 —— 说明那些重启**另有触发源**（需进一步定位，多半是 `--reload` 期间进程短暂不可达，或 worker 崩溃循环）。
2. **修复动作要改**：不能只加 `NO_PROXY` 就收工。**必须同时修三处**：
   ```python
   # ① 探针校验响应体（拒绝 index.html 冒充）
   # prod_runner.py::_FrontendNginx.alive() —— 建议改为校验响应体
   def alive(self) -> bool:
       try:
           with _OPENER_DIRECT.open(f"http://127.0.0.1:{self.web_port}/nginx-health", timeout=1.5) as resp:
               if resp.status != 200:
                   return False
               body = resp.read(200).decode("utf-8", "ignore")
               return '"service":"nginx"' in body      # 关键：拒绝 index.html 冒充
       except Exception:
           return False

   # ② 启动探测失败时必须告警，禁止无条件置 running
   # prod_runner.py::_ensure_started()
   for _ in range(10):
       if self.alive():
           break
       time.sleep(0.5)
   else:
       self.status = "crashed"                          # ← 补上，不再无条件 running
       print("[prod_runner] ERROR: 前端 Nginx 启动失败，/nginx-health 探测 10 次均未通过")
   if self.alive():
       self.status = "running"
       self.delay = 5.0
       print(f"[prod_runner] 前端 Nginx 已启动 (port {self.web_port})")
   ```
3. 这一条比原 P0-2 更根本 —— **没有它，即使修好了拓扑，下次 Nginx 挂掉依然无人知晓**。

### 已明确排除（不要再排查这些方向）

| 怀疑项 | 实测结论 |
|---|---|
| 生产跑 `--reload` | 生产路径**没有**；但当前实际运行的那个**有** |
| 单进程同步阻塞 | 否，生产配置 8 worker + `httptools` |
| `SQL_ECHO` 开着 | 否，`echo=False` |
| 日志级别 DEBUG | 否，实际 INFO |
| `pool_pre_ping` 未启用 | 已启用 |
| 登录 N+1 / 密码哈希过慢 | 无 N+1；Argon2id + `run_in_threadpool` 不阻塞 |
| JWT 慢 | 否，ES256 单次签名 ~0.2ms |
| 每请求全量缓存失效 | 无，仅针对性 `invalidate_cache('orders:p*')` |
| Source Map 未关闭 | **已关闭**，`dist` 内 0 个 `.map` |
| Sentry 全量 trace | 未启用（无 `SENTRY_DSN`） |
| `NGINX_PROXY=0` 导致绕过 Nginx | 误解，该变量全仓**无引用**，是误导项 |
| Flask `werkzeug` 慢哈希 | 不适用，本项目是 FastAPI + ES256 |

---

## 4. 优化路线图（含优化前/后预期效果）

> **前置铁律：先测基线，再动手。** 没有基线无法区分"真优化"与"网络抖动"。

### P0 —— 立即修复（阻断性 / 高危）

| # | 问题 | 改法 | 优化前 → 优化后（预期） | 验证方法 |
|---|------|------|----------------------|---------|
| **P0-1** | 托管拓扑错配：生产实为 dev 启动器 | 明确走 `nssm start erp-prod`（prod_runner + Nginx + dist + 8 worker）；保留 GUI 启动器则须把 `--reload` 换成 `--workers N --http httptools`、`npm run dev` 换为托管 `dist`。**前置已实测：3000 不在 Windows 排除端口段内（仅 5357、50000-50059），无需改端口、无需重启 `winnat`** | 前端从"按需转译源码"→"预打包+压缩+长缓存"；首屏与切页显著改善（**用户感受的主体**） | `curl -s :3000/ \| grep -c "@vite/client"` 期望 **0**；`Get-Process nginx` 期望 ≥1；`curl -sI :3000/` 期望 `server: nginx` |
| **P0-2** | 健康探针误杀 → 重启风暴（**注意：根因已修正，见 §3 末"对 M11 根因的修正"**） | ① 修复 `_FrontendNginx.alive()` 让其**校验响应体**（拒绝 index.html 冒充 nginx-health）；② 补 `_ensure_started()` 的失败分支（探测全败须置 `crashed` 并告警，**禁止无条件置 `running`**）；③ pid 应从 nginx 侧取，避免前端托管层不可观测；④ 注入 `NO_PROXY=127.0.0.1,localhost,::1`；⑤ 另行定位后端重启真实触发源 | 探针不再"假成功"；重启风暴 → **0**；可用性从"每日数十次中断"→"持续在线"；Nginx 挂掉能被立刻发现 | 观察 `logs/erp-prod.log` 30 分钟内不再出现"健康检查持续失败，强制重启进程树"；`curl -s :3000/nginx-health` 在 Vite 托管时应**不再**返回 200 |
| **P0-3** | PWA Service Worker 接管 API（数据陈旧 + 请求翻倍） | 从 `workbox.runtimeCaching` 移除所有 `/api/` 条目，加 `navigateFallbackDenylist:[/^\/api\//, /^\/ws\//]` | 首屏 12 个 API 场景：请求数 **~24 → ~12**；消除 1.5s 超时等待；首屏 API 完成时间**降 ~40-50%**；消除 1-2 分钟数据陈旧 | DevTools → Network 确认 API 请求 Source **不是** `(ServiceWorker)` |
| **P0-4** | gzip 真空（后端让出 + Nginx 缺席） | 把 gzip 归属改为"检测 Nginx 实际存活"而非仅看 `APP_ENV`；或确保 Nginx 运行 | **全站 185 个 JS/CSS：3487KB → gzip 1037KB（省 70%）**；首屏关键路径 **447KB → 145KB（-67%）**；API JSON 实测 **86.4% 浪费** | `curl -H "Accept-Encoding: gzip" -D - -o /dev/null <asset> \| grep -i content-encoding` |

### P0-B —— 强烈建议同批修复

| # | 问题 | 改法 | 优化前 → 优化后 |
|---|------|------|----------------|
| P0-5 | 静态资源 hash 撕裂 404 | 原子目录切换部署：`build → dist.new → 切换 → nginx -s reload` | 消除每次导航 ~250KB 无效往返 + 重试 |
| P0-6 | `.env` / `.env.production` 双份且后者无效 | 二选一：让 `.env.production` 真正生效（注入真实密钥），或删除以免误导 | 消除"排查走错方向"的团队成本（本次已实际发生） |
| P0-7 | `vite.config.js` 覆盖 `.ts` | 删除 `vite.config.js` + `vite.config.d.ts`，统一 `.ts` | 消除"改了 TS 配置却不生效"的静默陷阱 |

### P1 —— 显著收益（1-2 周）

| # | 问题 | 改法 | 预期效果 | 依据 |
|---|------|------|---------|------|
| P1-1 | 8-worker L1 命中率 ~12% | `CACHE_L1_BROADCAST_ENABLED=true` + 重启全部 worker | L1 命中率恢复至接近单 worker；**Redis 读请求量降 30-50%**（待基线确认） | `cache.py` + `.env:159,169` |
| P1-2 | 日志 IO 放大 8× + 行撕裂 | 每 worker 独立日志文件 / 统一 stdout；生产 INFO→WARNING；`[po-sku]` 逐行 INFO 改 debug 或聚合 | 写入量 **降 80%+**；请求密集时 **P95 降 5-15ms** | 单日日志曾达 6.85MB；实测 `[po-sku]` 105 行 |
| P1-3 | 大包 + 无 Brotli | 补齐 Brotli（带 brotli 的 Windows 构建 / 构建期预压缩）；PrimeVue 真按需、ECharts 走 `echarts/core`；`chunkSizeWarningLimit` 调低让 CI 暴露 | 主包 443KB → brotli ~105KB（**-76%**）；PrimeVue 672KB → 估 150-250KB（**-60~75%**）；**LCP 预计改善 200-500ms** | 体积实测 + brotli 相对 gzip 典型再降 15-20% |
| P1-4 | 反代无 keepalive | 第三方 nginx 构建 / 提升 `worker_connections` 1024→4096 | 低并发 <5ms；**首屏 10-20 并发 API 时 P95 改善 20-50ms** | 当前 `request_time≈upstream_response_time`，增量小 → 优先级不宜过高 |
| P1-5 | 连接池 worker 数三方错位 | 核对 NSSM `AppEnvironmentExtra` 与 `.env:169` 同值(8)；补 `pool_recycle`；放宽 `max_overflow` | 避免连接池饥饿与死连接抖动 | 8×(5+3)=64 < PG 100 ✓ |

### P2 —— 锦上添花（1 个月）

| # | 项 | 改法 | 预期 |
|---|---|---|---|
| P2-1 | 对象存储 | `STORAGE_TYPE=s3` + MinIO | 上传/下载不占本机 IO，可多机共享 |
| P2-2 | 统一 `/static/uploads` 挂载 | 删除 FastAPI 侧重复挂载 | 消除 404 不确定性 |
| P2-3 | 死配置清理 | 删除/标注 `log_config.json`、`NGINX_PROXY`、`DB_POOL_SIZE`、`FLASK_ENV` | 降低后续排障误判成本 |
| P2-4 | 凭据安全 | 轮换 `.env` 明文凭据，迁移至密钥管理；核对 `.gitignore` | 消除凭据泄露风险 |
| P2-5 | CDN / 边缘缓存 | 静态资源上 CDN | 跨网段用户首屏显著改善 |

---

## 5. 排查工具与命令手册

### 5.1 一键「模式自检」脚本（**已落地为可执行脚本** ✅）

> **本节的脚本已真正写好并实跑验证过**，不再是纸面建议：
> **`deliverables/gstack/perf-selfcheck.ps1`**（Windows PowerShell 5.1，严格只读）

```powershell
# 在项目根目录执行
powershell -ExecutionPolicy Bypass -File .\deliverables\gstack\perf-selfcheck.ps1
# 自定义端口 / 指定落盘
powershell -ExecutionPolicy Bypass -File .\deliverables\gstack\perf-selfcheck.ps1 -WebPort 3000 -ApiPort 5002 -OutFile .\baseline.log
```

**它检查 6 组共 15 项**，逐项输出 `PASS / FAIL / WARN`，并在结尾给出**综合判定**（开发栈 / 生产栈 / 混合降级态）：

| 组 | 检查内容 |
|---|---|
| 1 端口归属 | 3000 / 5002 的监听 PID + 进程名 |
| 2 前端模式 | `@vite/client` 注入、`/src/main.ts` 直出、`Server` 头、index.html 缓存策略 |
| 3 托管层 | nginx 进程数、`erp-prod/arq/redis/redis-broker` 四个 NSSM 服务状态 |
| 4 传输压缩 | API 与静态资源的 `Content-Encoding`，**并本地估算 gzip 后体积、量化浪费比例** |
| 5 端口保留 | `netsh excludedportrange` 判定 3000 是否落在排除区间（10013 排查） |
| 6 日志信号 | 强制重启次数、`nginx-error.log` 的 `[emerg]`、静态资源 404、今日 `--reload` 次数 |

**当前基线（2026-09-17 09:08 实跑，已存为 `baseline-before-2026-09-17-0908.log`）**：
`FAIL 7 项 / WARN 5 项` → 判定【开发栈】。

⚠️ 脚本自身的两个坑（已修，改脚本时注意）：
- PowerShell 的 `$Pid` 是**自动变量**（当前进程 ID），自定义参数绝不能叫 `$Pid` —— 会静默返回空进程名。已改名 `$ProcId`。
- 压缩探测**不能挑小响应**：`GZipMiddleware` 默认 `minimum_size=1000`，`/api/health` 只回 39 字节，按设计就不压缩，测了会误判成"没开 gzip"。脚本已改为优先探测大响应端点并自动跳过 <1KB 的。

以下为等价的手工命令版（供 Linux/Git Bash 环境或不想装脚本时用）：

```bash
#!/usr/bin/env bash
echo "== 5002/3000 归属 =="
netstat -ano | grep -E ":3002|:5002|:3000"

echo "== 前端是 dev 还是 dist（>0 即 dev） =="
curl -s http://127.0.0.1:3000/ | grep -c "@vite/client"     # 期望 0

echo "== 3000 server 头（nginx / Vite） =="
curl -s -I http://127.0.0.1:3000/ | grep -i "^server:"

echo "== 今日 reload 次数 =="
grep -c "Reloading\.\.\." logs/server_manager_$(date +%Y%m%d).log 2>/dev/null

echo "== 今日后端强制重启次数（期望 0） =="
grep -c "健康检查持续失败，强制重启进程树" logs/erp-prod.log 2>/dev/null

echo "== gzip 是否生效 =="
curl -s -H "Accept-Encoding: gzip" -D - -o /dev/null \
  http://127.0.0.1:3000/assets/index-Cb7_V1ei.js \
  | grep -i "content-encoding" || echo "NO GZIP"

echo "== 静态资源 404（期望 0 增长） =="
grep -c "CreateFile.*failed" logs/nginx-error.log 2>/dev/null
```

### 5.2 进程与端口

```powershell
# 谁在监听关键端口
Get-NetTCPConnection -State Listen |
  Where-Object LocalPort -in 5002,3000,6379,6380 |
  Select-Object LocalAddress,LocalPort,OwningProcess

# 由 PID 反查进程名与父进程（判断是否 GUI 拉起 / 多 worker）
Get-CimInstance Win32_Process |
  Where-Object { $_.ProcessId -in 17264,18348,10640 } |
  Select-Object ProcessId,ParentProcessId,Name,CommandLine | Format-List

# 数 worker / nginx
Get-Process python,nginx -ErrorAction SilentlyContinue |
  Select-Object Id,ProcessName,@{n='MemMB';e={[math]::Round($_.WorkingSet64/1MB,1)}}
```

```bash
# Git Bash 版
netstat -ano | grep -E ":5002|:3000|:6379|:6380"
tasklist | grep -i nginx    # 期望 ≥1，当前为 0
```

### 5.3 服务状态（NSSM / SCM）

```powershell
Get-Service erp-prod,erp-arq,erp-redis,erp-redis-broker | Select Name,Status
nssm start erp-prod      # 或 sc start erp-prod
```
> ⚠️ 不要直接 kill NSSM 受管进程（会被自动重拉，形成重启循环）。

### 5.4 浏览器端排查（DevTools）

| 面板 | 看什么 | 判定 |
|------|--------|------|
| **Network** | `Disable cache` + 硬刷新；看 `Content-Encoding` | 无 `gzip`/`br` → 压缩未生效 |
| **Network → Source 列** | API 请求是否来自 `(ServiceWorker)` | 是 → PWA 在拦 API（P0-3） |
| **Network → 瀑布图** | 首屏关键路径总字节数 | 447KB（未压缩）vs 145KB（gzip） |
| **Application → Service Workers** | SW 是否注册、scope | scope `/` → 接管全站 |
| **Performance** | LCP / FCP / TTI，主线程长任务 | 对比优化前后 |
| **Lighthouse** | 整体评分 + 优化建议 | 基线与回归对照 |

```js
// Console 一键导出所有资源加载耗时（按耗时排序）
performance.getEntriesByType('resource')
  .map(r => ({ name: r.name.split('/').pop(), ms: Math.round(r.duration),
               kb: Math.round((r.transferSize||0)/1024),
               enc: r.encodedBodySize, dec: r.decodedBodySize }))
  .sort((a,b) => b.ms - a.ms).slice(0,20).forEach(r => console.log(r));

// 验证压缩：transferSize 远小于 decodedBodySize 说明压缩生效
```

### 5.5 服务器端 HTTP 计时

```bash
# 连接/首字节/总耗时拆分 + 压缩验证
curl -o /dev/null -s -w "dns=%{time_namelookup} conn=%{time_connect} ttfb=%{time_starttransfer} total=%{time_total} size=%{size_download}\n" \
  http://127.0.0.1:5002/api/v1/aux/health

# 对比直连后端 vs 经前端代理（关键！）
curl -o /dev/null -w "direct  %{time_total}s\n" http://127.0.0.1:5002/api/health
curl -o /dev/null -w "proxied %{time_total}s\n" http://127.0.0.1:3000/api/health

# 验证 gzip/brotli
curl -s -H "Accept-Encoding: br,gzip" -D - -o /dev/null \
  http://127.0.0.1:3000/assets/index-Cb7_V1ei.js | grep -i "content-encoding"
```

### 5.6 日志分析

```bash
# 是否开 --reload（WatchFiles/Reloading 只可能来自 reload）
grep -c "Reloading\.\.\."        logs/server_manager_$(date +%Y%m%d).log
grep    "WatchFiles detected"    logs/server_manager_$(date +%Y%m%d).log | tail -5

# 重启频率（冷启动次数）
grep -c "Started parent process" "logs/后端(uvicorn).out.log"

# 启动模式判定
grep -E "GZip 压缩由|CSP 模式|连接池预热完成" logs/server_manager_$(date +%Y%m%d).log | tail -10

# 5xx / 超时 / 慢查询（应用内已有 0.2s OLTP 慢查询监听）
grep -E '"status": 5[0-9][0-9]'  logs/fastapi_$(date +%Y%m%d).log | tail -20
grep -i "slow\|慢查询\|timeout\|连接池" logs/fastapi_$(date +%Y%m%d).log | tail -20

# 前端资源 404
grep -c "CreateFile.*failed" logs/nginx-error.log
```

### 5.7 数据库侧

```sql
-- 当前活跃连接（判断是否触顶 PG max_connections=100）
SELECT count(*), state, wait_event_type
FROM pg_stat_activity WHERE datname='erp_system' GROUP BY 2,3;

-- 正在跑的慢 SQL（>1s）
SELECT pid, now()-query_start AS dur, state, left(query,120)
FROM pg_stat_activity
WHERE datname='erp_system' AND now()-query_start > interval '1 second'
ORDER BY dur DESC;
```

### 5.8 Python 侧火焰图（可选）

```bash
pip install py-spy psutil
py-spy record -o deliverables/gstack/profile.svg --pid <worker_pid> --duration 30
py-spy top --pid <worker_pid>
```

---

## ✅ 行动清单

| # | 行动 | 负责方 | 紧急度 | 期望完成 |
|---|------|--------|--------|---------|
| 1 | **先补基线测量**：跑 `deliverables/gstack/perf-selfcheck.ps1` 存档（**已跑，见 `baseline-before-2026-09-17-0908.log`：FAIL 7 / WARN 5**）；另补后端 TTFB 20 次统计 + 浏览器首屏 LCP/FCP 硬刷新记录 | 全员 | **P0-0** | 立即 |
| 2 | **修复前端探针"假成功"（五层链需一并补）**：① `_FrontendNginx.alive()` 只校验 status 不校验 body，导致 Nginx 失效被静默吞掉；② `_ensure_started()` 探测全败仍无条件置 `running`；③ 前端 `pid` 仅从 `self.vite.proc.pid` 取值，nginx 分支永远为 `None`（不可观测）；④ `Popen` handle 被丢弃 + `stderr=DEVNULL`，仅剩 `nginx-error.log` 且无人读；⑤ 注入 `NO_PROXY=127.0.0.1,localhost,::1`。并**另需定位后端重启的真实触发源**（代理隐患代码已修，重启风暴另有来源） | 后端 + 运维 | P0 | 本周 |
| 3 | 明确托管拓扑：停用 GUI 开发启动器，改用 `erp-prod` NSSM 正式栈；验证 3000 返回 `server: nginx`。**已实测 3000 不在 Windows 排除端口段（仅 5357 / 50000-50059），替换进程即可，无需改端口或重启 `winnat`** | 运维 + 后端 | P0 | 本周 |
| 4 | 修复 gzip 归属逻辑：按"Nginx 实际存活"决定应用是否注册 `GZipMiddleware` | 后端 | P0 | 本周 |
| 5 | 移除 PWA `runtimeCaching` 中所有 `/api/` 条目，加 `navigateFallbackDenylist` | 前端 | P0 | 本周 |
| 6 | 改为原子目录切换部署，消除静态资源 hash 撕裂 404 | 运维 | P0 | 本周 |
| 7 | 收敛 `.env` / `.env.production` 双份配置；删除无效 `NGINX_PROXY` | 后端 | P0 | 本周 |
| 8 | 删除 `vite.config.js` + `vite.config.d.ts`，统一用 `.ts` | 前端 | P0 | 本周 |
| 9 | 修正生产 CORS，显式列出 LAN 源并放宽私有网段过滤 | 后端 | P1 | 2 周 |
| 10 | 置 `CACHE_L1_BROADCAST_ENABLED=true` 并重启全部 worker | 后端 | P1 | 2 周 |
| 11 | 日志治理：每 worker 独立文件 / 生产 INFO→WARNING / 去逐行 INFO | 后端 | P1 | 2 周 |
| 12 | 前端体积优化：Brotli 补齐 + PrimeVue/ECharts 真按需 | 前端 | P1 | 2 周 |
| 13 | 轮换 `.env` 明文凭据并核对 `.gitignore` 覆盖 | 安全 + 运维 | P1 | 2 周 |
| 14 | **消除静默降级**：`prod_runner` 检测不到 Nginx 时应 **WARN/FAIL** 而非只打 INFO 就回退 preview | 后端 | P0 | 本周 |
| 15 | 统一 `/static/uploads` 挂载点，清理死配置（`FLASK_ENV`/`NGINX_PROXY`/`log_config.json`） | 后端 | P2 | 1 月 |
| 16 | 排查 ARQ worker 为何处于 `external`/Stopped，确认异步任务未无声堆积 | 后端 | P1 | 2 周 |
| 17 | **核实 nginx 访问日志中的外部来源 IP**：`logs/nginx-access.log` 出现来源标注为 `https://frp-fun.com:30001/` 的请求（第 14788 行附近）。若确实存在 frp 内网穿透映射，则本服务可能已被暴露到公网 —— 需确认该映射是否为有意配置；若非有意，**应视为待评估的安全事件并立即下线隧道**，同时轮换会话/凭据 | 安全 + 运维 | **P0（待确认）** | 立即确认 |

---

## ⚠️ 待完善 / 已知局限

1. **本报告的"production 更慢"结论基于日志与配置的静态取证**。要**严格证明**，须先 `nssm start erp-prod` 启正式栈，再做同条件 A/B 压测（同客户端、同数据量、同并发）。
2. **未执行任何写操作或服务重启** —— 全程只读取证，当前运行状态未被改变。
3. **量化收益均为估算**，依据已逐项标注。真实收益必须以 §5.1 自检脚本的**基线对照**为准。
4. **`logs/prod_runner.json` 是陈旧快照**，不可作为"当前在跑生产"的证据。
5. 历史压测数据 `scripts/performance_report.json`（2026-04-20）显示 **100 并发下成功率仅 1.77%、p99=25.7s**，该数据采集于 5 个月前且未说明环境，**不宜直接引用为当前基线**，但提示压测能力需重建。
6. **`.env.development` 与 `.env` 中含明文凭据**。若 `.env` 未被 `.gitignore` 覆盖，应立即处置 —— 此项需人工核实 git 历史。
7. 未覆盖：Windows 磁盘 IO 特性（Defender 实时扫描对大目录构建的影响）、局域网交换机/网卡协商速率、客户端设备差异 —— 这些在真实环境可能贡献额外延迟。
8. **安全项未经完整审计**：本报告为性能排查，未做 OWASP/STRIDE 全量安全审计。行动清单第 17 条（`frp-fun.com:30001` 来源）仅为**线索提示**，未经安全官正式核验，不宜直接作为定论；如需，应单独发起一次安全审计。
9. **假成功缺陷的修复代码仅为主理人建议草案**，未经提交或测试，请由工程负责人复核后再落地。

---

## 📚 成员产出索引

- **排障手（investigator-perf）** 原始产出：`deliverables/gstack/_raw-investigator-backend.md`（569 行，含 12 组证据链、后端优化清单、服务器端命令手册）
- **产品官（product-perf）** 原始产出：`deliverables/gstack/_raw-product-review.md`（541 行，含 12 条机制剖析、17 项风险清单、P0/P1/P2 路线图、验证回归清单）
- **质量门神（qa-perf）** 原始产出：`deliverables/gstack/_raw-qa-frontend.md`（894 行，含构建产物体积分析、Nginx 双配置差异、浏览器端排查手册、三条启动路径梳理）
- **主理人独立复核**：首屏关键路径压缩实测（447KB→145KB）、nginx 进程数=0、`vite.config.js` 覆盖 `.ts` 确认、dev vs preview 冲突裁定、`FLASK_ENV` 无效性验证

### 成员结论冲突及裁定记录

| 争点 | 产品官 | 排障手 | 主理人裁定 | 裁定依据 |
|------|--------|--------|-----------|---------|
| 3000 端口跑 dev 还是 preview | preview + Nginx | dev server | **dev server**（但产品官揭示"三条路径都不走 Nginx"同样成立） | `/@vite/client` 注入 + `/src/main.ts` 引用 + 171 条 `hmr update` 三重实证 |
| 是否走 Nginx | 是（Nginx 反代） | 否（nginx 进程 0） | **否** | `tasklist \| grep nginx` = 0 |
| `10013` 是否因 Windows 保留端口段 | — | 提出需先查排除段（否则杀进程无效） | **不是保留段问题** | `netsh int ipv4 show excludedportrange protocol=tcp` 仅 5357 与 50000-50059；3000 当前 LISTENING |

---

> 本报告由软件工坊 AI 协作生成，关键决策请由工程负责人复核。
> 最重要的一条：**先启动正确的生产栈并测基线，再谈优化** —— 否则所有优化都在优化一套没在运行的系统。
