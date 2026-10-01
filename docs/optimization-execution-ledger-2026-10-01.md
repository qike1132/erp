# P0 执行台账（集成）— 2026-10-01

> **生成者**：`verifier`（独立验证 + 集成，任务 t7 / attempt 1 = `015ff15a-7f0b-4e49-8c01-829627fcb05c`）
> **依据**：`docs/optimization-plan-2026-10-01-final.md`（唯一执行依据，§1 P0 定义 + §3 DAG + §5/§6）与 `docs/p0-verification-2026-10-01.md`（t6 独立验证台账）
> **口径**：本文件记录**工作树**状态（截至 2026-10-01 本文件生成时）；团队全程 **未 git add / 未 git commit**，提交由 Lead 统一审 diff 后执行。
> **生产机纪律**：未重启任何服务、未执行 icacls/sc/schtasks、未改 .env 口令与密钥**值**（P0-10 仅删 3 个死键）、未使用 sandbox_permissions；Python 一律 `D:\erp_system\.venv\Scripts\python.exe`。

---

## 1. 结论（摘要）

| 问题 | 结论 |
|---|---|
| P0 代码批（9 项纯代码改动 / 11 个 P0 编号项）是否落地 | **落地**。P0-2 代码半、P0-3、P0-4、P0-5、P0-6、P0-7、P0-8、P0-9、P0-10、P0-11、P0-12 全部完成并有实测证据 |
| 未达标项 | **0 项**（见 §5；仅 6 条已登记缺口/残余风险，均非本批代码缺陷，其中 4 条属生产机项或需用户裁决） |
| 三门禁 | `quality_gate.py` **exit 0 [PASS]**（10 门禁全 OK 且与基线一致）；`mypy --config-file mypy.ini` **exit 0**（107 files, no issues）；`pytest -q` **exit 0**（3585 passed / 267 skipped / 0 FAILED·ERROR） |
| 最终 diff 规模 | **57 个已跟踪文件（2427 insertions / 1435 deletions）+ 24 项未跟踪新增**；`git status --porcelain` 共 **81 项** |
| 仍需用户在场执行 | P0-1 **全部**、P0-2 **运维半**、nginx `limit_req_dry_run` 转正 + reload、后端重启（详见 §6） |
| P1 / P2 / P3 | **全部未开工**（本轮只做 P0 止血，见 §7） |

---

## 2. 最终 diff 规模（工作树 vs HEAD）

命令与输出（本文件生成时实测）：

```
$ git diff HEAD --shortstat
 57 files changed, 2427 insertions(+), 1435 deletions(-)

$ git status --porcelain | Measure-Object   # 含未跟踪
porcelain_entries=81
```

| 类别 | 数量 | 说明 |
|---|---|---|
| 已跟踪 · 修改（M） | 49 | 见 §2.1 |
| 已跟踪 · 删除（D） | 8 | P0-8 死代码（7 模块 + 1 测试） |
| 未跟踪 · 新增（??） | 24 | 11 个新测试、2 个新门禁/配置文件、11 个文档与其它 |
| **合计（porcelain）** | **81** | `git diff --stat` 只统计前 57 项 |

### 2.1 按 P0 归因的变更文件清单

