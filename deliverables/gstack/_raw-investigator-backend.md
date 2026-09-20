# 后端 + 基础设施侧性能排查报告

- **调查员**：investigator-perf（GStack 团队）
- **项目**：D:\erp_system（滨发协同系统 ERP，FastAPI + Vue/Vite，Windows 原生）
- **调查时间**：2026-09-17 08:44 ~ 08:50（+08:00）
- **环境**：win32 / Git Bash + PowerShell
- **职责边界**：后端 + 基础设施。前端构建产物细节归 qa-perf；本报告仅从「后端/托管方式如何影响首屏与页面切换」切入。

> **所有结论均基于实际执行的命令输出与真实文件内容，已逐条标注证据来源。未查证项标注为「未证实」，不做推测性断论。**

---

## 一、结论摘要（真凶按影响排序）

### ★★★★★ P0-1：用户口中的「production」实际上是**开发启动器**——`--reload` + Vite dev server 正在跑

**这是压倒性主因，且直接解释了「debug 比 production 快」的悖论。**

当前 5002（API）与 3000（前端）端口的真实托管方式：

| 端口 | 真实占用进程 | 实际运行模式 | 证据 |
|---|---|---|---|
| 5002 | `python.exe` PID 17264（父进程 = `ERP服务器管理器_v5.33.exe` PID 15636） | **uvicorn `--reload --reload-dir fastapi_app`** | 进程树 + 启动日志 `WatchFiles ... Reloading...` |
| 3000 | `node.exe` PID 10640 | **Vite dev server（HMR）** | 首页含 `<script type="module" src="/@vite/client">` |
| 服务 | `erp-prod` (NSSM) | **Stopped** | `Get-Service` |

**根因**：`server_manager_v533.py` 的 GUI 界面有一个「双进程/调试」启动分支 `_start_dual_thread()`，它**硬编码**了开发参数：

```python
# server_manager_v533.py:1811
backend_cmd = [_PYTHON_EXE, '-u', '-m', 'uvicorn', 'fastapi_app.main:app',
               '--host', '0.0.0.0', '--port', str(_API_PORT),
               '--log-level', 'info', '--reload', '--reload-dir', 'fastapi_app']
```
```python
# server_manager_v533.py:1838  ← 前端也走 dev
self._frontend_process = subprocess.Popen(
    [npm_cmd, 'run', 'dev', '--', '--port', str(_WEB_PORT)], cwd=str(_FRONTEND_DIR), ...)
# frontend-vite/package.json:  "dev": "vite --host 0.0.0.0 --port 5173"
```

而真正的生产路径是另一条：`erp-prod` NSSM 服务 → `prod_runner.py` → `uvicorn --workers 8 --http httptools`（**无 --reload**）+ Nginx 托管 `frontend-vite/dist`。**这条路径当前根本没在跑**（`erp-prod` = Stopped）。

**补充（与 qa-perf 交叉验证后确认）：能拉起 Vite dev 并落到 3000 端口的一共 3 条路径，全部是 dev：**

| # | 位置 | 命令 | 说明 |
|---|---|---|---|
| 1 | `server_manager_v533.py:1839` | `[npm_cmd, 'run', 'dev', '--', '--port', str(_WEB_PORT)]` | **当前正在跑的那条**；同一分支 `:1811` 后端带 `--reload` |
| 2 | `server_manager.py:1827` | `[_NPM_CMD, 'run', 'dev', '--', '--port', str(_PORTS.web)]` | 旧版管理器（149KB），同样是 dev |
| 3 | `start.py:110` | `["npm", "run", "dev", "--", "--port", str(args.web_port)]` | CLI 入口；`start.py:45` `--web-port default=3000`；`start.py:120-121` 默认就走 dev |

**解释「为什么 `package.json` 写 5173 却出现 3000」**：`frontend-vite/package.json` 的 `"dev": "vite --host 0.0.0.0 --port 5173"` 只是默认值；上面 3 条路径都用 `npm run dev -- --port 3000` **显式覆盖** `--port` 为 3000。因此 5173 从不落地，3000 是这三条 dev 路径的统一端口。

**架构层根因**：`server_manager_v8/domain/models.py:170-171` 把进程角色的 docstring 直接定义为 `FRONTEND` = **"开发模式前端（vite）"**、`BACKEND` = **"开发模式后端（uvicorn）"** —— 这套管理器本就设计成「dev 模式 = vite + uvicorn --reload」与「prod 模式 = NSSM 服务」两条平行路径。问题不在路径设计，而在 **GUI 上这条 dev 路径被当作/被误用为生产**。

**为什么这会「比 production 快」**：用户对比的两个对象其实是
- 「快的那个」= 开发启动器（Vite dev 已在内存中热编译、uvicorn reloader 子进程常驻、无 8 worker 池分摊）
- 「慢的那个」= `erp-prod` NSSM 正式栈（8 worker 冷启动、Nginx 反代无 keepalive 每次新建连接、静态资源首次冷加载）

**这是 A/B 两组完全不同的运行时，不是同一套系统的两种模式。** 结论方向要反过来看：不是 production 慢，而是「被误认为 production 的那次」跑的是 dev。

### ★★★★☆ P0-2：gzip 真空 —— **实测已确认正在发生**（生产配置 + 开发运行时错位）

**升级说明**：经与 qa-perf 交叉验证并补做实测后，本条由「配置缺陷（隐患）」升级为「**当前正在发生的、已量化的事实**」：对运行中的后端发 `Accept-Encoding: gzip`，`/metrics` 返回 **18745 字节 `text/plain` 且 `Content-Encoding` 为空**。

启动日志同时出现这两组**互相矛盾**的行：

