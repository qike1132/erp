# P1 收口批执行台账（集成视图，2026-10-01）

- **任务**：t27（kind=integration，attempt 1 = `5e7c1eb0-cc71-45ee-b81d-6520a5b07b4d`），集成人 = verifier（独立验证之外不改任何实现文件）
- **汇总对象**：P1 收口批全部实现/修复/评审任务（t13～t43 系列，见 §4）+ P0 止血批已提交成果（`d2fa8baa`）
- **验证基线**：`HEAD = 73b3a93cc85a5dc6fec352a8d599679ec02df18f`（2026-10-01 20:26:11，P0 提交之后的第 4 个提交）
- **本台账唯一写入**：`docs/p1-execution-ledger-2026-10-01.md`（未跟踪）；未改任何实现文件（§9）
- **上游验证结论**：`docs/p1-verification-2026-10-01.md`（289 行 / 32198 B / SHA256 `9ECCA58CC9A0F95AA521F954582CB9205F857F4D3B27138A57F471886798A39D`）—— 总判定「达标可收口、未达标项 0」

---

## 1 结论（TL;DR）

| 维度 | 状态 |
| --- | --- |
| ~~**最终验收（全仓 `ruff format` 后的树，2026-10-01 23:29:29–23:36:44）**~~ **【历史 · 已废止】** | **未通过（红）**：`pytest` = **1**（`16 failed, 3770 passed, 268 skipped in 404.55s`），`quality_gate.py --verbose` = 0 `[PASS]`，`mypy` = 0，`scan_secrets` = 0 ⇒ **当时不定稿、等待裁决**；**裁决 B 已回退该树**（下一行 = 最终状态）。触发原因全部是**测试对源码文本（引号/行号/行数）的断言被格式化打破**，非产品缺陷（该 format 树已按裁决 B 全部回退，未进入任何提交；本节数据作为红灯对照留档） |
| **★ 最终状态（裁决 B 已落地：format 树废弃、回退后树四件套全绿）** | **`pytest` = 0**（`3786 passed, 268 skipped in 440.15s`，0 failed / 0 errors）、**`quality_gate` = 0** `[PASS]`（十类与基线一致，含 `function_length 51` / `bare_except 5` / `ruff 60` / `service_commit 12`）、**`mypy` = 0**（`Success: no issues found in 144 source files`）、**`scan_secrets` = 0** `[PASS]`；证据 = `D:\erp_system\logs\_final_p1_acceptance3.log`（1733631 B，START 2026-10-01T23:41:34 / END 23:49:25；**本任务直读原日志逐行确认**，§2.5）。以下为回退与工作树现状：**format churn（1048 files）已全部回退、未进入任何提交**；工作树仅剩本轮「钩子/配置修复」= 本任务实测 **2 files / 9(+) / 3(−)**（`.pre-commit-config.yaml` + `ruff.toml`）；`gate_baseline.json` 回到 **`function_length = 51`**、`db_health.py` 回到 HEAD 版本、`TRANSACTION_BOUNDARY_GUIDE.md` 回到 format 前版本（t44 改动随之回退）；全仓格式化登记为 **P2 `R-repo-format`**（§2.5）。**本任务在回退后的树上独立复跑 `quality_gate.py --verbose` = exit 0 `[PASS]`**（§2.5），与 captain 的最终验收 `QG_EXIT=0` 同树一致 |
| P1 收口批实现项 | **12/12 达标**（P1-1…P1-12，另 P1-2b/P1-11/P1-12 follow-up 全部关闭）；未达标项 **0** |
| P0 止血批已提交成果 | **未被回退**（§3：`d2fa8baa` 是 HEAD 祖先 + 死代码仍缺席 + P0 符号在位 + 门禁基线一致） |
| `scripts/quality_gate.py`（本任务 verify 命令；**已跑三次：提交前树 / format 后树 / 裁决 B 回退后树**） | **exit 0** `[PASS]`（三次），10 门禁逐行「与基线一致」。**最近一次 = 回退后的当前树（HEAD `100569f8`）：`function_length 51 / bare_except 5 / service_commit 12 / ruff 60`，证据 `%TEMP%\t27-integrator\qg_postrevert.out`（§2.5）**。另两次为历史：提交前树一次；format 树一次（`function_length = 68`，已废止，§2.3，证据 `%TEMP%\t27-integrator\qg_postformat.out`） |
| `pytest -q --ignore=tests/stress`（**最终 = 裁决 B 回退后的树**） | **exit 0**，`3786 passed, 268 skipped in 440.15s (0:07:20)`，**0 failed / 0 errors**（`_final_p1_acceptance3.log` 的 `PYTEST_EXIT=0`，本任务直读原日志确认；§2.5）。**历史对照**：提交 `993fd728` 的树同样 `3786 passed / 0 failed`；已废止的 format 树为 exit 1（`16 failed, 3770 passed, 268 skipped in 404.55s`，§2.4 独立复现 16/16） |
| `mypy --config-file mypy.ini`（**最终 = 裁决 B 回退后的树**） | **exit 0**，`Success: no issues found in 144 source files`（`_final_p1_acceptance3.log` 的 `MYPY_EXIT=0`；本任务直读原日志确认）。历史两次同值（P1 提交前树本任务实测、format 树 captain 实测） |
| 交付规模（提交口径） | **P1 功能提交 `993fd728` = 64 files changed, 7518 insertions(+), 613 deletions(-)**（`M=45 / A=18 / D=1`）；**其后 `100569f8`（外部会话 OPT-19）= 4 files / 127(+) / 110(−)**；**本轮待提交的钩子修复 = 2 files / 9(+) / 3(−)**（§2.1）。已无「style 提交」 |
| 待用户在场执行 | **1 个有生产风险动作**（迁移 061）+ P0-1/P0-2 运维半 + nginx reload 与后端重启 + PG 连接预算确认（§6） |
| P2 / P3 / P4 | **未开工**（0 项落地；仅 P2「传输安全」子集的 4 个运维动作由外部会话完成并提交，§7） |
| 并发外部会话在途产物 | **2 项，captain 已裁定本次提交排除**（`config/nginx-windows.conf` 的 secure_link 启用 + 硬编码 md5 串、`config/tls/ca.crt`）——非 P1 批次产物，见 §5.1 R-1/R-2 与 §8 |

---

## 2 最终工作树 diff 规模与按路径分组的改动清单

### 2.1 规模与口径（`D:\erp_system`；A/A2/B = 历史时点口径，C = **裁决 B 回退后的当前状态**）

**A. 提交口径（= 本批交付口径）**

```text
$ git log --oneline -1
 993fd728 feat(p1): P1 收口批落地（库存对账/负库存策略/乐观锁统一/编号单调/锁序/审计批写/ARQ 幂等/前端契约/门禁机械）
$ git show --stat --oneline 993fd728 | tail -1
 64 files changed, 7518 insertions(+), 613 deletions(-)
$ git show --name-status --format= 993fd728  ->  M=45  A=18  D=1
```

**A2. 提交口径 ②：`100569f8`（并发外部会话的 OPT-19；非本批产物，已进历史）**

```text
$ git show --stat --oneline 100569f8 | tail -1
 4 files changed, 127 insertions(+), 110 deletions(-)
（M：config/nginx-windows.conf / fastapi_app/schemas/product.py /
       fastapi_app/services/storage_service.py / fastapi_app/tests/test_signed_urls.py）
父提交 = 993fd728
```

⇒ **实际提交历史 = `993fd728`（P1 功能批）→ `100569f8`（OPT-19）→ 待提交的「钩子/配置修复」（§2.5）**；**不再存在「全仓 format 的 style 提交」**（裁定 B 取消）。

**B. 提交前工作树口径（历史：23:1x，HEAD 当时 = `73b3a93c`）**

```text
$ git diff HEAD --shortstat
 47 files changed, 1970 insertions(+), 625 deletions(-)
$ git status --porcelain | Measure-Object  ->  66 项
  46 × " M"（tracked 修改） + 1 × " D"（tracked 删除） + 19 × "??"（未跟踪新增）
```

**C. 【当前状态】裁决 B 回退后的工作树（HEAD = `100569f8`，本任务独立复核）**

