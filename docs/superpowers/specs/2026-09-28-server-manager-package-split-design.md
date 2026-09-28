# 设计:server_manager 完整包化 + 规模门禁收严

- 日期:2026-09-28
- 状态:待用户审阅
- 前置:A 止血(`f361ee7a`)与 B 去重(`e60c82e5`)已完成;当前 `server_manager.py` 3082 行、`ServerManagerApp` 单类 2266 行 / 112 方法
- 用户决策:**完整包化**(`server_manager/` 目录,多模块 + UI 层)+ **先拆后收严**

## 1. 目标与非目标

**目标**:
1. `server_manager.py`(3082 行,阈值 1600 的 ~2 倍)重组为 `server_manager/` 包,每个模块单一职责、可独立理解;
2. 规模门禁(c1)与函数长度门禁(c2)把仓库根纳入扫描,CI 的 `file_size_gate.py` 修复空转(改为 `--all`)。

**非目标**:不改任何运行时行为(B 已完成行为收敛);不动 UI 视觉;不做 D(消费侧去二次推导,另立项);不引入 `pywin32`/结构化 SCM API(D 的范畴)。

## 2. 目标结构

```
server_manager/                  ← 新包(替代单文件)
├── __init__.py                  # 导出 main;兼容 `python server_manager.py` 旧入口
├── __main__.py                  # 使 `python -m server_manager` 可用
├── windows_ops.py               # 进程/端口/服务层(纯函数,无 Tk 依赖)
│     _taskkill/_taskkill_many/_is_prod_runner_cmdline
│     find_port_pids/kill_port_sync/collect_process_tree/kill_process_tree
│     find_project_residual_pids/find_loose_prod_runner_pids
├── service_ops.py               # NSSM/sc 服务操作(类 WindowsServiceOps,无 Tk 依赖)
│     _find_nssm/_run_capture/_decode_output/_svc_state/_svc_pid/_svc_installed
│     _wait_service/_wait_service_stopped/_wait_service_running/_start_one_service
│     _stop_managed_services/_managed_service_pids/_service_cmd_sync
│     _nssm_install/_apply_depends/_set_depends_registry/_uninstall_services_flow
│     _ensure_production_stopped
├── redis_ops.py                 # Redis 探活/启停(类 RedisOps)
│     _redis_ping/_is_redis_running/_is_broker_running/_redis_service_state
│     _start_redis_via_service/_start_redis/_start_redis_process
│     _ensure_redis_broker/_stop_redis/_get_env_value
├── dev_mode.py                  # 开发模式(类 DevModeOps)
│     _start_dual_server/_start_dual_thread/_start_dual_worker
│     _stop_dual_mode_async/_stop_dual_flow/_restart_dual*
│     _on_dual_*/_start_frontend/_ensure_development_stopped
│     _terminate_dev_processes/_read_stdout/_read_frontend_stdout
├── widgets.py                   # RoundedButton(203 行)/StatusBadge(126 行)/颜色助手
├── action_gate.py               # _ActionCancelled + ActionGate(115 行)
├── constants.py                 # _SVC_* 常量/_PORTS/_NSSM_CANDIDATES/_HTTP_DIRECT
├── app.py                       # ServerManagerApp(拆掉操作层后剩 ~1200 行:UI 构建、
│                                 #   消息泵、托管徽章渲染、生命周期)
└── legacy_entry.py              # 保留 `python server_manager.py` 兼容(见 §4)
```

行数预估(实测分组):windows_ops ~157 + service_ops ~437 + redis_ops ~182 + dev_mode ~258 = **~1034 行**从 app 挪出;app.py ≈ 3082 − 1034 − widgets/gate/constants ≈ **~1200 行**(低于 1600 阈值)。

## 3. 关键设计决策

### 3.1 依赖方向(强制,单向)

```
app.py ──▶ service_ops ──▶ windows_ops
   │            │
   ├─▶ redis_ops ──▶ windows_ops(端口杀)
   ├─▶ dev_mode ──▶ service_ops(切生产前停服务)
   │         └────▶ windows_ops
   └─▶ widgets / action_gate / constants
```

- **操作层模块不得 import app、不得 import Tk**。它们从 `constants` 拿服务名/端口,通过**构造注入**拿回调(`msg_queue.put`/`gate`)——现有代码本来就全走这两个回调,不改变协议;
- `ServerManagerApp` 用**委托**而非继承:`self.ops = WindowsServiceOps(msg_queue=self._msg_queue, gate=self._gate, ...)`。为把改动面控住,app 内保留**同名瘦方法**转发(如 `def _svc_state(self, name): return self.ops.svc_state(name)`)——既有 112 个调用点不用改,静态断言测试(`test_server_manager_*.py` 共 34 条)继续对**转发后行为**生效;
- 瘦转发方法在 §5 的步骤里逐步消除(每消一批跑一次全量 GUI 断言),但不属于本次的完成判据——**保留转发也可交付**。

