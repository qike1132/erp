# ERP 系统整机迁移方案

> 目标：将 ERP 系统及全部配套软件从当前服务器迁移到新服务器 `192.168.1.97`，迁移后项目路径保持不变（`D:\erp_system`），数据库全部数据完整迁移。

---

## 1. 迁移概述

### 1.1 源服务器现状（自动采集）

| 组件 | 版本/位置 | 端口 | 说明 |
|------|----------|------|------|
| 应用 | FastAPI (uvicorn)，`d:\erp_system` | 5002 | 多 worker，`prod_runner` 监督 |
| 前端 | Vue/Vite 构建产物 `frontend-vite\dist` | 3000 | Nginx 托管 |
| Nginx | Windows 版，配置 `config\nginx-windows.conf` | 3000 | 反代 `/api`、`/ws`、静态资源 |
| PostgreSQL | 16，`C:\Program Files\PostgreSQL\16\bin` | 5432 | 库 `erp_system`，用户 `erp_app` |
| 只读副本 | 同机流复制副本 | 5433 | 可选，本次不迁移，恢复后自动回退主库 |
| Redis 缓存 | `config\redis.production.conf` | 6379 | 密码由 `.env` 注入 |
| Redis 队列 | `config\redis-broker.conf` | 6380 | ARQ 任务队列实例 |
| ARQ Worker | `fastapi_app.core.arq_app.WorkerSettings` | - | 异步任务/定时任务 |
| Windows 服务 | NSSM：`erp-prod` + `erp-arq` | - | 开机自启、崩溃自愈 |

### 1.2 迁移策略

- **方式**：源服务器在线导出（pg_dump + 文件打包）→ 拷贝迁移包到新服务器 → 新服务器脚本自动恢复环境 → 注册服务 → 启动 → 验证。
- **路径**：迁移后项目仍在 `D:\erp_system`。`config\nginx-windows.conf`、`.env`、`prod_runner` 中的绝对路径均指向该目录，保持不变可免去大量配置修改。
- **数据库**：`pg_dump` 全库导出（含表结构、数据、序列、索引、扩展），`pg_restore` 恢复。导出过程**无需停库**（在线快照）。
- **Redis**：缓存/队列数据属可重建数据（缓存）与运行态任务（队列），**不迁移**，只在新服务器重建实例与密码配置。任务失败由 ARQ 重试，业务数据不受影响。

---

## 2. 需要打包的内容

### 2.1 必须打包的目录（均在 `D:\erp_system` 下）

