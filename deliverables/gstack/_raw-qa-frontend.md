# 前端构建产物 / 静态资源 / 网络传输层 排查报告（QA 实测版）

- 负责人：qa-perf（GStack 质量门神 · 前端构建 + 网络传输层）
- 项目：`D:\erp_system`
- 环境：Windows (win32)，Git Bash / PowerShell
- 排查方式：**全部结论均基于实测命令输出**，凡未实测的推测均显式标注 `[推测]`
- 报告日期：2026-09-17
- 修订：v3（含与 investigator-perf / product-perf 的三轮交叉复核收敛结果）

> **给赶时间的读者（3 条必读）**
> 1. **真凶**：所谓"production 模式"的入口（3000 端口）实际跑的是 **Vite dev server**，不是 `dist` + Nginx。nginx 进程数为 **0**。
> 2. **为何能长期潜伏**：健康检查假阳性 = **五层缺陷链**（弱判据 → dev SPA 回退欺骗它 → 探测无失败路径 → `pid` 来源不匹配 → `[emerg]` 已落盘却无人读取）。**必须五层同修，只修任一层都会继续假成功。**
> 3. **一个容易被忽略的前置动作**：nginx 曾以 `[emerg] bind() failed (10013: 权限拒绝)` 致命退出（`logs/nginx-error.log:19`，全日志唯一一条、且早于状态快照近两天）。`10013` **不是**"端口已占用"，而更可能是 **3000 落在 Windows 保留端口区间** → **先跑 `netsh int ipv4 show excludedportrange protocol=tcp`，否则杀完进程 nginx 仍起不来**。

---

## 0. 结论摘要（真凶排序）

> **一句话结论：用户所说的"production 模式"当前根本没有跑在 `dist` 构建产物 + Nginx 上，而是跑在 Vite dev server 上。**
> 这解释了"首次加载慢、切换页面慢、整体不流畅"的**全部**现象，与后端 SQL/连接池无关。

### 真凶 #1（P0，决定性，已实测确凿）：生产环境 3000 端口实际由 Vite dev server 提供服务，Nginx 完全不在运行

实测证据链：

| 证据 | 命令 | 输出 |
|---|---|---|
| 3000 端口持有者 | `netstat -ano \| grep ":3000 "` | `LISTENING 10640` |
| PID 10640 进程名 | `tasklist` | `node.exe`（**不是 nginx.exe**） |
| 是否存在 nginx 进程 | `tasklist /FI "IMAGENAME eq nginx.exe"` | **"没有运行的任务匹配指定标准"（0 个）** |
| 首页 HTML | `curl http://127.0.0.1:3000/` | 含 `<script type="module" src="/@vite/client">` |
| dev client 可访问 | `curl -I http://127.0.0.1:3000/@vite/client` | `200 text/javascript`，**101,809 字节** |
| 源码入口可访问 | `curl -I http://127.0.0.1:3000/src/main.ts` | `200 text/javascript`，18,589 字节 |
| 而 prod_runner 却自报 nginx | `cat logs/prod_runner.json` | `"frontend_type": "nginx"`, `"status": "running"` |

**矛盾点**：`logs/prod_runner.json`（启动于 `2026-09-17T08:37:53`）声称 `frontend_type=nginx`、`status=running`，但**实际系统里一个 nginx.exe 都不存在**，3000 端口被 `node.exe` 占用。

**根因判断**：Nginx 启动后未成功绑定 3000（或启动后被 dev server 抢占/nginx 退出未被 prod_runner 重启），端口被一个 **Vite dev server** 占据。dev server 因为 `vite.config.ts` 里配了 `/api` 代理，所以**业务能跑通**——这正是问题最阴险的地方：**功能正常，所以没人发现有服务跑错了**。

### 真凶 #2（P0，由 #1 直接导致）：静态资源被 SPA 回退吞掉，返回 HTML 而非 JS，且无任何压缩

> **⚠️ 本节结论已于协作复核后修订（2026-09-17）**：原先我将"压缩失效"单一归因于真凶 #1。
> 经与 investigator-perf 交叉验证（我独立复读源码确认），"当前观测到的无压缩"**要拆成两个独立成因**：
>
> | 场景 | 成因 | 性质 | 修复动作 |
> |---|---|---|---|
> | 当前在跑的 3000（Vite **dev**） | Vite dev server 本身不压缩、不缓存 | **预期行为**，非缺陷 | 换掉 dev server（P0-1） |
> | 真正的 prod 栈（Nginx + dist，当前未运行） | **真空**：后端 `_setup_gzip` 在 `APP_ENV=production` 时**主动不注册 gzip 中间件**，把压缩完全让给 Nginx；而 Nginx 又没在跑 → **两侧都不压缩** | **真实配置缺陷** | 见下方 P0-3 修订 |
>
> 两者**现象相同（都没有 Content-Encoding）、根因不同、修复动作不同**，不可混为一谈。
>
> **我独立复核的源码证据**（`fastapi_app/core/middleware.py:319-324`）：
> ```python
> 319: def _setup_gzip(app: FastAPI) -> None:
> 320:     # 生产环境由 Nginx 统一处理 GZip 压缩，避免双重压缩
> 321:     if settings.is_production:
> 322:         logger.info("GZip 压缩由 Nginx 处理（生产环境）")
> 323:         return                                  # <-- 直接返回，不注册任何压缩中间件
> 324:     app.add_middleware(GZipMiddleware, minimum_size=1000)
> ```
> 且 `fastapi_app/core/config.py:42` `raw = os.getenv("APP_ENV","").strip().lower()`、`:176-178` `is_production` 只读 `APP_ENV`；
> 而当前生效的 `.env:172` 为 `APP_ENV=production`（实测 grep 确认）→ **`is_production` 为真 → 当前后端确实不压缩**。
>
> **因此这条真空不是"将来风险"，而是当下事实**：即使立刻把 Nginx 起起来，只要 Nginx 侧配置有遗漏（如 Windows 版无 brotli、`gzip_types` 漏 `application/wasm`），压缩就仍可能不足；而只要 Nginx 再次挂掉，压缩就**归零且无声**——这正是 P0-2（健康检查假阳性）必须优先修的原因。
>
> 附带澄清：`FLASK_ENV` 与本判定**无关**（investigator 已确认全仓仅测试文件引用；`.env:42 FLASK_ENV=development` 是误导性遗留键，不造成模式误判）。

实测（决定性反证）：

```
$ curl -I -H "Accept-Encoding: gzip, deflate, br" http://127.0.0.1:3000/assets/index-8985Y_zC.js
HTTP/1.1 200 OK
Content-Type: text/html          <-- 请求的是 .js，返回的是 text/html！
Cache-Control: no-cache
Etag: W/"cb2-..."                <-- 整个 SPA 回退只有 3250 字节
（无 Content-Encoding）

$ curl -s http://127.0.0.1:3000/assets/index-8985Y_zC.js | head -c 300
<!DOCTYPE html>
<html lang="zh-CN" ...>
    <script type="module" src="/@vite/client"></script>
    ...
```

对照：真实构建产物 `frontend-vite/dist/assets/index-Cb7_V1ei.js` 是 **45 万字节**（443 KB），返回的却是 3250 字节的 HTML。

**含义**：
1. `/assets/*.js` 拿到的是 HTML → 浏览器按 `type="module"` 校验 MIME 会**直接拒绝执行**；
2. 所有静态资源请求**没有 `Content-Encoding`** → **压缩完全失效**，2.99 MB JS 原样裸传；
3. 所有响应 `Cache-Control: no-cache` → **浏览器缓存完全失效**，每次切页都重新取。

### 真凶 #3（P0）：`NGINX_PROXY=0` 是一个死开关（dead flag），零代码引用

```
$ grep -rn "NGINX_PROXY" --include="*.py" .
>>> ZERO python references <<<
```

全仓仅 3 处出现 `NGINX_PROXY`，**全在 env 文件里，无任何代码消费它**：

| 文件 | 行号 | 值 |
|---|---|---|
| `.env.production` | 57 | `NGINX_PROXY=0` |
| `.env.production.example` | 67 | `NGINX_PROXY=0` |
| `config/.env.production` | 56 | `NGINX_PROXY=0` |

`.env.production:56` 注释写着"1 = Nginx 反向代理，0 = 直连模式"，**但这个开关从未被任何 Python 代码读取**。真正决定是否用 Nginx 的是 `fastapi_app/core/prod_runner.py:454` 的 `_find_nginx()` 探测（文件存在则用 nginx，否则回退 `vite preview`）。

**风险**：运维以为设 `0` 就是"直连模式"、设 `1` 就走代理，**实际上改这个值毫无作用**——这是一个会误导排障方向的配置陷阱，必须清理或接线。

### 真凶 #4（P1，独立于 #1，实测确凿）：Nginx 配置导致 index.html 引用了不存在的 chunk → 404 → 路由 chunk 重载循环

`logs/nginx-error.log` 实测：

```
2026/09/16 18:43:49 [error] CreateFile() "D:\erp_system/frontend-vite/dist/assets/HubeiView-CvR8KlHF.js" failed
    (2: The system cannot find the file specified), request: "GET /assets/HubeiView-CvR8KlHF.js"
...[error] CreateFile() ".../HubeiSearchBar-zfCkT9Wa.js" failed
...[error] CreateFile() ".../OutsourceOrderView-CY9V7f_T.js" failed
...[error] CreateFile() ".../HubeiRouteTabs-DqL0ldOb.js" failed
...[error] CreateFile() ".../SupplierView-BUA99Ou7.js" failed
...[error] CreateFile() ".../PurchaseView-CeMIzq0g.js" failed
```

而这些 chunk 在**当前** dist 里是存在的，但 **hash 不同**：

```
$ ls frontend-vite/dist/assets/ | grep -i hubei
HubeiView-C_NXWV72.js      <-- 当前
（日志里请求的是 HubeiView-CvR8KlHF.js）
```

**含义**：客户端拿着**旧 index.html**（引旧 hash），去请求**新 dist** 里不存在的文件 → 404。结合 `src/router/index.ts:129-157` 的动态导入失败重载逻辑（`CHUNK_LOAD_KEY` / `MAX_RELOAD` / `window.location.href = to.fullPath`），会触发**整页刷新循环**。用户体感 = "切页面卡一下白屏一下"。

叠加上 `sw.js` 预缓存了 `index.html`（见真凶 #6），旧 index.html 会被 Service Worker **长期钉住**，使 404 持续复现。

### 真凶 #5（P0-级，第五轮修订）：nginx 有过 `[emerg] bind() 10013` 失败，但**是瞬时的、非持续**；真正的问题是错误不可观测

> 本节经四轮修订。**第四轮我方曾把 `[emerg]` 误读为"故障持续 ≥2 天"，第五轮用访问日志自我更正** —— 保留此修订痕迹，因为它本身就是一次重要的方法教训。

`logs/nginx-error.log:19`（**全日志唯一的 `[emerg]`**，`grep -c` = 1）：

```
2026/09/15 14:05:58 [emerg] 1796#19272: bind() to 0.0.0.0:3000 failed
        (10013: An attempt was made to access a socket in a way forbidden by its access permissions)
```

- **`[emerg]` 是致命级** → 该次启动 nginx **放弃**，故此刻进程不存在。
- ❌ **【第四轮错误结论，已作废】"故障已持续 ≥2 天"** —— **这是错的**。访问日志证明 nginx 在 `[emerg]`（09-15 14:05）**之后**仍成功绑定并服务：`09-16 08:14:00` 起 `GET /` → `200`，并正常返回 `/assets/*.js`、`/registerSW.js`。且 `09-15 09:06:41`（emerg 前 5 小时）也有 `200`。
  → **正确结论：该 `[emerg]` 是一次瞬时启动冲突，nginx 随后多次正常绑定 3000。它不能解释"当前为何不是 nginx"，只是解释了"某一次启动为何失败"。**