```
GZip 压缩由 Nginx 处理（生产环境）
生产环境未配置 WS_ALLOWED_ORIGINS，CSP connect-src 回退到 wss:（建议收紧）
安全头部已配置（CSP 模式: 生产（无 unsafe-eval/ws:））
INFO:     Started server process [18348]
```
来源：`logs/server_manager_20260917.log`（08:43:02）

即：进程读的是 `.env`（`APP_ENV=production`、`FASTAPI_DEBUG=false`）→ **坚信自己是生产**；但**外层用 dev 参数拉起**（`--reload`）、**外层用 Vite dev 托管前端**。中间件按生产裁剪（gzip 交给 Nginx），可实际上**根本没有 Nginx 在跑**（nginx 进程数 = 0）。

**直接后果：gzip 被两边同时放弃**——FastAPI 中间件因「生产模式」直接 return，而 Nginx 未运行 → **前端静态资源与 API 响应全程无压缩**。

#### ★ 实测证据（经与 qa-perf 交叉验证后补入 —— 真空是「当前事实」而非「隐患」）

对**当前正在运行的后端**（5002）发带 `Accept-Encoding: gzip` 的请求，实测结果：

```
$f: D:\erp_system\deliverables\gstack\_probe6.txt   (PROBE6 2026-09-17T08:50:59)
请求均带 Accept-Encoding: gzip

/api/v2/health -> status=200 rawlen=33     cenc=[]  ctype=[application/json]
/metrics       -> status=200 rawlen=18745  cenc=[]  ctype=[text/plain; version=0.0.4; charset=utf-8]
/api/health    -> status=200 rawlen=51     cenc=[]  ctype=[application/json]
```

**`/metrics` 返回 18745 字节的 `text/plain`，客户端明确发了 `Accept-Encoding: gzip`，响应 `Content-Encoding` 为空（`cenc=[]`）。**

18.7 KB 远超 `GZipMiddleware(minimum_size=1000)` 阈值 → 若中间件已注册，此响应**必然**被压缩；实测未压缩 → **`GZipMiddleware` 确实未注册**，`middleware.py:321-323` 早退分支真实生效；且前方无 Nginx 兜底。

**结论：gzip 真空不是「起正式栈后才需担心」，而是此刻正在发生、且已量化的事实。** 18.7 KB 明文文本按常规压缩比可降至约 1/4。

证据链：
- `fastapi_app/core/middleware.py:319-324` —— `if settings.is_production: return`（生产直接 return，不注册中间件）
- `fastapi_app/core/middleware.py:320` 注释自述「生产环境由 Nginx 统一处理 GZip 压缩」→ **把可用性押在另一个进程存在上，却无任何守卫**（设计层面单点依赖）
- `Get-Process nginx` → `none`（本轮探测，nginx 进程数 = 0）
- 启动日志 `GZip 压缩由 Nginx 处理（生产环境）`（`logs/server_manager_20260917.log` 08:43:02）
- 实测 `/metrics` 18745B 未压缩（`_probe6.txt`）

### ★★★☆☆ P1-1：`--reload` 的 WatchFiles 会持续扫描整个 `fastapi_app` 树

```python
'--reload-dir', 'fastapi_app'   # server_manager_v533.py:1811
```
`WatchFiles detected changes in 'fastapi_app\core\middleware.py', 'fastapi_app\services\staging\order.py', ... Reloading...`
—— 今日已触发至少 1 次全量 reload（`logs/server_manager_20260917.log` 08:42:56）。每次 reload = 全部 worker/事件循环重建 + 连接池 dispose + 缓存预热重跑。用户「首次加载和切换页面偶尔卡一下」与此高度吻合。

### ★★☆☆☆ P1-2：`logs/后端(uvicorn).out.log` 累计 **406 次 `Started parent process`**

```bash
grep -c "Started parent process" "logs/后端(uvicorn).out.log"   → 406
```
即该日志覆盖的历史窗口内，后端父进程被拉起 **406 次**。结合 `--reload`、GUI 反复启停、以及历史「重启风暴」，说明这个栈**长期处于频繁重启状态**——每次冷启动都要重建连接池、预热门户缓存、重连 Redis，首次请求必然显著变慢。

### ★★☆☆☆ P1-3：连接池 `max_overflow=3` 偏小 + `pool_recycle` 未生效

`fastapi_app/core/database.py::_get_pool_config()` 用 `UVICORN_WORKERS` 动态均分，但**分母偏大**：
```python
pool_size    = max(5, available // (workers * 2))    # available=80, workers=8 → 5
max_overflow = max(3, available // (workers * 3))    # available=80, workers=8 → 3
```
→ 每 worker 5+3=8 连接，8 worker 合计上限 64。`max_overflow=3` 在并发突发（如首页同时打多个列表接口）时容易触顶，请求排队等连接。

**`pool_recycle` 未设置**：`.env:22` 写了 `DB_POOL_RECYCLE=1800`，但 `_get_pool_config()` 返回的 dict 中**没有 `pool_recycle` 键** → 长连接可能被 PostgreSQL `idle_session_timeout` / 中间网络设备静默断开，下一个请求拿到死连接 → 触发 `pool_pre_ping` 探测失败 → 重连，单次请求多出数百 ms。

`.env` 注释本身也警告过这个错位（未修）：
> `UVICORN_WORKERS` 若与 NSSM `AppEnvironmentExtra` 不一致，会造成"prod_runner 日志说 4、实际跑 8、database.py 连接池按 4 分摊"的三方错位

### ★☆☆☆☆ P2-1：`log_config.json` 是**死配置**（已排除该嫌疑）

用户点名怀疑「sync 日志 handler 在请求路径写盘」。**实测：该文件从未被加载**。

