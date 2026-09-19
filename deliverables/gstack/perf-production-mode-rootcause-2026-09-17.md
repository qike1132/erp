# 滨发 ERP ·「生产模式加载变慢」根因排查与优化清单

**排查日期**：2026-09-17
**被排查系统**：滨发 ERP（本机 192.168.0.95 兼生产机与开发机）
**生产形态**：NSSM 服务 `erp-prod` → `fastapi_app/core/prod_runner.py` → uvicorn(:5002) + ARQ + nginx(:3000 服务 `frontend-vite/dist`)
**结论状态**：根因已定位并取证；代码层修复 D1–D7 已落地待验收；运维层动作待人工执行

---

## 0. TL;DR

**用户的前提需要修正：不是"生产模式慢"，而是三件不同的事被混成了一件。**

1. **排查起点时（09:17），生产模式根本没在运行** —— `:3000` 上是 Vite **dev server**（首页直出 `/@vite/client` 与 `/src/main.ts`），`:5002` 上是带 `--reload` 的单 worker **dev 后端**，nginx 进程数为 **0**，而 `logs/prod_runner.json` 却宣称 `mode=production, frontend_type=nginx, status=running`。用户拿"dev 栈"当了生产模式。
2. **"debug 比 production 快"这个直觉是反的**。同机同后端实测：prod 栈首屏 `load` **222 ms**、JS 传输 **520 KB**；dev 栈 `load` **394 ms**、JS 传输 **7894 KB**（**15.2 倍**）、模块级请求 **129 条**。dev 栈**更慢**。
3. **生产模式确实存在真实劣化，但成因不是压缩/CDN/Source Map 这些常见项**，而是**生产栈周期性自伤**：健康探针误判 → 强制重启整个后端进程树（累计 **366 次**）→ 每次都是一个全站 5xx 窗口（access log 精确统计：**23×502 / 34×500 / 47×499 / 8×503**，共 112 条）。用户感知的"加载慢、登录卡、切页面卡"来自这些窗口。

**已排出（不必再查）**：gzip 失效、CDN、Source Map、N+1、日志写盘、密码哈希、Sentry、8 worker 的 L1 缓存不广播。
**本轮额外发现**：PWA Service Worker 缓存 API 会返回**陈旧业务数据**（一致性问题，非性能问题，`dist/sw.js` 实测含 `StaleWhileRevalidate` + `NetworkFirst`）；另有一份"我曾误判 ARQ 未运行"的自我更正 —— **ARQ 实际健康**（`erp-arq` 服务 Running、子进程 pid 5080、日志持续写入），当时误判的原因是**提权/NSSM 派生进程的 `cmdline` 读不到**，详见 §11 第 11 条。

---

## 1. 现场快照（实测，非推断）

### 1.1 排查起点 09:17 —— 伪装成生产模式的 dev 栈

| 检查项 | 实测值 | 判定 |
|---|---|---|
| `:3000` 归属 | `node vite.js --host 0.0.0.0 --port 5173 --port 3000`（pid 10640） | **Vite dev server** |
| `:3000` 首页 | 注入了 `/@vite/client`，直出 `/src/main.ts` | **非构建产物** |
| `:5002` 归属 | `python -m uvicorn fastapi_app.main:app --port 5002 --reload --reload-dir fastapi_app`（pid 17264），**无 `--workers`** | **dev 单 worker** |
| nginx 进程 | **0 个** | 生产前端未运行 |
| `logs/prod_runner.json` | mtime `08:37:53`，宣称 `mode=production, workers=8, frontend_type=nginx, frontend.status="running"`；但 `pid=16576` **已死**、`frontend.pid=null` | **谎报** |
| `content-encoding: gzip`（`:5002/metrics`） | **缺失**（明文 18,745 B） | 全站零压缩 |
| Redis 6379 / 6380 | 均 LISTENING（`redis-server.exe`） | **正常**（已不是 2026-09-16 那次故障态） |

### 1.2 09:19 —— 系统自行切到了**真正**的生产栈

09:19:05 起，`erp-prod` 服务（State=Running, StartMode=Auto, PID=4792）拉起了新的 `prod_runner`（pid 18232，**父进程 = nssm.exe**），dev 的 vite/uvicorn 消失。09:19:38 复测：

| 检查项 | 实测值 | 判定 |
|---|---|---|
| `:3000` | 13 个 `nginx.exe`，响应头 `server: nginx`，`content-encoding: gzip` 生效，服务 `dist` 产物（etag `W/"6aaa8034-e95"`） | **真生产** |
| `:5002` | pid 9172（prod_runner 子进程），**无 `--reload`**，下辖 8 个 python worker | **生产后端** |
| `logs/nginx-error.log` | 09:19 无新增错误 | nginx 本次绑定成功 |
| `logs/prod_runner.json` | `frontend.pid` 仍是 `null`，`status` 恒 `"running"`（13 个 nginx 在跑） | **D3 缺陷现场可复现** |

> **重要**：本报告的所有"生产性能"数据均取自 1.2 这个真实生产态；所有"dev 性能"数据取自 §3 临时起的 5199 dev server。两者同机、同后端 `:5002`、同 Edge 内核。

> **关于 `arq: {pid: null, status: "external"}`**：这是**设计如此**，不是缺陷。ARQ 由独立的 NSSM 服务 `erp-arq` 托管（`prod_runner` 不代管），实测该服务 Running、子进程 pid 5080 存活、日志持续写入。**但请注意**：`pid: null` 会让"ARQ 是否在跑"看起来不可知 —— 这正是 D3 同类问题的另一个表现面（可观测性依赖 `pid` 而非真实探活）。

---

## 2. 用户问题 2 的字面答案：dev 与 prod 的差异实测

浏览器层 A/B（Playwright + 系统 Edge headless，各 3 次取中位数）：

| 指标 | PROD nginx `:3000` | DEV vite `:5199` | DEV/PROD |
|---|---|---|---|
| 文档 TTFB | **7.7 ms** | 33.1 ms | **4.3×** |
| DOMInteractive | 89.6 ms | 67.9 ms | 0.8× |
| DOMContentLoaded | 221 ms | 381 ms | **1.7×** |
| **load** | **222 ms** | **394 ms** | **1.8×** |
| 资源请求条数 | 28 | **136** | **4.9×** |
| 模块/源码级请求 | **0** | **129** | — |
| **JS 传输** | **520 KB** | **7894 KB** | **15.2×** |
| CSS 传输 | 13.4 KB | 0 KB | — |

**典型差异对照表（用户问题 2 的正式回答）**：