| 目录 | 说明 |
|------|------|
| `fastapi_app\` | 后端源码（含 `core\prod_runner.py`、`arq_app.py`） |
| `frontend-vite\dist\` | 前端构建产物（已编译，无需重建） |
| `frontend-vite\src\` 等源码 | 前端源码（保留，便于后续维护） |
| `migrations\` | Alembic 迁移脚本 |
| `config\` | 全部运行配置（Nginx、Redis、PgBouncer、JWT、Prometheus 等） |
| `scripts\` | 数据库管理、部署等工具脚本 |
| `static\uploads\`、`static\files\`、`static\releases\` | 用户上传/导出/发布文件（**业务数据，必须迁移**） |
| `requirements\` | Python 依赖清单 |
| `tests\`、`utils\`、`docs\` | 测试与文档（可选，建议一并迁移） |

### 2.2 必须打包的配置文件

| 文件 | 说明 |
|------|------|
| `.env` | **核心**：数据库/Redis 密码、SECRET_KEY、JWT 路径、ALLOWED_HOSTS 等全部运行参数 |
| `config\jwt\private.pem` + `public.pem` | JWT RS256 密钥对，**丢失后所有已签发令牌失效** |
| `config\nginx-windows.conf` | 前端托管 + 反向代理配置（含绝对路径，路径不变则免改） |
| `config\redis.production.conf` / `config\redis-broker.conf` | 两个 Redis 实例配置模板 |
| `config\security-headers.conf` | Nginx 安全头（被 nginx-windows.conf include） |
| `server_manager.py` / `start.py` / `deploy-windows.ps1` | 管理入口与部署脚本 |

> `.env.production` / `.env.example` 为模板文件，仅作参考，实际生效的是根目录 `.env`。

### 2.3 不需要打包的内容

| 目录/文件 | 原因 |
|-----------|------|
| `node_modules\` | 前端已编译为 `dist`，无需依赖 |
| `.git\` | 版本历史留在源服务器即可 |
| `logs\`、`temp\` | 运行日志/临时文件 |
| `build\`、根目录 `dist\`、`*.spec` | PyInstaller 打包缓存 |
| `evidence\` | 测试取证材料 |
| `backups\` | 备份文件（建议保留源服务器；如磁盘允许也可带上） |
| `__pycache__`、`*.pyc` | 编译缓存，可自动重建 |

### 2.4 新服务器需要重新安装的软件（不随包传输）

| 软件 | 版本 | 安装位置要求 |
|------|------|-------------|
| Python | 3.12 | 需加入 PATH 或可通过 `python` 调用 |
| PostgreSQL | 16 | 默认 `C:\Program Files\PostgreSQL\16` |
| Redis | tporadowski/Redis for Windows | 建议 `C:\Redis\redis-server.exe` |
| Nginx | Windows 稳定版 | **必须 `C:\nginx\`**（`prod_runner` 按固定候选路径探测） |
| NSSM | latest | **必须 `C:\nssm\nssm.exe`**（`server_manager` 按固定候选路径探测） |
| Node.js | 20（可选） | 仅需重新构建前端时 |

---

## 3. 数据库导出

### 3.1 推荐方式：迁移脚本自动导出

在**源服务器**以管理员 PowerShell 执行：

```powershell
cd D:\erp_system
powershell -ExecutionPolicy Bypass -File scripts\migrate\export_on_source.ps1
```

输出：

```
D:\erp_migration_package\erp_migration_20260817_100000\
├── erp_system.dump        # 数据库全量导出（pg_dump -Fc 自定义格式，已压缩）
├── project\               # 项目文件（已排除垃圾目录）
└── manifest.txt           # 导出清单（含 dump 的 SHA256 校验和）
```

### 3.2 手动方式

```powershell
# 1. 导出数据库（custom 格式，自带压缩）
$env:PGPASSWORD="110110"
& "C:\Program Files\PostgreSQL\16\bin\pg_dump.exe" -h localhost -p 5432 -U erp_app `
  --no-owner --no-privileges -d erp_system -Fc -f D:\erp_migration_package\erp_system.dump
Remove-Item Env:PGPASSWORD

# 2. 校验导出（可选）
& "C:\Program Files\PostgreSQL\16\bin\pg_restore.exe" -l D:\erp_migration_package\erp_system.dump | Measure-Object
```

> 参数说明：`-Fc` 自定义压缩格式；`--no-owner/--no-privileges` 保证恢复时对象归属于新库连接用户 `erp_app`，避免源服务器角色信息缺失导致恢复失败。

### 3.3 导出前检查清单

- [ ] 确认磁盘空间充足（dump 约为数据库体积的 1/3，加上项目文件）
- [ ] 确认 `erp_app` 用户密码可从 `.env` 读取（脚本自动读取，也可 `-DbPassword` 参数覆盖）
- [ ] 建议在业务低峰期导出，避免大量写入导致 dump 体积偏大

---

## 4. 新服务器环境恢复

### 4.1 安装前置软件（手动，一次性）

1. **Python 3.12**：安装时勾选 *Add Python to PATH*。
2. **PostgreSQL 16**：安装时**记录 `postgres` 超级用户密码**（脚本需要它来创建应用角色/库）；组件可选 pgAdmin。
3. **Redis**：将 `redis-server.exe` 解压到 `C:\Redis\`（tporadowski/redis 的 Windows 发行版支持 `--service-install`）。
4. **Nginx**：解压到 `C:\nginx\`，确认 `C:\nginx\conf\mime.types` 存在。
5. **NSSM**：将 `nssm.exe` 放到 `C:\nssm\`。
6. （可选）Node.js 20：仅当前端需要重新构建时。

### 4.2 迁移包传输

将源服务器 `D:\erp_migration_package\` 整个拷贝到新服务器，例如放到 `D:\migration_in\`。

### 4.3 一键恢复（推荐）

在新服务器以管理员 PowerShell 执行（脚本可从任意路径运行，不受项目目录限制）：

```powershell
# 场景 A：迁移包（目录或 zip）尚未解压 —— 传入 -PackageZip
powershell -ExecutionPolicy Bypass -File D:\migration_in\setup_on_target.ps1 `
  -PackageZip "D:\migration_in\erp_migration_20260817_100000" `
  -PgSuperPassword "<安装 PostgreSQL 时设置的 postgres 密码>"

