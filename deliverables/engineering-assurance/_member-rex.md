# 事故响应报告（成员产出）— Rex · SRE 工程师

- **任务**：#3 事故响应（检测定级 / 影响评估 / 根因 / 复盘）
- **报告时刻**：2026-09-17 22:16（本地，UTC+8）
- **方法**：只读独立复核。进程/服务/文件/事件日志用 PowerShell 采集，模式探针与 Redis 哨兵键用系统 Python（`C:\Users\Administrator\AppData\Local\Programs\Python\Python313\python.exe`）现场复现，`backup_schedule` 表用 **`SET TRANSACTION READ ONLY`** 连接只读查询。**未做任何写操作。**
- **一句话结论**：**当前不存在活跃在线事故**；主理人「ARQ 未运行」的前提已被现场数据证伪。本次响应的真实价值在**检测能力缺陷与观测盲区**，而非一次服务中断。

---

## 0. 结论摘要（TL;DR）

| # | 事项 | 结论 | 定级 |
|---|---|---|---|
| 1 | 在线服务是否有中断 | **无**。/api/health 200、/:3000 nginx-health 200、ARQ 哨兵键新鲜、6 服务 Running+Auto | — |
| 2 | 21:46:19–21:46:35 整栈重启是什么 | **一次被「紧急停止」中止的「切开发模式」操作，随后回滚到生产**（人为/工具触发），**不是** ARQ 宕机、**不是**机器重启、**不是** `AppExit` 自愈 | 历史事件 SEV-4 |
| 3 | 模式探针 `runtime_mode_probe.py` 对 ARQ 报 `not running` | **确认是假阴性**，已现场复现。它靠进程 cmdline 判活，而 NSSM 提权派生的进程 cmdline 读不到 | **潜在 SEV-3** |
| 4 | ARQ 健康是否被任何健康/监控端点暴露 | **没有**。仓内已有可靠判活契约 `check_worker_health()`，却只被备份端点消费 | **潜在 SEV-3** |
| 5 | `logs/erp-prod.log` = 0 字节 | **确认**，mtime=21:46:31。`PYTHONUNBUFFERED` 未真正注入 → `prod_runner` 自身 stdout 块缓冲，启动日志滞留内存 | **潜在 SEV-3** |
| 6 | `prod_runner.json` 的 `started_at` | **确认语义错误**：它是「本次写盘时刻」，非进程启动时刻。实测比真实启动晚 28 分钟 | 潜在 SEV-4 |
| 7 | `UVICORN_WORKERS=8` 的来源 | ⚠️ **对主理人结论的纠正**：8 来自 **`.env:171`**（被 `_load_dotenv()` 加载），**不是**代码默认值（代码默认封顶为 4）。NSSM 侧声明为死配置 | 潜在 SEV-4 |
| 8 | 备份数据保护现状 | **备份实际在正常运行并产出产物**；但 `backup_schedule.last_status` 是**死字段**（永远 `running`）→ 监控失真 | **潜在 SEV-3** |

---

## 1. 事故时间线

### 1.1 现场状态快照（2026-09-17 22:12–22:15，只读实测）

进程链（`Win32_Process`，cmdline 因 NSSM 提权派生读不到，按父子关系判定）：

| 服务（NSSM 宿主） | 子进程链 | 创建时刻 |
|---|---|---|
| `erp-prod` (nssm 1272) | prod_runner **18916** → uvicorn master **7676** → **8 worker**（1488/17692/7500/18728/4080/15420/10116/17276） | 21:46:31 |
| `erp-arq` (nssm 4328) | python.exe **16904** | 21:46:33 |
| `erp-redis` (nssm 4220) | redis-server **16448** | 21:46:29 |
| `erp-redis-broker` (nssm 4180) | （broker :6380） | — |
| `postgresql-x64-18` (4608) / `postgresql-replica` (4616) | — | — |

- 6 个服务全部 **State=Running, StartMode=Auto**。
- HTTP 实测：`/api/health` → **200**；`/nginx-health` → **200**；`/` → 200。
- Redis：`:6379` PING → `+PONG`；`:6380`（broker）AUTH → `+OK`。
- ARQ 哨兵键（broker :6380）`arq:queue:health-check` = `Sep-17 22:14:43 j_complete=13 j_failed=0 j_retried=0 j_ongoing=0 queued=0`，TTL 循环 0–60（探测时 TTL=9）。

