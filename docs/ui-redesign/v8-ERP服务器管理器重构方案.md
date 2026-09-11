# ERP 服务器管理器 v8 重构方案

> 版本：v8.0-draft-1　|　日期：2026-08-31　|　状态：**待评审**
> 基线代码：`server_manager.py` v6.0.0（4854 行）
> 前置输入：`v7-pywebview-UI设计方案.md`、`同类开源项目调研与落地方案.md`、`UI重构V3设计方案.md`
> 配套效果图：`ui_prototype_v8.html`（高保真交互原型，可直接双击运行）

---

## 0. 执行摘要（结论先行）

| 项 | 结论 |
|---|---|
| **是否需要完全重构** | 需要。但**重构对象是架构与 UI 层，不是业务能力**。现有业务逻辑（进程树管理、NSSM 托管、端口清理、Redis 探测、依赖注入服务顺序）是本项目最有价值的资产，经过实机验证，必须**逐行迁移而非重写**。 |
| **核心病灶** | 单一上帝类 `ServerManagerApp`（1669 行 / 96 方法）把 UI 渲染、进程编排、服务托管、日志管道、告警判定全部耦合，**没有任何一层可以脱离 Tkinter 单独测试**。 |
| **技术路线** | 延续 v7 已定裁决：**pywebview 混合架构**。UI 层 HTML/CSS/JS（Edge WebView2），业务层 Python 保留并分层重写为 4 层单向依赖。 |
| **架构目标** | Domain（纯逻辑，零 I/O）← Application（编排/事务）← Adapter（进程/服务/文件/网络）← Presentation（WebView + Bridge）。UI 可替换、Domain 可单测。 |
| **能力扩展** | 新增 3 项从大厂实践引入的能力：**症状化告警引擎**（SRE 黄金四指标 + 分组抑制静默）、**RBAC 三级权限 + 高危操作审批**（堡垒机 4A 裁剪版）、**不可篡改操作审计流水**（Romaster 模式裁剪版）。 |
| **工作量估算** | 6 个阶段，约 18~24 个工作日。P1（骨架 + Domain 迁移）为关键路径。 |
| **回退保证** | v6.0.0 EXE 与源码全程保留为回退基线，v8 与 v6 可并存安装（配置文件按 schema 版本号隔离）。 |

**一句话方案**：把 4854 行单文件拆成「可测试的业务内核 + 可替换的 Web 界面」，并在此之上补齐运维平台该有的告警工程、权限分级与审计留痕。

---

## 1. 现状审计

### 1.1 代码资产盘点

| 文件 | 行数 | 职责 | 健康度 |
|---|---:|---|---|
| `server_manager.py` | 4854 | GUI 主体：Design Token + 组件库 + 6 页面 + 上帝类 + 告警引擎 + 采样器 | 🔴 高危 |
| `server_manager_console.py` | 779 | 控制台版（CMD 风格） | 🔴 **导入即崩溃，死代码** |
| `one_click_action.py` | 328 | 一键操作组件（锁 + 控制器 + 按钮组） | 🟢 良好（唯一成功拆分） |
| `start.py` | 139 | 简易启动入口 | 🟡 与主程序职责重叠 |
| `server_manager.spec` | — | PyInstaller 打包配置 | 🟢 良好（excludes 已排除重型依赖） |
| `server_manager_config.json` | — | 配置持久化（9 个字段） | 🟡 无权限/告警/备份配置 |
| `build_server_manager.bat` | — | 一键打包 | 🟢 良好 |

### 1.2 现状架构拓扑

```
                    ┌──────────────────────────────────────┐
                    │  server_manager.py  （单文件 4854 行）│
                    │                                      │
  ┌── 全局层 ───────┤  _PORTS  _APP_CONFIG  _mutex_handle  │
  │  25 个模块级     │  _PROJECT_DIR  _PYTHON_EXE  ...      │
  │  全局变量        └──────────────┬───────────────────────┘
  │                                │  ← 跨文件靠 import 全局变量共享
  │  ┌─────────────────────────────┴─────────────────────────────┐
  │  │              ServerManagerApp（1669 行 / 96 方法）          │
  │  │  ┌──────────┬──────────┬──────────┬──────────┬──────────┐ │
  │  │  │ UI 装配  │ 一键操作 │ 日志管道 │ 进程管理 │ NSSM托管 │ │
  │  │  │ 6 方法   │ 7 方法   │ 9 方法   │ 5 方法   │ 15 方法  │ │
  │  │  └──────────┴──────────┴──────────┴──────────┴──────────┘ │
  │  │  ┌──────────┬──────────┬──────────┬──────────┐            │
  │  │  │ 环境检查 │ 开发模式 │ 生产模式 │ 托盘退出 │            │
  │  │  │ 6 方法   │ 12 方法  │ 15 方法  │ 5 方法   │            │
  │  │  └──────────┴──────────┴──────────┴──────────┘            │
  │  └────────────────────────────────────────────────────────────┘
  │       │                    │                    │
  │  ┌────┴─────┐      ┌───────┴──────┐     ┌───────┴───────┐
  └──┤ 组件库    │      │ AlertEngine  │     │MetricsSampler │
     │ 14 个类   │      │ 60s 冷却去重 │     │ psutil 2s 采样│
     │ tk. ×478  │      └──────────────┘     └───────────────┘
     └───────────┘
           ▲
           │  ← 反向依赖 hack：函数体内延迟 import 规避循环
     ┌─────┴──────────────┐
     │ one_click_action.py │
     └────────────────────┘
```

**关键观察**：依赖箭头存在**双向环**（`one_click_action` → `server_manager` → `one_click_action`），靠函数内延迟导入硬绕。这是"没有独立业务层"的直接后果。

### 1.3 核心模块清单

| # | 模块 | 现状位置 | 实现要点 |
|---|---|---|---|
| M1 | 设计令牌与主题 | `DesignTokens`(L378) | 亮/暗双色板 + 8pt 栅格；主题切换需**销毁全部子控件重建**（`_rebuild_ui` L3255） |
| M2 | 组件库 | L585~L1466（14 类） | `RoundedButton`(222行) 用 Canvas 手绘圆角；`SparkLine`/`TrendChart` 手绘折线 |
| M3 | 布局框架 | `SideNav`(208px) `TopBar`(52px) `StatusBar`(30px) `PageRouter` | 三段式，与 v7 设计稿一致 |
| M4 | 页面 | `OverviewPage` `ServicesPage` `LogsPage` `ConfigPage` `DeployPage` `AlertsPage` | 6 页面，每页 141~287 行 |
| M5 | 开发模式编排 | `start_dual_dev` 等 12 方法 | 清端口 → 起 Redis → 起 uvicorn(--reload) → 健康检查轮询 30×1s → 起 vite |
| M6 | 生产模式托管 | `_nssm_install` 等 15 方法 | NSSM 注册 `erp-prod`/`erp-arq`；`_detect_service_deps` 扫 PG/Redis 写 `DependOnService` |
| M7 | 进程管理 | `_taskkill` `_kill_port_sync` `_collect_process_tree` | argv[0] 字面量 + `executable=` 传参（Mimosa 合规）；OEM 代码页解码 |
| M8 | 日志管道 | `setup_logging` 等 9 方法 | 缓冲 + 批量 flush + 行数上限裁剪（2000/1600） |
| M9 | 告警引擎 | `AlertEngine`(L3012) | 60s 冷却、未确认合并、落盘上限 100 条 |
| M10 | 指标采样 | `MetricsSampler`(L3077) | psutil 2s 采样 CPU/内存/磁盘/网络/进程 Top5，缺失时优雅降级 |
| M11 | 一键操作 | `one_click_action.py` | `ActionLock` 幂等 + 跨模式互斥；`ModeActionSpec` 声明式配置 |
| M12 | 系统集成 | `_apply_dark_titlebar` `_init_tray` `_ensure_single_instance` | DPI 感知、暗色标题栏、pystray 托盘、互斥体单实例 |

