---
design_type: feature
created_at: 2026-08-14
---

# 生产模式启动方式与性能重构

## Intent Contract

```
intent: 重构 Windows 原生生产模式的启动链路与性能：统一入口、多进程 Uvicorn、Nginx/静态托管前端、ARQ 后台任务，
      并以「Windows 服务 + 守护」形态集成进 server_manager（开机自启、崩溃自愈、GUI 仅做状态与管理）
constraints:
  - 不改变对外访问方式（内网 http://<host>:3000，后端 5002）
  - 不破坏现有调试模式（run.py / server_manager 调试卡）与既有 API 行为
  - 不引入需要付费或大幅新增依赖的组件（Nginx/NSSM 为可选，缺失时有降级路径）
  - Windows 上不依赖 uvloop（不支持），保留 httptools
success_criteria:
  - 生产以多 worker Uvicorn 运行（默认 UVICORN_WORKERS=4），并发/吞吐较单进程提升
  - 生产不再依赖 vite preview 托管前端（去掉 Node 进程，内存下降）
  - server_manager 可一键安装/启动/停止/卸载 Windows 服务，服务开机自启、进程崩溃自动重启
  - 前端/后端/Redis/ARQ 状态与健康在 GUI 可观测
  - 后端测试套件与前端类型检查通过；手工并发验证通过
risk_level: medium
```

## Verification Contract

```
verify_steps:
  - run tests: pytest tests/ -m "not e2e and not stress" && npm run build 后 vue-tsc 通过
  - check: uvicorn 多进程启动后，netstat 与任务管理器确认 worker 数；/api/health 返回 200
  - check: Nginx/降级静态托管下首页 200、/api 反代、/ws 连通；静态资源带缓存头
  - check: NSSM 安装后 sc query 显示 RUNNING；kill 后端进程后自动重启；重启系统后自启
  - check: 生产运行前后对比任务管理器内存（预期去掉 Node 进程，总内存下降）
  - confirm: 浏览器访问 192.168.0.95:3000 登录、核心页面正常；GUI 生产托管面板状态正确
```

## Governance Contract

```
approval_gates:
  - 本设计获批后才进入 writing-plans / 实现
  - Windows 服务注册（NSSM）行为需人工确认后再执行
rollback: git revert；涉及文件均为可逆改动，服务注册可用 GUI「卸载服务」撤销
ownership: 当前会话
```

## Scope

| In | Out |
|---|---|
| 统一生产启动入口（start.py --prod → prod_runner 监督器） | 重构开发模式（dev/HMR）启动 |
| 多进程 Uvicorn（--workers，uvloop 之外的可选项如 httptools/keep-alive/no-access-log） | 引入 uvloop（Windows 不支持） |
| 前端托管改为 Nginx for Windows 首选 + FastAPI dist 挂载降级，移除 vite preview | 改造成本地的 SPA 构建产物/路由 |
| ARQ worker 纳入生产启动（含内建 cron） | 重新启用 Celery |
| server_manager 新增「生产托管」面板（服务安装/启停/状态/健康/日志） | 把 server_manager 自身做成服务 |
| Windows 服务（NSSM）注册与开机自启、崩溃自愈 | 引入 k8s/Docker 部署（另立 initiative） |
| deploy-windows.ps1 / .env.example 文档纠偏 | 扩展第三方监控栈（Prometheus 等保持现状） |

## Decisions