| 维度 | debug / dev 栈 | production / prod 栈 |
|---|---|---|
| 前端服务 | Vite dev server（按需编译、模块级 ESM） | nginx 静态托管 `dist` 构建产物 |
| 资源形态 | 129 个模块级请求、不压缩、不 minify | 28 个请求、已打包 minify、内容 hash |
| 压缩 | **应用层 gzip 启用**（`minimum_size=1000`） | **应用层 gzip 关闭，由 nginx 承担**（见 D5） |
| HTTP 缓存 | 无（dev 每次新鲜） | 静态资源长缓存 + `index.html` `no-cache` |
| Service Worker | **禁用**（`devOptions` 未开） | **启用**，接管 `/api/` 与 precache（见 D6） |
| 后端 | 单 worker + `--reload` | 8 worker、无 reload |
| API 缓存 | 单进程 L1 命中率高 | 8 个 worker 各自 L1（`.env:159 CACHE_L1_BROADCAST_ENABLED=false`） |
| 前端路由 chunk | 现场编译，**不存在 hash 失配** | 内容 hash，**构建换代会产生 chunk 404**（见 §4.4） |

结论：**在两端都正常运行时，production 明显快于 debug**（load 1.8 倍、JS 传输 15 倍）。用户观察到的"相反"现象，只能由**生产端自身故障**解释。

---

## 3. 生产模式服务端性能实测（真实鉴权请求）

用只读 GET + 真实 Bearer token（`_mint_token.py`）经 `:3000` 实测，25 次重复取分位：

| 端点 | TTFB p50 | TTFB p90 | >100ms 占比 | 明文体积 | gzip 后 | **节省** |
|---|---|---|---|---|---|---|
| `/api/v1/dashboard/stats` | 7 ms | 8 ms | 0% | 337 B | 337 B | 0%（低于 `gzip_min_length`） |
| `/api/v1/products/list?per_page=50` | 7 ms | 7 ms | 0% | 9,821 B | 1,604 B | **83.7%** |
| `/api/v1/stock/inventory?per_page=50` | 7 ms | 7 ms | 0% | 8,362 B | 1,234 B | **85.2%** |
| `/api/v1/purchase-center/orders?per_page=50` | 8 ms | 10 ms | 0% | **77,013 B** | **4,102 B** | **94.7%** |

- 响应头原始证据（经 nginx）：`Server: nginx` / `Transfer-Encoding: chunked` / `Vary: Accept-Encoding` / **`Content-Encoding: gzip`**
- 对照：**直连 `:5002` 不带 gzip**（`/metrics` 4,784 B 与明文一致）→ 压缩确实由 nginx 承担，应用层确实关着（D5）
- **Codel 结论：生产态的 HTTP/API 层是健康的，p50 = 7 ms，无冷路径抖动。**

---

## 4. 「生产比 debug 慢」的真实成因（按证据强度排序）

### 4.1 🔴 主因：健康探针误判 → 强制重启整个后端进程树（自我 DDoS）

**证据（`logs/erp-prod.log`）**
- `[prod_runner] 后端(uvicorn) 健康检查持续失败，强制重启进程树` —— **366 次**
- 失败原因：`健康检查失败(60s 内不重复记录): URLError: <urlopen error timed out>`
- 用户侧伤口（`logs/nginx-access.log`，**精确按 combined 日志第 4 字段统计，非子串匹配**）：**23×502 / 34×500 / 47×499 / 8×503**，共 **112** 条 5xx/499
  > ⚠️ **计数方法更正（2026-09-17 10:04）**：本报告早先版本写的是「17×502 / 8×503 / 33×499」，那是用 `" 502 "` 之类的**子串**匹配得到的，会把日志里的**响应体大小**（如 `"GET /assets/x.css" 200 503` 中的 `503`）误计为状态码，并且**完全漏掉了 `500` 这一类**（34 条，占比最大）。已按字段位重新精确统计，上表为更正后的准确值。
- nginx 侧（`logs/nginx-error.log`）：**18× `connect() failed`（上游拒连）**，聚集于 09/12 09:12、09/14 15:34、09/16 08:14、09/16 12:34；**11× `WSARecv() failed (10054)`**（`/ws/notifications` 被强制断开）

**成因（修复前源码）**
```python
132: def _http_ok(url, timeout=2.0)                                   # 探针超时仅 2 秒
349: threshold = self.start_grace if ... else 20.0                    # 「20s 窗口内有过失败」
350: if time.monotonic() - self.health_fail_start > threshold:
352:     self.kill_tree()                                              # 杀掉含 8 个 worker 的整棵树
```
而 `/api/health` 正常只要 **4–5 ms**（p50）。触发它的不是"后端挂了"，而是**后端偶尔忙/依赖抖动 → 探针 2s 超时 → 20s 后整树被杀 → 全站 502 十几到几十秒**。

**严重度校准（据实，勿放大）**：366 是累计值，**341 次集中在单一历史代**（第 3 代，疑与已被 `_OPENER_DIRECT` 修掉的 HTTP 代理问题同源）；第 4~11 代各仅 6 行（启动即重启的短循环）；**当前第 15 代（workers=8，09:17 起）强制重启 0 次**。但机制**潜伏且危险**，且今日仍有发生（第 12 代 4 次、第 13 代 17 次）。判定：**潜在高危、中等频次**。

### 4.2 🔴 主因（并列）：生产栈经常压根没在跑，且系统设计上无法发现

四层「假成功」链导致这是**结构性不可能被发现**的问题：

| 层 | 位置 | 缺陷 |
|---|---|---|
| 1 | `prod_runner.py:132` `_http_ok` | 只比状态码 → Vite 的 SPA fallback 返 200+HTML 也算"nginx 健康" |
| 2 | `_ensure_started` 探测循环后 | **无条件** `status = "running"`，10 次全败也宣布成功 |
| 3 | `write_status` | 直接取用被污染的状态 → `prod_runner.json` 谎报 |
| 4 | `Popen(stdout=DEVNULL, stderr=DEVNULL)` | 真相只躺在 `nginx-error.log` 里，**没有任何机制去读** |

第 4 层最要命：**系统确实记录了自己的失败，只是没人读**。

### 4.3 🟠 次要：应用层 gzip 被"环境名推断"关掉

`middleware.py:319-324` 因 `settings.is_production`（`.env:172 APP_ENV=production`）直接 `return`，注释写"由 Nginx 统一处理，避免双重压缩"。
- **nginx 在线时无实际损失**（实测 nginx 自己就压 proxied 响应，84–95% 节省，见 §3）
- **nginx 一缺席就是全站零压缩**（实测 `/metrics` 明文 18,745 B vs gzip 后约 2.5 KB）
- 「双重压缩」担忧本身不成立：nginx 对**已带 `Content-Encoding` 的**上游响应不会二次压缩

### 4.4 🟡 罕见：构建换代造成的路由 chunk 404（hash 撕裂）

11 条 `CreateFile() ... failed`，**全部是内容 hash 分片**，其中 6 条是路由级懒加载 chunk：

