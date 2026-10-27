# 滨发协同系统（binfa-erp）· AI 一键部署提示词

> **怎么用**：把本文件**整篇**发给一个能执行命令、读写文件的 AI 代理（Claude Code / Cursor / Codex / Windsurf 等），
> 让它在**目标 Windows 服务器**上从零把本系统部署起来。本文件既是给人看的说明，也是给 AI 的**可执行指令**。
>
> - **目标形态**：Windows 主机 + Nginx `:3000` + Uvicorn `:5002`（仅回环）+ PostgreSQL 18 + 双 Redis（`6379`/`6380`）+ NSSM 五服务。
> - **全流程 17 步、约 2–4 小时**（不含数据迁移）。每步都有验收命令，**验收不过不许进下一步**。
> - 想走**全自动离线包**（源机一条命令打包、目标机一条命令安装）：见 [`deploy/README.md`](deploy/README.md)。
> - 完整**人工手册**（架构 / 运维 / 门禁 / API 约定）已移至 [`docs/PROJECT_MANUAL.md`](docs/PROJECT_MANUAL.md)，排障与深挖以它为准。

---

## 0. 给 AI 代理的指令（先读这一段）

你是一名 Windows 部署工程师。请按本文流程把本 ERP 部署到目标服务器。**以下五条是硬性要求，违反即中止**：

1. **逐步执行、逐步验收**：每个步骤末尾都有「✅ 验收」命令与期望输出。**验收失败立即停下**，按该步的「⚠️ 失败处理」定位修复后再继续；**禁止跳过验收**，禁止「先把所有命令跑完再看结果」。
2. **只从指定官方来源取安装包**，不要凭记忆换镜像、换版本。尤其 **Redis 必须是 tporadowski 的 5.0.14.1**——换成 7.x/8.x 的第三方 Windows 构建会因配置指令差异翻车。
3. **需要管理员权限**：安装服务、写 `C:\`、改防火墙、注册计划任务都需要。没有提权就 `Start-Process -Verb RunAs` 拉起并让用户点 UAC 确认。
4. **密钥/口令纪律**：所有真实口令、私钥**只写 `.env` 与 `_ops/credentials/`**；**绝不**写进文档、聊天记录、命令行参数或 git。凡是要用口令的地方，优先交互式隐藏输入。
5. **缺信息就问，不要臆造**：目标 IP、口令、盘符、数据来源等，若用户没给，**先问再动**。

> ⚠️ 本机是**生产主机也是运维主机**，没有独立测试环境。若目标机就是当前生产机，任何命令都直接影响在用业务——**改动小步、可回滚，动手前确认**。

### 0.1 开始前，先向用户索取这些信息

| 需要 | 默认 | 用途 |
|---|---|---|
| 目标机**固定内网 IP** | **无（必填）** | 写入 `ALLOWED_HOSTS` / `CORS_ORIGINS` / `WS_ALLOWED_ORIGINS`；也是最终访问地址 |
| 项目**部署路径** | `D:\erp_system` | 全仓大量绝对路径按此写好（nginx conf、nssm 快照）；换路径要同步改，见步骤 11 |
| 组件**安装落位** | Nginx `C:\nginx`、Redis `C:\Redis`、NSSM `C:\nssm\nssm.exe` | 管理器只在这几处查找 |
| **PostgreSQL 超级用户口令** | 无（必填） | 建库 / 建角色 |
| **Redis 口令** | 无（必填） | 三处必须一致：Redis 服务参数 / `.env` / broker conf |
| **初始 `admin` 口令** | 无（必填） | 全新空库引导时写入（走数据迁移则可省） |
| **数据来源** | 全量镜像恢复 / 空库起步 | 决定步骤 9 走 A 还是 B |
| 是否启用 **443 TLS** | 否 | 全新 clone 无私钥，默认注释 443 段 |

### 0.2 完成后必须回报用户

一句「完成」不算数。**必须附上步骤 13 的逐项验收输出**（后端 / 前端 / 入口健康、ARQ 哨兵键、运行模式探针、`prod_runner.json`）**与步骤 12 的五服务状态**，并说明：入口地址、数据来源、遗留项。

---

## 目标形态速览（端口与五服务）

```text
浏览器 → Nginx :3000 (config/nginx-windows.conf, root = frontend-vite/dist)
        → uvicorn 127.0.0.1:5002 (仅绑回环，API 不直接暴露局域网)
        → PostgreSQL :5432 / Redis :6379(缓存) + :6380(ARQ broker)