```text
$ git status --porcelain      -> 4 项
 M .pre-commit-config.yaml    （钩子修复：ruff-pre-commit rev v0.11.0 → v0.16.9，删除 ruff-format 钩子并以注释说明）
 M ruff.toml                  （[format] quote-style "single" → "double"）
?? config/tls/ca.crt          （R-2，外部会话产物，已裁定排除）
?? docs/p1-execution-ledger-2026-10-01.md   （本台账，t27 唯一写入）
$ git diff HEAD --shortstat   ->  2 files changed, 9 insertions(+), 3 deletions(-)
$ git log --oneline -2        ->  100569f8 / 993fd728
```

- 全仓 format churn（1048 files）已按**用户裁决 B = 回退 format + 修钩子**由 captain 以 `git restore --worktree -- .` 全部回退，**未进入任何提交**；本任务复核确认工作树仅剩上表 4 项。
- `scripts/gate_baseline.json` 现值 **`function_length = 51`**（本任务独立读取：另为 `bare_except 5 / vue 7 / service_commit 12 / bom 0 / alembic 0 / env_drift 0 / ruff 60 / pip_audit 0`，与 P0 提交一致；format 期间标定的「例外二」`_comment` 已随回退消失，`_comment` 里现只保留 P0-7 的 `service_commit 9→12` 说明）。
- ⚠ **口径差 1 项**：本任务实测钩子修复 = **2 个 tracked 文件 / 9 insertions / 3 deletions**（captain 口径写「3 个文件」）；差额 1 不在本任务可见范围内（`config/tls/ca.crt` 为未跟踪且已裁定排除）。
- 该回退使 **P2 独立项 `R-repo-format`** 生效：全仓格式化**前置条件 = 先把 16 个源码文本守卫测试改成抗格式**（§2.4），届时单独一轮提交。
- **回退后树的最终验收（`logs\_final_p1_acceptance3.log`）= 全绿**：`pytest 3786 passed / 268 skipped / 440.15s`（exit 0）、`quality_gate exit 0 [PASS]`、`mypy exit 0 (144 files)`、`scan_secrets exit 0` ⇒ **本台账定稿（§2.6）**。

口径与漂移说明：

- **本批交付口径 = 提交 `993fd728`**：**64 files changed（45 M + 1 D + 18 A）**、`7518 insertions(+) / 613 deletions(−)`。已**排除** `config/nginx-windows.conf`（R-1，留在工作树）与 `config/tls/ca.crt`（R-2，未跟踪），本台账草稿亦不在提交内（captain 实测，本任务用 `git show --stat/--name-status` 独立复核一致）。§2.2 表 **A–I 组 = 45 M + 1 D**，**18 个未跟踪新增件**（§2.2 表内 `（新）` 行）与之对应；**表 J 组两项即被排除者**。
- 上表 **B** 的 47 files / 1970(+) / 625(−) / 66 项是**提交前**的原始工作树数字（未剔除 R-1/R-2）；**A 的 64 files / 7518(+) / 613(−) 才是本批交付口径**。`--shortstat` 不含未跟踪文件，故 A 的 `64 = 45 + 1 + 18` 需显式计入新增件。
- 数字时点链（务必按「时点」读）：t26 round 3 三门禁跑在 `1964 insertions(+)` 的树上（23:02:05–23:08:33）→ 提交前 `1970(+)`（+6 全部来自 R-1 的 `config/nginx-windows.conf`，numstat `14/12`）→ **提交 `993fd728`**（已剔除 R-1/R-2）→ **全仓 `ruff format`（当前工作树，1051 files 未提交）**。⇒ 提交前那次 round 3 结论只对「提交 `993fd728` 的那批 Python/config 文件」成立；**任何「当前树」门禁数字必须以 format 之后重跑为准**（§2.3、§8 第 6 条）。
- 提交前未跟踪新增件（19 件，字节数实测；其中 **18 件已进 `993fd728`**，`config/tls/ca.crt` 按 R-2 排除）：文档 3（`docs/p1-review-p1-3-2026-10-01.md` 15085 / `docs/p1-review-p1-6-2026-10-01.md` 23079 / `docs/p1-verification-2026-10-01.md` 32198）、新模块 2（`fastapi_app/services/inventory_reconcile.py` 5993、`fastapi_app/tasks/inventory_reconcile_task.py` 2043）、新测试 11（test_arq_idempotency 11529 / test_audit_middleware_batching 9538 / test_backup_sidecar_delete_failure 8286 / test_inventory_reconcile 8903 / test_numbering_sequence_monotonic 8126 / test_order_batch_lock_order 15460 / test_order_deduction_completeness 26120 / test_product_stock_check_constraint 12219 / test_stock_negative_policy 20788 / test_stock_negative_policy_repo_wide 35854 / test_stock_optimistic_lock_unification 15243）、迁移 1（`migrations/versions/pg_standalone_061_add_product_stock_check.py` 4103）、门禁脚本 1（`scripts/check_openapi_frontend_alignment.py` 13881）、运维产物 1（`config/tls/ca.crt` 1927）。

### 2.2 按路径分组的改动清单

> **口径**：本节描述 **P1 功能提交 `993fd728`** 的内容（本批交付口径），已按裁决 B 回退树的现状见 §2.1-C 与 §2.5。**J 组两项**现已各自结案：`config/nginx-windows.conf` 由外部会话在 `100569f8` 中自行提交，`config/tls/ca.crt` 仍未跟踪并继续排除。

行数为 `git diff HEAD --numstat` 的 `+ / −`；「归属」= 该文件所属 P1 项（`报告` = 来自该任务 changedPaths 报告；`读 diff` = 我读 diff 内容判定）。

