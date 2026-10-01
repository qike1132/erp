# P0 运维动作清单（需用户在场执行）— 2026-10-01

> 配套：`docs/optimization-plan-2026-10-01-final.md`（§1 P0-1 / P0-2 / P0-6 运维半）
> 以下动作**不在** `erp-p0-hardening` 团队委派范围内：它们改生产机 ACL、口令、计划任务与网络配置，且部分动作不可逆（旧备份口令改错会使历史 `.enc` 永久不可读）。
> 铁律：**一次只动一簇**；每步做完先验证再进下一步；`.env` 与 ACL 各留一份可回滚副本。

## 0. 执行顺序（勿颠倒）

1. P0-1-A ACL 收紧 → 2. P0-1-B 凭据迁出仓库 → 3. 服务重启验证 → 4. P0-2 恢复演练（**必须在改备份口令之前**）→ 5. P0-1-C 口令轮换（`BACKUP_ENCRYPTION_PASSWORD` 最后）→ 6. P0-2 运维半（watchdog / 告警出口 / 异地副本）→ 7. nginx reload + 后端重启（让 P0-6 的限流与转发头生效）。

---

## 1. P0-1 凭据与文件权限收口

### 1-A ACL 收紧（先备份，再收紧）
```powershell
# ① 备份整棵树 ACL（失败即停止，不要继续）
icacls D:\erp_system /save D:\erp_acl_backup\erp_system.acl /T
# ② 逐个目标收紧（示例：.env）
icacls D:\erp_system\.env /inheritance:r /grant:r "BUILTIN\Administrators:(OI)(CI)(F)" "NT AUTHORITY\SYSTEM:(OI)(CI)(F)" "NT AUTHORITY\NETWORK SERVICE:(OI)(CI)(F)" "DESKTOP-11111\Administrator:(OI)(CI)(F)"
```
对以下路径各做一次：`.env`、`.env.production`、`.env.development`、`_ops\credentials`、`config\pgbouncer\userlist.txt`、`backups`、`logs`、`certs`。
**验证**：`icacls <path>` 输出中不再出现 `BUILTIN\Users` 与 `NT AUTHORITY\Authenticated Users`；用非管理员账户 `Get-Content D:\erp_system\.env` 应被拒。
**回滚**：`icacls D:\erp_system /restore D:\erp_acl_backup\erp_system.acl`。
**注意**：本机上只有 `D:\erp_system` 带 `Mandatory Label\Low Mandatory Level:(OI)(CI)(NW)` 标签；若 `/inheritance:r` 后服务读不到配置（表现为 `prod_runner.json` 非 `ready`），先回滚 ACL 再排查标签来源。

### 1-B 凭据迁出仓库
1. 新建 `D:\erp_secrets\`（同样收紧 ACL），把 `_ops\credentials\` 下 `_backup_encryption_password.txt`(827B)、`_metrics_bearer_token.txt`(43B)、`.env.bak-20260911`、`.env.bak-20260927-085022` 迁入。
2. 代码侧读绝对路径环境变量（团队 P0-10 已把 `.env` 死键清掉；此处只改路径来源）。
3. 确认 `.gitignore` 含 `_ops/credentials/`，并 `git status --porcelain` 确认无凭据进入工作树。
4. **待你拍板**：`AGENTS.md:29`/`:70` 是否改指 `D:\erp_secrets\`（这是文档红线，改前需你确认）。

### 1-C 口令轮换（顺序严格）
```powershell
# 每个口令：先改服务端 → 再改 .env → 重启 → 验证 ready:true → 再动下一个
# ⚠ 不要一次改多个簇
```
1. `METRICS_BEARER_TOKEN` → 验证 `curl -H "Authorization: Bearer <新 token>" http://127.0.0.1:5002/metrics` 返回 200（未配 token 时 `/metrics` 是 503 fail-closed，见 `fastapi_app/core/health.py:198-214`）。
2. `DB_PASSWORD` / `REDIS_PASSWORD` → 改库/Redis 侧后同步 `.env`，重启验证 `logs/prod_runner.json` 的 `ready:true` 且 `frontend_ok:true`。
3. `BACKUP_ENCRYPTION_PASSWORD` **最后**，且**先完成第 2 节演练**证明现有 `.enc` 可解开。
**回滚**：`.env` 用 `.env.bak-20260927-085022` 回退（该备份应已迁出工作区）。