```
HubeiView-Q0Id88a-.js / HubeiView-CvR8KlHF.js
PurchaseView-tTfhKvfp.js / PurchaseView-BaC7GmN1.js / PurchaseView-CeMIzq0g.js   ← 三个不同 hash
OutsourceOrderView-CY9V7f_T.js / SupplierView-BUA99Ou7.js
DefaultLayout-BvAITJGN.css / HubeiSearchBar-zfCkT9Wa.js / HubeiRouteTabs-DqL0ldOb.js
CompletedOrdersPanel-Ci67qDLA.js
```
- 时间分布：**09/12 共 5 条、09/16 共 6 条**（09/16 那 6 条集中在同一秒的一个页面加载）→ **不是慢性问题**
- 当前 `dist` 自洽（`index.html` 引用的 6 个资源全部存在）；这些 hash 在保留的历史产物里也找不到（已轮转）
- 机制：长开着的 SPA 标签页 + 部署换代 → 旧 chunk 请求 404 → 路由切换卡住/失败。**dev 栈不存在此问题**（模块现场编译，无 hash）
- **影响规模小**：access log 里 404 共 130 条，其中 **108 条是 `/static/uploads/customer-sampling/...` 图片缺失**（功能性问题，与性能无关），chunk 404 仅 6 条

### 4.5 🟡 一次性：`[emerg] bind() to 0.0.0.0:3000 failed (10013)`

09/15 14:05:58 出现 1 次。`10013` = `WSAEACCES`（端口被系统保留），**不是端口占用**（占用会是 `10048`）。
实测当前 `netsh int ipv4 show excludedportrange protocol=tcp` 仅 `5357` 与 `50000-50059`，**3000 不在排除区间**，且 nginx 现已稳定绑定。**判定为一次性事件，不列为 P0**。

### 4.6 🟡 一致性风险（非性能）：PWA Service Worker 缓存 API

`dist/sw.js` 实测（12,724 B）含 `precacheAndRoute`（**191 条目，含 `index.html` 与 76 个路由 chunk**）+ 3 条 API 缓存路由。
- **但它不是变慢的原因** —— A/B 实测（SW 拦截 vs 启用）：`load` 反而 **快 38 ms**（181→143），JS 传输仅 +2.9 KB
- 真正的危害是**返回陈旧业务数据**（`StaleWhileRevalidate` 2 分钟窗口 / `NetworkFirst` 60 s 窗口）
- 且 dev 禁用、prod 启用 → 制造"两端表现不一致"（见 D6）

---

## 5. 已排除的假设（诚实列出，避免后人重走死路）

| 假设 | 证伪证据 |
|---|---|
| **8 worker + L1 缓存不广播 → TTFB 双峰卡顿**（我最初的假设） | 同端点重复 25 次：`dashboard/stats` p50=7 / p90=8 / max=87 ms；`purchase-center/orders` p50=8 / p90=10 ms；**>100ms 的调用数 = 0/25**。无双峰。**假设不成立** |
| gzip 未启用导致生产慢 | nginx 路径实测 **84–95% 节省**，`Content-Encoding: gzip` 存在 |
| Service Worker 拖慢首屏 | SW 启用反而 `load` **快 38 ms**（见 §4.6） |
| 端口 3000 被 WinNAT 永久保留 | `excludedportrange` 实测不含 3000；nginx 现稳定绑定 |
| Source Map / CDN / 日志写盘 / N+1 / 密码哈希 / Sentry | 本次无相关证据；上一轮已排除，本轮未发现反例 |
| 5173 端口上有残留 dev server | `:5199` 无监听；`:5173` 未在监听列表 |

**⚠️ 死路警告**：`/ws/notifications` 在 access log 里表现为 `request_time≈60s`（6153 条 `101` 状态），看起来像"大量慢请求"。**那是长连接 WebSocket 的存活时长，不是延迟**。把这些算进"慢请求"会得出完全错误的结论（43% 请求 >1s 的假象）。

---

## 6. 已落地的代码修复（D1–D7）

> 全部改动已落工作区，**尚未 commit**。验收状态见 §7。

| # | 文件 | 修复要点 |
|---|---|---|
| **D1** | `fastapi_app/core/prod_runner.py` | `_http_ok()` 新增 `expect_substr`；`_FrontendNginx.alive()` 要求响应体含 `"service":"nginx"`，杜绝 SPA fallback 假阳性。有界读取 `resp.read(8192)`；不传参数的既有调用方行为不变 |
| **D2** | 同上 | `_ensure_started()` 拆出 `_spawn()`；探测全败时置 `crashed` + 退避 + **dump `nginx-error.log` 尾部**（唯一能自我说明的通道）；成功才置 `running` |
| **D3** | 同上 | `_FrontendNginx.proc` 句柄 + `pid` property（`poll() is None` 才返回）；新增 `Supervisor._frontend_state()` 现探存活；落盘新增 `frontend_ok` 字段，**`ready` 原语义保持不变** |
| **D4** | 同上 | `Popen` 句柄保存；`stdout/stderr` 落 `logs/nginx-spawn.out.log`（不再 `DEVNULL`）；`_close_spawn_log()` 防句柄泄漏 |
| **D5** | `fastapi_app/core/middleware.py` | `_setup_gzip()` 不再按 `is_production` 推断，默认始终启用；改由显式 `APP_GZIP_DISABLED=true` 关闸 |
| **D6** | `frontend-vite/vite.config.ts` **+** `vite.config.js` | `/api/` 的三条缓存条目（`StaleWhileRevalidate` / 2×`NetworkFirst`）统一替换为 `/\/api\//i → NetworkOnly`；两文件同步改 |
| **D7** | `fastapi_app/core/prod_runner.py` | 抽出纯函数 `_should_restart(consecutive, window, proc_alive)`；**进程存活则绝不 `kill_tree()`**；触发条件 = 连续 ≥3 次 **且** 窗口 ≥90s **且** 进程已死；探针超时 2s→5s；阶梯退避 `(30,60,120,300)`；重启日志补可归因信息 |

**D7 顺带修掉的一个潜伏缺陷**：原 `next_start` 每轮被重置，导致已退出进程**永远不会被重启**（2026-09-12 实证：uvicorn master 死后 4 个孤儿 worker 顶着 `:5002` 服务数小时无人接管）。已用 `_mark_crashed()` 的「运行→崩溃跳变」判定 + `status=="crashed"` 防重复排期修掉。

---

## 7. 验收证据

> **验收总览**：质量门禁 **PASS**（基线未上调）｜工程师测试 23 项 + BOM 回归 28 项 + QA 独立测试 **39 项** = **90 项全绿**｜主理人独立复核 + **D1 真实 dev server 对抗性验证** 已完成｜**D6 已完成构建层验证**（`dist-new/sw.js` 策略正确）。**唯一未闭合项 = D6 的"部署"动作**（`QA_PASS: NO` 的唯一原因），其余 6 项源码级全部通过独立对抗性验证；**代码层无遗留缺陷**。

