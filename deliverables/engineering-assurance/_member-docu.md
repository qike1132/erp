# 文档债盘点（只读）— 滨发 ERP

> 作者：多库（Docu）· 技术文档师 · 团队：engineering-full-audit
> 日期：2026-09-17 ｜ 方式：**只读**（未改动任何文档/源码/服务；未做任何 git 写操作）
> 范围：README / 部署文档 / Runbook / API 文档 / 迁移手册 的**完整性与"文档 vs 实际行为"漂移**
> 说明：第二步（Rex 复盘文档清晰度审查）待其交付 `postmortem-arq-backup-2026-09-17.md` 后另行进行，本文档**仅覆盖第一步**。
> 保密：本文档**不含任何密钥值**；凡涉及配置仅**列举键名**。

---

## 0. 一句话结论

**文档健康度：中偏低。** 核心事实（`.env` 单一权威、生产拓扑、备份/迁移/服务启停的真实约束）**大量存在于"临时脚本 / 提交信息 / 一次性审核报告"，而非任何面向运维的正式文档**；同时 3 处**高危害误导**（`.env.production.example` 引导维护 `.env.production`、`swap-dist.mjs` 错误归因、`README_DEPLOY.txt` 描述已废弃的 Flask 打包部署）会直接把人带沟里。

---

## 1. 文档资产清单

| 类别 | 位置 | 现状 |
|---|---|---|
| 后端主 README | `fastapi_app/README.md` | 较完整（技术栈/目录/启动/API 约定/迁移/部署），但部署与迁移两处漂移（见债 #7/#9） |
| 部署说明（旧） | `README_DEPLOY.txt`（仓库根） | **严重过期**（Flask+PyInstaller 时代） |
| 变更日志 | `CHANGELOG.md`（仓库根） | 有，按批次记录 |
| 迁移手册 | `migrations/README` | 仅 1 行 Alembic 模板残留；`migrations/alembic.ini` 存在 |
| 数据库备份工具说明 | `scripts/database/README.md` | 面向 MySQL 的旧说明（与现网 PG 不符，见债 #6） |
| API 契约（离线） | `tests/contract/endpoints.yaml` + `snapshots/`（22 条）+ `test_api_contract.py` | **存在但未被任何文档登记为契约事实来源**（见债 #10） |
| 架构 / ADR | `docs/adr/`、`docs/analysis/`、`docs/designs/` | 备份域 ADR/设计较扎实 |
| 备份/恢复 | `docs/backup-restore/`（设计方案/调研/审核 3 篇） | 只有**设计**，无**可执行 Runbook**（见债 #4） |
| 服务管理器（GUI） | `docs/ui-redesign/v8-*`、`一键操作按钮功能实现方案.md` | 设计/执行记录为主，非运维 Runbook |
| 事故/Bug/票据 | `docs/bugs/`（35+）、`docs/tickets/`（P0-01..10 + iterations） | 丰富，但无索引，检索困难 |
| 计划/工作流 | `docs/plans/`（20+） | 一次性执行记录 |
| 报告 | `docs/reports/`、`deliverables/`、`deliverables/audit-2026-09-17/`、`deliverables/gstack/` | 本轮多数"实际行为"证据来源在此，**非正式文档** |
| 配置（自文档） | `.env`、`.env.example`、`.env.production.example`、`.env.production`、`.env.development` | `.env` 内注释质量高；`.env.production*` 误导（债 #1） |
| 前端 | `frontend-vite/scripts/swap-dist.mjs`、`package.json#build:atomic` | 注释错误归因（债 #7） |
| 归档 | `.archive/`（legacy_backup / cleanup-20260815） | 历史堆积 |
| 仓库根临时物 | ~208 个 `_*` 脚本/输出（`_swap_dist_safe.py`、`_prod_deploy_preflight.py` 等） | **承载真实运维知识但被 gitignore、未入库** |

> 注：本仓无**仓库根 `README.md`**（仅 `README_DEPLOY.txt`）。新人入职第一入口实际是 `fastapi_app/README.md` + `CHANGELOG.md`。

