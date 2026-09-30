# Runbook · 服务生命周期与运行模式切换

**适用范围**：滨发 ERP 生产机（`192.168.0.95`，**本机即生产**）
**最后更新**：2026-09-28（erp-web 单一职责重构 · 全部结论为实测）
**适用对象**：运维 / 值班 / 任何需要启停本栈的人

> ⚠️ 本文的每一条约束都是实测得出的。**请不要凭直觉替代本文步骤**，尤其是提权部分。

> ⚠️⚠️ **迁移窗口禁令（2026-09-28 重构落地后、`scripts/migrate_erp_web.ps1`
> 执行完成前）**：禁止重启 `erp-prod`、禁止重启机器。此窗口内 erp-prod 任何重启
> 都会让新版瘦身监督器上线——它不再托管 nginx 而 erp-web 未注册，:3000 将无人
> 服务；恢复 = 立即执行迁移脚本（幂等）或 GUI「安装服务」。详见
> `deliverables/2026-09-28-erp-web-migration/VERIFICATION.md` §0。

---

## 0. 一条必须记住的硬约束（最常见的翻车点）

> **非提权（普通用户）shell 下，重启 `erp-prod` 没有任何可用路径。**

已实测封死的四条路：

| 尝试 | 结果 |
|---|---|
| `nssm restart erp-prod` / `nssm stop` | **rc=3**，stderr `OpenService(): 拒绝访问` |
| `sc stop erp-prod` / `Stop-Service` | 拒绝访问（且 `sc` 已被本机安全策略屏蔽） |
| `taskkill` 受监督的子进程（nginx / uvicorn / prod_runner） | `OpenProcess` 返回 **err=5 ACCESS_DENIED** |
| `Start-Process -Verb RunAs` 自提权 | **被安全策略永久拦截**（LOLBin） |

**根因**：整个服务树以 `LocalSystem` 运行，而普通 shell 持的是 UAC **过滤令牌**（`IsElevated=False`）→ 这是 Windows ACL 边界，**不是沙箱限制**，绕不过去。

⇒ **结论：重启生产栈必须交给人用「管理员 PowerShell」或提权 GUI。** CLI 无解，不要浪费时间尝试。

⚠️ **不要用 `schtasks` 绕过**：本机已把 `schtasks.exe` 列入黑名单，且**禁止任何等价绕行**。
⚠️ **计划任务 `\ERPSystem` 是死任务**（目标 `start_production.py` 不存在，`RunLevel=Limited`，末次 2026-04-07 返回 `0xC000013A`）→ **不可**当作提权或启动入口。`\ERP_Database_Backup` 同样是死任务（返回 `0x2`）。两者 Author 是**另一台机器** `DESKTOP-FKCGN3O`（本机 `DESKTOP-11111`），属迁机遗留。

---

## 1. 拓扑（先认清对象）

```
services.exe
 ├─ nssm.exe (erp-redis, 4220) → redis-server.exe (:6379, 缓存)
 ├─ nssm.exe (erp-redis-broker, 4180) → redis-server.exe (:6380, **ARQ broker**)
 ├─ nssm.exe (erp-arq, 4328)
 │   └─ python.exe (arq worker)    ← 定时备份/异步任务 + nginx 日志轮转 cron
 ├─ nssm.exe (erp-web)            ← nginx.exe (:3000, root=frontend-vite/dist)
 │   └─ nginx.exe (master + N worker, 独立进程树)
 └─ nssm.exe (erp-prod)
     └─ prod_runner.py            ← 自研监督器，只守护下列后端子进程
         └─ uvicorn master (:5002)
             └─ N × uvicorn worker
```

| 服务 | 作用 | 启动方式 |
|---|---|---|
| `erp-prod` | uvicorn `:5002`（prod_runner 只守护后端） | `Auto` + `AppExit=Restart` + `DependOnService=erp-redis` |
| `erp-web` | nginx `:3000`（静态 + 反代，与后端启停解耦） | `Auto` + `AppExit=Restart`，无依赖 |
| `erp-arq` | ARQ worker（**定时备份的唯一调度者** + nginx 日志轮转 cron 04:30） | `Auto` |
| `erp-redis` | 缓存 / Pub-Sub / 维护模式 | `Auto` |
| `erp-redis-broker` | **ARQ 队列 broker**（哨兵键在这里） | `Auto` |