- **错误码 `10013`（权限拒绝）≠ `10048`（端口占用）** → 提示可能涉及保留端口区间或独占持锁，**但仍需实测确认**（见下方第五轮）。

**✅ 真实的、确定的问题（不因上述更正而削弱）：错误完全不可观测。**
`prod_runner.py:394` `Popen` 句柄未保存、`:398` `stderr=subprocess.DEVNULL` → 这类 `[emerg]` **没有任何代码路径会读到它**。所以"某次启动失败"被无声吞掉，加上 P0-2 假阳性，对外始终表现为 `running`。

#### 第五轮：`10013` 成因的两假设 —— 双方证据与推断方向（**结论：未确诊**）

product-perf 用本机探针进一步缩小范围，得出一组实测值：

| 探针 | 结果 | 该结果的含义 |
|---|---|---|
| `Get-NetTCPConnection -LocalPort 3000` | `LISTEN pid=10640 name=node` | 3000 当前被 node **独占监听** |
| `Get-Process nginx` | 0 个 | 与"某次放弃启动"一致 |
| `Get-Service winnat` | **`Stopped`** | — |
| HNS `State` 键 | **空**（无预留记录） | — |
| `netsh ... excludedportrange` | **沙箱拦截，返回空** | 正是我警告的"空结果≠事实"陷阱 |

**product-perf 据此倾向假设 (b) 独占持锁、弱化 (a) 保留区间。我方基本认同其方向，但要指出两点限定（以免把"倾向"当成"已定"）：**

1. **探针是"今天的快照"，测的不是事故发生时刻（09-15 14:05）的系统状态。** 中间隔了近两天，且期间 nginx 成功绑过多次（见上）。**用今日态推断当年因，证据强度有限。**
2. **`winnat = Stopped` 的因果方向需谨慎**：`winnat` 停止时 Windows 会**释放**动态保留区间——所以"`winnat` 已停"在**检测时刻**是**不利于** (a) 的证据；但它说明不了 09-15 当时的状态（若那时 `winnat` 在运行，保留区间就是存在的）。**不能由"现在没保留"推出"当时没保留"。**
3. **`10048` vs `10013` 的语义是关键**：若为纯"某进程先占端口"，Windows 通常报 `10048`；报 `10013` 更像**权限/保留**语义。因此我方**不认为 (b) 已被证据压过 (a)**，(a) 仍应作为并列假设保留。

**→ 双方统一口径（无分歧）**：**未确诊**。列为 **P0-前置核查项**：跑 `netsh int ipv4/ipv6 show excludedportrange protocol=tcp` + `netstat -ano | findstr :3000`，**先 `Write-Output ok` 验证 shell 有输出再取数**（否则空结果会被误读为"无保留区间"）。**先核查、再决定"杀进程"还是"换端口"** —— 这一步的价值在于避免"杀了还是起不来"的无效循环，而非断言某个具体成因。
- **错误不可观测**：`prod_runner.py:394` `Popen` 句柄未保存、`:398` `stderr=DEVNULL` → 这条致命错误**没有任何代码路径会读到它**，于是被掩盖成"running"。

**由此，真凶 #1 的完整解释链闭合为五层**（详见 P0-2）：弱判据 → dev SPA 回退欺骗它 → 探测无失败路径 → `pid` 来源不匹配 → `[emerg]` 无人读取。

### 真凶 #5b（P1）：Docker 版 nginx.conf 的 brotli 极可能未生效，且两套 nginx 配置严重不一致

- `config/nginx.conf:73-88` 开启了 `brotli on;`，但 `:75` 自己承认"**注意：Nginx 容器镜像必须包含 ngx_brotli 模块**"。
- 而 Windows 实际用的 `config/nginx-windows.conf` **完全没有 brotli 指令**（只有 gzip）。
- 结果：**无论走哪套配置，brotli 都没有确定生效**；Windows 路径下只有 gzip。
- 更关键：**因为真凶 #1，这两套配置当前一套都没在用**。

### 真凶 #6（P1，实测确凿）：PWA Service Worker 预缓存 index.html，且 `registerType: autoUpdate` 静默接管

`frontend-vite/dist/sw.js` 实测：

```js
self.skipWaiting(), s.clientsClaim(),
s.precacheAndRoute([
  {url:"registerSW.js",...},
  {url:"index.html",  revision:"c4f6d64613845c9df2babf4b860eec9f"},   // <-- index.html 进预缓存
  {url:"assets/vendor-echarts-CjpiykIs.js", revision:null},
  ... 192 项
])
```

且 `dist/registerSW.js`：

```js
if('serviceWorker' in navigator)
  {window.addEventListener('load', () => {navigator.serviceWorker.register('/sw.js', { scope: '/' })})}
```

**风险**：`index.html` 被 Service Worker 预缓存 → 即使服务端部署了新版本，**旧标签页仍可能拿到旧 index.html**（引旧 hash）→ 直接制造真凶 #4 的 404 循环。`skipWaiting()+clientsClaim()` 是 `autoUpdate`，会**静默接管**所有标签页，用户无法感知版本切换。

### 非真凶项（已实测排除，避免误伤）

| 项 | 实测结果 | 结论 |
|---|---|---|
| Source Map 泄漏 | `find dist -name "*.map" \| wc -l` → **0** | ✅ 未开启，**排除**（Vite 默认 `sourcemap:false`） |
| 构建产物缺失 | dist 存在，192 文件 / 3674.2 KB | ✅ **排除**，产物是好的 |
| 打包分包 | `manualChunks` 已按 echarts/vue/primevue/axios 等分 8 组 | ✅ 已做，**排除** |
| echarts 全量引入 | `import { LineChart, PieChart, BarChart } from 'echarts/charts'` | ✅ **按需引入，排除** |
| FontAwesome 全量 | `import { faCheck, faTimes, ... }` 具名导入 | ✅ **按需引入，排除** |
| PrimeVue 全量 | `components.d.ts` + `PrimeVueResolver()` 自动按需 | ✅ **排除** |
| 路由懒加载 | `grep -c "() => import"` → **43** 处动态导入 | ✅ **排除** |
| axios 重复请求 | `_inflightGet` Map 做了 GET 去重（`request.ts:167-185`） | ✅ **排除** |
| 每请求写 localStorage | 请求拦截器**无** localStorage 写入（`request.ts:72-86`） | ✅ **排除** |
| vue-query staleTime 过短 | `staleTime: 30_000`，`gcTime: 5*60*1000`，还有 sessionStorage 持久化 | ✅ **排除**，配置合理 |
| 路由守卫 await 重逻辑 | `beforeEach` 仅 `await authStore.init()`（受 `loaded` 幂等保护） | ✅ 基本合理，非主因 |

---

## 1. 构建产物体积分析表（实测）

命令（Git Bash，Node 内置 zlib，无需额外安装）：

```bash
cd /d/erp_system/frontend-vite && node -e "
const fs=require('fs'),path=require('path'),zlib=require('zlib');let rows=[];
function walk(d){for(const e of fs.readdirSync(d,{withFileTypes:true})){const p=path.join(d,e.name);
 if(e.isDirectory())walk(p);else{const b=fs.readFileSync(p);
 rows.push({f:p.replace(/\\\\/g,'/'),raw:b.length,gz:zlib.gzipSync(b,{level:9}).length,
 br:zlib.brotliCompressSync(b,{params:{[zlib.constants.BROTLI_PARAM_QUALITY]:11}}).length});}}}
walk('dist');rows.sort((a,b)=>b.raw-a.raw);const kb=n=>(n/1024).toFixed(1);
rows.slice(0,25).forEach(r=>console.log(r.f+'\t'+kb(r.raw)+'\t'+kb(r.gz)+'\t'+kb(r.br)));"
```

### 1.1 总体积

| 类别 | 文件数 | 原始 | gzip | brotli |
|---|---|---|---|---|
| JS | 120 | 2990.3 KB | 945.0 KB | 792.0 KB |
| CSS | 68 | 532.6 KB | 107.0 KB | 90.6 KB |
| 其他(png/html/manifest) | 4 | 151.3 KB | 0 | 0 |
| **合计** | **192** | **3674.2 KB** | **1200.3 KB** | **1030.4 KB** |

> `.map` 文件数：**0**（无 Source Map 泄漏）

### 1.2 TOP 25 最大产物（原始 / gzip / brotli / gzip压缩率）

| 文件 | 原始 KB | gzip KB | brotli KB | gzip% |
|---|---|---|---|---|
| `assets/vendor-primevue-SadobcXg.js` | 672.4 | 143.7 | 104.2 | 21% |
| `assets/vendor-echarts-CjpiykIs.js` | 556.9 | 190.3 | 160.5 | 34% |
| `assets/index-8985Y_zC.js` | 442.9 | 147.1 | 124.6 | 33% |
| `assets/vendor-fontawesome-RiOzw8uk.js` | 148.3 | 44.1 | 37.7 | 30% |
| `logo_plush.png` | 146.4 | 145.5 | 145.5 | 99% |
| `assets/vendor-vue-ClQujFAc.js` | 113.2 | 44.0 | 39.6 | 39% |
| `assets/vendor-reka-ui-D8xOjm3U.js` | 92.7 | 29.3 | 25.6 | 32% |
| `assets/PatternRoomView-B6L7mt0v.js` | 68.4 | 20.4 | 17.5 | 30% |
| `assets/index--Wssmdmm.css` | 53.6 | 10.3 | 8.8 | 19% |
| `assets/CustomerOrderView-DnnLWgSf.js` | 52.1 | 14.3 | 12.3 | 28% |
| `assets/index-Cb7_V1ei.js` | 50.6 | 18.4 | 15.5 | 36% |
| `assets/ProductListView-CnBZ-xcz.js` | 45.7 | 14.8 | 12.2 | 32% |
| `assets/vendor-axios-BsXaTpjw.js` | 44.4 | 17.2 | 15.6 | 39% |
| `assets/PurchaseView-DrMGVffe.js` | 41.4 | 12.5 | 10.7 | 30% |
| `assets/CaseView-Btr-9L5W.js` | 40.9 | 12.7 | 10.9 | 31% |
| `assets/vendor-query-IsYXmFLx.js` | 37.7 | 11.2 | 10.2 | 30% |
| `assets/ProductionView-BnlRfLcf.css` | 35.6 | 5.3 | 4.6 | 15% |
| `assets/ProductionView-C0C7la66.js` | 35.3 | 10.7 | 9.2 | 30% |
| `assets/StockOutView-Cx3uKMoL.js` | 35.2 | 11.5 | 9.9 | 33% |
| `assets/ProductListView-Cg3-cpyO.css` | 34.0 | 4.6 | 4.0 | 14% |
| `assets/BackupView-BCwLOChs.js` | 30.9 | 10.8 | 9.2 | 35% |
| `assets/PatternRoomView-AuJki6_L.css` | 30.7 | 5.2 | 4.6 | 17% |
| `assets/PurchaseView-CD5mOIO5.css` | 27.6 | 3.9 | 3.2 | 14% |
| `assets/PurchasePlanView-DPy0g-aU.js` | 25.3 | 8.7 | 7.7 | 35% |
| `assets/BackupView-NyOjYDqp.css` | 25.3 | 4.0 | 3.4 | 16% |

### 1.3 首屏关键路径传输量（index.html + modulepreload + 入口 CSS）