---

## 2. 文档债清单

> 严重度：🔴 会致误操作/停机 ｜ 🟠 高（误导排障、阻断执行） ｜ 🟡 中（不一致/缺失细节） ｜ 🟢 低（冗余/整洁）
> 每条均附**文件路径 + 原文引用片段**（密钥值一律略去）。

| # | 类别 | 严重度 | 文档位置 | 问题 | 与实际行为的差异（附证据） | 建议动作 |
|---|---|---|---|---|---|---|
| 1 | 误导 | 🔴 | `.env.production.example`(:6)、`.env.production`、全仓 `.env*` 文档 | 模板头部引导：**"复制为 `.env.production` 并按需调整"**，暗示存在"生产配置由 `.env.production` 维护"的流程 | 实际**从未加载 `.env.production`**：`fastapi_app/core/config.py:10 load_dotenv(override=False)`（只读 `.env`）、`prod_runner.py:69 load_dotenv(PROJECT_ROOT/".env")`。权威文件是 **`.env`**。且 `.env.production.example` **缺生产启动必需键 `ALLOWED_HOSTS`**（生产强校验，缺失→`RuntimeError`），并缺 `UVICORN_WORKERS`、`ASYNC_DATABASE_REPLICA_URL`、`PG_SUPER_PASSWORD`、`FASTAPI_DEBUG`、`API_URL`、`CACHE_L1_BROADCAST_ENABLED` 及**全部 `BACKUP_*`（约 50 键）**；反之 `.env` 无 `SQL_ECHO/REDIS_URL/LIMITER_STORAGE_URI/STORAGE_TYPE/S3_*/NGINX_PROXY/SESSION_COOKIE_SECURE/PREFERRED_URL_SCHEME/FASTAPI_HOST`。旁证：`deliverables/audit-2026-09-17/审计报告-配置依赖部署.md:118` 曾判 `.env.production` 覆盖 `.env` 会致全站宕机；修复报告 M5 已 `git rm --cached`，但**文档未同步** | ① 在 `.env.production.example` 与 `.env.production` 头部加醒目横幅："**占位/历史模板，勿用于覆盖 `.env`；生产权威是 `.env`**"；② 补 `.env.production.example` 缺失的生产必需键（键名，占位值）；③ 新增"配置权威链"说明（`.env` → `load_dotenv(override=False)` → NSSM 环境变量优先级） |
| 2 | 误导 | 🟠 | `scripts/switch_env.py`(:17,:29-32,:111-120) | 脚本帮助文本仍把 **`production` 列为受支持命令**并给示例 `python switch_env.py production` | 实际 `:29-32` 对 production **直接拒绝执行**（打印"生产环境切换已禁用"）。另：`project_root = Path(__file__).parent`（:17）=`scripts/`，故 `env_dev = scripts/.env.development` **不存在** → 连 `development` 分支也恒失败（脚本整体已失效） | 同步帮助文本与实现（移除 production 示例，或标注"已禁用"）；修正 `project_root`（应为 `parent.parent`）；或在脚本头注明"已废弃，改走 server_manager GUI" |
| 3 | 缺失 | 🔴 | `docs/`（无服务启停 Runbook） | **无任何文档说明"非提权下重启 `erp-prod` 无可用路径"**：`OpenServiceW` err=5、杀受监督子进程 err=5、`Start-Process -Verb RunAs` 被安全策略永久拦截；仅能交接管理员 PowerShell / 提权 GUI | 反向误导遍布：`docs/plans/2026-08-15-project-cleanup-workflow.md:73,78` 直接给 `Start-Service erp-prod`；`docs/plans/2026-08-16-*:37,55` 给 `nssm restart erp-prod`——**均未标注"需管理员"**。旁证：`deliverables/audit-2026-09-17/上线前问题修复报告-20260917.md:102`（"恢复生产托管只能走提权 GUI，CLI 派生进程会被回收"）、`:59`（restart_prod.ps1 加 NSSM 护栏）；`docs/bugs/BUG-SERVER-MANAGER-v5.33-MODE-SWITCH-20260908.md:44-46`（非管理员则服务控制全被拒） | 新建 **Runbook：服务启停**（何时用/前置权限/提权方式/验证/回滚/升级路径）；在所有提及服务的既有文档标注提权前提并链接该 Runbook |
| 4 | 缺失 | 🟠 | `docs/backup-restore/`（仅设计/调研/审核） | **无可执行备份/恢复 Runbook**（含 `pg_restore -Fc` 恢复演练步骤）；未反映"生产自动全量备份曾长期缺失、2026-09-17 才补 `每日全量备份`（`.env:102 BACKUP_FULL_CRON=0 2 * * *`）"的现状 | 配置已在位（`.env:102` `BACKUP_FULL_CRON=0 2 * * *`、`:103` 增量 `0 */1 * * *`），但 `backups/recovery_logs/` 曾为空（`审计报告-配置依赖部署.md:156`：无恢复演练记录）；设计文档只写方向（`docs/backup-restore/备份与恢复模块设计方案.md:105` 提到 `pg_restore -Fc -c`），**无逐步演练 SOP**；实操脚本 `scripts/restore_drill.py`（恢复到 `erp_system_drill`）**无任何文档引用** | 新建 Runbook：备份/恢复（全量+增量备份、`scripts/restore_drill.py` 演练、`pg_restore -Fc` 恢复、验证 `alembic current==head`、回滚、演练记录留存路径）；补记 2026-09-17 全量备份启用 |
| 5 | 过期 | 🟠 | `README_DEPLOY.txt`（仓库根，全篇） | 描述**已废弃的 Flask + PyInstaller 桌面部署**：`:6`"双击运行 `ERP_System.exe`"、`:7` 访问 `http://127.0.0.1:5003`、`:8`"admin / admin123"、`:13`"无需安装 Python"、`:31` `templates/`、`:47`"详细文档请查看 `EXE_PACKAGING_GUIDE.md`" | 现网为 **FastAPI:5002 + nginx:3000 + NSSM(erp-prod/erp-arq/redis)**，非 exe 单体、非 5003；`templates/` 与 `EXE_PACKAGING_GUIDE.md` **实测不存在**（`deliverables/audit-2026-09-17/审计报告-配置依赖部署.md:94` 亦证 `templates/` 不存在） | 删除或整体重写为"当前部署拓扑 + 指向 server_manager GUI/`fastapi_app/README.md`"；至少加"⚠️ 历史文档，已过期"横幅 |
| 6 | 过期/误导 | 🟠 | `scripts/database/README.md`(全篇) | 说明面向 **MySQL**：`:16`"支持 MySQL 数据库"、`:107`"MySQL备份"、`:109` `erp_system_backup_*.sql`、`:96-103` 目录 `backups/daily|weekly|monthly` | 实际生产 DB 是 **PostgreSQL 18.3**（`deliverables/audit-2026-09-17/REPORT-qa-frontend-runtime-2026-09-17.md:171`），备份产物在 `backups/server/erp_backup_*.zip`，走 `pg_dump`/`psql`（`fastapi_app/services/backup/dump.py:1,52,157`）。且 `:175` 链接 `../../docs/DATABASE_BACKUP_RECOVERY_GUIDE.md` **不存在**（`docs/` 无此文件）。该 README 描述的 `db_manager.py`（`scripts/database/db_manager.py`）与**生产真正在用的备份服务**（`fastapi_app/services/backup/`）**是两条不同路径**，易误以为前者即生产备份 | 重写为 PostgreSQL 版，或标注"**仅旧版手动工具说明，生产备份见 `fastapi_app/services/backup` + 备份中心**"；删除失效链接 |
| 7 | 误导 | 🟠 | `frontend-vite/scripts/swap-dist.mjs`(:5-6,:30,:43) | ① `:30` 把原子切换失败归因为"**如防病毒锁定 dist-new**"；② `:5-6` 宣称"窗口极短且**可回退**" | ① **真实根因非防病毒**：`vite dev` 的 chokidar watcher 对**新建的 `dist-new`** 持目录句柄 → `rename(dist-new → dist)` **必然 EPERM**（证据：`_swap_dist_safe.py:4-6`"绕开 vite dev server 对 dist-new 的目录句柄锁…这解释了 swap-dist.mjs 注释里被归因于「防病毒」的现象"；`_mem_tail.txt:21-23`；`docs/tickets/P0-09-editable-list-index-key.md:215`、`docs/tickets/README.md:107` 亦记该事实）。② 头注释称"可回退"，但 `:43 await rm(distOld, {recursive:true, force:true})` **成功后即删除唯一回滚副本** `dist-old`（证据：`_prod_deploy_preflight.py:4`"该脚本第 43 行会 rm -rf 掉旧 dist，不留回滚副本"）。**关键**：以上正解仅存于根目录被 gitignore 的 `_*` 临时脚本，**无正式文档** | 修正 `swap-dist.mjs` 注释（根因=vite watcher 持句柄；明确"成功后无回滚副本，需先外部备份 dist"）；将"发布前停 dev server / 外部备份"写入部署 Runbook 并入库（勿留在 `_*`） |
| 8 | 误导 | 🟡 | `fastapi_app/README.md`(:139,:141) | 部署段指引 `.\deploy-windows.ps1 -Env production`，并称"环境变量见根目录 `.env.example`" | `deploy-windows.ps1` 已于 2026-09-17 **删除**（`deliverables/audit-2026-09-17/上线前问题修复报告-20260917.md:59,115` M9/P2：删除"必然 exit 1 的过时脚本"）；生产权威配置是 `.env` 而非 `.env.example` | 更新部署段：删去已删除脚本引用，指向 server_manager GUI / NSSM；把 `.env.example` 改为 `.env`（注明权威） |
| 9 | 不一致 | 🟠 | `fastapi_app/README.md:133-134`、`deliverables/观测能力建设报告.md:167-168`、`deliverables/未修复项清单.md:117`、`docs/plans/2026-09-10-bom-role-field-workflow.md:80` | 迁移命令**三种版本并存**：① `alembic -c migrations/alembic.ini upgrade head`（仓库根）；② `cd migrations && PYTHONPATH=.. alembic upgrade head`；③ `python -m alembic -c migrations/alembic.ini current` | `alembic.ini` 在 `migrations/`（非仓库根），`script_location = .`（`migrations/alembic.ini:4`）→ 需在 `migrations/` 目录运行；`env.py:18,32` 导入 `fastapi_app.*` → 需 `PYTHONPATH` 含仓库根。故**唯一自洽写法为 ②**（`cd migrations && PYTHONPATH=.. alembic ...`），与 deliverables 一致；`fastapi_app/README.md:133` 的 ① 与仓根上下文易踩脚本目录解析。**另：PG 工具链在 `D:\PostgreSQL\bin`（不在 PATH）**，全仓文档**零处**说明——仅代码级兜底 `fastapi_app/services/backup/dump.py:22-27`"PG 客户端工具自动发现候选目录（F6：pg_dump/psql 常不在服务进程 PATH 上）"列出 `D:\PostgreSQL\bin` | 统一迁移命令为 ② 并写入 `fastapi_app/README.md` + 新建"迁移 Runbook"；显式记录 `alembic.ini` 位置与 PG 工具链路径/PATH 前提 |
| 10 | 缺失 | 🟡 | `fastapi_app/README.md:75-82`、`tests/contract/endpoints.yaml` | 生产已关 `/api/docs`、`/api/redoc`（README 已说明防暴露），但**无离线 API 契约文档**作替代；`endpoints.yaml` 未被登记为"契约事实来源" | `tests/contract/endpoints.yaml` 实存（**22 条：21 只读 GET + 1 计算型 POST `purchase-center/calculate`**）+ `snapshots/*.json` + `test_api_contract.py`，可作离线事实来源，但 README/docs 均**未链接**。**写操作端点（POST/PUT/DELETE）无任何契约/快照** | 在 README 增设"API 契约"小节，把 `endpoints.yaml`+`snapshots` 登记为离线契约来源与用法（`scripts/contract_snapshot.py --record/--check`）；为高频写操作端点补契约快照 |
| 11 | 冗余 | 🟢 | `migrations/README`、`migrations/alembic.ini:1` | `README` 全文仅 `"Single-database configuration for Flask."`（Flask 模板残留，且**本项目非 Flask**）；ini 注释同为通用样板 | 本项目为 FastAPI + SQLAlchemy async + alembic；README 内容错误且无信息量 | 重写 `migrations/README`（用途/命令②/多 head 提示——`deliverables/gstack/pre-launch-check-fullstack-2026-09-05.md:53` 曾提"4 个 `down_revision=None` 基线迁移，多 head 风险"） |
| 12 | 冗余/过期 | 🟢 | `.env.development`、`.env.bak-20260911`、`.env.production`、`.env.production.example`、`.env.example`；`.env:42-43` | 多份 `.env*` 并存易混；`.env` 保留**代码从不读取**的 `FLASK_ENV=development`/`FLASK_DEBUG`（本系统无 Flask）死键 | `deliverables/audit-2026-09-17/审计报告-配置依赖部署.md:59` 判 `FLASK_ENV/FLASK_DEBUG` 为死键且易误导；`:60` 列 `.env.example` 有而 `.env` 无的键（`STORAGE_TYPE/S3_*/PGBOUNCER_*/PROD_LOG_ROTATE_MB/SLOW_QUERY_*/REDIS_URL`，非缺陷） | 归档 `*.bak`；清理 `.env` 内 Flask 死键；在 `.env.example` 标"示例非权威" |
| 13 | 冗余 | 🟢 | `docs/`（bugs 35+/designs 22/plans 22/ui-redesign 30+）、`deliverables/`、`.archive/`、仓库根 ~208 个 `_*` | 历史报告大量堆积，**无索引/无生命周期标记**，现状与历史混杂；真实运维知识（swap-safe、deploy preflight）却在被 gitignore 的 `_*` 临时物中 | `deliverables/audit-2026-09-17/审计报告-配置依赖部署.md:139,142` 记根目录 `_*` 及 `deliverables/gstack/_*` 未忽略、`git add -A` 会带入 | 建 `docs/README.md` 索引 + 每篇加状态页眉（现行/历史/已废弃）；把 `_swap_dist_safe.py`、`_prod_deploy_preflight.py` 等运维脚本**规范化入库** |