### 3.2 单实例锁与入口兼容(最大风险点)

`_ensure_single_instance`(L92)用 **Windows 命名互斥体**(`ERP_Server_Manager_{user_hash}_v1`,
经 `CreateMutexW` + `GetLastError()==183` 判重)——与 `__file__` 路径无关,**包化不影响锁语义**
(spec 初稿误写为文件锁,已更正)。真正要守住的是 `_get_project_dir`(L123):冻结分支按 `sys.executable` 探测
(`erp_project_path.txt` / `d:\erp_system` 兜底,与包结构无关,**不动**);
非冻结分支是 `Path(__file__).resolve().parent`——包化后 `__file__` 从仓库根
变为 `server_manager/`,需改为 `.parent.parent`(或直接落到根壳 `server_manager.py`
里,让包内不再自带探测)。这是步骤 1 必须实测的点。
- 兼容入口:仓库根保留一个 **~15 行的 `server_manager.py` 薄壳**,内容为
  `from server_manager.app import main; main()`——这样「双击旧快捷方式 /
  `python server_manager.py` / PyInstaller spec 的 `server_manager.spec` 入口」都不破。
- **PyInstaller 是硬约束**:spec 的入口必须继续可用;**重建出的 EXE 必须在无 Python
  解释器的双击场景下工作**(冻结模式下项目根探测逻辑保留原样,仅上溯层数适配)。

### 3.3 静态断言测试的迁移

`tests/test_server_manager_*.py` 共 34 条断言,全部 `read_text` 一个单文件路径。策略:
- 各操作模块**新增对应断言文件**(如 `tests/test_sm_service_ops.py` 断言 service_ops 的关键机制),原文件**逐步重定向**到新模块路径;
- 迁移判据:每迁一批,原 34 条断言**总数不减**(允许等价改写,不允许静默丢失)。

## 4. 迁移与验证

**分 6 个可回滚的小步,每步独立提交、全量 GUI 断言 + 导入冒烟通过:**

1. 建 `server_manager/` 包骨架(constants/action_gate/widgets 先入,根壳 `server_manager.py` 改为转发)——**此步后 EXE 必须重建并实测启动**,因为入口变了;
2. windows_ops(纯函数,无状态,最安全)入包;
3. service_ops 入包(app 转发);
4. redis_ops 入包;
5. dev_mode 入包;
6. c1/c2 门禁收严:`file_size_gate.py` 的 `SCAN_DIRS` 加入仓库根(或 CI 改 `--all`),`check_function_length.py` 同步;跑门禁,全绿提交。

**每步验证清单**(缺一不可):
- `python -c "import server_manager"` 冒烟;
- 34 条 GUI 断言 + A/B 回归锁(stop_scope/dedup/erp_web/backup_badge/v533_stop)全绿;
- headless tkinter 桩导入 app 成功;
- 步骤 1 与完成后:**重建 EXE + marshal 取证**(关键符号在新入口脚本字节码中出现);
- **用户实测**:双击 EXE 启动、五服务卡片正常、「启动/停止/重启」一轮、「紧急停止」一轮。

**回滚**:任一步失败 `git revert` 该步提交;步骤 1 的回滚额外要求把根壳恢复为完整单文件(即回退到 B 完成态 `e60c82e5`)。

## 5. 门禁收严细节(c 步)

1. `scripts/file_size_gate.py`:`SCAN_DIRS = ("fastapi_app","tests","utils","scripts", ".")` 不行(`.` 会递归进自身),改为显式 `(".", )` 顶层文件模式——具体:保留 SCAN_DIRS 不变,**新增顶层根文件扫描**(`PROJECT_ROOT.glob("*.py")`);
2. CI(`ci-cd.yml` L164-166)那步改为 `python scripts/file_size_gate.py --all --fail`(`--all` 模式同时纳入根文件);
3. `scripts/check_function_length.py` 的 `DEFAULT_SCAN_DIRS` 同样纳入仓库根;
4. 收严后跑全仓:预期**零新红**(拆分后 app.py ~1200 行、其余模块全部 <1600;`_apply_hosting_data` 153 行仍是超长函数——**本次只拆文件,不拆函数**,153<1600 不拦,函数级收严留给 D)。

## 6. 风险与已知取舍

| 风险 | 缓解 |
|---|---|
| PyInstaller 打包路径/单实例锁在冻结模式下断裂 | 步骤 1 单独提交 + EXE 实测为硬门;锁文件路径不进包 |
| 34 条静态断言迁移丢失 | 断言总数不减判据 + 每步全跑 |
| 另一会话并行工作在同一工作树 | 每步小提交;操作前 `git status` 检查;发现外来改动即停手询问 |
| 转发层与 D 的二次重构叠加 | D 明确为独立立项;本次转发层允许保留 |
