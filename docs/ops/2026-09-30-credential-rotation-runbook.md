# 凭据轮换操作手册（2026-09-30）

> **本文件不含任何密钥值**，可安全入库。所有 `<尖括号>` 都是待你替换的占位符。

## 0. 为什么必须轮换

2026-09-30 的项目审核中，三个真实凭据的值被打印进了 AI 会话记录（即离开本机、进入第三方模型服务）：

| # | 凭据 | 值形态 | 载体 | 当前是否在用 |
|---|---|---|---|---|
| **S1** | `PG_SUPER_PASSWORD` | 32 字符 | `.env:46` | **否** —— 应用代码从不读取（见 §2.1）<br>⚠️ 2026-10-09 起：备份恢复「重建数据库」会读取它，见 dump.py |
| **S2** | pgbouncer 三账号共享口令 | 26 字符 | `config/pgbouncer/userlist.txt`，**已被 git 跟踪** | 否 —— PGBouncer 未运行（见 §2.2） |
| **S3** | `BACKUP_ENCRYPTION_PASSWORD` | 42 字符 | `.env` | **是** —— 加密备份的唯一密钥来源（见 §2.3） |

**只把文件从 git 删除并不能修复泄露** —— 值已经离开了本机。唯一真正的补救是**在每个凭据的权威位置换掉它**。本手册按"先降影响面、再换值、最后验证"的顺序编排。

轮换三个凭据**不需要停服**：S1/S3 是配置值替换，S2 走文件与数据库角色。但请仍然选一个无人使用的时段做（本机是生产主机兼运维主机）。

---

## 1. 动手前的固定动作

### 1.1 先做快照（出任何问题都能回退）

```powershell
cd D:\erp_system
# 1) .env 快照（含旧值，用于回滚；做完轮换请按 §3.4 销毁）
Copy-Item .env "$env:TEMP\.env.before-rotation-20260930" -Force
# 2) pgbouncer 认证文件快照
Copy-Item config\pgbouncer\userlist.txt "$env:TEMP\userlist.txt.before-rotation-20260930" -Force
# 3) 加密备份清单快照（轮换后这些将不可恢复）
Get-ChildItem backups -Recurse -File -Filter *.enc      | Select-Object FullName,Length,LastWriteTime | Export-Csv "$env:TEMP\enc-backups-before.csv" -NoTypeInformation -Encoding UTF8
Get-ChildItem backups -Recurse -File -Filter *.enc.meta | Select-Object FullName,Length,LastWriteTime | Export-Csv "$env:TEMP\enc-meta-before.csv" -NoTypeInformation -Encoding UTF8
```

### 1.2 确认影响面（关键：先确认"谁在用"）

| 凭据 | 已知消费者 | 说明 |
|---|---|---|
| S1 `PG_SUPER_PASSWORD` | **无应用消费者**；仅人工运维（psql 手工登录取用） | 全仓 grep 只命中 `deliverables/**` 的审核报告，`fastapi_app/**` 零命中 |
| S2 userlist 口令 | PGBouncer（**当前未运行**，端口 6432 无监听） | 应用走 `DB_USER=erp_app` 直连 PostgreSQL，不经过 PGBouncer |
| S3 `BACKUP_ENCRYPTION_PASSWORD` | `fastapi_app/core/backup_encryption.py`、`fastapi_app/services/backup/crypto.py`、`fastapi_app/api/v1/endpoints/backup/_deps.py`、`.../validation.py`、`.../export.py`、`.../actions.py` | 优先级链：显式 password 参数 > `X-Backup-Password` 头 > 环境变量 |

**⚠️ 动手前请人工确认一件事**：除本机应用外，**是否有别的机器/脚本也使用 S1 或 S2 的同一个口令**（例如运维笔记本上的 psql、备份脚本、监控探针）。若有，轮换会让那些连接立即失败，需要同步改。

### 1.3 当前环境快照（供比对，非机密）

