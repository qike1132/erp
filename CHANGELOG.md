# 变更日志 (Changelog)

## [2026-10-16] 服务器管理器 v5.40：退出进程孤儿 / 紧急停止窗口 / 跨线程 Tk 等审计修复

两轮修复合并发版（2026-10-15 审计修复 `4169aa03` + 2026-10-16 结构评审修复 `1dd4de90`）。

### 🔴 修复（高危）
- **退出进程孤儿**：`_do_quit` 旧实现只杀后端、不碰 `_frontend_process`（开发模式退出后 vite 残留 :3000）、且经守护线程起 taskkill 会被解释器关闭掐断（竞态）；退出瞬间有动作在飞时闸门直接拒绝、后端+前端+直接拉起的 Redis 三重孤儿。改为同步 `terminate_dev_processes` + `_stop_redis`，且先 `gate.cancel` + `wait_idle`（H2：不取消在飞动作的话，启动 worker 会继续 Popen 进程然后被掐断，照样孤儿）。
- **开发模式健康检查吃系统代理**：两处 `127.0.0.1` 探测用裸 `urlopen`（constants 已实证的事故模式：代理转发本机探测间歇假失败 → 误杀刚拉起的进程），改 `_HTTP_DIRECT` 直连 opener。

### 🟡 修复（中危——「紧急停止窗口」一族）
- **M1**：紧急停止清扫期（可达数十秒）按钮全可点，此时点启动 `gate.start` 会 clear 掉取消标志、与清扫并发互踩。清扫期置灰全部操作按钮，`stop_all_done`（成功/异常两路）复位。
- **M3/L4**：`_prod_running` 双写方，滞留的采集结果在清扫期翻回 True 与停止矛盾；`_mode` 直落 'none' 让徽章谎报「已停止」。加 `_stopping_all` 标志丢弃窗口内采集轮（放弃型助手 `_apply_stopping_all` 全徽章置「状态未知」），mode 走 'stopping' 过渡态。
- **M2**：`sc query` 漏在 Tk 主线程渲染阶段（5s 超时冻界面），`web_svc_state` 挪进采集阶段。
- **M4**：`log_message` 从 worker 线程调 `root.after_idle`（跨线程碰 Tk，间歇崩溃经典来源），flush 改经 `log_flush` 消息队列回主线程派发。
- **开发卡补「停止」按钮**：v5.33 卡片改版把停止按钮丢了，`stop_dual_dev` 成了 UI 不可达死方法，只能靠「紧急停止」（连 Redis 一起停）间接停开发。补按钮（仅运行中可用）。

### 🟢 修复（低危清理）
- `wait_service_stopped` 在 nssm 缺失时把 None 塞 argv 被 run_capture 吞成 -1（停止命令根本没发出），补 `sc stop` 回退。
- `read_frontend_stdout` 退出后不关 stdout（句柄悬到 GC），补 try/finally。
- `stop_dual_flow` 作为闸门 worker 全程无 checkpoint，补步骤边界。
- Worker 数读取默认 20s 超时且在主线程跑（nssm 卡住冻界面），主线程读现状改走 3s 限时通道。
- 删 9 个全仓零引用死转发（含上轮漏网的 `_find_redis`）；`_log_size`/`_read_log_lines` 收编 log_ops；`decode_output` 提为模块级纯函数（log_ops 不再依赖整个 ServiceOps）。
- 生产卡「停止/重启」随 `_prod_running` 联动；环境检查告警去 `after(500)`；裁剪首帧装饰动画（低配机拖累）。

### ✅ 验证
- server_manager 全家 161 passed（新增 `tests/test_sm_audit_2026_10_15.py` 29 条，含 sc 回退/日志尾部读取/解码器行为级验证；既有 backup_badge 契约在 M3 第一版上真实拦截「丢弃不置灰」，按契约补弃型助手）。
- `quality_gate.py` PASS（ruff 棘轮累计净减 13）；app.py 违规数与改前基线持平。
- app.py 1525 → 1473 行。

### 🏗️ 打包
- 版本号 `v5.35 → v5.40`（`constants._VERSION` + `server_manager.spec` 产物名 + `docs/PROJECT_MANUAL.md` 现行版本表述）。
- `.venv` 里没有 PyInstaller，重打包用系统 Python（已装 6.19.0），且需先退出正在运行的管理器 exe（文件被占用写不进去）。产物 `dist/ERP服务器管理器_v5.40.exe`。

## [2026-10-13] 服务器管理器 v5.35：修复「点重启后 erp-prod 起不来」