### 1.4 数据流

**唯一主干：消息队列驱动的单向数据流**（这是现有代码最好的设计，必须保留）

```
后台工作线程（18 个 threading.Thread）
   │  put(('log'|'metric'|'status'|'toast'|..., payload))
   ▼
queue.Queue（线程安全边界）
   │
   ▼  root.after(200, _poll_queue) 主线程轮询，单批最多 30 条
_poll_queue  ──分派──▶ log_message / _handle_metric / toast.show / ...
   │                          │
   │                          ▼
   │                    Tk 控件渲染（主线程独占）
   ▼
after(200ms) 自我重排 —— 单条消息异常被 pass 吞掉以保护调度链
```

12 种消息类型：`log`、`log_batch`、`started`、`dual_started`、`dual_failed`、`ui_update`、`status`、`startup_progress`、`hosting_refresh`、`hosting_apply`、`metric`、`toast`。

**副数据流**：
- 配置：`server_manager_config.json` ⇄ `_APP_CONFIG`（全局 dict，无 schema 校验）
- 告警：`AlertEngine` → `logs/server_manager_alerts.json`（上限 100）
- 生产状态：`prod_runner.json`（NSSM 运行态快照）
- 服务真值：`sc query` / `nssm status` 实时探测（OEM 解码）

### 1.5 接口设计

| 接口族 | 方法 | 契约特征 |
|---|---|---|
| 进程管理 | `_taskkill` `_taskkill_many` `_kill_port_process` `_find_port_pids` `_collect_process_tree` `_kill_process_tree` | 同步阻塞；返回 bool 或 pid 列表；**无异常抛出，失败静默** |
| 服务托管 | `_svc_state` `_svc_pid` `_detect_service_deps` `_wait_service_stopped/_running` `_nssm_install` `_service_cmd_sync` | 同步 + 轮询等待；状态字符串来自 `sc` 解析 |
| 模式互斥 | `_ensure_production_stopped` `_ensure_development_stopped` | 前置守卫，跨模式互斥的核心 |
| 一键操作 | `ActionLock.acquire/release` `OneClickActionController._dispatch/_finish` | **唯一有正式契约的接口**：`ModeActionSpec` frozen dataclass 声明式注入 |
| UI 更新 | `_msg_queue.put((type, payload))` | 事实上的内部消息总线，但**无类型定义、无 schema、字段靠约定** |

**评价**：接口存在但未被抽象——全部是私有方法（`_` 前缀），无 Protocol/ABC 定义，无法 mock，无法替换实现。

### 1.6 优点（必须保留的资产）

1. ✅ **消息队列线程模型正确**：严格遵守 Tk 主线程独占渲染，无跨线程改控件；单条消息异常隔离，调度链不断。
2. ✅ **subprocess 安全约定严谨**：argv[0] 恒为字符串字面量，运行时路径经 `executable=` 命名参数传入，全程无 shell。这是罕见的正确做法。
3. ✅ **Windows 平台细节到位**：OEM 代码页解码 `sc`/`nssm` 输出、DPI 感知、暗色标题栏、Reduced Motion、互斥体单实例、pystray 托盘。
4. ✅ **服务依赖自动探测**：`_detect_service_deps` 扫描 PostgreSQL/Redis/Memurai 写入 `DependOnService`，避免开机重启风暴——这是踩过坑才有的设计。
5. ✅ **跨模式互斥完备**：开发/生产双模式的互斥守卫 + 幂等锁，防止双起冲突。
6. ✅ **端口不硬编码**：全部从配置读取（API 5002 / WEB 3000 / Redis 6379），`_Ports` 单例支持热更新。
7. ✅ **一键操作组件已达标**：`one_click_action.py` 的四层单向依赖是本项目应推广的架构范式。
8. ✅ **打包配置干净**：`excludes` 排除 fastapi/uvicorn/pandas/numpy 等重型依赖，EXE 体积可控。
9. ✅ **Design Token 已体系化**：亮暗双主题、8pt 栅格，与 Ant Design / Arco / TDesign 对齐，可 1:1 迁移到 CSS 变量。
10. ✅ **优雅降级意识**：psutil 缺失、pystray 缺失、nssm 缺失均有降级分支，不会白屏崩溃。

### 1.7 缺点（量化证据）

