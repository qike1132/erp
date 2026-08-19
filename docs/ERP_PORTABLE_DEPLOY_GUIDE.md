# ERP 独立安装目录 + 设置目录 部署指南

> 目的：把本机 ERP 运行环境（Python 3.13 + 全部依赖）整理成 **独立安装目录**（代码 + 运行时）与 **设置目录**（环境相关配置）分离的可移植包，在新服务器（192.168.1.97）上从安装目录部署，无需在新服务器联网安装 Python 依赖。

---

## 0. 本机环境实测结论（2026-08-18）

| 项 | 值 |
|----|----|
| Python 版本 | **3.13.13**（`C:\Users\Administrator\AppData\Local\Programs\Python\Python313`） |
| site-packages 包总数 | 555 个（约 1.3 GB） |
| base.txt 直接依赖 | 35 个，其中 **34 个已安装**，`opentelemetry*` 系列缺失 |
| opentelemetry 影响 | **无**（`telemetry.py` 全量 `try/except ImportError` 容错，未设 `OTEL_ENABLED=true` 时完全不加载） |
| `.pth` 绝对路径 | 无（可安全整体复制 site-packages） |

> **结论**：Python 安装目录可整体复制为"便携运行时"，新服务器**无需安装 Python、无需联网 pip install**。

---

## 1. 目录结构规划

```
D:\erp_portable\                        ← 便携包根（本机构建产物）
├── runtime\                            └── ① 运行时（独立安装目录 · 只读）
│   └── python313\                        完整 Python 3.13.13（含全部 site-packages）
│       ├── python.exe / python313.dll / DLLs / Lib / Scripts
│       └── Lib\site-packages\            555 个已装依赖
│
├── app\                                └── ② 应用代码（独立安装目录 · 只读）
│   ├── fastapi_app\                     后端源码
│   ├── frontend-vite\dist\              前端构建产物
│   ├── migrations\                      Alembic 迁移脚本
│   ├── scripts\                         工具脚本
│   ├── static\                          上传/导出/发布文件（业务数据）
│   ├── requirements\                    依赖清单
│   └── start.py / server_manager.py     启动入口
│
├── settings\                           └── ③ 设置目录（环境相关 · 部署时合并到 D:\erp_system）
│   ├── .env                            环境变量（DB/Redis/密钥/ALLOWED_HOSTS）
│   ├── jwt\private.pem + public.pem    JWT RS256 密钥对
│   ├── nginx-windows.conf              Nginx 前端托管 + 反代配置
│   ├── redis.production.conf            Redis 缓存实例(6379)
│   ├── redis-broker.conf                Redis ARQ 队列实例(6380)
│   ├── security-headers.conf            Nginx 安全响应头
│   └── pgbouncer\                       PgBouncer（可选）
│
├── deploy\
│   ├── install_on_target.ps1           ← 新服务器部署脚本（见 §5）
│   └── README.txt                       部署说明
│
└── manifest.txt                         构建清单（SHA256 校验）
```

### 目标机部署后的最终布局（路径必须为 `D:\erp_system`）

```
D:\erp_system\
├── runtime\python313\     ← 从包内 runtime\ 复制（Python + 依赖）
├── fastapi_app\           ← 从包内 app\ 复制
├── frontend-vite\dist\    ← 从包内 app\ 复制
├── migrations\ scripts\ static\ requirements\
├── config\jwt\            ← 从包内 settings\ 复制（Nginx/Redis 配置）
├── .env                   ← 从包内 settings\.env 复制（自动追加新服务器 IP）
└── server_manager.py / start.py
```

> **路径约束**：`config\nginx-windows.conf`、`.env`、`server_manager.py`、`fastapi_app\core\prod_runner.py` 中存在 150+ 处 `D:/erp_system` 绝对路径硬编码。**因此目标机安装目录必须保持 `D:\erp_system`**，否则需全局替换路径（不建议）。

---

## 2. 需要包含的依赖