| 组 | 文件 | +/− | 归属（依据） |
| --- | --- | --- | --- |
| **A 库存不变量（P1-1/1-3/1-6）** | `fastapi_app/services/inventory_reconcile.py`（新） | 5993 B | P1-1（报告） |
| | `fastapi_app/tasks/inventory_reconcile_task.py`（新） | 2043 B | P1-1（报告） |
| | `fastapi_app/tests/test_inventory_reconcile.py`（新） | 8903 B | P1-1/t29（报告） |
| | `fastapi_app/shared/stock_concurrency.py` | 226 / 31 | P1-3（t15）+ P1-6（t22/t39）（报告） |
| | `fastapi_app/tests/test_stock_optimistic_lock_unification.py`（新） | 15243 B | P1-3（报告） |
| | `fastapi_app/shared_models/product.py` | 4 / 1 | P1-6（报告：`CheckConstraint`） |
| | `migrations/versions/pg_standalone_061_add_product_stock_check.py`（新） | 4103 B | P1-6（报告，down_revision=060，单 head） |
| | `fastapi_app/tests/test_product_stock_check_constraint.py`（新） | 12219 B | P1-6（报告） |
| | `fastapi_app/tests/test_stock_negative_policy.py`（新） | 20788 B | P1-2（t14）/ P1-6（t39 集合断言）（报告） |
| | `fastapi_app/tests/test_stock_negative_policy_repo_wide.py`（新） | 35854 B | P1-2b（t31，51 例）（报告） |
| | `.env.example` | 17 / 0 | P1-2 + P1-6（t14/t29/t39：策略开关与 CHECK 互斥说明）（读 diff） |
| **B 统一入口调用点收口（P1-2b，t31/t42）** | `fastapi_app/services/{stock_out,stock_in,stock_return}_service.py` | 33/12、11/4、14/6 | P1-2b（t31；我逐条读过 `approval_service.py` 的同类 hunk）（读 diff） |
| | `fastapi_app/services/staging/stockout.py`、`order/commands.py`、`order/deduction.py`、`order_deduction_service.py`、`case/commands.py`、`batch_import_core.py`、`batch_import_service.py`、`product_service.py`、`approval_service.py`、`ocr/_import.py` | 6/3、6/3、49/9、6/3、16/6、3/2、13/5、11/4、6/3、3/1 | P1-2b（t31 报告称「11 处判定接入、8 文件 +82/−34」；t42 另收口 `product_service.py`）。**本 diff 中同组文件多于 8 个**（含其它 P1 任务同期改动），逐文件任务号未逐一取证 ⇒ 标为读 diff 推断 |
| **C 并发/幂等/编号/锁序** | `fastapi_app/services/numbering_sequence.py` | 19 / 5 | P1-4（t16）（报告） |
| | `fastapi_app/tests/test_numbering_sequence_monotonic.py`（新） | 8126 B | P1-4（报告） |
| | `fastapi_app/services/order_batch_create.py` | 29 / 8 | P1-5（t17）（报告） |
| | `fastapi_app/tests/test_order_batch_lock_order.py`（新） | 15460 B | P1-5（报告） |
| | `fastapi_app/core/arq_app.py` | 175 / 0 | P1-7（t23）（报告） |
| | `fastapi_app/tasks/batch_tasks.py` | 100 / 31 | P1-7（t23）（报告） |
| | `fastapi_app/tests/test_arq_idempotency.py`（新） | 11529 B | P1-7（报告） |
| **D 审计热路径（P1-9）** | `fastapi_app/core/audit_middleware.py` | 124 / 32 | P1-9（t18）（报告） |
| | `fastapi_app/tests/test_audit_middleware_batching.py`（新） | 9538 B | P1-9（报告） |
| **E 抵扣完整性（P1-8）** | `fastapi_app/tests/test_order_deduction_completeness.py`（新） | 26120 B | P1-8（t33）/ 修复 t43（报告；SHA256 `456853641DDF8CCF9CC295B42C4F64550A05610BD70D9EE4CAB2AE947F899AC5`） |
| | `tests/test_stock.py`、`tests/test_stock_concurrency.py` | 79/1、27/2 | t41（F-01 修复，测试侧）（读 diff：桩 `side_effect`/`execute` 序列补齐） |
| **F 门禁机械化（P1-10）** | `scripts/check_service_commit.py` | 255 / 167 | P1-10①（t19：正则→AST）（报告） |
| | `mypy.ini` | 60 / 2 | P1-10②（t20 +38 模块）/ t36 −1（145→144）（报告） |
| | `scripts/gate_baseline.json` | 1 / 1 | P1-10③（t30：`ruff 61 → 60` **收紧**）（读 diff，见 §3-E4） |
| | `.github/workflows/ci-cd.yml` | 10 / 0 | P1-10（报告） |
| | `frontend-vite/scripts/check-route-alignment.mjs` | 225 / 56 | P1-12（t24/t34：修「恒不失败」）（报告） |
| | `scripts/check_openapi_frontend_alignment.py`（新） | 13881 B | P1-12（t24/t34）（报告） |
| | `frontend-vite/src/api/report.ts` | 0 / 1 | P1-12（§6.14 裁决：删前端死端点 `customerNames`）（读 diff） |
| | `docs/TRANSACTION_BOUNDARY_GUIDE.md` | 17 / 5 | P1-10/P0-7 文档同步（t19 报行号并发漂移）（读 diff） |
| **G 死代码与兼容层（P1-11）** | `fastapi_app/services/base_search_service.py` | 1 / 36 | P1-11（t37：删 `SyncSelectQuery`/`search_sync`）（报告） |
| | `fastapi_app/services/product_search_service.py` | 2 / 44 | P1-11（t37）（报告） |
| | `fastapi_app/services/purchase_order_service.py`（删除） | 0 / 65 | t36（报告） |
| | `scripts/perf_benchmark.py` | 1 / 1 | t36（报告：改指生产路径） |
| | `fastapi_app/shared/report_data_service.py` | 35 / 31 | P1-11 系列（`.filter(` → `.where(`）（读 diff） |
| | `fastapi_app/tests/test_order_item_migration.py` | 24 / 16 | t35（alembic 替身补 `_legacy_base_guard`；据 diff 内容与 P1 follow-up 清单）（读 diff） |
| **H 备份域（P1-residual t25/t38 + P0-2 尾款）** | `fastapi_app/services/backup/cleanup/service.py` | 3 / 1 | t38（报告：errors 透传） |
| | `fastapi_app/services/backup/records.py` | 17 / 4 | t25/t38（报告：`_delete_backup_sidecars(errors=…)`） |
| | `fastapi_app/services/backup/orchestration/policy_service.py` | 9 / 2 | P0-2 ③ 单源（t8 补丁；读 diff：去掉硬编码 30） |
| | `fastapi_app/tasks/backup_tasks.py` | 34 / 3 | t25/t38 下游（读 diff） |
| | `fastapi_app/tests/test_backup_retention_policy.py` | 69 / 1 | t38（报告，18 例） |
| | `fastapi_app/tests/test_backup_sidecar_delete_failure.py`（新） | 8286 B | t38（报告） |
| | `config/README.md` | 11 / 2 | t38(c)（报告：灾备件口径重写） |
| | `config/nssm-services.json` | 1 / 1 | t38/其自述与 README 对齐（读 diff） |
| **I 文档（captain/评审人，非实现）** | `docs/optimization-plan-2026-10-01-final.md` | 133 / 0 | captain（读 diff：§6.x 裁决追加） |
| | `docs/p0-ops-checklist-2026-10-01.md` | 69 / 0 | captain（读 diff：新增 §6-A…§6-D） |
| | `alembic.ini` | 2 / 2 | t40-F-04 修复（陈旧 head 注释 060→061）（读 diff） |
| | `docs/p1-review-p1-3-2026-10-01.md`（新） | 15085 B | t32 评审（报告） |
| | `docs/p1-review-p1-6-2026-10-01.md`（新） | 23079 B | t40 评审（报告，sha1 `77045F5DA4679E7849D6A43635CA8E3993DB2CE0`） |
| **J 非本批（并发外部会话，已裁定排除）** | `config/nginx-windows.conf` | 14 / 12 | **非 P1**：23:10:16 由外部会话启用 `secure_link` 并硬编码 md5 串（§5.1 R-1）→ **本次提交排除** |
| | `config/tls/ca.crt`（新） | 1927 B | **非 P1**：443 自签 TLS 产物（§5.1 R-2）→ **本次提交排除**（入库与否由该会话决定） |

分类合计核对：**提交 `993fd728` = 45 M + 1 D + 18 A = 64 files**（与 `git show --stat` 的 64 一致）；**提交前树** = 46 M + 1 D = 47 tracked + 19 `??`（与当时 `--shortstat` 一致）。

### 2.3 【历史 · 已废弃，未进入任何提交】全仓 `ruff format`（style 提交）带来的门禁漂移（独立复核）

> **状态（2026-10-01 23:4x 起）：本节全部内容为历史记录。** 用户最终裁决 **B = 回退 format + 修钩子**：captain 已 `git restore --worktree -- .` 把 1048 个 format 文件全部回退，**该 format 树已废弃、未进入任何提交**。回退后：`scripts/gate_baseline.json` = **`function_length 51`**（「例外二」`_comment` 消失）；`fastapi_app/core/db_health.py` 回到 HEAD 版本（:118 单行 `except Exception:  # defensive: …  # noqa: S110  # nosec B110`，`bare_except` 仍 **5**）；`docs/TRANSACTION_BOUNDARY_GUIDE.md` 回到 format 前版本（**t44 为 format 漂移所做的行号改动随之回退**；该文档自身行号锚点的现状见 §2.5）。全仓格式化改登记为 **P2 独立项 `R-repo-format`**，前置 = 先修 §2.4 的 16 个守卫测试。
>
> 以下是当时的漂移分析，保留以备 `R-repo-format` 开工时复用：

用户裁决 `docs/optimization-plan-2026-10-01-final.md` §6.9 方案 (b)：**接受单引号**，并先做一次全仓 `ruff format` 作为**独立 style 提交**（与 P1 功能提交分开）。captain 实测（ruff 0.16.9）：`1047 files reformatted, 308 files left unchanged`；`ruff format --check` 复验 `1355 files already formatted`。

| 门禁 | 变化 | 原因 | 复核与处置 |
| --- | --- | --- | --- |
| `function_length` | **51 → 68** | 19 个函数因折行跨过 80 行阈值、2 个因合并降回阈值下，算术闭合 `51 − 2 + 19 = 68`，**纯格式化造成、无函数被新写长** | `scripts/gate_baseline.json` 一次性重新标定，`_comment` 登记「**例外二**」并指向 final plan §6.28。**本任务独立读取基线文件确认现值 `function_length = 68`**，`_comment` 原文含「例外二：2026-10-01 全仓 ruff format 后 function_length 51→68，19 个函数因折行跨过 80 行阈值、2 个因合并降回阈值下，纯格式化造成」 |
| `bare_except` | 5 → **6（瞬时）** → **5** | `fastapi_app/core/db_health.py` 的 `except Exception:` 被折成三行，`scripts/check_bare_except.py` 只检查 `node.lineno` 那一行的注释 ⇒ 原有 `# defensive:` 豁免失效 | 已修复为**单行**：`fastapi_app/core/db_health.py:120` = `except Exception:  # noqa: S110  # nosec B110  # defensive: metrics non-fatal`（本任务 `Select-String` 独立复核在位于 :120；`ruff format --check` 报 already formatted ⇒ 不会再被折行）⇒ 复算 `total = 5`，**基线未放宽** |
| `ruff` | 60（不变） | format 是格式化动作，不改变 `ruff check` 违规计数 | 基线保持 60 |