### 1.2 21:46:19–21:46:35 的整栈重启 —— 已定性

证据：`logs/server_manager_20260917.log:5661-5692`（工作台 GUI 自身日志）+ 各进程 `create_time`。

| 时刻 | 事件（GUI 日志原文摘要） |
|---|---|
| 21:46:19.949 | `正在启动开发模式（前后端）...` |
| 21:46:19.951 | `正在停止生产服务 erp-prod...` |
| 21:46:21.565 | `正在停止生产服务 erp-arq...` |
| 21:46:23.245 | `已自动停止生产模式` |
| 21:46:23.656 | `后端进程已启动 (PID: 2572)`（dev 后端，`--reload`） |
| 21:46:23.856 | **`正在取消动作：启动开发模式（前后端）…`** |
| 21:46:24.545 | `日志已清空` ⟵ **解释 erp-prod.log=0** |
| 21:46:26.709 | **`启动开发模式（前后端）已中止（原因：紧急停止）`** |
| 21:46:26.715 | 终止 dev 后端 PID 2572 |
| 21:46:26.927 | `已终止端口6379占用进程 (PID: 14320)` |
| 21:46:27.972 | `正在启动生产模式 (Windows 服务 NSSM)...` |
| 21:46:31.457 | `Redis 已由服务 erp-redis 启动` / `正在启动生产服务 erp-prod...` |
| 21:46:33.490 | `erp-prod 启动成功 (state=4 RUNNING, PID: 1272)` |
| 21:46:35.533 | `erp-arq 启动成功 (state=4 RUNNING, PID: 4328)` / `生产模式启动完成` |

**判定**：这是**一次被 `紧急停止` 中止的开发模式切换尝试，随后回滚生产**。
- 排除「机器重启」：`Win32_OperatingSystem.LastBootUpTime = 2026-09-17 15:44:56`（探测时 uptime 6h28m），21:46 无 6005/6006/1074 引导/关机事件。
- 排除「`AppExit=Restart` 异常自愈」：进程重建由 GUI 的「启动生产模式」动作发起，且此前显式执行了「停止生产服务」。
- 系统事件日志（21:40–21:52）**未记录任何 SCM 服务控件事件**（7031/7034/7036/7040/7045/7046 全为空）——**此通道不足以作证**，故以 GUI 日志 + 进程 `create_time` 为准。**[未确认]：SCM 事件为何缺失，需后续确认（日志策略/提供程序本地化过滤）。**

### 1.3 全天模式切换清单（可靠性背景）

`logs/server_manager_20260917.log` 显示当天**至少 14 次** dev/prod 模式切换：08:36、08:37、09:17、11:20、11:33、11:34(×2)、13:15、16:05、16:14、17:12、18:29、20:50、21:46。**生产机被当作开发机频繁切换**，每次切换都会停掉生产栈再起。20:50 亦有一次完整生产重启。这是**流程性风险**（详见 §4 与预防措施）。

---

## 2. 影响范围

### 2.1 活跃影响：无
端点、ARQ、Redis、DB、前端全部在线；ARQ `j_failed=0`。**无活跃用户影响，无需客户通知。**

### 2.2 21:46 事件的历史影响：约 13–16 秒全栈短暂不可用
从 21:46:20（prod 开始停）到 21:46:33（erp-prod RUNNING），生产 API(:5002) 与 nginx(:3000) 均不在线。窗口内任何在途请求会失败。影响面 = 全体用户，但时长极短、且由运维主动动作引发、已自动恢复，**无客户报障记录被提及**。

### 2.3 检测/观测盲区的影响（真正需要定级的）
- **探测工具会谎报**：`runtime_mode_probe.py` 对**运行中**的 ARQ 报 `verdict="not running"` 且 `arq_worker_processes: []`。若真的 ARQ 宕机，同一工具**输出完全相同** → **运维无法区分「真宕机」与「探针误报」**（见 §4-A，已现场复现）。
- **ARQ 无对外健康信号**：全仓通用健康/监控端点（`core/health.py` 的 `/api/health`、`/api/health/db|live|ready|startup`、`/metrics`）**都不查 ARQ**。`/api/health` 的 `internal_checks` 只有 `database` 与 `redis`。因此**外部监控即使轮询 `/api/health`，ARQ 死亡也表现为“healthy”** → 备份链路可静默停摆。
- **启动期无磁盘证据**：`erp-prod.log`=0 字节，`prod_runner` 自身启动日志滞留内存。若启动期故障（如 nginx 端口冲突、迁移未跑），**磁盘上无任何可查证据**。