```bash
grep -rn "log-config\|log_config" --include="*.py" .   →  仅命中 temp/_leader_ast_audit.py（无关）
```
- `prod_runner.py::_cmd_uvicorn` **未传 `--log-config`**
- 全仓库无 `dictConfig` / `LOGGING_CONFIG` 引用
- 结论：`fastapi_app/log_config.json` 中指向 `D:/erp_system/logs/fastapi.log` 的同步 `FileHandler` **未生效**。

实际生效的日志 handler 来自 `fastapi_app/core/logger.py`：`StreamHandler(stdout)` + `TimedRotatingFileHandler(INFO)`，均为单条追加写，非 `fsync`。**每请求同步写盘不是本项目的瓶颈**。→ **此嫌疑排除。**

### P2-2：日常「每请求固定开销」清单（存在但不致命）

| 开销 | 位置 | 每请求成本 |
|---|---|---|
| CSP nonce `secrets.token_urlsafe(16)` | `middleware.py::_setup_security_headers` | 一次 CSPRNG 调用 |
| `set_cookie("fastapi_csrf_token", ...)` | `middleware.py::_setup_csrf` | Set-Cookie 头 + 客户端写入 |
| Prometheus 路径归一化正则 | `middleware.py::_setup_prometheus` | 每请求正则匹配 |
| X-Request-ID UUID | `middleware.py::_setup_request_id` | 一次 UUID4 |
| body size 检查 | `middleware.py::_setup_body_size_limit` | Content-Length 判断（轻） |
| AuditLog 中间件 `BaseHTTPMiddleware` | `audit_middleware.py` | 仅写方法（POST/PUT/PATCH/DELETE）计时；GET 直接透传 |
| 限流器 `Limiter` | `limiter.py:28` | `enabled=False`，已关闭 |

这些叠加通常在**亚毫秒级**，不足以解释「明显变慢」。列出仅为完整性。

### 已查证**排除**的嫌疑（重要——避免继续在错方向排查）

| 用户怀疑项 | 实测结论 | 证据 |
|---|---|---|
| 生产跑 `--reload`？ | **生产路径没有**（`prod_runner.py:167-181` 无 --reload）；但**当前实际运行的那个有** | 见 P0-1 |
| 单进程同步阻塞？ | **否**。生产配置 8 worker，`--http httptools` | `prod_runner.py`、`logs/prod_runner.json` |
| SQL_ECHO 开着？ | **否**，`echo=False` | `database.py:128/178` |
| 日志级别 DEBUG？ | **否**，INFO | `logger.py:49`、`log_config.json`（后者未生效） |
| `pool_pre_ping` 未启用？ | **已启用** | `database.py:51-52` |
| 登录 N+1？ | **无**。`selectinload(User.permissions)` 已预加载 | `user_service.py:241-248` |
| 密码哈希过慢？ | **否**。Argon2id（memory_cost=19456/t=2/p=1）+ `run_in_threadpool` 不阻塞事件循环 | `security.py`、`auth_service.py` |
| JWT 慢？ | **否**。ES256 单次签名 ~0.2ms | `security.py`、`.env` |
| BOM/审批详情 N+1？ | **无**。均为 `selectinload`/`joinedload` 预加载 | `bom_service.py:150-171`、`approval_service.py:128-137` |
| 每请求全量缓存失效？ | **无**。仅有针对性 `invalidate_cache('orders:p*')` 等 | `cache.py:496-498`、`purchase_center/order_routes.py:55/68` |
| 模型层 lazy='select' 泛滥？ | **部分**：77 处 `relationship()` 多为默认 lazy；但 188 处 `selectinload/joinedload` 覆盖了主要热路径 | `grep relationship(` / `grep selectinload` |
| 模型层无预加载？ | **否**，188 处预加载 | 同上 |
| `FLASK_ENV=development` 会导致模式误判？ | **否**。FastAPI 应用**从不读** `FLASK_ENV`（全仓唯一引用是 `tests/performance/test_performance.py`）；模式判定唯一权威是 `config.py:35 _is_production_env()`，只读 `APP_ENV` | `grep -rn FLASK_ENV --include=*.py` → 仅测试文件一处 |

---

## 二、逐项证据

### 证据 1：当前进程树 —— 5002 由 GUI 启动器拉起（含 --reload）

```
$ Get-CimInstance Win32_Process     （PowerShell，节选）
ProcessId : 17264   Name: python.exe    ParentProcessId: 15636      ← 占用 5002
ProcessId : 18348   Name: python.exe    ParentProcessId: 17264      ← reloader 子进程
ProcessId : 15636   Name: ERP服务器管理器_v5.33.exe  ParentProcessId: 4856
ProcessId : 10640   Name: node.exe                                  ← 占用 3000
```
```
$ Get-NetTCPConnection -State Listen
LocalAddress LocalPort OwningProcess
0.0.0.0           5002         17264     ← python.exe
0.0.0.0           3000         10640     ← node.exe
127.0.0.1         6379         12572     ← redis-server.exe
127.0.0.1         6380         17412     ← redis-server.exe
```
**父子关系链**：`ERP服务器管理器_v5.33.exe (15636)` → `python.exe (17264, :5002)` → `python.exe (18348)`
这正是 uvicorn `--reload` 的典型父子结构（reloader 父进程 + 被监管的子进程）。

### 证据 2：服务状态 —— `erp-prod` 根本没在跑

```
$ Get-Service | Where Name -like "*erp*"
Name             DisplayName                        Status
erp-arq          erp-arq                           Stopped
erp-prod         erp-prod                          Stopped     ← 正式生产服务已停止
erp-redis        erp-redis                         Running
erp-redis-broker erp-redis-broker                  Running
rediserp         rediserp                          Stopped
```
**无 nginx 进程**（`Get-Process nginx` → 无输出）。