修复后 captain 复跑 `scripts\quality_gate.py --verbose` = **exit 0 `[PASS]`**（`function_length = 68` / `bare_except = 5` / `ruff = 60` / `service_commit = 12`，其余与基线一致）。

**本任务独立复算（format 后的当前树上，只读、非 pytest、不触测试库）**：

```text
$ D:\erp_system\.venv\Scripts\python.exe scripts\check_function_length.py --json
  ... "total": 68            (rc=1：扫描器只要存在违规即非零；基线比对在 quality_gate.py)
$ ...\python.exe scripts\check_bare_except.py --json
  {"violations": [records.py:825/867/879/896/900], "parse_errors": 0, "total": 5}   (rc=1，同上)
$ ...\python.exe scripts\quality_gate.py --verbose   ->  RC=0
  OK  N+1 = 0 / except = 5 / 函数长度 = 68 / Vue = 7 / service_commit = 12 / BOM = 0
  OK  Alembic = 0 / env 漂移 = 0 / ruff = 60 / pip-audit = 0（未装 ⇒ 仅 [WARN]）
  [PASS] 无新增违规。
```

⇒ 三个数字（`function_length = 68`、`bare_except = 5`、`ruff = 60`）与基线**独立复算一致**；`db_health.py` 已不在 `bare_except` 命中列表内（5 处命中全在 `fastapi_app/services/backup/records.py`，均为既有存量）。证据落盘 `%TEMP%\t27-integrator\qg_postformat.out`。

⚠ **行号引用面**：`docs/TRANSACTION_BOUNDARY_GUIDE.md` 中 `service_commit` 豁免行号锚点会随 format 漂移，已另派 **t44（gatekeeper）** 逐条重核；**本台账引用该文档行号时以 t44 结果为准**（本台账本身不引用其具体行号）。

### 2.4 【历史 · 红灯对照留档】format 后最终验收 16 failed：全为「源码文本级守卫」被格式化打断（本任务独立复现）

> **状态：该 format 树已按裁决 B 全部回退，未进入任何提交**；本节作为**红灯对照口径**留档，也是 P2 项 `R-repo-format` 的前置工作清单（开工前必须把这 16 个断言改成抗格式）。当前树的最终验收以 `logs\_final_p1_acceptance3.log`（§2.5、§8）为准。

captain 的最终验收（format 后的树，后台作业 `pwsh-1733`，日志 `D:\erp_system\logs\_final_p1_acceptance2.log`，23:29:29–23:36:44；日志由 PowerShell 重定向写成 UTF-16，本任务直接读取其原文）：

```text
PYTEST_EXIT=1    16 failed, 3770 passed, 268 skipped in 404.55s (0:06:44)
QG_EXIT=0        scripts\quality_gate.py --verbose  ->  [PASS]
MYPY_EXIT=0      Success: no issues found in 144 source files
SCAN_EXIT=0      scan_secrets  ->  [PASS]
```

对照口径：**format 之前**的同一命令（提交 `993fd728` 的树）= `3786 passed, 268 skipped`、**0 failed**。

**16 个失败逐条 + 本任务独立复现**（只跑窄范围定向命令、串行、不与任何全量套件并发）：

| # | 测试 | 失败数 | 复现证据 | 根因（读源码/diff 判定） |
| --- | --- | --- | --- | --- |
| 1 | `fastapi_app/tests/test_strict_auth_wiring.py` | 6 | 复现 **6 failed**（`%TEMP%\t27-integrator\guard_repro_static.out`：`13 failed, 27 passed in 5.97s`，rc=1） | 该测试 `:53` 用 `src.index(f'prefix="{prefix}",')`（**双引号**）定位路由；format 后 `fastapi_app/api/v1/router.py:88` 变成 `prefix='/products',` ⇒ 锚点找不到（纯引号差异） |
| 2 | `tests/test_gates_cover_repo_root.py` | 4 | 同上 | 折行使 `server_manager/app.py` 达 **1891 行**（本任务实测）> 文件行数门禁 1600 阈值；函数长度门禁在 `server_manager/` 亦现违规 |
| 3 | `tests/test_server_manager_erp_web.py::test_install_flow_has_erp_web` | 1 | 同上 | 文本级断言被折行打断 |
| 4 | `fastapi_app/tests/test_log_policy_unification.py::test_prod_runner_uses_shared_policy_and_maintenance` | 1 | 同上 | 断言 `'LOG_POLICY_PATH = PROJECT_ROOT / "config" / "log_policy.json'`（双引号）不再逐字出现 |
| 5 | `tests/test_health_backup_signal.py::test_health_route_wires_backup_block` | 1 | 同上 | 断言 `'health_data["backup"] = await _backup_signal()'` 同上 |
| 6 | `fastapi_app/tests/test_stock_negative_policy.py` | 2 | 复现 **2 failed**（`%TEMP%\t27-integrator\guard_repro_db.out`：`3 failed, 62 passed in 6.09s`，rc=1） | 断言**精确行号集合**：期望 `stats.py:20…`，实测 `stats.py:27…`（折行导致行号漂移） |
| 7 | `tests/test_purchase_plan_order_quota.py::TestAdmissionWiringGuards::test_staging_validates_order_remaining` | 1 | 同上 | 同类：`commands.py` 行号漂移（`assert ['stats.py:27...'] == ['stats.py:20...']`、`assert 0 == 2`） |

⇒ **16 = 6 + 4 + 1 + 1 + 1 + 2 + 1**：本任务在 **7 个测试文件**上逐条复现出**完全相同的 16 个失败**，无一属环境/连接类偶发（与本批 `R-pg` 的建连期失败无关）。

**性质判定**：16 个失败全部是**测试对源码文本（引号风格 / 精确行号 / 行数）的断言被 `ruff format` 打破**，**不是产品缺陷**；但它们使「全仓 format」不能作为纯 style 提交直接落地。captain 的对照实验（改用 `--config "format.quote-style='double'"`，1033 files reformatted 后定向复跑）仍 **15 failed / 90 passed** ⇒ 引号只解释一部分，其余约 10 个由折行/重排造成 ⇒ **任何全仓 format 都必须先修约 10 个守卫测试**（把断言改为结构不敏感形式，或同步锚点）。

**状态**：captain 已将「保留 format 需修约 10 个守卫测试」与两个方案报用户裁决 ⇒ **t27 保持 `in_progress`，不定稿、不结案**（§8 第 6 条）。本台账此前的绿色数字（§2.3）**只对门禁 10 类成立**，不能代表最终验收通过。

### 2.5 裁决 B（回退 format + 修钩子）后的现状、独立复核与新发现

**captain 执行的动作（我未参与、未执行任何 git 写操作）**：① `git restore --worktree -- .` 把工作树恢复到 HEAD（`100569f8`），1048 个 format 文件全部回退；② 钩子修复（本轮待提交）：`.pre-commit-config.yaml` 的 `ruff-pre-commit rev: v0.11.0 → v0.16.9` 且**删除 `ruff-format` 钩子**（原位置改为说明注释），`ruff.toml` 的 `[format] quote-style "single" → "double"` ⇒ 计划 §6.18 第 6 项「提交钩子冲突」关闭，**后续提交不再需要 `--no-verify`**；③ 全仓格式化登记为 **P2 独立项 `R-repo-format`**（前置 = 先把 §2.4 的 16 个守卫测试改成抗格式）。

**本任务独立复核（只读 + `quality_gate.py`；未碰 git 写操作、未跑全量 pytest）**

