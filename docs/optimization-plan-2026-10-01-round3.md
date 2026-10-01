# 滨发协同系统 · 优化方案（第 3 轮，落地版）

- 依据：`docs/architecture-audit-round3-2026-10-01.md`（第 3 轮评审，逐条带 `路径:行号`）
- 定位：**可执行工单清单**。每项 = 问题 → 证据 → 变更 → 验证 → 回滚 → 工时 → 风险
- 与既有方案的关系：`docs/optimization-plan-2026-10-01-round2.md`（1040 行，未开工）保留为**设计档案**；本方案**只选取其中能被本轮证据支撑、且可在生产机安全落地**的部分，并按"先止血、后治病"重排。二者冲突时以本方案为准。
- 前四项（凭据 / 指标 / 门禁旁路 / 时钟）的**可执行改动清单**：`docs/p0-exec-checklist-2026-10-01.md`（含实测 ACL、逐行 diff、验证命令与回滚）。
- 生产约束（不可违反）：这台机器既是生产主机也是运维主机，**无独立测试/预发环境**；唯一启动入口 `python start.py`；健康真源 `logs/prod_runner.json`（需 `ready:true` 且 `frontend_ok:true`）；改动必须小步可回滚；`AGENTS.md` §5 七条红线不得触碰（尤其：不可改 `frontend-vite/vite.config.js`、不可让 uvicorn 绑 `0.0.0.0`、Alembic 保持单 head）。

---

## 0. 批次总览

| 批次 | 主题 | 项数 | 预计工时 | 风险 | 建议窗口 |
|---|---|---|---|---|---|
| **P0** | 止血：凭据、备份与 DR、告警出口、可观测、时钟、权限口子、门禁旁路、已知功能缺陷 | 12 | 4–5 人日 | 低（全部可回滚） | 立即，分 4 个窗口 |
| **P1** | 收口：库存不变量、并发与幂等、门禁机械化、契约校验 | 12 | 8–12 人日 | 中 | 1 周内 |
| **P2** | 补齐：前端减重、传输安全、审计字段、类型与测试欠账 | 12 | 12–18 人日 | 中 | 1 个月内 |
| **P3** | 结构性：库存单一真相、拆分上帝对象、字段级审计、行级权限 | 6 | 20–30 人日 | 高（需专项评审） | 单独排期 |
| **P4** | 治理：执行台账、门禁对象纠偏、验收标准 | 3 | 持续 | — | 与 P0 同步启动 |

**贯穿原则**：①每项独立可回滚；②每项带验证命令；③先"只读观测"再"改写入路径"；④任何"存量数据不满足新约束"的情况，先出对账数据再上约束。

---

## 1. P0 · 止血（12 项，4–5 人日）

### P0-1 凭据与文件权限收口 ★最高优先
- **问题**：根 `.env` 含 `SECRET_KEY`/`DB_PASSWORD`/`REDIS_PASSWORD`/`PG_SUPER_PASSWORD`/`BACKUP_ENCRYPTION_PASSWORD`/`METRICS_BEARER_TOKEN`；实测 ACL 含 `NT AUTHORITY\Authenticated Users:(I)(M)` 与 `BUILTIN\Users:(I)(RX)` → 本机任一已认证用户可读。
- **证据**：`icacls D:\erp_system\.env`（本轮实测）；`_ops/credentials/` 内 `_backup_encryption_password.txt`(827B)、`_metrics_bearer_token.txt`(43B)、`.env.bak-20260911`、`.env.bak-20260927-085022`。
- **变更**：
  1. 先备份 ACL：`icacls D:\erp_system /save D:\erp_acl_backup\erp_system.acl /T`
  2. 取消继承并只保留必要主体（对 `.env`、`.env.production`、`.env.development`、`_ops\credentials`、`config\pgbouncer\userlist.txt`、`backups`、`logs`、`certs`）：
     ```
     icacls <path> /inheritance:r /grant:r "BUILTIN\Administrators:(OI)(CI)(F)" "NT AUTHORITY\SYSTEM:(OI)(CI)(F)" "NT AUTHORITY\NETWORK SERVICE:(OI)(CI)(F)" "DESKTOP-11111\Administrator:(OI)(CI)(F)"
     ```
  3. `_ops/credentials/` 整体移到仓库外（如 `D:\erp_secrets\`），代码里改为读绝对路径环境变量；确认 `.gitignore` 已含 `_ops/credentials/`。
  4. 轮换 `METRICS_BEARER_TOKEN`、`DB_PASSWORD`、`REDIS_PASSWORD`（**顺序**：改库/Redis 侧 → 改 `.env` → 重启服务 → 验证 `prod_runner.json`）。
  5. `BACKUP_ENCRYPTION_PASSWORD` **必须最后再改**，且改前先跑一次 P0-2 的恢复演练，确认现有 `.enc` 可解开（否则旧备份永久不可读）。
- **验证**：`icacls` 复查无 `Users`/`Authenticated Users`；用非管理员账户 `Get-Content .env` 应被拒；服务重启后 `logs/prod_runner.json` `ready:true`；`curl -H "Authorization: Bearer <新 token>" http://127.0.0.1:5002/metrics` 返回 200。
- **回滚**：```icacls D:\erp_system /restore D:\erp_acl_backup\erp_system.acl```；`.env` 用 `.env.bak-20260927-085022` 回退（该备份也应移出工作区）。
- **工时**：0.5–1 人日。**风险**：口令轮换顺序错误会起不来 → 保持 `.env.bak` 在手且一次只改一簇密钥。