### 7.1 主理人独立核验（已完成）

| 项 | 方法 | 结果 |
|---|---|---|
| 语法编译 | `py_compile` 四个文件 | 全部 OK |
| 未定义名 | `ruff check --select F821,F823,F401` | **All checks passed** |
| D5 隐患 | 断言 `middleware.py` 已 `import os`（新引入 `os.getenv`） | ✅ 已导入（顶层 `import os`） |
| D6 双份一致性 | 两配置文件 api handler 逐项比对 | 一致；残留字样仅在**注释**中 |
| 工程师新增测试 | `pytest` 单文件 | `test_gzip_middleware.py` **2 passed**；`test_prod_runner_frontend_failure.py` **13 passed** |
| **D1 对抗性验证（确定性）** | 起冒牌服务，任意路径返 `200 + HTML` | 不带 `expect_substr` → `True`（**旧假阳性成功复现**）；带 → `False`（**被挡住**） |
| **D1 对抗性验证（真实性）** | 起真实 Vite dev server :5199 并预热 | 不带 → `True`；带 → `False`。**真实 SPA fallback 场景下假阳性被挡住** |
| **D1 无假阴性** | 对真实 nginx `:3000/nginx-health` 带 `expect_substr` | `True` ✅ 未把真 nginx 误判为不健康 |
| **D1 向后兼容** | `:5002/api/health` 不传 `expect_substr` | `True` ✅ 既有调用方语义不变 |
| **D7 真值表** | 穷举 `_should_restart` 关键组合 | 关键断言通过：**`proc_alive=True` 时无论失败多久都返回 `False`**（`_should_restart(50,3000,True) = False`）→ 366 次误杀的形态在逻辑层被阻断 |
| **D7 进程死亡路径** | 读 `poll()` 早期分支 + `_mark_crashed()` + 主循环 `maybe_restart()` | 进程已死 → 走早期分支 `_mark_crashed()` → 主循环安排重启。覆盖完整 |
| 生产未受扰动 | 全程 nginx 进程数 | **13 → 13**，`:3000`/`:5002` 始终 LISTENING |

> **关于 2 个"看似不通过"的边界用例**：我最初期望 `_should_restart(1, 5, False) == True` 与 `_should_restart(0, 0, False) == True`，实测均为 `False`。追查后确认**是我的期望值写错了**——进程已死的情况在 `poll()` 开头就被早期分支接管（`self.proc.poll() is not None` → `_mark_crashed()`），根本不会走到 `_should_restart`。按项目既有铁律：**断言错而非代码错 → 修断言，不改代码**。

### 7.2 工程师交付 + 主理人复核

工程师已交付并补做 D7。**以下每项均由主理人独立重跑/重读，未采信其自述**：

| 复核项 | 工程师自述 | 主理人实测 | 判定 |
|---|---|---|---|
| `quality_gate.py` | PASS（超长函数 53） | `OK 后端超长函数: 53 处（与基线一致）`，`[PASS] 无新增质量问题`，exit 0 | ✅ 一致 |
| 门禁自身自检 | 未提 | `scripts/_selftest_gate.py` **全部通过**（棘轮/假绿守卫/N+1 语义 12 项），exit 0 | ✅ 补测通过 |
| 新增测试 | 8 + 13 + 2 | `test_prod_runner_backend_restart.py` **8 passed**；`test_prod_runner_frontend_failure.py` **13 passed**；`test_gzip_middleware.py` **2 passed** | ✅ 一致 |
| BOM 回归 | 28 passed | `test_bom_role.py` **28 passed** | ✅ 一致 |
| `_http_ok` 默认超时 2.0→5.0 是否造成隐式漂移 | 称调用方都显式传参 | 全文件 3 处 `_http_ok` 出现：L132 定义、**L370 `timeout=5.0`**、**L571 `timeout=1.5`** → 两个调用点均显式传参，**默认值改动无隐式影响** | ✅ 确认 |
| `bom_service` 抽取是否机械等价 | 称 28 项测试过 + 逐行等价 | 逐行多重集比对：新函数体 48 实质行中，仅 3 行新 docstring + `return copied_count` 为新增，**其余逻辑行 100% 存在于原实现**；`copied_count += 1` 两侧各 **3** 次一致；调用点 **L599 `copied_count = _add_default_scope_items_to_role(...)` 正确接收返回值**（未出现计数归零回归）；`skipped_role_items` 统计（L604-608）完整保留 | ✅ 等价确认 |

**门禁裁定记录**：门禁曾报 `后端超长函数 54（基线 53）→ 新增 1 处`。经核实基线文件 mtime 停在 2026-09-15 21:37（提交 `3b923d3`）**未被动过**，故判定为**真新增**（`bom_service._copy_bom_into_role` 125 行）。按项目铁律「**先修增量、再谈基线**；禁止 `--update-baseline` 洗白」，**未改基线**，改为按职责拆出 `_add_default_scope_items_to_role`，门禁回到 PASS。基线仍为 `53`，**棘轮未被放宽**。

### 7.3 QA 独立回归（已完成）

QA 自写 `fastapi_app/tests/test_qa_prod_stack_regression.py`（**39 项独立断言，非照抄工程师测试**），系统 Python 单文件跑：**39 passed / 0 failed / 0 skipped**（3 项 live 用例真实执行，未跳过）。

| # | QA 判定 | 关键证据 |
|---|---|---|
| D1 | ✅ 已验证 | 自建 SPA-fallback 服务（200+HTML）：不传 `expect_substr` → **True**（旧误判复现）；传 → **False**；真 nginx `:3000/nginx-health` 带子串 → **True**（无假阴性）；`:5002/api/health` 不带 → **True**（向后兼容） |
| D2 | ✅ 已验证 | 打桩全败 → `status=crashed`、`next_start>0`、`delay=10.0`；成功 → `running`/`delay=5.0`；失败时 dump `nginx-error.log` 尾部 |
| D3 | ✅ 已验证 | 注入污染 `self.nginx.status="running"` → 落盘 `frontend.status≠running`、`pid=None`、`frontend_ok=False`；**`ready` 仍仅由后端决定**（前端 crashed + 后端 ready → `ready=True`），原语义未被破坏 |
| D4 | ✅ 已验证 | `_spawn` 保存 `self.proc`、生成 `logs/nginx-spawn.out.log`；Popen 抛错时打印错误（不静默） |
| D5 | ✅ 已验证 | 默认 >1KB → `content-encoding: gzip`；`APP_GZIP_DISABLED=true` → 不压缩；**`APP_ENV=production` → 仍压缩**（核心修复点）；<1000B 不压缩（设计）；已 `import os` |
| **D6** | ⚠️ **源码 ✅ / 线上未生效（severe）** | 见 §10：「构建产物未同步」 |
| D7 | ✅ 已验证 | 真值表 `proc_alive=True` 恒 `False`；**存活进程 100 轮 / 500s 窗口 → 0 次 kill**；探针期死亡 → 1 次 kill；入口即死走早期分支（符合设计）；`_mark_crashed` **幂等**；`maybe_restart` **不饥饿** |