---

## 3. 修复优先级（建议执行顺序）

**P0（先做，直接防停机/防误操作）**
1. **债 #1** — `.env.production.example`/`.env.production` 加"勿覆盖 `.env`"横幅 + 补 `ALLOWED_HOSTS` 等生产必需键；新增"配置权威链"说明。
2. **债 #3** — 新建《Runbook：服务启停》，明确"非提权无法重启 `erp-prod`"与提权路径；修正既有文档中无提权前提的 `nssm restart`/`Start-Service` 指引。

**P1（高收益）**
3. **债 #7** — 修正 `swap-dist.mjs` 错误归因与"可回退"表述；把"发布前停 dev server + 外部备份 dist"入库。
4. **债 #4** — 新建《Runbook：备份/恢复》（含 `pg_restore -Fc` 演练、`scripts/restore_drill.py`）。
5. **债 #5 / #6** — 处置/重写 `README_DEPLOY.txt`、`scripts/database/README.md`（Flask/MySQL 过期内容）。
6. **债 #2 / #8 / #9** — 修 `switch_env.py` 帮助文本与路径；更新 `fastapi_app/README.md` 部署/迁移段并统一迁移命令为 `cd migrations && PYTHONPATH=.. alembic upgrade head`。

**P2（整洁与可持续）**
7. **债 #10** — 登记离线 API 契约来源；补写操作端点契约。
8. **债 #11 / #12 / #13** — 重写 `migrations/README`；清理 `.env*` 冗余；建 `docs/README.md` 索引与状态页眉；规范化入库运维 `_*` 脚本。