### P0-2 让演练与告警重新为真（备份本身在跑）
- **问题（先纠正直觉）**：备份**没有停摆**——调度由 erp-arq 的 ARQ cron 驱动（`BACKUP_FULL_CRON=0 2 * * *`、`BACKUP_INCREMENTAL_CRON=0 */1 * * *`），产物如 `erp_auto_daily_20261001_020013.zip.enc`（4.5MB）+ `.meta`；Windows 计划任务 `\ERPSystem`、`\ERP_Database_Backup` 均为 **Disabled 的死任务**（**不要**再按它们排障）。真正断的是四件事：
  (a) **恢复演练断档 39 天**：`backups/server/recovery_tests/` 仅 1 份（`m5_drill_raw_20260823.json`，2026-08-23），`cleanup_reports` 停在 2026-08-20，与 `BACKUP_RECOVERY_TEST_FREQUENCY=7` 不符；
  (b) **主动告警通道为零**：`.env` 未设 `SENTRY_DSN`、`OTEL_ENABLED=false`、`BACKUP_ALERT_EMAIL_ENABLED=false`、`BACKUP_ALERT_WEBHOOK_ENABLED=false` 且 URL 为空；9090/3001/3100/8888/4317 均未监听；watchdog 计划任务未注册（`schtasks` 找不到、`logs/` 无 `watchdog.log`），而 `scripts/ops/watchdog.py` 与 `install_watchdog_task.ps1` 都在仓库里；`config/prometheus.yml` 的 targets 全是 docker 服务名（`app:5002` 等）、`config/alertmanager.yml` 的邮件/钉钉段被注释 ⇒ **没有任何出口**；
  (c) **演练脚本已过期**：`scripts/restore_drill.py:35-39` 只 glob `erp_backup_*.zip`，对当前生产格式（`*.zip.enc`）必然 SystemExit（应用内演练 `fastapi_app/services/backup/recovery_test_service.py:245-248/:330-337` 已 enc 感知，两条链路不一致）；
  (d) **DR 无法闭环（blocker）**：备份包白名单 `fastapi_app/services/backup/_constants.py:89-104` 只收 `config/` 下的 `.env.production`、现役 JWT 钥、`redis.production.conf`、`nginx.conf` + 根 `.env`，缺**生效的** `nginx-windows.conf`、`security-headers.conf`、`redis-broker.conf`、NSSM 服务定义；`BACKUP_DIR=backups/server` 与生产同机同盘且无异地副本 ⇒ 主机/磁盘故障同时丢生产与备份。
- **证据**：`backups/server/` 产物清单、`.env` 的 `BACKUP_ALERT_*`/`OTEL_ENABLED`、`Get-NetTCPConnection -State Listen`、watchdog 任务查询、`scripts/restore_drill.py:35-39`、`services/backup/_constants.py:89-104`、`config/prometheus.yml`、`config/alertmanager.yml`。
- **变更**：
  1. 修 `scripts/restore_drill.py:35-39`：同时匹配 `erp_backup_*.zip` 与 `erp_backup_*.zip.enc`，取最新，口令缺失时**显式报错**（不静默按明文处理）。
  2. 手动跑完整链路一次：备份 → `python scripts/restore_drill.py`（演练库 `erp_system_drill`，不碰生产库）→ 落新的 `m5_drill_raw_*.json`。
  3. 注册 watchdog 任务（`scripts/ops/install_watchdog_task.ps1`）并**至少启用一个告警出口**（webhook 或邮件），做一次真实投递验证。
  4. 把"演练产物存在且 < 30 天""当日备份产物存在"做成 preflight/门禁（放 `scripts/prod_audit/`）。
  5. 备份包补入 `nginx-windows.conf`、`security-headers.conf`、`redis-broker.conf`、NSSM 定义（改 `_constants.py` 白名单 + 补守卫测试）。
  6. 建立异机或离线副本（最低：每日全量包同步到另一台主机/移动盘并记录校验和）。
  7. 保留策略收敛为单一真源：`fastapi_app/services/backup/records.py:563-640` 硬编码 30 天/50 份，而 `policy_service.py:49-52`、`cleanup/service.py:60-63` 读 env 的 30 天/100 份 ⇒ 统一走 env；并把 `.zip.enc.meta` 加入清理匹配（当前删 `.enc` 后 `.meta` 永久残留）。
  8. 核对增量包 mtime 比文件名时间戳晚约 8 小时（推测 UTC 命名 vs 本地时间），确认后统一时间语义。
- **验证**：watchdog 任务存在且 LastTaskResult=0；演练产物为当日；`restore_drill.py` 输出 `status=ok`；一次真实告警投递有记录；备份包解压后可见 4 个补齐的配置文件；`.meta` 数量与 `.enc` 一致。
- **回滚**：`Unregister-ScheduledTask`；白名单/保留策略 `git revert`；告警出口可关（`BACKUP_ALERT_*` 置回 false）。
- **工时**：2–2.5 人日。**风险**：演练占磁盘与 IO（演练库独立，不影响生产）；异地副本需先确认目标空间与网络。

### P0-3 给"响应已发出、提交失败"装仪表
- **问题**：`fastapi_app/core/database.py:226-240` 注释明写"commit 失败时客户端已收到成功响应"，当前只 `logger.error` + `rollback` + `raise`，**无任何指标/计数**，无法告警与统计。
- **变更**：在该 `except` 分支增加 Prometheus 计数（复用现有注册器，先 grep 指标定义位置，避免重复注册）：
  ```python
  from fastapi_app.core.metrics import db_commit_failures_total  # 名称以仓库现有约定为准
  db_commit_failures_total.labels(path=request.url.path).inc()
  ```
  并把结构化日志（含 `request.state.request_id`、`settings.DB_NAME`）一起输出。
