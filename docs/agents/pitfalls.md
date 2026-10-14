# 分析方法与历史踩坑（按需阅读）

> 本文是 `AGENTS.md` §6 的外置细节：**动手分析本仓代码前读它**。
> 根文件只留"每次都要看见的"（红线、拓扑、门禁、运维护栏），分析方法的坑放这里。

## 1. 解析 Python 结构必须用 `ast`

导入关系、迁移依赖图、`__init__.py` 聚合等结构信息，**必须用 `ast` 解析**，不要用正则或 shell 文本匹配。

代价实例：曾因此得出「15 个迁移 head」「48 个端点模块未接线」两个**纯解析伪影**——真相是**单 head、零孤儿**。当时若据此动手"修"，会删掉正在用的模块。

## 2. 判断死代码要按全仓导入

不能只看是否被 `fastapi_app/api/v1/router.py` 直接引用——`backup/`、`purchase_center/` 等是通过 `__init__.py` 聚合接入的，直接引用看不到。判"没被引用"就删，等于删掉生产在用的端点。

## 3. 文档与报告的结论可能已过期

`deliverables/`、`*.md` 报告里的结论是**写作当时的快照**，可能早已失效（实例：某报告称 `utils.redis_cache` 不存在，实际它一直在被 `fastapi_app/main.py` 使用）。**以代码为准**，文档只作为线索。

## 4. 本机 shell 是 Windows PowerShell 5.1（不是 pwsh 7）

- `-Encoding utf8` 会写 BOM；
- 没有 `Get-Content -AsByteStream`；
- 把内联 `if(){...}else{...}` 塞进字符串插值会触发 `MissingEndParenthesisInExpression`，并让**整段脚本一行都不执行**（静默！）——分步写、先赋值再输出。

## 5. git-bash 里 `python` 常常不在 PATH

`C:\Program Files\Git\bin\bash.exe` 环境下 `python` 通常不可见，钩子靠**绝对路径**兜底。写脚本给 agent 或钩子用时，别假设 PATH 里有 python。

## 6. `scripts/` 下一次性运维脚本的超长函数不是技术债

`scripts/check_function_length.py` 的默认扫描面是 `fastapi_app` + `server_manager` + 仓库根顶层 `.py`，**不含 `scripts/`**——故 `scripts/` 里的 >80 行函数不进质量门禁。这些多为一次性运维/诊断脚本（跑一次即弃），拆它们没有收益，反而增加改动面与回归风险。

- 2026-10-11 复核（`REVIEW-VERIFICATION.md` §2.7 ⑦）的处置：`scripts/prod_audit/**` 是**维护中的门禁框架**，11 条超长函数已全部拆到 ≤80 行；其余 17 条一次性脚本**按原样保留**（进 `check_function_length.py scripts` 的统计，但非门禁增量）。
- 别因为「看到超长函数」就去拆 `scripts/` 下的一次性脚本；要拆只拆 `prod_audit` 这类被持续维护的框架代码。
- 复核命令：`command .venv/Scripts/python.exe scripts/check_function_length.py scripts`。

## 7. 两种 pytest 假红形态（本机实测）

- **并发互撞**：`tests/conftest.py` 收尾 `DROP SCHEMA public CASCADE`，两进程共用同一测试库 `erp_system_test`。相隔 ~70s 重叠跑两次全量 → `8 failed / 7 errors`，报错 `asyncpg UniqueViolationError` 违反 `stock_out_stockout_no_key`、冲突值 `(stockout_no)=(SO-PERF-0000)`（来源 `tests/test_stock_routes.py` 硬编码 `f"SO-PERF-{i:04d}"`）。独占单跑即全绿。**全量 pytest 必须独占单实例**。
- **`--basetemp` 越界**：`fastapi_app/tasks/batch_tasks.py` 的 `ALLOWED_UPLOAD_DIRS = [tempfile.gettempdir(), <repo>/static/uploads]` + `realpath+commonpath` 守卫；把 `--basetemp` 指到 `%TEMP%` 之外 → `test_batch_tasks_semantics.py` 4 条必假红（默认 basetemp 下 5 passed）。
- 判别法：报错涉及**别的测试文件**的固定夹具值、或临时目录白名单守卫时，先怀疑跑法（并发 / 临时目录），而不是代码回归。