### 🔴 修复：重启后服务停在 STOPPED，必须手点「启动」才能恢复
- **现场**：管理器日志 3 次 `erp-prod 在 25s 内未进入 RUNNING（当前: 1 STOPPED）`（10-12 17:34、10-12 20:58、10-13 08:12），每次都紧跟「正在重启生产服务 erp-prod...」；事后手点一次「启动」即恢复。
- **根因（一）**：重启被交给 `nssm restart`，而 NSSM 2.24 的实现是 `ret = control_service(STOP); if (ret) nssm_exit(ret); control_service(START);`（nssm.cpp:271-275）——**停机阶段返回非 0 就直接退出，start 根本不会发出**。Windows 事件日志的指纹完全吻合：08:12 那次 `erp-prod` 只收到 STOP control、没有 START control，而同一刻其余 4 个服务都是 STOP+START 成对。更糟的是管理器把 nssm 的返回码与 stderr **全部丢弃**，界面上只剩「25s 内未进入 RUNNING」，故障无从定位。
- **根因（二）**：`prod_runner.kill_tree` 的软杀等待把停机拖出了 NSSM 的停机预算。NSSM 预算是 `AppStopMethodConsole=1500ms + AppStopMethodThreads=1500ms ≈ 3s`（NSSM 默认值，本仓 `nssm_install` 未覆盖），而软杀链路要 ~4.2s：实测 `taskkill /T`（不带 `/F`）对 `CREATE_NO_WINDOW` 子进程 **0.06s 就返回 rc=128**（「只能强制终止此进程(带 /F 选项)」）、一个进程都没杀掉，随后却白等 4s 才硬杀。监督器被 NSSM TerminateProcess 掉，**uvicorn 进程树成为继续占着 :5002 的孤儿**。此回归由 2026-10-11 的 P1-9（`657ccee4`）引入，其注释「4s 远小于 nssm restart 的停机容忍」是错的。
- **改法**：`ServiceOps.restart_service_via_stop_start` 取代 `nssm restart` —— 显式 `nssm stop` → 等 STOPPED → `nssm start` → 等 RUNNING，**start 无条件执行**；stop 的返回码与原文如实写进日志，停机未确认 STOPPED 也告警。整栈重启与「只重启 erp-prod」共用它。`kill_tree` 改为「软杀只在它**报告成功**（rc=0）时才等待」，窗口 4.0 → 1.0s（软杀 0.06 + 窗口 + 硬杀 0.05 ≈ 1.1s，仍在 1500ms 内），软杀成功却超时升级时留一条 WARNING（免得「优雅关停没走完」以后只能靠收尾哨兵不亮反推）。
- **顺带（消灭假成功）**：重启链路补上清端口（注入 app 的 `_release_ports`，与「启动生产模式」一致）。实测孤儿占着时 `bind 127.0.0.1:5002` 报 WinError 10048 —— 不清端口的话重启会变成「服务 RUNNING、界面报启动成功，但后端崩在绑定上」。

### ✅ 验证
- 聚焦回归 79 passed，含新增 `tests/test_sm_restart_stop_start.py`（stop→start 顺序、停机非零仍发 start、停机失败原文入日志、停机未确认告警、清端口时序、未注入不报错）。
- 变异检查逐条做过：把 start 改回 `nssm restart` → 4 条新测试全红；去掉软杀 `rc==0` 门 → 对应测试红；去掉三处新增行为 → 三条新测试 1:1 变红；恢复后全绿。
- `ruff`（改动文件）All checks passed、`mypy` Success 379 files、`scripts/quality_gate.py` exit 0 PASS。
- 独立评审（未参与实现的新上下文、最强模型）两轮：首轮 2 个 Medium（软杀窗口偏小、停机未确认时静默）已修，复审**零 High/Medium**。

### 🏗️ 打包
- 版本号 `v5.34 → v5.35`（`constants._VERSION` + `server_manager.spec` 产物名 + README/README_DEPLOY 的现行版本表述）。
- **注意**：`.venv` 里没有 PyInstaller，重打包要用系统 Python（已装 6.19.0），且需先关闭正在运行的 `ERP服务器管理器_v5.34.exe`（文件被占用会写不进去）。命令：`pyinstaller server_manager.spec` → 产出 `dist/ERP服务器管理器_v5.35.exe`。

## [2026-09-30] 服务器管理器 v5.34：生产日志实时输出 + 日志文件定时清理

### 🔴 修复：生产模式「运行日志不是实时输出」
- **根因**：开发模式的前后端由管理器自己 `Popen`，stdout 是管道，读到即显示；而生产模式跑在 NSSM 服务里，stdout 被重定向到 `logs\{erp-prod,erp-arq,erp-web}.log` —— 管理器与进程之间**没有管道**。原实现只在点「启动服务」那一刻回灌一次新增字节，此后界面一片安静（用户实测：「没有实时输出」）。
- **改法**：新增 `server_manager/log_ops.py::ProdLogTailer`，以 1s 轮询补齐这条管道（等价 `tail -f`）。契约：接入前的历史**绝不回灌**（那是上一次运行的旧 PID/旧崩溃栈）；半行缓冲到换行再出；超量只延后一轮不丢弃。
- **轮转判据**：不只比文件大小 —— NSSM 按 10MB 轮转是「旧文件改名 + 新文件从头写」，新文件可能已长过旧 offset，只比大小会**静默吞掉新文件开头几行**。故加文件句柄号（`st_ino`）变化判据，命中即重置游标并如实说明。
- **开关**：由权威状态（`sc query` 的 api_running）驱动，每轮托管刷新幂等同步 —— 覆盖「管理器启动时生产早就在跑」；采集失败（`collect_error`）时**不**关管线（「不知道」≠「生产停了」）。

