ERP 系统 - 部署说明（简版速查）
========================

> 📌 **本文件是速查卡，不是权威手册。** 完整手册（含**从零部署**全流程、五服务注册、
> 运行环境清单、备份恢复与红线）见仓库根 **`README.md`**。
> **两者若有冲突，一律以 `README.md` 为准**；发现不一致请改 `README.md` 并回来同步本文件。
> 本文件在 2026-10-06 做过一次口径对齐（管理器版本号、口令策略）。

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

运行环境（完整清单见 `README.md` §4.2）
========================================

必须是 64 位 Windows（10/11 或 Server 2019+）。核心组件与实测版本：

    Python 3.13.x（本机 3.13.13）      PostgreSQL 18（本机 18.3，含 pg_dump/pg_restore/psql）
    Node.js >= 22（本机 24.14.0）      nginx for Windows（本机 1.30.4）
    NSSM 2.24（C:\nssm\nssm.exe）      Redis for Windows（缓存 6379 + broker 6380 两实例）
    OpenSSL 3.x                        VC++ 2015-2022 x64 运行库

⚠️ 三个容易漏的坑（都能让系统"看起来正常"却出错）：
1) PG 客户端工具：`pg_dump`/`psql` 默认**不在 PATH** 上，工具解析顺序是
   `PG_TOOLS_BIN` → PATH → 三个约定目录（`C:\Program Files\PostgreSQL\*\bin`、
   `D:\PostgreSQL\bin`、`C:\PostgreSQL\bin`）。装到别处又不设 `PG_TOOLS_BIN`，
   备份会**静默降级为 JSON 导出**。
2) 生产服务固定指向 `.venv\Scripts\python.exe`；重建虚拟环境后必须重跑
   管理器「安装服务」或手工重设服务 Application。
3) **OCR 可选依赖**：`requirements/ocr.txt` 在依赖清单里写作"可选"，但**不装 =
   粘贴识别 / PDF 出货单识别整块不可用**（端点返回 503 并附安装命令）。
   2026-10-08 的生产部署就漏装过它，用户当时只看到「服务器内部错误」。
   自检：`.\.venv\Scripts\python.exe -c "import numpy, cv2, rapidocr, onnxruntime, fitz"`。
   完整依赖检查单见 `README.md` §4.6。

日常启停 / 切换运行模式
==========================

**必须用管理员权限的「ERP服务器管理器」GUI**（`server_manager.py`；版本号唯一真源是
   `server_manager/constants.py` 的 `_VERSION`，当前 **v5.35**）。

⛔ 非提权 shell 下没有任何 CLI 路径能重启 `erp-prod`（`nssm` / `sc` / `Stop-Service` /
   `taskkill` 全部因 ACL 拒绝访问）。这是 Windows ACL 边界，不是沙箱限制。
   完整实测记录与提权边界见 `docs/runbooks/service-lifecycle.md` —— 操作前请先读它。

管理员账号
============

- 用户名：`admin`
- 初始密码由部署方设定，**本文件不承载任何凭据**；
- 密码策略（`utils/password_validator.py`，MIN_LENGTH = 6）：**至少 6 位**，
  且**必须同时包含大写字母、小写字母和数字**（弱口令黑名单只拒最明显者，
  `123456` 按业务要求放行）；
- 忘记密码时用脚本重置（该脚本禁止硬编码明文）：

      $env:NEW_ADMIN_PASSWORD='<至少6位且含大小写字母与数字>'; python scripts/reset_admin_password.py
      python scripts/reset_admin_password.py --password <至少6位且含大小写字母与数字>

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
- 改完配置跑一次漂移检查：`python scripts/ops/check_env_drift.py`（注意：不带 `--ci`
  的全量口径还会比对 `.env` 与两份 `.env.production`，当前有存量缺口，见 `README.md` 附录 A.1）。

相关文档
==========

| 主题 | 位置 |
|---|---|
| **完整部署与运维手册（权威）** | `README.md` |
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

Q: 定时备份跑完却没有新鲜产物？
A: 先确认 `PG_TOOLS_BIN`/pg_dump 可达（否则会降级为 JSON 导出），
   并注意 `backup_schedule.last_status` 是死字段（永远显示 running），
   判断依据是 `backups/` 下产物的时间戳。