```text
$ git log --oneline -2        ->  100569f8 feat(security): 前端切换签名 URL 完成——secure_link 激活并五连测验收（OPT-19 闭环）
                                  993fd728 feat(p1): P1 收口批落地（…）
$ git show --stat --oneline 100569f8 | tail -1
 4 files changed, 127 insertions(+), 110 deletions(-)   ← 与 captain 口径一致
$ git status --porcelain      ->  4 项（2 M + 2 ??，见 §2.1-C）
$ git diff HEAD --shortstat   ->  2 files changed, 9 insertions(+), 3 deletions(-)
$ Get-Content scripts\gate_baseline.json -Encoding UTF8
 function_length = 51（另 bare_except 5 / service_commit 12 / ruff 60 / env_drift 0 …）
$ .venv\Scripts\python.exe scripts\check_function_length.py --json   -> "total": 51   （rc=1 为扫描器语义）
$ .venv\Scripts\python.exe scripts\check_bare_except.py --json      -> "total": 5    （rc=1 同上）
$ .venv\Scripts\python.exe scripts\quality_gate.py --verbose        -> QG_EXIT=0  [PASS]
  OK N+1=0 / except=5 / 函数长度=51 / Vue=7 / service_commit=12 / BOM=0
  OK Alembic=0 / env 漂移=0 / ruff=60 / pip-audit=0（未装 ⇒ 仅 [WARN]）
  [PASS] 无新增违规。
=> 证据落盘 %TEMP%\t27-integrator\qg_postrevert.out
```

⇒ **回退后的树十类门禁全部「与基线一致」（exit 0 [PASS]）**，其中 `function_length` 由 format 期的 68 回落到 **51**、`bare_except` 由 5→6 的瞬时漂移回到 **5**，`ruff` 保持 60、`service_commit` 保持 12（P0-7 的 12 未被回退）。`db_health.py` 现状（本任务实测）：`:118 except Exception:  # defensive: metrics collection failure must not interrupt health checks  # noqa: S110  # nosec B110`（单行、仅一处 `except Exception`，全文件 170 行）。

**新发现 R-3（low）：`docs/TRANSACTION_BOUNDARY_GUIDE.md` §4 行号锚点有 3 行已陈旧（与 format 无关，是 P1 批次改行造成）**

该表自称「行号是 2026-10-01 的实测值…以脚本输出为准」（文档 §4 尾部注释）。本任务用 `scripts/check_service_commit.py --json` 复算 **total = 12**（与 `gate_baseline.json` 一致），逐行对照后 **3 行陈旧**：

| 文档锚点（§4 表） | 实测（HEAD = `100569f8`） | 差额 |
| --- | --- | --- |
| `services/backup/cleanup/service.py:604`（表行 :99、另 :114 复述） | `:606` | +2（`993fd728` 对该文件 `+3/−1` ⇒ 净 +2） |
| `services/backup/orchestration/policy_service.py:544` | `:549` | +5 |
| `services/backup/records.py:791,803,822` | `:804,816,835` | +13/+13/+13 |

其余 6 行锚点（`auth_service.py:63,72` / `incremental.py:397` / `metrics/alert_service.py:222` / `recovery_test_service.py:573` / `restore.py:267` / `strategies.py:133`）与实测一致；12 处命中总数正确。**性质**：纯文档锚点漂移（无脚本校验文档行号、门禁只认计数），且文档自身声明「以脚本输出为准」⇒ 不影响门禁与验收，但会让评审者按行号找不到位置。**建议**：交回 gatekeeper（t44）在**无 format** 的当前树上同步这 3 行；本任务只读、不代改（`docs/` 下除本台账外的文件不在 t27 写域）。

### 2.6 定稿依据：裁决 B 回退后树的最终验收四件套（全绿）

**captain 后台作业 `pwsh-1769`**，日志 `D:\erp_system\logs\_final_p1_acceptance3.log`（**1733631 B**；START `2026-10-01T23:41:34` / END `23:49:25`），树 = `100569f8` + 本轮钩子/配置修复：

```text
================ 3786 passed, 268 skipped in 440.15s (0:07:20) ================
PYTEST_EXIT=0
QG_EXIT=0
Success: no issues found in 144 source files
MYPY_EXIT=0
[PASS] …未新增或未豁免的凭据…
SCAN_EXIT=0
```

**本任务独立复核方式**：只读读取该日志原文（`Get-Content -Encoding Unicode`，日志为 UTF-16），逐行确认上面 6 行与其顺序，**不采信转述**。

**四件套与 §1 的对应**：

| 口径 | 结果 | 与历史口径的差别 |
| --- | --- | --- |
| `pytest -q --ignore=tests/stress` | `3786 passed, 268 skipped in 440.15s`，**0 failed / 0 errors**，`PYTEST_EXIT=0` | 与提交 `993fd728` 树的 `3786 passed` 同值；format 树的 `16 failed` 已随回退消失（§2.4 留作对照） |
| `scripts\quality_gate.py --verbose` | `QG_EXIT=0` `[PASS]`，十类与基线一致（`function_length 51` / `bare_except 5` / `ruff 60` / `service_commit 12` …） | format 期的 `function_length 68` 与「例外二」基线标定**随回退作废** |
| `mypy --config-file mypy.ini` | `MYPY_EXIT=0`，`144 source files` | 与历史同值 |
| `scan_secrets` | `SCAN_EXIT=0` `[PASS]` | 无变化 |

**结论（最终状态）**：**裁决 B 已落地 —— format 树废弃（未进入任何提交、1048 files 已回退），回退后树四件套全绿**；本台账据此定稿，t27 完成。剩余未闭合项全部是**本批之外或需用户在场**的动作：§5 的 R-3（文档锚点，已派 t45）、F-03/F-04/F-05/F-07/R-pg、§5.4 的 9 项 P2 级残留、§6 的 9 项运维动作、§7 的 P2/P3/P4。

---

## 3 P0 已提交成果未被回退的证明

| # | 证据 | 实测 |
| --- | --- | --- |
| **E1** | P0 提交在 HEAD 祖先链上 | `git merge-base --is-ancestor d2fa8baa HEAD` → rc **0**；`d2fa8baa`（`fix(p0): P0 止血批落地（凭据/门禁旁路/时钟/备份/限流/上传魔数/死代码）`，2026-10-01 18:01:23）之后的 4 个提交全是 ops/security/前端 URL 收口，**无 revert**：`b5ae3a94`、`5a01faa1`、`bc41ae7b`、`73b3a93c` |
| **E2** | P0 删除的 8 个死模块仍缺席 | `Test-Path` 全 `False`：`fastapi_app/core/alert_rules.py`、`core/domains.py`、`schemas/purchase.py`、`services/batch_pipeline.py`、`services/backup/_stream.py`、`shared_models/base.py`、`utils/batch_upload_utils.py`、`fastapi_app/tests/test_batch_pipeline.py`。P1 期间**又**追加删除 `fastapi_app/services/purchase_order_service.py`（`0 / 65`，t36） |
| **E3** | P0 关键落地符号在当前工作树在位 | `fastapi_app/core/database.py:223` `db_commit_failures_total`（P0-3）；`fastapi_app/core/limiter.py:56` `def rate_limit_key`（P0-6）；`fastapi_app/services/stock_common.py:11` `def business_now`（P0-5）；`fastapi_app/core/validators.py:175` `def require_upload_magic` / `:137` `def matches_upload_magic`（P0-12）；`fastapi_app/shared_models/approval.py:21` `_utcnow` 且 `:56/:63/:130/:133` 四个 default/onupdate 全部指向它（P0-4） |
| **E4** | 门禁基线一致且只降不升 | `scripts/gate_baseline.json` 现值 = `n_plus_one 0 / bare_except 5 / function_length 51 / vue_component_length 7 / service_commit 12 / bom 0 / alembic_heads 0 / env_drift 0 / ruff 60 / pip_audit 0`。**P0 定的 `service_commit = 12` 仍保持**；唯一变化是 `ruff 61 → 60`（P1-10③ t30 收紧，方向正确）。`scripts/quality_gate.py` 本轮实测 exit **0** `[PASS]`，10 类逐行「与基线一致」 |
| **E5** | P0 交付文件在 P1 期间未被回退 | `scripts/quality_gate.py`（P0-11 重写）与 `pyproject.toml`（P0-11 pip-audit 策略）、`requirements/base.txt`（P0-10 声明）**均不在当前 diff 中** ⇒ 与 P0 提交版本逐字节相同。P1 只在 `scripts/check_service_commit.py`（`255/167`）、`ci-cd.yml`（`10/0`）、`mypy.ini`（`60/2`）上做**叠加式**硬化，未删 P0 的 AST 判定或 self-test |
| **E6** | 红线未被触碰 | 当前 diff 不含 `frontend-vite/vite.config.js`；`alembic heads` 单 head（门禁 `alembic_heads = 0`）；无新增 `0.0.0.0` 绑定（P0-6 暴露面收口未被回改） |