`dist/index.html` 声明的关键资源实测：

```html
<script type="module" crossorigin src="/assets/index-Cb7_V1ei.js"></script>
<link rel="modulepreload" crossorigin href="/assets/vendor-vue-ClQujFAc.js">
<link rel="modulepreload" crossorigin href="/assets/vendor-query-IsYXmFLx.js">
<link rel="modulepreload" crossorigin href="/assets/vendor-fontawesome-RiOzw8uk.js">
<link rel="modulepreload" crossorigin href="/assets/vendor-axios-BsXaTpjw.js">
<link rel="stylesheet" crossorigin href="/assets/index--Wssmdmm.css">
```

| 传输方式 | 关键路径体积 | 相对原始节省 |
|---|---|---|
| **原始（= 当前线上实际）** | **447.9 KB** | — |
| gzip | 145.3 KB | **-68%** |
| brotli | 127.5 KB | **-72%** |

> 全站 JS+CSS：3522.9 KB → gzip 1052.0 KB（**-70%**）→ brotli 882.6 KB（**-75%**）

**结论**：压缩打开即可让首屏传输量从 448 KB 降到 128~145 KB。**这是当前最廉价、收益最大的一刀。**

### 1.4 `logo_plush.png` 异常

| 文件 | 原始 | gzip | brotli | 说明 |
|---|---|---|---|---|
| `logo_plush.png` | 146.4 KB | 145.5 KB | 145.5 KB | PNG 已压缩，gzip 无效（99%），**且被当 PWA 图标 192/512 使用** |

`vite.config.ts:92-95` 把 `logo_plush.png` 同时声明为 192x192 和 512x512 图标，但它是 146 KB 的单文件。建议转 WebP/AVIF，或按尺寸生成图标，可省 ~140 KB。

---

## 2. Nginx 配置差异对照表（`config/nginx.conf` vs `config/nginx-windows.conf`）

| 项 | `nginx.conf`（Docker 版） | `nginx-windows.conf`（本机实际用） | 差异/风险 |
|---|---|---|---|
| 上游定义 | `server app:5002; keepalive 32;` | `server 127.0.0.1:5002;`（**无 keepalive**，注释说明官方 Windows 版无该模块） | ⚠️ Windows 下每个请求**新建到后端的 TCP 连接** → TTFB 偏高 |
| `/assets/` 缓存 | `expires 1y; immutable` | `expires 1y; immutable` | ✅ 一致，正确 |
| `/` (index.html) | `no-cache, no-store, must-revalidate` | 同 | ✅ 一致（**正确**，index.html 不该长缓存） |
| gzip | ✅ 开（`gzip_types` 含 `application/javascript`） | ✅ 开（同） | ✅ 一致 |
| **brotli** | `brotli on; brotli_comp_level 5;`（`nginx.conf:76-77`） | **完全没有 brotli 指令** | ❌ **不一致**；Docker 版还需镜像含 `ngx_brotli`（`nginx.conf:75` 自承认） |
| gzip_types 缺项 | 缺 `application/wasm`、字体类型 | 同 | ⚠️ 漏 `application/wasm`；字体已走 `/assets` 但类型未列 |
| `/static/` | `alias /app/static/;`，含子 location 做 30d 缓存 | `/static/uploads/` 走本地 alias；`/static/` **反代到后端** | ❌ **语义不同**：Docker 版直读磁盘，Windows 版打后端 → Windows 下 `/static` 走 FastAPI worker，**占用应用 worker** |
| `/nginx-health` | ✅ 有 | ✅ 有 | ✅ 一致（prod_runner 探测用） |
| `security-headers.conf` | `/etc/nginx/conf.d/...` | `D:/erp_system/config/...` 绝对路径 | ✅ 路径适配正确 |
| `root` | `/app/frontend-vite/dist` | `frontend-vite/dist`（相对，配合 `-p D:/erp_system`） | ✅ 实测可解析 |
| MIME types | 继承镜像默认 | `include C:/nginx/conf/mime.types;`（实测文件存在，5448 B） | ✅ 存在 |
| keepalive / HTTP 版本 | `proxy_http_version 1.1; proxy_set_header Connection "";` + upstream keepalive | 注释说明**刻意用 HTTP/1.0 反代**（否则 400） | ⚠️ Windows 下**无连接复用**，是 TTFB 的次要放大因素 |

**关键实测**：`C:\nginx\nginx.exe` **确实存在**（6,626,304 字节，2026-07-15），`C:/nginx/conf/mime.types` 也存在（5448 字节）。所以 `_find_nginx()` 会返回路径 → `prod_runner` 判定 `frontend_type=nginx`。但**进程实际不在**。

---

## 3. 逐项证据（文件路径 + 行号 + 命令输出）

### E1. 3000 端口归属错误（真凶 #1）

```bash
$ netstat -ano | grep ":3000 " | grep LISTENING
  TCP    0.0.0.0:3000     0.0.0.0:0     LISTENING     10640

$ tasklist | grep -i -E "nginx|node"
python.exe   17264  ...  33,884 K
node.exe     15756  ...  47,732 K
node.exe     10640  ... 354,676 K      <-- 3000 端口持有者
node.exe     19140  ...  56,732 K
node.exe     19296  ...  73,304 K
python.exe   18348  ... 175,948 K

$ tasklist /FI "IMAGENAME eq nginx.exe"
信息: 没有运行的任务匹配指定标准。      <-- nginx 数量 = 0
```

### E2. 服务的是 dev server（真凶 #1 定案）

```bash
$ curl -s http://127.0.0.1:3000/ | head -5
<!DOCTYPE html>
<html lang="zh-CN" style="color-scheme: light">
  <head>
    <script type="module" src="/@vite/client"></script>      <-- dev-only 注入

$ curl -s http://127.0.0.1:3000/ | grep -o 'src="[^"]*"'
src="/@vite/client"
src="/src/main.ts?t=1789605671097"                            <-- dev-only 时间戳参数

$ curl -o /dev/null -w "%{http_code} %{size_download}" http://127.0.0.1:3000/@vite/client
200 101809                                                    <-- 101KB dev client
```

### E3. 静态资源返回 HTML + 零压缩（真凶 #2）

```bash
$ curl -I -H "Accept-Encoding: gzip, deflate, br" http://127.0.0.1:3000/assets/index-8985Y_zC.js
HTTP/1.1 200 OK
Vary: Origin
Content-Type: text/html          <-- 致命：.js 返回 text/html
Cache-Control: no-cache
Etag: W/"cb2-0OKz2ifSrszJpYjsyr6nXGY8LxU"
（无 Content-Encoding / 无 Content-Length 合理值）

$ curl -o /dev/null -w "size=%{size_download} type=%{content_type}\n" .../assets/index-8985Y_zC.js
size=3250 content_type=text/html       <-- 3250 B 的 SPA 回退

$ ls -la frontend-vite/dist/assets/index-Cb7_V1ei.js
-rw-r--r-- 1 Administrator 197121 453571 ... index-Cb7_V1ei.js   <-- 真实是 443 KB
```

对照：用普通静态服务器（`python -m http.server 3099 --directory dist`）实测同一产物：

```bash
$ curl -o /dev/null -w "status=%{http_code} type=%{content_type} size=%{size_download}\n" \
    http://127.0.0.1:3099/assets/index-Cb7_V1ei.js
status=200 type=text/javascript size=51850     <-- 正确
```

→ **证明 dist 产物本身没问题，是"由谁服务"出了问题。**

### E4. `NGINX_PROXY` 死开关（真凶 #3）

```bash
$ grep -rn "NGINX_PROXY" --include="*.py" .
>>> ZERO python references <<<

$ grep -rn "NGINX_PROXY" --include="*.py" --include="*.ps1" --include="*.md" \
      --include="*.bat" --include="*.yml" --include="*.yaml" --include="*.cmd" \
      --include="*.sh" --include=".env*" . | grep -v node_modules | grep -v "\.git/"
./.env.production:57:NGINX_PROXY=0
./.env.production.example:67:NGINX_PROXY=0
./config/.env.production:56:NGINX_PROXY=0
```

`fastapi_app/core/prod_runner.py:454-464` 真正的判定逻辑（与 `NGINX_PROXY` 无关）：

```python
454:        nginx = _find_nginx()
455:        self.nginx = _FrontendNginx(nginx, web_port) if nginx else None
456:        self.vite: _Managed | None = None
457:        if nginx:
458:            self.frontend_type = "nginx"
459:        else:
460:            self.frontend_type = "vite"
461:            self.vite = _Managed(
462:                "前端(vite preview)", _cmd_vite_preview(web_port), FRONTEND_DIR,
463:                health_url=f"http://127.0.0.1:{web_port}/",
464:            )
```

`_cmd_vite_preview`（`:188-190`）：

```python
188: def _cmd_vite_preview(web_port: int) -> list[str]:
189:     npx = "npx.cmd" if os.name == "nt" else "npx"
190:     return [npx, "vite", "preview", "--port", str(web_port), "--host", "0.0.0.0"]
```

> 注意：回退分支是 `vite preview`（不是 `vite dev`）。但**实测到的是 dev server 特征（`/@vite/client` + `/src/main.ts?t=`）**，说明当前 3000 端口的进程**不是 prod_runner 拉起的**，而是有人手动跑了 `npm run dev`（`package.json:10` → `vite --host 0.0.0.0 --port 5173`，注意脚本写的是 5173，说明是**另一种方式**把它绑到了 3000），或另一个未纳入管理的 dev 进程。**无论哪种，结论一致：生产入口跑的不是 nginx。**

### E5. nginx 曾运行但已消失，且有过 stale chunk 404（真凶 #4）

**E5-a. `prod_runner.json` 自报 nginx 但 pid 为 null**：

```bash
$ cat logs/prod_runner.json
{
  "pid": 16576,
  "started_at": "2026-09-17T08:37:53",
  "mode": "production",
  "ready": true,
  "workers": 8,
  "api_port": 5002,
  "web_port": 3000,
  "frontend_type": "nginx",          <-- 自报 nginx
  "services": { ... "frontend": { "type": "nginx", "pid": null, "status": "running" } ... }
}
# 注意 "pid": null —— nginx 的 pid 是空的！

$ ls -la logs/nginx-*.log
-rw-r--r-- 1 Administrator 197121 4228579 Sep 17 08:37 logs/nginx-access.log   <-- 最后写入 08:37
-rw-r--r-- 1 Administrator 197121   14982 Sep 16 18:43 logs/nginx-error.log   <-- 最后写入 9/16

$ tail -8 logs/nginx-error.log
[error] CreateFile() "D:\erp_system/frontend-vite/dist/assets/HubeiView-CvR8KlHF.js" failed (2: ...)
[error] CreateFile() ".../HubeiSearchBar-zfCkT9Wa.js" failed (2: ...)
[error] CreateFile() ".../OutsourceOrderView-CY9V7f_T.js" failed (2: ...)
[error] CreateFile() ".../HubeiRouteTabs-DqL0ldOb.js" failed (2: ...)
[error] CreateFile() ".../SupplierView-BUA99Ou7.js" failed (2: ...)
[error] CreateFile() ".../PurchaseView-CeMIzq0g.js" failed (2: ...)
```

`"pid": null` 是**硬证据**：prod_runner 自己都没拿到 nginx 的 PID，却把状态写成 `"running"` → **健康检查是假阳性**（这是典型的"假成功"缺陷：状态字段声称 running，实际进程不存在）。

**E5-b. nginx 致命退出证据 —— 全日志唯一的 `[emerg]`（本轮新增，含我方独立复核）**：