### 证据 3：`--reload` 正在生效（WatchFiles 触发重载）

```
logs/server_manager_20260917.log:
[2026-09-17 08:42:56,986] INFO: WARNING:  WatchFiles detected changes in
  'fastapi_app\core\middleware.py', 'fastapi_app\services\staging\order.py',
  'fastapi_app\services\order\commands.py', 'fastapi_app\core\prod_runner.py',
  'fastapi_app\tests\conftest.py', ... Reloading...
```
`WatchFiles` / `Reloading...` 只可能来自 uvicorn `--reload`。

### 证据 4：3000 端口是 **Vite dev server**，不是 Nginx、不是 dist 静态托管

```
$ curl -s http://127.0.0.1:3000/ | grep "@vite/client"
    <script type="module" src="/@vite/client"></script>          ← HMR 客户端
```
```
$ grep -c "@vite/client" frontend-vite/dist/index.html
0                                                                 ← 干净构建无此脚本
$ grep -o 'src="[^"]*"' frontend-vite/dist/index.html
src="/assets/index-Cb7_V1ei.js"
src="/registerSW.js"
```
```
logs/server_manager_20260917.log:
[WEB] 08:41:10 [vite] (client) hmr update /@fs/D:/erp_system/frontend-vite/src/styles/app.css
[WEB] 08:41:10 [vite] (client) page reload dist-bench/index.html
```

**同时注意**：`frontend-vite/dist/` **已存在且是新鲜构建**（2026-09-16 19:40，assets 3.9MB，主 chunk `index-Cb7_V1ei.js`）——也就是说**生产产物是齐的，只是没被用上**。

### 证据 5：生产配置 + 开发运行时的错位

```
logs/server_manager_20260917.log (08:43:02):
INFO:  GZip 压缩由 Nginx 处理（生产环境）
WARNING: 生产环境未配置 WS_ALLOWED_ORIGINS，CSP connect-src 回退到 wss:（建议收紧）
INFO:  安全头部已配置（CSP 模式: 生产（无 unsafe-eval/ws:））
INFO:  Started server process [18348]
```
```
$ grep -n "^APP_ENV\|^FASTAPI_DEBUG\|^UVICORN_WORKERS" .env
49:FASTAPI_DEBUG=false
169:UVICORN_WORKERS=8
172:APP_ENV=production
```
后端按生产配置裁剪了 gzip（交给 Nginx），但 **Nginx 没跑** → **静态资源与 API 响应实现上全程未压缩**。

### 证据 6：前端 dev 模式下 API 反代是 Vite 内置 proxy，且 3000 反代本身更快（迷惑点）

```
$ curl -o /dev/null -w "..." http://127.0.0.1:5002/api/v1/auth/login   （直连后端）
try1: http=405 connect=0.022283s ttfb=0.027269s total=0.027921s
try2: http=405 connect=0.017629s ttfb=0.023384s total=0.024168s

$ curl -o /dev/null -w "..." http://127.0.0.1:3000/api/v1/auth/login   （经 3000）
try1: http=405 connect=0.006081s ttfb=0.012516s total=0.013099s
try2: http=405 connect=0.013816s ttfb=0.019504s total=0.019994s
```
**后端本身响应 20ms 级，不是瓶颈**（405 = 探针用了 GET，接口是 POST）。

### 证据 7：`erp-prod` 正式栈的 `prod_runner.json` 与实际不符（陈旧快照）

```
$ type logs\prod_runner.json
{
  "pid": 16576, "started_at": "2026-09-17T08:37:53", "mode": "production",
  "ready": true, "workers": 8, "api_port": 5002, "web_port": 3000,
  "frontend_type": "nginx",
  "services": { "backend": { "pid": 3708, "status": "ready", ... }, ... }
}
```
- 文件声称 `pid=16576`、`workers=8`、`frontend_type=nginx`、`pid=3708`
- **实际**：5002 的拥有者 = PID **17264**；无 nginx 进程；`erp-prod` 服务 Stopped
- 结论：**这是上一轮生产的陈旧快照**，当前运行的栈不是它。

### 证据 8：406 次父进程启动（长期重启史）

```
$ grep -c "Started parent process" "logs/后端(uvicorn).out.log"
406
```
```
logs/后端(uvicorn).out.log 头部:
INFO:     Uvicorn running on http://0.0.0.0:5002 (Press CTRL+C to quit)
INFO:     Started parent process [17044]
   ...（同一次启动内出现多个 "Started server process"，说明历史上是多 worker 模式）
```

### 证据 9：连接池配置与 `pool_recycle` 缺失

```python
# fastapi_app/core/database.py::_get_pool_config()（节选）
workers = int(os.getenv("UVICORN_WORKERS", "4"))          # =8
available = int(os.getenv("DB_MAX_CONNECTIONS", "100")) - 20   # =80
pool_size    = max(5, available // (workers * 2))         # =5
max_overflow = max(3, available // (workers * 3))         # =3
return {"pool_size": pool_size, "pool_timeout": 30, "max_overflow": max_overflow,
        "pool_pre_ping": True, "pool_use_lifo": True}     # ← 无 pool_recycle
```
```
$ grep -n "DB_POOL_RECYCLE" .env
22:DB_POOL_RECYCLE=1800            ← 写了但代码没读
```

### 证据 10：`log_config.json` 未被加载（嫌疑排除）