后台任务 → ARQ worker（独立进程/服务 erp-arq）
```

| 端口 | 用途 | 暴露范围 |
|---|---|---|
| 3000 | Nginx：前端静态 + API/WS 反代（**用户唯一入口**） | 局域网 |
| 443 | Nginx：自签内网 TLS（可选） | 局域网 |
| 5002 | FastAPI（uvicorn） | **仅 127.0.0.1**（禁止 0.0.0.0） |
| 5432 | PostgreSQL | 仅本机 |
| 6379 / 6380 | Redis 缓存 / ARQ broker | 仅 127.0.0.1 |

**五个 NSSM 服务**：`erp-prod`（uvicorn `:5002`）、`erp-arq`（ARQ worker）、`erp-web`（nginx `:3000`）、`erp-redis`（`:6379`）、`erp-redis-broker`（`:6380`）。
两个关键不变量：`erp-arq` **必须依赖** `erp-redis-broker`（否则开机抢跑 → 无限重启 → 备份静默停摆）；`erp-web` 与 `erp-prod` **启停解耦**（重启后端不影响前端静态）。

---

## 步骤 0 —— 前置检查

**目标**：确认目标机满足最低条件，否则后面每一步都会踩坑。

- [ ] **管理员权限**（安装服务、写 `C:\`、注册计划任务都需要）
- [ ] Windows 10/11 或 Server 2019+（**x64**，本部署依赖 NSSM/Windows 服务）
- [ ] 磁盘：项目 + 备份至少预留 **100 GB**（备份默认保留 30 天）
- [ ] **3000 / 5002 / 5432 / 6379 / 6380 端口未被占用**
- [ ] 规划好项目路径：**强烈建议沿用 `D:\erp_system`**（全仓绝对路径按此写好，换路径要同步改）

**✅ 验收**：以上逐条为真。检查端口：

```powershell
foreach ($p in 3000,5002,5432,6379,6380) {
  $r = Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue
  if ($r) { "PORT $p IN USE by PID $($r.OwningProcess)" } else { "PORT $p free" }
}
```

---

## 步骤 1 —— 安装基础软件

**目标**：装齐运行时依赖。**VC++ 运行库必须先装**（Redis 与管理器 exe 依赖它）。

| 组件 | 版本 | 安装位置 / 要求 |
|---|---|---|
| Python | **3.13.x** | 任意位置，之后用它创建项目 `.venv` |
| PostgreSQL | **18**（含 pg_dump/pg_restore/psql） | 本机安装，服务建议 NetworkService |
| Redis for Windows | 兼容 Windows 的 `redis-server.exe` | **`C:\Redis\`**（管理器只在这两处查找：`C:\Redis` / `C:\Program Files\Redis`） |
| Nginx for Windows | 官方 Windows 构建 | **`C:\nginx\`**（`nginx.exe` 与 `conf\mime.types` 需在此） |
| NSSM | **2.24** | **`C:\nssm\nssm.exe`**（不在 PATH，命令全用绝对路径） |
| Node.js | **>= 22** | 构建前端用（也可在别处构建后拷 `dist`） |
| Git | 最新 | 拉代码与回滚 |
| OpenSSL | **3.x** | 步骤 6 生成密钥需要，`openssl` 须在 PATH 上 |
| VC++ 运行库 | **2015–2022 x64** | Redis 与管理器 exe 依赖；缺失报 `VCRUNTIME140.dll` 找不到 |

**官方下载来源**（照此取包，不要凭记忆找第三方镜像）：

| 组件 | 下载 | 落位要求 |
|---|---|---|
| Python 3.13.x | python.org/downloads/windows（最新 3.13.x 64-bit installer） | 之后创建项目 `.venv` |
| PostgreSQL 18 | enterprisedb.com/downloads/postgres-postgresql-downloads（EDB 安装器） | 静默安装见步骤 3；装在默认目录则 `pg_dump` 探测可直接命中 |
| Redis 5.0.14.1 | github.com/tporadowski/redis/releases（`Redis-x64-5.0.14.1.zip`） | 解压后 `redis-server.exe`/`redis-cli.exe` 在 `C:\Redis\` 根；**不要用 7.x/8.x 第三方构建** |
| Nginx | nginx.org/en/download.html（Stable Windows zip） | 解压为 `C:\nginx\` |
| NSSM 2.24 | nssm.cc/download（`nssm-2.24.zip`） | 取 `win64\nssm.exe` → `C:\nssm\nssm.exe` |
| Node.js ≥22 | nodejs.org（LTS x64 msi） | 构建前端用 |
| Git | git-scm.com/download/win | 拉代码；其 `usr\bin\openssl.exe` 可作步骤 6 的 openssl |
| VC++ 运行库 | aka.ms/vs/17/release/vc_redist.x64.exe | **先于 Redis/管理器安装** |

> ⚠️ **PG 客户端工具的落点是个坑**：`pg_dump`/`psql` 解析顺序为 `PG_TOOLS_BIN` → 系统 PATH → 三个约定安装目录
> （`C:\Program Files\PostgreSQL\*\bin`、`D:\PostgreSQL\bin`、`C:\PostgreSQL\bin`）。
> 若把 PostgreSQL 装到别处又没有 `PG_TOOLS_BIN`（步骤 7），备份会**静默降级为 JSON 导出**——功能看着正常，产物却不是 `pg_dump`。

**✅ 验收**：`C:\nssm\nssm.exe version`、`C:\nginx\nginx.exe -v`、`C:\Redis\redis-server.exe --version`、`python -V`（3.13.x）、`node -v`（≥22）均有输出。

---

## 步骤 2 —— 获取代码与准备目录

**目标**：把代码放到目标路径，建好运行期目录。

> 前置（唯一需要账号 Owner 介入的一步）：本仓库是**私有仓库**，新服务器克隆前先放行凭据，二选一：
> SSH（把公钥加进 GitHub 仓库 Settings → Deploy keys，只读即可）或 HTTPS（用 PAT）。

```powershell
# 方式一：Git 克隆（推荐，便于回滚）
git clone git@github.com:qike1132/erp.git D:\erp_system