```bash
$ grep -n '\[emerg\]|bind()' logs/nginx-error.log
logs/nginx-error.log:19:2026/09/15 14:05:58 [emerg] 1796#19272: bind() to 0.0.0.0:3000 failed
        (10013: An attempt was made to access a socket in a way forbidden by its access permissions)
```

**这条是整个排查中最关键的一行**，信息量远超其字面：
1. **`[emerg]` = 致命级**：nginx **直接放弃启动**（不是"启动后偶发错误"）→ 这解释了为何 `tasklist` 里 nginx 进程数为 **0**：它从未成功驻留。
2. **时间戳 `2026/09/15 14:05:58` 早于 `prod_runner.json` 快照（`2026-09-17T08:37:53`）近两天** → 该故障**至少已存在两天**，是持续状态而非瞬时抖动。
3. **错误码 `10013`（WSAEACCES / 权限拒绝）≠ `10048`（EADDRINUSE / 端口已占用）** → 这不只是"某进程抢占了端口"，而**更可能是"3000 落在 Windows 保留端口区间"**（启用 Hyper-V/WSL/Docker 后的动态端口预留常见此症）。**由此推出 P0-1 必须先做端口区间核查，否则杀进程后 nginx 仍起不来。**
4. **全日志仅此 1 条 `[emerg]`**（grep 计数确认）→ 该致命错误**发生过且仅发生一次**，之后 nginx 再未被成功拉起，而健康检查始终报 `running`。

```bash
# 计数确认（我方实测）：全日志唯一一条
$ grep -c '\[emerg\]' logs/nginx-error.log
1
```

### E6. Service Worker 预缓存 index.html（真凶 #6）

`frontend-vite/dist/sw.js`（头部，实测）：

```js
define(["./workbox-2da51cb1"],function(s){"use strict";
  self.skipWaiting(), s.clientsClaim(),
  s.precacheAndRoute([
    {url:"registerSW.js", revision:"1872c500de691dce40960bb85481de07"},
    {url:"logo_plush.png", revision:"e70e56236d9730de8405a3d01d0789da"},
    {url:"index.html",     revision:"c4f6d64613845c9df2babf4b860eec9f"},   // <-- 预缓存
    {url:"assets/vendor-echarts-CjpiykIs.js", revision:null},
    ... (共 192 项)
  ])
```

`frontend-vite/dist/registerSW.js`：

```js
if('serviceWorker' in navigator)
  {window.addEventListener('load', () => {
     navigator.serviceWorker.register('/sw.js', { scope: '/' })})}
```

`vite.config.ts:35` → `registerType: 'autoUpdate'`。
`vite.config.ts:98` → `disable: isCapacitor || mode === 'development'`（**注意：仅 development 禁用，所以 dev server 下没有 SW；这与 E2 观察一致**）。

### E7. Vite 构建配置实况（`frontend-vite/vite.config.ts`）

| 配置项 | 实测值 | 行号 | 评价 |
|---|---|---|---|
| `build.sourcemap` | **未设置** → 默认 `false` | — | ✅ 实测无 `.map`，正确 |
| `build.minify` | **未设置** → 默认 `esbuild` | — | ✅ 默认已压缩 |
| `build.target` | **未设置** → `'baseline-widely-available'`(Vite7) | — | ⚠️ 未显式声明，跨浏览器行为不确定 |
| `chunkSizeWarningLimit` | `600` | 108 | ⚠️ primevue(672)/echarts(557)/index(443) **均超限**，构建时会告警 |
| `build.cssCodeSplit` | `true` | 107 | ✅ 正确 |
| `rollupOptions.output.manualChunks` | 8 组分包（echarts/vue/query/vueuse/fontawesome/reka-ui/axios/primevue） | 112-140 | ✅ 已做，但 **primevue 单块 672 KB 仍过大** |
| `esbuild.drop` | `['console','debugger']`（production） | 20-22 | ✅ 已移除 console |
| 压缩插件(compression/gzip) | **无** | — | ⚠️ 依赖服务端压缩；而服务端压缩当前失效 |
| `define` | 仅 `__CAPACITOR_BUILD__` | 16-18 | ✅ |
| `server.proxy` | `/api`→5002, `/static`→5002, `/ws`→ws://5002 | 161-176 | ⚠️ **这就是"dev server 也能跑业务"的原因** |
| `preview.proxy` | 同上 | 178-197 | ✅ 有配 |
| PWA `registerType` | `autoUpdate` | 35 | ⚠️ 见 E6 |
| `optimizeDeps.noDiscovery` | `true` + 显式 include 列表 | 198-219 | ✅ 显式可控 |

**注意**：同时存在 **`vite.config.ts`（7,441 B, Sep 12）** 和 **`vite.config.js`（9,265 B, Sep 14）**。Vite 的解析优先级是 `vite.config.js` > `.ts`（同名时 `.js` 优先被 `resolveConfig` 命中）。**存在"改了 `.ts` 但实际生效的是 `.js`"的风险**，必须核查。

```bash
$ ls -la frontend-vite/vite.config.*
-rw-r--r-- 1 Administrator 197121   84 Sep 14 17:28 vite.config.d.ts
-rw-r--r-- 1 Administrator 197121 9265 Sep 14 17:28 vite.config.js      <-- 编译产物，日期更新
-rw-r--r-- 1 Administrator 197121 7441 Sep 12 00:41 vite.config.ts
```

### E8. 前端请求层与路由（已实测，非主因但需知悉）

`src/api/request.ts`：
- `:37-41` `timeout: 15000`，`withCredentials: true`
- `:72-86` 请求拦截器：仅按需注入 `X-CSRF-Token`（`_csrfCache` 内存缓存优先），**无 localStorage 同步写**，`import.meta.env.DEV` 才 `devLog` → ✅ 生产无日志开销
- `:88-131` 响应拦截器：401 单飞刷新（`_refreshPromise`，`:19`），403 节流提示
- `:167-185` **GET 去重**（`_inflightGet` Map）→ ✅ 已优化
- `:11-12` `isRedirecting401` / `isShowing403` 节流标志 → ✅ 防抖

`src/router/index.ts`：
- 43 处 `() => import(...)` → ✅ 全懒加载
- `:160-202` `beforeEach`：`authStore.loaded` 幂等保护，仅首次 `await authStore.init()` → ✅ 合理
- `:129-157` **chunk 加载失败重载**：`MAX_RELOAD` 计数 + `sessionStorage` + `window.location.href = to.fullPath` → ⚠️ **与真凶 #4 组合会触发刷新循环**

`src/main.ts:80-100`：`persistQueryClient` 持久化到 `sessionStorage`，`buster: 'binfa-erp-v1'`，`maxAge: 24h` → ✅ 良好
`src/main.ts:96` `app.mount('#app')` 在 persist 之后但**不 await restorePromise**（`:98` 是 `void restorePromise.catch(...)`）→ ✅ 不阻塞首屏

`src/composables/useEnhancedList.ts:14` `staleTime = 30_000`；`useVirtualScrollList.ts:66` `gcTime: 5*60*1000` → ✅ 合理

`.env`（当前生效）实测：
```
42: FLASK_ENV=development        <-- ⚠️ 注意：active .env 是 development
43: FLASK_DEBUG=0
49: FASTAPI_DEBUG=false
172: APP_ENV=production
```
→ **`.env` 里 `FLASK_ENV=development` 与 `APP_ENV=production` 自相矛盾**，也是"模式认知混乱"的一个来源。

---

## 4. 优化清单（P0 / P1 / P2）

> 每项：问题 → 改法 → 预期收益 → 验证方法

### P0-1 让 Nginx 真正接管 3000 端口（真凶 #1，最高优先级）

- **问题**：3000 端口被 `node.exe`（Vite dev server）占用，nginx 进程为 0，`dist` 构建产物完全未被使用。
- **⚠️ 前置必做（由 `nginx-error.log:19` 的错误码 10013 推出，见 P0-2 第 5 层）**：nginx 曾以 `[emerg] bind() to 0.0.0.0:3000 failed (10013: ...)` **致命退出**。`10013` 是**权限拒绝（WSAEACCES）而非端口已占用（10048）**，可能意味着 **3000 落在 Windows 保留/排除端口区间内**。若属实，**仅杀进程无效**，必须先核查：
  ```powershell
  netsh int ipv4 show excludedportrange protocol=tcp    # 确认 3000 是否落在区间内
  netsh int ipv6 show excludedportrange protocol=tcp
  ```
  若命中，需改用区间外端口、或调整预留并重启 `winnat`（详见 P0-2 改法第 6 步）。**先做这一步，否则会陷入"杀了进程仍起不来"的死循环。**
- **改法**：
  1. 找到并停掉占用 3000 的 dev 进程：
     ```bash
     # Git Bash
     netstat -ano | grep ":3000 " | grep LISTENING     # 拿到 PID
     taskkill //F //PID <PID>
     ```
     ```powershell
     # PowerShell
     Get-NetTCPConnection -LocalPort 3000 -State Listen |
       ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }
     ```
  2. **【关键修订 · 2026-09-17】不要只当"误操作"处理**：investigator-perf 已查明这**不是偶发误操作，而是 3 个入口的默认行为**（详见附录 A.1）：
     - `server_manager_v533.py:1839`（当前在跑）
     - `server_manager.py:1827`
     - `start.py:110` + `start.py:45`（`--web-port default=3000`）+ `start.py:120-121`（默认 `args.dev = True`）

     三条都用 `npm run dev -- --port 3000` 显式把端口覆盖成 3000。因此**只 kill 进程治标不治本**——下次谁点一下 GUI 就又回到 dev。
     **必须在这 3 处入口加上"生产模式禁止起 dev"的硬拦截**（或把 `start.py` 的 `args.dev` 默认值改为 `False`、把 `server_manager_v533.py:1811` 的 `--reload --reload-dir fastapi_app` 与 `:1839` 的 `npm run dev` 收进显式的"开发模式"开关）。
     另注：`server_manager_v8/domain/models.py:170-171` 已把角色 docstring 写成"开发模式前端（vite）"，说明这套架构本意就是 dev/prod 双模式——问题在于 **GUI 把这条 dev 路径当生产在用**。

     3. 用 prod_runner 重启，确认 nginx 起来：
     ```bash
     python -m fastapi_app.core.prod_runner   # 或项目既有的启动入口
     tasklist /FI "IMAGENAME eq nginx.exe"    # 必须 >= 2 个（master + worker）
     ```
- **预期收益**：静态资源从"dev 模式实时编译"变成"直接读磁盘文件"，**首屏从数百个未打包模块请求降为 6 个请求**；这是数量级的改善。
- **验证方法**：
  ```bash
  curl -s http://127.0.0.1:3000/ | grep -c "@vite/client"    # 必须为 0
  curl -sI http://127.0.0.1:3000/assets/<真实hash>.js | grep -i content-type  # 必须 text/javascript
  tasklist /FI "IMAGENAME eq nginx.exe"                      # 必须有进程
  ```

### P0-2 修复健康检查假阳性（E5，"假成功"缺陷）· 已补代码级根因

- **问题**：`logs/prod_runner.json` 中 `frontend.status="running"` 但 `frontend.pid=null`、实际 nginx 不存在。