- **验证**：新增单测（monkeypatch `session.commit` 抛 `SQLAlchemyError` → 计数 +1、异常仍向上抛）；`/metrics` 抓取含新指标名。
- **回滚**：纯新增，回退即删除。
- **工时**：0.5 人日。**风险**：无。

### P0-4 统一审批域时钟
- **问题**：`fastapi_app/shared_models/approval.py:56` `default=_utcnow` 与 `:61` `default=datetime.now`（另 `:128` 对 `:130` 同款）→ 同一张表两套时钟，差 8 小时，时间不可作证据。
- **变更**：`:61`/`:130` 改为 `_utcnow`（与同表其他时间列一致）。
- **验证**：单测断言两条记录的时间差 < 1 分钟（对同一操作）；抽查 `approval_time` 与 `request_time` 的分布一致性。
- **回滚**：还原两行。
- **工时**：0.5 人日。**风险**：历史数据语义仍是"naive 本地时间"，需在文档标注；**完整修复（naive→timestamptz）属 P2-9**，本项只消除"同表两套时钟"。

### P0-5 业务日口径统一（库存）
- **问题**：`fastapi_app/services/stock_common.py:15-19` 用 `datetime.now(UTC)` 的时分秒拼 naive 业务时间 → 北京时间 00:00–08:00 之间的入库会落到前一天。
- **变更**：抽公共 `business_now()`（时区源直接用现有 `fastapi_app/services/numbering_sequence.py:27` 的 `_BUSINESS_TZ`），`stock_common.py` 改用它。
- **验证**：单测：给定 `date_str='2026-10-01'`，断言生成时间为北京时间当日（在 CI 里用固定 `TZ` 断言）。
- **回滚**：还原 1 行 import/调用。
- **工时**：0.5 人日。**风险**：会影响"当天入库单"的日期展示，需在变更说明里写明并抽查 1 天数据。

### P0-6 暴露面与限流口子
- **问题与证据**：
  (a) `fastapi_app/api/v1/endpoints/customer_sampling.py:63` `router = APIRouter()`，权限点只在写端点（`:126/:149/:182/:199/:215/:261/:294/:312`），9 个 GET 无模块级权限；
  (b) `fastapi_app/main.py:256-271` 限流键未登录时回落 `get_remote_address`（slowapi 实现只读 `request.client.host`，`.venv/Lib/site-packages/slowapi/util.py:20-27`）——**但该 host 已被 uvicorn 用 XFF 重写成客户端可控值**：`fastapi_app/core/prod_runner.py:267-268` 传 `--proxy-headers --forwarded-allow-ips=*`，`.venv/Lib/site-packages/uvicorn/middleware/proxy_headers.py:163-164` 在 `always_trust` 时取 XFF **最左值**，而 `config/nginx-windows.conf:60` 用 `$proxy_add_x_forwarded_for` 把客户端自带的头原样保留在最左 ⇒ 换一个伪造 XFF 就换一个限流桶，**限流可被绕过**（对照：审计 IP 取 XFF 最右值 `audit_middleware.py:134-138`/`:202-205`，不可伪造）；
  (c) `scripts/restart_backend.py:66` 使用 `--host 0.0.0.0`（与红线 §5.3 冲突）；
  (d) `config/pgbouncer/pgbouncer.ini:15` `listen_addr = 0.0.0.0`。
- **变更**：
  (a) 先 `grep -rn "customer_sampling" frontend-vite/src` 与 `grep -rn "customer_sampling_manage" fastapi_app` 核对调用方与权限码发放范围；确认后给 router 加 `dependencies=[Depends(require_any_permission(PERM, ...))]`（若只读角色必须可访问，则按端点逐个加读权限，而不是整树放开）。
  (b) 把 `core/prod_runner.py:268` 的 `--forwarded-allow-ips=*` 改成 `--forwarded-allow-ips=127.0.0.1`（保留 `--proxy-headers`）：uvicorn 会**从右往左**取第一个不可信地址，即 nginx 追加在最右的真实客户端地址，客户端伪造的左端条目被忽略 → `request.client.host` 变可信，限流键与审计日志同时正确。**不要**改用 slowapi 的 `get_ipaddr`（它无条件信任整个 `X-Forwarded-For`）。
  (c) `restart_backend.py:66` 改 `127.0.0.1`。
  (d) `pgbouncer.ini:15` 改 `127.0.0.1`，并确认应用连接串指向 `127.0.0.1:6432`；同时复核 `pg_hba.conf` 是否允许非本机来源。
- **验证**：`Get-NetTCPConnection -State Listen` 复查 5002 仅 `127.0.0.1`；模拟 2 个来源打匿名登录端点，确认各自独立计数（用日志或慢api 头）；`customer_sampling` GET 在无权限账号下返回 403。
- **回滚**：启动参数/配置行均可单行回退；router 依赖回退即恢复原状。
- **工时**：1 人日。**风险**：(a) 可能影响只读用户（先核对再改，必要时只保护含价格/客户信息的查询）；(b) 需重启后端，选低峰窗口并验证 `ready:true`。