---

## 2. P0-2 运维半（代码半由团队完成）

### 2-A 恢复演练（改备份口令的**前置条件**）
```powershell
D:\erp_system\.venv\Scripts\python.exe scripts\restore_drill.py   # 演练库 erp_system_drill，不碰生产库
```
**验证**：输出 `status=ok`；`backups/server/recovery_tests/` 出现当日 `m5_drill_raw_*.json`（此前仅 1 份 2026-08-23，断档 39 天）。
**注意**：备份**没停**（ARQ cron：`0 2 * * *` 全量、`0 */1 * * *` 增量）；`\ERPSystem`、`\ERP_Database_Backup` 两个计划任务是 **Disabled 死任务**，不要按它们排障。

### 2-B watchdog 任务注册
```powershell
powershell -ExecutionPolicy Bypass -File D:\erp_system\scripts\ops\install_watchdog_task.ps1
schtasks /query /tn <任务名> /v /fo LIST   # 确认存在且 LastTaskResult=0
```
**验证**：任务存在、`logs/watchdog.log` 有新增；**回滚**：`Unregister-ScheduledTask`。

### 2-C 至少一个真实告警出口
在 `.env` 启用 `BACKUP_ALERT_WEBHOOK_ENABLED=true`（或 `BACKUP_ALERT_EMAIL_ENABLED=true`）并填 URL/收件人，做一次**真实投递**并确认收到。
**现状**：`SENTRY_DSN` 未设、`OTEL_ENABLED=false`、9090/3001/3100/8888/4317 均未监听、`config/prometheus.yml` targets 全是 docker 服务名、`config/alertmanager.yml` 出口被注释 ⇒ 目前**零出口**。
**回滚**：`BACKUP_ALERT_*` 置回 `false`。

### 2-D 异机/离线副本
最低标准：每日全量 `.zip.enc` 同步到另一台主机或移动盘，**记录校验和**并抽查一次可解。现状 `BACKUP_DIR=backups/server` 与生产同机同盘 ⇒ 主机/磁盘故障同时丢生产与备份。

### 2-E 演练与备份的门禁
把"演练产物 < 30 天""当日备份产物存在"做成 `scripts/prod_audit/` 门禁（团队不写该目录，留给你或下一批）。

---

## 3. 让 P0-6 的改动生效（团队改代码后由你执行）

```powershell
# ① nginx：limit_req_dry_run 转正后 reload（不是 restart）——**延后到观察期结束，转正是生产行为变更，需你签核**
#   转正点共 5 处，均在第 90/191/200/355/364 行附近（行号随他人改动漂移）：
#   锚点 = 紧随各 `limit_req zone=<name> nodelay;` 的那一行 `limit_req_dry_run on;` → 改为 off;
#   zone 名：perip / authzone（具体名以文件内 `limit_req_zone` 定义为准，见 config/nginx-windows.conf 顶部）
Select-String -Path D:\erp_system\config\nginx-windows.conf -Pattern 'limit_req_dry_run|limit_req_zone'
#   ⚠️ 转正前须知：并发会话（非本团队）已在同一文件加了 443/TLS 与 secure_link 相关内容（未提交）。
#      本团队对该文件贡献为 0，也未 git add；reload 前先用 -t 验语法，并确认你认可那部分改动。
#   ⚠️ OPT-18 注释要求「dry_run 观察 3-7 天无正常用户误伤后再改 reject」——若认可该观察期，此刻保持 on; 不改。
C:\nginx\nginx.exe -t -c D:\erp_system\config\nginx-windows.conf    # 先测语法
C:\nginx\nginx.exe -s reload -c D:\erp_system\config\nginx-windows.conf
# ② 后端：低峰期重启，随后确认 5002 只监听 127.0.0.1
Get-NetTCPConnection -State Listen | Where-Object LocalPort -eq 5002
# ③ 健康真源
Get-Content D:\erp_system\logs\prod_runner.json   # ready:true 且 frontend_ok:true
```
**验证限流真的生效**：用两个不同伪造 `X-Forwarded-For` 打 `/api/v1/auth/login`，应落入**同一个**限流桶（`--forwarded-allow-ips=127.0.0.1` 后客户端自带的左端条目被忽略）；再确认登录端点触发 429 而非无限放行。