```
APP_ENV=production            FASTAPI_DEBUG=false          DB_TYPE=postgresql
DB_HOST=localhost             DB_PORT=5432                 DB_NAME=erp_system
DB_USER=erp_app               UVICORN_WORKERS=4            ALLOWED_HOSTS 含 192.168.0.95
BACKUP_ENCRYPTION_ENABLED=true   BACKUP_ENCRYPTION_ALGORITHM=AES256
BACKUP_ENCRYPTION_KEY_PATH=（空）  BACKUP_DIR=backups/server
备份产物：*.enc（加密）+ 同名 *.enc.meta —— 由每日/增量定时任务持续累积（2026-09-30 10:05 实测又新增 2 个）；另有 *.zip（明文）= 47 个
backups/.backup_encryption.key = 不存在
PostgreSQL 服务：postgresql-x64-18 = Running，postgresql-replica = Running（存在副本！）
```

---

## 2. 逐项操作

### 2.1 S1 —— PostgreSQL 超级用户口令

**先说清性质：`PG_SUPER_PASSWORD` 是"死键"**。`deliverables/audit-2026-09-17/审计报告-配置依赖部署.md:59` 早已判定它是"代码从不读取的键"，与 `FLASK_ENV`/`FLASK_DEBUG`/`API_URL`/`DB_POOL_*` 并列。所以：

> ⚠️ **2026-10-09 起不再是死键**：备份恢复需重建库（DROP/CREATE），而应用角色 `erp_app` 默认无
> `CREATEDB`，故 `dump.py` 改用它执行重建（未配置时回退 `DB_USER`）。轮换后**必须同步更新 `.env`**，
> 否则恢复会在建库权限预检处被拒绝（不会删库，但恢复无法进行）。

- 改这个值**不会**影响应用运行（应用用 `DB_USER=erp_app` + `DB_PASSWORD` 连库）。
- 但泄露的是**`postgres` 超级用户的口令** —— 拿到它等于完全接管数据库（含 `pg_read_server_files` 之类能力），**这是三件里最高危的**。
- 因此轮换动作发生在 **PostgreSQL 侧**，`.env` 里那行只是运维备注。

**步骤：**

```powershell
# ① 用旧的超级用户口令登录（或任何具备 CREATEROLE 的账号）
& "C:\Program Files\PostgreSQL\18\bin\psql.exe" -U postgres -h localhost -p 5432 -d postgres
```

```sql
-- ② 换掉口令（把 <新口令> 换成新生成的强口令）
ALTER ROLE postgres WITH PASSWORD '<新口令>';

-- ③ 顺手核查：还有哪些角色存在、是否有不该有的超权限
SELECT rolname, rolsuper, rolcreaterole, rolcanlogin FROM pg_roles ORDER BY rolname;

-- ④ 核查该口令是否还被别处复用（application/dblink 等）
SELECT * FROM pg_stat_activity;
```

```powershell
# ⑤ 更新 .env 中的备注值（它不参与运行，但要与实际一致）
#    用编辑器手工替换 .env 第 46 行的 PG_SUPER_PASSWORD 值，不要用脚本批量写，避免误伤其它行

# ⑥ 立刻验证新口令可登录、旧口令已失效
& "C:\Program Files\PostgreSQL\18\bin\psql.exe" -U postgres -h localhost -p 5432 -d postgres -c "SELECT current_user;"
```

**⚠️ 副本（replica）**：本机有 `postgresql-replica` 服务在 Running。`ALTER ROLE ... PASSWORD` 是 WAL 日志的普通变更，会随复制传到副本；但若副本上有独立连接使用该口令，请一并更新。

**回滚点**：若新口令有问题，用 §1.1 的 `.env` 快照与 psql 旧口令再执行一次 `ALTER ROLE`。

**顺手做（可选）**：`PG_SUPER_PASSWORD` 既然是死键，建议在 `.env` 里把那行注释掉并标注`# 非应用读取，仅运维手工使用`，避免下一个接手的人以为应用依赖它。同样的标注适用于 `FLASK_ENV`/`FLASK_DEBUG`/`API_URL`/`DB_POOL_RECYCLE`/`DB_MAX_OVERFLOW`。