### 🆕 功能：日志文件定时清理（不再只增不减）
- **问题**：NSSM 只按 `AppRotateBytes=10MB` 轮转、**从不删除**旧副本；`server_manager_YYYYMMDD.log` 每天新增一个也永不清理（现场 `logs/` 已 51MB / 21 个文件，`erp.log`/`error.log`/`fastapi_*` 各 9–15MB）。
- **改法**：`log_ops.prune_log_files` 双闸门清理 —— 按最后写入时间（默认保留 **14 天**，与后端 `fastapi_*.log` 约定一致）+ 目录总体积上限（**512MB**），两轮都最旧先删。
- **安全边界**：只碰 `logs\*.log*`，`prod_runner.json`/`nginx.pid`/`watchdog_state.json` 这类状态文件永不入候选；1 小时内有写入的（正在用的）文件不删；删不掉（被 NSSM/nginx 占用）只记 skipped 并在面板如实报告，绝不让整轮清理失败。
- **调度与入口**：管理器启动 20s 后首跑、此后每 24h 一轮；日志面板新增「清理旧日志」按钮可随时手动跑，标题旁常驻「日志文件自动清理：保留 14 天」，避免用户以为「清空」只清了显示。

### 🆕 功能：日志健康巡检（「谁在疯长」+ 异常增长告警）
- **问题**：保留清理只回答「过期没」，不解释**增长**。同为 100MB，安静攒了 14 天的访问日志与崩溃循环半小时刷出来的错误栈，处置完全不同 —— 而原来无人知道是哪一个在长。
- **改法**：`log_ops.inspect_log_health` 每次采样把 `(文件, 大小, 时刻)` 落一份快照（`logs/log_health_state.json`，刻意不含 `.log` 后缀，故不会被清理或被误统计），下一轮相减即得**字节/天**（增长率只能来自两次采样，这是唯一可靠来源）。
- **面板**：日志面板标题下新增巡检行：`日志巡检 20:27 · 合计 49.7MB / 18 个文件 · 增长最快：fastapi_20260930.log 14.1MB/天（占 28%）…`，右侧「巡检」可手动补一轮；启动 30s 后首轮、此后每 5 分钟一轮。
- **只列真的在长的**：安静时绝大多数文件是 0 增长，把 `0.0MB/天` 排进「增长最快」等于用噪声顶掉真正的增长源（真机实测踩到，已改为过滤 + 「本轮采样区间内无文件增长」）。
- **告警**（面板变橙 + WARNING 日志，同类只报一次、异常消失后再出现会重报）：① 单文件日增 > **1GB**（崩溃循环 / DEBUG 泄漏）；② 日志目录总量 > 保留上限 **512MB**（说明体积闸门因「文件正在写」回收不了，需排查增长源）。

### 🆕 功能：轮转兜底（不再依赖 ARQ 的每日 cron）
- **问题**：谁是日志的轮转责任人一直不完整 —— NSSM 服务日志有 `AppRotateBytes=10MB`、后端 `fastapi_*.log` 有自己的 handler，但 **nginx 的 access/error 日志靠 ARQ 每日 04:30 的 cron 轮转**（ARQ 一挂就没人转），而**管理器自己的 `server_manager_*.log` 从来没有轮转**。
- **改法**：管理器维护轮次里新增 `log_ops.rotate_oversized_logs`：把超过 **50MB** 的**现行** `*.log` 就地 copytruncate 成「一代 `.1` 副本 + 清零的现行文件」（Windows 不许 rename 被 nginx/NSSM 持有的文件，只能 copytruncate；持有方按追加语义会自然落在新文件尾）。
- **阈值与顺序都有约束**：阈值取 50MB = NSSM 自身上限的 5 倍，**天然不会与 NSSM 抢同一个文件**（有测试锁住这条不变量）；维护轮次先轮转（止血）再清理（腾空间），反过来会白占一个保留期。只轮转现行 `*.log`，不碰 `.1`/`.log.<时间戳>` 副本，否则会生出 `.1.1` 链。
- **频率**：轮转+清理从每 24h 改为**每 6h**——兜底的意义就是「外部任务靠不住时自己止血」，巡检负责发告警、这里负责止血。
- **刻意不复用 `utils.log_rotation`**：`utils/__init__.py` 会连带导入 `batch_upload_utils`，后者**硬要求 polars + openpyxl**，而 `server_manager.spec` 明确 exclude 了 openpyxl/sqlalchemy —— 管理器一旦 import utils，打包后的 exe 会启动期 `ImportError`。故自带一份等价实现并在注释里写明来龙去脉。