| # | 问题 | 量化证据 | 影响 |
|---|---|---|---|
| D1 | **上帝类** | `ServerManagerApp` 1669 行 / **96 方法**，覆盖 8 个不相关职责域 | 任何改动都要读 1669 行上下文；无法并行开发 |
| D2 | **UI 与业务不可分离** | `tk.` 引用 **478 次**散布全文件；业务方法直接 `self.log_message()` 写 UI | **业务逻辑 0% 可单测**；换 UI 等于重写业务 |
| D3 | **全局状态** | 模块级全局变量 **25 个**（`_PORTS` `_APP_CONFIG` `_mutex_handle` ...） | 跨文件靠 import 全局变量共享，隐式耦合，无法并发多实例 |
| D4 | **循环依赖** | `one_click_action.py` L317-328 函数体内 `from server_manager import RoundedButton, TOKENS` | 依赖环，靠延迟导入硬绕，重构极易连环崩 |
| D5 | **异常被系统性吞掉** | `except Exception` **67 次** + `contextlib.suppress` **54 次** + 裸 `pass` **23 处** = **90+ 处静默失败** | 故障不可观测：操作"看起来成功"但实际失败，无痕迹 |
| D6 | **死代码** | `server_manager_console.py` 从主文件导入 `_API_PORT`/`_WEB_PORT`/`_REDIS_PORT` 三个**不存在的符号**（实际为 `_DEFAULT_*`），导入即 `ImportError` | 779 行文件完全不可运行且无人发现，说明**无 CI、无 import 检查** |
| D7 | **主题切换全量重建** | `_rebuild_ui` 销毁 root 全部子控件后重建，靠保存 `_log_index`/`_last_hosting` 恢复 | 状态易丢、闪屏、逻辑脆弱 |
| D8 | **视觉能力触顶** | `RoundedButton` 222 行 Canvas 手绘圆角；折线图手绘 | Tkinter 无法达到 AntD 级质感，投入产出比持续恶化 |
| D9 | **硬编码路径** | 3 处硬编码 `C:\` 绝对路径 | 换机/换盘符即失效 |
| D10 | **无消息 schema** | 12 种消息类型的 payload 字段全靠约定，无 dataclass/TypedDict | 字段拼写错误在运行时才暴露（且被 D5 吞掉） |
| D11 | **无权限概念** | 配置文件 9 个字段，**零**用户/角色/权限字段 | 任何能打开 EXE 的人都能卸载生产服务、kill 进程 |
| D12 | **无操作审计** | 仅有运行日志，无「谁在何时对哪个对象做了什么、结果如何」的结构化审计流水 | 事故无法追溯、不满足合规留痕 |
| D13 | **告警是"原因告警"** | `AlertEngine` 基于 CPU/内存阈值触发 | 违反 SRE 原则（应告警症状：错误率/延迟），噪声高、可行动性低 |
| D14 | **无 runbook 绑定** | 告警只有文本描述 | 值守人员收到告警不知道该做什么 |
| D15 | **健康检查硬编码** | `_start_dual_thread` 内 `30 × 1s` 轮询 `/api/health` 写死 | 慢启动环境误判失败；不可配置 |
| D16 | **配置无校验** | JSON 直接 `json.load` 进全局 dict | 手改坏配置 → 启动崩溃或行为异常 |

---

## 2. 大厂最佳实践研究与映射

### 2.1 阿里云 · Apsara Uni-manager 运维控制台

| 实践 | 要点 |
|---|---|
| **三层运维视图** | 基础设施层 / 云服务层 / 业务层分离，每层有独立健康视图与下钻路径 |
| **CMDB 汇聚** | 所有资源、配置、关系统一进配置管理库，运维动作全部基于 CMDB 对象 |
| **期望态导向** | 声明目标状态，平台负责收敛（而非命令式一步步操作） |
| **多级权限模型** | 组织 → 用户组 → 用户 → 角色 → 角色单元（资源集 + 操作集 + 授权选项） |
| **分权分域** | Region/环境级隔离，运维人员只能看到并操作被授权的域 |
| **ITIL/ITSM 对齐** | 变更、事件、问题、配置四大流程标准化 |

**→ 本项目裁剪**：
- 采纳「三层视图」→ 总览页分为 **基础设施（Redis/PostgreSQL/端口/磁盘）/ 应用服务（API/ARQ/Web）/ 业务健康（接口错误率/任务积压）** 三段。
- 采纳「期望态」→ 服务管理页由「点按钮执行命令」改为「**声明期望模式（开发/生产/停机），平台自动收敛**」，互斥逻辑内聚到 Domain 层状态机。
- 采纳「角色单元」→ 简化为 `Role = {资源域} × {操作集}`，三个预置角色。
- 不采纳 CMDB 全套（单机场景过重），改为**轻量资源清单 + 依赖拓扑图**。

### 2.2 腾讯 · 蓝鲸智云

| 实践 | 要点 |
|---|---|
| **原子平台 + 场景 SaaS 分层** | 管控平台 / 配置平台 CMDB / 作业平台 Job / 节点管理 为原子能力；上层场景 SaaS 组合调用 |
| **三类资源抽象** | 主机 / 进程 / 通用对象，统一原子操作层 |
| **标准运维 SOPS** | 可视化流程编排，把「多步运维动作」沉淀为可复用、可审批的流程模板 |
| **权限中心** | 用户组授权 + 实例级/属性级授权 + 分级管理员 |
| **监控告警套餐** | 主机进程监控、服务拨测、**杜绝告警风暴**、日志关键字告警 + 汇聚告警 |
| **故障自愈** | 告警触发预定义自愈流程，闭环处理 |

**→ 本项目裁剪**：
- **强采纳「原子能力 → 场景层」分层**：这正是 v8 的 Application/Domain 分界。原子能力 = `ProcessPort`/`ServicePort`/`HealthPort`；场景 = `StartDevModeUseCase`/`SwitchToProdUseCase`。
- **采纳「流程编排」**：把开发模式启动的 5 个步骤（清端口→起 Redis→起 API→健康检查→起 Web）显式建模为 **Pipeline + Step**，每步有状态、耗时、可重试、可中断，UI 上呈现为 Stepper。这直接解决 D15（步骤写死在一个 120 行线程函数里）。
- **采纳「日志关键字告警 + 汇聚」**：日志中心支持配置关键字规则 → 命中即产告警，同类合并。
- **采纳「杜绝告警风暴」**：分组 + 抑制 + 静默三件套（见 2.4）。
- 自愈能力**降级为半自动**：提供「一键执行推荐修复」按钮，不做全自动（单机运维场景全自动风险 > 收益）。

### 2.3 字节跳动 · Argos/Argus + Romaster

| 实践 | 要点 |
|---|---|
| **统一可观测** | Metrics / Traces / Logs / Events 四类数据统一收拢到一个平台、一个控制台、一次 SSO |
| **数据标准化** | Measurement 模型 + 全面元数据，保证跨源可关联 |
| **AI 排障** | 告警即触发全自动分析；智能聚合同根因告警；影响面评估；准确率 ~70%，遵循「**有用 > 准确**」 |
| **智能降噪** | TACP 异常检测，告警量降低 50%+ |
| **主动管控底座（Romaster）** | 权限 + 工单 + **不可篡改审计轨迹**；事前管控 + 事后合规留痕 |

**→ 本项目裁剪**：
- **采纳「统一可观测」**：把现在分散的「日志窗口 / 指标条 / 告警页」统一到**同一时间轴**——告警可一键跳转到该时刻的日志与指标（时间关联下钻）。
- **采纳「同根因聚合」的轻量版**：不做 AI，做**规则聚合**——同一服务、同一时间窗（默认 5min）、同一告警族的多条告警合并为一个「事件」，展示为可展开的聚合卡片。
- **强采纳 Romaster 的「不可篡改审计轨迹」**：v8 新增 `audit.jsonl` **append-only** 审计流水，每条含 `ts / actor / role / action / target / params_digest / result / duration_ms / trace_id`，配 hash 链（每条记录前一条的 sha256）防篡改。
- 不采纳全量 Traces（单机 ERP 无微服务链路），但保留 `trace_id` 字段串联「一次一键操作 → N 个子步骤 → M 条日志 → K 条告警」。

### 2.4 Google SRE · 告警工程

| 原则 | 要点 |
|---|---|
| **告警症状而非原因** | 该告 `API 错误率 > 5%`，而不是 `CPU > 80%` |
| **黄金四指标** | 延迟 Latency / 流量 Traffic / 错误 Errors / 饱和度 Saturation |
| **错误预算燃烧率** | 多窗口多重告警：14.4x 快烧（1h）触发 page，6x 慢烧（6h）触发 ticket |
| **分级** | P1 立即 page ~ P4 仅记录 |
| **runbook 强制绑定** | 每条告警规则必须挂处置手册链接 |
| **分组 / 抑制 / 静默** | `group_by` 聚合、`inhibition` 上游故障抑制下游、`silence` 计划维护静默 |
| **可行动性** | 收到告警若无需人工动作，则该告警不该存在 |
| **on-call 负载** | 每班 ≤ 2 次 page |

**→ 本项目裁剪**（这是 v8 告警模块的完整设计依据）：

| SRE 原则 | v8 落地 |
|---|---|
| 症状告警 | 一级告警只保留 4 条：`API 健康检查失败`、`API 5xx 率 > 5%`（5min 窗）、`ARQ 任务队列积压 > N`、`服务非期望态`（期望 running 实际 stopped）。CPU/内存/磁盘降为 P3「饱和度预警」 |
| 黄金四指标 | 总览页顶部固定四卡：**延迟 P95 / 请求量 QPS / 错误率 / 饱和度（CPU·内存·磁盘取最大）** |
| 错误预算 | 单机场景简化为「**24h 可用性预算**」：健康检查失败分钟数 / 1440，快烧（15min 内失败 > 3min）→ P1；慢烧（6h 内失败 > 30min）→ P2 |
| 分级 | P1 弹窗 + 托盘气泡 + 声音；P2 托盘气泡；P3 仅角标；P4 仅审计流水 |
| runbook | 每条规则在配置中带 `runbook` 字段，告警卡片直接渲染「处置建议 + 一键执行修复」 |
| 分组 | 按 `service + rule_family` 分组，5min 窗合并 |
| 抑制 | `PostgreSQL 不可用` 抑制 `API 5xx`；`API 停止` 抑制 `API 健康检查失败`（依赖链驱动） |
| 静默 | 支持「维护窗口」：选择服务 + 时长（15min/1h/自定义），期间告警只记不通知 |
| 可行动性 | 每条告警必须有 `suggested_action`，否则规则不允许启用（配置期校验） |

### 2.5 权限与高危操作（堡垒机 4A / RBAC）

| 实践 | 要点 |
|---|---|
| **RBAC 最小权限** | 默认拒绝，按角色显式授权 |
| **读写分离** | 只读诊断权限与变更权限分离 |
| **JIT 临时提权** | 需要时申请，限时自动回收 |
| **break-glass 应急账号** | 封存的最高权限账号，启用即强审计 + 告警 |
| **4A** | 认证 Authentication / 账号 Account / 授权 Authorization / 审计 Audit |
| **高危操作管控** | 二次确认 + 命令级阻断 + 审批流 |
| **审计留存** | ≥ 6 个月 |

**→ 本项目裁剪**（单机桌面工具，不引入账号体系，用「本地角色 + PIN 提权」模型）：

**三级角色**

| 角色 | 可读 | 可做 | 不可做 |
|---|---|---|---|
| **只读 Viewer**（默认） | 全部页面、指标、日志、告警 | 导出日志、确认告警 | 任何启停、配置写入 |
| **运维 Operator** | 全部 | 启停/重启服务、清理端口、切换模式、静默告警、执行备份 | 卸载服务、恢复备份、改端口/路径、改权限 |
| **管理员 Admin** | 全部 | 全部 | — |

**高危操作分级与管控矩阵**

| 等级 | 操作 | 管控 |
|---|---|---|
| 🔴 L3 极高危 | 卸载 NSSM 服务、**恢复备份（覆盖数据）**、重置配置、修改角色权限 | Admin 专属 + **输入操作名确认**（类 GitHub 删仓库）+ 强制填写变更原因 + 审计 |
| 🟠 L2 高危 | 停止生产服务、kill 端口占用进程、切换运行模式、修改端口/路径 | Operator+ + **二次确认弹窗（列出影响面）** + 审计 |
| 🟡 L1 中危 | 重启服务、清空日志、静默告警 | Operator+ + 轻确认（Toast 内撤销 5s）+ 审计 |
| 🟢 L0 低危 | 查看、导出、刷新、确认告警 | 全角色 + 审计（仅流水） |

**提权模型**：Viewer → Operator/Admin 通过 **本地 PIN**（首次运行设置，PBKDF2 存 hash）提权，提权有效期 **30 分钟**滑动过期，UI 顶栏显示剩余时间与「立即降权」按钮（JIT 思想的桌面化裁剪）。

**审计**：`logs/audit.jsonl` append-only + hash 链，默认保留 **180 天**，UI 提供审计查询页（按时间/角色/操作/结果筛选 + 导出 CSV）。

### 2.6 映射总表

| 维度 | 大厂实践 | v8 采纳程度 | 落地物 |
|---|---|---|---|
| 界面布局 | 阿里三层视图 / 蓝鲸场景化 | ✅ 完全 | 三段式框架 + 总览三层下钻 + 7 页面信息架构 |
| 功能模块 | 蓝鲸原子平台分层 | ✅ 完全 | Domain/Application/Adapter 四层 + Ports 契约 |
| 交互流程 | 蓝鲸 SOPS 流程编排 | ✅ 完全 | Pipeline + Step 模型，UI 呈现为可视 Stepper |
| 监控告警 | SRE + 字节降噪聚合 | ✅ 完全 | 症状化规则 + 黄金四指标 + 分组/抑制/静默 + runbook |
| 权限管理 | 堡垒机 4A + RBAC + JIT | ⚠️ 裁剪 | 三级本地角色 + PIN 提权 + 高危四级矩阵 |
| 审计合规 | 字节 Romaster | ✅ 采纳核心 | append-only hash 链审计流水 + 查询页 |
| 可观测 | 字节 Argos 统一 | ⚠️ 裁剪 | Metrics+Logs+Events 统一时间轴（不做 Traces） |
| 自愈 | 蓝鲸故障自愈 | ⚠️ 降级 | 半自动「一键执行推荐修复」 |
| CMDB | 阿里 CMDB | ❌ 不采纳 | 改为轻量资源清单 + 依赖拓扑 |

---

## 3. 目标架构

### 3.1 分层设计

```
┌────────────────────────────────────────────────────────────────┐
│ L4  Presentation 表现层                                         │
│     web/ (HTML/CSS/JS)  ←→  bridge.py (pywebview JS API)       │
│     职责：渲染、事件、路由；零业务逻辑                            │
└──────────────────────────┬─────────────────────────────────────┘
                           │ 只调 Application 的 UseCase / 只收 Event