---

## 3. SEV 评级

| 对象 | 等级 | 论证 |
|---|---|---|
| **活跃事故** | **无** | 无在线中断。如实给出，不虚构。 |
| **21:46 整栈重启** | **SEV-4** | 全栈不可用但仅约 13–16 秒、主动动作引发、已恢复、无客户影响。按分级定义（次要功能/低影响、下一工作日响应）落 SEV-4，记录为**操作近失（near-miss）**而非常规事故。 |
| **检测能力缺陷（探针假阴性 + ARQ 未上健康端点）** | **潜在 SEV-3** | 该缺陷**移除的是「发现故障的能力」**。若 ARQ 真宕机，备份/告警等定时任务静默停止，而其后果（数据保护失效）在相当长时间内**不可见**；探针还会持续输出误导性 `not running`。属「次要功能问题、1 小时内响应」量级的**潜在**风险，故 SEV-3。 |
| **观测盲区（erp-prod.log=0 / last_status 卡 running）** | **潜在 SEV-3** | 直接拉长 **MTTD/MTTR**；把「可定位的故障」变成「无从下手的故障」。分级同 SEV-3。 |
| **状态字段语义错误 / 配置效果脱钩** | **潜在 SEV-4** | 不直接致障，但会**把诊断引向错误结论**（低影响、下个工作日响应）。 |

> SEV 评级说明：本表按「若发生则」的**潜在**等级定级，并显式区分「已发生的 21:46（SEV-4）」与「尚未发生但能力缺失的潜在 SEV-3」。**当前无任一 SEV-1/2。**

---

## 4. 根因分析（5 Why）

### A. 核心缺陷：模式探针假阴性 —— 「有正确契约却未接线」

事实链（**现场复现**，22:14:17 输出）：
```
api_listening_pids: [7676]
api_processes: [ { "pid": 7676, "error": "(pid=7676)" } ]   ← psutil 读 cmdline 抛错
verdict: "not running"                                       ← 假阴性
arq_worker_processes: []                                     ← 假阴性
```

1. **Why 探针报 not running？** → `runtime_mode_probe.py:79` `cmdline = proc.cmdline()` 对 NSSM 提权派生的 uvicorn master **抛 `psutil.Error`**，被 `:91-92` 吞进 `detail`，而 `verdict` 保持 `:74` 的初值 `"not running"`。
2. **Why 抛错？** → NSSM 以提权身份派生进程，其 `cmdline` 对非提权读取者不可见（本次同样解释 `arq_worker_processes` 为空：`:128-132` 靠 cmdline 含 `"arq"` 匹配，而 ARQ 进程 16904 的 cmdline 读不到）。
3. **Why 用 cmdline 判活？** → 脚本 docstring `:3-9` 把「5002 监听进程的 cmdline」当作**唯一可靠判据**——该前提在 NSSM 环境下不成立。
4. **Why 没发现该前提错误？** → 它**没有复用仓内既有的权威判活契约** `core/arq_app.py:check_worker_health()`（哨兵键 `queue_name + ':health-check'`，`getattr(pool,'default_queue_name')` 解析队列名，三态文案，`:182-229`）。
5. **Why 有契约不用？** → 该契约**只被备份端点消费**（`backup/actions.py:72-83` 入队前 503 预检；`backup/validation.py:239-254` 备份预检聚合 `:304`），**从未接入任何通用健康/监控端点**（`core/health.py` 不含 ARQ）。→ **契约与监控面之间缺一根线**，导致第二套（错误的）判活逻辑被独立发明。

**一句话根因**：**权威判活契约存在但未接线到监控/诊断面，诊断脚本改用不可靠的进程 cmdline，且异常吞没掩盖了失败。** 这正是「静默降级无人察觉」的翻版——只不过这次谎言来自**用来发现事故的工具本身**。

### B. 观测盲区：erp-prod.log = 0 字节

