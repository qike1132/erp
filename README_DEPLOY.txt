ERP 系统 - 部署说明
========================

> ⚠️ 本文在 2026-09-18 整体重写。此前版本描述的是**已废弃的 Flask + PyInstaller
> 桌面单体部署**（`ERP_System.exe` / 端口 5003 / `admin123` / `templates/`），
> 与本机实际部署完全不符，且引用的 `EXE_PACKAGING_GUIDE.md`、`templates/` 实测不存在。
> 若你需要历史版本，请查 git 记录，不要按旧文档操作。

当前部署拓扑
==============

    nginx :3000  ──反代 /api /ws /static──▶  uvicorn :5002  (FastAPI)
     (erp-web 独立服务)                        (prod_runner 只守护后端)
                                                  │
                                                  ├─ PostgreSQL 18
                                                  └─ Redis (缓存 + ARQ broker)

- 对用户暴露的入口是 **nginx 的 3000 端口**（前端静态资源 + API 反代）；
- 后端 FastAPI 监听 **5002**，且生产绑定 `127.0.0.1`（不直接对外）；
- 五个 Windows 服务由 NSSM 托管：`erp-prod`（uvicorn）、`erp-web`（nginx）、
  `erp-arq`、`erp-redis`、`erp-redis-broker`；
- 前后端**启停解耦**：重启 `erp-prod` 不影响前端静态服务；
- 后端进程入口是 `python -m fastapi_app.core.prod_runner`，**不是 exe 单体**。

日常启停 / 切换运行模式
==========================

**必须用管理员权限的「ERP服务器管理器」GUI**（`server_manager.py`；版本号唯一真源是
   `server_manager/constants.py` 的 `_VERSION`，当前 **v5.33**）。

⛔ 非提权 shell 下没有任何 CLI 路径能重启 `erp-prod`（`nssm` / `sc` / `Stop-Service` /
   `taskkill` 全部因 ACL 拒绝访问）。这是 Windows ACL 边界，不是沙箱限制。
   完整实测记录与提权边界见 `docs/runbooks/service-lifecycle.md` —— 操作前请先读它。

管理员账号
============

- 用户名：`admin`
- 初始密码由部署方设定，**本文件不承载任何凭据**；
- 密码策略（`utils/password_validator.py`）：至少 8 位，且同时包含字母与数字；
- 忘记密码时用脚本重置（该脚本禁止硬编码明文）：

      $env:NEW_ADMIN_PASSWORD='<至少8位字母+数字>'; python scripts/reset_admin_password.py
      python scripts/reset_admin_password.py --password <至少8位字母+数字>

⚠️ 请勿在任何文档、脚本、工单或聊天记录里记录真实口令。

数据库与配置
==============

- 配置唯一真源是仓库根的 **`.env`**（`.env.example` 是模板，`.env.production.example`
  仅为示例——**不要**拿它覆盖 `.env`，其自身也带同样警示）。
- 数据库连接示例：

      DB_HOST=localhost
      DB_PORT=5432
      DB_USER=erp_app
      DB_PASSWORD=<your_password>
      DB_NAME=erp_system

- 结构变更走 Alembic 迁移（`migrations/`），**不要**用 `create_all` 代替迁移。

相关文档
==========

| 主题 | 位置 |
|---|---|
| 服务生命周期与模式切换（必读） | `docs/runbooks/service-lifecycle.md` |
| 后端说明与模块结构 | `fastapi_app/README.md` |
| 变更历史 | `CHANGELOG.md` |
| 事务边界规范 | `docs/TRANSACTION_BOUNDARY_GUIDE.md` |

常见问题
==========

Q: 页面打不开？
A: 先确认 nginx（3000）与 `erp-prod`（5002）都在运行；健康检查 `GET /api/health`。

Q: 数据库连接失败？
A: 检查 `.env` 的 DB_* 配置，以及 PostgreSQL 服务是否已启动。

Q: 定时备份没有执行？
A: 备份由 ARQ worker（`erp-arq`）驱动，确认该服务在线；备份健康度可查 `GET /api/v1/backup/health`。