---

## 8. 路由表不是平的：`app.routes` 只有 13 条，业务路由在 `_IncludedRouter` 里

2026-10-12 实测。想「遍历 app 的路由表做点全局检查」时会踩：

```python
len(app.routes)                 # 13   ← 只有健康检查 / 静态挂载 / ws / 根
len(app.openapi()['paths'])     # 341  ← 真正的业务路由
```

业务路由被包在 **`_IncludedRouter`** 懒加载壳里（`vars()` 里有 `original_router` /
`include_context`）。壳本身**没有 `.path` / `.dependant` / `.routes`**，所以：

- 只扫 `app.routes` 顶层 → 得到空集合。**若据此写断言，测试会恒真**（这正是它危险的地方）。
- 正确遍历要同时展开 `.routes` 与 `_IncludedRouter.original_router.routes`。
- **展开后 `route.path` 不带 include 前缀**（前缀在匹配期拼），所以**不能靠路径识别端点**
  ——要么按尾段 `endswith` 比，要么只断言与路径无关的属性。

判别法：任何「扫全路由」的脚本，先打印 `len(app.routes)` 与 `len(app.openapi()['paths'])`
对一下；差一个数量级就是踩到了。同理，任何据此得出的「某端点不存在」结论都不可信。

---

## 9. 本机无法验证的改动（CI-only）必须先证实前提，别凭推断

2026-10-12。给 CI 的 test job 加了一步 `sudo apt-get install -y postgresql-client-18`
（理由：service 是 `postgres:18-alpine`，而 runner 自带的 `pg_dump` 是 16，大版本不匹配时
pg_dump 直接 abort）。**本机是 Windows，这一步没有任何本地验证手段**，我凭「PGDG 的包名
就叫 `postgresql-client-18`」推断它在 Ubuntu 24.04 的默认源里——实际不在：

```
E: Unable to locate package postgresql-client-18
```

runner 镜像**预装**了 16 的 PGDG 包（`pg_dump --version` 报 `16.15-1.pgdg24.04+2`），但
**没有留 PGDG 仓库配置**——「镜像里有这个二进制」不等于「apt 源里有这个包」。正解是先加
PGDG 源再装（`.github/workflows/ci-cd.yml` 该步注释 + 提交 `7ae03d14`）。

**判别法**：改动落在本机跑不了的地方（CI job、远端构建、容器内步骤）时，先问「这个前提我
能证实吗」——

- **能证实** → 去证实：先加一步只做探测（`apt-cache policy <pkg>` / `apt-cache search`，
  把结果打进日志），或先在分支上单跑一次该 workflow，确认前提成立再写安装步骤。
- **不能证实** → 在注释里写明「这是未经本地验证的推断」，并**预期第一次会红**、盯结果。

**同源的反面样本**（同一次会话更早）：重写 `logs/_run_pytest_elevated.ps1` 时把注释写成
中文，PS 5.1 解不了无 BOM 的 UTF-8 中文 → 脚本在**解析阶段**就 `ParserError` 退出；而我把
`Start-Process` 返回 0（「发起成功」）当成了「跑起来了」，白等好几轮才想到去验证脚本本身。
**「命令没报错」不等于「事情做了」。** 改工具脚本后，先用最小参数把它跑一遍再交给它干活。

---

## 10. 发布后浏览器仍跑旧代码 = Workbox SW 预缓存了 `index.html`

2026-10-14 实测。现象：`build:atomic` 已换 dist、nginx 确认在服务新入口、把那个 chunk 拉下来反编译也确认是新代码，**浏览器打开还是旧界面，且无痕也一样**。