---

## 4 P1 逐项状态（集成视图；逐项证据链见 `docs/p1-verification-2026-10-01.md` §6）

| 项 | 主题（主任务） | 状态 | 关键证据（摘要） |
| --- | --- | --- | --- |
| P1-1 | 库存只读对账（t13 / t29） | 达标（复算） | 对账 SQL 为单条集合式 `LEFT JOIN + GROUP BY`；模块内 `commit/add/delete/flush/rollback` 调用数 0；默认关闭（`.env` 无 `INVENTORY_RECONCILE_ENABLED` ⇒ cron 不注册） |
| P1-2 | 参数化负库存策略（t14） | 达标（复算） | `ALLOW_NEGATIVE_STOCK` 缺省 = 拒绝；开关行为可观测（t39 后随策略附加原子守卫） |
| P1-2b | 其余内联判定接入统一入口（t31 / t39 / t42） | 达标（复算） | 全仓「`.current_stock` 序关系比较」集合恰为 `{stock_concurrency.py:146/:199/:278, dashboard/stats.py:208（只读阈值，具名豁免）}`；`product_service.py` 内联硬拒已不存在 |
| P1-3 | 扣减统一乐观锁（t15；评审 t32） | 达标（复算 + 运行复现） | `_classify_update_miss` 精确分流；t41 修复后 `tests/test_stock*.py` 全绿 |
| P1-4 | 编号计数单调性（t16） | 达标（复算） | 单调性用例 + 并发分配用例 |
| P1-5 | 批量创建锁顺序（t17） | 达标（复算） | 无序 `purchase_order_spare` 已死，锁序用例通过 |
| P1-6 | DB CHECK + 原子守卫（t22 迁移；t39 条件化；评审 t40） | **代码半达标；DB 半未上线（属运维，§6）** | 真实库 SQL 捕获 33/33 PASS；一次性库端到端 14/14 PASS；dev 库 `alembic_version` 仍 = `pg_standalone_060_fix_updated_at_varchar_columns`、无 `ck_product_current_stock_nonneg` |
| P1-7 | ARQ 幂等键 + 循环 commit 批量化（t23） | 达标（复算） | 幂等键空间/批量提交形状复算；Redis 不可用 fail-open |
| P1-8 | 抵扣完整性校验（t33 / 修复 t43） | 达标（运行复现） | 定向 12 passed；全量语境两例真实库用例 PASSED |
| P1-9 | 审计写入移出请求热路径（t18） | 达标（复算） | 批量 INSERT 形状与 `params=22` 复算 |
| P1-10 | 门禁硬化（t19 AST / t20 mypy / t30 ruff） | 达标（复算） | 三门禁 + `--self-test` 48 项 + `check_service_commit --self-test` 14 项 + `check_orphan_modules` 144⊆144（WARN 0） |
| P1-11 | 遗留 `.query(` 清理（t21；t37 follow-up） | 达标（复算） | 同步死路径与 `SyncSelectQuery` 已删（全仓 0 外部引用，双向 grep+AST 复证） |
| P1-12 | 前端契约真校验（t24 / t34） | 达标（复算 + 灵敏度反证） | `check-route-alignment.mjs` 注入缺陷即非零退出；openapi 对齐 `status=pass`（`backendPaths=343`、`missing=[]`） |
| P1-residual | 备份残留（t25 / t38） | 达标（运行复现 + 复算） | 伴随文件失败进 `errors` 聚合；`config/README.md` 与 nssm 自述一致（含一致性断言） |

**未达标项：0**。唯二的非「全绿」条目都是既定的边界：P1-6 的 DB 半（属运维上线动作）与 `pip_audit` 门禁本机 WARN（§5 F-04）。

---

## 5 残留风险清单（单列）

### 5.1 本任务新发现（非 P1 批次；captain 已裁定：本次提交排除，需外部会话自证）

| ID | 级别 | 事实 | 建议处置 |
| --- | --- | --- | --- |
| **R-1** | **high（提交面）** | `config/nginx-windows.conf` 在 23:10:16 被**外部会话**改成**启用** `secure_link`（`secure_link $arg_st,$arg_s;` + `secure_link_md5 "$secure_link_expires$uri 0829c6a6b01cafc47788ccc04297dd382838bdfc1f77e5ef1a58b1e5d6e32589";`）。该提交前状态（`bc41ae7b`）是「注释态回退 + 防呆护栏」，注释明确写「重新启用前必须先用签名 URL 实测 200 再上」 | **裁定（captain）：本次提交排除。** 属该会话在途工作，介入会与其冲突；且 `bc41ae7b` 复盘结论要求「重新启用前先用签名 URL 实测 200」，非本批所能签核 ⇒ **需外部会话自证**（提供签名 URL 实测 200 / 存量直链不再 403 的证据）后方可入库。另注：md5 串是硬编码密钥材料，与 §6.3 `UPLOAD_URL_SIGNING_SECRET` 口径需一致 |
| **R-2** | low | `config/tls/ca.crt`（1927 B）为未跟踪的 443 自签 TLS 产物，与 `b5ae3a94`（443 TLS）相关 | **裁定（captain）：本次提交排除**（未跟踪、443 自签产物、属外部会话；入库与否由该会话决定，本批不碰）。若入库需确认不含私钥 |
| **R-3** | low | `docs/TRANSACTION_BOUNDARY_GUIDE.md` §4 行号锚点 **3 行陈旧**（与 format 无关，P1 批次改行造成）：`cleanup/service.py:604→606`、`policy_service.py:544→549`、`records.py:791/803/822→804/816/835`；12 处命中总数与 `gate_baseline.json` 一致（§2.5 独立复算） | 交 **t44/gatekeeper** 在**无 format 的当前树**上同步（文档 §4 自称「以脚本输出为准」，不影响门禁/验收）；本任务只读不代改 |

### 5.2 t26 验证的遗留（转载，均为非阻断）

| ID | 级别 | 事实 | 处置 |
| --- | --- | --- | --- |
| F-03 | low | 迁移 061 未落 dev 库（`alembic_version` = 060、无 CHECK 约束）；代码侧守卫已生效 | **运维**：§6 步骤 ①–④（本批唯一生产风险动作） |
| F-04 | low | 本机未装 `pip-audit` ⇒ 门禁第 10 类只 WARN，本机 `[PASS]` 不含真实漏洞库判定（CI 不受影响） | 可选：`pip install pip-audit` 后 `--only pip_audit`（`docs/p0-ops-checklist-2026-10-01.md` §5） |
| F-05 | info | `tests/stress` 未评估（`--collect-only` 仅 1 项 `<Coroutine test_login>`） | 接受现状；最终验收沿用 `--ignore=tests/stress` |
| F-07 | low | `_is_test_db_url()` 只认「以 `_test` 结尾」，派生库名仍会算错库名，但连接异常已被捕获 ⇒ 后果降级为 `skip` | 后续以 `TEST_DATABASE_URL` 为唯一真源 |
| R-pg | medium（环境） | PG 连接预算饱和（97/100）导致全量套件偶发建连期失败 | captain 已执行 `ALTER SYSTEM SET idle_session_timeout='5min'` + `pg_reload_conf()`；实测二次运行 `3786 passed` exit 0。若复发立即参照 §6-D |

### 5.3 t40 评审遗留（转载，非阻断）

| ID | 级别 | 事实 | 处置 |
| --- | --- | --- | --- |
| t40-F-01 | info | 整链离线 `alembic upgrade head --sql` 在 060 之前即 `NoInspectionAvailable(MockConnection)`（与 061 无关的既有离线渲染限制） | 登记 P2 |
| t40-F-02 | low | = F-03（已转运维清单） | 见上 |
| t40-F-03 | low | `ALLOW_NEGATIVE_STOCK=true` 与已落库 CHECK 互斥，需手工 `DROP CONSTRAINT`（不可逆） | 既定设计（plan §6.19），已写入 `.env.example` 与 ops 清单 §6-A 末条 |
| t40-F-04 | info | `alembic.ini` 陈旧 head 注释 | **已修复**（现为 `100 revisions, exactly one head (pg_standalone_061_add_product_stock_check) and 4 roots`，diff 2 行，仍纯 ASCII） |
| t40-F-05 | info | 迁移 INFO 日志在默认 `logger_root = WARN` 下不可见 | 已写入 ops 清单（升级加 `-v`） |