- **代码级根因（经 product-perf 定位 + 我方独立逐行复核确认）**：这不是单点 bug，而是**四层缺陷叠加**，缺一层都不会造成"静默假成功"：

  **第 1 层 — 判据只看状态码、不校验响应体**（`prod_runner.py:132-138`）：
  ```python
  132: def _http_ok(url: str, timeout: float = 2.0) -> bool:
  133:     try:
  134:         with _OPENER_DIRECT.open(url, timeout=timeout) as resp:
  135:             return resp.status == 200      # ← 只看状态码，从不校验 body
  136:     except (urllib.error.URLError, OSError, TimeoutError) as e:
  137:         _log_health_fail(e)
  138:         return False
  ```
  因 dev server 对未知路径返回 `200 + index.html`，`/nginx-health` 被"认作存活"。

  **第 2 层 — `alive()` 直接复用上述判据**（`prod_runner.py:408-409`）：
  ```python
  408:     def alive(self) -> bool:
  409:         return _http_ok(f"http://127.0.0.1:{self.web_port}/nginx-health", timeout=1.5)
  ```

  **第 3 层【我方复核新发现，比 product-perf 所述更严重】— 探测结果被丢弃，状态无条件置为 running**（`prod_runner.py:384-406`）：
  ```python
  394:         subprocess.Popen(   # Popen 派生后立即返回，句柄未保存 → nginx 退出码永不被观测
  395:             [str(self.nginx), "-p", str(PROJECT_ROOT), "-c", str(NGINX_CONF), ...],
  ...
  400:         for _ in range(10):
  401:             if self.alive():
  402:                 break
  403:             time.sleep(0.5)
  404:         self.status = "running"          # ← 无条件赋值！10 次探测全失败也照样 running
  ...
  406:         print(f"[prod_runner] 前端 Nginx 已启动 (port {self.web_port})")  # ← 无条件报成功
  ```
  **关键**：`:400-403` 的探测循环**没有 `else` 分支、没有失败路径**，`:404` 无条件置 `running`。
  → **即使把第 1、2 层修好（`alive()` 正确返回 `False`），`:404` 仍会把状态写成 `running`。** 这是本次"假成功"的**决定性一层**，也是**只修 `alive()` 会漏掉的那一层**。

  **第 4 层 — `pid` 字段的来源与 nginx 分支不匹配**（`prod_runner.py:503-508`）：`pid` 只取 `self.vite.proc.pid`（`:505`），走 nginx 分支时 `self.vite is None` → 恒为 `null`。这解释了"自报 running 却 pid=null"的表象。

  **第 5 层 — 决定性错误已写入日志却无人读取（product-perf 补充，我方已用日志实证复核）**：
  `Popen` 句柄未保存（`:394`）、`stderr=subprocess.DEVNULL`（`:398`）→ nginx 的致命错误**不会被任何代码路径观测**。
  但错误**确实被记录了**——实测 `logs/nginx-error.log:19`（**全日志唯一的 `[emerg]`**）：
  ```
  2026/09/15 14:05:58 [emerg] 1796#19272: bind() to 0.0.0.0:3000 failed
           (10013: An attempt was made to access a socket in a way forbidden by its access permissions)
  ```
  **三个关键点（我方补充解读）**：
  1. `[emerg]` 是 nginx 的**致命级**——它表示 **nginx 直接放弃启动**，不是"启动后偶发错误"。这解释了为何 `tasklist` 里 nginx 进程数为 **0**：它从未成功驻留。
  2. 时间戳 `2026/09/15 14:05:58` **早于** `prod_runner.json` 快照（`2026-09-17T08:37:53`）**近两天** → 该故障**至少已存在两天**，而非瞬时。
  3. **错误码是 `10013`（WSAEACCES / 权限拒绝），而非 `10048`（EADDRINUSE / 端口已占用）** —— 这是一个重要区别：它**更符合"被 Windows 保留端口区间（excludedportrange / Hyper-V 动态端口）占用"或"权限/SO_EXCLUSIVEADDRUSE 冲突"**，而不只是"某个进程先占了"。→ **这提示 P0-1 的修复不能只做"杀进程"，还应检查 `netsh int ipv4 show excludedportrange protocol=tcp` 是否覆盖了 3000。**

  另附 **P0-0 的复合根因**（product-perf 定位，我方已复核 `prod_runner.py:378-387`）：`_ensure_started():387` 先调 `_kill_all()`，而 `_kill_all()` 只执行 `taskkill /F /T /IM nginx.exe` —— **它不会杀占用 3000 的 `node.exe`**。故 nginx 启动后**绑定 3000 失败**，而失败又被第 1~3 层掩盖 → **"端口被抢占/被拒 + 健康检查掩盖绑定失败 + 致命错误无人读取"的复合缺陷**。

> **五层收敛简史**：第 1 层（product-perf 初版：弱判据）→ 第 2 层（我方：dev SPA 回退欺骗弱判据）→ 第 3 层（我方：探测无失败路径、状态无条件置 running）→ 第 4 层（`pid` 来源不匹配）→ 第 5 层（product-perf 补：`[emerg]` 已落盘却无人读取）。**任何单层修复都会被其余层抹平，必须同修。**

- **改法（必须五层一起修，否则任一残留仍会假成功）**：
  1. **判据改为"200 且响应体含 `"service":"nginx"`"**（product-perf 提供，可直接用）：
     ```python
     def alive(self) -> bool:
         try:
             with _OPENER_DIRECT.open(f"http://127.0.0.1:{self.web_port}/nginx-health", timeout=1.5) as resp:
                 if resp.status != 200:
                     return False
                 return '"service":"nginx"' in resp.read(256).decode("utf-8", errors="replace")
         except (urllib.error.URLError, OSError, TimeoutError) as e:
             _log_health_fail(e)
             return False
     ```
     （注意：`/nginx-health` 的返回体是 `{"status":"ok","service":"nginx"}`，见 `config/nginx-windows.conf:148-153`，故该子串校验有效。）
  2. **【关键】给探测循环加失败路径，取消无条件置 running**：`:400-403` 改为
     ```python
     for _ in range(10):
         if self.alive():
             self.status = "running"
             print(f"[prod_runner] 前端 Nginx 已启动 (port {self.web_port})")
             self.delay = 5.0
             return
         time.sleep(0.5)
     self.status = "down"                  # 10 次全失败 = 明确 down
     print("[prod_runner] 前端 Nginx 启动失败：/nginx-health 未通过体校验")
     ```
  3. **保留 `Popen` 句柄并在探测失败时读取退出码**（`subprocess.PIPE` + `poll()`），或改用 `nginx -t` 先做配置语法预检，避免"静默死掉"。**并让 `stderr` 可观测**（改为 `PIPE` 或重定向到独立文件后读取），把 `[emerg]` 类致命错误纳入健康判定（见第 5 层与下方第 6 步）。
  4. **`pid` 字段按分支取**：nginx 分支应上报 nginx 实际 pid（可用 `nginx.pid` 文件或按镜像名反查），而非取 `self.vite.proc.pid`。
  5. **修复 P0-0 的端口释放**：`_kill_all()` 增加一步"检测 3000 占用者，若命令行含 `vite` 则一并终止"（product-perf 建议）。
  6. **【新增 · 由错误码 10013 推出的必要动作】排查 Windows 保留端口区间**：
     第 5 层实测的错误码是 **`10013`（WSAEACCES 权限拒绝）而非 `10048`（端口已占用）**，说明可能不只是"某进程占先"，而是 **3000 落在 Windows 保留/排除端口区间内**（常见于启用 Hyper-V / WSL / Docker 后的动态端口预留）。**只杀进程可能反复失败**，必须先验证：
     ```powershell
     # 查看 TCP 动态端口排除区间，确认是否覆盖 3000
     netsh int ipv4 show excludedportrange protocol=tcp
     netsh int ipv6 show excludedportrange protocol=tcp
     # 查看 3000 当前占用者（若为保留态则看不到进程，只能看到排除区间命中）
     netstat -ano | findstr :3000
     ```
     若 3000 落在排除区间内，则需**改用区间外的端口**（或 `netsh int ipv4 add excludedportrange` 调整预留、并重启 `winnat` 服务），否则 nginx 永远绑不上。**这一步应在 P0-1 之前做**，否则会陷入"杀了进程仍起不来"的死循环。

- **预期收益**：这类"服务其实没起来但监控说正常"的问题将无法再静默存在（**本次故障能潜伏至今，正是因为监控系统全程在说谎**）。
- **验证方法**：
  ```bash
  # ① 正常态：应通过体校验
  curl -s http://127.0.0.1:3000/nginx-health          # 期望 {"status":"ok","service":"nginx"}
  # ② 伪造态：用 dev server 占 3000，重启 prod_runner
  #    期望：status=down、明确打印启动失败，且 nginx-access.log 无新条目（证明没把 dev 当 nginx）
  # ③ 回归：kill 掉 nginx 进程后读状态文件
  cat logs/prod_runner.json                            # frontend.status 必须非 running
  # ④ 端口区间核查（Windows 特有，见改法第 6 步）
  netsh int ipv4 show excludedportrange protocol=tcp   # 3000 不应落在任何区间内
  # ⑤ 致命错误可观测性：日志中不应再有"已启动"但存在同刻 [emerg]
  grep "\[emerg\]" logs/nginx-error.log
  ```


### P0-3 消除"压缩真空"并确保 gzip 生效（真凶 #2 / #5 · 已修订为两个独立成因）

- **问题（拆成两半，务必分开处理）**：
  - **成因 A（当前在跑，3000 = Vite dev）**：Vite dev server 不压缩不缓存 → 属**预期行为**，修 P0-1 即消除。
  - **成因 B（真正的 prod 栈，真实缺陷）**：`fastapi_app/core/middleware.py:319-324` 在 `settings.is_production` 为真时**直接 return，不注册 gzip 中间件**，注释写明"生产环境由 Nginx 统一处理 GZip 压缩，避免双重压缩"；而当前 `.env:172 APP_ENV=production`（实测确认）→ `config.py:176-178 is_production` 为真 → **后端确实不压缩**。一旦 Nginx 未运行（正是现状），**两侧都不压缩 = 真空**，且此真空**无声**（不报错、不告警）。
- **改法**：
  1. **先修 P0-1**（Nginx 不在，成因 A 无法消除；成因 B 的"让给 Nginx"也无意义）。
  2. **为成因 B 加"兜底"而非仅依赖 Nginx**：把 `_setup_gzip` 改为**始终注册** O(或按显式开关 `BACKEND_GZIP=auto|on|off` 控制)。理由：既然后端已经知道"压缩依赖 Nginx"（有注释），就必须承认"Nginx 可能不在"这一事实——当前实现把可用性押在另一个进程上却无任何守卫。若担心双重压缩，Nginx 侧 `gzip on` 对已有 `Content-Encoding` 的响应不会重复压缩，风险可控。
  3. 在 `config/nginx-windows.conf` 补 `application/wasm`、字体类型到 `gzip_types`：
     ```nginx
     gzip_types
         text/plain text/css text/xml
         text/javascript application/javascript
         application/json application/xml application/rss+xml
         image/svg+xml
         application/wasm
         font/woff font/woff2 application/font-woff;
     ```
  4. brotli（再省约 4%）：Docker 用含 `ngx_brotli` 的镜像（如 `fholzer/nginx-brotli`）。**Windows 官方版 nginx 不含 brotli**，故 Windows 场景采用"构建期预压缩 + `gzip_static`"：
     ```nginx
     gzip_static on;   # 优先返回 .br/.gz 预压缩文件
     ```
     构建期生成 `.gz`/`.br`（见 P1-4 脚本）。