---

## 4. 完成判据（全部满足才算 P0 收口）

- `icacls` 复查无 `Users`/`Authenticated Users`；非管理员账户读不到 `.env`
- `logs/prod_runner.json` `ready:true` 且 `frontend_ok:true`
- `recovery_tests/` 有当日产物且 `restore_drill.py` `status=ok`
- watchdog 任务 `LastTaskResult=0`，且至少一次真实告警投递有记录
- 备份包解压后可见 `nginx-windows.conf`/`security-headers.conf`/`redis-broker.conf`/NSSM 定义；`.meta` 数量与 `.enc` 一致
- 5002 仅监听 `127.0.0.1`；伪造 XFF 不再能切换限流桶；`customer_sampling` 无权限账号 403
- 团队侧：`quality_gate.py` PASS、`mypy` 通过、`pytest -q` 无新增失败（见 `docs/optimization-execution-ledger-2026-10-01.md`）

---

## 5. 可选：让本机门禁也覆盖依赖漏洞（`pip-audit`）

- 现状：`scripts/quality_gate.py` 的 `pip_audit` 门禁在本机因**未安装** `pip-audit` 而 **WARN 跳过**（见 `docs/optimization-plan-2026-10-01-final.md` §6.5），所以本机 [PASS] 不含真实漏洞库判定；CI 不受影响（`.github/workflows/ci-cd.yml:136` 以 `--only pip_audit --audit-report dependency-audit.json` 运行）。
- 动作（可选，**不阻塞 P0 收口**）：
```powershell
D:\erp_system\.venv\Scripts\python.exe -m pip install pip-audit
D:\erp_system\.venv\Scripts\python.exe scripts\quality_gate.py --only pip_audit
```
- 纪律：漏洞豁免**只能**加在 `pyproject.toml` 的 `[[tool.code-quality.pip-audit-ignores]]`（每项含 `id` / `expires`（ISO 日期，≤180 天）/ `reason`）；过期或僵尸条目会被门禁判 FAIL，不得用注释或跳过方式消红。
---

## 6. P1 批次上线步骤（团队代码已落地，需你在运维窗口执行）

### 6-A 迁移 061：给 `product.current_stock` 加非负 CHECK（本批唯一有生产风险的动作）

- 现状（t26-F-03 / t40-F-02 只读实测）：dev 库 `alembic_version` 仍停在 `pg_standalone_060_fix_updated_at_varchar_columns`，`pg_constraint` 中没有 `ck_product_current_stock_nonneg` ⇒ **代码侧守卫已生效，但 DB 兜底未启用**。
- 迁移文件：`migrations/versions/pg_standalone_061_add_product_stock_check.py`（down_revision = `pg_standalone_060_fix_updated_at_varchar_columns`，`alembic heads` 仍为单 head）。
- 步骤（按序，勿跳）：

```text
① 先看存量负值（用你惯用的客户端 psql/pgAdmin 执行这条只读 SQL，预期 neg_rows = 0）：
   SELECT COUNT(*) FILTER (WHERE current_stock < 0) AS neg_rows,
          MIN(current_stock) AS min_stock, COUNT(*) AS total FROM product;

② 按现有流程做一次备份（别手搓），确认备份产物可读。

③ 升级（加 -v 才能看到迁移的 INFO 日志；alembic.ini 默认 logger_root = WARN，见 §6.22 的 t40-F-05）：
   D:\erp_system\.venv\Scripts\python.exe -m alembic upgrade head -v

④ 复核：
   D:\erp_system\.venv\Scripts\python.exe -m alembic current
```

- **迁移是自适应的**：`neg_rows = 0` → 约束以 **VALID** 建立；`neg_rows > 0` → 以 **NOT VALID** 建立并在日志里 WARNING 打印条数（写入侧从此仍被拦，存量负值需人工对平后再执行）：