cd D:\erp_system
New-Item -ItemType Directory -Force _ops\credentials   # 凭据存放（已 gitignore）
New-Item -ItemType Directory -Force logs, backups      # 运行期目录（启动时也会自动建）
```

**✅ 验收**：`Test-Path D:\erp_system\fastapi_app`、`Test-Path D:\erp_system\.env.example` 均为 `True`。

---

## 步骤 3 —— PostgreSQL：建库与账号

**目标**：建好业务库与账号，owner 必须是 `erp_app`。

静默安装（已装好则跳过本段直接建库）：

```powershell
# EDB 安装器示例（安装包名以实际下载为准）；默认装到 C:\Program Files\PostgreSQL\18
.\postgresql-18.x-x64.exe --mode unattended --superpassword "<超级用户强口令>" --serverport 5432
# ⚠️ 装到非默认目录时，pg_dump 的三个约定探测目录都会落空 —— 必须设 .env 的 PG_TOOLS_BIN（步骤 7）
```

用超级用户（`psql -U postgres`）执行，**替换为强口令并存入 `_ops/credentials`**：

```sql
CREATE ROLE erp_app LOGIN PASSWORD '<强口令>';
CREATE DATABASE erp_system WITH OWNER = erp_app ENCODING = 'UTF8' TEMPLATE = template0;
```

- ⚠️ **PG 15+ 全新库必须以 `erp_app` 为 owner**；非 owner 仅凭 `GRANT` 仍会在迁移建表时报 `InsufficientPrivilege: 模式 public 权限不够`。
- `pg_hba.conf`：对 `127.0.0.1/32` 使用 `scram-sha-256`；**不要**把 5432 暴露给局域网。
- 结构与数据**全部**由 Alembic 迁移创建（步骤 8），不要手工建表，也不要用 `create_all` 代替迁移。

**✅ 验收**：`psql -h 127.0.0.1 -U erp_app -d erp_system -c "select 1"` 返回成功。

---

## 步骤 4 —— Redis：双实例（缓存 6379 + broker 6380）

**目标**：两个 Redis 实例分开跑（避免缓存驱逐把排队任务清掉），并注册为服务。

```powershell
# 1) 缓存实例配置：以仓库【模板】为基准，落地到 C:\Redis
#    ⚠️ 用 .template，不是 config/redis.production.conf —— 后者含真实口令、已 gitignore，全新 clone 根本没有
Copy-Item D:\erp_system\config\redis.production.conf.template C:\Redis\redis.windows-service.conf
#    模板已是：bind 127.0.0.1 / port 6379 / maxmemory 512mb allkeys-lru / appendonly yes / logfile 置空
#    落地后【务必确认】文件里没有生效的 requirepass 行（模板中那行已注释）；
#    口令只由服务启动参数 --requirepass 注入（与 .env 一致），绝不写进 .conf

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

**✅ 验收**（两个实例都要通）：