### P0-7 封堵事务门禁的注释旁路
- **问题**：`scripts/check_service_commit.py:32-39` 的 `ALLOWED_PATTERNS` 含 `r"#\s*independent[-_]transaction"`，与 `docs/TRANSACTION_BOUNDARY_GUIDE.md:48`「脚本不会因为该注释而跳过」**直接矛盾**；导致 `backup/cleanup/service.py:599`、`backup/metrics/alert_service.py:222`、`backup/orchestration/policy_service.py:544` 被静默豁免。
- **变更**：
  1. 删除该白名单项（连同行内零命中的宽规则 `r"#.*commit\("`）。**不要另造标记**：`docs/TRANSACTION_BOUNDARY_GUIDE.md:40-48` 规定的例外标记就是 `# manual-tx: <为什么必须现在提交>`，并明确"脚本不会因该注释跳过"——三处豁免行本就带 `manual-tx:`，只需**重新可见**。
  2. 三处理由按 §2.2 具体化（如"清理按批独立提交，避免长事务跨批持锁"），并去掉 `independent-transaction;` 前缀。
  3. 基线**一次性上调**：`scripts/gate_baseline.json` 的 `service_commit` 9 → **12**（原本被静默豁免的 3 处重新可见），提交信息写明理由；**不得**用 `quality_gate.py --update-baseline`（`scripts/quality_gate.py:189-199` 会重写全部门禁计数，静默吸收其它漂移）。
  4. 同步修 `docs/TRANSACTION_BOUNDARY_GUIDE.md:72-85` §4：标题基线改 12、行号改为实测值（`backup/incremental.py:397`、`backup/restore.py:267`、`backup/orchestration/recovery_test_service.py:573`、`backup/records.py:757,769,788`）、补登 3 处新条目。
  5. 脚本加 `--self-test`：注释不再能当豁免的 5 条断言（输出用 `[SELFTEST]` 前缀，避免被 `scripts/quality_gate.py:123` 的 `COUNT_RE` 误读）。
  6. **中期**：按 `AGENTS.md` §6「分析代码必须用 ast」把该脚本从"逐行正则"改为 AST 判定（避免字符串/注释/多行调用误判）。
- **验证**（**已按实测更正**）：`python scripts/check_service_commit.py` 会由 9 处 FAIL 变为 **12 处**（那 3 处重新可见），输出中不应出现其它新增；`--self-test` 通过；基线改为 12 后 `python scripts/quality_gate.py --only service_commit` 为 PASS；再跑一次全量 `python scripts/quality_gate.py` 确认其它门禁无漂移。
- **回滚**：单文件回退。
- **工时**：0.5 人日（AST 化另计 1 人日，可放 P1）。**风险**：极低。

### P0-8 死代码清理 + "白名单 ⊆ 导入图"机械校验
- **问题**：约 1,100 行死代码（`core/alert_rules.py`(37)、`core/domains.py`(86)、`schemas/purchase.py`(39)、`services/batch_pipeline.py`(128)、`services/purchase_order_service.py`(65)、`services/backup/_stream.py`(14)、`shared_models/base.py`(6)、`services/purchase_order_spare.py`(249)、`utils/batch_upload_utils.py`(501)、`utils/logger.py`(164)），其中 3 个仍在 `mypy.ini:50/:60/:130` 白名单内 → "看似被类型检查保护"。
- **变更**：
  1. 删除前**逐个 grep 复核**（AGENTS.md 要求，不凭"未被引用"下结论；注意 `utils/__init__.py:63` 的 PEP 562 惰性导出与动态导入）。
  2. 新增 `scripts/check_orphan_modules.py`（用 AST 构导入图）：CI 中断言 `mypy.ini` 的 files 全部在导入图内、且不存在"零入边且非 root"的模块。
  3. 同步删除对应测试（如 `tests/test_batch_pipeline.py`、`tests/test_logger.py`）或移到 `tests/archive/`。
- **验证**：`python -m mypy --config-file mypy.ini` 通过；`python scripts/quality_gate.py` `[PASS]`；`pytest -q` 无新增失败；新脚本能对一条人工制造的孤儿模块报错。
- **回滚**：`git revert` 单个提交（删除是独立提交，便于回滚）。
- **工时**：1 人日。**风险**：误删被动态导入的模块 → 用 `python -c "import fastapi_app.main"` + 全量 pytest 双重验证。

---

### P0-9 修一个"必现 NameError"的功能缺陷（OCR 不可用）
- **问题**：`mypy.ini` 的注释记录了两个真实缺陷——`fastapi_app/services/ocr/_extractors.py` 的 `global _pdf_extracter` **未声明**（首次调用必 NameError ⇒ OCR 整体不可用）、`batch_import_dedup.py` 的 `Container` **未 import**。
- **变更**：读该文件确认声明位置，补模块级 `_pdf_extracter: Any | None = None`（或改为函数内惰性缓存）；补 `from collections.abc import Container` 或正确导入；各加一条最小回归测试（调用一次抽取路径，断言不抛 NameError）。
- **验证**：`python -m pytest -q fastapi_app/tests -k "ocr or extract"`；若原先无测试覆盖该路径，先写一条**会失败**的用例再修。
- **回滚**：单文件改动 `git revert`。**工时**：0.5 人日。**风险**：低（纯缺陷修复）。