**前后端解耦（2026-09-28 重构）**：`prod_runner` 不再托管 nginx；它对 `:3000/nginx-health`
只做**只读探针**（结果写 `frontend_ok` 字段），探测失败只报告、绝不重启。重启
`erp-prod` 不影响前端静态服务；`erp-web` 挂了 `nssm restart erp-web` 即可，不影响 API。

**镜像/工具路径**：`nssm` 在 `C:\nssm\nssm.exe`（**不在 PATH**）。

---

## 2. 正常启停：走提权 GUI（首选）

在 `ERP服务器管理器_v5.33.exe` 上点「生产模式」。其内部顺序为：

1. **停开发**（若有）
2. **清 `:3000` / `:5002` 端口占用**
3. **确认 `redis` / broker 就绪**
4. `nssm start erp-prod` + `nssm start erp-arq`

### ⛔ 切换运行模式的顺序不可颠倒

> **停开发 → 换 dist → 起服务**

理由（实测）：`build:atomic` 的最终 `rename dist-new → dist` **在开发模式运行时必然 EPERM** ——
**真因是 vite dev server 的 chokidar watcher 持有 `dist-new` 目录句柄**（vite 只忽略
`build.outDir`=dist，不忽略 `dist-new`），**不是防病毒软件**。
实测对照：`rename(dist, dist.__probe)` **成功**，而 `rename(dist-new, …)` 抛 `PermissionError errno=13`。

**绕开办法（不必停 dev server）**：把产物先 `copytree` 到 **vite root 之外**的暂存目录
（如 `D:\erp_system\_dist_stage`），再 `rename` 到 `frontend-vite/dist` —— 源在 watch 树之外无锁，
目标是 `dist`（被忽略）可替换。⚠️ 暂存目录**不能**建在 `frontend-vite/` 内，否则同样被 watch。

### ⛔ 另一个顺序陷阱

> **禁止在开发模式仍占着 `:5002`/`:3000` 时执行 `nssm start`** —— 两边会抢端口互斗。

---

## 3. 替代路径：管理员 PowerShell

> 需要「管理员」身份。普通 PowerShell **会失败**（见 §0）。

```powershell
# 只读状态（非提权也可）
nssm status erp-prod
nssm status erp-arq

# 启停（需管理员）
nssm stop  erp-prod
nssm start erp-prod
```

### 诊断 `nssm` 输出时必须做的事

- **`nssm` 的输出是 UTF-16LE**（stdout 与 stderr 都要）：
  `encoding='utf-16-le', errors='replace'`
- **必须解 stderr**：只解 stdout 会把 `OpenService(): 拒绝访问` 吞成「无输出」，
  进而把「权限不足」误判成「服务本就 STOPPED」。
- **`nssm start/stop/restart` 非提权时返回 rc=3** —— 别把它读成「服务不存在」。

### ⚠️ 优雅停止超时

不要给 `nssm restart` 套很短的 timeout：优雅停止可能 >60s，中断会**留下孤儿进程**。

---

## 4. 变更后验证（缺一不可）

### 4.1 前端是否真的由生产托管（四条硬判据）

```bash
# 判据 1/2：不应出现 vite dev 特征（两个都必须是 0）
curl -s --noproxy '*' http://127.0.0.1:3000/ | grep -c "@vite/client"
curl -s --noproxy '*' http://127.0.0.1:3000/ | grep -c "/src/main.ts"
# 判据 3：Server 头必须是 nginx
curl -sI --noproxy '*' http://127.0.0.1:3000/ | grep -i '^server:'
# 判据 4：>1KB 的响应必须 gzip（注意 gzip_min_length=1024，别拿 /api/health 这种 51B 的测）
curl -sI --noproxy '*' -H "Accept-Encoding: gzip" \
  'http://127.0.0.1:3000/api/v1/products/list?page=1&per_page=50' | grep -i content-encoding
```

> ⛔ **不要用「`:3000` 端口归属进程」判定**：dev 模式下 `psutil.net_connections()` 会把
> `nginx.exe` 与 `node.exe`(vite) **同时**列为监听者（句柄被继承）→ 据此会误判成生产。
> ⛔ **`/nginx-health` 返回 200 ≠ nginx 在服务**：dev 模式下 vite 的 SPA fallback 会把它当路由吃掉
> （实测 `/nginx-health` 与 `/` 返回同一份 dev HTML）。要证「nginx 在服务」**只认 `Server: nginx` 头**。

### 4.2 后端是否活着

```bash
curl -s --noproxy '*' http://127.0.0.1:5002/api/health
# 期望：200 {"status":"healthy",...}
```

### 4.3 ARQ 是否在线（用哨兵键，别用进程匹配）