```powershell
C:\Redis\redis-cli.exe -p 6379 -a <REDIS_PASSWORD> ping    # PONG
C:\Redis\redis-cli.exe -p 6380 -a <REDIS_PASSWORD> ping    # PONG
```

> 口令必须与 `.env` 的 `REDIS_PASSWORD` / `REDIS_CACHE_URL` / `REDIS_BROKER_URL` 一致；轮换时三处同步改。

---

## 步骤 5 —— Python 虚拟环境与依赖

**目标**：建生产解释器 `.venv` 并装依赖。

```powershell
cd D:\erp_system
python -m venv .venv
.\.venv\Scripts\python.exe -V                     # 应输出 3.13.x
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\pip.exe install -r requirements/base.txt     # 生产必需
```

**依赖检查单**（「按需」= 不装不影响其它功能，但缺了对应功能就整块不可用）：

| 依赖文件 | 用途 | 缺了会怎样 | 自检 |
|---|---|---|---|
| `requirements/base.txt` | 生产必需 | 服务起不来 | `python -c "import fastapi, sqlalchemy, asyncpg, redis"` |
| `requirements/ocr.txt` | **粘贴识别** + PDF 出货单 OCR | 该功能整块不可用（端点返回 **503**） | `python -c "import numpy, cv2, rapidocr, rapidocr_pdf, rapid_table, onnxruntime, fitz"` |
| `requirements/s3.txt` | `STORAGE_TYPE=s3` 时的对象存储 | 附件读写失败 | `python -c "import boto3"` |
| `requirements/test.txt` / `dev.txt` | 回归测试 / ruff / mypy | CI 与本地检查不可用 | — |

> 上面 `python` 均指 **`.\.venv\Scripts\python.exe`**。**OCR 那条尤其容易漏**——它在「按需」清单里看着像可选项，但**装了才是功能可用**。
> ⚠️ **NSSM 服务固定指向 `.venv\Scripts\python.exe`**。换/重建虚拟环境后必须重设服务 Application，否则服务仍指向旧解释器。

**✅ 验收**：`python -c "import fastapi, sqlalchemy, asyncpg, redis"` 无报错。

---

## 步骤 6 —— 生成密钥与证书

**目标**：为生产生成全部密钥，落点明确。

| 用途 | 生成命令 | 落点 |
|---|---|---|
| `SECRET_KEY` | `python -c "import secrets; print(secrets.token_hex(32))"` | `.env`（≥32 字符） |
| JWT RS256 密钥对 | `openssl genpkey -algorithm RSA -out config\jwt\private_v2.pem -pkeyopt rsa_keygen_bits:4096`<br>`openssl rsa -pubout -in config\jwt\private_v2.pem -out config\jwt\public_v2.pem` | `config/jwt/`（私钥已 gitignore，**永不入库**） |
| 上传 URL 签名 | `openssl rand -hex 32` | `.env` 的 `UPLOAD_URL_SIGNING_SECRET` + `config/uploads-signing.conf` |
| 备份加密口令 | `python -c "import secrets; print(secrets.token_urlsafe(32))"` | `.env` 的 `BACKUP_ENCRYPTION_PASSWORD`（**严禁留空**） |
| `/metrics` Token | `python -c "import secrets; print(secrets.token_urlsafe(32))"` | `.env` 的 `METRICS_BEARER_TOKEN` |
| 内网 TLS 自签证书（可选） | `config/tls/` 下**公钥证书已入库**，**私钥 `*.key` 未入库**；全新 clone 需自备 `server.key` 或重新签发 | `config/tls/` |

**统一把上面所有真实值记录到 `_ops/credentials/`**（受 ACL 保护、不入库）。

**✅ 验收**：`Test-Path config\jwt\private_v2.pem`、`Test-Path config\jwt\public_v2.pem` 为 `True`。

---

## 步骤 7 —— 编写 `.env`（唯一运行时配置源）

**目标**：把 `.env` 写对。**这是最容易翻车的一步**。

```powershell
Copy-Item .env.example .env
```

> ⚠️ **写 `.env` 别用 PowerShell `Get-Content`/`Set-Content`**：Windows PowerShell 5.1 读写非 GBK 内容会误判编码，把中文注释与配置行**粘成一行**（被粘的键随之失效），也容易写出 BOM/乱码。用 UTF-8 编辑器手改，或用 Python 生成（`open(path,'a',encoding='utf-8')`）。

**必填 / 生产必改键位**（完整清单见 [.env.example](.env.example) 注释）：