```
$ grep -rn "log-config\|log_config" --include="*.py" .
./temp/_leader_ast_audit.py:111:  "log_config", "utf-16", ...     ← 唯一命中，与本项目无关
```
```
# fastapi_app/core/prod_runner.py::_cmd_uvicorn —— 无 --log-config
[_PY, "-m", "uvicorn", "fastapi_app.main:app",
 "--host", "0.0.0.0", "--port", str(api_port),
 "--workers", str(workers), "--http", "httptools",
 "--proxy-headers", "--forwarded-allow-ips=*",
 "--no-access-log", "--timeout-keep-alive", "5"]
```
→ `fastapi_app/log_config.json` 的同步 `FileHandler` **未生效**。实际日志由 `core/logger.py` 的 `TimedRotatingFileHandler` 承担。

### 证据 11：正式生产路径本身是「正确」的（对照用）

```python
# fastapi_app/core/prod_runner.py::_cmd_uvicorn  ——  正确：无 --reload，多 worker，httptools
"--workers", str(workers), "--http", "httptools", "--proxy-headers",
"--forwarded-allow-ips=*", "--no-access-log", "--timeout-keep-alive", "5"
```
```
# config/nginx-windows.conf —— Windows 官方版限制
upstream fastapi_backend { server 127.0.0.1:5002; }   # 无 keepalive
# 注释：Windows 官版 nginx 无 ngx_http_upstream_keepalive_module，
#       反代每次新建 TCP 连接（HTTP/1.0 语义）
```
→ 正式栈唯一的结构性代价是 **Nginx 反代每次新建连接**，但这与用户当前遇到的问题**不同源**（用户当前跑的根本不是这条栈）。

### 证据 12：缓存中间件行为（非主因，记录在案）

```
fastapi_app/core/limiter.py:28
Limiter(enabled=False, storage_uri=os.getenv("REDIS_CACHE_URL") or "memory://", ...)
```
- 限流存储与缓存共用 `:6379/0`（key 命名空间有重叠风险），但 `enabled=False`，**当前无实际影响**。
- `CACHE_L1_BROADCAST_ENABLED=false` + 多 worker → L1 缓存跨进程失效窗口最长 30s（`local_ttl=30`）。这是**正确性**问题（脏读窗口），不是速度问题。

---

## 三、后端侧优化清单（P0 / P1 / P2）

> 每项格式：**问题 → 改法 → 预期收益 → 验证方法**

### P0-1　纠正「生产」实为「开发启动器」的错配 ★最高优先

- **问题**：GUI 的 `_start_dual_thread()` 用 `--reload` + Vite dev 拉起，被误当作生产；正式 NSSM 栈（`erp-prod` + Nginx + dist + 8 worker）未启用。
- **改法（择一）**：
  1. **要用生产** → 停止 GUI 的「双进程/调试」按钮，改用「生产模式」按钮（走 `erp-prod` NSSM）：`nssm start erp-prod` / `sc start erp-prod`，并确认 Nginx 起来（`nginx-health` 探针 200）。
  2. **保留 GUI 启动器** → 在 `_start_dual_thread()` 中把 `--reload` 换成 `--workers N --http httptools`，`npm run dev` 换成托管 `dist`（`npm run preview` 或让 Nginx serve dist）。**不要**一边声称生产一边跑 dev 参数。
- **预期收益**：消除 reload 抖动；前端从「按需转译 ES 模块」变为「预打包 + gzip + 长缓存」；首屏与切页应显著改善（这是用户感受的主体）。
- **验证方法**：
  ```bash
  # 1) 确认无 --reload
  powershell -c "(Get-CimInstance Win32_Process | ? Name -like 'python*').CommandLine"
  # 2) 确认前端非 dev（不应出现 @vite/client）
  curl -s http://127.0.0.1:3000/ | grep -c "@vite/client"     # 期望 0
  # 3) 确认 nginx 在跑
  powershell -c "Get-Process nginx | Measure-Object | % Count" # 期望 >=1
  # 4) 确认 3000 响应头 server
  curl -s -I http://127.0.0.1:3000/ | findstr /i server       # 期望 nginx
  ```

### P0-2　修复「gzip 两边都放弃」的真空（★实测已确认正在发生）

- **问题**：后端因 `APP_ENV=production` 让出 gzip（`middleware.py:321-323` 直接 return），但 Nginx 未运行 → **响应对客户端全程未压缩**。实测 `/metrics` 返回 18745B `text/plain` 且无 `Content-Encoding`（见 P0-2 实测证据）。
- **改法（采纳 qa-perf 提议 + 本报告 Nginx 语义复核）**：
  **不要**再把可用性押在「Nginx 一定在跑」上。改为**后端始终注册 gzip**，或加显式开关：
  ```python
  # middleware.py::_setup_gzip
  # 方案 A（最简单）：始终注册，Nginx 不会二次压缩
  app.add_middleware(GZipMiddleware, minimum_size=1000)
  # 方案 B（可配）：BACKEND_GZIP=auto|on|off；auto=探测 Nginx 存活，缺席则自压
  ```
  **「不会双重压缩」的依据**：Nginx `gzip` 模块只对「响应中尚无 `Content-Encoding`」的对象压缩，对已带 `Content-Encoding: gzip` 的上游响应不重复压缩。`config/nginx-windows.conf:66-80` 的 `gzip_proxied any` 只是允许压缩被代理响应，并非强制重压。
- **设计层评价**：`middleware.py:320` 注释自述「生产环境由 Nginx 统一处理 GZip 压缩」——即代码**明知依赖另一个进程**却无守卫，属单点依赖，不只是配置疏漏。
- **预期收益**：文本类资源（JS/CSS/JSON/`/metrics`）体积降低 60%~80%，首屏与列表接口 TTFB 明显改善；且 Nginx 再挂也不会压缩归零。
- **验证方法**（当前环境 Bash/PowerShell stdout 可能失效，用「PowerShell 写文件 → Read 读回」）：
  ```powershell
  # 对 >1000B 的文本响应验证（/metrics 最直观：18.7KB）
  $r = Invoke-WebRequest "http://127.0.0.1:5002/metrics" -UseBasicParsing -Headers @{ "Accept-Encoding"="gzip" }
  "rawlen=$($r.RawContentLength) cenc=[$($r.Headers['Content-Encoding'])]"
  # 期望：cenc=[gzip]；当前实测：cenc=[]
  ```