1. **Why 0 字节？** → `prod_runner` 的 stdout 无任何 flush。
2. **Why 无 flush？** → `PYTHONUNBUFFERED=1` 对 `prod_runner` **未生效** → 其自身 stdout 走块缓冲，启动 banner（`prod_runner.py:683`）滞留内存。
3. **Why 未生效？** → NSSM `AppEnvironmentExtra` 被写成**单个 `REG_MULTI_SZ` 元素**（`_reg_svc.txt`：`['APP_ENV=production ... UVICORN_WORKERS=8','']`），NSSM 只在第一个 `=` 处切分 → 只设了一个名为 `APP_ENV` 的变量，`PYTHONUNBUFFERED` 等**均未注入**。
4. **Why 子进程有日志而它没有？** → `prod_runner` 给**子进程**显式设了 `PYTHONUNBUFFERED=1`（`prod_runner.py:312`），故 `后端(uvicorn).out.log` 有 143KB；但**它自己**由 NSSM 拉起，拿不到该变量 → 自己裸奔。
5. **Why 未被察觉？** → GUI 在 21:46:24 执行了「日志已清空」，重启后 0 字节看起来「像刚启动」，无人能分辨「正常空文件」与「启动异常但无处可写」。

**运维代价量化（"无日志可查"）**：正常排障依赖启动日志在 **秒级**定位问题；此缺陷下启动期故障的**磁盘证据 = 0 条**，MTTD 从「分钟级」退化为「必须复现或加 instrumentation 才能定位」，且**重启会破坏现场**（日志被清空 + 内存缓冲丢失）。对一个「本机即生产」的系统，这是**不可接受的观测空洞**。

### C. `prod_runner.json` 的 `started_at` 语义错误

1. **Why 字段叫 started_at 却非启动时刻？** → `prod_runner.py:715` `"started_at": _iso_now()`，而 `_iso_now()`（`:154-155`）= `datetime.now()` = **写盘时刻**。
2. **Why 每几秒变？** → `write_status()` 在主循环 `:774` 每轮调用，循环间隔 3s（`:777`）。
3. **实测证据**：JSON `started_at=2026-09-17T22:14:16`，真实进程启动 = **21:46:31** → 偏差 **28 分钟**；JSON mtime 与 `checked_at` 仅差 1 秒。
4. **后果**：任何用 `started_at` 判断「服务是否刚重启」的逻辑**必然得出错误结论**。
5. **旁证**：GUI 也依赖文件 mtime 推断（`:5692`「生产服务 8s 前刚启动…状态文件最后更新 21:46:20」），说明系统内**多处**在用不可靠的时间语义。

### D. 配置与效果脱钩 —— 对主理人结论的纠正

主理人主张：「8 是**代码里的默认值**，不是配置生效」。**实测证据不支持该归属，需纠正**：

- 代码默认（`prod_runner.py:81-85` `_default_workers()`）在无环境变量时为 `max(1, min(4, cpu_count))` → **最多 4，不可能是 8**。
- 生效值来自 **`.env:171 UVICORN_WORKERS=8`**，由 `_load_dotenv()`（`prod_runner.py:66-71`，`load_dotenv(PROJECT_ROOT/".env", override=False)`）加载，被 `_default_workers()` 读为 `configured>0` → 返回 8。
- 直接证据：`server_manager_20260917.log:66` `[prod_runner] 启动生产模式 (workers=8, ...)`。

**因此更准确的表述是**：
- **效果（8）来自 `.env`，是配置生效**，不是代码默认值。
- **NSSM 侧的 `UVICORN_WORKERS=8` 声明是死配置**（单元素 bug → 未注入）。故「在 NSSM 里改 `UVICORN_WORKERS` 无效」**成立**；但「8 来自代码默认值」**不成立**。
- **真正的风险**：**同一参数有两个声明源（NSSM + `.env`），只有 `.env` 生效，NSSM 侧被静默忽略**。`.env:164` 甚至写着「必须与 NSSM `AppEnvironmentExtra` 里的 `UVICORN_WORKERS` 必须一致」——该不变式**根本无法被强制**（NSSM 永不应用）。当前两者恰好都=8，掩盖了此问题；一旦有人只改 NSSM，会以为生效而实际没有。
- 附带：`core/database.py:31` 的连接池分摊也读同一环境变量，当前与 8 一致（无三方错位），但同样受「NSSM 改动无效」影响。

### E. 备份监控失真（`last_status` 死字段）

- `backup_schedule` 只读实测（2 行）：