| P0 | 变更文件 |
|---|---|
| **P0-2 代码半**（t5 + t8 + t12） | 改：`scripts/restore_drill.py`、`fastapi_app/services/backup/_constants.py`、`fastapi_app/services/backup/records.py`、`fastapi_app/services/backup/cleanup/service.py`、`fastapi_app/services/backup/orchestration/core.py`、`fastapi_app/services/backup/orchestration/policy_service.py`、`fastapi_app/services/backup/filestore.py`、`fastapi_app/tests/test_backup.py`、`fastapi_app/tests/test_backup_config_packaging.py`；新：`fastapi_app/tests/test_restore_drill.py`（15 用例）、`fastapi_app/tests/test_backup_retention_policy.py`（12 用例）、`config/nssm-services.json`（五服务定义快照，schema erp-nssm-services/1） |
| **P0-3** 提交失败仪表 | 改：`fastapi_app/core/database.py`；新：`fastapi_app/tests/test_db_commit_metric.py` |
| **P0-4** 审批域时钟 | 改：`fastapi_app/shared_models/approval.py`；新：`fastapi_app/tests/test_approval_clock_utc.py` |
| **P0-5** 业务日口径 | 改：`fastapi_app/services/stock_common.py`；新：`fastapi_app/tests/test_business_day_stock_common.py` |
| **P0-6** 暴露面与限流 | 改：`fastapi_app/core/limiter.py`、`fastapi_app/core/prod_runner.py`、`fastapi_app/main.py`、`fastapi_app/api/v1/endpoints/customer_sampling.py`、`scripts/restart_backend.py`、`config/pgbouncer/pgbouncer.ini`；新：`fastapi_app/tests/test_rate_limit_identity_key.py`、`fastapi_app/tests/test_customer_sampling_permission.py` |
| **P0-7** 门禁注释旁路封堵 | 改：`scripts/check_service_commit.py`、`scripts/gate_baseline.json`（service_commit 9→12）、`docs/TRANSACTION_BOUNDARY_GUIDE.md`、`fastapi_app/services/backup/metrics/alert_service.py`（豁免行理由具体化） |
| **P0-8** 死代码清理 | 删：`fastapi_app/core/alert_rules.py`、`fastapi_app/core/domains.py`、`fastapi_app/schemas/purchase.py`、`fastapi_app/services/batch_pipeline.py`、`fastapi_app/services/backup/_stream.py`、`fastapi_app/shared_models/base.py`、`utils/batch_upload_utils.py`、`tests/test_batch_pipeline.py`；改：`mypy.ini`（110→107，整文件转纯 ASCII）、`utils/__init__.py`；新：`scripts/check_orphan_modules.py`（362 行） |
| **P0-9** OCR 缺陷 | 未改实现（HEAD 已具备）；新：`fastapi_app/tests/test_ocr_extractors_regression.py`、`fastapi_app/tests/test_batch_import_dedup_annotations.py` |
| **P0-10** 依赖显式声明 + 死配置 | 改：`.env`（**删 3 死键**）、`.env.example`、`requirements/test.txt`、`fastapi_app/core/middleware.py`、`fastapi_app/core/health.py`、`fastapi_app/core/telemetry.py`、`fastapi_app/core/database.py`（pool_recycle 纳入 _get_pool_config()）；新：`fastapi_app/tests/test_middleware_degraded_production.py` |
| **P0-11** 门禁本体加固 | 改：`scripts/quality_gate.py`、`scripts/check_service_commit.py`（与 P0-7 同文件）、`scripts/check_bare_except.py`、`scripts/check_function_length.py`、`scripts/check_vue_component_length.py`、`scripts/gate_baseline.json`、`pyproject.toml`、`.github/workflows/ci-cd.yml` |
| **P0-12** 上传魔数与内存放大 | 改：`fastapi_app/core/validators.py`（新增魔数层）、`fastapi_app/core/middleware.py`（无 Content-Length 累积计数提前 413）、`fastapi_app/api/v1/endpoints/production_plan.py`、`production_summary.py`、`auth.py`、`ocr_import.py`、`backup/validation.py`、`fastapi_app/tests/test_request_body_limit_paths.py`、`fastapi_app/tests/test_ocr_order_preview.py`；新：`fastapi_app/tests/test_upload_magic_validation.py` |
| **非 P0 编目项**（团队本期顺带/纪律性改动） | 改：`.gitignore`（captain：忽略 `config/tls/*.key`、`.env.bak-*`、`/.agent-teams/` 等，防私钥与凭据副本入库）、`fastapi_app/tests/test_new_libraries.py`（t9：4 个可选库缺失即 skip，治愈全量 pytest 收集中断） |
| **并发外部会话产物**（非本团队写域，未 git add） | `config/nginx-windows.conf`（+216/−2：443 自签 TLS、secure_link、限流 zone）、`config/tls/ca.crt`、`fastapi_app/services/signed_urls.py` 等 |