### P1-1　消除 `--reload` 全树扫描

- **问题**：`--reload-dir fastapi_app` 让 WatchFiles 常驻扫描整个应用树，任何文件变更（包括测试、临时文件）触发全量重载。
- **改法**：生产/准生产一律去掉 `--reload`；若确需热重载，把 `--reload-dir` 收窄到 `fastapi_app/api`、`fastapi_app/services`，并排除 `tests/`、`temp/`、`__pycache__/`。
- **预期收益**：消除「偶发卡顿」（重载瞬间请求被中断/排队）、降低 CPU 与磁盘 IO。
- **验证方法**：改一个 `fastapi_app/tests/` 下的文件，观察日志**不再**出现 `Reloading...`。

### P1-2　连接池参数修正

- **问题**：`max_overflow=3` 偏小；`pool_recycle` 未设置（`.env` 写了 1800 但代码不读）；`DB_POOL_SIZE/DB_MAX_OVERFLOW` 是死配置。
- **改法**（`fastapi_app/core/database.py::_get_pool_config()`）：
  ```python
  return {
      "pool_size": pool_size,
      "max_overflow": max_overflow,
      "pool_timeout": 30,
      "pool_pre_ping": True,
      "pool_use_lifo": True,
      "pool_recycle": int(os.getenv("DB_POOL_RECYCLE", "1800")),   # ← 补上
  }
  ```
  并把 `max_overflow` 分母从 `workers*3` 放宽到 `workers*2`（或设下限 ≥5）。
  同时**清理 `.env` 中会被误读的 `DB_POOL_SIZE/DB_MAX_OVERFLOW`**，或让代码优先读它们，避免「三方错位」重演。
- **预期收益**：突发并发不再排队等连接；消除死连接导致的偶发数百 ms 抖动。
- **验证方法**：
  - 启动日志应出现「连接池预热完成 (N 个连接)」，N 与配置一致；
  - 压测并发（如 `ab -c 20 -n 200`）观察 P95 与 `pool_timeout` 报错计数（应为 0）；
  - PG 侧：`SELECT count(*) FROM pg_stat_activity WHERE datname='erp_system';` 观察是否逼近上限。

### P1-3　收敛频繁重启

- **问题**：单份日志 406 次 `Started parent process`，冷启动频繁 → 每次重建连接池/预热缓存/重连 Redis。
- **改法**：查清重启来源（GUI 反复启停 / 历史重启风暴残留 / 健康检查误判），统一由 NSSM 托管并让其负责重启策略，禁止 GUI 与 NSSM 同时管同一端口。
- **预期收益**：稳态连接池与热缓存，首次请求不再周期性变慢。
- **验证方法**：连续观察 30 分钟，`grep -c "Started parent process"` 增量应为 0。

### P2-1　限流存储与缓存分库

- **问题**：`limiter.py` 用 `REDIS_CACHE_URL`（`:6379/0`）作限流存储，与业务缓存同 db。
- **改法**：给限流单独 db（如 `/1`）或独立 key 前缀；若长期保持 `enabled=False`，可暂时降级为 `memory://`。
- **预期收益**：避免未来开启限流时的 key 冲突/失效风暴；当前无即时收益。
- **验证方法**：`redis-cli -n 0 --scan --pattern "*limiter*"` 应无输出。

### P2-2　`CACHE_L1_BROADCAST_ENABLED` 与 worker 数匹配

- **问题**：8 worker + L1 广播关闭 → 跨进程脏读窗口 30s。
- **改法**：要么开启 L1 广播（`CACHE_L1_BROADCAST_ENABLED=true`）并保证 Redis Pub/Sub 可用；要么把 `local_ttl` 调小到 5~10s。
- **预期收益**：消除「切页看到旧数据」的正确性问题（非速度）。
- **验证方法**：worker A 改数据 → worker B 立即读，应无 30s 陈旧窗口。

### P2-3　清理死配置

- **问题**：`fastapi_app/log_config.json`、`.env.production`、`.env` 中的 `DB_POOL_SIZE/DB_MAX_OVERFLOW`、`DB_POOL_RECYCLE` 均与实际行为不符，误导排查；`.env:42 FLASK_ENV=development` 与 `:172 APP_ENV=production` 自相矛盾。
- **改法**：删除或加醒目注释标明「不生效」；`.env.production` 与 `.env` 二选一（当前实际生效的是 `.env`）；删除 `FLASK_ENV`（FastAPI 不读它，纯 Flask 遗留）。
- **预期收益**：降低后续排障误判成本（本次调查中 `.env.production` 与 `FLASK_ENV` 都曾构成干扰）。
- **验证方法**：全仓 `grep` 确认无残留引用；`grep -rn "FLASK_ENV" --include="*.py" fastapi_app/` 应为空。

### P2-4　合并 dev/prod 两条启动路径的「模式自证」

- **问题**：同一套系统存在 3 条 dev 启动路径（`server_manager_v533.py:1839`、`server_manager.py:1827`、`start.py:110`）与 1 条 prod 路径（`prod_runner.py`），但**没有任何机制阻止「用 prod 的 .env 跑 dev 的启动参数」**——这正是本次故障的形成方式。
- **改法**：在启动入口加一致性断言——若 `APP_ENV=production` 却检测到 `--reload` 或 `npm run dev`，则**启动即失败并明确报错**（而不是静默按生产裁剪 gzip 却让 Nginx 缺席）。
- **预期收益**：从机制上杜绝本次这类「生产配置 + 开发运行时」的错配，避免同类问题复发。
- **验证方法**：故意用 `APP_ENV=production` + `--reload` 启动，应被拒绝并给出可读错误。