### P0-10 依赖显式声明 + 死配置清理
- **问题**：(a) **【执行期更正】原判断不成立**——全仓 `fastapi_app/**` 0 处 `itsdangerous` import，`fastapi_app/core/middleware.py:146` 的 `try:` 内只有 `ipaddress`/`secrets`，CSRF token 由 `:262 secrets.token_urlsafe(32)` 生成 ⇒ `:296 except ImportError` 是不可达死分支，不存在传递依赖风险（详见 `docs/architecture-audit-round3-2026-10-01.md` §9 第 9 条更正）；(b) `.env` 的 `DB_POOL_SIZE`/`DB_MAX_OVERFLOW`/`DB_POOL_RECYCLE` 在 `fastapi_app/core/database.py:25-53` **从不读取**（池参数由 `UVICORN_WORKERS`×`DB_MAX_CONNECTIONS` 计算）⇒ 死键（成立）。
- **变更**（按执行期更正后）：撤回 `requirements/base.txt` 的 `itsdangerous==2.2.0` 声明与错误注释；删除 `fastapi_app/core/middleware.py` 的死降级分支；删除 `.env` 死键并在 `.env.example` 注明池参数来源；`database.py` 补 `pool_recycle`（如 1800）并纳入 `_get_pool_config()`；另补 `requirements/test.txt` 的 4 个测试依赖与 `.env.example` 的 `UPLOAD_URL_SIGNING_SECRET`。
- **验证**：全仓 grep 证 `itsdangerous` 0 处 import；删死键后启动无告警且 `/api/health` 的 `db_pool` 字段仍符合公式；`check_env_drift --ci` exit 0；`check_function_length --json` total=51；重启后连接在 recycle 周期内被回收（日志/pg_stat_activity 可见新连接）。
- **回滚**：`git revert`；`pool_recycle` 去掉即恢复。**工时**：0.5 人日。

### P0-11 门禁本体加固（防"静默失效"）
- **问题**：(a) `scripts/quality_gate.py:122-123` 用**正则从子脚本 stdout 抠违规数**（子脚本改输出即静默失效）；(b) 本机未装 pre-commit，第④层门禁降级为"手动记得跑"；(c) CI 的 ruff 只扫 `fastapi_app`/`tests`/`utils`（`.github/workflows/ci-cd.yml:176-177`），`server_manager/`、`scripts/` 不进 lint；(d) `pip-audit` 无 `--ignore-vuln` 白名单 ⇒ 新 CVE 直接变红且无豁免流程。
- **变更**：①子脚本改 `--json` 输出或纯 `exit code` 语义，`quality_gate.py` 不再解析文本；②CI 增加"恒失败自测"——故意制造一个违规（临时超长函数），断言 `quality_gate.py` 退出码非 0；③ruff 扩到 `scripts/`、`server_manager/`（先只开 E/F）；④pip-audit 增加 `--ignore-vuln` 清单文件，每条带到期日与理由。
- **验证**：人为违规时 `quality_gate.py` 退出码非 0；CI 全绿；ruff 新范围首次跑通的违规数写入基线。
- **回滚**：门禁改动可单提交回退。**工时**：1 人日。**风险**：ruff 扩范围会暴露大量存量 → 用棘轮基线，不一次性清零。

### P0-12 上传魔数统一 + 无 Content-Length 的内存放大
- **问题**：(a) 只有备份恢复端有魔数校验（`fastapi_app/api/v1/backup/restore.py:115-117`：`PK\x03\x04`/`{`/`\x1f\x8b`），而 `production_plan.py:245`、`production_summary.py:304`、`auth.py:516`、`ocr_import.py:67/:109/:156`、`backup/validation.py:56` 等**仅按后缀判定**；(b) `fastapi_app/core/middleware.py:392-417` 在无 `Content-Length` 时逐块 `body += chunk` ⇒ chunked 形式的 512MB 上传造成同量内存放大。
- **变更**：抽 `validate_upload_magic(head_bytes, allowed_sets)` 到公共校验层并在上述端点接入（xlsx/xlsm → `PK`/OLE、csv → 文本、json → `{`/`[`），失败返回 400 并记录文件签名；中间件在无 `Content-Length` 时用累积计数器**提前 413**，不等到读满上限。
- **验证**：`python -m pytest -q fastapi_app/tests/test_request_body_limit_paths.py` 等既有 parity 测试不破；手工上传改扩展名的伪 xlsx 被 400 拒绝；用 `curl -H "Transfer-Encoding: chunked"` 推大文件时进程内存不随之增长到上限。
- **回滚**：魔数校验按端点开关，可逐个回退。**工时**：1 人日。**风险**：老旧客户端上传的非标准文件可能被误拒 → 先记录 3 天"本会拒绝"的日志再硬开关。

---
## 2. P1 · 收口（12 项，8–12 人日）

> 顺序有依赖：**先对账（P1-1）→ 再上约束（P1-6）**；先补幂等（P1-7）再改批量提交。

