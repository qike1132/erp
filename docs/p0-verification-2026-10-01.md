# P0 止血批 · 独立验证与集成台账

- 台账日期：2026-10-01
- 验证者：verifier（erp-p0-hardening 团队 worker，独立于 5 个实现任务）
- 验证对象：`docs/optimization-plan-2026-10-01-final.md` §1 P0-2 代码半、P0-3/4/5/10、P0-6/9/12、P0-7/11、P0-8
- 工作树快照（本地时间 2026-10-01 17:16:24）：HEAD = `0f58ad98`；`git diff HEAD --shortstat` = 57 files changed, 2397 insertions(+), 1435 deletions(-)；未跟踪新文件 22 个
- 验证方式：只读 diff 与源文件（不采信实现者自述）＋ 独立复算探针 ＋ 全量门禁与测试
- 纪律声明：**验证期间未修改任何实现文件**（唯一写操作是本台账）。未执行 git add/commit/checkout/stash，未重启服务，未执行 icacls/sc/schtasks，未改 .env 的值，未使用 sandbox_permissions，未改 `scripts/gate_baseline.json`。

---

## 1. 结论摘要

| 项 | 内容 | 判定 | 一句话依据 |
|----|------|------|-----------|
| P0-2 | 备份/DR 代码半（命名空间·敏感闸门·保留策略单源·演练脚本） | **达标** | `_constants.py` 命名空间与 `retention_days()/retention_count()` 单源已落地；`restore_drill.py` 识别 .zip.enc；`check` 无遗留旁路 |
| P0-3 | commit 失败仪表 | **达标** | `database.py:254-277` 结构化日志 + 计数器 + 原样上抛，新增测试 |
| P0-4 | 审批时钟统一 UTC | **达标** | `approval.py:61/:132` 与同表 `:56/:128` 同用 `_utcnow` |
| P0-5 | 业务日（北京时区） | **达标** | `stock_common.py:11 business_now()` 复用 `numbering_sequence._BUSINESS_TZ` |
| P0-6 | 限流键绑身份 + 暴露面收口 + 默认限流空转 | **达标（含 1 项生产机遗留）** | 5 端点显式 `key_func=rate_limit_key`；绑定仅 127.0.0.1；`if default_limits:` 守卫 |
| P0-7 | 门禁旁路封堵（service_commit） | **达标** | 两条注释旁路已删；FAIL 计数 9→12 复算一致 |
| P0-8 | 死代码清理 + 白名单⊆导入图校验 | **达标** | 7 模块 + 1 测试删除；`check_orphan_modules.py` exit 0 |
| P0-9 | OCR `_pdf_extracter` / 注解收窄 | **达标** | `_extractors.py:22` 已声明；`batch_import_dedup.py:140 Iterable[Hashable]` |
| P0-10 | 依赖声明与死配置 | **达标** | `.env` 三死键已删；`pool_recycle=1800`；test.txt 四依赖补齐 |
| P0-11 | 门禁本体加固 | **达标** | `quality_gate.py` 语义模式重写；`--self-test` 48 项 |
| P0-12 | 上传魔数 + chunked 体积上限 | **达标** | `validators.py` 魔数层接入 6 条真实上传路径；middleware 提前 413 |

**未达标项：0。** 所有 P0 均给出实现证据；下列为**已登记的缺口/残余风险**（不构成本批代码改动未达标，但需 captain 生产机裁决或单独派单）：

