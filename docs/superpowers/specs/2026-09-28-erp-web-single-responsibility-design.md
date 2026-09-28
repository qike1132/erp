# 设计:消除双层守护 —— 拆出 erp-web 服务,prod_runner 只管 uvicorn

- 日期:2026-09-28
- 状态:已获用户批准(方案 1 全量 + 顺带 worker 数调整);2026-09-28 迭代自审后修订(补 QA 对抗测试处置、GUI 五处元组清单、轮转函数下沉、回滚禁用自启)
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

**保留(转为只观察不管理)**:每轮主循环 HTTP 探测 `http://127.0.0.1:3000/nginx-health`(带 `expect_substr='"service":"nginx"'`),结果写入状态文件 `frontend_ok` 字段;**探测失败只报告,绝不重启**。模块 docstring 与 `check()` 自检输出同步更新(删去 vite preview 回退相关文案)。

**轮转函数下沉**:`_rotate_file_copytruncate` 从 prod_runner 移至 `utils/log_rotation.py`(纯函数,无副作用),prod_runner 与 ARQ 日志轮转任务(§7)都从该处导入。

**状态文件新契约**:

```json
"frontend_type": "erp-web",
"services.frontend": {"type": "erp-web", "pid": null, "status": "external"}
```

`frontend_ok` 仍由探针得出,GUI 就绪徽章语义不变。GUI 的 `_svc_detail` 对 `external` 已有既定处理范式(ARQ `external` → 另走服务状态查询,见 §6.4)。

## 6. GUI(server_manager.py)改造

1. 新增常量 `_SVC_WEB = 'erp-web'`。硬编码 `(_SVC_API, _SVC_ARQ)` 元组的全部 5 处逐一加入 `_SVC_WEB`:
   - `_managed_service_pids`(受管 PID 枚举,P0-4 闸门);
   - `_stop_managed_services`(紧急停止/切换开发前的停服务);
   - `_service_cmd_sync`(停止/重启按钮流转);
   - `_start_services_flow` 的日志回灌 offsets 字典;
   - `_uninstall_services_flow`(卸载清单)。
2. `_install_services_flow` 增加 erp-web 注册(复用幂等 `_nssm_install`,env_extra 为空串;无需 Python,Application 直指 nginx.exe)。
3. **关键**:`_svc_pid('erp-web')` 返回 nginx master PID,由 `_managed_service_pids`/`_stop_managed_services` 的既有逻辑自动纳入排除集——dev 模式切换才能抢到 :3000,不重演历史端口互斗。
4. 生产状态卡片前端一行:仿 ARQ `external` 范式——`svcs.frontend.status == 'external'` 时改读 `erp-web` 服务状态(`_svc_state`/`_svc_pid`)而非信任快照;`frontend_ok` 探针结果作交叉验证(二者不一致时以服务状态为准,探针异常时告警)。
5. `_is_prod_runner_cmdline` / `_find_loose_prod_runner_pids` 保留(手工游离监督器清理仍需要)。

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

**回滚**:`nssm stop erp-web` → **`nssm set erp-web Start SERVICE_DISABLED`**(防止重启机器后 erp-web 与旧 prod_runner 拉起的 nginx 双跑互斗 :3000)→ `git revert` → `nssm restart erp-prod`(旧 prod_runner 重新拉起 nginx,原路恢复)。回滚步骤以注释写死在脚本里,演练时先走一遍。

## 10. 测试策略

- **删**:`fastapi_app/tests/test_prod_runner_frontend_failure.py`(测被删的 `_FrontendNginx`);
- **适配**:`fastapi_app/tests/test_qa_prod_stack_regression.py`——删 D2(`TestD2EnsureStarted`)、D4(`TestD4Spawn`)两个只测 `_FrontendNginx` 的类;D1 中 `test_frontend_alive_false_on_spa_fallback`、D3 中 `_prep_frontend` 相关用例随类删除;**保留** D7(重启真值表,后端守护不动)、D5(gzip)、D6(vite 配置一致性)、D1/D3 中不依赖 `_FrontendNginx` 的探针用例(`_http_ok` + `expect_substr` 行为不变);
- **保留**:`fastapi_app/tests/test_prod_runner_backend_restart.py`(后端守护不动);
- **新增**(TDD 先行):
  1. Supervisor 无 nginx 管理职责、无 `_FrontendNginx`/`_find_nginx`/`_cmd_vite_preview` 引用;
  2. 状态文件 `frontend_type == "erp-web"`、`services.frontend.status == "external"`、探针失败只报告不重启(状态不跳 crashed、不调 kill_tree);
  3. 迁移脚本 `-DryRun` 输出的 nssm 命令序列可断言;
  4. `utils/log_rotation.py` 的轮转函数单测(阈值以下不动、超阈值 copytruncate、保留 .1 副本、IO 失败不抛);
  5. ARQ 轮转任务注册断言(nginx 日志路径在 cron 任务列表中)。
- **用户手动验证**:GUI 五服务卡片、生产→开发→生产模式切换、迁移后四条硬判据(Server 头、无 @vite/client、无 /src/main.ts、gzip)。

## 11. 文档同步

- `docs/runbooks/service-lifecycle.md` §1 拓扑重写(5 服务)、§5 故障条目更新;
- `README_DEPLOY.txt` 服务清单更新;
- `CHANGELOG.md` 记录;
- 删除已被护栏拦死的 `restart_prod.ps1`(死脚本,继续误导人)。