| 编号 | 项 | 证据 | 变更要点 | 验证 | 工时 | 风险 |
|---|---|---|---|---|---|---|
| P1-1 | 库存只读对账 | 54 写点/24 文件；`InventoryLog` 26 构造点；`shared_models/inventory_log.py` 只有位移无结存 | 新增 ARQ 任务：按 `product_id` 聚合 `inventory_log.change_quantity` 与 `product.current_stock` 比对，输出差异报告（**只读，不改数据**） | 报告条数与差异清单；跑两周观察漂移 | 1–2 | 低 |
| P1-2 | 参数化负库存 | `shared/stock_concurrency.py:86`、`batch_import_service.py:333/575`、`case/commands.py:313` | 抽 `assert_stock_available(db, product, qty, policy)`，策略读配置（`ALLOW_NEGATIVE_STOCK`），默认拒绝 | 单测覆盖三处路径；配置切换后行为变化可观测 | 1 | 中 |
| P1-3 | 扣减路径统一走乐观锁 | `shared/stock_concurrency.py:44-109` 已有 `update_stock_with_optimistic_lock`（会推 `version`），但 `order/deduction.py:129/181/194` 等直接改 `current_stock` | 把写点逐个改为调用统一函数（先只改订单/出库/退货三类，每类一次提交） | `grep current_stock +=` 写点数量下降；并发回归测试 | 2–3 | 中 |
| P1-4 | 编号计数表单调性 | `numbering_sequence.py:30-46` `DO UPDATE SET last_seq = last_seq + 1`，`seed` 仅在首次 INSERT 生效（`:61`）→ counter 落后即撞唯一索引 500 | `DO UPDATE SET last_seq = GREATEST(numbering_counter.last_seq, :seed) + 1`（range 版同理 `+ :count`） | 单测：预置 counter=5、seed=100 → 分配到 101 | 0.5 | 低 |
| P1-5 | 批量锁顺序 | `order_batch_create.py:79-86` `select(Product).where(id.in_(...)).with_for_update()` 无 `ORDER BY` | 加 `.order_by(Product.id)`（`product_ids` 本身已 sorted，显式声明防回归）；并把锁范围限制到本组商品 | 并发批量压测无死锁（PG 日志无 `deadlock detected`） | 0.5 | 低 |
| P1-6 | DB 兜底约束 | `shared_models/product.py:37` 无 `CHECK(current_stock>=0)`；`product.py:39` `version` 已存在 | **依赖 P1-1 结果**：先把存量负值对平（或确认为 0），再加 `CheckConstraint('current_stock >= 0')` + 一个 Alembic 迁移；仓储路径同时用 `UPDATE ... WHERE current_stock >= n` 原子扣减 | 迁移 `alembic upgrade head` + `alembic heads` 单 head；插入负值应被拒 | 1 | 中 |
| P1-7 | ARQ 幂等键 | `core/arq_app.py:201` `max_tries=3`；`tasks/batch_tasks.py:142`、`tasks/backup_tasks.py:320` 循环 commit | 任务入口以 `job_id + 业务主键` 做幂等（复用 `order_routes.py:113` 的 `X-Idempotency-Key` 思路/表）；循环 commit 改每 N 条一批 | 重放同一 job 不产生重复写；单测模拟重试 | 2 | 中 |
| P1-8 | 抵扣完整性校验 | `services/order/deduction.py:204` 结尾无 `remaining>0` 校验；`:254` 仍返回成功 | 结尾校验并返回实际生效量；不足时明确报错 | 单测：请求抵扣 100、可用 30 → 返回错误而非"成功" | 0.5 | 低 |
| P1-9 | 审计写入移出请求热路径 | `core/audit_middleware.py:300` 请求内循环 `session.execute` | 改为批量写入/独立短事务或异步队列（保留失败不影响主请求的语义） | 压测下 P95 改善；审计条数不丢 | 1–2 | 中 |
| P1-10 | 门禁机械化与棘轮 | `mypy.ini:13-20` 只收零错文件（约 110 项）；`scripts/gate_baseline.json` 存量基线 | ①新增 `check_orphan_modules.py` 进 CI（见 P0-8）；②把 `scripts/check_service_commit.py` 改 AST；③mypy 先并入 21 个零成本模块，之后按模块分批 | 三个门禁在 CI 里都能"因新增而失败" | 2 | 低 |
| P1-11 | 遗留 `.query(` 清理 | 非测试 9 处：`shared/report_data_service.py:110/127/181/190/231/243/286/295`、`services/base_search_service.py:89` | 改 `select()` 风格（与 `base_search_service.py:89` 已有注解一起收敛） | `grep -rn "\.query(" fastapi_app --include=*.py` 非测试为 0；相关报表接口回归 | 0.5–1 | 低 |
| P1-12 | 前端契约真校验 | `scripts/check-api-alignment.mjs:46-64` 只做前端自比对、`:54` 跳过模板插值；`frontend-vite/scripts/check-route-alignment.mjs:75-83` 恒不失败（`process.exit(1)` 不可达）；`check:dto` 未进 CI | ①后端导出 `openapi.json`（`python -c "from fastapi_app.main import app; ..."`）→ 新增只读脚本校验"前端 api 层字面端点 ⊆ openapi paths"；②修 `check-route-alignment.mjs` 的比较逻辑使其能失败；③`.github/workflows/ci-cd.yml:245-249` 增加 `check:dto` | 故意写错一个 URL 时 CI 失败；正常状态全绿 | 1–2 | 低 |
| P1-13 | 后端小卫生（**已并入 P0**） | `core/middleware.py:409-414` `body += chunk`；`database.py:47-53` 缺 `pool_recycle` | 已分别并入 **P0-12**（累积上限提前 413）与 **P0-10**（池加 `"pool_recycle": int(os.getenv("DB_POOL_RECYCLE", "1800"))`）；本项只保留回归验证 | 大 body 上传回归；长连接空闲 30 分钟后无 `connection closed` 报错 | — | 低 |

---

## 3. P2 · 补齐（12 项，12–18 人日）