### 2.2 S2 —— PGBouncer 三账号共享口令

**现状性质**：PGBouncer **没有在运行**（6432 端口无监听；`.env` 里甚至没有 `PGBOUNCER_ENABLED`，而 `fastapi_app/core/database.py:37` 默认取 `false`），所以它不是活跃攻击面 —— 但 `config/pgbouncer/userlist.txt` **被 git 跟踪**，那 26 字符口令就在仓库历史里，且三个数据库账号共用同一个口令、无权限隔离。

另外，现行文件格式本身是坏的：值以字面 `md5` 开头，但长度 26 字符 ≠ 合法 `md5`+32hex（应为 35 字符）；而两个 ini（`pgbouncer.ini`/`pgbouncer.windows.ini`）都设 `auth_type = scram-sha-256`，该模式本就要求存明文（见 `scripts/pgbouncer_gen_userlist.py:7` 的注释）。**所以正确做法是：存明文、但每账号一个独立强口令。**

**步骤：**

```sql
-- ① 为三个角色分别设置独立强口令（在 psql 里执行，<...> 逐个替换）
ALTER ROLE erp_app     WITH PASSWORD '<新口令A>';
ALTER ROLE erp_admin   WITH PASSWORD '<新口令B>';
ALTER ROLE erp_monitor WITH PASSWORD '<新口令C>';
```

```powershell
# ② 让脚本重新生成 userlist（口令通过环境变量/参数传入，不要写死在命令行历史里）
python scripts/pgbouncer_gen_userlist.py --help    # 先看它支持哪些传参方式
# ③ 生成后确认三个账号的口令互不相同、且文件格式与 auth_type=scram-sha-256 匹配
```

```powershell
# ④ 把该文件从 git 索引里摘掉（它已被 .gitignore 覆盖，见同批提交）
git rm --cached config/pgbouncer/userlist.txt
# ⑤ 提交时确认 userlist.txt.example（无口令的模板）仍在版本控制里
```

**⚠️ 如果 `erp_app` 的口令也要换**：注意 `.env` 的 `DB_PASSWORD` 正是 `erp_app` 的口令，应用靠它连库。换 `erp_app` 口令 = **改库 + 改 `.env` + 重启 API 进程**，属于会影响服务的操作。若你只想先摘掉 git 里的泄露，可以**只轮换 `erp_admin`/`erp_monitor` 两个非应用账号**，`erp_app` 留到下次维护窗口一并处理 —— 但请注意泄露的是"三账号共用口令"，只换两个、留一个复用旧值的意义有限，建议三个一起换。

**因为 PGBouncer 未运行，本项没有立即可验证的入口**。验证方式是：等真正启用 PGBouncer 时，用 `psql -h 127.0.0.1 -p 6432 -U erp_app -d erp_system` 逐个账号试连。

### 2.3 S3 —— 备份加密口令

**现状性质**：这是**唯一真正在用的泄露凭据**。

- `BACKUP_ENCRYPTION_ENABLED=true`、`ALGORITHM=AES256`（AES-256-GCM + PBKDF2 600k）。
- `BACKUP_ENCRYPTION_KEY_PATH` 为**空**、`backups/.backup_encryption.key` **不存在**、`.env` 里也没有 `BACKUP_ENCRYPTION_KEY`。
- ⇒ 密钥来源里**只有 `BACKUP_ENCRYPTION_PASSWORD` 一项**（`crypto.py:60-66` 的优先级链在 password 命中后即返回）。

**影响面可量化，但它是"移动靶"**：加密产物只有 `*.enc`（+ 同名 `.enc.meta`），而**每日/增量定时任务正在持续产出新的加密备份**（2026-09-30 10:05 实测：一次 `auto_daily_backup` 产出 4,482,348B、一次 `auto_incremental_backup` 产出 182,755B，均为 `.zip.enc`）。其余 47 个 `.zip` 是明文备份，**不受轮换影响**。你已确认历史加密备份可以弃置。