# 场景 B：项目已手动复制到 D:\erp_system（脚本会自动检测，跳过解包步骤）
#         只需将 setup_on_target.ps1 放到任意位置执行，并指定 dump 位置
powershell -ExecutionPolicy Bypass -File D:\migration_in\setup_on_target.ps1 `
  -TargetDir "D:\erp_system" `
  -PgSuperPassword "<postgres 密码>"
```

> 脚本位置：迁移包内的 `project\scripts\migrate\setup_on_target.ps1`；也可在源服务器上直接使用 `D:\erp_system\scripts\migrate\setup_on_target.ps1`（它随迁移包一起打包）。若项目已就位但 dump 文件未放在项目内，请先手动把 `erp_system.dump` 放到项目根目录。

脚本自动完成：

```
[1/8] 前置环境检查        Python / PostgreSQL / Redis / Nginx / NSSM
[2/8] 停止旧服务(若存在)    nssm stop erp-prod erp-arq
[3/8] 解压并复制项目到 D:\erp_system
[4/8] 恢复数据库           创建 erp_app 角色 → 创建 erp_system 库 → pg_restore
[5/8] 更新 .env            ALLOWED_HOSTS 追加 192.168.1.97；CORS 追加；副本配置注释
[6/8] 配置 Redis           生成部署 conf + requirepass + 注册双实例服务
[7/8] 注册 Windows 服务     NSSM: erp-prod + erp-arq
[8/8] 启动并验证           健康检查 /api/health、前端 3000、库表计数、Redis ping
```

### 4.4 手动方式（脚本不可用时）

见下方第 5、6 节命令，按顺序执行即可。

---

## 5. 权限与服务启动配置

### 5.1 PostgreSQL 服务

- 安装程序已注册服务 `postgresql-x64-16`（开机自启）。
- 确认运行账号有权限读写 `C:\Program Files\PostgreSQL\16\data`（默认 NetworkService）。

### 5.2 数据库角色与库（脚本自动执行，等价 SQL）

```sql
-- 以 postgres 超级用户执行
CREATE ROLE erp_app LOGIN PASSWORD '110110';               -- 密码与 .env 保持一致
CREATE DATABASE erp_system OWNER erp_app;
```

> 脚本会先判断是否存在，幂等执行。

### 5.3 Redis 双实例（脚本自动执行）

脚本将 `config\redis.production.conf` / `config\redis-broker.conf` 复制到 Redis 目录生成部署版配置（自动追加 `requirepass <REDIS_PASSWORD>`），并注册两个服务：

```powershell
# 缓存实例 6379
C:\Redis\redis-server.exe --service-install C:\Redis\erp-redis.conf --service-name Redis
# ARQ 队列实例 6380
C:\Redis\redis-server.exe --service-install C:\Redis\erp-redis-broker.conf --service-name RedisBroker
net start Redis
net start RedisBroker
```

> 若 `--service-install` 不受支持（非 tporadowski 发行版），脚本自动回退用 NSSM 托管两个 redis-server 进程。

### 5.4 Nginx

- Nginx 由 `prod_runner` 负责拉起（`nginx -p D:\erp_system -c config\nginx-windows.conf`），**无需注册 Windows 服务**。
- 路径保持 `D:\erp_system` 时，`nginx-windows.conf` 中的绝对路径 include/alias 无需修改。
- 确认 `C:\nginx\conf\mime.types` 存在，否则前端静态资源 MIME 错误。

### 5.5 NSSM 服务（erp-prod / erp-arq）

脚本自动注册，等价命令如下（供排障参考）：

```powershell
$env:APP_ENV='production'; $env:FASTAPI_DEBUG='false'; $env:PYTHONPATH='D:\erp_system'
$env:PYTHONUTF8='1'; $env:PYTHONUNBUFFERED='1'; $env:UVICORN_WORKERS='4'