### 🔗 统一：后端与桌面壳共用同一套日志轮转/保留策略
- **问题**：同一条日志管线上曾有**三个**各自为政的策略 —— `prod_runner` 只管自己的 `.out.log`（50MB，`PROD_LOG_ROTATE_MB` 可调）、ARQ cron 只管 nginx 两文件（固定 **100MB**、且不做保留清理）、桌面壳管全部 `*.log`（50MB + 保留 14 天 / 512MB）。「多大该轮转」在一台机器上有三个答案，改一个必漏两个；nginx 的轮转责任还全押在 ARQ 每日 cron 上（ARQ 停摆就没人管）。
- **改法**：策略与实现统一到 `utils/log_rotation.py`，策略落 `config/log_policy.json`（默认 **50MB / 14 天 / 512MB**）。三方都 `load_log_policy()` 读同一份文件、都调 `rotate_oversized_logs` / `prune_log_files` —— `prod_runner` 每 60s 的维护轮次与 ARQ 的每日 cron 现在都做「轮转 + 保留清理」，行为完全一致；`PROD_LOG_ROTATE_MB` / `NGINX_LOG_ROTATE_BYTES` 两个独立阈值来源已删除。
- **为什么现在能共享了**：`utils/__init__.py` 改为**惰性导出**（PEP 562）—— 此前它 eager 导入 `batch_upload_utils`（硬要求 polars + openpyxl）与 `logger`（sqlalchemy），桌面壳（PyInstaller 明确 exclude 这些）一 `import utils` 就在启动期 `ImportError`，这正是「管理器只能自带一份实现」的根因。实测全仓没有 `from utils import <名字>` 的用法，故 `__getattr__` 惰性解析后旧契约不变。守卫测试：`tests/test_utils_lazy_import.py`（子进程校验不拉起重依赖 + 旧名字仍可取）。
- **运维入口**：`docs/runbooks/service-lifecycle.md` §5.6（谁在管、怎么改、怎么验证；含 handler `backupCount` 与共享清理的分层说明 —— 实际保留期以策略文件为准）
- **验证**：`fastapi_app/tests/test_log_policy_unification.py` 锁住三方共享（含 `PROD_LOG_ROTATE_MB`/`NGINX_LOG_ROTATE_BYTES` 不得复活）、`tests/test_log_policy.py` 覆盖缺失/损坏/坏值夹取/表单越界报错。

### 🆕 功能：日志策略界面可配并持久化
- 日志面板新增「设置」入口，可在界面上改**轮转阈值 / 保留天数 / 体积上限**，保存后写入共享的 `config/log_policy.json` —— 改完**立刻对后端生效**，无需重启任何服务。
- 边界取值：轮转 1–4096MB、保留 1–3650 天、上限 16–65536MB。**界面越界报错、不静默夹取**（界面不能替用户改写意图）；文件侧则夹取，给手改坏值兜底（如 `rotate_mb: 0` 会被夹到 1）。
- 桌面壳一律用项目目录拼策略路径：打包后 `__file__` 指向 PyInstaller 解包临时目录，`default_policy_path()` 会算出不存在的路径并静默回落默认值（表现：改了设置却像没生效）。