**步骤：**

```powershell
# ① 记录【轮换时刻之前】的全部加密备份（已在 §1.1 存过 CSV），确认它们确实可以弃置
Get-ChildItem backups -Recurse -File -Filter *.enc | Select-Object FullName,Length,LastWriteTime
```

```powershell
# ② 换掉 .env 里的 BACKUP_ENCRYPTION_PASSWORD 值（手工编辑，换成新的强口令）
#    建议：32+ 字符、含大小写数字符号；生成后同时写入 _ops/credentials/ 的安全存放处
```

```powershell
# ③ 归档/删除旧加密备份与孤儿元数据（先移到回收目录，别直接删）
$stale = Join-Path $env:TEMP 'stale-enc-backups-20260930'
New-Item -ItemType Directory -Path $stale -Force | Out-Null
Get-ChildItem backups -Recurse -File -Include *.enc,*.enc.meta | Move-Item -Destination $stale -Force
"已移出："; Get-ChildItem $stale | Measure-Object | Select-Object -ExpandProperty Count
```

```powershell
# ④ 重启 API 让新环境变量生效（生产由 NSSM 服务 erp-prod 托管，故用 nssm restart erp-prod）
# ⑤ 触发一次加密备份，并立即做一次还原验证 —— 这是唯一能证明新口令可用的方式
python -m pytest fastapi_app/tests/test_backup_encrypted_restore_path.py -q
```

**⚠️ 不要漏掉**：`_ops/credentials/_backup_encryption_password.txt`（827B）里存的是**旧口令**，轮换后必须同步更新或销毁，否则下一个人会拿着失效口令去还原新备份。

---

## 3. 收尾

### 3.1 轮换后自查清单

- [ ] S1：新口令能登录 `postgres`，旧口令已失败；`.env:46` 已同步
- [ ] S2：三个角色口令互不相同；`userlist.txt` 已 `git rm --cached`；`.gitignore` 已覆盖
- [ ] S3：`.env` 已换；**轮换时刻之前**的全部 `.enc`/`.enc.meta` 已移出 `backups/`；新的加密备份能创建**且能还原**
- [ ] `_ops/credentials/` 里对应的明文文件已更新或销毁
- [ ] §1.1 的三个快照文件已按 §3.4 销毁
- [ ] §4 的遗留问题已阅读

### 3.2 `.gitignore` 补充（随本手册同批提交）

`config/pgbouncer/userlist.txt` 此前**没有任何** ignore 规则（`git check-ignore` 返回 exit 1）。本批已补上，并同时补了 AI 工具痕迹的一批规则。

### 3.3 关于 git 历史重写（可选，我的建议是**不做**）

`config/pgbouncer/userlist.txt` 的旧口令**仍存在于 git 历史**中，当前分支只做 `git rm --cached` 不会消除历史记录。两个选项：

| 选项 | 代价 | 建议 |
|---|---|---|
| 只止血（`git rm --cached`） | 历史里仍可查到旧值 | **推荐**。理由是：口令已经轮换 → 历史里的旧值**失效**，不再是可利用凭据；仓库仅内网使用、无外部克隆 |
| 重写历史（`git filter-repo` / BFG） | 全部提交哈希改变；所有克隆者必须重新克隆；正在并发提交的 AI agent 会冲突 | 仅在仓库曾对外分发过时考虑 |

### 3.4 销毁快照

快照文件含**旧明文口令**，轮换验证通过后立即销毁：

```powershell
Remove-Item "$env:TEMP\.env.before-rotation-20260930","$env:TEMP\userlist.txt.before-rotation-20260930" -Force
```

---

## 4. 本手册写作时发现的遗留问题（与轮换无关，但请知情）