---

## 3. 三门禁结论（本文件生成时的**串行**实测）

| # | 命令 | exit code | 关键输出 |
|---|---|---|---|
| 1 | `D:\erp_system\.venv\Scripts\python.exe scripts\quality_gate.py` | **0** | 10 项门禁全 OK 且与基线一致：N+1=0 / bare_except=5 / function_length=51 / 前端 Vue=7 / **service_commit=12** / BOM=0 / Alembic 单 head=0 / env_drift=0 / **ruff=61** / pip_audit=0；结尾 [PASS] 所有门禁通过 |
| 2 | `D:\erp_system\.venv\Scripts\python.exe -m mypy --config-file mypy.ini` | **0** | `Success: no issues found in 107 source files` |
| 3 | `D:\erp_system\.venv\Scripts\python.exe -m pytest -q` | **0** | `3585 passed, 267 skipped in 354.45s`，FAILED/ERROR 行命中 **0**（3852 = 3585 + 267，与 --collect-only 一致） |
| 4 | `D:\erp_system\.venv\Scripts\python.exe scripts\check_service_commit.py --json` | **1** | 设计如此：**扫描器命中即非零**，`total=12`；基线比对在 `quality_gate.py`（第 1 行的 --only service_commit → exit 0 [PASS]，12 处与基线一致）。属脚本语义，非实现缺陷 |

**串行纪律**：全量 `pytest -q` 不得与第二名成员的全量套件并行（并行会触发 `asyncpg.exceptions.DeadlockDetectedError`，t9 那次并行得到 1250 errors；串行两次均为 3585 passed / 0 FAILED·ERROR）。本文件第 3 行为 **backup-eng 的 t12 落地后**的串行复跑（t12 只改 3 个 `fastapi_app/tests/test_backup*.py`）。

**附加门禁自检**（t6 实跑，t12 后计数未变）：`quality_gate.py --self-test` 48 项 exit 0；`check_service_commit.py --self-test` 8 项 exit 0（两条注释旁路确认已删且未复活）；`check_orphan_modules.py` exit 0（白名单 107 ⊆ 导入图 107，1 WARN `purchase_order_service.py`）；`pytest tests/test_gates_cover_repo_root.py scripts/prod_audit/tests/test_scan_secrets_hook_parity.py` → 22 passed。

---

## 4. P0 项台账（每项一行，四要素齐全）