| 键 | 生产取值 | 说明 |
|---|---|---|
| `APP_ENV` | `production` | 生产自动关闭 `/api/docs`、启用强校验 |
| `SECRET_KEY` | 步骤 6 生成 | 不得用默认值/占位符 |
| `DB_HOST/DB_PORT/DB_USER/DB_PASSWORD/DB_NAME` | `127.0.0.1 / 5432 / erp_app / <口令> / erp_system` | 连接池由 `UVICORN_WORKERS × DB_MAX_CONNECTIONS` 推导，不要另设池参数 |
| `PG_TOOLS_BIN` | `D:\PostgreSQL\bin`（本机实际路径） | `pg_dump`/`psql` 所在目录。**留空且 PATH 里也没有 → 备份静默降级为 JSON 导出** |
| `REDIS_PASSWORD`、`REDIS_CACHE_URL`、`REDIS_BROKER_URL` | 与步骤 4 一致 | broker 指 `:6380`，cache 指 `:6379` |
| `ALLOWED_HOSTS` | **JSON 数组**（如 `["192.168.1.97","localhost"]`），**禁止 `*`** | 字段名与变量同名，pydantic 对 list 按 **JSON** 解析：写成裸 `*` 或逗号串会 `SettingsError` 直接起不来 |
| `CORS_ORIGINS` | **逗号串**（如 `http://<主机IP>:3000`） | 与 `ALLOWED_HOSTS` 格式**不同**；不得含 `null` |
| `WS_ALLOWED_ORIGINS` | 同上（逗号串） | **漏配 → 全站 WebSocket 403** |
| `JWT_ALGORITHM` + `JWT_PRIVATE_KEY_PATH` + `JWT_PUBLIC_KEY_PATH` | `RS256` + 步骤 6 两个路径 | RS256 下两文件必须真实存在，否则启动失败 |
| `BACKUP_ENCRYPTION_ENABLED` + `BACKUP_ENCRYPTION_PASSWORD` | `true` + 强随机口令 | **口令为空会静默降级为不加密备份** |
| `BACKUP_ENCRYPTION_FALLBACK_TO_GENERATED` | `false`（保持） | 置 true 会产生「事后无法解密」的备份 |
| `METRICS_BEARER_TOKEN` | 步骤 6 生成 | 为空则 `/metrics` 返回 503（fail-closed） |
| `UPLOAD_URL_SIGNING_SECRET` | 步骤 6 生成 | 与 `config/uploads-signing.conf` 逐字一致，否则上传文件全部 403 |
| `STRICT_CONFIG_CHECK` | `true` | 生产启动强校验（备份加密、BACKUP_DIR 可写等） |
| `UVICORN_WORKERS` | 建议 4（8GB 内存） | 重装服务后 NSSM 注入值优先于 `.env` |
| `STORAGE_TYPE` | `local`（默认） | 用 S3/MinIO 才改 `s3` 并装 `requirements/s3.txt` |

> ⚠️ 改完 `.env` 或任何服务参数后一律用 **`nssm restart <服务名>`**；`nssm start` 对**已在运行**的服务返回 1 且**不重载配置**（进程仍旧、仍用旧 `.env`），极易被误当成「已重启」。`start` 只在首次拉起时用。

**✅ 验收**：

```powershell
.\.venv\Scripts\python.exe scripts\ops\check_env_drift.py       # 门禁口径 = 0
.\.venv\Scripts\python.exe start.py --prod --check              # 环境自检（不起进程）
```

---

## 步骤 8 —— 迁移与初始化数据

**目标**：建表 + 初始化权限树与导航。

```powershell
cd D:\erp_system

# 1) 结构迁移（从仓库根执行，无需 cd，无需 PYTHONPATH）
.\.venv\Scripts\python.exe -m alembic -c migrations\alembic.ini upgrade head
.\.venv\Scripts\python.exe -m alembic -c migrations\alembic.ini heads   # 必须只有一个 head

# 2) 权限树初始化（迁移建表之后）
.\.venv\Scripts\python.exe scripts\init_permissions.py

# 3) 左侧导航种子（init_permissions 不写 url/section，缺此步侧栏为空）
.\.venv\Scripts\python.exe scripts\seed_nav.py
```

> ⚠️ 迁移链包含历史 revision，**任何全新安装都会经过整条链**，因此验收不能只看退出码，还要在步骤 15 跑一次应用启动。

**✅ 验收**：`heads` 输出**仅一行**；两个脚本均以退出码 0 结束。

---

## 步骤 9 —— 初始管理员账号

**目标**：让系统能登录。按**数据来源**二选一。