1. **nginx 侧限流仍是 dry-run**（P0-6(e) 的生产面）：`config/nginx-windows.conf` 5 处 `limit_req_dry_run` 实测仍为 `on;`（行 90/191/200/355/364，zone 定义 :28-29）。本批只改了应用侧（SlowAPIMiddleware 守卫），配置转正是生产机操作项且该文件由他人并发改写，需 captain 裁决。
2. **`customer_sampling_view` 权限行全仓不存在**：9 个 GET 现要求 `view|manage`，无 manage 码的登录用户改判 403（这正是 P0-6(a) 要堵的口）。若生产需要「能看不能改」角色，须补种权限 + 授权（属 migrations/ 与生产库）。
3. **pip-audit 漏洞库数据缺失**：本机未安装 pip-audit，门禁对该项记 WARN 跳过（条目 0、未超 180 天）。僵尸/过期条目的真实判定需 CI 传 `--audit-report`。
4. **文档行号漂移**：`docs/TRANSACTION_BOUNDARY_GUIDE.md:91/:106` 引用的 `services/backup/cleanup/service.py:599` 因新增 docstring 现为 `:604`（已由 t8 告知 gatekeeper）。
5. **P1 保留项**：`purchase_order_service.py`（只被 scripts/ 引用）、`purchase_order_spare.py`（文档标注已实施但从未接线）、`utils/logger.py` 有反证保留，属 P1。

---

## 2. Verify 命令的真实结果（4 条任务书命令 + 附加）

| # | 命令 | exit code | 关键输出 |
|---|------|-----------|---------|
| 1 | `.venv\Scripts\python.exe scripts\quality_gate.py` | **0** | 10 门禁全 OK 且「存量一致」：N+1=0、bare_except=5、function_length=51、vue=7、service_commit=12、bom=0、alembic=0、env_drift=0、ruff=61、pip_audit=0；末行 `[PASS] 未发现新增违规` |
| 2 | `.venv\Scripts\python.exe -m mypy --config-file mypy.ini` | **0** | `Success: no issues found in 107 source files`（error 计数 0） |
| 3 | `.venv\Scripts\python.exe -m pytest -q` | **0** | `3585 passed, 267 skipped in 378.06s (0:06:18)`，无 FAILED/ERROR 行 |
| 4 | `.venv\Scripts\python.exe scripts\check_service_commit.py` | **1** | `[FAIL] 在 service 层发现 12 处非法 commit()` + 12 条明细（脚本有命中即 exit 1；计数 12 == 基线 12） |

> 关于第 4 条的如实说明：该脚本是「检出即非零」的扫描器，基线比对在 `quality_gate.py`。因此单独的 `check_service_commit.py` **exit code 为 1**（存量 12 处），而门禁口径 `quality_gate.py --only service_commit` 为 **exit 0 + [PASS]（12 存量一致）**。本台账不谎报 0。

附加命令（全部实跑）：

| 命令 | exit | 输出 |
|------|------|------|
| `scripts\quality_gate.py --self-test` | 0 | 48 项断言全部通过 |
| `scripts\quality_gate.py --only ruff` | 0 | ruff 违规 61 存量一致 |
| `scripts\quality_gate.py --only service_commit` | 0 | service 层手动 commit(): 12 存量一致 |
| `scripts\check_service_commit.py --self-test` | 0 | 8 项（行内 `independent-transaction`/`commit(`/manual-tx 均不再豁免；整行注释仍豁免；退役旁路未复活） |
| `scripts\check_orphan_modules.py` | 0 | 1247 个 .py / 346 候选 / ROOTS=3；白名单 107 ⊆ 导入图 107；1 WARN |
| `pytest -q tests/test_gates_cover_repo_root.py scripts/prod_audit/tests/test_scan_secrets_hook_parity.py` | 0 | 22 passed |

---

## 3. 数字复算（验收标准③）