| 项 | 状态 | 变更文件 | 验证证据（命令 + exit code） | 回滚点 |
|---|---|---|---|---|
| **P0-1** 凭据与文件权限收口 | **待用户在场**（不在委派范围） | `.env` ACL、`_ops/credentials`（均**未改动**） | 未执行；`icacls` 复查与 `/metrics` 200 属生产机验收 | `icacls /restore D:\erp_acl_backup\erp_system.acl`；`.env` 用 `.env.bak-20260927-085022` |
| **P0-2 代码半** 演练/白名单/保留策略 | **达标** | 见 §2.1 P0-2 行（12 个文件） | `pytest fastapi_app/tests -k "backup or restore_drill" -q` → 564+ passed exit 0；`restore_drill.py` 匹配 `.zip`/`.zip.enc` + 缺口令显式报错（15 用例）；打包→还原真实往返（`.env` 字节级恢复、不建 `config/root`）；`.meta`/`.record` 随主文件同删；保留策略三消费方单源 `_constants.retention_days()/retention_count()`；全量第 1/3 行 exit 0 | 单文件 `git checkout --`（或 `git revert`）：`restore_drill.py`/`_constants.py`/`records.py`/`cleanup/service.py`/`orchestration/*`/`filestore.py`；`config/nssm-services.json` 删除须**与 _constants 白名单条目同时回退**（否则打包 zf.write 抛错）；测试文件删除即回退 |
| **P0-3** commit 失败仪表 | **达标** | `core/database.py`、`tests/test_db_commit_metric.py` | 计数 +1、异常仍上抛、`request=None` 不炸（t1 35 passed exit 0，含真 app 200 回归）；`/metrics` 暴露 `db_commit_failures_total`（惰性注册防热重载重复） | 纯新增：删计数块与测试即回退 |
| **P0-4** 审批域时钟 | **达标** | `shared_models/approval.py`、`tests/test_approval_clock_utc.py` | 同一操作两条记录时间差 < 1 分钟；AST 扫描无本地 `datetime.now`（31 passed exit 0） | 还原 `approval.py` 两行（`:63`/`:133`） |
| **P0-5** 业务日口径 | **达标** | `services/stock_common.py`、`tests/test_business_day_stock_common.py` | 冻结 `2026-09-30T16:30Z`（北京 `2026-10-01 00:30`）断言业务日 = `2026-10-01`（5 passed exit 0） | 还原 `stock_common.py` 1 行（`business_now()` 调用点） |
| **P0-6** 暴露面与限流（含 N2/N3） | **达标（代码半）** | `core/limiter.py`、`core/prod_runner.py`、`main.py`、`api/v1/endpoints/customer_sampling.py`、`scripts/restart_backend.py`、`config/pgbouncer/pgbouncer.ini`、2 个新测试 | 限流键随身份变化（5 端点 `limit.key_func is rate_limit_key`；同用户换 IP 同桶、同 IP 异用户异桶、匿名回退 IP、vitals e2e 429 后换身份放行）；`customer_sampling` 9 个 GET 加 `require_any_permission` 且 403 有测试；`0.0.0.0`→`127.0.0.1` 三处（prod_runner/restart_backend/pgbouncer.ini）；`default_limits` 为空时不注册 `SlowAPIMiddleware`（等价删除空转）；t2 4 条 verify 全 exit 0（162/124/70/34 passed） | 逐处单行回退：`prod_runner.py:263/:270`、`restart_backend.py:68/:70`、`pgbouncer.ini:15`、`limiter.py` 的 `rate_limit_key`、`main.py` 的 `key_func=` 删除行、5 处装饰器 `key_func=`、`customer_sampling.py` 依赖行。**回退后需重启后端/pgbouncer 才恢复原行为（生产机项）** |
| **P0-7** 门禁注释旁路封堵 | **达标** | `scripts/check_service_commit.py`、`scripts/gate_baseline.json`、`docs/TRANSACTION_BOUNDARY_GUIDE.md`、`backup/metrics/alert_service.py` | FAIL 计数 **9 → 12**（探针 `git show HEAD:<path>` × 新旧 ALLOWED_PATTERNS：旧规则+HEAD=9、新规则+工作树=12；与 `--json total=12`、`gate_baseline.json` 三方一致）；`--self-test` 8/8；`quality_gate.py --only service_commit` exit 0 [PASS]；两条宽规则（`# independent[-_]transaction`、`#.*commit(`）全局过滤结果 0 命中 | 单文件回退 `check_service_commit.py` + `gate_baseline.json`（12→9）+ 文档；`alert_service.py` 注释行还原 |
| **P0-8** 死代码清理 + 白名单⊆导入图 | **达标** | 见 §2.1 P0-8 行（8 删 / 3 改新） | 删除 7 个零入边模块 + 1 悬挂测试（952 行）；逐模块 grep/AST 复核（含 PEP 562 `utils/__init__.py` 惰性导出）；`check_orphan_modules.py` exit 0（白名单 107 ⊆ 导入图 107，人工孤儿探针 exit 1）；`mypy.ini` 110→107 且纯 ASCII（修 `cp936` 下检查前 `UnicodeDecodeError` 根因）；3 个保留项各有**反证**（见 §5 R-5） | `git revert`（7 个删除文件 + `mypy.ini` + `utils/__init__.py`）；新增脚本/测试删除即回退 |
| **P0-9** OCR 必现 NameError | **达标（已具备/加回归）** | 2 个新测试（实现未改） | AST 证明 HEAD 即已声明 `_pdf_extracter`、`batch_import_dedup.py` 注解已是 `Iterable`（mypy.ini 旧注释过期）；两条最小回归测试 + ast 未绑定名检查 exit 0 | 删除 2 个测试文件即回退（无实现改动） |
| **P0-10** 依赖显式声明 + 死配置 | **达标** | `.env`（删 3 死键）、`.env.example`、`requirements/test.txt`、`core/middleware.py`、`core/health.py`、`core/telemetry.py`、`core/database.py`、新测试 | `.env` 键级对比：**仅少 3 个死键**（`DB_POOL_SIZE`/`DB_MAX_OVERFLOW`/`DB_POOL_RECYCLE`，删除前已键级取证），其余键值未变；`itsdangerous` 声明**撤回**（`git diff HEAD -- requirements/base.txt` 为空，全仓 0 处 import，`middleware.py` 原 `except ImportError` 为不可达死分支，已随删除）；`requirements/test.txt` 补 4 个测试依赖；`check_env_drift.py --ci` exit 0；`telemetry.py` 显式 SpanExporter 标注后 mypy exit 0；`.env.example` 说明池参数真实来源 `UVICORN_WORKERS×DB_MAX_CONNECTIONS` | `.env` 死键如需回滚 = **手工加回 3 行**（原值见 t1 键级取证；`.env.bak-pre-p010` 已在取证后删除，不再存在）；其余单文件 `git revert` |
| **P0-11** 门禁本体加固 | **达标** | `scripts/quality_gate.py`、`check_service_commit.py`、`check_bare_except.py`、`check_function_length.py`、`check_vue_component_length.py`、`gate_baseline.json`、`pyproject.toml`、`.github/workflows/ci-cd.yml` | `quality_gate.py` 重写为 4 种语义模式（子脚本 --json/纯 exit code/ruff JSON/pip-audit 策略），**不再有任何 stdout 正则**；`--self-test` 在 `--only` 隔离下双向证明（人为违规 exit 1 + REGRESS、移除违规 exit 0）48 项；ruff 棘轮 61（配置口径，不经 CLI --select/--ignore）；`pyproject.toml` 增 `pip_audit_max_days=180` 与 `[[tool.code-quality.pip-audit-ignores]]` 策略门禁（过期/僵尸/超上限/缺字段/未豁免漏洞全 FAIL）；`ci-cd.yml` 增 self-test、--only ruff、check_orphan_modules.py 三步 | 单文件回退 `scripts/*.py` + `pyproject.toml` + `ci-cd.yml` + `gate_baseline.json`（注意 `gate_baseline.json` 单写者 = gatekeeper） |
| **P0-12** 上传魔数 + 内存放大 | **达标** | `core/validators.py`、`core/middleware.py`、5 个端点文件、2 改 1 新测试 | 魔数层（`magic_signature`/`matches_upload_magic`/`validate_upload_magic`/`require_upload_magic`）接入 6 处真实上传路径，失败 **400** 并记录文件签名（改扩展名伪 xlsx 被拒有测试）；无 `Content-Length` 时累积计数**提前 413**；既有 `test_request_body_limit_paths.py` parity 不破（+42 行新用例）；`test_ocr_order_preview.py` 适配真实 PNG 签名后仍通过 | 魔数校验**按端点逐个开关回退**（`validators.py` 层保留）；`middleware.py` 计数器行回退 |