---

## 4. 附：本次核对覆盖的关键事实锚点（供交叉引用）

- 配置权威：`fastapi_app/core/config.py:10`、`fastapi_app/core/prod_runner.py:69`（`.env` 唯一来源，`override=False`）。
- 服务拓扑：`erp-prod`/`erp-arq`/`erp-redis*`（NSSM），nginx:3000 → `frontend-vite/dist`，FastAPI:5002（8 worker）。
- 生产文档端点：`/api/docs`、`/api/redoc` 已关（`fastapi_app/README.md:77-82`）。
- 迁移：`migrations/alembic.ini`（`script_location=.`）+ `PYTHONPATH=..`；PG 工具 `D:\PostgreSQL\bin`（`dump.py:22-27`）。
- 备份 cron：`.env:102` `BACKUP_FULL_CRON=0 2 * * *`；增量 `:103` `0 */1 * * *`；产物 `backups/server/erp_backup_*.zip`。
- 原子发布：`package.json:13 build:atomic` → `swap-dist.mjs`；dev 运行期 rename 必 EPERM（vite watcher 持 `dist-new` 句柄）。

---

## 5. 第二步：复盘文档清晰度审查 — `postmortem-arq-backup-2026-09-17.md`

> 审查对象：`deliverables/engineering-assurance/postmortem-arq-backup-2026-09-17.md`（Rex 出品，14,489B，标"最终/只读调查"）
> 审查视角：① 面向**不熟悉本项目**读者的独立性；② 术语密度与信息分层；③ 事实与证据锚点自洽。
> **结论：结构优秀、事实克制、可直接作为对外稿的基础；需 4 类小修**（残留内部语境、术语分层、1 处无锚点强主张、编号/口径）。均为精修项（P2 以内），不做重构；P0 三条改完即可定稿外发。
> 本次为**只读审查**，未改动复盘文件本身。