| 声称 | 复算方法 | 复算结果 | 是否一致 |
|------|---------|---------|---------|
| service_commit FAIL 9→12 | 探针用 `git show HEAD:<path>` 取 HEAD 版文件，分别套旧/新 `ALLOWED_PATTERNS` | 旧规则+HEAD = **9**；新规则+工作树 = **12**；`check_service_commit.py --json` total=12；`gate_baseline.json:8` = 12 | ✅ 三方一致 |
| ruff 违规 61 | `ruff check scripts/ server_manager/ --output-format json` 独立统计 | **61**（UP031×21、S110×18、F841×5、S112×4、RUF059×3、SIM105×2…） | ✅ 与门禁一致 |
| mypy 覆盖 110→107 | 解析 `mypy.ini` files 列表 | **107**（106 条 + 首行 1 条）；实跑 107 source files | ✅ 一致 |
| .meta 清理（P0-2） | 读 `records.py`/`cleanup/service.py` 的 `_delete_backup_sidecars` 接线 + 保留策略测试 | `.zip.enc.meta` 与 `.record` 随主文件一起删；单源 `retention_days()/retention_count()` | ✅ 一致 |
| 限流键随身份变化 | 通读 `test_rate_limit_identity_key.py` + 复核 `limiter.py:56-79`、5 端点装饰行 | 5 处 `limit.key_func is rate_limit_key`；同用户换 IP 同桶；同 IP 不同用户不同桶；匿名回退 IP；e2e 429 后换身份放行 | ✅ 一致 |

---

## 4. 逐项三件套（达标判定 + 证据 + 反证/缺口）

### P0-3 commit 失败仪表 —— 达标
- **证据**：`fastapi_app/core/database.py:207-226` `_COMMIT_FAILURE_COUNTER` + `_commit_failure_counter()`（惰性 import `core.metrics._get_or_create_counter`，注册 `db_commit_failures_total`，避免热重载重复注册）；`:229` `async def get_async_db(request: Request = None)`（可空默认，兼容 `main.py:125` 的 `async for db in get_async_db()` 无参调用）；`:254-277` 失败分支：`request_id`/`path` 用 `getattr` 防御、`:263` `inc()`、`:264-272` `logger.error` + `extra` 同名字段、`:273-276` rollback、`:277` 原样 `raise`。新增 `fastapi_app/tests/test_db_commit_metric.py`。
- **反证/缺口**：计数器为惰性注册，未配置 prometheus 客户端时仅内存计数（设计如此）；无未达标项。

### P0-4 审批时钟统一 UTC —— 达标
- **证据**：`fastapi_app/shared_models/approval.py:61` 与 `:132` 的 `updated_at` 由本地 `datetime.now` 改为 `_utcnow`，与同表 `:56 request_time`/`:128 action_time` 同钟。新增 `fastapi_app/tests/test_approval_clock_utc.py`（含 AST 扫描无本地 `datetime.now`）。
- **反证/缺口**：无。

### P0-5 业务日（北京时区） —— 达标
- **证据**：`fastapi_app/services/stock_common.py:8` `from ...numbering_sequence import _BUSINESS_TZ`；`:11` `def business_now()`（`datetime.now(_BUSINESS_TZ).replace(tzinfo=None)`）；`:27` 原 `datetime.now(UTC)` 改用它。新增 `fastapi_app/tests/test_business_day_stock_common.py`（冻结 2026-09-30T16:30Z ⇒ 业务日 2026-10-01）。
- **反证/缺口**：复用私有常量 `_BUSINESS_TZ`（跨模块私有依赖），建议后续提升为公开符号（P2，不影响达标）。