| id | name | task_type | cron | enabled | last_run_at (UTC) | last_status |
|---|---|---|---|---|---|---|
| 18 | 自定义增量备份 | incremental | `0 2 * * *` | true | 2026-09-17 01:20:01 | **running** |
| 19 | 每日全量备份 | full | `0 2 * * *` | true | 2026-09-17 08:59:21 | **running** |

- **备份实际在正常产出产物**（交叉验证成立）：
  - `backups/server/erp_auto_daily_20260917_165927.zip`（8.67MB）@ 16:59:27 CST = **08:59:27 UTC**，与 id=19 `last_run_at`（08:59:21 UTC）**吻合** → 每日全量备份**今天成功跑过并产出健康产物**。
  - `backups/server/erp_incremental_20260917_012003.zip` @ 09:20:04 CST = **01:20:04 UTC**，与 id=18 `last_run_at`（01:20:01 UTC）**吻合**。
- **5 Why（监控失真）**：`last_status` 仅在入队时被写为 `running`（`tasks/backup_tasks.py:291`），**全仓无任何代码把成功的调度回写为 `success`/`failed`**（`shared_models/backup_schedule.py:26` 注释声明了 success/failed/running 三态，但后两态无人写）→ 字段永远停在 `running` → **失败也会显示 running** → 调度表无法区分成功与失败。
- **结论**：这是**监控真实性缺陷，不是数据保护失效**。不应据此宣称「备份失败」。
- **[未确认]**：声明 cron 为 `0 2 * * *`，但实际处理批次出现在 ~16:59 CST / ~09:20 CST，**02:00 档未见对应产物** → 疑似调度时区/语义偏移。**证据不足以定性，标记为待复核，勿写成结论。**

---

## 5. 行动项

| # | 行动 | 优先级 | 归属 | 验收标准 |
|---|---|---|---|---|
| A1 | **把哨兵键判活接入统一健康检查**：在 `core/health.py` 的 `/api/health`（或 `/api/health/ready`）中复用 `check_worker_health()`，将 `arq` 纳入 `internal_checks`；ARQ 离线时 `/api/health` 返回 **503 / status=unhealthy**（或至少 `checks.arq.status=unhealthy`） | P0 | 后端 | 停掉 erp-arq 后 `/api/health` 在 ≤90s 内变 unhealthy；恢复后自动转 healthy |
| A2 | **修复模式探针**：删除 `runtime_mode_probe.py` 中基于 cmdline 的两处判定（`:51-61 classify`、`:128-132 arq_worker_processes`），改用 `check_worker_health()` 哨兵键；并对「cmdline 读不到」与「真的没进程」给出**可区分**的 verdict（三态：`running / not_running / probe_unknown`）。禁止把 `psutil` 读失败静默成默认值 | P0 | 后端/运维 | 在对运行中的生产栈运行探针时，`verdict` 必为 `running`、`arq_worker_processes` 非空（或明确 `probe_unknown`），不再出现假阴性 |
| A3 | **恢复 prod_runner 自身日志可查**：修正 NSSM `AppEnvironmentExtra` 为**每变量一个元素**（`fix_nssm_appenv.ps1` 已存在），使 `PYTHONUNBUFFERED=1` 真正注入；或在 `prod_runner` 启动首行**显式 `sys.stdout.reconfigure(line_buffering=True)` / `flush=True`**，不依赖 NSSM | P0 | 运维 | 重启后 `logs/erp-prod.log` 秒级出现启动 banner（非 0 字节） |
| A4 | **修正 `started_at` 语义**：改名为 `status_updated_at`（保留兼容别名），并**新增真实进程启动时刻** `process_started_at`（可在 `Supervisor.run()` 起点取 `_iso_now()` 存实例字段） | P1 | 后端 | GUI/脚本据 `process_started_at` 能正确判断「是否刚重启」；实测与进程 `create_time` 一致 |
| A5 | **消除配置双源**：统一以 `.env` 为唯一真源，移除 NSSM 侧 `UVICORN_WORKERS`（或反向：修好 NSSM 后删 `.env` 重复项），并让 `prod_runner --check` 打印「生效 worker 数 + 来源」 | P1 | 运维 | `--check` 明确显示来源；改 NSSM 或改 `.env` 的行为与文档一致 |
| A6 | **修复备份调度状态回写**：任务函数成功/失败时回写 `backup_schedule.last_status = success/failed`（含 `last_error`），使调度表可信 | P1 | 后端 | 一次成功备份后 `last_status=success`；人为制造失败后=`failed` |
| A7 | **模式切换协议**：为「切模式 / 紧急停止」增加**二次确认 + 中止后自动回滚校验**（回滚后必须确认 prod 全绿才结束），并在中止路径打印明确状态 | P2 | 运维/工具 | 复现「启动 dev → 紧急停止」后，系统自动确认已回到 prod 健康态并留痕 |
| A8 | **复核调度 cron 时区语义**（`0 2 * * *` 实际未在 02:00 触发） | P2 | 后端 | 给出调度时区与触发时刻的实测对照，明确 02:00 档是否缺失 |
| A9 | 清理 SRE 临时证据文件（`deliverables/engineering-assurance/_rex_*`）或归档 | P3 | 本成员 | 目录整洁 |