| 类别 | 内容 | 说明 |
|------|------|------|
| **运行时** | `runtime\python313\` | 完整 Python 3.13.13 + site-packages（555 包），覆盖 base.txt 全部 35 个直接依赖 |
| **可选补装** | `requirements\base.txt` | 如需启用 OpenTelemetry，部署后 `runtime\python313\python.exe -m pip install -r requirements\base.txt`（会补齐 opentelemetry 系列） |
| **外部软件** | PostgreSQL 16 / Redis / Nginx / NSSM | 不随便携包传输，需在新服务器单独安装（见 §4.1） |

> 本机 `Scripts\` 含 88 个命令入口（uvicorn/alembic/arq 等），随运行时整体复制，无需重建。

---

## 3. 需要包含的配置文件

| 文件 | 归属 | 作用 |
|------|------|------|
| `.env` | settings\ | 全部运行参数（DB/Redis 密码、SECRET_KEY、JWT 路径、ALLOWED_HOSTS） |
| `jwt\private.pem` `public.pem` | settings\ | RS256 签名密钥，丢失后全部令牌失效 |
| `nginx-windows.conf` | settings\ | 前端托管 + `/api` `/ws` `/static` 反代（含绝对路径） |
| `redis.production.conf` `redis-broker.conf` | settings\ | 双 Redis 实例配置模板 |
| `security-headers.conf` | settings\ | 被 nginx-windows.conf include |
| `pgbouncer\` | settings\ | 连接池（本机未启用，可选带） |
| `requirements\*.txt` | app\ | 依赖清单（审计/补装用） |

**不需要打包**：`node_modules`、`.git`、`logs`、`temp`、`build`、`evidence`、`__pycache__`、`*.pyc`。

---

## 4. 环境变量的设置方式

项目通过 `.env` + `load_dotenv`（`fastapi_app/core/config.py` 顶部）+ NSSM 环境注入三层生效，**无需修改 Windows 系统环境变量**。

### 4.1 `.env`（部署时由脚本合并）

| 变量 | 部署时动作 |
|------|-----------|
| `DB_HOST/PORT/USER/NAME/PASSWORD` | 保持源值；目标机 `erp_app` 角色密码与 `.env` 一致 |
| `REDIS_PASSWORD` | 保持源值；同时注入两个 Redis 实例 `requirepass` |
| `SECRET_KEY` | 保持源值（新服务器沿用，已签发 JWT 不断签） |
| `JWT_PRIVATE_KEY_PATH` / `PUBLIC_KEY_PATH` | 保持 `d:/erp_system/config/jwt/*.pem`（路径不变） |
| `ALLOWED_HOSTS` | 脚本自动追加 `192.168.1.97` |
| `CORS_ORIGINS` | 脚本自动追加 `http://192.168.1.97:3000` |
| `ASYNC_DATABASE_REPLICA_URL` | 脚本自动注释（只读副本 5433 不迁移，应用回退主库） |

### 4.2 NSSM 服务环境注入（脚本自动设置）

```powershell
AppEnvironmentExtra="APP_ENV=production FASTAPI_DEBUG=false PYTHONPATH=D:\erp_system PYTHONUTF8=1 PYTHONUNBUFFERED=1 UVICORN_WORKERS=4"
```

### 4.3 运行时命令示例（新服务器）

```powershell
# 后端启动（直接用便携运行时，无需系统 PATH 有 python）
D:\erp_system\runtime\python313\python.exe -m fastapi_app.core.prod_runner --no-arq
# ARQ Worker
D:\erp_system\runtime\python313\python.exe -m arq fastapi_app.core.arq_app.WorkerSettings
```

---

## 5. 新服务器部署与运行完整步骤

### 5.0 前置：安装外部软件（一次性）

| 软件 | 安装要求 | 备注 |
|------|---------|------|
| PostgreSQL 16 | 默认 `C:\Program Files\PostgreSQL\16` | **记录 postgres 超管密码** |
| Redis (tporadowski) | 解压到 `C:\Redis\redis-server.exe` | 支持 `--service-install` |
| Nginx for Windows | 解压到 `C:\nginx\nginx.exe` | `prod_runner` 按固定候选路径探测 |
| NSSM | 放到 `C:\nssm\nssm.exe` | `server_manager` 按固定候选路径探测 |

### 5.1 传输便携包

将 `D:\erp_portable\` 整个复制到新服务器（如 `D:\migration_in\erp_portable\`）。

### 5.2 执行部署脚本（管理员 PowerShell）

```powershell
powershell -ExecutionPolicy Bypass -File D:\migration_in\erp_portable\deploy\install_on_target.ps1 `
    -PackageDir "D:\migration_in\erp_portable" `
    -PgSuperPassword "postgres 超管密码" `
    -NewServerIP "192.168.1.97"
```

脚本自动完成：

```
[1/9] 环境自检      外部软件(PG/Redis/Nginx/NSSM) + 便携运行时 python.exe
[2/9] 停止旧服务    erp-prod / erp-arq（若存在）
[3/9] 复制安装目录  app\ → D:\erp_system，runtime\ → D:\erp_system\runtime
[4/9] 合并设置      settings\ → D:\erp_system（.env/jwt/nginx/redis）
[5/9] 恢复数据库    建 erp_app 角色 + erp_system 库 → pg_restore（dump 可选）
[6/9] 更新 .env     ALLOWED_HOSTS/CORS 追加新 IP；注释副本
[7/9] 配置 Redis    生成部署 conf + requirepass + 双实例服务
[8/9] 注册服务      NSSM: erp-prod / erp-arq（指向便携运行时 python.exe）
[9/9] 启动并验证    /api/health + 前端 3000 + 库表计数 + Redis ping
```

### 5.3 日常启动（新服务器）

- **开机自启**：`erp-prod` + `erp-arq` 为自动启动的 NSSM 服务，Redis/PostgreSQL 亦自动启动。
- **手动启动**：`D:\erp_system\runtime\python313\python.exe -m fastapi_app.core.prod_runner`（前端 Nginx 由 prod_runner 拉起）。
- **GUI 管理**：`D:\erp_system\server_manager.py`（或打包的 `ERP_System.exe`），Python 环境自动探测 `runtime\python313` 需在 `server_manager.py` 的 `_get_python_executable` 候选路径中追加该目录（见 §6 注意事项）。

### 5.4 验证清单

- [ ] 浏览器访问 `http://192.168.1.97:3000`，admin 登录
- [ ] 抽查业务数据与源服务器一致
- [ ] 上传文件 → `static\uploads\` 落盘且可预览
- [ ] 触发报表导出 → `logs\erp-arq.log` 有执行记录
- [ ] 重启服务器 → 全部服务自动恢复
- [ ] `logs\prod_runner.json` → `"ready": true`

---

## 6. 注意事项

1. **路径保持 `D:\erp_system`**：150+ 处硬编码绝对路径，换路径必须全局替换，风险高、不建议。
2. **Python 版本一致性**：便携运行时直接复制，**新服务器不需要装 Python**。若未来要升级 Python，重新构建便携包即可，依赖随之更新。
3. **opentelemetry 缺失**：如需链路追踪，部署后补装 `requirements/base.txt`（离线场景可将 wheels 一并打入包内）。
4. **回滚**：源服务器在新服务器验证通过前不要停机。
5. **安全**：便携包含 `.env` 与 JWT 私钥，传输务必加密；部署后建议更新数据库/Redis 密码并同步 `.env`。
6. **server_manager 探测路径**：若使用 GUI 管理器，需将 `runtime\python313` 加入 `_get_python_executable()` 的 venv 候选列表（部署脚本已自动处理 NSSM，GUI 需手工适配）。

---

## 7. 相关文件

| 文件 | 作用 |
|------|------|
| `scripts/migrate/build_portable.ps1` | 本机构建便携包（§1 结构 + 自检） |
| `scripts/migrate/install_on_target.ps1` | 新服务器一键部署（§5.2） |
| `docs/ERP_MIGRATION_GUIDE.md` | 整机迁移方案（全量版，含旧式 pip 安装路径） |