1. **【已修正】生产拓扑已核实为正常服役**。本手册初稿依据 09:47 的探测写了"三个 NSSM 服务全部 Stopped、由手工 node/python 进程顶替"——该判定**在当时成立**，但已被 10:05 起启动的生产模式取代，故在此更正：`erp-web` / `erp-prod` / `erp-arq` / `erp-redis` / `erp-redis-broker` 五个服务均 **Running / Automatic**；`logs/prod_runner.json` 报 `ready: true, frontend_ok: true`；nginx 3 个进程监听 `:3000`，`/nginx-health` 返回 `{"status":"ok","service":"nginx"}`；ARQ worker 正常执行定时任务（见第 5 条）。注意 `prod_runner.json` 里 `arq.status = "external"` 是**设计如此** —— `erp-prod` 以 `--no-arq` 启动，ARQ 由独立的 `erp-arq` 服务托管，而非监督器子进程。
2. **【已修正】API 当前不裸露**：09:47 探测时 5002 曾绑在 `0.0.0.0`；当前实测为 **`127.0.0.1:5002`**，符合 `prod_runner.py:178` 的"仅绑回环"设计，局域网无法绕过 nginx 直连后端。
3. **`BACKUP_ENCRYPTION_ENABLED=true` 而 `BACKUP_ENCRYPTION_KEY_PATH` 为空**：当前靠 `BACKUP_ENCRYPTION_PASSWORD` 单点支撑；若该变量将来被清空，按 `crypto.py:57-66` 会**降级为不加密备份**（`BACKUP_ENCRYPTION_FALLBACK_TO_GENERATED` 默认已是 false，不会退化成随机密钥）。
4. **`.env` 与 `.env.example` 双向漂移**：`.env` 有而 example 无 —— `PG_SUPER_PASSWORD`、`BACKUP_ENCRYPTION_PASSWORD`、`FLASK_ENV`、`FLASK_DEBUG`、`PGBOUNCER` 之外的多数 `BACKUP_*`；example 有而 `.env` 无 —— `PGBOUNCER_ENABLED`、`PGBouncer_HOST`、`PGBouncer_PORT`、`REDIS_URL`、`S3_*`、`STORAGE_TYPE`、`PROD_LOG_ROTATE_MB`、`SLOW_QUERY_*`。
5. **生产日志里发现的真实缺陷**（2026-09-30 10:05 的 `logs/erp-arq.log`，即"生产模式已正常服役"之后的新证据，与轮换无关但值得单独修）：
   - **增量备份静默跳过一张表**：`增量备份表 approval_log 失败: asyncpg.exceptions.DataError: invalid input for query argument $1: datetime.datetime(...) (expected str, got datetime.datetime)`，对应 SQL `SELECT * FROM "approval_log" WHERE "updated_at" >= $1`。异常被捕获后**备份仍报 success（`table_count: 32`）**，即增量备份链里长期缺 `approval_log` 的数据且无人告警。建议单独排查该表 `updated_at` 的列类型与参数绑定方式。
   - **`获取 PG 版本失败: [WinError 2] 系统找不到指定的文件`**：服务运行环境找不到 `pg_dump`/`psql`（PATH 缺失），数据库快照与版本探测因此降级。建议在 NSSM 服务环境或 `.env` 里显式给出 PostgreSQL `bin` 路径。
   - 旁证：`MeiliSearch 索引导出失败（可忽略）: All connection attempts failed`（日志自称可忽略）、`CPU使用率过高: 82.4% > 80.0%阈值`（备份窗口内的阈值告警）。
   - **运行时漂移**：`logs/prod_runner.json` 报 `workers: 8`，而 `.env` 写的是 `UVICORN_WORKERS=4` —— `load_dotenv(override=False)` 使**真实环境变量优先**，说明 `erp-prod` 服务环境里另设了 `UVICORN_WORKERS=8`，`.env` 的 4 在生产中不生效。

---

*生成于 2026-09-30，依据对 `D:\erp_system`（分支 `feat/production-cockpit-pc`）的实际探测。文中所有结论均附可复核的证据位置；所有凭据值均未写入本文件。*