**根因**：`vite.config.ts` 的 VitePWA 里 `globPatterns` 含 `html`，而 generateSW 的 `navigateFallback` 默认就是 `'index.html'`（`vite-plugin-pwa/dist/index.js`）⇒ 生成的 `sw.js` 里同时有 `precacheAndRoute([{url:"index.html",…}])` 和 `new NavigationRoute(createHandlerBoundToURL("index.html"))` ⇒ **SW 用预缓存的旧 index.html 应答所有导航**（含 `/report`），里面引用的还是旧入口 chunk ⇒ 整套旧代码。

**无痕为什么也不灵**：无痕 profile 的 SW 活到**该窗口组全部关闭**为止。只要那个无痕窗口在构建之前访问过本站，它就一直拿旧预缓存——刷新多少次都没用，这也是最容易把人带偏的地方（"无痕都旧，那肯定是服务器旧"）。

**判别顺序**（别再从"我的改动没生效"查起）：

1. **服务端先自证**：`curl -sk https://<host>/ | grep -oE 'assets/index-[A-Za-z0-9_-]+\.js'` 与 `frontend-vite/dist/index.html` 里的入口比对；再把该 chunk 拉下来 `grep` 新代码的指纹（如 `_g_date`）。服务器是新的 ⇒ 到此为止，**问题在浏览器**，别再翻构建配置。
2. **看浏览器实际加载了哪个 chunk**（Console）：`performance.getEntriesByType('resource').filter(r=>/ReportView-/.test(r.name)).map(r=>r.name.split('/').pop())` —— 输出旧 hash 即 SW/缓存供旧文件。
3. **清法**：关掉所有无痕窗口再开新的（最干净）／DevTools → Application → Service Workers → Unregister + Clear site data／`Ctrl+Shift+R`。

注：`index.html` 的响应头本就是 `Cache-Control: no-store`，**HTTP 缓存不背这个锅**；`/api/` 是 NetworkOnly，业务数据也不受影响——只有 HTML 这一层被 SW 拦了。

**已修**（2026-10-14，提交 `acaa11d7`）：`navigateFallback: null` + `globIgnores: ['**/index.html']`。**两个必须成对**，缺一即坏（只删预缓存 → NavigationRoute 绑到不存在的 URL，`createHandlerBoundToURL` 抛 `non-precached-url`；只关 navigateFallback → workbox 预缓存的 `directoryIndex` 默认 `index.html`，从根路径进站仍中招），理由见 `vite.config.ts` 该处注释。

⚠️ **但这条修复只对"下一个版本"生效**：已装旧 SW 的客户端仍要等浏览器自己去取新 `sw.js`，而 Chrome 对同一 SW 的字节级更新检查**最长 24h 节流**。所以**发布后短期内仍可能看到旧界面，别据此判定发布失败**——按上面三步先分清是服务端旧还是浏览器旧。

---

## 11. 并发会话提交时，工作区会短暂「看起来被回退」——那是 pre-commit 的 stash 窗口

2026-10-14 实测。本机常常多个会话同时改同一个工作区。当**另一个**会话执行 `git commit` 时，
它的 pre-commit 框架会打印 `[WARNING] Unstaged files detected`，把**所有未暂存改动**
（包括你这个会话正在写的文件）`git stash` 走，跑完门禁再 `Restore` 回来。

于是你会在几分钟内反复看到：刚写完的文件 `git status` 干净、内容退回 HEAD 版本，过一会儿又全回来。
**这不是别人回退你的活，是提交钩子的正常时序。** 本次会话因此在 stock-return / components/ui 上
误判过一次，重写了两遍文件。

判别与对策：

- 提交输出里出现 `Stashing unstaged files to …patch*` / `Restored changes from …`，或 `git stash list` 临时多一条又消失，即为该窗口。
- **窗口内不要下结论、不要重写文件、更别用 `git checkout`/`git stash` 去"救"**——等它 pop 回来再核对。
- 这与 `AGENTS.md` §6.1-5「看到陌生改动先问，别 stash/回退」同源：**并发工作区里，git 命令本身也是并发写者。**

---

## 关联

- 运维护栏（红线之外的第二道人防）在 `AGENTS.md` §6.1——**常驻**，动手前必看。
- 本文的坑若再犯，按 `AGENTS.md` §8 把新根因追加到这里，而不是塞回根文件。
