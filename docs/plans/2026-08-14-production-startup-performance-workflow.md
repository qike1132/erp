---
intent: 重构 Windows 原生生产模式的启动链路与性能：统一入口（start.py --prod → prod_runner 监督器）、多进程 Uvicorn、Nginx/静态托管前端、ARQ 后台任务，并以「Windows 服务 + 守护」集成进 server_manager（开机自启、崩溃自愈、GUI 仅做状态与管理）
success_criteria:
  - 生产以多 worker Uvicorn 运行（默认 UVICORN_WORKERS=4，GUI 可调），并发/吞吐较单进程提升
  - 生产不依赖 vite preview 作为主托管（优先 Nginx，缺失才回退），去掉不必要的 Node 进程，内存下降
  - server_manager 可一键安装/卸载/启动/停止/重启 Windows 服务，服务开机自启、进程崩溃自动重启
  - 前端/后端/Redis/ARQ 状态与健康在 GUI 可观测
  - 后端测试套件与前端构建/类型检查通过；手工并发与服务自愈验证通过
risk_level: medium
auto_approve: true
---

## Steps

- [x] **Step 1: 新增生产监督器 prod_runner.py**
action: 在 fastapi_app/core/prod_runner.py 实现生产监督器：加载 .env；支持 --check 模式（校验配置与代码路径，Redis/dist/nginx 缺失仅 WARN 不失败，exit 0 表示模块功能正常）；拉起并守护子进程——(1) 后端 uvicorn：python -m uvicorn fastapi_app.main:app --host 0.0.0.0 --port 5002 --workers {UVICORN_WORKERS 默认 min(4,cpu)} --http httptools --proxy-headers --forwarded-allow-ips=* --no-access-log --timeout-keep-alive 5；(2) ARQ worker：python -m arq fastapi_app.core.arq_app.WorkerSettings；(3) 前端：检测到 nginx.exe 则管理 Nginx（加载 config/nginx-windows.conf），否则回退 npx vite preview --port 3000；(4) Redis：仅检查连通（预期为独立 Windows 服务，不拉起）。子进程退出自动重启（指数退避 2s→30s 封顶防崩溃风暴）；轮询 /api/health 200 后置后端就绪；向 logs/prod_runner.json 落盘状态（pid、started_at、各服务 pid/status、workers、最近健康检查时间）；--foreground 直接运行并支持 Ctrl+C 优雅关闭（先停前端/ARQ 再停 uvicorn）。
loop: until 校验通过
max_iterations: 3
verify:
  - type: shell
    command: python -m fastapi_app.core.prod_runner --check
  - type: artifact
    path: fastapi_app/core/prod_runner.py
    assert:
      kind: exists
gate: auto

- [x] **Step 2: start.py --prod 接入 prod_runner**
action: 修改 start.py：--prod 分支改为调用 prod_runner（直接导入 prod_runner 的 main，或等价执行其监督逻辑），并透传 --check / --workers；start_production_optimized.py 保持现有 shim（已转 --prod）不改动；确保 --dev / --backend-only / --frontend-only 行为不变。
loop: until 校验通过
max_iterations: 3
verify:
  - type: shell
    command: python start.py --prod --check
  - type: shell
    command: python start.py --help
gate: auto

- [x] **Step 3: 新增 Windows Nginx 配置**
action: 新建 config/nginx-windows.conf：listen 3000；root 指向 frontend-vite/dist；/assets/ 设一年缓存、/static/ 设缓存头、gzip on；location / 做 SPA fallback（try_files ... /index.html）；proxy /api/、/ws/（含 WebSocket upgrade）、/static/ 至 http://127.0.0.1:5002；client_max_body_size 100m；server_tokens off。参考 config/nginx.conf 的 server 块语义，但上游地址改为 127.0.0.1:5002（而非容器服务名 app:5002）。
loop: false
verify:
  - type: artifact
    path: config/nginx-windows.conf
    assert:
      kind: exists