**A. 从现有部署迁移（推荐）**：从备份恢复 —— 用户、权限、业务数据一并带走。恢复后直接跳到步骤 10。

**B. 全新空白库引导**：迁移后库内没有任何用户，需手工建一次 `admin`（系统没有内置种子）：

```powershell
# 1) 生成 Argon2id 口令哈希（口令策略：≥6 位，且必须同时含大写字母 + 小写字母 + 数字）
.\.venv\Scripts\python.exe -c "from fastapi_app.core.security import hash_password; print(hash_password('<你的强密码>'))"
```

```sql
-- 2) 用 psql 写入（替换 <哈希>；create_time/update_time 显式给值）
INSERT INTO "user" (username, password, is_super, status, create_time, update_time)
VALUES ('admin', '<哈希>', true, true, now(), now());
```

- 登录后立刻在「用户管理」里建各岗位账号并按权限树授权。
- 忘记口令时：`python scripts/reset_admin_password.py --password <新密码>`（只重置、不创建）。

**✅ 验收**：`psql ... -c "select count(*) from \"user\""` ≥ 1。

---

## 步骤 10 —— 构建前端

**目标**：产出生产 `dist`。

```powershell
cd D:\erp_system\frontend-vite
npm ci
npm run build                 # vue-tsc -b && node scripts/vite-build.mjs → dist/
```

- 生产无需设置 API/WS 地址：`VITE_API_BASE_URL` 缺省 `/api/v1`，WebSocket 同源推导，统一走 nginx 反代。
- 需要**原子替换**产物时用 `npm run build:atomic`（先构建到 `dist-new` 再替换 `dist`）。⚠️ 同机跑 vite dev server 时 watcher 会锁目录导致 EPERM —— 先停开发模式。
- `frontend-vite/vite.config.js` 是 `vue-tsc -b` 编译 `vite.config.ts` 的设计产物，**不要手改/删除**（有回归测试断言两者一致）。

**✅ 验收**：`frontend-vite\dist\index.html` 存在，且不含 `@vite/client`、`/src/main.ts`。

---

## 步骤 11 —— 配置 Nginx

**目标**：让 `:3000` 正确托管前端并反代 API。

```powershell
# 1) 校验/替换 config\nginx-windows.conf 中的绝对路径（换过盘符时）
#    include C:/nginx/conf/mime.types;            ← Nginx 安装路径
#    include D:/erp_system/config/security-headers.conf;
#    alias   D:/erp_system/static/uploads/;
#    其余 root frontend-vite/dist 为相对项目根（-p 参数指定）

# 2) 上传签名密钥（必需，否则 /static/uploads/** 全部 403）
Copy-Item D:\erp_system\config\uploads-signing.conf.example D:\erp_system\config\uploads-signing.conf
#    将里面 <在此填入密钥...> 替换为与 .env 的 UPLOAD_URL_SIGNING_SECRET 逐字相同的值

# 3) TLS（可选）：config\tls\server.crt / server.key 就位；不启用就把 443 server 块整段注释掉
#    ⚠️ 全新 clone 只有公钥，私钥 server.key 被 gitignore、不随仓库来 → 默认即「不启用」

# 4) 首次运行前建 nginx temp 目录（nginx -p <项目根> 时【不会自建】）
$root = 'D:\erp_system'
foreach ($d in 'client_body_temp','proxy_temp','fastcgi_temp','uwsgi_temp','scgi_temp') {
    New-Item -ItemType Directory -Force "$root\temp\$d" | Out-Null
}

# 5) 语法测试（-p 指定项目根，而不是 nginx 目录）
C:\nginx\nginx.exe -p D:\erp_system -c D:\erp_system\config\nginx-windows.conf -t
```

**防火墙**：只放行入站 TCP **3000**（启用 443 时再加 **443**）；5002/5432/6379/6380 一律仅回环。

```powershell
New-NetFirewallRule -DisplayName "erp-web-3000" -Direction Inbound -Protocol TCP -LocalPort 3000 -Action Allow
# 启用 443 时再加一条：
New-NetFirewallRule -DisplayName "erp-web-443"  -Direction Inbound -Protocol TCP -LocalPort 443  -Action Allow
```

**✅ 验收**：`nginx -t` 输出 `syntax is ok` + `test is successful`。

---

## 步骤 12 —— 安装五个 Windows 服务

**目标**：把五个服务注册进 SCM。

**首选：管理器 GUI**（`python server_manager.py` 或打包的 `ERP服务器管理器_vX.Y.exe`，需管理员）：

