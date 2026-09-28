# 设计:消除双层守护 —— 拆出 erp-web 服务,prod_runner 只管 uvicorn

- 日期:2026-09-28
- 状态:已获用户批准(方案 1 全量 + 顺带 worker 数调整)
- 范围:生产编排重构(Windows / NSSM / 本机即生产 `192.168.0.95`)

## 1. 目标与非目标

**目标**:每个 NSSM 服务职责单一——新增 `erp-web` 只管 nginx,`erp-prod` 内的 `prod_runner` 瘦身为只守护 uvicorn。重启静态资源不再惊动 API;nginx 的问题不再连累后端监督器(历史事故:nginx spawn 阻塞主循环 → NSSM 反复重启监督器 → 全站每 ~35s 断连)。

**非目标**:备份可观测性(独立高优任务);容器化;`prod_runner` 退避逻辑重构;GUI 视觉改造。

## 2. 现状(实测 2026-09-28)

```
services.exe
 ├─ nssm (erp-redis)         → redis-server :6379
 ├─ nssm (erp-redis-broker)  → redis-server :6380
 ├─ nssm (erp-arq)           → arq worker(定时备份唯一调度者)
 └─ nssm (erp-prod)          → prod_runner --no-arq
                              ├─ uvicorn :5002 (UVICORN_WORKERS=8)
                              └─ nginx :3000 (worker_processes auto = 12 进程)
```

病灶(均有事故记录或实测依据):

1. `prod_runner` 同时管理生命周期不同的 nginx(无状态静态)与 uvicorn(有状态 API),一方故障连累另一方;
2. 监督器"僵而不死"时 NSSM 感知不到(`AppExit=Restart` 只看退出码);
3. GUI(`server_manager.py:79`)深耦合 `prod_runner.json`,但已确认 GUI 可同步改造。

机器:6 物理核 / 12 逻辑核 / 15.4GB RAM(已用 68.7%)。当前 20 个服务进程(nginx×13、python×12 含解释器)对 6 核过订阅。

## 3. 目标拓扑

```
services.exe
 ├─ nssm (erp-redis)         :6379  不变
 ├─ nssm (erp-redis-broker)  :6380  不变
 ├─ nssm (erp-arq)                  不变
 ├─ nssm (erp-web)     ★新增  nginx.exe :3000 — AppExit=Restart
 └─ nssm (erp-prod)           prod_runner(瘦身后) → uvicorn :5002
```

NSSM 用 Job Object 托管进程树——今天 `nssm stop erp-prod` 就能干净杀掉整棵树,故 NSSM 直管 `nginx.exe` 不存在孤儿 worker 问题(那是绕过 NSSM 手工击杀才发生的)。

## 4. erp-web 服务定义

| 项 | 值 |
|---|---|
| Application | `C:\nginx\nginx.exe` |
| AppParameters | `-p D:\erp_system -c D:\erp_system\config\nginx-windows.conf -e D:\erp_system\logs\nginx-error.log` |
| AppDirectory | `D:\erp_system` |
| AppExit / AppRestartDelay | `Default Restart` / `5000` |
| Start | `SERVICE_AUTO_START` |
| DependOnService | 无(nginx 反代上游未起只 502,静态照常;比现状"先起后端才起 nginx,期间 :3000 全不通"更好) |
| AppEnvironmentExtra | 空 |
| AppStdout/AppStderr | NSSM 接管 nginx stdout(基本无输出);nginx 自身日志仍在 `logs/nginx-access.log` / `logs/nginx-error.log`(conf 内绝对路径) |

## 5. prod_runner 瘦身

**删除**(约 220 行):

- `_FrontendNginx` 整个类(含 `_taskkill_project_nginx`、pid 文件定向、spawn 日志、`_dump_error_log_tail`、`_ensure_started`);
- `_find_nginx` / `_NGINX_CANDIDATES`;
- `_cmd_vite_preview` 与 Supervisor 的 vite preview 回退分支;
- 陈旧备份文件 `fastapi_app/core/prod_runner.py.bak_ipv6`。