### 🏗️ 顺带：日志视图层抽出（`LogViewMixin`）
- 上述改动若堆在 `app.py` 会把该文件顶到 1676 行，`tests/test_gates_cover_repo_root.py` 的永久锁（app.py ≤ 1600 行，规模门禁阈值）判红。故按 hosting_view 的同一套切法把日志面板与日志运维整体抽到 `server_manager/log_view.py`，`app.py` 降到 **1520 行**（该锁由「已红」转绿）。
- **验证**：新增 `tests/test_server_manager_log_ops.py`（15 例：历史不回灌/增量实时/半行缓冲/两种轮转判据/超量不丢/ERROR 着色/接入幂等/状态文件不受清理/体积上限/被占用跳过）；server_manager 相关测试 74 例全绿；`quality_gate.py` 无新增违规（宽泛 except 9→5）；`mypy` 无错误。
- **打包**：版本号 `v5.33 → v5.34`（`constants._VERSION` + `server_manager.spec` 产物名），用 `python -m PyInstaller server_manager.spec` 产出 `ERP服务器管理器_v5.34.exe`（19.5MB，已核对 `log_ops`/`log_view` 确实入包），并放入 `D:\erp_system\dist\`（**v5.33 原样保留作回滚点**）。
- **真机冒烟（2026-09-30 20:36–20:43，生产五服务全 RUNNING 下运行该 exe）**：
  - `20:36:42` 启动 → `20:36:42.654` 即「已接入生产日志实时输出（erp-prod、erp-arq、erp-web）」；
  - `20:37:02` 「日志清理完成：无过期文件，保留 18 个」（定时首跑，20s 后）；`logs/log_health_state.json` 生成（巡检首轮采样）；
  - **实时性实测**：ARQ 于 `20:40:00` 写入 `erp-arq.log` 的 6 行 cron 输出，在管理器日志里的时间戳是 `20:40:00.813`；ARQ 于 `20:40:57` 写入的 health 行 → 管理器 `20:40:58.354`（≈1s，即轮询周期）；
  - `20:40:11` 巡检基线行：`合计 49.7MB / 18 个文件 · 增长最快：server_manager_20260930.log 1.2MB/天（占 0%）、后端(uvicorn).out.log 1.1MB/天（占 2%）、fastapi_20260930.log 0.9MB/天（占 28%）`，无告警（安静期不给假警报）。

## [2026-09-28] 移除「定制订单」与「国家」功能

### 🗑️ 订单类型收敛为单一常规订单
- **范围**：`/customer-order` 不再有订单类型与国家录入；`/stock` 不再有定制订单列、国家筛选与按国家校验库存；`/aux/countries` 国家管理接口整体删除。
- **数据层**：迁移 `pg_standalone_055` 删除 `order`/`order_item`/`stock_in`/`staging_order`/`staging_stock_out` 五张表的 `order_type`、`country` 列、定制订单专用部分索引 `idx_order_custom_type` 与国家主数据表 `country`。执行前实测**无任何 custom 数据**，不丢业务数据。
- **行为变化**：新建订单/备货一律常规；可出货量回到「客户+产品」维度；库存页「总订单 = 订单余量 + 备货量」；Excel 批量导入若仍带「国家」列则**静默忽略**。
- **实现**：后端 33 个文件（schema/service/endpoint/ORM/批量导入/序列化/湖北列表/purchase 读取路径）+ 前端 40 余个文件（customer-order、stock、共享类型与 API、purchase 面板「定制」标签），并删除 `Country` 模型、`stores/country.ts`、`api/country.ts`、`CountryDialog.vue`、`StockWarningDialog.vue`。
- **验证**：后端全量 pytest；前端 `vue-tsc` 0 错误 + vitest 655 通过；迁移 `upgrade` → `downgrade` → `upgrade` 演练通过。
- 设计与计划：`docs/superpowers/specs/2026-09-28-remove-custom-order-design.md`、`docs/superpowers/plans/2026-09-28-remove-custom-order.md`。
- **部署注意**：迁移生效后必须重启 `erp-prod` 服务——旧进程仍读写已删列，订单/出库路径会 500。

## [2026-09-28] 生产编排重构：erp-web 单一职责（拆 nginx 出 prod_runner）

### 🏗️ 五服务拓扑（消除监督器混管）
- **问题**：`prod_runner` 同时托管 nginx（无状态静态）与 uvicorn（有状态 API），生命周期不同却被绑在一个进程树里。历史事故：nginx spawn 方式不当阻塞监督器主循环 → NSSM 反复重启监督器 → nginx 周期性 kill/重建 → **全站连接每 ~35 秒被切断一次**。
- **改动**：新增 NSSM 服务 `erp-web` 直管 `nginx.exe`（AppExit=Restart，无依赖）；`prod_runner` 删除 `_FrontendNginx`/`_find_nginx`/vite preview 回退等约 260 行，瘦身为只守护 uvicorn；保留对 `:3000/nginx-health` 的**只读探针**（写 `frontend_ok` 字段，失败只报告绝不重启）。前后端启停解耦：重启 erp-prod 不再影响前端静态服务。
- **迁移**：`scripts/migrate_erp_web.ps1`（幂等，`-DryRun` 可预览命令序列；回滚步骤见脚本头注释，**必须含 `nssm set erp-web Start SERVICE_DISABLED` 防回滚后开机双 nginx**）。
- **GUI**：`server_manager.py` 七处服务元组扩为三元组（含 `_managed_service_pids` P0-4 闸门——dev 模式切换仍能抢到 :3000）；安装流注册 erp-web；前端徽章仿 ARQ `external` 范式改读服务状态 + 探针交叉验证。
- **nginx 日志轮转归属**：`_rotate_file_copytruncate` 下沉 `utils/log_rotation.py`；nginx access/error 日志轮转挂入 ARQ cron（每日 04:30，阈值 100MB；ARQ 停摆仅意味着暂不轮转，优雅降级）。
- **顺带**（同维护窗口生效）：nginx `worker_processes auto(12)→2`、`.env` `UVICORN_WORKERS 8→4`（6 物理核机器去过订阅）。
- **文档**：`docs/runbooks/service-lifecycle.md` 拓扑重写为五服务、新增 5.2b/5.2c 故障条目；删除被护栏拦死的死脚本 `restart_prod.ps1`。
- 设计与计划：`docs/superpowers/specs/2026-09-28-erp-web-single-responsibility-design.md`。

## [2026-09-18] 文件规模门禁阈值上调与单点化

### 🧱 `file_size_gate` 阈值 1200 → 1600，且不再三处硬编码
- **问题**：阈值原先写在 3 个地方（`pyproject.toml max_file_size`、`scripts/file_size_gate.py DEFAULT_THRESHOLD`、CI workflow 的 `--threshold 1200`），改一处必漏两处；而 1200 会让两个存量文件一旦被改动就阻断提交（`test_purchase_center.py` 1497 行、`recovery_test_service.py` 1353 行）。
- **改动**：`file_size_gate.py` 新增 `_threshold_from_pyproject()`，改为读取 `pyproject.toml [tool.code-quality] max_file_size`（与 `quality_gate.py` 同一约定，解析失败才回落内置默认值）；CI 步骤去掉 `--threshold 1200` 改为读配置。
- **定档依据**：受扫描的 777 个 `.py` 中仅上述 2 个超过 1200，故取 1600 留出余量，仍能拦住新增上帝类。
- **顺带修复**：`file_size_gate.py` 的 git 输出解码改为显式 `encoding="utf-8"`，并强制 stdout/stderr 为 UTF-8 —— 中文 Windows（cp936）下打印 `⚠` 会抛 `UnicodeEncodeError`，使门禁自身崩溃。

## [2026-08-22] 生产部署健壮性：服务依赖 + 日志轮转

### 🔗 NSSM 服务启动依赖（消除开机重启风暴）
- `server_manager.py` 安装 erp-prod / erp-arq 服务时自动扫描本机正在运行的 PostgreSQL/Redis 服务（名称含 postgres/redis/memurai 且 StartType=Automatic、Status=Running），写入 `DependOnService`——开机时数据库先就绪再拉起应用，避免后端健康检查失败触发监督器退避重启。只读副本（replica）与已停用旧实例（Automatic 但停止，如退役 Redis）自动排除，防止其启动失败连累主服务。本机实测探测到 `postgresql-x64-18 / erp-redis / erp-redis-broker`。
- 探测不到时打 WARNING 跳过（PG/Redis 可能在远端）；可用环境变量 `SERVICE_DEPENDS_ON=svc1,svc2` 显式指定。
- 顺带修复 `_run_capture` 在中文 Windows（OEM/GBK 代码页）+ PYTHONUTF8=1 环境下按 UTF-8 解码 sc/nssm 输出抛异常、stdout 丢失的问题（改按 OEM 解码 + replace）——此前含中文显示名的服务会被误判为"未安装"。
- **生效方式**：在 server_manager「生产托管」面板重新执行「安装服务」即可（已注册服务需重装才更新依赖）。

### 📜 生产日志轮转（防止磁盘占满）
- `prod_runner.py` 新增 copytruncate 轮转：子进程 `logs/<name>.out.log` 与 Nginx `access/error` 日志超过阈值（默认 50MB，`PROD_LOG_ROTATE_MB` 可调）时先复制为 `.1` 副本再原地截断，每 60 秒检查一次。
- Windows 下日志文件被子进程/nginx 以共享读写 + 追加方式占用无法 rename，copytruncate 是可行解；截断瞬间的少量行丢失对运维日志可接受。
- 此前仅 NSSM 自身的 `logs/erp-*.log` 有 10MB 轮转，子进程与 Nginx 日志无限增长。

## [2026-08-21] 代码质量修复（P1/P2/P3）

### 🧹 静态分析清零（ruff 全范围 All checks passed）
- **fastapi_app + scripts：114 → 0 项**（含 78 个 F401、20 个 import 排序等）。
- **tests + utils 存量：73 → 0 项**（N803 参数命名 ×10、RUF013 隐式 Optional ×30、RUF010/RUF012 等）。
- 兼容层保护：`purchase_plan_crud.py`、`stock_service.py` 等 re-export 文件加文件级 `# ruff: noqa: F401`，**未删任何兼容 import**（外部调用方零影响）。
- 修复 ruff 0.16 RUF013 unsafe-fix 误伤：`batch_upload_utils.py` 的 `callable` 内置名被改坏 → 修正为 `Callable | None`。
- 有意的 noqa（F403 star-import、S110 防御性降级、RUF012 只读常量）均保留并加注释说明。