### 5.1 总体判断（结论先行）

**优点（务必保留）**
- 「一页摘要 → 背景 → 事实 → 发现 → 行动项 → 术语表」递进合理，**重点前置**（先给"服务没坏，但发现故障的能力有洞"）。
- **诚实度与可核对性高**：明确区分「已发生 / 潜在缺陷」、「结论 / **[未确认]**」，并给可核对来源（文件:行、日志时刻、进程创建时间）。
- 「背景」+「术语表」有效降低前置门槛，是本文最值得保留的设计。

**需修**：见 5.2–5.6。

### 5.2 独立性：残留内部语境（P0/P1）

| # | 位置 | 现状原文 | 问题 | 建议改写（可直接替换） |
|---|---|---|---|---|
| a | line 8 | 本文件面向**不熟悉本项目团队分工**的读者 | "团队分工"本身是内部概念 | 面向**不熟悉本项目背景**的读者 |
| b | line 14 | 当天夜里 22:09–22:16，**团队在做例行工程审计时**，一条较早的观测记录… | 暴露"内部自审"语境；外部读者不知情 | 当天夜里 22:09–22:16，**一次例行生产环境复核中**，一条较早的观测记录… |
| c | line 127 小标题 | 3.2 `UVICORN_WORKERS=8`「改了没用」的真相（**对一条初始判断的纠正**） | 外部读者从未见过那条"初始判断"，指向落空 | ……的真相（**常见误解澄清**） |
| d | line 175 | …导致**第二套错误的判活逻辑被独立发明** | "被独立发明"带内部叙事口吻 | …导致出现**第二套并不可靠的判活逻辑**（写进了诊断脚本） |
| e | line 6 | 报告人：Rex · **SRE** 工程师 | `SRE` 未入术语表 | 术语表补 `SRE` 条，或写作"Rex（SRE／站点可靠性工程师）" |