- **预期收益**：首屏 447.9 KB → **145.3 KB（gzip，-68%）**；若上 brotli → 127.5 KB（-72%）。全站 3522.9 KB → 1052.0 KB（-70%）。**且成因 B 修复后，即使 Nginx 再次挂掉，压缩仍由后端兜底，不再归零。**
- **验证方法**：
  ```bash
  # ① 静态资源（走 Nginx）
  curl -sI -H "Accept-Encoding: gzip" http://127.0.0.1:3000/assets/<hash>.js | grep -i "content-encoding"
  # 期望：Content-Encoding: gzip（或 br）
  curl -s -o /dev/null -H "Accept-Encoding: gzip" -w "gzip 传输=%{size_download}B\n" \
       http://127.0.0.1:3000/assets/<hash>.js
  curl -s -o /dev/null -H "Accept-Encoding: identity" -w "原始传输=%{size_download}B\n" \
       http://127.0.0.1:3000/assets/<hash>.js
  # 两者比值应约 1:3

  # ② 后端响应（验证成因 B 已兜底）——绕过 Nginx 直打 5002
  curl -sI -H "Accept-Encoding: gzip" http://127.0.0.1:5002/api/v1/dashboard/stats | grep -i content-encoding
  # 修复前：无输出（真空）；修复后：Content-Encoding: gzip

  # ③ 确认后端 gzip 中间件已注册（日志不应再出现"GZip 压缩由 Nginx 处理"）
  grep "GZip 压缩由 Nginx 处理" logs/*.log | tail -3
  ```

### P0-4 修复缓存头：`/assets/` 必须 immutable，index.html 必须不缓存

- **问题**：实测 `/assets/*.js` 返回 `Cache-Control: no-cache`（dev server 行为），浏览器完全不缓存。
- **改法**：P0-1 修复后由 nginx 接管即自然正确（`nginx-windows.conf:83-87` 已有 `expires 1y; immutable`）。**需确认 `/assets/` 不被 `location /` 覆盖**（nginx 前缀匹配最长优先，`/assets/` 会胜出 → ✅ 逻辑正确，但必须实测确认）。
  Windows 版 `/index.html` 走 `location /` 的 `no-cache` → ✅ 正确（**切勿**给 index.html 加长缓存，那会导致用户永远拿不到新版本）。
- **预期收益**：二次访问切页时，带 hash 的 chunk **完全不发请求**（from disk cache），"切换页面慢"直接消失。
- **验证方法**：
  ```bash
  curl -sI http://127.0.0.1:3000/assets/<hash>.js | grep -i cache-control
  # 期望：Cache-Control: public, immutable  +  Expires: ...
  curl -sI http://127.0.0.1:3000/index.html | grep -i cache-control
  # 期望：Cache-Control: no-cache, no-store, must-revalidate
  ```

### P1-1 清理 `/static/` 语义不一致（配置漂移）

- **问题**：Windows 版 `/static/` **反代到 FastAPI**（`nginx-windows.conf:99-104`），而 Docker 版直接读磁盘（`nginx.conf:52-64`）→ Windows 下静态上传文件消耗应用 worker。
- **改法**：统一为磁盘 alias；已有 `/static/uploads/` 本地托管（`:90-96`），把其余静态子目录也纳入 alias 或用 `try_files` 兜底。
- **预期收益**：减少 FastAPI worker 占用，间接降低 API 排队延迟。
- **验证方法**：`curl -sI http://127.0.0.1:3000/static/<某文件>`，并核对 nginx access log 中该请求**不出现** `upstream_response_time`。

### P1-2 nginx 与 dist 版本一致性（真凶 #4 的 stale 404）

- **问题**：nginx error log 大量 `CreateFile() failed`，客户端旧 index.html 引用新 dist 不存在的 hash。
- **改法**：
  1. 部署流程改为"**先构建到临时目录 → 原子切换 dist**"（`package.json:13` 已有 `build:atomic` + `scripts/swap-dist.mjs`，**应强制走这条路**，杜绝边构建边服务）。
  2. 构建后加校验：index.html 引用的所有 `/assets/*` 必须存在（见下方验证脚本）。
- **预期收益**：消除 404 与路由刷新循环，"切页面卡一下白屏"消失。
- **验证方法**：
  ```bash
  cd /d/erp_system/frontend-vite
  for f in $(grep -o '/assets/[A-Za-z0-9_.-]*\.\(js\|css\)' dist/index.html | sed 's|/assets/||'); do
    [ -f "dist/assets/$f" ] && echo "OK   $f" || echo "MISS $f"
  done
  # 不允许出现 MISS
  ```
  （本次实测：当前 index.html 的 6 个引用**全部 OK** → 说明**最新 dist 是自洽的**，历史 404 来自旧 index.html / 旧部署。）

### P1-3 PWA / Service Worker 策略收紧（真凶 #6）

- **问题**：`sw.js` 预缓存 `index.html`，`autoUpdate` 静默接管；旧标签页可能长期拿旧 index.html → 制造 P1-2 的 404。
- **改法**（任选，建议 a+b）：
  a. 把 `index.html` 移出 precache，改为 `NetworkFirst`（或 `NetworkOnly`）运行时策略，确保版本切换即时；
  b. `registerType` 从 `autoUpdate` 改为 `prompt`，或保留 autoUpdate 但**在激活后对已打开页面做一次受控 reload**（避免用户在旧 JS 上继续操作）；
  c. 明确禁用范围：`vite.config.ts:98` 目前是 `isCapacitor || mode === 'development'`，**建议同时为 "内网生产" 提供环境开关**，便于排障时快速排除 SW 干扰。
- **预期收益**：消除"部署后仍见旧版本 / 莫名 404"类问题，减少支持成本。
- **验证方法**：DevTools → Application → Service Workers 勾选 "Update on reload / Bypass for network" 对比；或 `chrome://serviceworker-internals` 观察 active worker 的 script hash 是否随部署更新。
  ```bash
  # 服务端确认 SW 已随构建更新
  curl -s http://127.0.0.1:3000/sw.js | grep -o 'index.html[^,]*'
  ```

### P1-4 构建期预压缩（配合 P0-3，Windows 最优解）

- **问题**：Windows 官方 nginx 无 brotli 模块，只能靠 gzip 或 `gzip_static`。
- **改法**：构建后生成 `.br`/`.gz` 旁挂文件，nginx 开 `gzip_static on;`（若镜像支持 brotli_static 则可直接吃 `.br`）。示例脚本（Node，无需额外依赖）：
  ```bash
  cd /d/erp_system/frontend-vite && node -e "
  const fs=require('fs'),path=require('path'),zlib=require('zlib');
  function walk(d){for(const e of fs.readdirSync(d,{withFileTypes:true})){const p=path.join(d,e.name);
   if(e.isDirectory())walk(p);else if(/\.(js|css|html|svg|json|woff2?)$/.test(p)){
     const b=fs.readFileSync(p);
     if(b.length>1024){
       fs.writeFileSync(p+'.gz', zlib.gzipSync(b,{level:9}));
       fs.writeFileSync(p+'.br', zlib.brotliCompressSync(b,{params:{[zlib.constants.BROTLI_PARAM_QUALITY]:11}}));
     }}}}walk('dist');console.log('precompressed');"
  ```
  （更规范做法：用 `vite-plugin-compression2` 接入 `vite.config.ts`，构建即产出。）
- **预期收益**：gzip 静态直出，无需运行时压缩 CPU 开销；传输量同 P0-3（-68%/-72%）。
- **验证方法**：`ls dist/assets/*.gz | wc -l` 应等于可压缩文件数；`curl -sI -H "Accept-Encoding: gzip" .../x.js` 应有 `Content-Encoding: gzip`。

### P1-5 `vite.config.ts` / `vite.config.js` 双文件冲突

- **问题**：`.js`（Sep 14）比 `.ts`（Sep 12）新，Vite 可能优先加载 `.js`，导致改 `.ts` 不生效。
- **改法**：删除编译产物 `vite.config.js` 与 `vite.config.d.ts`，并把它们加入 `.gitignore`；只保留 `vite.config.ts` 作为唯一真源。
- **预期收益**：消除"改了配置没生效"的隐性坑。
- **验证方法**：
  ```bash
  cd /d/erp_system/frontend-vite
  npx vite build --logLevel info 2>&1 | head -20   # 观察实际加载的 config 路径
  ```

### P1-6 `prod_runner` 自检：Nginx 存在但端口不可达时应告警

- **改法**：`_FrontendNginx._probe()`（`prod_runner.py:409`）已探测 `/nginx-health`，需确认**探测失败会真正降级/告警**，而非仅打印。同时把"端口被非预期进程占用"纳入启动自检。
- **验证方法**：人为用别的方式占 3000，启动 prod_runner，观察是否明确报错而非静默 running。

### P2-1 细化分包，降低单块体积

- **问题**：`vendor-primevue` 672.4 KB、`vendor-echarts` 556.9 KB、`index` 442.9 KB **均超 `chunkSizeWarningLimit: 600`**（`vite.config.ts:108`）。
- **改法**：把 `vendor-primevue` 再拆（按组件域，如 datatable / forms / overlay）；echarts 已是按需，可进一步只保留实际用到的 `LineChart/PieChart/BarChart`（当前 `echartsPreload.ts:20-22` 已是最小集，✅）。
- **预期收益**：首屏可只加载必需块，`primevue` 可拆到 200 KB 级（`[推测]` 需实测构建验证）。
- **验证方法**：构建后复查 TOP10；或接入 `rollup-plugin-visualizer`（已在 devDependencies）：
  ```bash
  cd /d/erp_system/frontend-vite && npx vite build --mode production
  # 需在 vite.config.ts 临时加 visualizer 插件，产出 stats.html 后浏览器打开
  ```

### P2-2 图片资源优化

- **问题**：`logo_plush.png` 146.4 KB 同时充当 192/512 图标（`vite.config.ts:92-95`），gzip 无效（99%）。
- **改法**：转 WebP/AVIF，或按尺寸生成多套图标。
- **预期收益**：省约 100~140 KB。
- **验证方法**：`ls -la dist/*.png` 对比优化前后。

### P2-3 显式声明 `build.target`

- **改法**：`vite.config.ts` 的 `build` 中补 `target: 'es2020'`（或与 `tsconfig.json` 的 target 对齐）。
- **预期收益**：构建确定性，避免 Vite 默认值随版本漂移。
- **验证方法**：构建产物中不应出现超出目标语法的现代特性。

---

## 5. 浏览器端排查手册

### 5.1 DevTools 各面板具体看什么

| 面板 | 看什么 | 本次故障的特征 |
|---|---|---|
| **Network** | ① 请求条数 ② 每条 `Size` / `Time` ③ 表头 `Content-Encoding` 列 ④ `Cache-Control` | dev 模式下**静态模块数百条**；无 Content-Encoding 列值；`/assets/*.js` 的 Type 显示 `html` |
| **Network → 右键列头** | 勾选 `Content-Encoding`、`Cache-Control`、`Content-Type`、`Priority` | 一眼看出"缺压缩、缺缓存" |
| **Network → 筛选 `JS`** | 应有 6 条左右（prod） | dev 下数百条 → 立即判定跑错模式 |
| **Network → Disable cache 关闭** | 二次访问应有 `(disk cache)` / `304` | 全是 `200` 且无缓存头 → 缓存失效 |
| **Performance** | 录制首屏 → 看 Main 线程长任务、`Recalculate Style`、`Scripting` 占比 | dev 下 `Scripting` 极高（实时编译+大量模块） |
| **Performance → Timings** | `TTFB`、`First Contentful Paint`、`LCP` | 区分是网络慢还是渲染慢 |
| **Lighthouse** | Performance 分数、`Opportunities`、`Diagnostics` | 会明确列出 "Enable text compression" / "Serve static assets with an efficient cache policy" |
| **Application → Service Workers** | active worker 的 script URL/时间戳 | 确认 SW 是否在用旧 index.html |
| **Application → Cache Storage** | workbox precache 里 index.html 的 revision | 见 E6 |
| **Application → Frames → Top** | 确认 `Is Secure Context`、`Service Worker` 注册状态 | — |
| **Coverage**（Ctrl+Shift+P → Show Coverage） | 未使用 JS/CSS 占比 | echarts/primevue 全量与否的直观证据 |
| **Console** | `[API]` 日志、chunk 加载失败告警 | `devLog` 只在 DEV 输出；若生产看到 `[API]` 日志即可判定跑在 dev |