**保留(转为只观察不管理)**:每轮主循环 HTTP 探测 `http://127.0.0.1:3000/nginx-health`(带 `expect_substr='"service":"nginx"'`),结果写入状态文件 `frontend_ok` 字段;**探测失败只报告,绝不重启**。模块 docstring 更新职责描述。

**状态文件新契约**:

```json
"frontend_type": "erp-web",
"services.frontend": {"type": "erp-web", "pid": null, "status": "external"}
```

`frontend_ok` 仍由探针得出,GUI 就绪徽章语义不变。

## 6. GUI(server_manager.py)改造

1. 新增常量 `_SVC_WEB = 'erp-web'`;所有迭代 `(_SVC_API, _SVC_ARQ)` 的流转(启动/停止/重启/安装/卸载/日志回灌 offset)加入 `_SVC_WEB`;
2. `_install_services_flow` 增加 erp-web 注册(复用幂等 `_nssm_install`,env_extra 为空串);
3. **关键**:切换开发模式的"停生产"路径与 `_release_ports` 的受管 PID 排除集必须涵盖 erp-web 的 nginx 进程——否则 dev 模式抢不到 :3000,重演历史端口互斗;
4. 生产状态卡片前端一行改读 `erp-web` 服务状态 + Server 头探测,`prod_runner.json` 的 `frontend_ok` 作交叉验证;
5. `_is_prod_runner_cmdline` / `_find_loose_prod_runner_pids` 保留(手工游离监督器清理仍需要)。

GUI 无测试基建,由用户在实机验证(交付清单附逐项验证步骤)。

## 7. nginx 日志轮转归属

`prod_runner` 不再管 nginx 后,`nginx-access.log`(现 8.2MB)/`nginx-error.log` 轮转出现真空。方案:复用现有 `_rotate_file_copytruncate` 函数,挂进 ARQ worker 已有的每日 cron(阈值 100MB)。ARQ 停摆后果仅为"暂不轮转"——按当前增速数月 8MB,一年不满盘,优雅降级。

## 8. 顺带项(已批准纳入)

1. `config/nginx-windows.conf`:`worker_processes auto` → **2**(静态服务足够);
2. `.env`:`UVICORN_WORKERS` **8 → 4**(6 物理核)。

## 9. 迁移与回滚(一次维护窗口,用户在管理员 PowerShell 执行)

新增 `scripts/migrate_erp_web.ps1`(支持 `-DryRun`,幂等):

```
1. 部署代码(main 即生效)
2. 注册 erp-web(stopped,幂等可重跑)
3. nssm stop erp-prod    → Job Object 干净杀旧树(uvicorn+nginx)
4. nssm start erp-web    → 验证 :3000 Server:nginx + /nginx-health 响应体
5. nssm start erp-prod   → 验证 /api/health 200
6. python scripts/diag/runtime_mode_probe.py 打印终态判定
```

**回滚**:`nssm stop erp-web` → `git revert` → `nssm restart erp-prod`(旧 prod_runner 重新拉起 nginx,原路恢复)。回滚步骤以注释写死在脚本里,演练时先走一遍。

## 10. 测试策略

- **删**:`fastapi_app/tests/test_prod_runner_frontend_failure.py`(测被删的 `_FrontendNginx`);
- **保留**:`fastapi_app/tests/test_prod_runner_backend_restart.py`(后端守护不动);
- **新增**(TDD 先行):
  1. Supervisor 无 nginx 管理职责、无 `_FrontendNginx`/`_find_nginx` 引用;
  2. 状态文件 `frontend_type == "erp-web"`、探针失败只报告不重启(状态不跳 crashed、不调 kill_tree);
  3. 迁移脚本 `-DryRun` 输出的 nssm 命令序列可断言。
- **用户手动验证**:GUI 五服务卡片、生产→开发→生产模式切换、迁移后四条硬判据(Server 头、无 @vite/client、无 /src/main.ts、gzip)。

## 11. 文档同步

- `docs/runbooks/service-lifecycle.md` §1 拓扑重写(5 服务)、§5 故障条目更新;
- `README_DEPLOY.txt` 服务清单更新;
- `CHANGELOG.md` 记录;
- 删除已被护栏拦死的 `restart_prod.ps1`(死脚本,继续误导人)。