> 说明：你在消息里点名的 line 127「对一条初始判断的纠正」——**同意改**，中性的「常见误解澄清」对外部读者更自然。另 line 14 的"工程审计"、line 8 的"团队分工"是同类问题，建议一并处理。

### 5.3 术语密度与信息分层（P1）

**判断：不必整体降档。** 理由两点——(1) 读者是"不熟悉本项目"的人，未必"非技术"；(2) 那些标识符（`runtime_mode_probe.py`、JSON 复现输出、`check_worker_health()`）**本身就是证据**，删掉会削弱复盘的"可核对性"，与本文最大优点相悖。

**问题不在"术语太多"，而在"术语与证据混在叙事句里，非技术读者无法整段跳过"。** 建议做**两层呈现**（保留证据 + 可跳过）：
1. **第 2 节正文**：实现标识符**首次出现**时"先中文、后括号"，例如 `check_worker_health()` → "项目里已有的权威判活函数（代码名 `check_worker_health()`，读 ARQ 哨兵键）"；`cmdline` → "读进程的命令行信息"。
2. **下沉附录 B「技术根因与复现原始输出」**：把现 line 91–96 的「连续追问」根因链、现 line 82–89 的 JSON 复现块移入附录；正文第 2 节只留一句人话摘要 + "（技术细节见附录 B）"。这样技术读者仍拿到全证据，非技术读者可一路读完叙事。
3. **补脚注/词条**：`TTL=9`（line 46）、`mtime`（line 111）、`入队`（line 149）。