### 5.2 Lighthouse / PageSpeed

- **Chrome DevTools**：`F12` → `Lighthouse` 面板 → Mode: Navigation，Device: Desktop + Mobile 各跑一次 → 勾选 "Performance"、"Best Practices" → Analyze。
- **CLI**（推荐，可进 CI）：
  ```bash
  npm i -g lighthouse
  lighthouse http://127.0.0.1:3000/dashboard --only-categories=performance \
    --preset=desktop --output=json --output-path=./lh.json --chrome-flags="--headless"
  ```
  ```powershell
  # 若走内网 IP
  lighthouse http://192.168.0.95:3000/dashboard --only-categories=performance `
    --preset=desktop --view
  ```
- **PageSpeed Insights**：需公网地址；内网系统用 Lighthouse 本地跑即可。
- **重点看两条审计**：
  - `uses-text-compression` → 本报告 P0-3
  - `uses-long-cache-ttl` → 本报告 P0-4

### 5.3 `performance.getEntriesByType('resource')` 采集脚本

在 DevTools Console 或 Snippet 中执行（首屏加载后运行）：

```js
(() => {
  const res = performance.getEntriesByType('resource');
  const byType = {};
  let totalTransfer = 0, totalDecoded = 0;
  const rows = res.map(r => {
    const t = r.initiatorType || 'other';
    byType[t] = (byType[t] || 0) + 1;
    totalTransfer += r.transferSize || 0;
    totalDecoded  += r.decodedBodySize || 0;
    return {
      name: r.name.replace(location.origin, ''),
      type: t,
      transferKB: +((r.transferSize || 0) / 1024).toFixed(1),
      decodedKB: +((r.decodedBodySize || 0) / 1024).toFixed(1),
      durationMs: +r.duration.toFixed(1),
      // transferSize ~= 0 且 decodedBodySize > 0 => 来自缓存
      fromCache: (r.transferSize === 0 && r.decodedBodySize > 0)
    };
  }).sort((a, b) => b.decodedKB - a.decodedKB);

  console.log(`资源总数: ${res.length}`);
  console.log(`按类型:`, byType);
  console.log(`总传输: ${(totalTransfer/1024).toFixed(1)} KB`);
  console.log(`总解压: ${(totalDecoded/1024).toFixed(1)} KB`);
  console.log(`压缩率: ${totalDecoded ? (100*(1-totalTransfer/totalDecoded)).toFixed(1) : 'n/a'}%  <-- 接近 0% 说明压缩未生效`);
  console.table(rows.slice(0, 25));
})();
```

**本次故障下预期输出**：资源总数**数百条**（dev）；压缩率 **≈0%**（无 gzip）。修复后应为**十余条**、压缩率 **≈65~70%**。

### 5.4 web-vitals 接入（项目已依赖 `web-vitals@^5.2.0`）

`package.json:73` 已有依赖，且 `vite.config.ts` 里已把它列进 `optimizeDeps.include`（`:208`），`dist/assets/webVitals-CQunnhHY.js` 也存在于产物中。后端已有 `/api/v1/monitoring/vitals` 接收端点（nginx access log 实测到 `POST /api/v1/monitoring/vitals 200`）。**说明已经接了**，验证一下上报是否含 `TTFB` 即可：

```js
// 确认上报字段（在 Console 里覆盖 fetch 观察）
const _f = window.fetch;
window.fetch = (...a) => { if (String(a[0]).includes('monitoring/vitals')) console.log('VITALS', a); return _f(...a); };
```

```bash
# 服务端侧看上报量与 TTFB 分布
grep "monitoring/vitals" logs/nginx-access.log | tail -20
```
> ⚠️ 注意：`POST /api/v1/monitoring/vitals` 是 **POST**，而 `nginx-windows.conf:133` 的 `/api/` 反代用的是 HTTP/1.0（`:134-136` 注释说明的刻意选择）→ 每次上报新建连接，高频上报会放大连接开销。`[推测]` 影响有限，但值得观察。

### 5.5 curl 验证压缩与缓存头（可直接抄）

```bash
BASE=http://127.0.0.1:3000

# 1) 压缩是否生效（三选一对比）
JS=$(curl -s $BASE/ | grep -o '/assets/[A-Za-z0-9_.-]*\.js' | tail -1)
echo "探测资源: $JS"
curl -sI -H "Accept-Encoding: gzip, br" "$BASE$JS" | grep -iE "content-encoding|vary|content-length"
curl -s -o /dev/null -H "Accept-Encoding: identity" -w "原始   : %{size_download} B\n" "$BASE$JS"
curl -s -o /dev/null -H "Accept-Encoding: gzip"     -w "gzip   : %{size_download} B\n" "$BASE$JS"
curl -s -o /dev/null -H "Accept-Encoding: br"       -w "brotli : %{size_download} B\n" "$BASE$JS"

# 2) 缓存头是否正确
curl -sI "$BASE$JS"        | grep -i cache-control   # 期望 public, immutable
curl -sI "$BASE/index.html" | grep -i cache-control  # 期望 no-cache, no-store

# 3) MIME 是否正确（应为 text/javascript，绝不能是 text/html）
curl -sI "$BASE$JS" | grep -i content-type

# 4) 是否跑在 nginx（不该出现 Server: uvicorn / 不该有 dev client）
curl -s "$BASE/" | grep -c "@vite/client"            # 期望 0
curl -sI "$BASE/nginx-health" | head -1              # 期望 200 且返回 JSON

# 5) TTFB / 分阶段计时
curl -s -o /dev/null -w "dns=%{time_namelookup}s connect=%{time_connect}s tls=%{time_appconnect}s ttfb=%{time_starttransfer}s total=%{time_total}s\n" "$BASE/"
```

### 5.6 服务器端定位瓶颈的命令

```bash
# --- 端口与进程归属（Git Bash）---
netstat -ano | grep -E ":3000|:5002|:5173" | grep LISTENING
tasklist /FI "IMAGENAME eq nginx.exe"      # Windows 版 nginx 应有 2 个进程（master+worker）
tasklist | grep -i -E "nginx|node|python"

# --- nginx 日志分析（本次故障的取证核心）---
tail -50  logs/nginx-error.log
tail -100 logs/nginx-access.log
# 找出最慢的请求（request_time 字段）
grep -o 'request_time=[0-9.]*' logs/nginx-access.log | sort -t= -k2 -rn | head -20
# 找出 404（stale chunk 的证据）
grep " 404 " logs/nginx-access.log | tail -20
# 统计压缩是否生效：看 body_bytes_sent 与文件大小关系
grep "assets/.*\.js" logs/nginx-access.log | tail -10

# --- 确认 nginx 实际加载的配置 ---
C:/nginx/nginx.exe -p D:/erp_system -c config/nginx-windows.conf -t     # 语法测试
# 配置里是否有 brotli（Windows 版应为 0）
grep -n "brotli" config/nginx-windows.conf || echo "Windows 版无 brotli（已确认）"

# --- 【新增】nginx 为何起不来：查致命错误 + Windows 保留端口区间 ---
grep -n '\[emerg\]' logs/nginx-error.log          # 期望：不新增（历史有 1 条 bind 3000 failed 10013）
grep -c '\[emerg\]' logs/nginx-error.log          # 实测历史计数 = 1
netsh int ipv4 show excludedportrange protocol=tcp   # 确认 3000 是否落在保留区间
netsh int ipv6 show excludedportrange protocol=tcp

# --- 生产状态文件（注意 pid 是否为 null）---
cat logs/prod_runner.json