```sql
ALTER TABLE product VALIDATE CONSTRAINT ck_product_current_stock_nonneg;
```

- 回滚（downgrade 是 `DROP CONSTRAINT IF EXISTS`，幂等）：

```powershell
D:\erp_system\.venv\Scripts\python.exe -m alembic downgrade pg_standalone_060_fix_updated_at_varchar_columns
```

- ⚠️ 若日后确实要允许负库存：**仅把 `ALLOW_NEGATIVE_STOCK=true` 是不够的**，必须先 `ALTER TABLE product DROP CONSTRAINT ck_product_current_stock_nonneg`（见方案 §6.19：策略为真时应用层守卫不再附加，但 DB CHECK 仍会拒绝）。

### 6-B 代码侧已就绪、无需你操作

- **P1-1 库存只读对账**：默认关闭（`.env` 无 `INVENTORY_RECONCILE_ENABLED` ⇒ cron 不注册）。要启用就加 `INVENTORY_RECONCILE_ENABLED=true`（每日 03:30 跑，单条 GROUP BY LEFT JOIN，只读、不 commit、差异清单进日志）。
- **P1-7 ARQ 幂等键**：Redis 不可用时 fail-open（best-effort，只记 WARNING），无需配置。
- **P1-2 负库存策略**：`ALLOW_NEGATIVE_STOCK` 缺省 = 拒绝（与改动前行为等价），模板已声明。

### 6-C 提醒

- `alembic upgrade head` 会同时应用他人的后续迁移；当前 `alembic.ini` 自述为「100 revisions, exactly one head (`pg_standalone_061_add_product_stock_check`) and 4 roots」，`scripts/check_alembic_heads.py` 会把关单 head。
- 提交钩子冲突（方案 §6.9）未裁决前，本仓提交仍需 `--no-verify`；P1 提交时同样按路径显式挑选（工作树里有并发外部会话的未提交产物）。

### 6-D PG 连接预算（R-pg-connection-budget，上线前置）

- 现象：常驻服务（8 worker uvicorn + arq + prod_runner）空闲占用 64–65 条 `erp_app@erp_system` 连接；全量测试套件瞬时叠加最多 33 条测试库连接 ⇒ 客户端后端触达 `max_connections(100) − superuser_reserved_connections(3) = 97`，服务端记录 `致命错误:  remaining connection slots are reserved for roles with the SUPERUSER attribute`，客户端表现为建连期 `ConnectionResetError [WinError 10054]` / asyncpg `ConnectionDoesNotExistError`（方案 §6.25 有完整取证）。
- 三选一（按侵入性从小到大）：

```sql
-- ① 一次性回收长空闲连接（不重启、不改配置；应用侧 pool_pre_ping 会在下次取用时自动重建）
SELECT pg_terminate_backend(pid) FROM pg_stat_activity
 WHERE datname = 'erp_system' AND state = 'idle' AND backend_start < now() - interval '5 minutes';

-- ② 持久化空闲回收（推荐；reload 即可，不需重启）
ALTER SYSTEM SET idle_session_timeout = '5min';
SELECT pg_reload_conf();

-- ③ 抬高上限（需重启 PG，有短暂停机）
ALTER SYSTEM SET max_connections = 200;
```

- 说明：应用侧池参数由 `fastapi_app/core/database.py:25-57 _get_pool_config()` 按 `UVICORN_WORKERS` 与 `DB_MAX_CONNECTIONS` 反推（默认 8 worker × (pool_size 10 + max_overflow 3) ≈ 104 容量，故 64–65 条空闲属正常水位）；`pool_pre_ping=True` + `pool_recycle=1800` 使被回收的空闲连接在下一次取用时自动重建（毫秒级）。
- 注意：测试侧的 `tests/test_numbering_sequence_integration.py:53` 自建引擎用 SQLAlchemy 默认池（5+10=15），**不读** `DB_MAX_CONNECTIONS` ⇒ 给测试进程设该环境变量无法缓解（方案 §6.25 反向验证实验已证伪）。