| # | 决策 | 说明 / 备选 |
|---|---|---|
| 1 | 统一入口：`start.py --prod` 改为调用新监督器 `prod_runner` | 替代 server_manager dual_prod 的手工多进程方式；dual_prod 保留为「手动快速排障」入口 |
| 2 | 多进程 Uvicorn：`--workers {UVICORN_WORKERS}`，默认 4 | 与 database.py 按 workers 分摊连接池的既有契约一致；Windows 不用 uvloop（无效），保留 httptools + `--no-access-log` + keep-alive |
| 3 | 前端托管：Nginx for Windows 首选，缺失时降级 FastAPI 挂载 dist | 移除 vite preview（去掉 Node 进程，省内存）；复用 config/nginx.conf 的 server 块语义，新增 Windows 专用配置 |
| 4 | 后台任务：启动 ARQ worker（`arq ...WorkerSettings`） | Celery 已迁移 ARQ 且 cron 内建，无需独立 beat |
| 5 | Windows 服务：NSSM 注册 `erp-prod`（监督器）与 `erp-arq`（ARQ worker），`SERVICE_AUTO_START` + 崩溃自动重启 | 备选 pywin32 自实现服务；NSSM 零 Python 依赖、日志重定向成熟 |
| 6 | server_manager 增加「生产托管」面板 | GUI 不再作为生产进程宿主，只做服务的安装/启停/状态/健康/日志查看 |
| 7 | 文档纠偏：deploy-windows.ps1 去掉 uvloop/Celery 误导，写 ARQ + NSSM | 消除「写了但没生效」的坑 |
| 8 | worker 数可配置且默认 4（用户机器 8GB 内存），GUI 在安装服务时可选（4 档 / 2 省内存档） | 多 worker 内存 ×N 与省内存目标存在张力，按 8GB 内存估算：每 worker 约 400-500MB，4 worker ≈ 2GB，加 PG/Redis/系统仍有余量 |

## Surface

- **API**：无对外 API 变更。`/api/health` 继续作为就绪探针；监督器向 `logs/prod_runner.json` 写本地状态（各进程 PID、状态、最近健康检查时间），供 server_manager GUI 读取展示。
- **Storage**：无表结构变更。`frontend-vite/dist` 构建产物作为前端静态源；新增 `config/nginx-windows.conf`（Windows Nginx 配置）。
- **Components**：
  - 新增 `fastapi_app/core/prod_runner.py`：生产监督器（依赖解析、Redis 检查、子进程拉起 Uvicorn/ARQ/前端、健康门、崩溃重启退避、优雅关闭、状态落盘）。
  - 修改 `start.py`：`--prod` 走 prod_runner（多 worker 需要子进程方式，不能再用进程内 `uvicorn.run`）。
  - 修改 `server_manager.py`：新增「生产托管」卡片/面板（检测 NSSM、安装/卸载/启动/停止/重启服务、读取 prod_runner 状态、查看日志），复用现有暗色 UI 与进程/日志组件。
  - 修改 `main.py`（可选）：production 下将 dist 挂载为 SPA 静态（html=True）作为 Nginx 缺失时的降级路径，并适配根路由（不再返回 JSON）。
  - 修改 `deploy-windows.ps1`、`.env.example`：纠偏 uvloop/Celery 表述，补齐 `UVICORN_WORKERS` 与 NSSM 说明。
- **Files-touched**：
  - 新增：`fastapi_app/core/prod_runner.py`、`config/nginx-windows.conf`
  - 修改：`start.py`、`server_manager.py`、`start_production_optimized.py`（保持 shim）、`restart_backend.py`（改造为多 worker 或标注弃用）、`deploy-windows.ps1`、`.env.example`、`main.py`（可选）、`frontend-vite/vite.config.ts`（preview 仅调试用）

## Risks & Open Questions

- **内存与并发的张力**：多 worker 每进程内存约等于单进程，总内存可能高于现状（虽然去掉 Node/vite preview）。需在 GUI 展示各服务 RSS，并让 worker 数可配置（默认 4，省内存档 2）。
- **NSSM 未安装**：GUI 需检测并在缺失时给出安装指引，不阻断其它功能。
- **每 worker 独立预热**：4 个 worker 各自执行 DB/Redis 预热，启动耗时略增；均属后台预热，不阻塞「健康门」就绪判定。
- **Nginx 配置风险**：`/static/uploads` 上传目录别名、SPA fallback、WebSocket 升级需在 Windows 配置中正确复刻；上线前用 `nginx -t` 校验，失败自动回退降级路径。
- **根路由语义变化**：production 下 `/` 由 JSON 响应改为 index.html，仅影响直接访问根路径的场景（前端 SPA 正常）。

> 已定（用户确认 2026-08-14）：worker 默认 4（8GB 内存），GUI 安装服务时可调；ARQ worker 纳入守护自愈，Redis 保持独立 Windows 服务、监督器仅检查。