---

## 6. 预防措施

1. **单一判活契约（Single Source of Truth for Liveness）**：ARQ 判活**只能**通过 `check_worker_health()` 哨兵键。在 CI 增加「禁止新增基于 cmdline 的进程判活」的 lint/约定，并在 `runtime_mode_probe.py` 顶部注明「判活一律复用 `check_worker_health`」。
2. **健康端点必须覆盖全部关键依赖**：把「健康检查必须包含 ARQ」写入评审清单。当前 `/api/health` 只覆盖 DB+Redis，等于**默认假设 ARQ 永不挂**——这正是静默降级温床。建立「核心依赖清单 → 健康检查逐项覆盖」的对照表。
3. **监控的真实性 > 监控的存在性**：`last_status` 死字段、探针假阴性、`started_at` 谎报，三者同源——**字段/工具存在但没有被验证过会「说真话」**。对每个监控信号建立**正反向验证**：「制造一次故障，信号是否变化？恢复后是否自动复位？」（A1/A2/A6 的验收标准即按此设计）。
4. **启动日志红线**：任何生产进程**不允许**在磁盘上零字节。将「重启后 N 秒内 `logs/*.log` 出现启动行」纳入部署检查清单（本仓已有 `scripts/diag` 体系，可加一条断言）。
5. **配置真源化**：杜绝同一参数在多处声明。NSSM/`.env`/代码三处取值的**优先级必须可解释且有测试**；`prod_runner --check` 输出「值 + 来源」。
6. **生产机不与开发模式混用**：当天 ≥14 次模式切换说明生产机被当开发机。若确需，应把「切模式」纳入变更管理并保证**切前/切后健康校验**，避免「切一半被紧急停止」留下窗口。

---

## 附录 A：证据清单（只读产出，位于 `deliverables/engineering-assurance/`）

| 文件 | 内容 |
|---|---|
| `_rex_probe_output.txt` | **探针假阴性复现**（verdict=not running、api_processes error、arq_worker_processes=[]） |
| `_rex_arq_out2.txt` | 独立哨兵键读取（AUTH +OK；`j_failed=0`，TTL=9） |
| `_rex_probe_proc.txt` | 服务状态 + 进程树 + create_time |
| `_rex_probe_live.txt` | 日志文件 size/mtime（`erp-prod.log size=0`） |
| `_rex_probe_event.txt` / `_rex_probe_event2.txt` | 启动时刻（15:44:56）与事件日志查询结果 |
| `_rex_probe_backups.txt` | 备份产物时间戳（`erp_auto_daily_20260917_165927.zip` 等） |
| `_rex_db_output.txt` | `backup_schedule` 只读查询（2 行） |
| `_rex_http.txt` | HTTP 健康探测（全 200）+ 后端日志尾部 |
| `_rex_db_query.py` / `_rex_arq_probe2.py` | 复现用只读脚本 |

## 附录 B：未确认 / 需后续确认项

1. **[未确认]** SCM（服务控制管理器）事件为何在 21:40–21:52 无任何记录（7031/7034/7036/7040/7045/7046 全空）——需确认日志策略或提供程序本地化过滤。
2. **[未确认]** `backup_schedule` 声明 cron `0 2 * * *` 却未见 02:00 档产物——疑似调度时区/语义偏移，需实测对照。
3. **[未确认]** `后端(uvicorn).out.log` 中文乱码（GBK/UTF-8 不一致），与 `erp-arq.log` 编码表现不一致——是否影响排障可读性待评估。
4. **不做结论**：21:46 的「启动开发模式」由谁触发（人工/GUI/自动化）——日志未记录触发者身份，**不猜测**。