### P0-6 限流键/暴露面/默认限流 —— 达标（生产面 1 项遗留）
- **证据（限流键）**：`fastapi_app/core/limiter.py:56` `def rate_limit_key(request)`（延迟 import `deps._resolve_user_id`，已登录 `f"user:{user_id}"`，否则 `get_remote_address`）；`:78` `key_func=rate_limit_key`；`:72` `default_limits = limiter_default_limits_from_env()`。5 个装饰端点显式绑键已实测：`auth.py:218`、`monitoring.py:206`、`daily_production.py:328`、`report.py:154`、`stock.py:349`（`@limiter.limit("...", key_func=rate_limit_key)`）。
- **证据（暴露面）**：`fastapi_app/core/prod_runner.py:263` `"--host","127.0.0.1"`、`:270` `--forwarded-allow-ips=127.0.0.1`（保留 `--proxy-headers`）；`scripts/restart_backend.py:68/70` 同；`config/pgbouncer/pgbouncer.ini:15` `listen_addr = 127.0.0.1`。全仓 `0.0.0.0` 仅出现在 `prod_runner.py:262` 的注释里。
- **证据（P0-6(e) 与应用侧开关）**：`fastapi_app/main.py:280-281` `if default_limits: app.add_middleware(SlowAPIMiddleware)`（`:277-279` 注释说明 slowapi 中间件只对未装饰路由生效）。当前 `.env` 无 `RATE_LIMIT_DEFAULT` ⇒ 不注册（等价删除空转），配置后自动生效。
- **证据（P0-6(a)）**：`fastapi_app/api/v1/endpoints/customer_sampling.py` 9 处 GET 加 `Depends(require_any_permission(READ_PERM, PERM))`：行 87/107/123/257/386/399/414/433/446。
- **反证/缺口**：①`customer_sampling_view` 权限行全仓不存在（migrations 0 命中），持有 `customer_sampling_manage` 者因 `shared_models/user.py:69-75` 的「manage 自动通过 view」零影响，无 manage 码用户 403；②nginx `limit_req_dry_run` 仍 `on;`（行 90/191/200/355/364）——生产机项，需 captain 裁决。

### P0-7 门禁旁路封堵 —— 达标
- **证据**：`scripts/check_service_commit.py` 的 `ALLOWED_PATTERNS` 现仅 4 条（`nested.commit(`、`short_session.commit(`、`_session.commit(`、`^\s*#`）；HEAD 版的 `#.*commit(` 与 `#\s*independent[-_]transaction` 两条注释旁路已删除（探针复算证实）。新增 `--json` 与 `--self-test`（8 项）。
- **反证/缺口**：计数由 9 升到 12（见第 3 节复算），`gate_baseline.json:8` 手写 12 并带 `_comment` 说明为唯一一次基线上调。

### P0-8 死代码清理 —— 达标
- **证据**：删除 7 个零入边模块（`fastapi_app/core/alert_rules.py`、`core/domains.py`、`schemas/purchase.py`、`services/batch_pipeline.py`、`services/backup/_stream.py`、`shared_models/base.py`、`utils/batch_upload_utils.py`）与 `tests/test_batch_pipeline.py`；新增 `scripts/check_orphan_modules.py`，实跑 exit 0：白名单 107 ⊆ AST 导入图 107，零入边非 root 断言 PASS，人工孤儿探针反证 exit 1。
- **反证/缺口**：1 WARN —— `fastapi_app/services/purchase_order_service.py` 仅被 `scripts/perf_benchmark.py:78` 引用；`purchase_order_spare.py`、`utils/logger.py` 有活测试消费者，保留正确（P1 处理）。

### P0-9 OCR 名称/注解 —— 达标
- **证据**：`fastapi_app/services/ocr/_extractors.py:22` 模块级 `_pdf_extracter: Any = None`（`:29 global`、`:80` 使用），HEAD 即已如此、无需改；`fastapi_app/services/batch_import_dedup.py:140` `existing_keys: Iterable[Hashable] = ()`（`:32` 导入、`:136-139` 注释说明 `Container` 不保证可迭代），消除运行期崩溃面。
- **反证/缺口**：两项均新增最小回归测试（含 ast 注解未绑定名检查）。

### P0-10 依赖声明与死配置 —— 达标
- **证据**：`fastapi_app/core/database.py` `_get_pool_config()` 新增 `pool_recycle=int(os.getenv("DB_POOL_RECYCLE","1800"))`；`.env` 三死键 `DB_POOL_SIZE`/`DB_MAX_OVERFLOW`/`DB_POOL_RECYCLE` 实测已删（Select-String 结果为空），`.env.bak-pre-p010` 实测不存在；`.env.example` 删除两项、保留 `DB_POOL_RECYCLE=1800` 并说明池参数真实来源（`UVICORN_WORKERS × DB_MAX_CONNECTIONS`）、新增 `UPLOAD_URL_SIGNING_SECRET=`（空值）；`requirements/test.txt` 新增 `aiosqlite==0.22.1`、`fastexcel==0.20.2`、`aiohttp==3.13.3`、`arrow==1.3.0`；`fastapi_app/core/telemetry.py:35` 增加 `SpanExporter` 导入、`:55` 前显式标注 `exporter: SpanExporter`（修复 mypy 双分支推断）。
- **反证/缺口**：`itsdangerous` 声明按 captain 裁决撤回（`requirements/base.txt` 对 HEAD diff 为空）—— 与计划书原文不一致但**经裁决**，记为已决事项而非未达标。