---

## 5. 未达标项与缺口

### 5.1 未达标项

**0 项。** 11 个 P0 编号项（9 项纯代码改动）全部达到 `docs/optimization-plan-2026-10-01-final.md` §1 的验收口径，且经过独立复算（§3 + `docs/p0-verification-2026-10-01.md` §4）。

### 5.2 已登记缺口 / 残余风险（均**不阻塞**本次代码批收口）

| ID | 缺口 | 影响 | 归属 / 下一步 |
|---|---|---|---|
| **R-1** | `config/nginx-windows.conf` 仍有 **5 处** `limit_req_dry_run on;`（第 90/191/200/355/364 行附近） | nginx 侧 `limit_req` 仍**只记录不拒绝**；后端侧限流键修复（P0-6(d)）与条件注册（P0-6(e)）不受影响 | **captain 已裁决延后**（plan §6.1：生产行为变更、无预发、文件由并发外部会话持有）；补丁与前置检查见 `docs/p0-ops-checklist-2026-10-01.md` §3①，由用户签核 |
| **R-2** | `customer_sampling_view` 权限行全仓 **不存在**（`migrations/` 0 命中） | 无 `customer_sampling_manage` 码的登录账号读 9 个 GET 现在 **403**（fail-closed，即 P0-6(a) 目的）；若真有「能看不能改」只读账号，其读取会 403 | **captain 已裁决保留收紧**（plan §6.2）；如生产需要只读角色，需单独立项补幂等迁移（补种权限 + 授权，照 `pg_standalone_043` 范式） |
| **R-3** | 本机**未安装** `pip-audit` | `quality_gate.py` 的 `pip_audit` 门禁在本机 **WARN 跳过**，本机 [PASS] 不含真实漏洞库判定 | 已列入运维清单（可选，不阻塞）：`pip install pip-audit`；CI 侧不受影响（`ci-cd.yml:136` 以 `--audit-report` 运行） |
| **R-4** | `.env` 无 `RATE_LIMIT_DEFAULT` | `SlowAPIMiddleware` 不注册（等价删除空转，无副作用）；未装饰路由不受全局限流 | 生产 `.env` 加 `RATE_LIMIT_DEFAULT=300/minute` 即生效（**无需改代码**），建议先观察 |
| **R-5** | P0-8 三个「保留项」各有反证 | `purchase_order_service.py`（仅 `scripts/perf_benchmark.py:78` 引用）、`purchase_order_spare.py`（文档标注「已实施」但 `recompute_po_spare_from_item_rates` 从未接进 `purchase_order_crud.py`，生产仍走 `purchase_order_sku.py:214`）、`utils/logger.py`（有活测试消费者） | P1 收口项：改 `scripts/` 引用后可删前者；后两者是**接线缺口**而非死代码，需单独立项 |
| **R-6** | `docs/TRANSACTION_BOUNDARY_GUIDE.md` 与实现的历史行号漂移 | `:91`/`:106` 引用的 `cleanup/service.py:599` 因 t8 新增 docstring 变为 **:604** | **已由 t10 修复**（并复核全文 12/12 锚点 MATCH）；本批无残留 |