### 🐛 存量 bug 修复（扫描中发现）
- **`utils/audit.py` 模块无法导入**：`from fastapi_app.core.database import SyncSession` 引用不存在的名称 → `database.py` 新增 `SyncSession()` 兼容工厂（lazy 初始化，带失败保护）。
- **`utils/number_generator.py` / `batch_import_handler.py` 参数命名**：`Order/StockIn/Product` 等大写参数重命名为 `order_model/stockin_model/product_model`（位置调用，调用方零影响）。
- **`pg_tune.py` 闭包捕获循环变量（B023）**：lambda 绑定默认参数 `v=value`。
- **`redis_cache.py` SQLAlchemy 布尔比较**：`== True` → `.is_(True)`。

### 🔒 安全复核（bandit 1.9.4 实跑）
- **0 个 MEDIUM/HIGH**（历史 bandit_report 的 27 个 MEDIUM B608 已全部消除），仅 2 个 LOW 噪音。

### 🧪 测试补强（前端 61 → 70 用例）
- 新增 `usePagedSearch.test.ts`（5 用例：防抖重置页码/连续输入/清空/卸载清理）。
- 新增 `useStockWarning.test.ts`（4 用例：库存充足/无记录/不足/接口异常 fail-closed）。
- 全量回归：后端 **834 passed**、前端 **70/70 passed**、`vue-tsc --noEmit` 零错误。

### 🛡️ 文件规模门禁（防新上帝类）
- 新增 `scripts/file_size_gate.py`：CI 中检查 git 变更文件行数（阈值 1200），存量超限文件不阻断。
- 已集成 `.github/workflows/ci-cd.yml` lint job。
- 当前超限存量：`tests/test_purchase_center.py`（1406 行）、`backup/orchestration/recovery_test_service.py`（1319 行）——建议后续拆分。

### 📊 类型检查扩展（mypy 13 → 20 文件）
- 纳入 `shared/shipment_calc.py`、`shared/stock_crud_service.py`、`shared/report_data_service.py` 及核心 shared_models；补全 8 处局部变量注解，`shipment_calc` 签名 `dict[int, float] → dict[int, int]`（与实际 SQL 聚合一致）。

### 📦 快照清理
- `ruff_issues.txt`、`ruff_endpoints.json`、`ruff_services.json`、`pytest_full.log`、`bandit_report.json` 均为过时快照，重命名为 `*.stale-20260821`。

### 🔄 P1 多 SKU（渐进式改造，部分完成）
- ✅ `order_crud.create_order` 现写入 `OrderItem` 明细（与批量创建路径对齐，消除"部分多 SKU"数据不一致）；单 SKU 行为等价，历史订单不受影响。
- ⏳ 其余 19 处 `TODO(multi-sku-order)`（库存扣减/报表/审批/编辑语义）为架构级改造：需业务 spec 确认语义（多 SKU 编辑改哪个 item、扣减粒度）+ 查询入口 selectinload 预加载联动，**未在本轮擅自动手**。

## [2026-08-21] PG 重启生效 + 索引清理 + 前端测试修复