```python
# 见 scripts/diag/runtime_mode_probe.py（已改为复用该契约）
# 手工核对：broker 在 :6380（不是 :6379）
AUTH <口令>                                  # 期望 +OK
TTL  arq:queue:health-check                  # 期望 0..61（对应 health_check_interval=60）
GET  arq:queue:health-check
# 期望形如：Sep-17 22:37:48 j_complete=25 j_failed=0 j_retried=0 j_ongoing=0 queued=0
```

判定看**心跳时间戳新鲜度**与 `j_failed`；`TTL=-2` 或键不存在 ⇒ 确实未运行。

### 4.4 一条命令跑完全部上述检查

```bash
python scripts/diag/runtime_mode_probe.py
```

期望：`verdict` = `prod (multi worker …)`、`frontend.is_production` = `true`、`arq.verdict` = `running`。

---

## 5. 常见故障与诊断

### 5.1 「日志是 0 字节 / 乱码 / 滞后」

**先查 NSSM 的 `AppEnvironmentExtra`，别去查日志框架。**

> ✅ **2026-09-28 已修**：`server_manager.py` 的 `_nssm_install` 改为**逐元素**写入
> （列表展开成多个 argv 元素），新装/重装的服务不再有单元素问题。
> ⚠️ **存量服务需要重跑一次 GUI「安装服务」**才会更新为多元素 —— 在那之前，
> 本节描述的故障形态在本机仍然成立（读注册表可确认元素个数）。

机制：`AppEnvironmentExtra` 必须是「**一变量一元素**」。实测 `erp-prod`/`erp-arq` 的类型是
`REG_MULTI_SZ(7)`，但只解出 **1 个元素** —— 整串被塞进一个元素：

```
'APP_ENV=production FASTAPI_DEBUG=false PYTHONPATH=D:\erp_system PYTHONUTF8=1 PYTHONUNBUFFERED=1 UVICORN_WORKERS=8'
```

NSSM 按「每个元素设一个环境变量」（在**第一个 `=`** 处切分）⇒ **只产生 `APP_ENV` 一个变量**，
其余 5 个**从未生效**。后果链：

| 未生效的变量 | 表现 |
|---|---|
| `PYTHONUNBUFFERED` | `prod_runner` 自身 stdout 块缓冲 → `logs/erp-prod.log` **可能 0 字节**、行序错乱 |
| `PYTHONUTF8` | `logs/erp-arq.log` 中文乱码 |
| `UVICORN_WORKERS` | 修复前：worker 数实际来自 `.env`（见 §5.3）；修复后两侧都注入，NSSM 侧优先 |

**读法（无需提权）**：Python `ctypes` + `advapi32.RegOpenKeyExW/RegEnumValueW` 读
`HKLM\SYSTEM\CurrentControlSet\Services\<svc>\Parameters`；`type=7` 的原始字节按
`utf-16-le` 解码后 split `\x00`。现成脚本见 `deliverables/audit-2026-09-17/`。
**修复脚本**：`deliverables/audit-2026-09-17/fix_nssm_appenv.ps1`（先 `-DryRun` 只读预览，再加 `-Restart`）——**需管理员**。

> ⚠️ `erp-redis` / `erp-redis-broker` 的 `AppParameters` **明文带 `--requirepass <口令>`**，
> 本机任意用户可经注册表/Win32_Process 读到 ⇒ **任何产物/工单中引用该配置时必须脱敏**。

### 5.2 「重启后 worker 变成孤儿，新 master 绑不上 `:5002`」

`prod_runner` 的 `_Managed.poll()` 发现 master 退出时只 `_mark_crashed()`，**不调用 `kill_tree()`**。
⇒ 若手工杀掉 master 而**没杀树**，worker 会孤儿占住 `:5002`，新 master 绑不上 → 崩溃循环。

**处置**：重启必须**整树**（`taskkill /F /T /PID <master>`）。这也是必须用 GUI/管理员而不是
手工 `taskkill` 单个进程的原因。

> 注（2026-09-28 重构后）：`erp-web` 的 nginx 由 NSSM Job Object 托管，
> `nssm stop/start erp-web` 会干净杀/起整棵 nginx 树；只有**绕过 NSSM 手工杀**
> nginx master 才会产生孤儿 worker。

### 5.2b 「erp-web 挂了但 erp-prod 全绿」

**这是解耦后的正常现象**：`erp-prod` 的健康只看后端。前端静态服务恢复：
`nssm restart erp-web`（需管理员），API 与备份不受影响。
GUI 前端徽章读的是 `erp-web` 服务状态 + `frontend_ok` 探针交叉验证。