### P0-11 门禁本体加固 —— 达标
- **证据**：`scripts/quality_gate.py` 重写为 4 种语义判定模式（子脚本 `--json` / 纯 exit code / ruff `--output-format json` / pip-audit 策略），无 stdout 正则；`--self-test` 48 项断言 exit 0；`pyproject.toml` 增 `pip_audit_max_days=180` 与 `[[tool.code-quality.pip-audit-ignores]]` 空清单（过期/僵尸/超上限/缺字段/未豁免漏洞的判定有合成 fixture 双向证明）。
- **反证/缺口**：本机未装 pip-audit ⇒ 漏洞库相关判定只 WARN 跳过（CI 需 `--audit-report`）。

### P0-12 上传魔数 + chunked 体积上限 —— 达标
- **证据**：`fastapi_app/core/validators.py:104 magic_signature` / `:137 matches_upload_magic` / `:163 validate_upload_magic` / `:175 require_upload_magic`；接入 6 处真实上传路径：`production_summary.py:312`、`production_plan.py:255`、`ocr_import.py:123`、`ocr_import.py:171`、`auth.py:514`、`backup/validation.py:71`（失败 400 并记录文件签名）；`fastapi_app/core/middleware.py` 在无 `Content-Length` 时按累积计数边读边判、超限立即 413（注释见 diff），避免 512MB 分块上传的内存放大。新增 `fastapi_app/tests/test_upload_magic_validation.py`、`test_middleware_degraded_production.py`。
- **反证/缺口**：魔数校验为白名单式首字节判定，对刻意构造的合法头+恶意载荷无效（属设计边界，需后续内容级校验，P1）。

### P0-2 备份与 DR 代码半 —— 达标
- **证据（命名空间一致性）**：`fastapi_app/services/backup/_constants.py` 新增 `CONFIG_NAMESPACE='config/'`、`ROOT_NAMESPACE='root/'`、`_config_entry(rel_path)`；`config_files_to_package()` 清单项自带命名空间（`nginx-windows.conf`/`security-headers.conf`/`redis-broker.conf`/`nssm-services.json` + `(RUNTIME_ENV_FILE,'root/.env')`）；`orchestration/core.py:95 pack_config_files`、`:121 record_config_includes`、`:426-428` 接线；`filestore.py` 新增 `_path_variants()`（两种命名空间写法都认，防闸门静默失效）、`_restore_roots()` 改最长前缀优先（旧包兼容，不产生 `config/root` 幽灵目录）。
- **证据（敏感闸门）**：`_SENSITIVE_CONFIG_FILES` 显式含 `'root/.env'`（`_constants.py:143-146`）；备份侧明文包不带 `.env` 且 `manifest.includes.config_files_excluded` 记录；还原侧 `confirm_sensitive=False` ⇒ `skipped_sensitive==['.env']` 且不动盘上文件。AST 守卫锁住接线。
- **证据（保留策略单源）**：`_constants.py` `RETENTION_DAYS_ENV`/`RETENTION_COUNT_ENV`/`RETENTION_DAYS_DEFAULT=30`/`RETENTION_COUNT_DEFAULT=100` + `retention_days()`/`retention_count()`（调用时求值，`monkeypatch.setenv` 生效）；三处消费方改调单源：`records.py`（新增 `_retention_thresholds()`、`_delete_backup_sidecars(filepath)` 同删 `.meta` 含 `.zip.enc.meta` 与 `.record`，OSError 仅 warning）、`cleanup/service.py:65/:68`（`:542` 用 `_delete_backup_sidecars`）、`policy_service.py:48-52`；AST 守卫禁止消费方直读 env。对照 HEAD（硬编码 30/50）确认为真实收敛。
- **证据（演练脚本）**：`scripts/restore_drill.py` 重写，`ENCRYPTED_SUFFIX='.zip.enc'`、`is_backup_candidate` 排除 `.meta`/`.record`、`list_backup_candidates/newest_backup`、`MissingPassphraseError`（`:54` 定义、`:117` raise）、`resolve_passphrase/require_passphrase/open_backup_archive/parse_args/main`。新增 `test_restore_drill.py`（15 用例）、`test_backup_retention_policy.py`（12 用例）。
- **证据（白名单完整性）**：6 个 config 目标文件实测全部存在（含新建 `config/nssm-services.json`，3004 字节）。
- **反证/缺口**：`docs/TRANSACTION_BOUNDARY_GUIDE.md:91/:106` 的 `cleanup/service.py:599` 因新增 docstring 现为 `:604`（文档行号漂移，需 gatekeeper 同步）。