**前端（5 项）**
1. **首屏减重**：`vite.config.ts:131` `'vendor-primevue': ['primevue']` 子串匹配把所有 primevue 模块并成 672KB 单 chunk + `main.ts:127-148` 非移动端在 mount 后立即 `import('primevue/config')` → 改为让 Vite 自然拆分，并把 `primevue/config` 延迟到首个 PrimeVue 组件挂载；**必须改 `.ts` 后重跑 `vue-tsc -b` 重新生成 `vite.config.js`**（红线 §5.5 + `fastapi_app/tests/test_qa_prod_stack_regression.py:448-465` 会断言二者一致）。
2. **类型钉死**：`api/request.ts:179/205/209/213` 的 `as Promise<T>` 改为 axios 第二泛型 `service.get<T, T>(...)`，逐步消解 131 处 `as unknown as`（非测试 42 处）。
3. **消灭 customer/supplier 复制级同构**：`views/customer/CustomerView.vue`(131) vs `views/supplier/SupplierView.vue`(148)、`useCustomer.ts`(177) vs `useSupplier.ts`(189)、两表 `onPageChange`（98-100 行逐行相同）→ 抽 `useCrudList<T>` + 配置化 `EntityTable`，约折叠 600 行。
4. **死代码与重复收敛**：`composables/useVirtualScrollList.ts`、`useEventDelegation.ts:9`、`api/auxiliary.ts:30`、`components/ui` 7 个零引用组件；三套虚拟滚动收敛为"列表用 `VirtualList.vue`、表格用 `useTableVirtualScroll.ts`"两套；`stores/auth.ts:209-212` 的 `permissions.includes` 改用已存在的 `permissionSet`（`:53`）。
5. **测试与可观测补口**：11/27 域零测试（approval/user/settings/case/login 优先）；`vitest coverage` 接 CI；确认生产配了 `VITE_SENTRY_DSN`（否则 `main.ts:103` 的 Sentry 是 no-op，而 `vite.config.ts:32-34` 已 drop 全部 console）。
6. **拆 `src/types/index.ts`**（793 行/65 导出跨十余域）→ 按域拆文件、`index.ts` 纯转发（保持 `@/types` 导入面）。

**后端与运维（6 项）**
7. **内网 TLS + 限流**：`config/nginx-windows.conf` 无 `ssl_certificate`、无 `limit_req` → 启用内网证书（或自签 + 客户端信任分发），对登录/导出类端点加 `limit_req_zone`；保持 `proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for`，配合 P0-6 的 `--proxy-headers`。
8. **PostgreSQL 暴露面**：`:5432` 当前监听 `0.0.0.0` → 收口到 `127.0.0.1`（除非确有远程连接需求，则限定 `listen_addresses` + `pg_hba.conf` 白名单并审计）。
9. **审计字段与软删除**：46/67 表无 `created_at`、26/67 无 `updated_at`；`stock_return.py:32` `stockout_id ondelete='CASCADE'` + `services/order/deduction.py:189` 硬删 → 退货历史可被级联删除。改为 `RESTRICT`/`SET NULL` + 退化为软删 + 写审计；新增迁移补审计字段（分批，先订单/库存/客户三类表）。
10. **编号读放大优化**：`numbering_sequence.py:115-127` 用正则 + `split_part` 全表扫 → 给"日期段"加函数索引或将 `read_daily_max` 改为 `col LIKE :prefix||'-'||:date||'-%'`（可走 `text_pattern_ops` 索引）并保留正则守卫。
11. **mypy 扩面**：`fastapi_app/services/` 全量约 387 errors（arg-type 97/assignment 60/attr-defined 49）→ 按模块分批纳入，每批以"该模块零错误"为条件，禁止把新错误写进白名单。
12. **时区收敛**：17 naive vs 124 timestamptz，`shared_models/order.py:92-95` 同表混用 → 制定"全部 timestamptz + 业务侧只做展示转换"的目标态，逐表迁移（每表一次迁移 + 数据回填 + 断言）。

---

## 4. P3 · 结构性（6 项，需专项评审）

### P3-1 库存单一真相（最重要，分 5 阶段）
- **目标态**（借鉴 ERPNext）：`inventory_log` 为唯一真相，补 `running_balance`、单位成本、单据来源；`product.current_stock` 降级为**派生缓存**（可重算、可对账）；作废用状态标记而非删除。
- **阶段**：
  1. （P1-1 已完成）只读对账，量化漂移；
  2. 双写：所有写点改为"写流水 + 更新余额"的单一函数，流水补 `running_balance`（同一事务内计算）；
  3. 双校验：对账差异持续为 0 连续 N 天后；
  4. 切读：报表/列表改从流水聚合（保留余额作快路径）；
  5. 收口：`current_stock` 只允许由该函数更新（加 CI 守卫：禁止其它文件直接赋值）。
- **风险控制**：每阶段可独立回滚；阶段 2 只增加字段与断言，不删旧路径。
- **工时**：8–12 人日（跨版本）。

### P3-2 拆分上帝对象
- 优先级：`services/backup/orchestration/recovery_test_service.py:29`（单类 1322 行，占 `max_file_size=1600` 的 85%）→ 按 prepare/execute/validate/cleanup 四阶段拆；随后 `services/backup/cleanup/service.py:48`(783)、`tasks/backup_tasks.py`(1008)、`api/v1/endpoints/backup/validation.py`(857，内含 201/160 行业务函数)、前端 `useSummaryModal.ts`(1083)。
- 原则：**先补测试再拆**（这几块恰好都有针对性测试，是难得的窗口）；每拆一步跑一次完整门禁。

### P3-3 状态与流程数据化
- `core/state_machine.py:29-40` 的 TRANSITIONS 移到配置/表（保留 fail-closed），为后续"审批升级/超时提醒"提供数据基础。