# --- 后端直连对比 TTFB（排除反代开销）---
for i in 1 2 3; do curl -s -o /dev/null -w "nginx3000: %{time_total}s\n" http://127.0.0.1:3000/api/health; done
for i in 1 2 3; do curl -s -o /dev/null -w "direct5002: %{time_total}s\n" http://127.0.0.1:5002/api/health; done
```

本次实测（后端健康检查，非瓶颈）：
```
dev3000 /api/health: 0.0157s / 0.0169s / 0.0158s
direct5002 /api/health: 0.0168s / 0.0269s / 0.0124s
```
→ **健康检查级别两者无差异**，说明瓶颈**不在反代跳数**，而在**静态资源服务方式**（dev 未打包 vs dist 已打包）。这进一步锁定真凶是 #1/#2，而非网络层。

---

## 6. 修复前后预期效果汇总

| 指标 | 当前（dev server 实际在跑） | 修复后（nginx + dist + gzip） | 改善 |
|---|---|---|---|
| 首屏静态请求数 | 数百条（每 .vue/.ts 一条） | 6 条 | **数量级下降** |
| 首屏 JS/CSS 传输量 | 447.9 KB（无压缩） | 145.3 KB（gzip）/ 127.5 KB（br） | **-68% ~ -72%** |
| 全站 JS+CSS 传输 | 3522.9 KB | 1052.0 KB（gzip）/ 882.6 KB（br） | **-70% ~ -75%** |
| `/assets/*` 缓存头 | `no-cache`（不缓存） | `public, immutable` + `1y` | **二次访问零请求** |
| `/assets/*` Content-Type | `text/html`（错误，被回退吞掉） | `text/javascript` | **修复致命错误** |
| 切页 chunk 404 循环 | 存在（stale hash） | 消除（原子部署 + 校验） | **消除白屏抖动** |
| 健康检查真实性 | 假阳性（running 但进程为 0） | 真实 | **消除静默故障** |
| Source Map 泄漏 | 无（✅ 已确认） | 无 | 保持 |
| 分包/懒加载/按需引入 | 已做（✅ 已确认） | 保持 | 保持 |

---

## 7. 排障优先级行动清单（TL;DR）

0. **【最先做，最易被忽略】核查 Windows 保留端口区间**：`netsh int ipv4 show excludedportrange protocol=tcp` —— 因 `logs/nginx-error.log:19` 的 `[emerg] bind() 10013`（权限拒绝，非端口占用）提示 3000 可能落在保留区间。**若命中，以下所有 nginx 动作都会失败，必须先换端口或调整预留。**
1. **【立刻】停掉占用 3000 的 `node.exe` dev 进程，让 nginx 接管；确认 `tasklist` 里有 nginx.exe（应为 2 个：master+worker）。**
2. **【立刻】修复健康检查假阳性 —— 必须五层同修**（弱判据 / dev SPA 回退 / 探测无失败路径 / `pid` 来源 / `[emerg]` 不可观测）。**只修 `alive()` 无效**，因 `_ensure_started():404` 会无条件把状态写成 `running`。
3. **【立刻】验证 `curl -sI .../assets/x.js` 出现 `Content-Encoding: gzip` 与 `Cache-Control: public, immutable`；且 `Content-Type` 为 `text/javascript`（非 `text/html`）。**
4. **【短期】Windows nginx 补 `gzip_static on` + 构建期预压缩；`gzip_types` 补 `application/wasm` 与字体。**
5. **【短期】给后端 gzip 加兜底**：`middleware.py:319-324` 改为始终注册（或显式开关），避免"Nginx 不在则两侧都不压缩且无声"。**注意这条当下就在生效——后端此刻确实不压缩。**
6. **【短期】强制走 `build:atomic` 原子部署 + 构建后校验 index.html 引用完整性。**
7. **【短期】收紧 PWA：index.html 移出 precache。**
8. **【短期】删除 `vite.config.js`/`.d.ts`，消除配置双源。**
9. **【中期】3 处 dev 入口加"生产禁止起 dev"硬拦截**（`server_manager_v533.py:1839` / `server_manager.py:1827` / `start.py:110`）——否则 kill 进程治标不治本。
10. **【中期】统一 Docker/Windows 两套 nginx 配置；清理或接线 `NGINX_PROXY` 死开关；统一 `.env` 的 `FLASK_ENV` 与 `APP_ENV`。**
11. **【中期】`/static/` 改磁盘 alias，减少 FastAPI worker 占用。**
12. **【中期】拆分 `vendor-primevue`（672 KB）并调整 `chunkSizeWarningLimit`。**
13. **【安全侧，超范围】排查内网穿透暴露面**：nginx 日志出现 `https://frp-fun.com:30001/` 来源请求（`access.log:14788`）。

---

## 附录 A：协作复核结果与剩余边界

### A.1 已由 investigator-perf 回答并闭环（2026-09-17）

**Q3（我请求排查的"dev 启动路径"）——已完全闭环，结论比预期更严重**：到达 3000 的启动路径**共 3 条，全部是 Vite dev，全部显式传 `--port`**：

| # | 位置 | 调用 |
|---|---|---|
| 1 | `server_manager_v533.py:1839`（**当前正在跑的那条**） | `subprocess.Popen([npm_cmd,'run','dev','--','--port',str(_WEB_PORT)], cwd=frontend-vite)` |
| 2 | `server_manager.py:1827`（旧版管理器） | `[_NPM_CMD,'run','dev','--','--port',str(_PORTS.web)]` |
| 3 | `start.py:110`（CLI 入口） | `["npm","run","dev","--","--port",str(args.web_port)]`；`start.py:45` `--web-port default=3000`；`start.py:120-121` 默认 `args.dev = True` |

**这解开了我报告里的"5173 vs 3000"矛盾**：`package.json:10` 的 `"dev": "vite --host 0.0.0.0 --port 5173"` 只是默认值，三条路径都用 `npm run dev -- --port 3000` **显式覆盖**为 3000。所以 5173 从不出现，**3000 才是这 3 条 dev 路径的落地端口**——即"生产正在跑 dev"不是偶发误操作，而是这 3 个入口的**默认行为**。

补充（investigator 发现）：`server_manager_v8/domain/models.py:170-171` 把 `FRONTEND`/`BACKEND` 角色的 docstring 直接写成 **"开发模式前端（vite）"/"开发模式后端（uvicorn）"** → 该管理器的架构本身就是「dev 模式 = vite+uvicorn reload」对「prod 模式 = NSSM 服务」，只是 GUI 上这条 dev 路径被当成了生产在用。**这解释了真凶 #1 为何能长期存在：它不是 bug，而是被误用的默认路径。**

**Q4（`.env` 自相矛盾）——已澄清为非问题但有清理价值**：`FLASK_ENV` 与模式判定**无关**，全仓唯一引用在 `tests/performance/test_performance.py`，`fastapi_app/` 下零引用。模式判定唯一权威是 `fastapi_app/core/config.py:35 _is_production_env()`（只读 `APP_ENV`，`:42`）。故 `FLASK_ENV=development` 不会造成模式误判，但属**误导性遗留键**，建议清理。

**真凶 #2 的成因拆分——已核实并已修订本报告正文**：我独立复读 `fastapi_app/core/middleware.py:319-324` 确认了"压缩真空"（详见正文真凶 #2 的修订框与 P0-3），并追加确认 `.env:172 APP_ENV=production` → `is_production` 为真 → **后端当下确实不注册 gzip 中间件**。这条**比我们原先各自的表述都更严重**：真空不是"将来风险"，而是**当前事实**。

**关于计时口径**：investigator 已区分路径（直连 5002：ttfb 0.019~0.027s；经 3000：ttfb 0.012~0.020s），结论与我一致——**后端是 20ms 级，不是瓶颈**。并明确：Windows nginx 无 upstream keepalive 的每次 TCP 建连开销**当前根本没生效**（因为跑的是 dev server 不是 nginx）。

### A.2 双方共识的统一表述

1. **"production 慢"这个命题在当前尚未被有效测量**——因为当前所有测量都发生在 dev server 上。
2. 唯一能证伪/证实的路径：先 `nssm start erp-prod` 起正式栈（Nginx + dist + 8 worker），再做同条件 A/B。**在此之前任何"production 慢"的结论都不可用于定案。**
3. `prod_runner.json` 的自报状态是**陈旧快照**（investigator 实测：文件称 backend pid=3708，实际 5002 持有者是 PID 17264、无 nginx、erp-prod 服务 Stopped）→ 与我的 P0-2（健康检查假阳性）是同一条链的两端。

### A.3 客户端（真实用户机）SW 状态核查 —— 已用服务端日志回答 product-perf 的待确认项（2026-09-17）

product-perf 提出一个方法论上正确的质疑：我的取证在**服务器本机**，而用户从 `192.168.0.149` 访问，且 nginx 日志证明**曾有 nginx 正常服务真实用户的时段**，故客户端可能已注册并 `activated` 旧 SW。他们建议我在真实客户端补 DevTools 检查。

**我无法访问真实客户端浏览器**（本次会话无浏览器工具），但我可以在**服务端日志侧给出可判定的证据**——因为客户端只要真正注册/更新过 SW，就**必然留下 `/sw.js` 的请求记录**。实测结果：

```bash
# 全部 /sw.js 请求（共 8 条，无一来自 LAN 客户端）
$ grep -n '"GET /sw\.js' logs/nginx-access.log
127.0.0.1  [16/Sep 13:01:15]  HeadlessChrome/153 (Edg/153)   <- 自动化
127.0.0.1  [16/Sep 13:01:23]  HeadlessChrome/153              <- 自动化
127.0.0.1  [16/Sep 13:16:35]  HeadlessChrome/153              <- 自动化
127.0.0.1  [16/Sep 13:16:44]  HeadlessChrome/153              <- 自动化
::1        [16/Sep 13:28:08]  Freebuff Electron/33            <- 本地应用
::1        [16/Sep 13:28:35]  Freebuff Electron/33            <- 本地应用
127.0.0.1  [16/Sep 21:19:07]  Chrome/132 (via frp 隧道)        <- 本地
（共 8 条，全部为 127.0.0.1 / ::1 / localhost）

# 关键反证：用户机 192.168.0.149 是否请求过 /sw.js？
$ grep -n '192\.168\.0\.149.*"GET /sw\.js' logs/nginx-access.log
>>> No matches found <<<

# 关键反证：任何 LAN 客户端（192.168.x.x）是否请求过 /sw.js？
$ grep -n '^192\.168\.\d+\.\d+ .*"GET /sw\.js' logs/nginx-access.log
>>> No matches found <<<
```

**结论（有证据支撑，非推测）**：
1. `/sw.js` 的**全部 8 次请求都来自本机地址族**（`127.0.0.1` / `::1` / localhost），其中 4 次明确是 `HeadlessChrome`（自动化测试）、2 次是 `Freebuff Electron`（本地 IDE 应用）。
2. **用户机 `192.168.0.149` 从未请求过 `/sw.js`**；**任何 LAN 客户端都没有**。
3. 而 `192.168.0.149` **确实请求过 `/registerSW.js`**（如 `logs/nginx-access.log:1927`、`:2212`，`upstream_response_time=-` 说明由 nginx 从磁盘直出）。`registerSW.js` 只是注册脚本，浏览器**执行它之后才会去取 `/sw.js`**——而 `/sw.js` 从未被取。

→ **判定：用户机上 Service Worker 极可能从未成功注册/激活**（至少从未完成到发起 `/sw.js` 请求这一步）。

**这对 product-perf 的 M1/PWA 项意味着什么**：
- product-perf"把 M1/PWA 降级但没删除"的处理是**恰当且稳健的**——我没有足以推翻它的正面证据，且 `sw.js` 预缓存 index.html 的**隐患本身客观存在**（我 E6 的证据不变）。
- 但按现有日志，**PWA 陈旧缓存不是当前用户感知的主因**，"本机 = dev server"这一个主因已足以解释全部现象。PWA 应定位为**需加固的潜在风险**，而非已发生的成因。
- **方法学上的诚实边界**：SW 注册只需一次成功，之后 `/sw.js` 的**更新检查**由浏览器按自有节奏发起（通常不重新下载整个 sw.js，而是带条件请求），**也可能被日志遗漏**；且 `registerSW.js` 可被缓存命中而不产生请求。故上述判定为"**证据不支持 SW 已激活**"，**不等于"已证明 SW 未激活"**。若需 100% 确认，仍需产品侧在真实客户端做一次 DevTools 检查（Application → Service Workers 看 controller）。
- 附带发现：日志里出现过 `https://frp-fun.com:30001/` 来源的请求（`:14788`）——说明存在**内网穿透/公网暴露路径**，建议安全侧关注（超出本次性能范围，仅作记录）。

**建议向 product-perf 回传的表述**：M1/PWA 由"头号待确认项"调整为"**已降级：现有日志不支持其为主因，但需加固**"，并保留其待确认属性；§5 的 DevTools 检查仍建议做，但**优先级低于 P0-1/P0-2**。

### A.4 剩余未覆盖边界

- 后端 SQL / 连接池 / N+1：由 investigator-perf 负责，本报告未触及。
- 数据库与 Redis 侧延迟：需 investigator-perf 的实测数据。
- 生产 8 workers（`prod_runner.json: "workers": 8`）与实际 CPU 核数的匹配：属 investigator 职责范围。
- **本次会话末段 Bash 工具的 stdout 曾整体失效**（连 `echo hello` 都返回空），故"真实 prod 栈（Nginx + dist）下的压缩/缓存实测"**未能在此次完成**——需在 `nssm start erp-prod` 之后补测。本报告所有"当前线上"数据均采集于工具正常期间（2026-09-17 08:41–08:47），未受此影响。
- 客户端 SW 激活状态的**最终确认**仍需真实客户端 DevTools 检查（见 A.3：日志证据不支持其已激活，但不构成反证）。

## 附录 B：复现本次全部证据的最小命令集

```bash
# 1) 端口真相
netstat -ano | grep ":3000 " | grep LISTENING
tasklist | grep -i -E "nginx|node"
tasklist /FI "IMAGENAME eq nginx.exe"

# 2) dev server 铁证
curl -s http://127.0.0.1:3000/ | grep -o 'src="[^"]*"'
curl -o /dev/null -w "%{http_code} %{size_download}\n" http://127.0.0.1:3000/@vite/client

# 3) 静态资源返回 HTML + 无压缩
curl -I -H "Accept-Encoding: gzip, br" http://127.0.0.1:3000/assets/index-8985Y_zC.js

# 4) 死开关
grep -rn "NGINX_PROXY" --include="*.py" .
grep -rn "NGINX_PROXY" .env.production config/.env.production

# 5) 假阳性健康检查 + stale 404
cat logs/prod_runner.json
tail -8 logs/nginx-error.log

# 6) SW 预缓存 index.html
grep -o 'index.html","revision":"[^"]*"' frontend-vite/dist/sw.js

# 7) 构建产物真实体积（无 map、gzip/brotli 对照）
find frontend-vite/dist -name "*.map" | wc -l
cd frontend-vite && node -e "const fs=require('fs'),zlib=require('zlib');console.log(zlib.gzipSync(fs.readFileSync('dist/assets/index-Cb7_V1ei.js')).length)"
```