# erp-prod：后端监督器（--no-arq 表示 ARQ 由独立服务托管，避免双跑定时任务）
C:\nssm\nssm.exe install erp-prod python
C:\nssm\nssm.exe set erp-prod AppParameters "-m fastapi_app.core.prod_runner --no-arq"
C:\nssm\nssm.exe set erp-prod AppDirectory D:\erp_system
C:\nssm\nssm.exe set erp-prod AppEnvironmentExtra "APP_ENV=production FASTAPI_DEBUG=false PYTHONPATH=D:\erp_system PYTHONUTF8=1 PYTHONUNBUFFERED=1 UVICORN_WORKERS=4"
C:\nssm\nssm.exe set erp-prod AppStdout D:\erp_system\logs\erp-prod.log
C:\nssm\nssm.exe set erp-prod AppStderr D:\erp_system\logs\erp-prod.log
C:\nssm\nssm.exe set erp-prod AppExit Default Restart
C:\nssm\nssm.exe set erp-prod AppRestartDelay 5000
C:\nssm\nssm.exe set erp-prod Start SERVICE_AUTO_START

# erp-arq：异步任务 Worker
C:\nssm\nssm.exe install erp-arq python
C:\nssm\nssm.exe set erp-arq AppParameters "-m arq fastapi_app.core.arq_app.WorkerSettings"
C:\nssm\nssm.exe set erp-arq AppDirectory D:\erp_system
C:\nssm\nssm.exe set erp-arq AppEnvironmentExtra "APP_ENV=production FASTAPI_DEBUG=false PYTHONPATH=D:\erp_system PYTHONUTF8=1 PYTHONUNBUFFERED=1 UVICORN_WORKERS=4"
C:\nssm\nssm.exe set erp-arq AppStdout D:\erp_system\logs\erp-arq.log
C:\nssm\nssm.exe set erp-arq AppStderr D:\erp_system\logs\erp-arq.log
C:\nssm\nssm.exe set erp-arq AppExit Default Restart
C:\nssm\nssm.exe set erp-arq AppRestartDelay 5000
C:\nssm\nssm.exe set erp-arq Start SERVICE_AUTO_START
```

### 5.6 防火墙

放行内网访问所需端口（按需）：

```powershell
netsh advfirewall firewall add rule name="ERP Web 3000" dir=in action=allow protocol=TCP localport=3000
netsh advfirewall firewall add rule name="ERP API 5002" dir=in action=allow protocol=TCP localport=5002
# 数据库/Redis 仅建议内网白名单，如需远程管理再放行 5432/6379/6380
```

---

## 6. 迁移后验证步骤

### 6.1 自动验证（脚本 [8/8]）

| 检查项 | 方法 | 期望 |
|--------|------|------|
| 后端健康 | `Invoke-WebRequest http://127.0.0.1:5002/api/health` | HTTP 200 |
| 前端页面 | `Invoke-WebRequest http://127.0.0.1:3000` | HTTP 200 |
| 数据库连通 | `psql -U erp_app -d erp_system -c "SELECT count(*) FROM pg_tables WHERE schemaname='public'"` | 返回表数 |
| Redis 连通 | `redis-cli -a <password> ping`（两个端口 6379/6380） | PONG |

### 6.2 手动验证