### 5.3 如实记录的偏差（非缺陷）

1. `scripts/check_service_commit.py` 的实测 exit code 是 **1**（扫描器语义：命中即非零），基线比对在 `quality_gate.py`（`--only service_commit` → exit 0）。§3 已逐字说明，避免下游误读为红灯。
2. 验证期（t6）与集成期（t7）各跑一次全量 `pytest -q`，两次均为 **3585 passed / 267 skipped / 0 FAILED·ERROR**（t7 为 t12 落地后串行复跑）。
3. `config/nginx-windows.conf` 的 +216/−2 由**并发外部会话**产生，本团队对该文件**贡献为 0**、未 `git add`；条目已按 plan §6.1 如实登记（未计入本批变更）。
4. `docs/p0-review-2026-10-01.md`（t11 评审）已列为新增文档；t11 verdict = `pass`，其 4 条 low findings（F-01 无用 noqa / F-02·F-03 导入排序 / F-04 断言被放宽）已由 **t12 全部关闭**，并已并入 §2 的最终 diff。

---

## 6. 仍需用户在场执行的运维动作清单

> 出自 `docs/p0-ops-checklist-2026-10-01.md`（配套 plan §1/§6）；**全部不在团队委派范围**。铁律：一次只动一簇，每步先验证再下一步。

### 6.1 P0-1 凭据与文件权限收口（**全部**）