1. 打开管理器 → 「安装服务」→ 它按当前 Worker 数安装 **erp-prod / erp-arq / erp-web**，自动写入环境变量（`APP_ENV=production`、`PYTHONPATH`、`PYTHONUTF8`、`PYTHONUNBUFFERED`、`UVICORN_WORKERS`）与依赖（`erp-prod→erp-redis`）。
2. 两个 Redis 服务按**步骤 4** 手工注册（管理器只负责「启动」，不负责安装）。
3. 安装可反复点击、幂等；会回读注册表核对服务指向。

若不用 GUI，手工 nssm 注册（要点，缺一不可）：

```powershell
C:\nssm\nssm.exe install erp-prod D:\erp_system\.venv\Scripts\python.exe
C:\nssm\nssm.exe set erp-prod AppParameters -m fastapi_app.core.prod_runner --no-arq
C:\nssm\nssm.exe set erp-prod AppDirectory D:\erp_system
C:\nssm\nssm.exe set erp-prod DependOnService erp-redis
# ⚠️ AppEnvironmentExtra 必须「一变量一元素」，整串塞进一个元素只会生效第一项
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

> 完整字段可对照机读快照 [config/nssm-services.json](config/nssm-services.json)（灾备重建五服务就是照它做）。
> ⚠️ `erp-arq` **必须** `DependOnService erp-redis-broker`。

**✅ 验收**：`Get-Service erp-prod,erp-arq,erp-web,erp-redis,erp-redis-broker | Format-Table Name,Status,StartType` 五服务齐全。

---

## 步骤 13 —— 启动与验收

**目标**：拉起全部服务并逐项验收。**启动顺序**（依赖已由 SCM 保证）：

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

# ④ ARQ 在线（用哨兵键，不要只看进程；broker 在 :6380）
C:\Redis\redis-cli.exe -p 6380 -a <REDIS_PASSWORD> TTL arq:queue:health-check   # 期望 0..61
C:\Redis\redis-cli.exe -p 6380 -a <REDIS_PASSWORD> GET arq:queue:health-check   # 含新鲜时间戳、j_failed=0

# ⑤ 一条命令跑完全部运行模式检查
.\.venv\Scripts\python.exe scripts\diag\runtime_mode_probe.py
#    期望：verdict=prod (multi worker …)、frontend.is_production=true、arq.verdict=running

# ⑥ 监督器状态文件（原子写入）
Get-Content D:\erp_system\logs\prod_runner.json    # ready:true 且 frontend_ok:true
```

> `logs/prod_runner.json` 里的 `mode/status` 字段**不可单独作为凭据**（启动窗口内可能陈旧），必须与上面的 HTTP/端口/ARQ 交叉验证。

**⚠️ 失败处理**：见文末「常见故障速查」。**五项全绿才算通过**，任何一项红都停下修复。

---

## 步骤 14 —— 备份调度与看门狗

**目标**：让定时备份与健康巡检真正跑起来。

- **备份**：应用内「备份中心」配置计划（真源是 `backup_schedule` 表，`scheduler_poller` 每 5 分钟扫表并补跑）。调度依附 **erp-arq** —— ARQ 停摆 = 定时备份静默停摆（巡检必查步骤 13④）。加密口令与 `BACKUP_ENCRYPTION_PASSWORD` 一致。
- **看门狗**（管理员）：

```powershell
powershell -ExecutionPolicy Bypass -File D:\erp_system\scripts\ops\install_watchdog_task.ps1
# 默认每 5 分钟以 SYSTEM 运行，检查：后端/就绪/ARQ/Web 入口/备份新鲜度/磁盘水位
.\.venv\Scripts\python.exe scripts\ops\watchdog.py --no-alert   # 手工只检查不告警
```

生产服务形态下把 `.env` 的 `WATCHDOG_EXPECT_SERVICES` 置 `true`（要求五服务 RUNNING）。

**✅ 验收**：手动触发一次备份 → `backups/` 出现新鲜产物；看门狗计划任务已注册且首轮检查通过。

---

## 步骤 15 —— 部署后检查清单（完成标准）

全部打勾才算部署成功：

- [ ] 五服务 `Start=Auto`、当前 RUNNING；`erp-prod` 依赖 `erp-redis`、`erp-arq` 依赖 `erp-redis-broker`
- [ ] `logs/prod_runner.json`：`ready=true`、`frontend_ok=true`
- [ ] `runtime_mode_probe.py` 三项 verdict 全部符合预期
- [ ] 浏览器从**另一台局域网机器**访问 `http://<主机IP>:3000` 能登录并跑通一笔业务
- [ ] 上传一张图片 → 刷新仍可见（验证签名 URL 链路）
- [ ] 触发一次手动备份 → `backups/` 出现产物且时间戳新鲜
- [ ] 看门狗计划任务已注册且首轮检查通过
- [ ] 已把 `_ops/credentials/` 中的真实凭据登记进组织级密码管理（不落文档）