┌──────────────────────────▼─────────────────────────────────────┐
│ L3  Application 应用层（用例编排）                               │
│     usecases/  pipeline/  event_bus.py  auth/                  │
│     职责：编排步骤、事务边界、权限校验、发事件、写审计            │
└──────────────────────────┬─────────────────────────────────────┘
                           │ 依赖 Domain 模型 + Adapter 的 Protocol
┌──────────────────────────▼─────────────────────────────────────┐
│ L2  Domain 领域层（纯逻辑，零 I/O，100% 可单测）                 │
│     models/  state_machine/  rules/  ports/                    │
│     职责：模式状态机、互斥规则、告警规则求值、权限矩阵、健康判定  │
└──────────────────────────┬─────────────────────────────────────┘
                           │ 只定义 Protocol，不含实现
┌──────────────────────────▼─────────────────────────────────────┐
│ L1  Adapter 适配层（所有 I/O 与平台细节）                        │
│     process/  service_nssm/  metrics_psutil/  storage_json/    │
│     health_http/  tray_pystray/  audit_jsonl/                  │
│     职责：实现 Domain 定义的 Port；封装 subprocess/psutil/文件   │
└────────────────────────────────────────────────────────────────┘

依赖方向：L4 → L3 → L2 ← L1     （L1 实现 L2 的 Protocol，依赖倒置）
禁止：L2 import L1/L3/L4；L1 import L3/L4；L4 import L1/L2
```

### 3.2 目标目录结构

```
server_manager/                      # 新包（v6 单文件退役为 legacy/）
├── __main__.py                      # 入口：装配容器 → 起 WebView
├── container.py                     # 依赖注入容器（get_xxx_service）
│
├── domain/                          # L2 纯逻辑，零 I/O
│   ├── models.py                    # RunMode ServiceSpec ServiceState Alert AuditEntry Role ...
│   ├── mode_machine.py              # 运行模式状态机（IDLE/DEV/PROD/SWITCHING）+ 互斥规则
│   ├── alert_rules.py               # 规则求值：症状规则、分组、抑制、静默、燃烧率
│   ├── permissions.py               # 角色×操作 权限矩阵 + 高危分级
│   ├── health.py                    # 健康判定（黄金四指标聚合）
│   └── ports.py                     # Protocol：ProcessPort ServicePort MetricsPort
│                                    #   StoragePort HealthPort NotifyPort AuditPort ClockPort
│
├── application/                     # L3 编排
│   ├── event_bus.py                 # 类型化事件总线（替代裸 queue.Queue）
│   ├── events.py                    # @dataclass 事件定义（替代 12 种裸 tuple）
│   ├── pipeline.py                  # Pipeline / Step / StepResult（SOPS 模型）
│   ├── auth/
│   │   ├── session.py               # 角色会话 + JIT 30min 滑动过期
│   │   └── guard.py                 # @require(perm, danger_level) 装饰器
│   └── usecases/
│       ├── start_dev.py             # 开发模式 5 步 Pipeline
│       ├── start_prod.py            # 生产模式 Pipeline（NSSM）
│       ├── switch_mode.py           # 期望态收敛（含互斥停机）
│       ├── stop_all.py
│       ├── install_services.py      # L3 高危
│       ├── uninstall_services.py    # L3 高危
│       ├── kill_port.py             # L2 高危
│       ├── log_ops.py               # 导出/清空/关键字规则
│       ├── alert_ops.py             # 确认/静默/执行推荐修复
│       ├── backup_ops.py            # 备份/恢复（复用 fastapi_app/services/backup）
│       └── config_ops.py            # 读写 + schema 校验
│
├── adapters/                        # L1 I/O
│   ├── process_win.py               # taskkill / 进程树 / 端口占用（保留 v6 安全约定）
│   ├── service_nssm.py              # sc / nssm 封装 + OEM 解码 + 依赖探测
│   ├── metrics_psutil.py            # 2s 采样，psutil 缺失降级
│   ├── health_http.py               # /api/health 探测（超时/重试可配）
│   ├── storage_json.py              # 配置读写 + pydantic schema 校验 + 版本迁移
│   ├── audit_jsonl.py               # append-only + sha256 hash 链
│   ├── notify_win.py                # 托盘气泡 / 声音 / 弹窗
│   └── tray_pystray.py
│
├── presentation/                    # L4
│   ├── bridge.py                    # @pywebview JS API：一个方法 = 一个 UseCase
│   ├── serializers.py               # Domain → JSON DTO
│   └── web/
│       ├── index.html
│       ├── css/tokens.css           # ← v7 Design Token 1:1 迁移
│       ├── css/app.css
│       └── js/{app,router,api,pages/*}.js
│
└── legacy/
    └── server_manager_v6.py         # 冻结基线，仅供对照，不参与打包
```

### 3.3 依赖规则与守护（防止重新腐化）

1. **CI 门禁**：引入 `import-linter` 契约，声明 4 层顺序，违反即 CI 失败。
2. **规模门禁**：函数 ≤ 80 行、文件 ≤ 800 行、类方法 ≤ 20 个（对齐项目 `docs/CODE_STANDARDS.md` 2.5 节 SOLID 细则），超限 CI 告警。
3. **禁止静默**：`except Exception: pass` 全面禁止；统一改为 `except SpecificError as e: audit.record_failure(...); bus.emit(OperationFailed(...))`。CI 用 ruff 规则 `BLE001`/`S110` 拦截。
4. **导入健全性检查**：CI 增加 `python -c "import server_manager.<每个模块>"` 冒烟，防止 D6 类死代码再现。
5. **Domain 零依赖检查**：`domain/` 目录禁止出现 `import subprocess|psutil|tkinter|os.system|open(`。

### 3.4 关键接口契约（Domain Ports）

```python
# domain/ports.py —— 仅 Protocol，无实现
class ProcessPort(Protocol):
    def find_port_pids(self, port: int) -> list[int]: ...
    def kill_tree(self, pid: int, *, timeout_s: float = 5.0) -> KillResult: ...
    def spawn(self, spec: SpawnSpec) -> ProcessHandle: ...

class ServicePort(Protocol):
    def state(self, name: str) -> ServiceState: ...          # RUNNING/STOPPED/PAUSED/ABSENT
    def pid(self, name: str) -> int | None: ...
    def install(self, spec: ServiceSpec) -> OpResult: ...
    def control(self, name: str, cmd: ServiceCmd) -> OpResult: ...
    def wait_state(self, name: str, want: ServiceState, timeout_s: float) -> bool: ...
    def detect_dependencies(self) -> list[str]: ...

class HealthPort(Protocol):
    def probe(self, target: HealthTarget) -> HealthSample: ...   # 含 latency_ms / status_code

class MetricsPort(Protocol):
    def sample(self) -> MetricsSample | None: ...                # None = 采集器不可用

class StoragePort(Protocol):
    def load(self, schema: type[T]) -> T: ...                    # 带校验与版本迁移
    def save(self, obj: BaseModel) -> None: ...

class AuditPort(Protocol):
    def record(self, entry: AuditEntry) -> None: ...             # append-only，永不抛出
    def query(self, f: AuditFilter) -> list[AuditEntry]: ...
    def verify_chain(self) -> ChainVerifyResult: ...             # hash 链完整性校验

class NotifyPort(Protocol):
    def notify(self, level: Severity, title: str, body: str) -> None: ...
```

**契约要点**：全部返回**显式结果对象**（`OpResult`/`KillResult` 含 `ok / reason / detail / duration_ms`），不再用 bool + 静默失败。这是解决 D5 的根本手段。

### 3.5 事件与状态模型（替代裸 queue）

```python
# application/events.py
@dataclass(frozen=True) class LogAppended:    ts: float; level: LogLevel; source: str; text: str
@dataclass(frozen=True) class MetricsUpdated: sample: MetricsSample
@dataclass(frozen=True) class StepStarted:    trace_id: str; pipeline: str; step: str; index: int; total: int
@dataclass(frozen=True) class StepFinished:   trace_id: str; step: str; ok: bool; duration_ms: int; detail: str
@dataclass(frozen=True) class ModeChanged:    old: RunMode; new: RunMode; trace_id: str
@dataclass(frozen=True) class AlertRaised:    alert: Alert
@dataclass(frozen=True) class AlertResolved:  alert_id: str; reason: str
@dataclass(frozen=True) class AuthChanged:    role: Role; expires_at: float | None
@dataclass(frozen=True) class ToastRequested: level: Severity; text: str; undo: UndoToken | None
```

**运行模式状态机**（domain/mode_machine.py）：

```
        ┌───────────────── IDLE ─────────────────┐
        │                   ▲                    │
   start_dev              stop_all            start_prod
        ▼                   │                    ▼
   ┌─ DEV ─┐            SWITCHING           ┌─ PROD ─┐
   │       │◄──── switch_mode（先停对侧）────►│        │
   └───────┘                                └────────┘

不变式：DEV 与 PROD 互斥；任一转移期间进入 SWITCHING 并持锁，拒绝并发转移。
```

这把散落在 `_ensure_production_stopped` / `_ensure_development_stopped` / `ActionLock` 三处的互斥逻辑内聚为一个可单测的状态机。

### 3.6 数据模型扩展（配置 schema v2）

```jsonc
{
  "schema_version": 2,
  "app":     { "theme": "dark", "nav_collapsed": false, "reduced_motion": "auto" },
  "ports":   { "api": 5002, "web": 3000, "redis": 6379 },
  "paths":   { "redis_exe": "", "nssm": "", "python": "", "project": "" },
  "health":  { "api_path": "/api/health", "timeout_s": 2, "retries": 30, "interval_s": 1 },
  "logs":    { "max_lines": 2000, "keep_lines": 1600, "retention_days": 14,
               "keyword_rules": [ { "pattern": "Traceback", "severity": "P2", "enabled": true } ] },
  "alerts":  { "rules": [ { "id": "api_health_fail", "family": "availability", "severity": "P1",
                            "expr": "health.api.consecutive_fail >= 3",
                            "for_s": 30, "runbook": "docs/runbook/api_down.md",
                            "suggested_action": "restart_api", "enabled": true } ],
               "group_by": ["service", "family"], "group_window_s": 300,
               "inhibitions": [ { "source": "pg_down", "targets": ["api_5xx", "api_health_fail"] } ],
               "silences": [] },
  "auth":    { "pin_hash": "pbkdf2_sha256$...", "elevate_ttl_s": 1800,
               "default_role": "viewer", "require_reason_for_l3": true },
  "audit":   { "retention_days": 180, "hash_chain": true },
  "backup":  { "schedule": "manual", "target_dir": "", "encrypt": true }
}
```

**迁移**：`storage_json` 检测 `schema_version` 缺失即视为 v1，按字段映射自动升级并备份原文件为 `*.v1.bak`。

---

## 4. 功能模块重构清单

| # | 模块 | v6 现状 | v8 目标 | 变更类型 |
|---|---|---|---|---|
| F1 | 运行模式编排 | 12+15 方法散在上帝类 | `mode_machine` + 3 个 UseCase + Pipeline 可视化 | 🔄 重写（逻辑迁移） |
| F2 | 进程管理 | 5 个私有方法 | `ProcessPort` + `process_win` 适配器，返回显式结果 | ♻️ 迁移 + 加契约 |
| F3 | 服务托管 | 15 个私有方法 | `ServicePort` + `service_nssm`，依赖探测保留 | ♻️ 迁移 + 加契约 |
| F4 | 日志中心 | 9 方法 + 单窗口 | 多源分流（API/Web/Redis/管理器自身）+ 级别过滤 + 关键字规则告警 + 虚拟滚动 | ⬆️ 增强 |
| F5 | 指标监控 | psutil 2s 采样 + 手绘图 | 黄金四指标卡 + 时序图（Canvas 轻量绘制）+ 进程 Top5 + 时间轴联动 | ⬆️ 增强 |
| F6 | 告警中心 | 阈值告警 + 60s 冷却 | 症状规则引擎 + 分组/抑制/静默 + P1~P4 + runbook + 推荐修复 + 事件聚合 | 🆕 重建 |
| F7 | 配置中心 | JSON 直读全局 dict | pydantic schema + 校验 + 版本迁移 + 分组表单 + 变更 diff 预览 | ⬆️ 增强 |
| F8 | 部署发布 | Stepper 4 步 | Pipeline 模型驱动，步骤可重试/可中断/带耗时 | ⬆️ 增强 |
| F9 | **权限与提权** | 不存在 | 三级角色 + PIN 提权 + JIT 30min + 高危四级矩阵 + UI 权限态 | 🆕 新增 |
| F10 | **操作审计** | 不存在 | append-only hash 链 + 查询页 + CSV 导出 + 链完整性校验 | 🆕 新增 |
| F11 | 备份恢复 | 不存在（GUI 侧） | 复用 `fastapi_app/services/backup` 子系统，GUI 提供触发与进度 | 🆕 新增（复用后端） |
| F12 | 系统集成 | DPI/暗色标题栏/托盘/单实例 | 全部保留，迁入 adapters | ♻️ 平移 |
| F13 | 控制台版 | 779 行死代码 | **删除**。改为 `python -m server_manager --cli <usecase>` 复用同一 Application 层 | ❌ 删除 + 🆕 重做 |

---

## 5. UI / 交互设计

### 5.1 信息架构（7 页面 + 分组导航）

```
运行
 ├─ 总览驾驶舱      Overview      黄金四指标 / 三层健康 / 一键操作 / 活动流水
 ├─ 服务编排        Services      期望态声明 / 服务清单 / 依赖拓扑 / Pipeline
可观测
 ├─ 监控告警        Alerts        事件聚合 / P1~P4 / runbook / 静默 / 规则
 ├─ 日志中心        Logs          多源分流 / 级别过滤 / 关键字规则 / 虚拟滚动
运维
 ├─ 部署发布        Deploy        Pipeline Stepper / 版本 / 回滚
 ├─ 备份恢复        Backup        备份清单 / 一键备份 / 恢复（L3 高危）
系统
 ├─ 配置中心        Config        分组表单 / diff 预览 / schema 校验
 └─ 权限与审计      Access        角色/提权 / 高危矩阵 / 审计流水查询
```

保留 v7 三段式框架：TopBar 52px（面包屑 + 模式徽章 + 端口 chip + **角色徽章/提权倒计时** + 主题切换）、SideNav 208px/52px 可折叠、StatusBar 30px。

### 5.2 关键页面设计要点

**① 总览驾驶舱**
- 顶部**黄金四指标卡**：延迟 P95 / QPS / 错误率 / 饱和度，每卡带 sparkline + 环比。
- **三层健康**（阿里三层视图）：基础设施（PostgreSQL/Redis/磁盘/端口）→ 应用服务（API/ARQ/Web）→ 业务健康（接口错误率/任务积压），逐层折叠下钻。
- **一键操作组**：开发模式 / 生产模式双卡，互斥联动锁，运行中卡片显示 PID/端口/运行时长。
- **活动流水**：最近 N 条 Step/Alert/Audit 混合时间轴，点击跳转对应页面并定位到该时刻。

**② 服务编排**
- 顶部**期望态选择器**（Segmented：停机 / 开发 / 生产），选择后展示收敛计划（将执行哪些步骤），确认后执行 → 实时 Stepper。
- 服务表格 44px 行高：名称 / 类型 / 状态徽章 / PID / 端口 / 启动类型 / 依赖 / 操作。
- **依赖拓扑图**：SVG 有向图展示 PostgreSQL → Redis → API → ARQ / Web，节点着色反映健康，用于抑制规则的可视化解释。
- 高危操作（卸载服务）在行内呈现为红色文字按钮，Viewer 角色下**禁用并带 Tooltip 说明所需角色**。

**③ 监控告警**
- 左侧筛选（严重度 / 服务 / 状态 / 时间窗），右侧**事件聚合卡片**：一个事件 = N 条同根因告警，卡片展示首次/最近时间、发生次数、影响服务、runbook 摘要、`一键执行推荐修复` 按钮。
- 顶部工具条：`静默窗口`（下拉选服务 + 时长）、`规则管理`、`导出`。
- 告警详情抽屉：时间轴（告警 ↔ 该时刻指标 ↔ 该时刻日志三联）。

**④ 日志中心**
- 左侧源树（管理器 / API / ARQ / Web / Redis），右侧虚拟滚动日志区（等宽字体 + 级别色标 + 关键字高亮）。
- 顶部：级别多选、关键字搜索、`跟随尾部` 开关、导出、清空（L1 高危 + 5s 撤销）。
- 底部：**关键字规则**入口（命中即产告警，对应蓝鲸日志关键字告警）。

**⑤ 权限与审计**（新增页，本次重构的差异化亮点）
- 上半：当前角色卡（角色徽章 + 提权倒计时进度条 + `提权` / `立即降权` 按钮）+ **高危操作矩阵表**（4 级 × 操作清单 × 各角色 ✓/✗），让权限规则对用户完全透明。
- 下半：**审计流水表**（时间 / 角色 / 操作 / 目标 / 结果 / 耗时 / trace_id），支持筛选、导出 CSV、`校验哈希链` 按钮（返回「链完整，N 条记录，无篡改」）。

### 5.3 权限态与高危操作交互（统一规范）

| 场景 | 交互 |
|---|---|
| 无权限的操作按钮 | **不隐藏，禁用 + 灰化 + Tooltip**「需要 运维 角色，点击提权」（隐藏会让用户以为功能缺失） |
| 点击禁用按钮 | 直接唤起提权弹窗（PIN 输入），成功后**自动继续原操作** |
| L2 高危确认 | 弹窗 420px：标题 + **影响面清单**（将停止 N 个服务、断开 M 个连接、预计耗时 X 秒）+ 取消/确认 |
| L3 极高危确认 | 弹窗：红色警示条 + 影响面 + **输入框要求键入操作名**（如 `uninstall erp-prod`）+ **变更原因必填** + 确认按钮默认禁用直到校验通过 |
| L1 中危 | 直接执行 + Toast 内 `撤销`（5s） |
| 提权即将过期 | 剩余 5min 时顶栏徽章变橙 + Toast 提示，可续期 |
| 操作执行中 | 按钮进入 busy 态（幂等锁），同族按钮全部禁用（复用 `ActionLock` 语义） |

### 5.4 响应式（沿用 v7 四档）

≥1440 舒适态（四卡一行）／1200–1439 标准态／1080–1199 堆叠（四卡 2×2 + 隐藏次要列）／<1080 导航自动折叠 52px。

---

## 6. 迁移路径（Strangler Fig 渐进替换）

| 阶段 | 内容 | 产出 | 预估 |
|---|---|---|---|
| **P0** ✅ | 现状审计 + 大厂调研 + 路线裁决 | 本文档 + `ui_prototype_v8.html` | 已完成 |
| **P1** | 骨架搭建：目录结构 + `domain/ports.py` + `container.py` + `event_bus` + `import-linter` 契约 + CI 门禁 | 可运行空壳 + 全绿 CI | 3d |
| **P2** | **Domain 迁移（关键路径）**：`mode_machine` / `permissions` / `alert_rules` / `health` 从 v6 逐行提取为纯逻辑 + 单测覆盖 ≥85% | 可单测的业务内核 | 5d |
| **P3** | Adapter 迁移：`process_win` / `service_nssm` / `metrics_psutil` / `health_http` / `storage_json` / `audit_jsonl`，**保留 v6 全部 Windows 细节与安全约定** | 与 v6 行为等价，契约化返回 | 4d |
| **P4** | Application + Bridge：UseCase 编排 + Pipeline + auth guard + `bridge.py` | CLI 可驱动全部能力（`--cli start-dev` 等），先于 UI 验证 | 3d |
| **P5** | Web UI 落地：原型 HTML/CSS/JS 拆分为 `presentation/web/`，接 bridge，逐页替换 | 功能对等的 v8 界面 | 5d |
| **P6** | 打包与实机验证：spec 更新（pywebview + WebView2 检测/引导）+ Windows Server 2019 实测 + v6/v8 并存验证 | `ERP服务器管理器_v8.0.0.exe` | 3d |

**关键路径**：P2（Domain 迁移）。P4 结束后即可通过 CLI 验证全部业务能力，**UI 风险与业务风险解耦**——这是本迁移路径最重要的设计。

**并存策略**：v8 配置文件 `schema_version=2` 与 v6 隔离；EXE 不同名；两者可同时安装，v8 出问题立即回退 v6。

---

## 7. 风险与对策

| # | 风险 | 等级 | 对策 |
|---|---|---|---|
| R1 | Windows Server 2019 无 WebView2 Runtime | 🔴 高 | 随包 Evergreen 离线安装器（~100MB）；启动时检测缺失 → 引导安装；极端离线场景改 Fixed Version 随包（+180MB） |
| R2 | 业务逻辑迁移时丢失 v6 隐性经验（OEM 解码、服务依赖探测、进程树边界） | 🔴 高 | P3 阶段**逐行对照**，v6 源码冻结在 `legacy/`；对每个适配器写"行为等价性"测试用例 |
| R3 | pywebview 桥接性能（高频日志刷屏） | 🟡 中 | 事件批量合并 + 后端节流（日志 100ms 聚合一批）+ 前端虚拟滚动；沿用 v6 已验证的批量 flush 思路 |
| R4 | EXE 体积增大 | 🟡 中 | spec `excludes` 继续排除重型依赖；WebView2 用 Evergreen 而非 Fixed；目标 ≤ 60MB（不含 Runtime） |
| R5 | 重构周期内 v6 仍需维护 | 🟡 中 | v6 进入**仅修 P1 缺陷**的冻结态；新需求全部排入 v8 |
| R6 | 权限模型在单机场景被绕过（用户直接改 config 里 pin_hash） | 🟡 中 | 明确定位：**防误操作 + 留痕，不防恶意管理员**。文档写明威胁模型边界；审计 hash 链可检出篡改 |
| R7 | 告警规则配置门槛升高 | 🟢 低 | 预置 4 条 P1 症状规则 + 4 条 P3 饱和度规则开箱可用；规则管理页提供可视化编辑与"测试求值" |
| R8 | 分层导致代码量增加、简单改动变慢 | 🟢 低 | 接受。换来的是可测性与可替换性；用 CI 规模门禁防止过度分层 |

---

## 8. 验收标准（DoD）

**架构**
- [ ] `import-linter` 4 层契约全绿；`domain/` 零 I/O 导入检查通过
- [ ] 无文件 > 800 行、无函数 > 80 行、无类 > 20 方法
- [ ] `except Exception: pass` 出现次数 = **0**（v6 为 90+）
- [ ] 模块级可变全局变量 = **0**（v6 为 25），全部经容器注入
- [ ] Domain 层单测覆盖率 ≥ 85%；全项目 ≥ 60%
- [ ] 所有模块 import 冒烟通过（防 D6 复现）

**功能对等**
- [ ] v6 全部能力在 v8 可用：开发/生产启停、模式互斥、端口清理、Redis 探测、NSSM 安装/卸载/依赖探测、日志导出、托盘、单实例、主题切换（**无需重建 UI**）
- [ ] Windows Server 2019 + Win10 实机各跑通一次完整开发/生产切换

**新增能力**
- [ ] 三级角色权限矩阵生效；Viewer 无法执行任何变更
- [ ] PIN 提权 + 30min JIT 过期 + 立即降权可用
- [ ] L2/L3 高危操作确认流程按 5.3 规范实现
- [ ] 审计流水 append-only，`verify_chain()` 可检出人为篡改
- [ ] 告警：4 条 P1 症状规则可触发；分组、抑制、静默三件套生效；每条告警带 runbook 与推荐修复
- [ ] 黄金四指标卡实时更新；告警可下钻到同时刻日志与指标

**交付**
- [ ] `ERP服务器管理器_v8.0.0.exe` 打包成功，≤ 60MB（不含 Runtime）
- [ ] v6/v8 并存互不干扰，v8 首次启动自动迁移 v1 配置并备份
- [ ] 文档齐备：架构说明、runbook 目录、权限矩阵、回退手册

---

## 9. 附录：现状缺陷清单（可直接转 issue）

| ID | 严重度 | 位置 | 问题 | v8 处置 |
|---|---|---|---|---|
| BUG-01 | 🔴 P1 | `server_manager_console.py` import 段 | 导入 `_API_PORT`/`_WEB_PORT`/`_REDIS_PORT` 三个不存在符号（实为 `_DEFAULT_*`），导入即 ImportError，779 行完全不可运行 | 删除该文件，改为 `--cli` 复用 Application 层。若需在 v6 上急修：三个符号改为 `_DEFAULT_*` 或统一改读 `_PORTS.api/.web/.redis` |
| BUG-02 | 🟠 P2 | `one_click_action.py` L317-328 | 函数体内 `from server_manager import RoundedButton, TOKENS` 规避循环依赖 | UI 组件由 L4 提供，控制器不再反向依赖 |
| BUG-03 | 🟠 P2 | 全文 90+ 处 | `except Exception: pass` / `suppress` 静默吞异常 | 全部改显式结果对象 + 审计记录 + 事件上报 |
| BUG-04 | 🟠 P2 | 3 处 | 硬编码 `C:\` 绝对路径 | 移入配置 `paths.*`，带探测与校验 |
| BUG-05 | 🟡 P3 | `_start_dual_thread` | 健康检查 `30×1s` 硬编码 | 移入 `config.health.{timeout_s,retries,interval_s}` |
| BUG-06 | 🟡 P3 | `_rebuild_ui` L3255 | 主题切换销毁重建全部控件 | CSS 变量切换，零重建 |
| BUG-07 | 🟡 P3 | `_APP_CONFIG` | 配置无 schema 校验，坏配置导致启动异常 | pydantic 模型 + 版本迁移 + 坏配置回退默认值并告警 |
| BUG-08 | 🟡 P3 | `AlertEngine` | 原因告警（CPU/内存阈值），噪声高 | 症状告警为主，饱和度降为 P3 |
| BUG-09 | 🟢 P4 | `_msg_queue` payload | 12 种消息无类型定义 | `@dataclass(frozen=True)` 事件 |
| BUG-10 | 🟢 P4 | `draw_icon` L953 | 单函数 120 行 | 图标改 SVG 资源，函数消失 |

---

## 10. 待决策项（需评审确认）

1. **权限模型强度**：当前设计为「防误操作 + 留痕」的本地 PIN 模型。若需防恶意（多人共用服务器），需升级为 Windows 账号集成（校验当前用户是否属于指定本地组），成本 +2d。**请确认威胁模型。**
2. **备份恢复复用范围**：GUI 侧是否直接复用 `fastapi_app/services/backup` 的 orchestrator（需 GUI 进程能 import fastapi_app，会增大 EXE），或改为通过后端 API 调用（要求后端在线）。**推荐后者。**
3. **审计存储**：`audit.jsonl` 单文件 append + hash 链，180 天约 10~50MB。是否需要按月切分归档？
4. **控制台版去留**：确认删除 779 行死代码，改为 `--cli` 子命令模式。
5. **P1 症状规则的错误率数据源**：需后端暴露 `/api/metrics`（5xx 计数、P95 延迟、ARQ 队列长度）。若后端暂不支持，第一版降级为「健康检查 + 服务态 + 饱和度」三类规则。**请确认后端改造意愿。**

---

*本方案由现状代码静态审计（AST 量化）+ 大厂公开实践调研（阿里 Apsara Uni-manager / 腾讯蓝鲸智云 / 字节 Argos·Romaster / Google SRE / 堡垒机 4A）+ 项目既有设计资产（v7 pywebview 裁决、Design Token 体系）三方交叉产出。所有量化指标均可复现。*