1. **1-A ACL 收紧**（先 `icacls /save D:\erp_acl_backup\erp_system.acl /T`）：对 `.env`、`.env.production`、`.env.development`、`_ops\credentials`、`config\pgbouncer\userlist.txt`、`backups`、`logs`、`certs` 执行 `/inheritance:r` + 仅留 Administrators/SYSTEM/NETWORK SERVICE/本机管理员。验证：`icacls` 输出无 `BUILTIN\Users`/`NT AUTHORITY\Authenticated Users`；非管理员读 `.env` 被拒。
2. **1-B 凭据迁出仓库**：`_ops\credentials\` 下 `_backup_encryption_password.txt`、`_metrics_bearer_token.txt`、两份 `.env.bak-*` 迁入 `D:\erp_secrets\`（同收紧 ACL）。**待用户拍板**：`AGENTS.md:29`/`:70` 是否改指 `D:\erp_secrets\`。
3. **1-C 口令轮换**（严格顺序）：`METRICS_BEARER_TOKEN` → `/metrics` 200 → `DB_PASSWORD`/`REDIS_PASSWORD` → `ready:true` → **BACKUP_ENCRYPTION_PASSWORD 最后**（且**先完成 6.2-A 演练**证明现有 `.enc` 可解）。

### 6.2 P0-2 运维半

- **2-A 恢复演练**（改备份口令的**前置条件**）：`.venv\Scripts\python.exe scripts\restore_drill.py` → 输出 `status=ok`，`backups/server/recovery_tests/` 出现当日 `m5_drill_raw_*.json`（此前仅 1 份，断档 39 天）。**注意**：备份没停（ARQ cron `0 2 * * *` / `0 */1 * * *`）；`\ERPSystem`、`\ERP_Database_Backup` 是 Disabled 死任务，别按它们排障。
- **2-B watchdog 任务注册**：`scripts\ops\install_watchdog_task.ps1` → `schtasks /query /tn <任务名> /v` 确认 `LastTaskResult=0`，`logs/watchdog.log` 有新增。
- **2-C 至少一个真实告警出口**：启用 `BACKUP_ALERT_WEBHOOK_ENABLED=true`（或 EMAIL）并做一次真实投递（现状零出口）。
- **2-D 异机/离线副本**：每日全量 `.zip.enc` 同步到另一台主机/移动盘 + 记录校验和并抽查可解（现状与生产同机同盘）。
- **2-E 演练与备份门禁**：把「演练产物 < 30 天」「当日备份产物存在」做成 `scripts/prod_audit/` 门禁（团队不写该目录）。

### 6.3 让 P0-6 的代码改动生效（**需重启，属生产行为变更**）

- **nginx**：`limit_req_dry_run` 转正（5 处）→ `nginx.exe -t` 验语法 → `nginx.exe -s reload`（reload 不是 restart）。**当前建议保持 on; **（R-1 / plan §6.1：观察 3–7 天无正常用户误伤后再改 reject）。
- **后端重启**：低峰期重启后确认 `Get-NetTCPConnection -State Listen` 中 **5002 仅 127.0.0.1**，`logs/prod_runner.json` `ready:true` 且 `frontend_ok:true`；再用两个不同伪造 `X-Forwarded-For` 打 `/api/v1/auth/login`，应落**同一**限流桶并触发 429。

### 6.4 可选（不阻塞 P0 收口）

- 装 `pip-audit` 让本机门禁也覆盖依赖漏洞（R-3）；豁免**只能**加在 `pyproject.toml` 的 `[[tool.code-quality.pip-audit-ignores]]`。

---

## 7. P1 / P2 / P3 状态

| 批次 | 主题 | 项数 | 工时 | 状态 |
|---|---|---|---|---|
| **P1 收口** | 库存不变量、并发幂等、门禁机械化、契约校验 | 12 | 8–12 人日 | **未开工**（0/12） |
| **P2 补齐** | 前端减重、传输安全、审计字段、类型与测试欠账 | 12 | 12–18 人日 | **未开工**（0/12） |
| **P3 结构性** | 库存单一真相、拆上帝对象、字段级审计、行级权限 | 6 | 20–30 人日 | **未开工**（0/6） |
| **P4 治理** | 执行台账、门禁对象纠偏、验收标准 | 3 | 持续 | 本轮产出本文件 + `docs/p0-verification-2026-10-01.md` + `docs/p0-review-2026-10-01.md` |

本轮**只执行 P0**；P1–P3 的详表见 `docs/optimization-plan-2026-10-01-round3.md` §2–§4。

---

## 8. 任务级执行记录（t1–t12）

| 任务 | 成员 | 类型 | 状态 | 产出摘要 |
|---|---|---|---|---|
| t1 | be-core | implementation | completed | P0-3/4/5/10（含 captain 裁决四项追加） |
| t2 | be-sec | implementation | completed | P0-6/9/12 + P0-10 中间件降级死分支删除 |
| t3 | gatekeeper | implementation | completed | P0-7 + P0-11（12 文件，基线单写者） |
| t4 | janitor | implementation | completed | P0-8（删 7 模块 + 1 测试，952 行；新增导入图校验） |
| t5 | backup-eng | implementation | completed | P0-2 代码半①②③④ |
| t6 | verifier | verification | completed | 独立验证 9 项 P0，`docs/p0-verification-2026-10-01.md` |
| t8 | backup-eng | implementation | completed | P0-2 补丁：命名空间一致性 + 运行时 `.env` 敏感闸门 + 保留策略消费方接线 |
| t9 | janitor | work | completed | 测试环境收口（bleach 缺失致收集中断治愈；备份打包 setup 失败定性） |
| t10 | gatekeeper | work | completed | `TRANSACTION_BOUNDARY_GUIDE.md` 行号 599→604 + 全文 12 锚点复核 |
| t11 | be-sec | review | completed（verdict=pass） | t8 独立评审，9 条 low/info，`docs/p0-review-2026-10-01.md` |
| t12 | backup-eng | repair | completed | 关闭 t11 的 F-01/F-02/F-03/F-04（3 个测试文件） |
| **t7** | **verifier** | **integration** | **本文件** | P0 执行台账 + 最终 diff 汇总 + 残余风险 |

**提交纪律**：全部任务只改工作树，无 `git add`/`commit`/`checkout`/`stash`；`scripts/gate_baseline.json` 单写者（gatekeeper）；`.env` 口令与密钥值未被修改。

---

## 9. 新增文档产物（未跟踪）

| 文件 | 来源 | 用途 |
|---|---|---|
| `docs/optimization-execution-ledger-2026-10-01.md` | t7（本文件） | 集成台账 |
| `docs/p0-verification-2026-10-01.md` | t6 | 独立验证三件套 |
| `docs/p0-review-2026-10-01.md` | t11 | t8 独立评审（verdict=pass） |
| `docs/p0-ops-checklist-2026-10-01.md` | captain | 生产机运维动作清单 |
| `docs/optimization-plan-2026-10-01-final.md`（及 round2/round3、audit-round3、round2-claim-verification、p0-exec-checklist、`docs/audit-round2/`） | 规划期 | 唯一执行依据与证据源 |

---

## 10. 一致性声明

本文件与 `docs/p0-verification-2026-10-01.md` **无矛盾**：

- 四条验证命令的 exit code 逐字一致（quality_gate 0 / mypy 0 / pytest 0 / check_service_commit 1 并附语义说明）。
- 五项数字复算一致（service_commit 9→12、ruff=61、mypy 覆盖 107、`.meta` 伴随清理 + 保留策略单源、限流键随身份变化）。
- 缺口清单一致：R-1（nginx dry_run）、R-2（`customer_sampling_view`）、R-3（pip-audit 缺失）、R-5（P0-8 三个保留项）、R-6（文档行号，**已由 t10 修复**）与验证台账登记的 5 条残余一一对应；R-4（`.env` 无 `RATE_LIMIT_DEFAULT`）为本文件按 plan §6.4 补登的第 6 条。
- 差异仅两处**增量**：①本文件纳入 t11/t12（评审 + 收尾修复）后的最终 diff 与测试结果（2427 insertions、pytest 354.45s）；②本文件新增 §6 运维清单与 §7 P1–P3 状态。验证台账的结论未被修改。