> 澄清一处：你消息提到正文出现 `PSUTIL`——**当前交付版全文并无 `PSUTIL`**（仅 `cmdline` 1 处，见 5.5）。若你记忆中的版本有，说明已被清理，**不影响定稿**。

### 5.4 编号与口径一致性（P2）

- **数字口径并存**：header「**3 项潜在 SEV-3**」↔ 第 2 节「三个能力缺陷」↔ 时间线「识别…**4 类问题**」↔ 第 3 节「另外两处」。建议 header 统一为「**3 项能力缺陷（潜在 SEV-3）+ 2 项误导项（未定级）**」，并让 3.1/3.2 明确标注"未定级（非 SEV-3）"，避免读者误以为 §3 也是 SEV-3。
- **编号风格**：摘要/背景无编号，正文用「一、二…」，风格不统一（可选，不强制）。

### 5.5 需核实 / 补锚点（P1）

1. **line 179「生产机被当开发机频繁切换（当天 ≥14 次）」缺证据锚点。** 本文自称"所有结论均标注证据来源"，且时间线仅记录 1 次切换。请补计数来源（哪个 GUI 日志/查询得出 ≥14），否则标 **[未确认]**。复核实况：我未在交付目录中找到该计数的证据文件。
2. `cmdline`（line 92）本身可留，但按 5.3 分层（正文说人话）。

### 5.6 定稿改动清单（按优先级，可直接照做）

**P0（对外可读性门槛 — 改完即可外发）**
1. line 8「团队分工」→「项目背景」
2. line 14「团队在做例行工程审计时」→「一次例行生产环境复核中」
3. line 127 小标题「（对一条初始判断的纠正）」→「（常见误解澄清）」

**P1（建议同批处理以完全达标）**
4. line 175「被独立发明」→ 中性表述
5. line 179 补「≥14 次」证据锚点，或标 [未确认]
6. 第 2 节：实现细节下沉「附录 B」，正文首现处"先中文后括号"
7. header 数字口径统一（3 能力缺陷 + 2 误导项）

**P2（整洁）**
8. 术语表补 `SRE`/`TTL`/`mtime`/`入队`；`cmdline` 分层

### 5.7 结论

**满足"面向非本团队读者独立可读"的目标，且证据链与诚实度出色，** 值得作为本团队复盘文档的范式。上述为**精修项而非重构项**：P0 三条（内部语境 2 处 + 小标题 1 处）改完即可定稿；P1 建议同批处理。Rex 可自行改，或授权我直接改后回传。