**QA 主动做过的证伪尝试（含"未能证伪"）**：极大 `consecutive`(10⁶)/`window`(10⁹) 逼存活进程被 kill → **未能证伪**（恒不杀）；自建 SPA fallback 骗探针 → **未能证伪**（正确判否）；反向真 nginx 判真 → **未能证伪**；反复调 `_mark_crashed` 制造 `next_start` 重置 → **未能证伪**（幂等）；复现"3s 主循环下重启饥饿" → **未能证伪**。**成功证伪 D6 的"已上线"**。并**撤销了一个假阳性**：日志里 `GZip 压缩已被 APP_GZIP_DISABLED 显式关闭` 看似生产关闸，但同段含 `GET http://test/big`（pytest 残留）且 `.env` 无该变量 → 判为误报撤销。

**QA 结论：`QA_PASS: NO`** —— 唯一阻塞是 D6 未落到线上产物；其余 6 项源码级全部通过独立对抗性验证，**无源码算法缺陷**。

**环境副作用确认**：快照 before(09:31)/after(09:36)/final(09:38) 对比 —— 端口 3000/5002/6379/6380 全程 listening；**nginx.exe 13 → 13 → 13**；`prod_runner` pid 18232 与 prod uvicorn pid 9172 存活；临时进程（进程内线程 + 两个临时脚本 14784/20904）均已退出；全程未执行 `taskkill`/`nssm`/`sc`/`reg`。

### 7.4 D6 构建层验证（已完成，主理人独立复核）

为把 D6 从"源码已改"推进到"能被构建出来"，工程师在**暂存目录**完成了一次真实构建（**未触碰线上 `dist`**）：

```
步骤1  node node_modules/vue-tsc/bin/vue-tsc.js -b            → rc=0（增量 <1s）
步骤2  node node_modules/vite/bin/vite.js build --outDir dist-new
       ✓ built in 23.55s
       PWA v1.3.0 · mode generateSW · precache 191 entries (3636.00 KiB)
       files generated: dist-new/sw.js / dist-new/workbox-c121765f.js
```

**主理人独立复核结果（非采信工程师自述）**：

| 核验项 | 实测 |
|---|---|
| 线上 `dist` 是否被动过 | **否**。`dist/sw.js` mtime 仍为 `2026-09-16 19:40:43`（12,724 B）；`dist/` 目录 mtime `19:44:06` 未变。`dist-new` 为 `2026-09-17 09:40:27` 新建 |
| 线上 `dist/sw.js` 策略 | 仍含旧策略：`StaleWhileRevalidate=1`、`NetworkFirst=1`、`api-read-cache=1`、`api-cache=1`，三条 API `registerRoute` 原样 |
| `dist-new/sw.js` 策略 | **旧策略全部归零**（`StaleWhileRevalidate=0 / NetworkFirst=0 / api-read-cache=0 / api-cache=0`）；仅一条 `/\/api\//i, new s.NetworkOnly, "GET"`；fonts 两条 `CacheFirst` 保留；workbox 运行时 hash `2da51cb1 → c121765f`（证明运行时策略确已改变） |
| **双份陷阱实测** | 跑完 `vue-tsc -b`（它确实重写了 `vite.config.js`，mtime 09:39:02）后，`.ts` 与 `.js` 的 api 条目**仍完全等价** → **陷阱闭合，实测而非假设** |
| `dist-new/index.html` 自洽性 | 引用 6 个 `/assets/*`，**缺失 0** |
| 从线上取实际服务的 `sw.js` | 经 nginx `:3000` 取回仍是旧的 12,722 B（`StaleWhileRevalidate=1`）→ **D6 确未部署** |
| 生产是否被扰动 | nginx **13**；`:3000`/`:5002` listening；`prod_runner 18232`、prod uvicorn `9172` 均存活 |

**结论（D6 的精确状态）**：**配置层 ✅ 正确** · **`.ts`/`.js` 双份一致 ✅** · **构建层 ✅ 已验证能产出正确 `sw.js`** · **部署层 ❌ 未执行**（刻意留给用户决定发布时机，产物在 `frontend-vite/dist-new/`）。

---

## 8. 可执行优化清单（按优先级）

### P0 —— 立即（已修复，待验收与重启生效）

| # | 动作 | 预期效果 | 验证方式 |
|---|---|---|---|
| P0-1 | 重启 `erp-prod` 使 D1–D5/D7 生效 | 消除"探针抖动即杀整树"的全站 502 窗口；nginx 启动失败不再谎报成功 | 重启后跑 `perf-selfcheck.ps1` 对比 §1 基线 |
| P0-2 | 确认 `logs/prod_runner.json` 的 `frontend.pid` 不再是 `null`、新增 `frontend_ok` 存在 | 生产栈"到底跑没跑"变成可观测事实 | `python -c "import json;print(json.load(open('logs/prod_runner.json'))['frontend_ok'])"` |
| P0-3 | **部署 D6**：把已验证的 `frontend-vite/dist-new/` 切到 `dist`（项目自带 `scripts/swap-dist.mjs` 做原子切换） | 消除 Service Worker 返回陈旧业务数据（一致性风险） | `curl --noproxy '*' -s http://127.0.0.1:3000/sw.js \| grep -c StaleWhileRevalidate` → 应为 **0**（当前为 1） |

> **P0-3 部署注意（两个真实副作用）**
> ① **会触发 hash 换代**：新构建的 asset hash 全部变化（`workbox-2da51cb1 → c121765f` 等）。长开着的 SPA 标签页在切换路由时会请求已不存在的旧 chunk → **404**（即 §4.4 的 hash 撕裂）。建议**低峰期部署 + 通知用户刷新页面**。
> ② 项目已有 `frontend-vite/dist_prev_*` / `backups/frontend-dist-*` 的备份惯例，切换前留一份 `dist` 副本便于回滚。

### P1 —— 本周

| # | 动作 | 预期效果 | 验证方式 |
|---|---|---|---|
| P1-1 | ~~让 ARQ 定时任务跑起来~~ **已核实无问题，撤销此条** | — | `erp-arq` 服务 Running，子进程 pid 5080 存活，`logs/erp-arq.log` 持续写入；`prod_runner.json` 里 `arq.status="external"` 是**设计如此**（ARQ 由独立 NSSM 服务托管，不归 prod_runner 管） |
| P1-2 | `dist` 发布改为原子切换 + 通知客户端，消除换代期 chunk 404 | 长开标签页切路由不再 404 | 部署后查 `nginx-error.log` 无新增 `CreateFile() failed` |
| P1-3 | 修 `108` 条 `/static/uploads/customer-sampling/*` 图片 404 | 客户打样图片可正常显示 | access log 中该前缀 404 归零 |
| P1-4 | 处置 `logs/后端(uvicorn).out.log`（18.6 MB，文件名含中文括号）与 `server_manager_20260910.log`（40.2 MB） | 降低日志体积与文件名编码脆弱性 | 轮转阈值 50 MB 生效；建议改 ASCII 文件名 |