- [ ] 浏览器访问 `http://192.168.1.97:3000`，使用 admin 账号登录
- [ ] 抽查业务数据：订单列表、客户列表、库存等页面与源服务器一致
- [ ] 上传一个文件，确认 `static\uploads\` 出现且前端可预览
- [ ] 触发一个异步任务（如报表导出），确认 `logs\erp-arq.log` 有执行记录
- [ ] 重启服务器后确认服务自动恢复（`erp-prod`、`erp-arq`、Redis、PostgreSQL 均为自动启动）
- [ ] 检查 `logs\prod_runner.json`，`ready: true`，`services.backend.status: "ready"`

---

## 7. 一键迁移脚本（供 AI 助手执行）

### 7.1 文件清单

| 脚本 | 位置 | 作用 |
|------|------|------|
| `export_on_source.ps1` | `D:\erp_system\scripts\migrate\` | 源服务器导出：数据库 + 项目打包 |
| `setup_on_target.ps1` | 随迁移包带到新服务器 | 新服务器一键恢复：解包 → 数据库 → 配置 → 服务 → 启动 → 验证 |

### 7.2 AI 助手执行步骤

**阶段 A（源服务器）：**

1. 确认在 `D:\erp_system`，运行 `export_on_source.ps1`，得到 `D:\erp_migration_package\erp_migration_<时间戳>\`。
2. 检查 `manifest.txt` 与 `erp_system.dump` 大小是否合理。

**阶段 B（新服务器 192.168.1.97）：**

1. 确认前置软件已安装（Python/PostgreSQL/Redis/Nginx/NSSM）。
2. 把迁移包整个放到新服务器某路径，如 `D:\migration_in\`。
3. 运行 `setup_on_target.ps1 -PackageZip <迁移包路径> -PgSuperPassword <postgres密码>`。
4. 逐项确认输出中的 `[OK]`，出现 `=== 迁移完成 ===` 即成功。
5. 执行 6.2 手动验证清单。

### 7.3 参数速查

`export_on_source.ps1`：

| 参数 | 默认 | 说明 |
|------|------|------|
| `-ProjectDir` | `D:\erp_system` | 项目根目录 |
| `-OutputDir` | `D:\erp_migration_package` | 迁移包输出位置 |
| `-DbPassword` | 从 `.env` 读取 | 数据库密码 |
| `-IncludeBackups` | 关 | 是否把 `backups\` 一并打包 |

`setup_on_target.ps1`：

| 参数 | 默认 | 说明 |
|------|------|------|
| `-PackageZip` | - | 迁移包路径（目录或 zip 均可） |
| `-TargetDir` | `D:\erp_system` | 目标项目路径（迁移后路径不变） |
| `-NewServerIP` | `192.168.1.97` | 追加到 `ALLOWED_HOSTS` / CORS |
| `-PgSuperPassword` | - | **必填**：postgres 超级用户密码（创建角色/库用） |
| `-DbPassword` | 从 `.env` 读取 | 应用库密码（需与源服务器一致） |
| `-SkipDbRestore/-SkipRedis/-SkipNginx/-SkipNssm/-SkipStart/-SkipVerify` | 关 | 跳过对应步骤（排障/局部重跑用） |

---

## 8. 风险与注意事项

1. **密码安全**：源库 `DB_PASSWORD=110110` 为弱密码，`.env` 亦含 SECRET_KEY 与 JWT 私钥。迁移包请**加密传输**（如压缩包加密码），完成后新服务器建议更新密码并同步 `.env`（注意 `erp_app` 库密码、Redis 密码需一致）。
2. **路径一致性**：迁移后路径必须保持 `D:\erp_system`。若目标盘符不同，需全局替换 `.env`、`nginx-windows.conf`、`prod_runner` 中的路径。
3. **只读副本**：`.env` 中 `ASYNC_DATABASE_REPLICA_URL` 指向 5433 副本，迁移脚本会自动注释该行，应用回退主库（代码已支持）。如需读写分离，可后续再搭建副本并取消注释。
4. **定时任务双跑**：`erp-prod` 以 `--no-arq` 启动监督器，ARQ 由独立 `erp-arq` 服务托管。切勿在新旧服务器**同时**运行 ARQ，否则定时任务双跑。
5. **回滚**：源服务器在新服务器验证通过前**不要停机**。若新服务器异常，直接继续使用源服务器即可。
6. **磁盘空间**：PostgreSQL 数据目录迁移后需额外预留 dump 导入临时空间。

---

## 9. 相关文档

- `docs/DATABASE_BACKUP_RECOVERY_GUIDE.md` — 备份/恢复详述
- `deploy-windows.ps1` — 原生部署脚本（含流复制/PgBouncer 配置参考）
- `README_DEPLOY.txt` — 快速部署说明
- `server_manager.py` — 服务管理器（生产托管面板）