### P3-4 字段级审计
- 在 `shared_models/audit_log.py:16` 的 `details` 里固化 `{field, old, new}` 契约（借鉴 Odoo `mail.tracking.value`），先只覆盖 Order/Product 两个高价值实体。

### P3-5 行级权限
- 把 `core/production_scope.py:45` 的部门域授权模式推广到订单/客户 scope，消除"两套授权语义"并存（`daily_production.py` 用部门域、其余用权限码）。

### P3-6 模块边界数据化
- `api/v1/router.py:7-40` 的 34 条绝对导入 → "模块清单"（前缀 + 权限码 + 功能开关同处声明），支持灰度关闭（参考 Dolibarr 模块描述符）；已有前端 `check:routes` 可作为对齐护栏。

---

## 5. P4 · 治理（3 项，与 P0 同步启动）

1. **执行台账**：新建 `docs/optimization-status-2026-10-01.md`，每项一行，格式：
   ```
   | 编号 | 标题 | 状态 | 证据(文件:行) | 核验日期 | 责任人 | 下一动作 |
   | P0-1 | 凭据与 ACL 收口 | 待办 | .env / _ops/credentials | 2026-10-01 | — | 备份 ACL 后执行 icacls |
   ```
   状态仅用：待办 / 进行中 / 已提交(哈希) / 已验证 / 已回滚 / 放弃(理由)。
2. **门禁对象纠偏**：文件体积门禁对存量给**偿还期限**而非永久豁免；mypy 按模块分批纳入；新增"孤儿模块/白名单 ⊆ 导入图"校验。
3. **验收标准（每批 DoD）**：`python scripts/quality_gate.py` `[PASS]`、`python scripts/check_service_commit.py` 不新增、`ruff check .` 通过、`pytest -q` 无新增失败、前端 `npm run type-check && npm run test && npm run check:api` 通过、`logs/prod_runner.json` `ready:true` 且 `frontend_ok:true`、本轮新增的门禁能"因人为制造的缺陷而失败"。

---

## 6. 不做什么（明确排除）

1. **不整体重写/迁移到 Odoo/ERPNext**：本机即生产、无预发；99 个迁移 + 3689 个测试用例是既有资产。
2. **不引入通用工作流引擎**：全仓真正的状态机只有审批一处，数据化即可。
3. **不引入隐式猴补丁/覆盖层魔法**：与显式依赖 + mypy/ruff/quality_gate 的工程约定冲突。
4. **不微服务化**：Windows NSSM 单机 + 小团队 + 无预发，拆分的运维成本无处消化。
5. **不追求"全库字段级审计"**：先覆盖 Order/Product，避免审计表成为新的性能热点。
6. **不在本轮改动 `frontend-vite/vite.config.js`、`core.hooksPath`、`config/pgbouncer/userlist.txt` 入库状态**（红线）。

---

## 7. 对 audit 报告的两处口径修正（含一处自我纠错，引用时必读）

| 位置 | 原表述 | 实测更正 |
|---|---|---|
| audit §3.6 | "限流键可被 `X-Forwarded-For` 伪造绕过" | **结论成立，机制与初判不同**（我一度以"slowapi 不读 XFF"判其不成立，是错的）：`prod_runner.py:267-268` 传 `--forwarded-allow-ips=*`，uvicorn `proxy_headers.py:163-164` 在 `always_trust` 下取 XFF **最左**值并**重写** `request.client.host`，故 slowapi 读到的已是客户端可控值。修复见 P0-6(b)（`*` → `127.0.0.1`）。 |
| audit §3.8 | "连接池未接线（config.py 无池参数）" | **部分成立**：`core/database.py:25-53` `_get_pool_config()` 已接线（由 `UVICORN_WORKERS`×`DB_MAX_CONNECTIONS` 算出 pool_size=5/max_overflow=3，8×8=64 < 100，含 `pool_timeout/pool_pre_ping/pool_use_lifo`），**但 `.env` 的 `DB_POOL_SIZE/DB_MAX_OVERFLOW/DB_POOL_RECYCLE` 是死键**（从不读取，"改了不生效"）；且**仍缺 `pool_recycle`**。修复见 P0-10 + P1-13。 |

---

## 8. 建议的落地节奏（5 个窗口）

- **窗口 1（当天，1 人日）**：P0-1 凭据/ACL + P0-3 指标 + P0-7 门禁旁路（互不干扰，可并行）。
- **窗口 2（次日，1 人日）**：P0-4/P0-5 时钟（纯模型/工具层）+ P0-9 OCR 缺陷 + P0-10 依赖声明与死键/`pool_recycle`。
- **窗口 3（第三天，1.5 人日）**：P0-2 演练与告警出口 + 备份包补齐 + 异机副本 + P0-11 门禁加固。
- **窗口 4（周末低峰，1.5 人日）**：P0-6 暴露面与限流（**需重启后端**，`*`→`127.0.0.1`）+ P0-8 死代码清理 + P0-12 上传魔数与内存上限。
- **窗口 5（下一周）**：P1-1 库存对账上线 → 拿到真实漂移数据后再排 P1-6 约束与 P3-1 阶段 2。

> **DR 维度的硬约束**：P0-2 的 (d) 属 blocker——在"备份包不完整 + 无异地副本"未解决前，任何"备份正常"的结论都不成立；其余 P0 项不阻塞上线，但 (a)(b) 至少要有可验证的产物。