### 5.2c 「回滚到旧结构后重启机器出现双 nginx」

回滚步骤必须先禁用 erp-web 自启，否则旧 `prod_runner` 拉起的 nginx 会与
自启的 erp-web 互斗 `:3000`：

```powershell
nssm stop erp-web
nssm set erp-web Start SERVICE_DISABLED   # 关键:防开机自启双跑
git revert <重构系列提交>
nssm restart erp-prod                      # 旧 prod_runner 重新拉起 nginx
```

### 5.3 「改了 `UVICORN_WORKERS` 没效果」

> ⚠️ **2026-09-28 起结论反转**：`_nssm_install` 修好单元素 bug 后，NSSM 侧的环境变量
> 会**真正注入**；而 `prod_runner._load_dotenv()` 用的是 `override=False`
> —— **操作系统环境变量优先**。因此**重装过服务之后**，NSSM 侧（即 GUI 的 Worker
> 下拉框）**优先于 `.env`**。以下旧结论只在「服务仍是修复前注册的」时成立。

`UVICORN_WORKERS` 有**两个声明源**：

- **`.env`**（仓库根，由 `prod_runner.py` 的 `_load_dotenv()` 加载，`override=False`）
- **NSSM `AppEnvironmentExtra`**（GUI「安装服务」按 Worker 下拉框写入）

**修复前的行为**：NSSM 侧因 §5.1 的单元素 bug 从未注入 ⇒ 只有 `.env` 生效，
改下拉框不会有任何效果。

**修复后的行为（需重装服务）**：两侧都会注入，`override=False` 让 **NSSM 侧胜出**
⇒ 下拉框真正生效，`.env` 的同名项被覆盖。

⇒ **改之前先用 §4 的探针确认实际 worker 数**（`runtime_mode_probe.py` 会报
`prod (multi worker …)` 与 worker 数），不要凭 `.env` 内容推断。
另：代码在两侧都没有该变量时回退 `max(1, min(4, cpu_count))` —— **上限 4**。

### 5.4 「`logs/prod_runner.json` 说 production，但我不确定」

**该文件会谎报**，且其字段本身有两个坑：

- `mode`/`status`：**不可信**。必须交叉验证：声明的 pid 是否存活 + 端口归属 + 真实 HTTP 响应 + 日志写入。
- `started_at`：**是「本次写盘时刻」，不是进程启动时刻**（`prod_runner.py:715` 的 `_iso_now()`），
  实测偏差可达 **28 分钟**。⇒ **别用它判断「服务是否刚重启」**，用进程 `create_time`。

### 5.5 「Redis 挂了，每个 POST 都慢 4 秒」

已知形态：Redis 不可用时**每个 POST 稳定 +4s**（维护模式 / Pub-Sub / 缓存失效监听各自超时叠加）。
判活要发 **RESP `PING`**（`netstat | grep LISTENING` 会漏判「端口活着但握手慢」）。
两个 Redis 都要看：`:6379`（缓存）与 `:6380`（broker）。

---

### 5.6 日志策略与清理（谁在管、怎么改、怎么验证）

**唯一权威是 `config/log_policy.json`**（轮转阈值 / 保留天数 / 目录体积上限）。
三个执行方读同一份文件、调 `utils.log_rotation` 的同一套实现 —— 任何一处都不该再出现独立阈值
（`PROD_LOG_ROTATE_MB` / `NGINX_LOG_ROTATE_BYTES` 已删除，测试锁死不得复活）：

| 执行方 | 频率 | 动作 |
|---|---|---|
| 桌面壳管理器 | 启动 +20s 首跑，此后每 6h | 轮转 + 保留清理 |
| `erp-prod`（prod_runner） | 每 60s | 轮转 + 保留清理 —— **nginx 日志的实际轮转者**（不再单押 ARQ） |
| `erp-arq`（`maintain_logs_task`） | 每日 04:30 | 轮转 + 保留清理（兜底） |

**怎么改**：管理器日志面板「设置」（保存立即对三方生效，无需重启任何服务）；或直接手改 JSON
（越界值按边界夹取：轮转 1–4096MB、保留 1–3650 天、上限 16–65536MB）。阈值必须**高于** NSSM
自身的 `AppRotateBytes=10MB` —— 调到 10MB 以下会去抢 NSSM 正在轮转的 `erp-*.log`。