---

## 四、服务器端定位命令手册（Windows 为主）

### 4.1 进程与端口

```powershell
# 谁在监听关键端口（5002 API / 3000 前端 / 6379,6380 Redis / 5433 PG）
Get-NetTCPConnection -State Listen |
  Where-Object LocalPort -in 5002,3000,6379,6380,5433 |
  Select-Object LocalAddress,LocalPort,OwningProcess

# 由 PID 反查进程名与父进程（判断是否 GUI 拉起 / 是否多 worker）
Get-CimInstance Win32_Process |
  Where-Object { $_.ProcessId -in 17264,18348,10640 } |
  Select-Object ProcessId,ParentProcessId,Name,CommandLine | Format-List

# 数 worker / nginx
Get-Process python,nginx -ErrorAction SilentlyContinue |
  Select-Object Id,ProcessName,@{n='MemMB';e={[math]::Round($_.WorkingSet64/1MB,1)}}
```

```bash
# Git Bash 版
netstat -ano | grep -E ":5002|:3000|:6379|:6380|:5433"
```

### 4.2 服务状态（NSSM / SCM）

```powershell
Get-Service erp-prod,erp-arq,erp-redis,erp-redis-broker | Select Name,Status
# 起正式生产栈
nssm start erp-prod      # 或:  sc start erp-prod
```
> 注意：不要直接 kill NSSM 受管进程（会被自动重拉，形成重启循环）。

### 4.3 HTTP 计时（区分网络/连接/服务处理）

```powershell
# PowerShell 原生：TTFB 与总耗时
Measure-Command { Invoke-WebRequest http://127.0.0.1:5002/api/health -UseBasicParsing }
```
```bash
# curl（Git Bash）：连接/首字节/总耗时拆分
curl -o /dev/null -w "http=%{http_code} dns=%{time_namelookup}s connect=%{time_connect}s ttfb=%{time_starttransfer}s total=%{time_total}s\n" \
  http://127.0.0.1:5002/api/v1/... 

# 对比直连后端 vs 经前端代理 的差异（关键！）
curl -o /dev/null -w "direct  %{time_total}s\n" http://127.0.0.1:5002/api/v1/...
curl -o /dev/null -w "proxied %{time_total}s\n" http://127.0.0.1:3000/api/v1/...

# 验证 gzip
curl -s -H "Accept-Encoding: gzip" -D - -o /dev/null http://127.0.0.1:3000/assets/index-Cb7_V1ei.js | grep -i "content-encoding\|content-length"
```

### 4.4 判断前端是 dev 还是 dist（一眼定性）

```bash
curl -s http://127.0.0.1:3000/ | grep -c "@vite/client"     # >0 = Vite dev；0 = 构建产物
curl -s -I http://127.0.0.1:3000/ | grep -i "^server:"       # nginx / Vite 一眼可辨
```

### 4.5 uvicorn / 应用日志分析

```bash
# 是否开着 --reload（WatchFiles/Reloading 只可能来自 reload）
grep -c "Reloading\.\.\."             logs/server_manager_20260917.log
grep    "WatchFiles detected"          logs/server_manager_20260917.log | tail -5

# 重启频率（冷启动次数）
grep -c "Started parent process"      "logs/后端(uvicorn).out.log"
grep -c "Finished server process"      logs/server_manager_20260917.log

# 启动模式判定（生产/开发配置）
grep -E "GZip 压缩由|CSP 模式|连接池预热完成|Redis缓存管理器" logs/server_manager_20260917.log | tail -10

# 5xx / 异常
grep -E '"status": 5[0-9][0-9]'        logs/fastapi_20260917.log | tail -20
grep -i "timeout\|pool\|连接池\|慢查询" logs/fastapi_20260917.log | tail -20
```

```powershell
# 实时跟踪（PowerShell）
Get-Content "D:\erp_system\logs\server_manager_20260917.log" -Wait -Tail 50
```

### 4.6 数据库侧

```bash
# 应用内已有慢查询监听（阈值 0.2s OLTP / 1.0s 报表）
grep -i "slow\|慢查询" logs/fastapi_20260917.log | tail -20
```
```sql
-- PG 侧：当前活跃连接（判断是否触顶）
SELECT count(*), state, wait_event_type
FROM pg_stat_activity WHERE datname='erp_system' GROUP BY 2,3;

-- PG 侧：当前正在跑的慢 SQL（>1s）
SELECT pid, now()-query_start AS dur, state, left(query,120)
FROM pg_stat_activity
WHERE datname='erp_system' AND now()-query_start > interval '1 second'
ORDER BY dur DESC;

-- 是否装了 pg_stat_statements（推荐开，用于长期 Top SQL）
SELECT query, calls, mean_exec_time, total_exec_time
FROM pg_stat_statements ORDER BY total_exec_time DESC LIMIT 20;
```

### 4.7 Python 侧剖析（可选，需安装）

```bash
pip install py-spy
# 火焰图（针对最耗 CPU 的 worker）
py-spy record -o D:/erp_system/deliverables/gstack/profile.svg --pid 17264 --duration 30
# 实时 top（看函数热点）
py-spy top --pid 17264
```
> 若 `psutil` 未安装：`pip install psutil`，之后可用
> `python -c "import psutil;[print(p.info['pid'],p.info['cmdline']) for p in psutil.process_iter(['pid','cmdline']) if 'python' in (p.info['name'] or '').lower()]"`
> 获取完整命令行（本次环境 `Get-CimInstance` 的 CommandLine 为空、`wmic` 被安全策略拦截）。