### P2 —— 择机

| # | 动作 | 预期效果 |
|---|---|---|
| P2-1 | `.env:159 CACHE_L1_BROADCAST_ENABLED=false` 与 8 worker 的组合重新评估（各 worker 各自 L1，跨进程失效不广播） | 一致性更可预期（**注意：实测未发现它造成 TTFB 抖动，勿按"性能"立项**） |
| P2-2 | ⚠️ `_FrontendNginx._kill_all()` 执行 `taskkill /F /T /IM nginx.exe` —— **会杀掉全机所有 nginx**。本机兼生产机，误触发即中断线上 | 收窄为按 PID/项目路径匹配 |
| P2-3 | `logs/api_error.log` 不存在、`prod_runner` 自身 stdout 无独立落盘文件 | 排障入口可读 |
| P2-4 | `.env` 含明文凭据 | 凭据外置 |

---

## 9. 排查命令手册

### 9.1 判定"到底是不是真生产"（四条硬判据，缺一不可）

```bash
# ① 前端必须是构建产物（预期 0）
curl --noproxy '*' -s http://127.0.0.1:3000/ | grep -c "@vite/client"

# ② 前端直出源码（预期 0）
curl --noproxy '*' -s http://127.0.0.1:3000/ | grep -c "/src/main.ts"

# ③ 必须有 Server: nginx（预期命中）
curl --noproxy '*' -sI http://127.0.0.1:3000/ | grep -i "^server:"

# ④ 必须有 content-encoding: gzip（预期命中；注意 <1KB 的响应按设计不压）
curl --noproxy '*' -sI -H "Accept-Encoding: gzip" \
  "http://127.0.0.1:3000/api/v1/products/list?page=1&per_page=50" | grep -i content-encoding
```

> **绝不要信 `logs/prod_runner.json` 的 `mode`/`status` 字段** —— 本轮已证明它会谎报。

### 9.2 后端形态（dev 还是 prod）

```python
import psutil
for c in psutil.net_connections(kind="tcp"):
    if c.status == psutil.CONN_LISTEN and c.laddr.port == 5002 and c.pid:
        print(psutil.Process(c.pid).cmdline())
# 含 --reload 且无 --workers = dev 单 worker
# 有 --workers N，且父链 nssm.exe → prod_runner → uvicorn = prod
```

### 9.3 服务与进程链（`sc`/`reg`/`wmic` 已被安全策略屏蔽，勿用）

```powershell
Get-CimInstance Win32_Service -Filter "Name='erp-prod'" |
  Select Name,State,StartMode,ProcessId,PathName
Get-CimInstance Win32_Process -Filter "ProcessId=<PID>" |
  Select Name,ParentProcessId,CommandLine
```

### 9.4 生产期自伤证据

```bash
grep -c "强制重启进程树" logs/erp-prod.log                 # 累计强制重启次数
grep "健康检查失败" logs/erp-prod.log | tail -20            # 失败原因（超时？代理？）
grep -E "connect\(\) failed|WSARecv|emerg" logs/nginx-error.log
# access log 状态码分布（注意 101 = WebSocket 升级，不是错误）
python -c "
import re,collections
t=open('logs/nginx-access.log',encoding='utf-8',errors='replace').read()
print(collections.Counter(re.findall(r'\" (\d{3}) ',t)))"
```

### 9.5 浏览器端（真实用户体验，绕开 curl 测不到的那层）

```python
from playwright.sync_api import sync_playwright
with sync_playwright() as pw:
    b = pw.chromium.launch(channel="msedge", headless=True)
    p = b.new_context().new_page()
    p.goto("http://127.0.0.1:3000/", wait_until="load")
    print(p.evaluate("""() => { const n=performance.getEntriesByType('navigation')[0];
        const r=performance.getEntriesByType('resource');
        return {ttfb:n.responseStart, dcl:n.domContentLoadedEventEnd, load:n.loadEventEnd,
                nRes:r.length, jsKB:r.filter(x=>/\\\\.js/.test(x.name))
                  .reduce((a,x)=>a+(x.transferSize||0),0)/1024,
                sw: !!navigator.serviceWorker.controller}; }"""))
```
> 沙箱有 HTTP 代理，`curl 127.0.0.1` 会走代理返 502 —— 必须 `--noproxy '*'`。Playwright 不走代理，可信。

---

## 10. 遗留与未完成

| 项 | 状态 | 说明 |
|---|---|---|
| 工程质量门禁 `quality_gate.py` | **✅ PASS** | 超长函数回到 53（与基线一致）；**基线未被上调**，棘轮保持。门禁自身自检 `_selftest_gate.py` 全过 |
| 工程师完整交付报告 | **✅ 已交付** | D1–D8 全部落地；新增测试 3 个文件共 23 项；BOM 回归 28 项 |
| 主理人独立复核 | **✅ 已完成** | 见 §7.1 / §7.2，含 D1 的**真实 dev server 对抗性验证**与 D7 真值表 |
| QA 独立回归（39 项对抗性复验） | **✅ 已完成，结论 `QA_PASS: NO`** | 见 §7.3。D1–D5/D7 全部通过；唯一阻塞 = D6 未落到线上产物 |
| **⚠️ D6 部署缺口（severe，本轮唯一未闭合项）** | **配置/构建已 ✅，部署未执行** | **源码配置正确**（`.ts`/`.js` 等价，且 `vue-tsc -b` 重写 `.js` 后仍等价 —— 实测）；**已构建验证**：`dist-new/sw.js` 旧策略全部归零、仅剩 `/\/api\//i → NetworkOnly`、fonts 缓存保留（见 §7.4）。但 **nginx root 仍指向 `frontend-vite/dist`，其 `sw.js`（mtime `2026-09-16 19:40:43`）仍是旧策略**，经 `:3000` 实测取回确认 → **线上 PWA 目前仍会返回陈旧业务数据**。这正是 QA `QA_PASS: NO` 的唯一原因。**剩余动作 = 部署**（用户决策项） |
| D1–D5/D7 尚未生效于线上 | **待重启** | 改动需重启 `erp-prod`（NSSM，需管理员）。**本报告所有结论均未通过重启生产服务验证** |
| 本次未做的验证 | — | ① 修复后的真实生产 A/B 基线（需先重启）② 8 worker 下 L1 缓存命中率的量化（未立项，因假设已被证伪）③ 客户打样图片 404 的上游成因 ④ `_kill_all()` 的全机 `taskkill /F /T /IM nginx.exe` 行为未改动（见 P2-2） |