---

## 步骤 16 —— 升级与回滚（日常发布）

```powershell
# 升级
git pull
cd frontend-vite && npm ci && npm run build      # 生产机若跑 dev server 先停
cd ..
.\.venv\Scripts\python.exe -m alembic -c migrations\alembic.ini upgrade head
# 管理员：nssm restart erp-prod（代码生效）；erp-arq 有任务变更时一并重启

# 回滚
#  前端：换回上一份 dist（发布前先自备份 dist）
#  后端：git checkout <上一个可用提交> + 重启 erp-prod
#  数据库：迁移只向前；需要回退结构时用 alembic downgrade <rev> 或从备份恢复（先评估数据丢失面）
```

---

## 常见故障速查

| 现象 | 先查什么 |
|---|---|
| 页面打不开 | `erp-web` 服务状态 + `curl :3000` 的 `Server: nginx` 头 |
| API 500 | `logs/erp-prod.log`、`logs/prod_runner.json`、`curl :5002/api/health` |
| 定时备份不跑 | `erp-arq` 是否运行（步骤 13④ 哨兵键）；ARQ 挂了备份静默停摆 |
| 每个 POST 慢 4 秒 | 两个 Redis 都要 `PING` 判活（端口 LISTENING 不代表握手正常） |
| 改 `UVICORN_WORKERS` 无效 | 重装过服务后以 NSSM 注入值为准；用探针确认实际 worker 数 |
| 上传图片 403/410 | `UPLOAD_URL_SIGNING_SECRET` ↔ `config/uploads-signing.conf` 是否逐字一致 |
| 日志 0 字节/乱码 | NSSM `AppEnvironmentExtra` 是否「一变量一元素」 |
| 迁移命令报 ImportError | 在仓库根执行，或改用 `-c migrations\alembic.ini` |
| 启动即退、报 `Could not parse SQLAlchemy URL` | `.env` 的 `DATABASE_URL=` 留空会覆盖 `DB_*` 拼接——填完整串或删该行 |
| WebSocket 全站 403 | `.env` 漏了 `WS_ALLOWED_ORIGINS` |

---

## 红线（会打挂生产，别做）

1. **不要删除**根 `utils/`（`fastapi_app/main.py` 直接 `from utils.redis_cache import ...`）、`fastapi_app/utils/`、`server_manager.py` + `server_manager/`。
2. **不要**把 `config/pgbouncer/userlist.txt` 或任何 `_ops/credentials/**` 加回版本库。
3. **不要**让 uvicorn 绑 `0.0.0.0`（绕过 nginx，并把 `/metrics` 暴露给同网段）。
4. **备份加密**：`BACKUP_ENCRYPTION_ENABLED` 是**总开关**；置 `true` 必须同时配好 `BACKUP_ENCRYPTION_PASSWORD`——密码为空时 `STRICT_CONFIG_CHECK=true` 下**拒绝启动**，否则**静默降级为不加密备份**。
5. **不要**改或删 `frontend-vite/vite.config.js`（它是 `vue-tsc -b` 编译 `vite.config.ts` 的设计产物，有回归测试）。
6. **不要**改 `core.hooksPath`（指到 husky 会废掉 `.githooks` 的密钥扫描）。
7. 迁移只做结构/数据变更，不夹带业务逻辑，保持单 head；**不得对生产库 autogenerate**。
8. 本机**既是生产主机也是运维主机**：没有独立测试环境，任何命令都直接影响在用业务——改动小步、可回滚。

---

## 相关文档

| 主题 | 位置 |
|---|---|
| **完整人工手册**（架构 / 运维 / 门禁 / API 约定） | [docs/PROJECT_MANUAL.md](docs/PROJECT_MANUAL.md) |
| 离线便携包一键部署（源机打包 → 目标机安装） | [deploy/README.md](deploy/README.md) |
| 服务生命周期与提权边界（操作前必读） | [docs/runbooks/service-lifecycle.md](docs/runbooks/service-lifecycle.md) |
| 环境变量：单一来源 / 漂移检查 / 灾备重建 | [docs/runbooks/env-config.md](docs/runbooks/env-config.md) |
| 项目协作契约（AI 与人都适用） | [AGENTS.md](AGENTS.md) |