---

## 5. 未跟踪/并发写者登记（非本批 9 项，避免台账误归因）

- **本批新增（属 9 项交付）**：`config/nssm-services.json`、`scripts/check_orphan_modules.py`、11 个 `fastapi_app/tests/test_*.py`（详见附录）。
- **他人写域/OPT 批次（不在 P0 验收范围）**：`config/tls/ca.crt`、`fastapi_app/tasks/replica_lag_task.py`、`docs/architecture-audit-round3-2026-10-01.md`、`docs/audit-round2/`、`docs/optimization-plan-2026-10-01-round2.md`、`docs/optimization-plan-2026-10-01-round3.md`、`docs/p0-exec-checklist-2026-10-01.md`、`docs/p0-ops-checklist-2026-10-01.md`、`docs/round2-claim-verification-2026-10-01.md`、`docs/optimization-plan-2026-10-01-final.md`（计划书本身）。

---

## 6. 验证者自身合规证明（验收标准④）

- 本回合唯一写操作：`docs/p0-verification-2026-10-01.md`（本文件）。
- 复核方式全部为只读：`git status`/`git diff HEAD`/`git show HEAD:<path>`/`Select-String`/`Test-Path`/grep/read/独立探针。
- 未运行 `git add|commit|checkout|stash`；未重启服务；未执行 `icacls|sc|schtasks`；未修改 `.env`（仅读取键名与存在性）；未使用 sandbox_permissions；未修改 `scripts/gate_baseline.json`。
- 所有 python 命令均使用 `D:\erp_system\.venv\Scripts\python.exe`。

---

## 附录 A：工作树改动清单（快照 2026-10-01 17:16:24）

已跟踪改动（57 个）：