---

## 11. 方法论与踩坑（给后续排查者）

1. **"服务状态"要交叉验证，不要只看状态文件。** `prod_runner.json` 会谎报；必须同时看进程存活（`psutil.pid_exists`）、端口归属、HTTP 响应头。本轮就是靠"文件宣称 production 而进程已死"破的局。
2. **`netstat | grep LISTENING` 判端口存活不可靠**，要发真实请求；反之 `curl` 又会被沙箱代理污染 → 一律 `--noproxy '*'`。
3. **curl 测不到浏览器层。** Service Worker、`precacheAndRoute`、路由 chunk 失配都只在浏览器里发生。必须用 Playwright + 系统 Edge。
4. **看 access log 的 `request_time` 前先看状态码。** `101`（WebSocket 升级）的 `request_time` 是连接存活时长，会被误算成海量慢请求。本轮差点被这个陷阱带偏。
5. **`10013` ≠ `10048`。** 前者是 `WSAEACCES`（端口被系统保留），后者才是端口占用。诊断方向完全不同。
6. **"同一个 URL 重复请求分位"是证伪"缓存类"假设的最快手段。** 25 次采样就能判定 p50/p90 是否存在双峰，比读代码猜快得多。
7. **看到 `nginx-error.log` 里 `CreateFile() ... failed`，先判断是不是内容 hash 分片**（`Name-XXXXXXXX.js`）。是的话，问题在"部署换代 + 长开客户端"，不在磁盘或权限。
8. **断言报错先证明是断言错还是代码错**，再决定改测试还是改代码。本轮 2 个"不通过"用例全是断言写错。
9. **本机兼生产机时，任何 `kill`/`taskkill`/`restart` 类验证都必须先确认爆炸半径** —— `_ensure_started()` 第一步就是 `taskkill /F /T /IM nginx.exe`，会杀掉线上 nginx。测试这类函数必须全程 mock。
10. **bash 环境在本沙箱间歇损坏**（`dirname`/`head`/`ls` 报 `command not found`）→ 禁用管道，改用 Python 脚本落盘再读；PowerShell 工具 stdout 可能被吞 → 同样落盘再读。
11. **提权/NSSM 派生进程的 `cmdline` 读不到（空字符串）** → `"xxx" in cmdline` 会静默失效，得出"进程不存在"的错误结论（本轮我据此误判过 ARQ 未运行）。正确姿势：查服务 State/ProcessId → 展开子进程链 → **交叉验证该服务自己的日志 mtime**。判"活"必须发真实请求或看日志写入。
12. **累计型指标（读全量历史日志的计数）重启后不会归零**，直接判 `>0` 会永久 FAIL 并掩盖真实变化。必须引入**增量基线棘轮**：只对「自基线起的新增」报警，且**只在无新增时才重设基线**（否则洗白新增）。改完必须做「篡改基线调小 → 应报新增」的对抗性自检 —— 否则只是把假红换成了假绿，而**假绿更危险**。

---

## 12. 部署记录（2026-09-17 09:49–09:55）

三个动作已全部完成，**每步都有实测证据**。

### 12.1 步骤 1：`erp-prod` 重启 —— 已完成，新代码已生效

`erp-prod` 服务于 **09:49:36** 完成一次重启（nssm pid 7808 → `prod_runner` pid 21308 → `uvicorn` pid 20792，启动 09:49:37；该次重启**非本报告作者发起**）。生效判据（均为**新代码独有**特征）：

| D-项 | 线上生效证据 |
|---|---|
| **D3** | `logs/prod_runner.json` 出现 **`"frontend_ok": true`**（旧代码**不写**该字段）且 **`services.frontend.pid: 21260`**（旧代码**恒为 `null`**）→ 新代码确已加载 |
| **D5** | 直连 `:5002/metrics` 由「无 `content-encoding`」变为 **`Content-Encoding: gzip`** ✅ |
| **D4** | `logs/nginx-spawn.out.log` **被创建**（0 B）—— 旧代码用 `DEVNULL`，该文件根本不会存在 ✅ |
| 后端 | `:5002` uvicorn 启动 09:49:37 **晚于**最新源码修改 09:30:06 |

### 12.2 步骤 2：D6 部署 —— 已完成（`dist-new` → `dist`）

用项目自带的**重命名交换**脚本执行；切换前**自行加了一层备份**（脚本第 43 行会 `rm` 掉旧 `dist`，不留回滚副本）：

```
① 前置校验：dist-new/sw.js = {SWR:0, NF:0, NO:1, api-read-cache:0, api-cache:0, fonts:1} ✅ 新策略
② 备份：dist → backups/frontend-dist-20260917-095034（192 文件，数量校验一致）
③ 切换：node scripts/swap-dist.mjs → rc=0「dist 已原子化替换完成」
④ 本地校验：dist/sw.js = {SWR:0, NF:0, NO:1, fonts:1}；index.html 引用 6 个 /assets/*，缺失 0
⑤ 经 nginx :3000 实测取回 /sw.js = 12,203 B，SWR=0 / NF=0 / NO=1 / api-cache=0
```

**线上 PWA 已不再缓存 `/api/`** → 陈旧业务数据风险解除。（回滚：把 `backups/frontend-dist-20260917-095034` 改回 `dist` 即可。）

### 12.3 步骤 3：巡检对比 —— FAIL 7 → **0**，WARN 5 → **1**

| 检查项 | ① 修复前（09:08） | ③ 部署后（09:53） |
|---|---|---|
| 前端产物模式 | ❌ 检测到 `@vite/client` → Vite DEV SERVER | ✅ 未注入 HMR 客户端 |
| 前端直出源码 | ❌ 引用 `/src/main.ts` | ✅ 未引用源码入口 |
| `:3000` Server 头 | ❌ 无 | ✅ **nginx** |
| nginx 进程数 | ❌ **0 个** | ✅ **13 个** |
| NSSM `erp-prod` / `erp-arq` | ⚠️ Stopped / Stopped | ✅ Running / Running |
| API 响应压缩 | ❌ 无 `Content-Encoding`，多传 **85.9%** | ✅ **`Content-Encoding: gzip`** |
| `:3000` 保留端口区间 | ⚠️ 未闭环 | ✅ 未被排除 |
| 后端强制重启 | ❌ 366 次（累计） | ✅ 新增 **0** 次 |
| nginx `[emerg]` | ❌ 1 条 | ✅ 新增 **0** 条 |
| 静态资源 404 | ⚠️ 11 条 | ✅ 新增 **0** 条 |
| `prod_runner` 心跳 | —（无此项） | ✅ **心跳龄 0s；frontend_ok=True** |
| 今日 `--reload` | ⚠️ 1 次 | ⚠️ 1 次（人工操作所致，非缺陷） |
| **汇总** | **FAIL 7 / WARN 5** | **FAIL 0 / WARN 1** |
| **判定** | **【开发栈】** | **【生产栈】** ✅ |

