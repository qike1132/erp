# 滨发协同系统（binfa-erp）

内网部署的**生产 ERP**，覆盖采购中心、客户订单、库存、出货计划、生产排产、板房打样、皮套管理、来料登记、外协（湖北）、审批、报表、数据备份与系统管理。后端 FastAPI（全异步）+ PostgreSQL 18 + Redis/ARQ，前端 Vue 3 + TypeScript + Vite 7（PC 与移动端自适应），在 Windows 上以 **Nginx + NSSM 五服务** 形态运行。

> ⚠️ 本仓库的部署形态是 **Windows 原生内网部署**，不是容器部署，也不由 CI 直接发布。
> 本文档同时是**新服务器从零部署的完整操作手册**（见 [第 4 章](#4-在新服务器上完整部署生产)）。
> 动手前请先读 [第 11 章 安全边界与红线](#11-安全边界与红线)，那里列的操作会直接影响在用业务。

---

## 目录

| 章节 | 内容 |
|---|---|
| [1. 项目概览](#1-项目概览) | 功能模块、技术栈、仓库规模 |
| [2. 系统架构](#2-系统架构) | 拓扑、端口、五个 Windows 服务、目录职责 |
| [3. 快速开始（开发环境）](#3-快速开始开发环境) | 本机跑起来需要的最短路径 |
| [4. 在新服务器上完整部署（生产）](#4-在新服务器上完整部署生产) | **核心章节**：从裸机到验收的完整流程 |
| [5. 配置参考](#5-配置参考) | `.env` 关键键位、单一来源与漂移检查 |
| [6. 数据库与迁移](#6-数据库与迁移) | Alembic 约定、单 head、建库 |
| [7. 备份与恢复](#7-备份与恢复) | 调度、加密、恢复演练 |
| [8. 运维手册](#8-运维手册) | 启停、日志、巡检、故障排查 |
| [9. 质量门禁与测试](#9-质量门禁与测试) | 提交前必须跑的检查 |
| [10. API 与前端约定](#10-api-与前端约定) | 响应格式、鉴权、路由对齐 |
| [11. 安全边界与红线](#11-安全边界与红线) | 会打挂生产的操作清单 |
| [12. 文档导航](#12-文档导航) | 深挖某主题时去哪里找 |
| [附录 A. 质量与审计快照](#附录-a-质量与审计快照2026-10-03) | 最近一次完整审核的结论 |

---

## 1. 项目概览

### 1.1 业务模块

| 域 | 说明 | 后端端点前缀 |
|---|---|---|
| 采购中心 | 采购订单、供应商汇总、采购计划 | `/api/v1/purchase-center`、`/api/v1/plans` |
| 客户订单 | 订单 CRUD、订单批次、暂存订单、出货计划 | `/api/v1/orders`、`/api/v1/order-batch`、`/api/v1/staging-orders` |
| 库存 | 备货入库、出库、退货、盘点、库存告警 | `/api/v1/stock`、`/api/v1/staging-stockins`、`/api/v1/staging-stockouts` |
| 生产 | 排产计划、生产日报、生产汇总 | `/api/v1/production-plans`、`/api/v1/daily-production`、`/api/v1/production-summary` |
| 板房 | 按客户分类打样、版师管理 | `/api/v1/pattern-room`、`/api/v1/pattern-maker` |
| 皮套 | 主件/配件维护、出入库合一 | `/api/v1/cases` |
| 来料登记 | 面料/物料到货登记 | `/api/v1/material-registrations` |
| 外协 | 湖北外发订单与收发 | `/api/v1/outsource` |
| 审批 | 审批流与日志 | `/api/v1/approvals` |
| 报表 | 统计报表与导出 | `/api/v1/reports` |
| 备份 | 备份/恢复/演练/健康检查 | `/api/v1/backup` |
| 系统 | 认证、用户、权限、通知、仪表盘、监控 | `/api/v1/auth`、`/api/v1/users`、`/api/v1/permissions`、`/api/v1/notifications`、`/api/v1/dashboard`、`/api/v1/monitoring` |
| 导入 | Excel 批量导入、PDF 出货单 OCR 识别 | `/api/v1/batch`、`/api/v1/ocr-import` |
| 基础数据与运维 | 产品、客户、供应商、辅助接口、异步任务、死信队列、编号巡检 | `/api/v1/products`、`/api/v1/customers`、`/api/v1/suppliers`、`/api/v1/aux`、`/api/v1/tasks`、`/api/v1/dead-letter`、`/api/v1/numbering-audit` |

后端共 **34 个端点模块、369 个路由处理器**：32 个扁平模块（286 个 handler）+ `backup/`、`purchase_center/` 两个**聚合包**（83 个 handler，经各自 `__init__.py` 汇总）。`fastapi_app/api/v1/router.py` 以绝对导入全部挂载，34/34 均 `include_router`，**零孤儿**（AST + 调用图实测，见附录 A）。

### 1.2 技术栈

| 层 | 选型 | 版本（锁定于 requirements/） |
|---|---|---|
| 运行时 | Python | **3.13.x**（CI 与生产实测 3.13） |
| Web 框架 | FastAPI + Uvicorn（多 worker） | 0.137.1 / 0.46.0 |
| ORM | SQLAlchemy 2.0（asyncpg 异步驱动；Alembic 用 psycopg3 同步） | 2.0.49 / 0.31.0 / psycopg 3.3.3 |
| 数据库 | PostgreSQL | **18** |
| 迁移 | Alembic（单一 head，禁止夹带业务逻辑） | 1.16.0 |
| 缓存 / 队列 | Redis 5.3.1 + ARQ 0.28（双实例：6379 缓存 / 6380 broker） | — |
| 配置 | pydantic-settings 2.14.2（`.env` 单一来源） | — |
| 安全 | Argon2id 口令、JWT（HS256/RS256）、CSRF/CORS/TrustedHost/CSP、slowapi 限流 | — |
| 可观测性 | structlog、Prometheus `/metrics`、OpenTelemetry、Sentry | — |
| 前端 | Vue 3.5 + TypeScript 6 + Vite 7 + Pinia 3 + Vue Router 5 | Node **>= 22** |
| UI | PrimeVue 4 + reka-ui + Tailwind CSS 4 + ECharts 6 | — |
| 前端测试 | Vitest 4 + @vue/test-utils + jsdom（121 个测试文件） | — |
| 桌面壳 | NSSM 服务管理器（Tkinter，PyInstaller 打包为 `ERP服务器管理器_vX.Y.exe`） | 见 `server_manager/constants.py` |

仓库规模：后端 `fastapi_app/` + `utils/` **126,259 行 Python**；前端 `frontend-vite/src` **92,713 行** TS/Vue（`*.vue` 48,115 / `*.ts` 44,598，其中测试 21,416 行 → 不含测试 **71,297 行**）；Alembic 迁移 **102 个 revision / 4 个 root / 单 head**；后端测试 **301 个文件**（`tests/` 114 + `fastapi_app/tests/` 187）；前端 Vitest **121 个文件**。

---

## 2. 系统架构

### 2.1 运行拓扑（生产）

```text
浏览器 / 移动端 Capacitor
        │
        ▼
Nginx :3000（HTTP）/:443（自签 TLS）
   ├── root = frontend-vite/dist        静态资源 + SPA
   ├── /api、/static、/ws → 反代 127.0.0.1:5002
   └── /static/uploads → secure_link 限时签名（未签名 403 / 过期 410）
        │
        ▼
Uvicorn :5002（仅绑回环，多 worker，由 prod_runner 监督）
   ├── PostgreSQL 18 :5432
   └── Redis :6379（缓存/限流/Pub-Sub）+ :6380（ARQ broker）
        │
        ▼
ARQ worker（独立进程/服务 erp-arq）：定时备份、批量任务、cron、日志轮转兜底
```

### 2.2 端口

| 端口 | 用途 | 暴露范围 |
|---|---|---|
| 3000 | Nginx：前端静态 + API/WS 反代（**用户唯一入口**） | 局域网 |
| 443 | Nginx：自签内网 TLS（可选，与 3000 并行） | 局域网 |
| 5002 | FastAPI（uvicorn） | **仅 127.0.0.1**（禁止 0.0.0.0，见红线 §11） |
| 5432 | PostgreSQL | 仅本机（应用；只读副本可另开 5433） |
| 6379 | Redis 缓存实例 | 仅 127.0.0.1 |
| 6380 | Redis ARQ broker 实例 | 仅 127.0.0.1 |

### 2.3 五个 Windows 服务（NSSM 托管）

真源：`server_manager/constants.py`（`_SVC_ALL`）与机读快照 [config/nssm-services.json](config/nssm-services.json)。

| 服务 | 作用 | Application / 参数 | 依赖 |
|---|---|---|---|
| `erp-prod` | API 监督器（uvicorn `:5002`） | `.venv\python.exe -m fastapi_app.core.prod_runner --no-arq` | `erp-redis` |
| `erp-arq` | ARQ worker（定时备份/异步任务，独立进程） | `.venv\python.exe -m arq fastapi_app.core.arq_app.WorkerSettings` | `erp-redis-broker` |
| `erp-web` | Nginx 静态 + 反代 `:3000` | `C:\nginx\nginx.exe -p <项目根> -c config\nginx-windows.conf` | 无 |
| `erp-redis` | 缓存 Redis（`:6379`） | `C:\Redis\redis-server.exe C:\Redis\redis.windows-service.conf --requirepass <口令>` | 无 |
| `erp-redis-broker` | ARQ broker Redis（`:6380`） | `C:\Redis\redis-server.exe config\redis-broker.conf --requirepass <口令>` | 无 |

两个关键不变量（都有生产事故背景）：

- **`erp-arq` 必须依赖 `erp-redis-broker`**：否则开机 SCM 并行启动，ARQ 抢在 broker 之前连 6380 → 超时退出 → NSSM 5 秒重拉 → 无限重启，**备份与 cron 静默停摆**。
- **`erp-web` 与 `erp-prod` 启停解耦**：`prod_runner` 不再托管 nginx；重启后端不影响前端静态服务，反之亦然。`logs/prod_runner.json` 里 `arq.status = "external"` 是**正常设计**，不是故障。

### 2.4 目录职责

```text
fastapi_app/                 后端（FastAPI + SQLAlchemy async）
  api/v1/                    路由汇总 + 34 个端点模块（32 扁平 + 2 聚合包）
  core/                      配置/数据库/中间件/ARQ/prod_runner 监督器
  services/                  业务服务层（backup/ 含备份、加密、恢复、清理）
  shared_models/             纯 SQLAlchemy 2.0 ORM
  schemas/                   Pydantic 请求/响应模型
  tasks/                     ARQ 任务
  tests/                     后端测试（与 tests/ 一起被 pytest 收集）
frontend-vite/               前端（Vue 3 + TS + Vite 7，Node >= 22）
  src/                       PC 与 mobile 双路由、api 层、stores、views
  scripts/                   build/check 脚本（vite-build.mjs、对齐检查等）
migrations/versions/         Alembic 迁移（102 个，单一 head）
server_manager.py + server_manager/  NSSM 服务管理器（唯一生产启停通道）
scripts/                     运维与质量脚本（quality_gate.py、ops/、diag/、prod_audit/）
config/                      nginx / redis / nssm 快照 / TLS / jwt / pgbouncer（见 config/README.md）
docs/                        决策记录与 runbook；deliverables/ 是历史归档，不作为现行真相
tests/                       根级回归测试（与 fastapi_app/tests/ 并集运行）
backups/ logs/               运行期数据，不入库
_ops/credentials/            凭据存放处（已 gitignore，**永不入库**）
```

---

## 3. 快速开始（开发环境）

### 3.1 前置条件

- Windows（本仓库开发机即生产机，**手工起 uvicorn/vite dev 会与生产抢端口**，见 §11）
- Python 3.13 + Node >= 22
- 可用的 PostgreSQL 18 与 Redis（`.env` 指向开发库/测试库，**不要指向生产库**）

### 3.2 后端

```powershell
python -m venv .venv
.venv\Scripts\pip.exe install -r requirements/dev.txt        # 含 base + ruff/mypy（**回归测试另装 requirements/test.txt** —— pytest 不在 dev.txt 里）

Copy-Item .env.example .env                                   # 然后填 SECRET_KEY / DB_* / REDIS_*
.venv\Scripts\python.exe -m alembic -c migrations/alembic.ini upgrade head
.venv\Scripts\python.exe scripts\init_permissions.py          # 首次：初始化权限树

python start.py --dev          # 仅后端：uvicorn reload，127.0.0.1:5002
```

### 3.3 前端

```powershell
cd frontend-vite
npm ci
npm run dev                    # Vite dev server（本脚本默认 5173；vite.config 的 server.port 是 3000）
```

或 `python start.py --frontend-only`（以 `--web-port 3000` 启动，并对 `/api`、`/static`、`/ws` 做代理）。

> 端口口径：只有绕开 `start.py` 裸跑 `npm run dev` 时才会落在 5173。
> `python start.py --dev` **只启动后端**，前端按上面的命令另开一个终端。

### 3.4 开发入口

| 入口 | 地址 |
|---|---|
| 前端（vite / start.py --frontend-only） | `http://localhost:3000`（或 5173） |
| 后端 API | `http://127.0.0.1:5002/api/v1` |
| 交互式文档（**仅非生产**） | `http://127.0.0.1:5002/api/docs`、`/api/redoc` |
| 健康检查（开发/生产均可） | `http://127.0.0.1:5002/api/health`；生产经 nginx：`http://<主机>:3000/api/health` |

---

## 4. 在新服务器上完整部署（生产）

> 目标形态：**Windows 主机 + Nginx :3000 + Uvicorn :5002 + PostgreSQL 18 + 双 Redis + NSSM 五服务**。
> 本机（当前生产）参考路径：项目 `D:\erp_system`、Nginx `C:\nginx`、NSSM `C:\nssm`、Redis `C:\Redis`、PG 工具 `D:\PostgreSQL\bin`。
> 全流程约 2–4 小时（不含数据迁移）；每步都有验收命令，**不要跳步**。

### 4.0 步骤总览

```text
0) 前置检查      → 1) 安装基础软件      → 2) 获取代码
3) PostgreSQL 建库 → 4) Redis 双实例     → 5) Python 虚拟环境
6) 生成密钥/证书  → 7) 编写 .env         → 8) 迁移 + 初始化数据
9) 初始管理员     → 10) 构建前端         → 11) 配置 Nginx
12) 安装 5 个服务 → 13) 启动与验收       → 14) 备份调度与看门狗
15) 部署后检查清单 → 16) 升级与回滚流程
```

### 4.1 前置检查

- [ ] **管理员权限**（安装服务、写 `C:\` 目录、注册计划任务都需要）
- [ ] Windows 主机（本部署为原生 Windows，非容器），固定内网 IP
- [ ] 磁盘：项目 + 备份至少预留 **100 GB**（备份默认保留 30 天）
- [ ] 已确认 **3000 / 5002 / 5432 / 6379 / 6380 端口未被占用**
- [ ] 规划好项目路径：**强烈建议沿用 `D:\erp_system`**（全仓大量绝对路径按此写好：`config/nginx-windows.conf`、`config/nssm-services.json`、NSSM 参数。换盘符/目录时这些文件都要同步改，见 4.12）

### 4.2 安装基础软件（含路径约定）

| 组件 | 版本 | 安装位置 / 要求 |
|---|---|---|
| Python | **3.13.x** | 任意位置，之后用其创建项目 `.venv` |
| PostgreSQL | **18**（含客户端工具 pg_dump/pg_restore/psql） | 本机安装，服务建议以 NetworkService 运行 |
| Redis for Windows | 兼容 Windows 的 `redis-server.exe` | **`C:\Redis\` 或 `C:\Program Files\Redis\`**（管理器只在这两处查找） |
| Nginx for Windows | 官方 Windows 构建 | **`C:\nginx\`**（`nginx.exe` 与 `conf\mime.types` 需在此） |
| NSSM | **2.24** | **`C:\nssm\nssm.exe`**（不在 PATH，全部命令用绝对路径） |
| Node.js | **>= 22** | 构建前端用（也可在别处构建后拷贝 `dist`） |
| Git（可选但推荐） | 最新 | 拉代码与版本回滚 |

> 路径不是硬编码在 Python 代码里的：管理器与服务参数由 `_PROJECT_DIR` 推导；
> 但 `config/nginx-windows.conf` 的 `include` / `alias`、`config/nssm-services.json` 里的
> `D:\erp_system` 是**字面路径**，换路径必须替换。

### 4.3 获取代码与准备目录

```powershell
# 方式一：Git 克隆（推荐，便于回滚）
git clone git@github.com:qike1132/erp.git D:\erp_system

# 方式二：拷贝整包（含 .venv 时注意目标机的 Python 路径不同，建议重建）
```

```powershell
cd D:\erp_system
New-Item -ItemType Directory -Force _ops\credentials      # 凭据存放（已 gitignore）
New-Item -ItemType Directory -Force logs, backups         # 运行期目录（启动时也会自动建）
```

### 4.4 PostgreSQL：建库与账号

用超级用户（`psql -U postgres`）执行，**替换为强口令并存入 `_ops/credentials`**：

```sql
CREATE ROLE erp_app LOGIN PASSWORD '<强口令>';
CREATE DATABASE erp_system WITH OWNER = erp_app ENCODING = 'UTF8' TEMPLATE = template0;
```

- `pg_hba.conf`：对 `127.0.0.1/32` 使用 `scram-sha-256`；**不要**把 5432 暴露给局域网。
- 可选性能项：启用 `pg_stat_statements`（脚本 `scripts/database/pg_stat_statements_setup.sql`）。
- 结构与数据**全部**由 Alembic 迁移创建（4.9），不要手工建表，也不要用 `create_all` 代替迁移。

验收：`psql -h 127.0.0.1 -U erp_app -d erp_system -c "select 1"` 返回成功。

### 4.5 Redis：双实例（缓存 6379 + broker 6380）

`erp-redis`（缓存）与 `erp-redis-broker`（ARQ 队列）**必须分开**，避免缓存驱逐把排队任务清掉。

```powershell
# 1) 缓存实例配置：以仓库 config/redis.production.conf 为基准，落地到 C:\Redis
Copy-Item D:\erp_system\config\redis.production.conf C:\Redis\redis.windows-service.conf
#    该文件已是：bind 127.0.0.1 / port 6379 / maxmemory 512mb allkeys-lru / appendonly yes
#    口令【不要】写进配置文件 —— 由服务启动参数 --requirepass 注入（与 .env 一致）

# 2) broker 实例：直接使用仓库内配置（port 6380，队列专用，无 AOF）
#    D:\erp_system\config\redis-broker.conf

# 3) 注册两个 NSSM 服务（管理员 PowerShell）
C:\nssm\nssm.exe install erp-redis C:\Redis\redis-server.exe
C:\nssm\nssm.exe set erp-redis AppParameters "C:\Redis\redis.windows-service.conf --requirepass <REDIS_PASSWORD>"
C:\nssm\nssm.exe set erp-redis AppDirectory C:\Redis
C:\nssm\nssm.exe set erp-redis Start SERVICE_AUTO_START
C:\nssm\nssm.exe set erp-redis AppExit Default Restart

C:\nssm\nssm.exe install erp-redis-broker C:\Redis\redis-server.exe
C:\nssm\nssm.exe set erp-redis-broker AppParameters "D:\erp_system\config\redis-broker.conf --requirepass <REDIS_PASSWORD>"
C:\nssm\nssm.exe set erp-redis-broker AppDirectory C:\Redis
C:\nssm\nssm.exe set erp-redis-broker Start SERVICE_AUTO_START
C:\nssm\nssm.exe set erp-redis-broker AppExit Default Restart

C:\nssm\nssm.exe start erp-redis
C:\nssm\nssm.exe start erp-redis-broker
```

验收（两个实例都要通）：

```powershell
C:\Redis\redis-cli.exe -p 6379 -a <REDIS_PASSWORD> ping    # PONG
C:\Redis\redis-cli.exe -p 6380 -a <REDIS_PASSWORD> ping    # PONG
```

> 口令必须与 `.env` 的 `REDIS_PASSWORD` / `REDIS_CACHE_URL` / `REDIS_BROKER_URL` 一致；
> 轮换时三处同步改（Redis 服务参数、`.env`、必要时 `config/redis-broker.conf`）。

### 4.6 Python 虚拟环境与依赖

```powershell
cd D:\erp_system
python -m venv .venv
.\.venv\Scripts\python.exe -V                     # 应输出 3.13.x
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\pip.exe install -r requirements/base.txt     # 生产必需

# 按需追加：
#   requirements/test.txt       回归测试（pytest 等）
#   requirements/dev.txt        ruff / mypy / pre-commit（开发机）
#   requirements/ocr.txt        PDF 出货单 OCR（约 500MB，可选）
#   requirements/s3.txt         STORAGE_TYPE=s3 时（MinIO/S3）
#   requirements/migration.txt  仅迁移旧 bcrypt 口令哈希时
#   requirements/desktop.txt    打包 server_manager.exe 时
```

⚠️ **NSSM 服务固定指向 `.venv\Scripts\python.exe`**。换/重建虚拟环境后，必须重跑一次
管理器「安装服务」或手工重设服务 Application（否则服务仍指向旧解释器）。

### 4.7 生成密钥与证书

| 用途 | 生成命令 | 落点 |
|---|---|---|
| `SECRET_KEY` | `python -c "import secrets; print(secrets.token_hex(32))"` | `.env`（≥32 字符） |
| JWT RS256 密钥对 | `openssl genpkey -algorithm RSA -out config\jwt\private_v2.pem -pkeyopt rsa_keygen_bits:4096`<br>`openssl rsa -pubout -in config\jwt\private_v2.pem -out config\jwt\public_v2.pem` | `config/jwt/`（私钥已 gitignore，**永不入库**） |
| 上传 URL 签名 | `openssl rand -hex 32` | `.env` 的 `UPLOAD_URL_SIGNING_SECRET` + `config/uploads-signing.conf` |
| 备份加密口令 | `python -c "import secrets; print(secrets.token_urlsafe(32))"` | `.env` 的 `BACKUP_ENCRYPTION_PASSWORD`（**严禁留空**，见红线） |
| `/metrics` Token | `python -c "import secrets; print(secrets.token_urlsafe(32))"` | `.env` 的 `METRICS_BEARER_TOKEN` |
| 内网 TLS 自签证书（可选） | `config/tls/` 下**公钥证书已入库**（`ca.crt`/`server.crt`/`server.csr`/`server.ext`），**私钥 `*.key` 未入库**（`.gitignore`）；全新 clone 需自备 `server.key` 或重新签发 | `config/tls/` |

统一把上面所有真实值记录到 `_ops/credentials/`（受 ACL 保护、不入库）。

### 4.8 编写 `.env`（唯一运行时配置源）

```powershell
Copy-Item .env.example .env
```

**必填 / 生产必改键位**（完整清单见 [.env.example](.env.example) 的注释，逐条都有证据行）：

| 键 | 生产取值 | 说明 |
|---|---|---|
| `APP_ENV` | `production` | 生产自动关闭 `/api/docs`、启用强校验 |
| `SECRET_KEY` | 4.7 生成 | 不得使用默认值/占位符 |
| `DB_HOST/DB_PORT/DB_USER/DB_PASSWORD/DB_NAME` | `127.0.0.1 / 5432 / erp_app / <口令> / erp_system` | 连接池由 `UVICORN_WORKERS × DB_MAX_CONNECTIONS` 推导，不要另设池参数 |
| `REDIS_PASSWORD`、`REDIS_CACHE_URL`、`REDIS_BROKER_URL` | 与 4.5 一致 | broker 指向 `:6380`，cache 指向 `:6379` |
| `ALLOWED_HOSTS` | 具体 IP/域名，**禁止 `*`** | 含 `*` 生产拒绝启动 |
| `CORS_ORIGINS` | `http://<主机IP>:3000` | 不得含 `null` |
| `JWT_ALGORITHM` + `JWT_PRIVATE_KEY_PATH` + `JWT_PUBLIC_KEY_PATH` | `RS256` + 4.7 的两个路径 | RS256 模式下两个文件必须真实存在，否则启动失败 |
| `BACKUP_ENCRYPTION_ENABLED` + `BACKUP_ENCRYPTION_PASSWORD` | `true` + 强随机口令 | **口令为空会静默降级为不加密备份** |
| `BACKUP_ENCRYPTION_FALLBACK_TO_GENERATED` | `false`（保持） | 置 true 会产生「事后无法解密」的备份 |
| `METRICS_BEARER_TOKEN` | 4.7 生成 | 为空则 `/metrics` 返回 503（fail-closed） |
| `UPLOAD_URL_SIGNING_SECRET` | 4.7 生成 | 与 `config/uploads-signing.conf` 逐字一致，否则上传文件全部 403 |
| `STRICT_CONFIG_CHECK` | `true` | 生产启动强校验（备份加密、BACKUP_DIR 可写等） |
| `UVICORN_WORKERS` | 建议 4（8GB 内存） | 影响连接池分摊；重装服务后 NSSM 注入值优先于 `.env` |
| `STORAGE_TYPE` | `local`（默认） | 用 S3/MinIO 才改 `s3` 并装 `requirements/s3.txt` |
| `ALLOW_NEGATIVE_STOCK` | `false`（默认） | 置 true 只解除应用层闸门，DB 约束仍会拒绝 |

验收：

```powershell
.\.venv\Scripts\python.exe scripts\ops\check_env_drift.py       # [PASS]，模板 ↔ .env 无漂移
.\.venv\Scripts\python.exe start.py --prod --check             # prod_runner 环境自检（不起进程）
```

### 4.9 迁移与初始化数据

```powershell
cd D:\erp_system

# 1) 结构迁移（从仓库根执行，无需 cd，无需 PYTHONPATH）
.\.venv\Scripts\python.exe -m alembic -c migrations\alembic.ini upgrade head
.\.venv\Scripts\python.exe -m alembic -c migrations\alembic.ini heads   # 必须只有一个 head

# 2) 权限树初始化（迁移建表之后）
.\.venv\Scripts\python.exe scripts\init_permissions.py
```

> ⚠️ 迁移链包含历史 revision（如 `pg_standalone_006` 曾缺 `from alembic import op`，已修复）。
> **任何全新安装都会经过整条链**，因此迁移完成后的验收不能只看退出码，还要跑一次应用启动。

### 4.10 初始管理员账号（全新空白库）

有两条路，按场景选：

**A. 从现有部署迁移（推荐）**：从备份恢复 —— 用户、权限、业务数据一并带走。
恢复流程见 [第 7 章](#7-备份与恢复) 与 `docs/backup-restore/`。恢复后直接跳到 4.11。

**B. 全新空白库引导**：迁移后库内没有任何用户，需要手工建一次 `admin`（系统没有内置种子）：

```powershell
# 1) 生成 Argon2id 口令哈希（口令策略见 utils/password_validator.py：**≥6 位**，不强制字符类别）
.\.venv\Scripts\python.exe -c "from fastapi_app.core.security import hash_password; print(hash_password('<你的强密码>'))"
```

```sql
-- 2) 用 psql 写入（替换 <哈希>；create_time/update_time 显式给值）
INSERT INTO "user" (username, password, is_super, status, create_time, update_time)
VALUES ('admin', '<哈希>', true, true, now(), now());
```

- 登录后立刻在「用户管理」里建各岗位账号并按权限树授权；
- 忘记口令时：`python scripts/reset_admin_password.py --password <新密码>`（只重置、不创建）。

### 4.11 构建前端

```powershell
cd D:\erp_system\frontend-vite
npm ci
npm run build                 # vue-tsc -b && node scripts/vite-build.mjs → dist/
```

- 生产 `${VITE_API_URL}`/`VITE_WS_URL` 保持为空 = 同源相对路径，走 nginx 反代（`.env.production` 已如此）。
- 需要**原子替换**产物时用 `npm run build:atomic`（先构建到 `dist-new` 再替换 `dist`）。
  ⚠️ 若同机还在跑 vite dev server，watcher 会锁住目录导致替换 EPERM —— 先停开发模式，
  或把产物暂存到 **vite watch 树之外**再替换（详见 `docs/runbooks/service-lifecycle.md` §2）。
- `frontend-vite/vite.config.js` 是 `vue-tsc -b` 编译 `vite.config.ts` 的设计产物，
  **不要手改/删除**（有回归测试断言两者一致）。

验收：`frontend-vite\dist\index.html` 存在，且不含 `@vite/client`、`/src/main.ts`。

### 4.12 配置 Nginx

```powershell
# 1) 校验/替换 config\nginx-windows.conf 中的绝对路径（换过盘符时）
#    include C:/nginx/conf/mime.types;            ← Nginx 安装路径
#    include D:/erp_system/config/security-headers.conf;
#    alias   D:/erp_system/static/uploads/;
#    其余 root frontend-vite/dist 为相对项目根（-p 参数指定）

# 2) 上传签名密钥（必需，否则 /static/uploads/** 全部 403）
Copy-Item D:\erp_system\config\uploads-signing.conf.example D:\erp_system\config\uploads-signing.conf
#    将里面 <在此填入密钥...> 替换为与 .env 的 UPLOAD_URL_SIGNING_SECRET 逐字相同的值

# 3) TLS（可选）：config\tls\server.crt / server.key 就位；不启用就把 443 server 块删掉

# 4) 语法测试（重要：-p 指定项目根，而不是 nginx 目录）
C:\nginx\nginx.exe -p D:\erp_system -c D:\erp_system\config\nginx-windows.conf -t
```

- 配置里含网关层限流（当前 `limit_req_dry_run on`，只记日志不拒绝），观察 3–7 天无误伤后改为 `off` 正式生效。
- `server_tokens off`、安全响应头、`/metrics` 仅本机白名单均已配置。
- Windows 官方 nginx 无 upstream keepalive 模块，配置刻意不用 keepalive（用了会 400）。

**防火墙**：只放行入站 TCP **3000**（启用 443 时再加 **443**）；5002/5432/6379/6380 一律仅回环。

### 4.13 安装五个 Windows 服务

**首选：管理器 GUI**（`python server_manager.py` 或已打包的 `ERP服务器管理器_v5.34.exe`，需管理员）：

1. 打开管理器 → 「安装服务」→ 它按当前 Worker 数安装 **erp-prod / erp-arq / erp-web**，
   自动写入环境变量（`APP_ENV=production`、`PYTHONPATH`、`PYTHONUTF8`、`PYTHONUNBUFFERED`、`UVICORN_WORKERS`）
   与依赖（erp-prod→erp-redis）。
2. 两个 Redis 服务（`erp-redis` / `erp-redis-broker`）按 [4.5](#45-redis双实例缓存-6379--broker-6380) 手工注册
   （管理器只负责「启动」它们，不负责安装）。
3. 安装后可反复点击，幂等；会回读注册表核对服务指向是否与当前源码一致。

若不用 GUI，可手工 nssm 注册（要点，缺一不可）：

```powershell
C:\nssm\nssm.exe install erp-prod D:\erp_system\.venv\Scripts\python.exe
C:\nssm\nssm.exe set erp-prod AppParameters -m fastapi_app.core.prod_runner --no-arq
C:\nssm\nssm.exe set erp-prod AppDirectory D:\erp_system
C:\nssm\nssm.exe set erp-prod DependOnService erp-redis
# ⚠️ AppEnvironmentExtra 必须「一变量一元素」，整串塞进一个元素只会生效第一项（PYTHONUNBUFFERED 等静默失效）
C:\nssm\nssm.exe set erp-prod AppEnvironmentExtra APP_ENV=production FASTAPI_DEBUG=false PYTHONPATH=D:\erp_system PYTHONUTF8=1 PYTHONUNBUFFERED=1 UVICORN_WORKERS=4
C:\nssm\nssm.exe set erp-prod AppRotateFiles 1
C:\nssm\nssm.exe set erp-prod AppRotateBytes 10485760
C:\nssm\nssm.exe set erp-prod AppExit Default Restart
C:\nssm\nssm.exe set erp-prod Start SERVICE_AUTO_START

# erp-arq 同法，参数改为：-m arq fastapi_app.core.arq_app.WorkerSettings，依赖 erp-redis-broker
# erp-web（无 Python 环境变量、无依赖）：
C:\nssm\nssm.exe install erp-web C:\nginx\nginx.exe
C:\nssm\nssm.exe set erp-web AppParameters -p D:\erp_system -c D:\erp_system\config\nginx-windows.conf -e D:\erp_system\logs\nginx-error.log
C:\nssm\nssm.exe set erp-web AppDirectory D:\erp_system
```

完整字段可对照机读快照 [config/nssm-services.json](config/nssm-services.json)（灾备时按原形态重建五服务就是照它做）。

### 4.14 启动与验收

启动顺序（依赖已由 SCM 保证，手工起时按此顺序）：

```text
erp-redis → erp-redis-broker → erp-prod → erp-arq → erp-web
```

一键方式：管理员运行管理器 → 「生产模式」（内部：停开发 → 清端口 → 确认 Redis/broker → 起三服务）。

逐项验收（缺一不可）：

```powershell
# ① 后端健康
curl.exe -s --noproxy "*" http://127.0.0.1:5002/api/health        # 200 healthy

# ② 前端确由 Nginx 托管（四条判据）
curl.exe -s --noproxy "*" http://127.0.0.1:3000/ | findstr /c:"@vite/client"   # 应为空
curl.exe -s --noproxy "*" http://127.0.0.1:3000/ | findstr /c:"/src/main.ts"   # 应为空
curl.exe -sI --noproxy "*" http://127.0.0.1:3000/ | findstr /i "^server:"      # Server: nginx
curl.exe -sI --noproxy "*" -H "Accept-Encoding: gzip" "http://127.0.0.1:3000/api/v1/products/list?page=1&per_page=50" | findstr /i content-encoding

# ③ 用户入口健康
curl.exe -s --noproxy "*" http://127.0.0.1:3000/api/health

# ④ ARQ 在线（用哨兵键，不要只看进程）
#    broker 在 :6380；TTL arq:queue:health-check 应为 0..61，GET 内容含新鲜时间戳与 j_failed=0

# ⑤ 一条命令跑完全部运行模式检查
.\.venv\Scripts\python.exe scripts\diag\runtime_mode_probe.py
#    期望：verdict=prod (multi worker …)、frontend.is_production=true、arq.verdict=running

# ⑥ 监督器状态文件（原子写入）
Get-Content D:\erp_system\logs\prod_runner.json    # ready:true 且 frontend_ok:true
```

> `logs/prod_runner.json` 里的 `mode/status` 字段**不可单独作为凭据**（启动窗口内可能陈旧），
> 必须与上面的 HTTP/端口/ARQ 交叉验证；`started_at` 是「写盘时刻」不是进程启动时刻。

### 4.15 部署后检查清单

- [ ] 五服务 `Start=Auto`、当前 RUNNING；`erp-prod` 依赖 `erp-redis`、`erp-arq` 依赖 `erp-redis-broker`
- [ ] `logs/prod_runner.json`：`ready=true`、`frontend_ok=true`
- [ ] `runtime_mode_probe.py` 三项 verdict 全部符合预期
- [ ] 浏览器从**另一台局域网机器**访问 `http://<主机IP>:3000` 能登录并跑通一笔业务
- [ ] 上传一张图片 → 刷新仍可见（验证签名 URL 链路）
- [ ] 触发一次手动备份 → `backups/` 出现产物且时间戳新鲜
- [ ] 看门狗计划任务已注册且首轮检查通过
- [ ] 已把 `_ops/credentials/` 中的真实凭据登记进组织级密码管理（不落文档）

### 4.16 备份调度与看门狗

- **备份**：应用内「备份中心」配置计划（真源是 `backup_schedule` 表，`scheduler_poller` 每 5 分钟扫表并补跑）。
  调度依附 **erp-arq** —— ARQ 停摆 = 定时备份静默停摆（巡检必查 4.14④）。
  加密口令与 `BACKUP_ENCRYPTION_PASSWORD` 一致；恢复演练不要等到真出事才跑。
- **看门狗**（管理员）：

  ```powershell
  powershell -ExecutionPolicy Bypass -File D:\erp_system\scripts\ops\install_watchdog_task.ps1
  # 默认每 5 分钟以 SYSTEM 运行，检查：后端/就绪/ARQ/Web 入口/备份新鲜度/磁盘水位
  .\.venv\Scripts\python.exe scripts\ops\watchdog.py --no-alert   # 手工只检查不告警
  ```

  生产服务形态下把 `.env` 的 `WATCHDOG_EXPECT_SERVICES` 置 `true`（要求五服务 RUNNING）。
- **日志策略**：唯一权威是 `config/log_policy.json`（当前 **轮转 80MB / 保留 7 天 / 目录上限 300MB**），
  由 `prod_runner`（每 60s）、ARQ（每日 04:30）、桌面管理器（每 6h）三方共用。

### 4.17 升级与回滚（日常发布）

```powershell
# 升级
git pull
cd frontend-vite && npm ci && npm run build      # 生产机若跑 dev server 先停
cd ..
.\.venv\Scripts\python.exe -m alembic -c migrations\alembic.ini upgrade head
# 管理员：nssm restart erp-prod（代码生效）；erp-arq 有任务变更时一并重启

# 回滚
#  前端：换回上一份 dist（发布前先自备份 dist，build:atomic/swap-dist 成功后不留回滚副本）
#  后端：git checkout <上一个可用提交> + 重启 erp-prod
#  数据库：迁移只向前；需要回退结构时用 alembic downgrade <rev> 或从备份恢复（先评估数据丢失面）
```

---

## 5. 配置参考

### 5.1 `.env` 是唯一运行时配置源

| 文件 | 是否被加载 | 用途 |
|---|---|---|
| `.env` | **是（唯一）** | 权威配置（`load_dotenv(override=False)` + Settings env_file） |
| `.env.example` | 否 | 唯一权威模板，新增配置键必须先加这里 |
| `config/.env.production` | 否 | 灾备底稿（随加密备份包分发） |
| `.env.production`（根） | 否 | 人工参考件（只写占位） |

- 改配置：先改 `.env.example` → 再改 `.env` → `python scripts/ops/check_env_drift.py` 必须 PASS → 重启进程（只在启动时读一次）。
- **进程环境变量优先于 `.env`**：NSSM 注入的 `UVICORN_WORKERS` 会覆盖 `.env` 同名项。
- 生产启动强校验：`BACKUP_ENCRYPTION_PASSWORD` 缺失、`BACKUP_DIR` 不可写等会**直接拒绝启动**（排障可临时 `STRICT_CONFIG_CHECK=false`，修好必须改回）。

### 5.2 常用的可选开关

| 开关 | 默认 | 说明 |
|---|---|---|
| `RATE_LIMIT_ENABLED` | true | 关掉会同时让端点级限流失效，仅排障用 |
| `CACHE_L1_BROADCAST_ENABLED` | false | 多 worker 生产建议开（跨 worker 缓存失效广播） |
| `INVENTORY_RECONCILE_ENABLED` | false | 开启后注册每日 03:30 只读库存对账 cron |
| `ALLOW_NEGATIVE_STOCK` | false | 负库存业务开关（DB 兜底约束独立于它） |
| `OTEL_ENABLED` / `SENTRY_DSN` | false / 空 | 可观测性接入（未接线时保持关闭） |
| `STORAGE_TYPE` | local | `s3` 时上传走 MinIO/S3 |

---

## 6. 数据库与迁移

```powershell
# 应用迁移（在仓库根执行；script_location 已与 CWD 解耦）
.\.venv\Scripts\python.exe -m alembic -c migrations\alembic.ini upgrade head
.\.venv\Scripts\python.exe -m alembic -c migrations\alembic.ini heads        # 单 head
.\.venv\Scripts\python.exe -m alembic -c migrations\alembic.ini current
.\.venv\Scripts\python.exe -m alembic -c migrations\alembic.ini history
```

规则与约定：

- **保持单一 head**（`scripts/check_alembic_heads.py` 与质量门禁共同守护）；迁移图不是线性链：102 个 revision、4 个 root。
- 迁移只做结构/数据变更，**不夹带业务逻辑**。
- `alembic.ini` 必须**纯 ASCII**（Alembic 以系统 locale 读取，中文 Windows 的 GBK 会 `UnicodeDecodeError`）。
- `sqlalchemy.url` 只是占位，运行时由 `migrations/env.py` 用 `.env` 的 `DATABASE_URL` 覆盖。
- 全新安装的完整链演练（含恢复演练）是常规动作，不要等灾备时才第一次跑。

---

## 7. 备份与恢复

- 应用内「备份中心」是生产路径：`pg_dump` + 压缩 + 分片 AES 加密 + 增量 + 健康检查 + 智能清理（`fastapi_app/services/backup/`）。
- 调度：`backup_schedule` 表；`scheduler_poller` 每 5 分钟扫表，错过的窗口会补跑（依赖 `erp-arq` 在线）。
- 加密：`BACKUP_ENCRYPTION_PASSWORD`（或 `BACKUP_ENCRYPTION_KEY`）必须配置；`FALLBACK_TO_GENERATED` 必须保持 `false`。
- ⚠️ **自定义备份路径慎设在盘符根下**（如 `D:\backups`）：校验靠「在目标目录建临时文件」探测可写性，而能否在盘根建文件随**执行账户/进程**而变（本机实测：同一会话的 bash 能建、项目 `.venv` 的 Python 不能 —— 见附录 A 遗留项 2）。用 `D:\erp_system\backups` 这类有真实父目录的路径最稳。
- ⚠️ `backup_schedule.last_status` 是死字段（永远显示 `running`），**不要用它判断失败**——看 `backups/` 下产物时间戳。
- 恢复：优先用应用内恢复流程；灾备时按加密包内 `root/.env` + `config/.env.production` 重建配置（顺序见 `docs/runbooks/env-config.md` §6）。
- 人工排障用的库级脚本在 `scripts/database/`（`db_manager.py` / `restore_db.py`），**不是**生产备份路径。

---

## 8. 运维手册

### 8.1 服务启停（唯一正确姿势）

- **生产启停必须提权**：普通用户 shell 下 `nssm` / `sc` / `taskkill` / `Stop-Service` 全部因 ACL 拒绝访问；`Start-Process -Verb RunAs` 也被安全策略拦截。
- 首选管理器的「生产模式 / 启动服务 / 停止 / 重启」；命令行用**管理员** PowerShell：`C:\nssm\nssm.exe restart erp-prod`（优雅停止可能 >60s，别套短 timeout）。
- 重启必须**整树**，不要手工杀单个进程（会留下孤儿 worker 占住 5002）。
- 详细实测边界与模式切换顺序：[docs/runbooks/service-lifecycle.md](docs/runbooks/service-lifecycle.md)（**操作前必读**）。

### 8.2 日志

| 日志 | 位置 |
|---|---|
| 应用 JSON 日志 | `logs/fastapi_YYYYMMDD.log`（保留 14 天） |
| 通用/错误 | `logs/erp.log`、`logs/error.log` |
| NSSM 服务输出 | `logs/erp-prod.log`、`logs/erp-arq.log`、`logs/erp-web.log`（NSSM 轮转 10MB） |
| Nginx | `logs/nginx-access*.log`、`logs/nginx-error*.log` |
| 管理器 | `logs/server_manager_*.log` |
| 监督器状态 | `logs/prod_runner.json` |

日志轮转/清理/体积上限统一由 `config/log_policy.json` 驱动（三方共用，改完即生效，无需重启）。

### 8.3 例行巡检

```powershell
.\.venv\Scripts\python.exe scripts\diag\runtime_mode_probe.py     # 运行模式 + ARQ 判活
.\.venv\Scripts\python.exe scripts\ops\watchdog.py --verbose      # 六项健康检查
.\.venv\Scripts\python.exe scripts\ops\check_env_drift.py          # 配置漂移
```

### 8.4 常见故障速查

| 现象 | 先查什么 |
|---|---|
| 页面打不开 | `erp-web` 服务状态 + `curl :3000` 的 `Server: nginx` 头（`/nginx-health` 200 不能证明 nginx 在服务） |
| API 500 | `logs/erp-prod.log`、`logs/prod_runner.json`、`curl :5002/api/health` |
| 定时备份不跑 | `erp-arq` 是否运行（§4.14④ 哨兵键）；ARQ 挂了备份静默停摆 |
| 每个 POST 慢 4 秒 | 两个 Redis 都要 `PING` 判活（端口 LISTENING 不代表握手正常） |
| 改 `UVICORN_WORKERS` 无效 | 重装过服务后以 NSSM 注入值为准；用探针确认实际 worker 数 |
| 上传图片 403/410 | `UPLOAD_URL_SIGNING_SECRET` ↔ `config/uploads-signing.conf` 是否逐字一致 |
| 日志 0 字节/乱码 | NSSM `AppEnvironmentExtra` 是否「一变量一元素」（注册表可读） |
| 迁移命令报 ImportError | 在仓库根执行，或改用 `-c migrations\alembic.ini`（script_location 已用 `%(here)s`） |

---

## 9. 质量门禁与测试

提交前必须全绿（提交钩子 `core.hooksPath=.githooks`，分四层，含密钥内容扫描）：

```powershell
# 后端（注意：门禁的 pip-audit 会扫解释器自身 site-packages，必须用项目 .venv 跑）
.\.venv\Scripts\python.exe scripts\quality_gate.py     # 基线棘轮：只拦新增违规
ruff check .                                           # lint（ruff.toml）
.\.venv\Scripts\python.exe -m mypy                     # 类型（mypy.ini）
.\.venv\Scripts\python.exe -m pytest -q                # 回归（testpaths = tests + fastapi_app/tests）
.\.venv\Scripts\python.exe scripts\check_orphan_modules.py  # 白名单 ⊆ 导入图 + 零入边孤儿（CI 门禁；⚠️ 当前 FAIL，见附录 A）

# 前端（frontend-vite/ 下）
npm run type-check                                     # vue-tsc --noEmit
npm test                                               # vitest run
npm run lint                                           # eslint src/ --ext .ts,.vue
npm run check:api                                      # API 对齐检查
npm run check:routes                                   # 路由对齐检查
```

- 门禁阈值（`pyproject.toml`）：函数 ≤ **80** 行、Vue 组件 ≤ **400** 行、单文件 ≤ **1600** 行；基线在 `scripts/gate_baseline.json`，**只拦新增**。
- ⚠️ `scripts/check_orphan_modules.py` 是 CI 门禁（`.github/workflows/ci-cd.yml`），**当前在 main 上为 FAIL**：`mypy.ini` 白名单 368 条里 6 个 `__init__.py` 条目零入边（P2 mypy 扩容遗留，非本轮引入）。修法需人拍板，见附录 A 遗留项 1。
- 密钥扫描误报的正确处置：命中行尾加 `secret-scan:allow <理由>`；`.githooks/allowlist.txt` 是逐文件豁免，新增条目必须在提交信息里说明理由。
- 本机未安装 `pre-commit` 时第 ④ 层降级（暂存含 `.py`/`.vue` 才直接跑门禁）；恢复完整门禁：`pip install pre-commit`。
- CI：`.github/workflows/ci-cd.yml`（Ubuntu + Postgres 服务容器，跑迁移、后端测试、前端构建与检查）。CI **不部署**生产（托管 runner 无法访问内网机）。

---

## 10. API 与前端约定

- 前缀 `/api/v1`；业务端点默认需登录（路由层统一注入认证依赖）；文档端点在 production 自动关闭。
- 认证：`Authorization: Bearer <JWT>`（移动端/API）或 httpOnly Cookie（浏览器）；支持 RS256（推荐）与 HS256。
- 权限：`require_permission("xxx_manage")` / `require_superuser()` 依赖工厂；`user_` 前缀敏感权限仅超管可见。
- **响应形状（刻意不引入统一信封中间件）**：成功 = `{"success": true, ...端点自有字段}`（构造收敛于 [fastapi_app/core/response.py](fastapi_app/core/response.py)，与内联 `{'success': True, **x}` 逐字节等价）；失败 = 全局异常处理器统一为 `{"success": false, "detail": ..., "status_code": ..., "request_id": ..., "timestamp": ..., ["code"]}`（`code` 只在 AppError / 422 / 500 出现）。`request_id` 在**响应头**恒有（`RequestIdMiddleware`），成功路径**不进响应体** —— 端点用 `response_model=` 声明契约，中间件新增的键会被模型白名单**静默丢弃**。
- 分页：`page` + `per_page`。**没有统一口径** —— 各端点的默认值与上限不同（实测默认 `50`×19 / `20`×16 / `15`×2 / `200`×1 / `100`×1；上限 `500`×16 / `100`×12 / `200`×11），对接前请按**具体端点**的 Query 声明确认。
- 前端：`npm run check:api` 保证移动端调用全部走共享 API 层；`npm run check:routes` 校验 PC/移动路由对齐（端独有路由属正常差异）。
- WebSocket：`/ws/notifications`（Nginx 已配置升级与长超时）。
- 契约快照对比（可选）：`CONTRACT_BASE_URL=http://127.0.0.1:5002 pytest tests/contract -v`。

---

## 11. 安全边界与红线

**会打挂生产、别做：**

1. 不要删除根 `utils/`（`fastapi_app/main.py` 直接依赖 `utils.redis_cache`）、`fastapi_app/utils/`、`server_manager.py` + `server_manager/`。
2. 不要把 `config/pgbouncer/userlist.txt` 或任何 `_ops/credentials/**` 加回版本库。
3. 不要让 uvicorn 绑 `0.0.0.0`（绕过 nginx，并把 `/metrics` 暴露给同网段）。
4. 不要让 `.env` 的 `BACKUP_ENCRYPTION_PASSWORD` 为空（`BACKUP_ENCRYPTION_ENABLED=true` 时会**静默降级为不加密备份**）。
5. 不要修改/删除 `frontend-vite/vite.config.js`（它是 `vue-tsc -b` 编译 `vite.config.ts` 的设计产物，有回归测试）。
6. 不要改 `core.hooksPath`（指到 husky 目录会废掉 `.githooks` 的密钥扫描）。
7. Alembic 迁移只做结构/数据变更，不夹带业务逻辑；保持单 head。
8. 本机**既是生产主机也是运维主机**：没有独立测试环境，任何命令都直接影响在用业务——改动小步、可回滚，提交前跑质量门禁。

**凭据边界**：真实值只在 `.env` 与 `_ops/credentials/`；`.env.example` / `.env.production.example` 只写占位符；JWT 私钥、备份加密口令、`METRICS_BEARER_TOKEN`、Redis 口令、TLS 私钥全部不入库。

---

## 12. 文档导航

| 主题 | 位置 |
|---|---|
| 服务生命周期与提权边界（操作前必读） | [docs/runbooks/service-lifecycle.md](docs/runbooks/service-lifecycle.md) |
| 环境变量：单一来源 / 漂移检查 / 灾备重建 | [docs/runbooks/env-config.md](docs/runbooks/env-config.md) |
| 看门狗部署与告警 | [docs/runbooks/watchdog.md](docs/runbooks/watchdog.md) |
| 后端结构与模块规范 | [fastapi_app/README.md](fastapi_app/README.md) |
| 事务边界规范 | [docs/TRANSACTION_BOUNDARY_GUIDE.md](docs/TRANSACTION_BOUNDARY_GUIDE.md) |
| config 目录：哪些生效、哪些是灾备件 | [config/README.md](config/README.md) |
| NSSM 五服务机读快照（重建用） | [config/nssm-services.json](config/nssm-services.json) |
| 数据库工具与只读副本 | [scripts/database/README.md](scripts/database/README.md) |
| 备份与恢复设计 | docs/backup-restore/ |
| 凭据轮换 runbook | docs/ops/2026-09-30-credential-rotation-runbook.md |
| 变更历史 | [CHANGELOG.md](CHANGELOG.md) |
| 项目协作契约（AI 与人都适用） | [AGENTS.md](AGENTS.md) |

---

## 附录 A. 质量与审计快照（2026-10-03，第四轮全量复核）

本轮是**只读全量复核**（不动业务代码）：计数一律用 `ast` 与 Alembic 官方 API 现场实测，不用正则 ——
本轮据此纠正了 §1.1（端点模块数）、§1.2（前端行数）、§2.4、§7（盘根备份路径）与 §10（响应形状）的 5 处与现场不符。

| 检查 | 结果 |
|---|---|
| `scripts/quality_gate.py`（项目 `.venv`） | **PASS** —— 10 项全部「与基线一致」（N+1 0 / 宽 except 5 / 超长函数 51 / 巨型组件 7 / service commit 12 / BOM 0 / Alembic 图 0 / 环境漂移 0 / ruff 59 / pip-audit 豁免策略 0） |
| `ruff check .` | 123 个既有违规（全仓口径；门禁口径 `scripts/ + server_manager/` = 59 与基线一致） |
| `mypy` | **Success: no issues found in 368 source files** |
| 前端 `vue-tsc --noEmit` | **0 错误**（Node v24.14.0） |
| 前端 `npm run lint` | **0 error / 168 warning** |
| `npm run check:api` / `check:routes` | **通过**（API 层 108 端点 / 移动端 44 文件 / PC 195 视图；移动端独有路由 3 条属正常差异） |
| 端点模块与路由（AST + 调用图） | **34 个端点模块 / 369 个 handler**；34/34 全部 `include_router`，**零孤儿** |
| Alembic（`ScriptDirectory` API） | **单 head**（`pg_standalone_063_fix_order_status_check`）；102 revisions / **4 roots** |
| 环境变量漂移 | **0 处** |
| NSSM 五服务与端口 | `erp-prod`→依赖 `erp-redis`、`erp-arq`→依赖 `erp-redis-broker`、broker 6380；与 `config/nssm-services.json` 一致 |
| 生产健康 | `logs/prod_runner.json`：`mode=production`、`ready=true`、`frontend_ok=true`、`workers=8`（`arq.status=external` 属正常设计） |
| 密钥卫生 | `.env`、`config/uploads-signing.conf`、`config/tls/*.key`、`config/pgbouncer/userlist.txt`、`_ops/credentials/**` 均被 `git check-ignore` 命中；版本库内只有 `*.example` 模板 |
| 后端 `pytest`（全量 4109 项） | **1 failed / 3840 passed / 268 skipped（6 分 22 秒）**；日志 `logs/pytest_audit_2026-10-03.log` |
| `scripts/check_orphan_modules.py` | **FAIL**（CI 门禁；见遗留项 1） |

唯一失败用例 —— `fastapi_app/tests/test_backup_m1.py::TestValidatePath::test_existing_root_parent_allowed`（单文件复跑稳定复现：1 failed / 25 passed）：

- **现象**：断言 `validate_path('D:\no_such_dir_xyz\backups')` 合法，实际返回 `{'valid': False, 'error': '目录不可写: D:\'}`（单文件复跑稳定复现）。
- **根因**：`validate_path` 向上找最近存在的父目录，落点是**盘符根 `D:\`**，而 `_is_writable` 是在该目录**建临时文件**；本机实测 `_is_writable('D:\') == False`、`_is_writable('D:\erp_system') == True`。
- **性质：环境相关，不是稳定功能缺陷**。证据链：同一会话里 bash `touch /d/x` **成功**、`icacls D:\` 显示 `Authenticated Users:(M)` / `Administrators:(F)`（有写权限），但项目 `.venv` 的 Python 对 `D:\` 根做 `open(...,'w')` 与 `mkstemp` **均** `PermissionError [Errno 13]` —— 属**进程级**限制（安全策略/软件），不是 ACL。生产服务 `erp-prod`/`erp-arq` 以 **LocalSystem** 运行（注册表 `ObjectName`），口径未必与本机 shell 相同。
- **代码层面真正该修的点（与环境无关）**：①`_is_writable` 的 docstring 写「尽力而为,失败不阻断」，但 `validate_path` 拿 False 当硬否决 —— 口径自相矛盾；②用「建文件」探测盘根本就不成立（盘根允许建目录、未必允许建文件）；③该用例硬编码 Windows 路径，Linux runner 上向上查找的落点是 CWD（可写），因此 **CI 抓不到**这层环境差异。

遗留关注项（均非本轮引入，按处理优先级排序）：

1. **CI 门禁 `check_orphan_modules.py` 在 main 上是红的**：`mypy.ini` 白名单 368 条中 6 个 `__init__.py` 条目零入边（`api/v1`、`services/{backup/metrics, dashboard, material_registration, purchase, serializers}`）。根因是 P2 批次的 mypy 扩容（白名单 144 → 370）新增了 `__init__.py` 条目，而扫描器的入边统计**不给父包补边**（只给可达集补，见其 docstring）—— 「子模块被导入」在保守图里不会给父包产生入边。两种修法需人拍板：①修扫描器（父包按子模块补入边，与断言 B 排除包的既有设计一致）；②从白名单移除这 6 条（会缩小 mypy 覆盖）。按「门禁只可能变严」的棘轮原则，本轮不动门禁语义。
2. **备份路径校验的盘根口径不稳**（上表唯一失败用例）：可写探测 = 试建文件，结论随执行账户/进程而变；且 `_is_writable` 的 docstring（「失败不阻断」）与 `validate_path`（硬否决）矛盾。修法需先定语义：允许盘根 → 改探测方式（试建**子目录**）且让 docstring 与实现一致；拒绝 → 明确错误文案 + 把用例改成不依赖 Windows 盘根（否则 CI 永远抓不到）。
3. **依赖漏洞**：现场 pip-audit 曾报 25 个包 172 条漏洞（其中 166 条已有修复版本），`pyproject.toml` 当前 **0 条豁免**。正确处理是升级依赖，而不是登记豁免；破坏面评估后再批量升级。
4. **`fastapi_app/README.md` 仍陈旧**：第 8–10 行写 PostgreSQL 16 / Celery（含 `celery_app.py`），与实际（PG 18 / ARQ）不符；同文件第 156 行已自我纠正，前后矛盾，可另行修订。

口径提醒：门禁必须用项目 `.venv` 跑 —— 系统解释器的 site-packages 会被 pip-audit 扫出上百条与本项目无关的漏洞，属纯口径噪声（见 `docs/runbooks/service-lifecycle.md` 第 3 层说明）。