---

## 6. 复审（Rex 采纳意见后版本）— 快速复扫

> 触发：sre-engineer 回传「审查意见全部采纳、已自行改完」。本轮针对其点名的 **§2／附录 B 两层拆分**做快速复扫，并顺带复核 P0 独立性与 line 179 计数。
> 方式：**只读**。已按关键字 grep 原始日志 `logs/server_manager_20260917.log` 做独立复核。
> **复审结论：通过，达定稿标准。** 仅 1 条可选精度建议（P2），不改也不影响外发。

### 6.1 逐项核对结果

| 审查项 | 结论 | 核对方式 |
|---|---|---|
| **§2 正文两层拆分** | ✅ | 现为「现象→复现(指针)→人话版根因→后果」四段，非技术读者可连读；`cmdline` 已改「读进程的命令行信息」；`check_worker_health()` 首现采用「先中文、后括号代码名」 |
| **附录 B 下沉** | ✅ | JSON 复现块 + 「连续追问」根因链已移入附录 B（line 210–232），开头有"可跳过"提示；正文 line 81/83 各留一处指针，无孤立引用 |
| **口径统一（原 5.4）** | ✅ | header「3 项能力缺陷（潜在 SEV-3）＋2 项误导项（未定级）」↔ §二「三个能力缺陷」↔ §三「（未定级，非 SEV-3）」↔ 时间线「…等能力缺陷」，四处已一致，无「4 类问题」残留 |
| **P0 独立性（原 5.2）** | ✅ | line 8/14/114/115 全部落地，无「团队分工／工程审计／初始判断」残留 |
| **line 179 计数（原 5.5-1）** | ✅（计数准确） | 证据文件 `_rex_mode_switches.txt` 存在、带原文件行号；我方独立 grep 原始日志**逐条命中与摘录一致**：8 次「启动开发模式（前后端）」＋9 次「启动生产模式」＝17 |
| **术语表（原 5.6-8）** | ✅ | 补 SRE／TTL／mtime／入队／潜在 SEV-x；报告人改「Rex（SRE／站点可靠性工程师）」 |
| **PSUTIL 澄清** | ✅ | 复扫当前交付版**全文无 PSUTIL**，仅 `cmdline` 一处且已分层 |

### 6.2 唯一可选精度建议（P2，非阻断）

复盘正文 line 166 现写「…**8 次进入开发模式**——而按本项目设计，进入开发模式会先停掉生产服务，故**这 8 次都打开了生产中断窗口**」。

但同一份日志里 **「已自动停止生产模式」只有 4 条**（原文件行 79 / 504 / 574 / 5664），另有 4 次 dev 启动（08:35:54、16:14:00、17:12:01、18:29:47）**无对应停止记录**——应为「已在 dev 态下的重启」或「开机首启」。故「8 次都打开了中断窗口」**比锚点支撑的更强**。建议对齐口径（二选一）：

- 保守：改为「其中 8 次进入开发模式，**日志明确记录了其中 4 次「已自动停止生产模式」**」；或
- 归因设计：改为「按设计，进入开发模式会先停生产（当日日志含 4 次明确的停止记录）」。

> 备注：其证据文件 `_rex_mode_switches.txt` 结尾的「本计数为『动作』计数，非『对外服务中断』计数」其实已经很克制——只要把正文 line 166 的口径对齐到这句即可。

### 6.3 极小 nit（可不改）

§2 标题「有正确契约却没有接线」与 line 83 末句「正确的判活契约存在，却没有接到该用的地方」语义重复一次，属强调写法，可保留。

---

_（本文件现已产出三步：第一步「文档债盘点」= 第 0–4 节；第二步「复盘文档清晰度审查」= 第 5 节；第三步「采纳后复审」= 第 6 节。全流程只读，未改动任何复盘/文档/源码/服务。）_