**「读」侧的分层（不要误判为不一致）**：后端 handler 仍各带微轮转（`fastapi_*.log` 按天×14、
`erp.log`/`error.log` 10MB×10 副本、`access.log` 按天×3），但它们的 `backupCount` 只是
**两轮共享清理之间的次级约束** —— 实际保留期由策略文件的 `keep_days` 决定（`prune_log_files`
按最后写入时间清全部 `logs/*.log*`，prod_runner 每 60s 一轮）。因此「handler 写 14 天、
文件 7 天就没了」是设计使然；要改保留期改策略文件，**不要**去改 handler。

```powershell
# 桌面壳侧动作记录（轮转/清理/巡检摘要都在这）
Select-String -Path logs\server_manager_*.log -Pattern '日志轮转兜底|日志清理完成'
# prod_runner 侧（每分钟轮）的轮转记录
Select-String -Path logs\erp-prod.log -Pattern '\[log_rotation\]'
# 最近轮转出的 .1 副本
Get-ChildItem logs\*.log.1 | Sort-Object LastWriteTime -Descending | Select-Object -First 5 Name,Length,LastWriteTime
```

被占用删不掉的文件按 skipped 记在摘要里、下一轮重试；**连续多轮** skipped 才需要排查
（通常是清理与写入方对同一文件的竞争窗口，或文件句柄被第三方进程长期持有）。

## 6. 备份与恢复（数据保护）

- **调度唯一来源**：`backup_schedule` 表。`scheduler_poller` 每 5 分钟扫表，**会补跑错过的窗口**
  （`last_run_at` 为空即补跑）。
- **调度器依附于 `erp-arq`** ⇒ **ARQ 停了，定时备份就静默停摆**。请把 §4.3 的 ARQ 检查
  纳入例行巡检（当前该信号不存在于 `/api/health`，是已知缺口，见审计 S3）。
- ⚠️ `backup_schedule.last_status` 是**死字段**：只在入队时写 `running`，**全仓无代码回写
  `success`/`failed`** ⇒ 它永远显示 `running`。**不要据此判断「备份失败」** ——
  应当核对 `backups/` 下的产物时间戳。
- 恢复：`pg_restore -Fc`。PG 工具链在 **`D:\PostgreSQL\bin`（不在 PATH）**。
- ⛔ **恢复演练前必读**：迁移链中 `pg_standalone_006` 曾缺失 `from alembic import op`
  （2026-09-17 已修复，提交见审计 S2）。**任何全新安装/灾备全量恢复都会经过该 revision**，
  因此恢复演练应作为常规动作，不要等到真需要时才跑。

---

## 7. 变更前检查清单

- [ ] 我是否有**管理员**权限？（否则 §0 里的任何重启动作都会失败）
- [ ] 当前是 dev 还是 prod？（§4.1 四条判据 / `runtime_mode_probe.py`）
- [ ] 若涉及前端产物：是否已**停开发**再换 `dist`？（§2）
- [ ] 发布前是否已**自己备份 `dist`**？（`swap-dist.mjs` 成功后**不留**回滚副本）
- [ ] 变更后是否**逐项**跑了 §4 的四组验证？
- [ ] 若改了后端源码：是否意识到 **NSSM 下必须重启 `erp-prod` 才生效**？
- [ ] 若动了迁移：是否单独验证过 `alembic upgrade head`（不只是 pytest）？

---

## 8. 相关入口（速查）

| 用途 | 命令 / 路径 |
|---|---|
| 运行模式 + ARQ 判活探针 | `python scripts/diag/runtime_mode_probe.py` |
| 生产巡检（只读） | `deliverables/gstack/perf-selfcheck.ps1`（**必须带 UTF-8 BOM**） |
| 生产预检（非破坏性） | `python -m fastapi_app.core.prod_runner --check` |
| 日志策略（轮转/保留/上限） | `config/log_policy.json`（三方共用；管理器日志面板「设置」可改，改完即生效） |
| 数据库迁移 | `python -m alembic -c migrations/alembic.ini upgrade head`（**在仓库根执行，无需 `cd`、无需 `PYTHONPATH`**；`script_location=%(here)s` 已与 CWD 解耦） |
| 迁移版本查询（只读） | `python -m alembic -c migrations/alembic.ini heads` / `history` |
| 环境变量修复 | `deliverables/audit-2026-09-17/fix_nssm_appenv.ps1`（**需管理员**） |

---

> 本文档的技能树位置：`docs/runbooks/service-lifecycle.md`。
> 若发现本文与实测不符，**以实测为准并立即修正本文** —— 一份过期的 Runbook 比没有更危险。
