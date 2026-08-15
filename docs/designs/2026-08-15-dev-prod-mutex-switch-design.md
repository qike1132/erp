---
design_type: feature
created_at: 2026-08-15
---

# ERP 服务器管理器：开发/生产互斥切换

## Intent Contract

```
intent: 在 ERP 服务器管理器 GUI 中，点击「开发服务器」或「生产服务」启动时，自动关闭对方的运行模式并清理端口，实现互斥无缝切换
constraints:
  - Redis 服务（6379 缓存 + 6380 ARQ 队列）在切换时保留运行，不随模式启停
  - 生产模式通过 NSSM 服务（erp-prod + erp-arq）启停，Nginx 由 prod_runner 自动拉起
  - 开发模式通过 subprocess 启动 uvicorn --reload + vite dev server
  - 不改变现有手动「全部停止」按钮行为
success_criteria:
  - 点击开发启动：若生产服务运行 → 自动停止 erp-prod + erp-arq，清理 5002/3000 端口，开发模式正常启动
  - 点击生产启动：若开发模式运行 → 停止开发进程，清理 5002/3000 端口，erp-prod + erp-arq 正常启动
  - 切换过程无端口冲突，Redis 始终可用
risk_level: medium
```

## Verification Contract

```
verify_steps:
  - run tests: python -c "import server_manager"  # 语法/导入校验
  - manual: GUI 双向切换测试 A（生产→开发）：先启动生产服务，点击开发启动；
    confirm: 日志出现「正在停止生产服务」→ 服务达 STOPPED → 开发模式就绪，5002 归 uvicorn --reload，3000 归 vite
  - manual: GUI 双向切换测试 B（开发→生产）：开发模式运行中点击启动服务；
    confirm: 开发进程终止 → 5002/3000 空闲 → erp-prod/erp-arq RUNNING，3000 归 nginx
  - manual: 切换后 Redis 6379/6380 全程可 PING（未被动过）
  - manual: 开发启动进行中（状态=启动中）点击生产启动 → 被拒绝并提示，不产生双后端
```

## Governance Contract

```
approval_gates:
  - 设计文档评审（本阶段）
  - 代码实现后的 GUI 手动验证
rollback: 撤销对 server_manager.py 的改动（git checkout 该文件）
ownership: ERP 运维负责人
```

## Scope

| In | Out |
|----|-----|
| 开发启动前自动停止生产 NSSM 服务 | 修改 Redis 服务启停逻辑 |
| 生产启动前自动停止开发进程 | 修改 Nginx 配置 |
| 切换时清理 5002/3000 端口 | 改造「全部停止」按钮 |
| 自动无缝切换（无确认弹窗） | 引入新的配置文件 |

## Decisions

| # | 决策 | 选择 | 说明 |
|---|------|------|------|
| 1 | 生产服务范围 | erp-prod + erp-arq | 仅前后端生产服务，Redis 属共享基础设施 |
| 2 | Redis 处理 | 保留 | 开发/生产均依赖 6379/6380 |
| 3 | 切换交互 | 自动无缝 | 检测到异模式直接停止，不弹窗 |
| 4 | 生产启动方式 | NSSM 服务 | Nginx 由 prod_runner 自动拉起 |
| 5 | 开发清理范围 | 清端口 + 停残留 prod | 清理 5002/3000 并停残留 prod_runner 进程树 |

## Surface

### 组件：server_manager.py

新增互斥切换的核心方法，供开发/生产启动入口复用：

- `_wait_service_stopped(name, timeout=45)` — 发出 `nssm stop` 后轮询服务状态直到 STOPPED；超时返回 False（fail-closed 依据，绝不带着 STOP_PENDING 的服务去杀端口，避免触发 NSSM 崩溃重启）
- `_ensure_production_stopped()` — ① 对运行中的 `erp-prod`、`erp-arq` 逐个 stop 并等待 STOPPED（超时则中止切换并报错）；② 扫描并 taskkill /T 命令行含 `prod_runner` 的残留 python 进程树（手动启动的生产监督器不受 NSSM 控制）；③ 返回是否有生产在跑
- `_ensure_development_stopped()` — 停止开发模式子进程（`self._process` uvicorn + `self._frontend_process` vite，复用 `_stop_dual_mode_async` 的进程清理逻辑而非 stop_all，后者会误停 Redis），并重置 GUI 状态
- `_release_ports()` — 清理 5002 与 3000 端口占用（复用现有 `_kill_port_sync`，其内部对多 PID 监听同端口已有 3 轮重试）

### 行为变更

1. **`_start_dual_server`（开发启动）**：前置检查改为——若 `_mode` 处于 `starting/restarting` 直接拒绝；否则日志预告「检测到生产模式，将自动停止」→ 调用 `_ensure_production_stopped()`（含等待 STOPPED + 清残留 prod_runner）→ `_release_ports()` → 启动开发。
2. **`_start_services`（生产启动）**：新增守卫——`_mode` 处于 `starting/restarting` 时拒绝并提示「开发模式正在启动中，请稍候」（防 TOCTOU：启动线程随后 spawn 的 uvicorn 会与生产抢 5002）；否则 `_ensure_development_stopped()` → `_release_ports()` → `_service_cmd('start')`。

### 改动文件

- `server_manager.py`（唯一改动文件）

## Risks & Open Questions

- **NSSM 重启风暴（已缓解）**：在服务 STOP_PENDING 期间杀其进程会被 `AppExit Default Restart` 判定为崩溃而自动重启。缓解：`_wait_service_stopped` 轮询等待 STOPPED，超时 fail-closed 中止切换。
- **残留 prod_runner（已缓解）**：手动启动的生产监督器不受 NSSM stop 影响；通过命令行特征扫描 + taskkill /T 清理整棵树，避免 uvicorn worker 孤儿进程残留。
- **Nginx 多进程监听 3000（已缓解）**：实测存在多个 nginx PID 同时监听 3000；`_kill_port_sync` 的多 PID 收集 + 重试机制可覆盖，prod_runner 优雅关闭时亦会自行 `nginx -s stop`。
- **开发模式 `self._mode` 状态**：停止开发进程后需同步更新 GUI 状态（`self._mode = 'none'`），避免 UI 状态残留；UI 更新必须走 `self._msg_queue`（工作线程不得直改控件）。