### 12.4 顺带修好了巡检脚本自身的三处缺陷

1. **累计型指标永久误报**（本轮剩余 2 项 FAIL 的真正原因）：`366 次` 与 `[emerg] 1 条` 读的是全量历史日志，重启不可能归零。已改为**增量基线棘轮**（基线 `deliverables/gstack/.perf-selfcheck-baseline.json`，新增 `-UpdateBaseline` 开关）。**并做了对抗性自检**：人为把基线调小后，脚本正确报出 `新增 66 次 / 1 条 / 11 条`、汇总 FAIL 2 —— **证明它不是"假绿"门**。
2. **新增心跳检查**：读 `prod_runner.json` 新鲜度 + `frontend_ok`。这是**唯一可靠的"生产栈到底活没活"判据** —— 因为 `prod_runner` 自身的 `print` 走**块缓冲**（它只给子进程设了 `PYTHONUNBUFFERED`，没给自己设），启动日志要等缓冲区满才落盘；实测 `logs/erp-prod.log` 里**根本没有 09:49 那次运行**（全文不含 `20792`/`21308`，最后一代仍是 08:36 的 `pid=16576`）。
3. **脚本缺 UTF-8 BOM**（含中文却无 BOM → PS 5.1 按 GBK 错读）。这正是此前巡检输出乱码（`ERP 鐢熶骇鏍堟ā寮忚嚜妫€`）的**真根因** —— 不是 `Out-File` 的问题。已补 BOM，`ParseFile errors = 0`，脚本自身日志现已完全干净。旧版备份：`perf-selfcheck.ps1.BEFORE-RATCHET`。

### 12.5 仍未闭合 / 新发现

| 项 | 状态 |
|---|---|
| **P2-2** `_FrontendNginx._kill_all()` 会 `taskkill /F /T /IM nginx.exe` **杀全机 nginx** | **未改**。本机兼生产机，误触发即中断线上 → 建议收窄为按 PID/项目路径匹配 |
| **新发现** `prod_runner` 自身 stdout 块缓冲 → 启动日志滞后 | 建议给服务设 `PYTHONUNBUFFERED=1`（NSSM `AppEnvironmentExtra`）或给关键 `print` 加 `flush=True`。**这是"系统无法发现自己坏了"的残留面** —— 启动期日志恰恰是最需要的 |
| 客户打样图片 404（access log 中 108 条 `/static/uploads/customer-sampling/*`） | 未查上游成因（功能性，与性能无关） |
| D1–D5/D7 已生效 · D6 已部署 | ✅ 本轮全部闭合 |
| QA 独立回归 `QA_PASS: NO` | 其唯一原因（D6 未部署）**已解除** |

### 12.6 部署后 15 分钟复验（2026-09-17 10:03，实时取证）

**结论：核心问题已闭合，线上零新增故障。**

| 复验项 | 实时值（10:03） |
|---|---|
| `:3000` 服务方 | `Server: nginx`，`Content-Length: 3733`，引用 **6 个 `/assets/*`**，**无 `@vite/client`**、**无 `/src/main.ts`** → 确为 dist 构建产物 ✅ |
| nginx 进程数 | **13**，最早启动 **09:49:37** ✅ |
| `prod_runner.json` | `mode=production  ready=True  frontend_ok=True`；`frontend={type:nginx, pid:21260, status:running}`；`backend={pid:20792, status:ready}`；`redis=ok`；心跳龄 **1–2s** ✅ |
| 压缩（直连 `:5002`，绕过 nginx） | **`content-encoding: gzip`** → D5 确认在线上生效 ✅ |
| 压缩（经 `:3000`） | **`Content-Encoding: gzip`** ✅ |
| 线上 `sw.js`（经 `:3000` 取回） | 长度 12,201 B；`StaleWhileRevalidate=0` / `NetworkFirst=0` / `api-read-cache=0` / `api-cache=0`；仅一条 `/\/api\//i → NetworkOnly`；fonts 两条 CacheFirst 保留 ✅ |
| 强制重启 | 累计 366，**本代（第 15 代）0 次** ✅ |
| **5xx / 499** | **09:49 重启之后新增 0 条**（112 条全部是 09/11–09/17 09:24 的历史值）✅ |
| nginx 错误日志 | `connect() failed` / `WSARecv` 最后事件停在 **09/16 13:00**，重启后 **0 条新增** ✅ |
| Redis `6379` / `6380` | 均 **`+PONG`**（用 `REDIS_PASSWORD` 认证；先前探针报的 `-NOAUTH` 是**我探针没带密码**，非故障）✅ |
| 回滚点 | `backups/frontend-dist-20260917-095034/`（前端）· `perf-selfcheck.ps1.BEFORE-RATCHET` ✅ |

**注意：D7（健康检查误杀防护）的线上效力尚未被触发验证** —— 重启后探针一路正常，未出现「连续 ≥3 次失败」的场景，因此该修复目前只有**单元测试级**证据，无生产实证。这是诚实的未验证项，不是失败。

**10:04 新发现（本轮新增，待处理）**

| 项 | 说明 |
|---|---|
| **`prod_runner.json` 的 `started_at` 字段名有误导性** | 源码 `write_status()` L668 写的是 `"started_at": _iso_now()` —— **每轮（3s）都被刷新成"当前时刻"**，实为"最后状态写入时间"，**不是进程启动时间**。任何据此判断"服务何时重启"的排查都会得出错误结论（本报告早期版本一度受影响，已改用 `psutil.create_time`）。建议改名为 `last_status_at` 或真正记录启动时刻 |
| **块缓冲未落盘在 10:04 依然存在** | `logs/erp-prod.log` 的 mtime 仍停在 **09:49:36**（已静默 14 分钟），全文不含本代 pid `21308`/`20792`/`21260`；最后一代日志仍是 08:36 那次（`pid=16576`，第 14075 行）。→ 当前 supervisor 的启动横幅与运行日志**全部卡在内存缓冲区**，一旦它出问题，日志同样看不到。这正是 12.5 那条遗留项，**已由本次复验确认仍然存在** |
| **`.env` 内以明文 URL 形式存放 Redis 口令** | `REDIS_CACHE_URL` / `REDIS_BROKER_URL` / `REDIS_RESULT_URL` 形如 `redis://:<pw>@127.0.0.1:6379/0`。属项目既有约定，但任何日志/探针打印这些变量都会泄露口令（**本轮我自己的探针就踩到了，已擦除产物文件**）。建议排查脚本一律脱敏 |