### 5.4 P2 级残留（plan §6.18 原文登记 + 本批追加）

1. `fastapi_app/ARCHITECTURE_IMPROVEMENT_REPORT.md:90` 仍引用已删除的 `build_search_query_sync`（t37 按契约未改历史报告）。
2. 根目录脚本不在 ruff 棘轮范围：全仓 `ruff check` 实测 108 条 vs 门禁 60 条，范围外 48 条（`docs/audit-round2/scripts/*` 28、`docs/tickets/tools/rebuild_migration.py` 7、`docs/ui-redesign/*.py` 2 等）。
3. `pip-audit` 未安装（= F-04）。
4. `.env` 无 `RATE_LIMIT_DEFAULT` ⇒ 全局限流未启用（加一行即生效）。
5. nginx 5 处 `limit_req_dry_run on;` 转正待用户运维窗口签核（plan §6.1）。
6. 提交钩子冲突（`.pre-commit-config.yaml` 的 `ruff-pre-commit v0.11.0` + `ruff-format` 与 `ruff.toml [format] quote-style="single"`）：未裁决前提交需 `--no-verify`（plan §6.9）。
7. mypy 扩面后续 tranche：`mypy.ini` 已 107 → 144 个模块；未列入的 96 个模块携带约 490 个 error（`follow_imports=silent` ⇒ 门禁不变松）。
8. 备份清理失败**文案失真**（t38 披露未修）：`cleanup/service.py:642` 的 `report['success']` 会让伴随文件删除失败走到 `tasks/backup_tasks.py:601` 的 else 分支并记「未知错误」+ severity=error 告警；方向正确、文案待修（为该 report 透出 `error/errors` 即可）。
9. 部署态 env 文件键集差异：`.env`、`.env.production`、`config/.env.production`（三者均**未被 git 跟踪**）与 `.env.example` 的键差异需在下次部署前人工对齐（缺失即走安全默认：拒绝负库存 / 对账关闭 / 签名 URL 禁用）。

---

## 6 待用户在场执行的运维项（团队不执行、不重启任何服务）

| # | 项 | 位置/命令 | 说明 |
| --- | --- | --- | --- |
| 1 | **迁移 061（本批唯一生产风险动作）** | ops 清单 §6-A | ①只读查负值 → ②按现有流程备份 → ③`D:\erp_system\.venv\Scripts\python.exe -m alembic upgrade head -v` → ④`-m alembic current`；`neg_rows>0` 时约束以 `NOT VALID` 建立，对平后 `ALTER TABLE product VALIDATE CONSTRAINT ck_product_current_stock_nonneg;`；回滚 `-m alembic downgrade pg_standalone_060_fix_updated_at_varchar_columns`（幂等） |
| 2 | P0-1 凭据与文件权限 | ops 清单 §1-A/1-B/1-C | ACL 收紧（先 `icacls /save` 备份）→ 凭据迁出仓库 → 口令轮换（顺序严格） |
| 3 | P0-2 运维半 | ops 清单 §2-A…2-E | 恢复演练（改口令前置）→ watchdog 任务注册 → 至少一个真实告警出口 → 异机/离线副本 → 演练与备份门禁 |
| 4 | 让 P0-6 生效 | ops 清单 §3 | nginx reload + 后端重启 + 伪造 XFF 验证限流桶 + `customer_sampling` 无权限 403 |
| 5 | PG 连接预算 | ops 清单 §6-D | 三选一；captain 已执行 ②（`idle_session_timeout='5min'` + `pg_reload_conf()`），最终验收前建议再确认一次空闲连接数 |
| 6 | `pip-audit`（可选） | ops 清单 §5 | 不阻塞收口；豁免只能写在 `pyproject.toml [[tool.code-quality.pip-audit-ignores]]`（含 `id/expires(≤180 天)/reason`） |
| 7 | 部署态 env 键对齐 | §5.4 第 9 项 | 涉及生产凭据文件，团队不代改 |
| 8 | nginx `limit_req` 转正 | plan §6.1 | 5 处 `dry_run on;`（行 90/191/200/355/364 附近，锚点 = 紧随 `limit_req zone=… nodelay;` 那行）；另一并发会话已改注释声明「观察 3–7 天后再 reject」 |
| 9 | 提交前裁定 R-1/R-2 | §5.1 | `config/nginx-windows.conf` 是否纳入本次提交 |

---

## 7 P2 / P3 / P4 未开工状态

| 批次 | 主题 | 项数 | 工时（计划） | 状态 | 关键项 |
| --- | --- | --- | --- | --- | --- |
| **P2 补齐** | 前端减重、传输安全、审计字段、类型与测试欠账（+ 新登记 **`R-repo-format`**：全仓格式化） | 12 + 1 | 12–18 人日 | **未开工（0 项落地）**；仅「传输安全」子集的 4 个运维动作由外部会话完成并提交（`b5ae3a94`：复制槽 active / 443 TLS / `limit_req` dry_run / 签名 URL），其中 dry_run **转正仍待签核** | **`R-repo-format`**（裁决 B 后新登记：全仓 `ruff format`，**前置 = 先把 §2.4 的 16 个源码文本守卫测试改成抗格式**，届时单独一轮提交）；首屏 672 KB primevue chunk（改 `.ts` 后必须重跑 `vue-tsc -b`）；`as unknown as` 131 处；内网 TLS + `limit_req` 转正；PG `5432` 收口；审计字段/软删除；mypy 扩面；时区收敛 |
| **P3 结构性** | 库存单一真相、拆上帝对象、字段级审计、行级权限 | 6 | 20–30 人日 | **未开工** | P3-1 库存单一真相（`inventory_log` 为唯一真相、`current_stock` 降级为派生缓存，分 5 阶段） |
| **P4 治理** | 执行台账、门禁对象纠偏、验收标准 | 3 | 持续 | **持续执行中** | 本台账 + `docs/optimization-execution-ledger-2026-10-01.md`（P0）+ `docs/p1-verification-2026-10-01.md`（验证） |

P2 起步前的前置依赖（本批已就绪）：P1-1 只读对账（先对账后上约束）、P1-6 的 DB CHECK 已就绪待上线、P1-10 门禁可机械判定。

---

## 8 提交建议（供 captain 单点提交）

1. **必须按显式路径清单挑选，绝不 `git add -A` / `git add .`**（工作树里有并发外部会话的在途产物）。**status：已按此执行**——P1 功能提交 = **`993fd728`**（**64 files changed**：45 M + 1 D + 18 A，`7518(+)/613(−)`）；**排除** = J 组的 `config/nginx-windows.conf`（R-1）与 `config/tls/ca.crt`（R-2）——**captain 已裁定，两者均未进提交**（当前 `??` 仅剩 `config/tls/ca.crt` 与本台账草稿）。见 §2.1-A、§5.1。
2. 未跟踪件需 `git add` 明确列名（逐条路径，不用通配）：3 份 `docs/p1-*`、2 个新模块（`fastapi_app/services/inventory_reconcile.py`、`fastapi_app/tasks/inventory_reconcile_task.py`）、11 个新测试、1 个迁移（`migrations/versions/pg_standalone_061_add_product_stock_check.py`）、`scripts/check_openapi_frontend_alignment.py`。**`config/tls/ca.crt` 明确排除**（§5.1 R-2）。
3. `.env` / `.env.production` / `config/.env.production` **未被 git 跟踪**（含凭据），本次不涉及、不要误加。
4. **提交钩子冲突 → 已关闭（本轮）**：「钩子/配置修复」提交把 `ruff-pre-commit` 升到 `v0.16.9` 并**删除 `ruff-format` 钩子**、`ruff.toml` 的 `[format] quote-style` 改为 `"double"` ⇒ 后续提交**不再需要** `--no-verify`（§2.5；plan §6.18 第 6 项关闭）。
5. **R-1/R-2 结案方式**：R-1（`config/nginx-windows.conf` 的 `secure_link` 启用 + 硬编码 md5 串）已由**外部会话自己在 `100569f8`（OPT-19）中提交**（4 files/127+/110−，未与本批混提交）⇒ 本批无需再决定其去留；本任务独立复核确认该提交只含 4 个文件、不含本批任何文件。**R-2**（`config/tls/ca.crt`，未跟踪）**继续排除**。
6. **提交顺序（用户裁决 B = 回退 format + 修钩子）**：
   - ① **P1 功能提交 = `993fd728`，已完成**（64 files / 7518(+) / 613(−)，§2.1-A）；
   - ② **钩子/配置修复（本轮，待提交）**：`.pre-commit-config.yaml`（`rev v0.11.0 → v0.16.9`、删 `ruff-format` 钩子）+ `ruff.toml`（`quote-style "single" → "double"`）= 本任务实测 **2 files / 9(+) / 3(−)**（§2.1-C）；提交信息建议标注「关闭提交钩子冲突」；
   - ③ ~~style 提交（全仓 `ruff format`）~~ **已取消**（裁决 B）；全仓格式化登记为 **P2 独立项 `R-repo-format`**（前置 = 先把 §2.4 的 16 个守卫测试改成抗格式）。