gate: auto

- [x] **Step 4: server_manager 新增「生产托管」面板**
action: 修改 server_manager.py：新增生产托管卡片/面板——(a) NSSM 检测（PATH 与 C:\nssm\nssm.exe 等常见路径）；(b) 操作按钮：安装服务（nssm install erp-prod 与 erp-arq，AppDirectory 指向项目根，AppStdout/AppStderr 重定向到 logs\erp-prod.log 与 logs\erp-arq.log，Start=SERVICE_AUTO_START，AppExit Default Restart，AppRestartDelay 5000，AppEnvironmentExtra 注入 UVICORN_WORKERS=GUI 下拉所选值，默认 4）、卸载服务（nssm remove <name> confirm）、启动/停止/重启服务（nssm start/stop/restart <name>）、打开日志目录；(c) 状态区：读取 logs/prod_runner.json 与 sc query erp-prod/erp-arq，展示后端/ARQ/前端/Redis 状态、PID 与健康；(d) 将 dual_prod 手动模式的后端命令对齐多 worker（追加 --workers {UVICORN_WORKERS} --no-access-log --proxy-headers），避免手动模式仍是单进程误导。复用现有暗色 UI 组件（RoundedButton/StatusDot/日志区）。
loop: until 校验通过
max_iterations: 3
verify:
  - type: shell
    command: python -m py_compile server_manager.py
  - type: shell
    command: python -c "import server_manager; print('import ok')"
gate: auto

- [x] **Step 5: 纠偏部署文档与 .env**
action: 修改 deploy-windows.ps1：删除/更正 --loop uvloop（Windows 无效）与 Celery worker/beat 段落，改为多 worker uvicorn（--workers ${UVICORN_WORKERS} --http httptools --proxy-headers --no-access-log）与 ARQ worker（python -m arq fastapi_app.core.arq_app.WorkerSettings），并补 NSSM 注册/卸载步骤。修改 .env.example：新增 UVICORN_WORKERS=4 及注释（8GB 内存默认 4，内存紧张可 2）。修改 restart_backend.py：uvicorn 调用改为多 worker（python -m uvicorn ... --workers {UVICORN_WORKERS}），文件头补一行说明指向 server_manager 生产托管。不改动其它文档。
loop: false
verify:
  - type: shell
    command: findstr UVICORN_WORKERS .env.example
gate: auto

- [x] **Step 6: 后端回归测试 + 前端构建**
action: 运行 gated 测试套件（pytest tests fastapi_app/tests --ignore=tests/qa --ignore=tests/e2e --ignore=tests/stress --ignore=tests/performance -m "not flask_legacy" -q）；前端执行 npm --prefix frontend-vite run build（确保 dist 产物存在，供 Nginx/vite 托管与类型检查）。
loop: until 全部通过
max_iterations: 3
verify:
  - type: shell
    command: pytest tests fastapi_app/tests --ignore=tests/qa --ignore=tests/e2e --ignore=tests/stress --ignore=tests/performance -m "not flask_legacy" -q
  - type: shell
    command: npm --prefix frontend-vite run build
gate: auto

- [x] **Step 7: 端到端验证与 Windows 服务安装**
action: 先停止旧进程并清理端口占用（5002/3000）；以生产方式启动（python start.py --prod）确认多 worker uvicorn 生效（任务管理器/netstat 中 worker 数≥配置）、/api/health 200、前端 http://192.168.0.95:3000 可登录、/ws 通知可用；随后在 server_manager「生产托管」面板安装 Windows 服务（erp-prod + erp-arq，开机自启、崩溃重启），服务启动后验证 sc query 为 RUNNING、手动杀掉 uvicorn 主进程后能自动重启、logs/prod_runner.json 状态与 GUI 展示一致。
loop: false
verify:
  - type: human-review
    check: 多 worker 生效、健康检查通过、Windows 服务自启与崩溃自愈按预期，GUI 生产托管面板状态展示正确
gate: human