### ⚡ PostgreSQL 调优生效（主从双库）
- 重启 `postgresql-x64-18`（主库）与 `postgresql-replica`（副本），**8 参数全部生效**（shared_buffers 3948MB / effective_cache_size 11844MB / maintenance_work_mem 512MB / wal_buffers 16MB / parallel 4 / statistics_target 200）。
- 修复 `scripts/pg_tune.py` 的 PGDATA 目录解析 bug（此前把 PGDATA 当文件判断，导致副本调优失效）；副本配置已同步并验证（in_recovery=True 流复制正常）。
- 主从配置文件均已备份（`postgresql.conf.bak-20260821_213655` 等）。

### 🔍 索引清理（备份+CONCURRENTLY+验证）
- **19 组重复索引全部删除**（保留各表的 `idx_*`/UNIQUE 约束），DDL 备份到 `docs/backups/index_cleanup_20260821_213825.sql`。
- **audit_log 9 个未使用索引全部删除**（60 天无扫描，仅剩主键），DDL 备份到 `docs/backups/audit_index_cleanup_20260821_213900.sql`。
- 全程 CONCURRENTLY 不锁表；删除前逐对对比列定义确认真重复；删除后复查保留索引完好。

### 🧪 前端测试修复（61/61 通过）
- **BeileOrderTab.export.test.ts（7 失败→8 通过）**：导出/打印按钮已从 BeileOrderTab 迁移到 **HubeiView 头部**（`bo-header-btn--export/print`），测试重写为挂载 HubeiView；修复 Pinia 缺失、HubeiSearchBar 内 PrimeVue AutoComplete jsdom 渲染失败（stub）、原生 checkbox 事件（setValue）。
- **PurchaseView.autorefresh.test.ts（2 失败→2 通过）**：`@tanstack/vue-query` mock 补全 `useQuery`（此前缺失导致 setup 崩溃）；增强 mock 支持 queryFn 挂载执行 + refetchInterval 响应式定时（watchEffect），模拟真实 auto-refresh。
- 全量回归：**61/61 通过**（此前 52/61），`vue-tsc --noEmit` 零错误。

## [2026-08-21] P2 扩展性优化 (PgBouncer / L1广播 / 索引审计)

### 🔌 PgBouncer 部署配置
- 新增 `config/pgbouncer/pgbouncer.windows.ini`（Windows 路径版，transaction 模式 + scram-sha-256）。
- 新增 `scripts/pgbouncer_gen_userlist.py`：自动生成 userlist.txt（明文/scram 或 md5 模式），替换占位符。
- 代码衔接已完备（`PGBOUNCER_ENABLED=true` 时应用侧连接池自动缩小，见 database.py）。

### 🔄 L1 缓存跨 worker 失效广播
- `.env.example` / `.env` 新增 `CACHE_L1_BROADCAST_ENABLED=false`（多 worker 生产建议开启）。
- **实测验证 PASS**：发布→监听→L1 清理闭环正确（执行计数 1→1→2 严格区分缓存命中/重算）。
- 注：单 worker/开发环境保持关闭（省一个 Redis 连接）。

### 🔍 索引审计 (scripts/index_audit.py)
- 新增只读审计脚本 `scripts/index_audit.py`（重复/未使用/膨胀/大小 4 类检查）。
- 报告见 `docs/index-audit-2026-08-21.md`：
  - **19 组重复索引**（建议删 `ix_*` 旧规范命名，保留 `idx_*`）
  - **20 个未使用索引**（audit_log 占 9 个、约 3.5MB 写入开销）
  - 无索引膨胀，无需 REINDEX

## [2026-08-21] PostgreSQL 调优 + 报表物化视图

### ⚡ PG 服务端调优 (scripts/pg_tune.py)
- 新增一键调优脚本 `scripts/pg_tune.py`（自动探测内存/CPU，`--check` 对比、`--apply` 备份写入）。
- 已应用到本机 PG 18.3（15.4GB RAM / 12 线程），8 参数写入 `D:\PostgreSQL\data\postgresql.conf`：
  - `shared_buffers 128MB → 3948MB`、`effective_cache_size → 11844MB`、`maintenance_work_mem 64MB → 512MB`、`wal_buffers 4MB → 16MB`、`max_parallel_workers_per_gather 2 → 4`、`default_statistics_target 100 → 200`
  - 原配置已备份: `postgresql.conf.bak-20260821_210748`
  - ⚠️ 需重启服务生效: `net stop postgresql-x64-18 && net start postgresql-x64-18`

### 📊 报表物化视图 (mv_product_aggregate)
- 新增迁移 `pg_standalone_017_product_aggregate_mv`：按产品维度聚合订单/入库/出库统计（order_count/order_quantity/stockin_*/stockout_* + 最近活动日期），与现有 3 个日统计 MV 互补。
- `maintenance_tasks.py` 重构：统一 `_refresh_materialized_views()`（每 MV 独立 session 并行刷新），新增产品 MV 不存在时优雅降级（不阻塞其他视图）。
- ARQ `refresh_dashboard_mv_task` 现刷新全部 4 个 MV（原 3 日统计 + 产品聚合）。
- 真实环境已验证：迁移执行成功、数据正确（9 个活跃产品）、burst worker 刷新任务返回 `success: True`。

## [2026-08-21] 前端产物体积优化 (Bundle Size)