```
M .env.example
 M .github/workflows/ci-cd.yml
 M .gitignore
 M config/pgbouncer/pgbouncer.ini
 M docs/TRANSACTION_BOUNDARY_GUIDE.md
 M fastapi_app/api/v1/endpoints/auth.py
 M fastapi_app/api/v1/endpoints/backup/validation.py
 M fastapi_app/api/v1/endpoints/customer_sampling.py
 M fastapi_app/api/v1/endpoints/daily_production.py
 M fastapi_app/api/v1/endpoints/monitoring.py
 M fastapi_app/api/v1/endpoints/ocr_import.py
 M fastapi_app/api/v1/endpoints/production_plan.py
 M fastapi_app/api/v1/endpoints/production_summary.py
 M fastapi_app/api/v1/endpoints/report.py
 M fastapi_app/api/v1/endpoints/stock.py
 D fastapi_app/core/alert_rules.py
 M fastapi_app/core/database.py
 D fastapi_app/core/domains.py
 M fastapi_app/core/health.py
 M fastapi_app/core/limiter.py
 M fastapi_app/core/middleware.py
 M fastapi_app/core/prod_runner.py
 M fastapi_app/core/telemetry.py
 M fastapi_app/core/validators.py
 M fastapi_app/main.py
 D fastapi_app/schemas/purchase.py
 M fastapi_app/services/backup/_constants.py
 D fastapi_app/services/backup/_stream.py
 M fastapi_app/services/backup/cleanup/service.py
 M fastapi_app/services/backup/filestore.py
 M fastapi_app/services/backup/metrics/alert_service.py
 M fastapi_app/services/backup/orchestration/core.py
 M fastapi_app/services/backup/orchestration/policy_service.py
 M fastapi_app/services/backup/records.py
 D fastapi_app/services/batch_pipeline.py
 M fastapi_app/services/stock_common.py
 M fastapi_app/shared_models/approval.py
 D fastapi_app/shared_models/base.py
 M fastapi_app/tests/test_backup.py
 M fastapi_app/tests/test_backup_config_packaging.py
 M fastapi_app/tests/test_ocr_order_preview.py
 M fastapi_app/tests/test_request_body_limit_paths.py
 M mypy.ini
 M pyproject.toml
 M requirements/test.txt
 M scripts/check_bare_except.py
 M scripts/check_function_length.py
 M scripts/check_service_commit.py
 M scripts/check_vue_component_length.py
 M scripts/gate_baseline.json
 M scripts/quality_gate.py
 M scripts/restart_backend.py
 M scripts/restore_drill.py
 D tests/test_batch_pipeline.py
 M tests/test_new_libraries.py
 M utils/__init__.py
 D utils/batch_upload_utils.py
```

未跟踪新文件（22 个）：

```
?? config/nssm-services.json
?? config/tls/ca.crt
?? docs/architecture-audit-round3-2026-10-01.md
?? docs/audit-round2/
?? docs/optimization-plan-2026-10-01-final.md
?? docs/optimization-plan-2026-10-01-round2.md
?? docs/optimization-plan-2026-10-01-round3.md
?? docs/p0-exec-checklist-2026-10-01.md
?? docs/p0-ops-checklist-2026-10-01.md
?? docs/round2-claim-verification-2026-10-01.md
?? fastapi_app/tests/test_approval_clock_utc.py
?? fastapi_app/tests/test_backup_retention_policy.py
?? fastapi_app/tests/test_batch_import_dedup_annotations.py
?? fastapi_app/tests/test_business_day_stock_common.py
?? fastapi_app/tests/test_customer_sampling_permission.py
?? fastapi_app/tests/test_db_commit_metric.py
?? fastapi_app/tests/test_middleware_degraded_production.py
?? fastapi_app/tests/test_ocr_extractors_regression.py
?? fastapi_app/tests/test_rate_limit_identity_key.py
?? fastapi_app/tests/test_restore_drill.py
?? fastapi_app/tests/test_upload_magic_validation.py
?? scripts/check_orphan_modules.py
```

---

## 附录 B：证据落盘位置（仓库外，避免污染工作树）

- `C:\Users\Administrator\AppData\Local\Temp\t6-verifier\qg.out` —— `quality_gate.py` 全量输出
- `C:\Users\Administrator\AppData\Local\Temp\t6-verifier\mypy.out` —— mypy 输出
- `C:\Users\Administrator\AppData\Local\Temp\t6-verifier\pytest.out` —— pytest 全量输出
- `C:\Users\Administrator\AppData\Local\Temp\t6-verifier\sc.out` —— `check_service_commit.py` 12 条明细
- `C:\Users\Administrator\AppData\Local\Temp\t6-verifier\probe_counts.py` —— 9→12 复算探针（HEAD 版文件 × 新旧正则）
- `C:\Users\Administrator\AppData\Local\Temp\t6-verifier\probe_ruff.py` —— ruff 61 条独立统计探针