### 4.8 一键「模式自检」脚本（建议固化为日常巡检）

```bash
#!/usr/bin/env bash
echo "== 5002/3000 归属 =="
netstat -ano | grep -E ":5002|:3000"
echo "== 前端是 dev 还是 dist（>0 即 dev） =="
curl -s http://127.0.0.1:3000/ | grep -c "@vite/client"
echo "== 3000 server 头（nginx / Vite） =="
curl -s -I http://127.0.0.1:3000/ | grep -i "^server:"
echo "== 今日 reload 次数 =="
grep -c "Reloading\.\.\." logs/server_manager_$(date +%Y%m%d).log 2>/dev/null
echo "== gzip 是否生效 =="
curl -s -H "Accept-Encoding: gzip" -D - -o /dev/null \
  http://127.0.0.1:3000/assets/index-Cb7_V1ei.js | grep -i "content-encoding" || echo "NO GZIP"
```

---

## 五、给团队的关键提醒

1. **本次问题的核心不是「production 慢」，而是「被当成 production 的那次跑的是 dev」**。请 qa-perf / product-perf 在结论中同步这一事实，避免团队按「生产优化」方向给出无效建议。
2. **正式生产栈本身（`prod_runner.py` + Nginx + 8 worker）在配置层面是正确的**，唯一结构性代价是 Windows Nginx 反代无 keepalive。若要真正验证「production 到底慢不慢」，必须先 `nssm start erp-prod` 把正式栈跑起来，再做同条件 A/B。
3. **`logs/prod_runner.json` 是陈旧快照，不可作为「当前在跑生产」的证据**。
4. **`.env.production` 与 `.env` 不一致，实际生效的是 `.env`**（`prod_runner.py::_load_dotenv()` 加载 `PROJECT_ROOT/.env`）；团队初期的 `.env.production` 信息会误导排查。
5. 已排除的嫌疑（日志写盘、N+1、密码哈希、DEBUG 日志）**不必再投入时间**。

---

## 附录 A：协作复核记录与工具环境说明

### A.1 与 qa-perf 的交叉验证（双方独立复核，结论互洽）

| 议题 | 双方结论 | 状态 |
|---|---|---|
| 真凶 #1（dev 被当生产） | 一致；qa-perf 独立确认 3000=node.exe 非 nginx、`@vite/client` 存在 | ✅ 确认 |
| gzip 真空 | 一致，且本研究**补上实测硬证据**（`/metrics` 18745B 无 `Content-Encoding`） | ✅ 确认（有数据） |
| 「压缩/缓存失效」两种成因需拆分 | 一致：dev 上属预期行为；prod 栈上才是缺陷 | ✅ 确认 |
| 「后端始终注册 gzip」不会双重压缩 | 一致：Nginx gzip 模块只压无 `Content-Encoding` 的对象（`nginx-windows.conf:66-80`） | ✅ 确认 |
| 3 条 dev 启动路径 | 一致：`server_manager_v533.py:1839` / `server_manager.py:1827` / `start.py:110`，均为默认行为 | ✅ 确认 |
| `FLASK_ENV` 与模式判定无关 | 一致：FastAPI 不读，唯一权威 `config.py:35`；降级为「误导性遗留键」 | ✅ 确认 |
| 计时口径（直连 5002 vs 经 3000） | 一致：后端 ~20ms 级非瓶颈；Nginx 无 keepalive 的开销**当前未生效**（跑的是 dev） | ✅ 确认 |
| P0-1 定性 | 由「偶发误操作」修正为「**3 条入口的默认行为**」→ 必须硬拦截 + 改默认值，不能只 kill 进程 | ✅ 修正 |

### A.2 团队共识表述（可直接引用）

> 1. 「production 慢」这一命题在当前**尚未被有效测量** —— 所有测量都发生在 dev server 上。
> 2. 唯一能证伪/证实的路径：先 `nssm start erp-prod` 起正式栈（Nginx + dist + 8 worker），再做同条件 A/B。
> 3. 在此之前任何「production 慢」的结论都**不可用于定案**。

### A.3 工具环境故障与绕过手法（重要，影响可复现性）

**故障现象**：本次会话末段 **Bash 与 PowerShell 的 stdout 同时失效** ——
- `echo ok` → 空输出、Exit Code 0
- `netstat -ano` / `Get-Process` / `Invoke-WebRequest` 的打印均不回显（Invoke-WebRequest 仅提示「正在读取 Web 响应…读取的字节数: 0」）

**后果**：**任何「命令没输出」都不能当作证据**（「没输出」≠「确实为空」）。qa-perf 亦独立复现此现象。

**可用的绕过手法（已验证有效）**：
```
PowerShell 写文件  →  Read 工具读回文件
例如：$r.Headers | Out-File -Append $f ；再用 Read 读 $f
```
本报告 P0-2 的 `/metrics` 实测数据即经此路径取得（`_probe6.txt`）。

**对后续补测的建议**：在 `nssm start erp-prod` 起正式栈后，先跑一次 `echo ok` 确认 shell 恢复，再取数；若 shell 仍未恢复，直接用上述绕过手法。

### A.4 未完成项（如实用，不做推测填补）

1. **正式生产栈（Nginx + dist + 8 worker）下的压缩/缓存实测** —— 需先 `nssm start erp-prod`。本研究已测**当前 dev+reload 实例**（同为 `APP_ENV=production`、同样不压缩），结论等价；正式栈基线待补。
2. **py-spy 火焰图** —— 环境未安装 `py-spy`/`psutil`，且 `wmic` 被安全策略拦截，未取得 worker 级 CPU 热点。当前判断后端的瓶颈不在此，优先级低。