### 📦 ECharts 按需打包 (Tree-shaking)
- `src/utils/echartsPreload.ts`: 由 `import('echarts/charts')` 动态整模块导入改为 **静态命名导入**（`echarts/core` + `echarts/charts` + `echarts/components` + `echarts/renderers` 具名导出），使 Rollup tree-shaking 生效。
- `src/views/production/composables/useProductionCharts.ts`: 复用 `ensureEcharts()` 统一注册，消除重复的动态全量导入。
- **结果**: `vendor-echarts` chunk 从 **1058KB → 547.6KB（-48%，减 510KB）**；gzip 后约 160KB。
- 已注册图表/组件: Line/Pie/Bar + Grid/Tooltip/Legend/Title/Dataset + CanvasRenderer，覆盖 dashboard 与生产页全部图表类型。

### 🎨 FontAwesome 规范化 (Icon Import)
- `src/icons.ts`: `import * as solidIcons`（namespace）改为**显式命名导入** + 直接引用，与 Rollup 静态分析语义对齐（产物已验证仅含 161 个已注册图标，未注册图标 0 引用）。
- `all.min.css` webfonts 保留（114 处 `fas fa-` class 用法依赖，删除会导致图标缺失）。

### 🧪 测试
- `vue-tsc --noEmit` 零错误；vitest 52/61 通过；**9 个失败为既有问题**（BeileOrderTab.export / PurchaseView.autorefresh，改动前后一致，与本优化无关）。

## [2026-08-21] 异步任务栈升级与清理

### ⚡ 依赖升级 (Dependency Upgrade)
- **arq 0.26.0 → 0.28.0**: 消除与 redis 版本范围的元数据冲突声明。
- **redis[hiredis] 7.4.1 → 5.3.1**: 匹配 arq 0.28 的 `redis<6` 约束，`pip install -r requirements/base.txt` 严格解析无冲突；hiredis parser 默认生效（`redis._parsers.hiredis`），性能不变。
- **删除 `fastapi_app/core/celery_app.py`**: Celery → ARQ 迁移兼容层已无引用，彻底移除。

### 🔧 异步任务端点重构 (Task API Refactor)
- `GET /api/v1/tasks/status/{task_id}`: 由 Celery `AsyncResult` 死代码改为 **ARQ Job 真实查询**（`Job.status()` / `Job.result_info()`），任务不存在返回 404，Redis 不可用返回 503。
- `GET /api/v1/tasks/download/{task_id}`: 同步改为 ARQ Job 结果查询，与提交端（import-orders / import-stockins / export-report 已用 ARQ）打通闭环。
- `fastapi_app/core/config.py`: 移除无消费方的 `CELERY_BROKER_URL` / `CELERY_RESULT_BACKEND` 配置项（ARQ 使用 `REDIS_BROKER_URL`）。
- 测试 `test_tasks.py` 重写为 ARQ 语义（NOT_FOUND→404、STARTED、SUCCESS、FAILURE、503 降级）。


## [2026-03-24] UI 优化: 产品列表页 (`/product/list`)

### 🎨 设计与排版 (Typography & Spacing)
- **增加留白与呼吸感**:
  - 引入 8-pt 栅格系统，统一内边距（如 `24px`、`32px`）与外边距。
  - 调整字体行高至 `1.5`，提升文本可读性。
- **字体层级优化**:
  - 主标题 (Page Title): `32px` -> `24px`，字重 `700` -> `400`。
  - 副标题 (Page Subtitle): `15px` -> `18px`，字重 `400`。
  - 正文与表单标签 (Body Text): `14px`，字重 `400`。

### 🖱️ 交互与触控 (Interaction & Touch Targets)
- **触控区域达标**:
  - 所有按钮 (`.btn`, `.btn-sm`, `.action-buttons .btn`) 最小尺寸调整为 `44x44 px`。
  - 输入框 (`.form-control`) 与下拉框 (`.form-select`) 最小高度设为 `44px`。
  - 分页控件 (`.page-link`) 最小尺寸调整为 `44x44 px`。
- **视觉降噪与元素分组**:
  - 弱化次要按钮的边框（`.btn-outline-secondary`），主操作按钮 (`添加产品`) 增加视觉高亮。
  - 搜索与排序控件组合进统一的 `toolbar-wrapper` 中。

### ♿ 可访问性 (Accessibility)
- **对比度达标 (>= 4.5:1)**:
  - 更新次要文本颜色 `#8B7B7B` 为 `#595959`。
  - 更新绿色图标 `#66BB6A` 为 `--plush-green-text` (`#2e7d32`)。
  - 更新蓝色文本颜色为 `--plush-blue-text` (`#02669e`)。
- **键盘可达性**:
  - 为图片预览、无图占位符、拖拽上传区域等交互元素增加 `tabindex="0"` 和 `:focus-visible` 焦点样式（2px 轮廓）。
  - 为分页控件、搜索框、排序下拉框补充 `aria-label` 等语义化标签。

### ⚡ 性能与响应式 (Performance & Responsive)
- **无布局偏移 (CLS < 0.1)**:
  - 避免图片加载导致的重排，占位符与图片尺寸严格固定 (`80x80 px`)。
  - 上传区域和列表区域指定了安全的最小高度。
- **多端适配**:
  - 完善了 `1920x1080`、`1366x768` (桌面端) 及 `375x667` (移动端) 的响应式断点，针对移动端缩小了触控元素的间距，但仍保证 `44x44 px` 的可点击区域。