7. 【已废止 · 历史留档】原「§6.9 方案 (b)」驱动的 style 提交计划（裁决 B 已取消；以下全部作废）：
8. **最终验收（已到手 · 全绿）** = `D:\erp_system\logs\_final_p1_acceptance3.log`（captain 后台作业 `pwsh-1769`；1733631 B；START `2026-10-01T23:41:34` / END `23:49:25`；树 = `100569f8` + 本轮钩子修复）：
   - `PYTEST_EXIT=0` —— `3786 passed, 268 skipped in 440.15s (0:07:20)`（0 failed / 0 errors）；
   - `QG_EXIT=0` —— 十类与基线一致（`function_length 51` / `bare_except 5` / `ruff 60` / `service_commit 12` …）；
   - `MYPY_EXIT=0` —— `Success: no issues found in 144 source files`；
   - `SCAN_EXIT=0` —— `[PASS]`（无新增/未豁免凭据）。
   **本任务独立读取该日志原文逐行确认上述四行与末行统计**（§2.5）。⇒ **裁决 B 落地、format 树废弃、回退后树全绿**，本台账据此**定稿**；`_final_p1_acceptance2.log`（format 树，`PYTEST_EXIT=1` / 16 failed）仅作红灯对照留档（§2.4）。提交顺序按第 6 条执行（① 已完成 → ② 本轮钩子修复 → ③ 无 style 提交）。
   - ① **P1 功能提交 = `993fd728`，已完成**（64 files / 7518(+) / 613(−)，§2.1-A）；
   - ② **style 提交 = 全仓 `ruff format`**：已执行（`1047 files reformatted, 308 files left unchanged`；`--check` 报 `1355 files already formatted`），**当前尚未提交**（工作树 1051 × ` M`，§2.1-C），其上另含 `bare_except` 的单行修复（`fastapi_app/core/db_health.py:120`，§2.3）；
   - 由此产生的门禁漂移与处置见 **§2.3**：`function_length` 51→68（`gate_baseline.json` 一次性重新标定、`_comment` 登记「例外二」、final plan §6.28）、`bare_except` 5→6→**修复回 5**（基线未放宽）、`ruff` 保持 60；`docs/TRANSACTION_BOUNDARY_GUIDE.md` 行号锚点由 **t44** 重核；
   - 本台账 §1/§2 现挂的 `pytest` `3786 passed, 268 skipped` 与 `mypy` `144 source files` 是 **format 之前**的数字，**不构成最终验收口径**；
   - **最终验收数字 = captain 在 format 修复之后重跑的四件套**（后台作业 `pwsh-1733`，日志 `D:\erp_system\logs\_final_p1_acceptance2.log`）：`pytest = 1`（`16 failed, 3770 passed, 268 skipped in 404.55s`）、`quality_gate = 0` `[PASS]`、`mypy = 0`、`scan_secrets = 0` ⇒ **红灯**（详见 §2.4）。format 之前的数字（t26 round 3 / P1 批：`3786 passed, 268 skipped`、0 failed）作为对照口径保留；
   - **等待裁决**（用户/captain）：16 个失败全为测试对源码文本的断言被 format 打破（§2.4 独立复现 16/16），captain 对照实验显示任何全仓 format 都需**先修约 10 个守卫测试**。captain 已把两个方案报用户 ⇒ **本台账保持不定稿、t27 保持 `in_progress`**；裁决为「保留 format」时须先修守卫测试并重跑四件套，裁决为「回退 format」时由 captain 决定回退方式（**本任务不自行 `git checkout/restore`**）；
   - 定稿前，§1「结论」不对最终验收数字作承诺。
9. **t44（gatekeeper）锚点重核 → 口径更正**：format 已回退 ⇒ **不再需要为 format 重核**；但本任务在回退后的树上复算出 **3 行锚点因 P1 批次改行而陈旧**（§2.5 新发现 **R-3**：`cleanup/service.py:604→606`、`policy_service.py:544→549`、`records.py:791/803/822→804/816/835`）⇒ 交 **t44/gatekeeper** 在**无 format 的当前树**上同步这 3 行；**本台账引用该文档行号时以 t44 结果为准**。

---

## 9 变更声明（未修改任何实现文件）

- 本任务唯一写入：`docs/p1-execution-ledger-2026-10-01.md`（新建，未跟踪）。所有探针/命令输出落在仓库外 `%TEMP%\t27-integrator\`。
- 本任务未执行 `git add/commit/checkout/stash`（**§2.1-C 的 format 回退由 captain 执行**；本任务只做只读复核）；未重启任何服务；未执行 `icacls/sc/schtasks`；未改 `.env` 与任何口令密钥值；未改 `scripts/gate_baseline.json`（单写者 = gatekeeper）；未使用 `sandbox_permissions`；python 一律 `D:\erp_system\.venv\Scripts\python.exe`。
- §2.4 的复现只跑**窄范围定向命令**（7 个测试文件，串行），其中涉及数据库的 3 例经仓库既有 conftest 对 `erp_system_test` 建 schema；**未启动任何全量 pytest**（遵守 captain 的串行纪律），未改任何迁移或库结构。
- 与 `docs/p1-verification-2026-10-01.md` 的一致性：§4 逐项结论、§5.2 残留编号（F-03/F-04/F-05/F-07/R-pg）与该台账 §5/§6 逐条对应；本台账不新增也未撤销任何验证结论，仅补充集成视图与 2 条本批之外的新发现（R-1/R-2）。

## 附：本任务证据文件（仓库外）

- `%TEMP%\t27-integrator\qg.out`（`quality_gate.py` 提交前树完整输出，末行 `RC=0`）
- `%TEMP%\t27-integrator\qg_postformat.out`（`quality_gate.py --verbose` 在 format 后树的完整输出，`RC=0 [PASS]`，§2.3）
- `%TEMP%\t27-integrator\guard_repro_static.out`（5 个静态守卫文件的定向复跑：`13 failed, 27 passed in 5.97s`，rc=1，§2.4）
- `%TEMP%\t27-integrator\guard_repro_db.out`（`test_stock_negative_policy.py` + `test_purchase_plan_order_quota.py`：`3 failed, 62 passed in 6.09s`，rc=1，§2.4）
- `D:\erp_system\logs\_final_p1_acceptance2.log`（captain 对 **format 树**的最终验收四件套日志，UTF-16；本任务直读其 `PYTEST_EXIT=1 / QG_EXIT=0 / MYPY_EXIT=0 / SCAN_EXIT=0` 与末行统计）——**该树已按裁决 B 回退，本日志作为红灯对照留档**
- `%TEMP%\t27-integrator\qg_postrevert.out`（裁决 B 回退后的当前树上 `quality_gate.py --verbose` 的完整输出：`[PASS]` / `QG_EXIT=0`，§2.1-C 与 §2.5）
- `D:\erp_system\logs\_final_p1_acceptance3.log`（**captain 对回退后当前树的最终验收四件套，全绿**；1733631 B，START `2026-10-01T23:41:34` / END `23:49:25`；本任务只读原日志确认 `PYTEST_EXIT=0 / QG_EXIT=0 / MYPY_EXIT=0 / SCAN_EXIT=0` 与末行 `3786 passed, 268 skipped in 440.15s`；§2.6、§8 第 8 条）
- §2.1-A/C 与 §2.3 的独立复核全部为**只读命令**（`git log/show/--name-status/--shortstat/status --porcelain`、`Select-String fastapi_app/core/db_health.py`、`Get-Content scripts/gate_baseline.json -Encoding UTF8`），未落盘、未改任何文件。
