# binfa-ERP 第二轮优化实施方案（基于 2026-10-01 第二轮全面审计）

> **本文件是什么**：把第二轮审计的结论转成**可执行、可验收、可排期**的整改方案。
> **本文件不是什么**：不是审计报告（那是 `docs/audit-round2/00-synthesis.md` 与 01–06 号），也不是代码补丁——只给"改什么、改哪里、怎么算改完、多久、谁依赖谁、放哪批"。

## 元信息与引用纪律

- **方案依据**：`docs/audit-round2/00-synthesis.md`（决策视图）+ `01`～`06` 六份成员报告（证据源）+ `docs/audit-round2/README.md`（归档索引）
- **编号对接**：复用既有 `docs/optimization-plan-2026-10-01.md` 的 OPT-01..22；**新项一律 `OPT-R2-xx`**，不复用、不占用、不改写既有编号
- **取证基线**：六份报告取证于 `aac4c43f`（2026-10-01 14:52:03）；归档与本方案写作基线 **HEAD = `546401ec`**（15:10:43）。中间多 1 个提交：`chore(types): mypy 覆盖 106→110（OPT-13 第一批），顺带删 staging_utils 死代码`（实测该提交改动 8 个文件：base_search_service.py、fifo_allocation.py、order_batch_create.py、order_deduction_service.py、order_utils.py、plan_utils.py、删除 `fastapi_app/services/staging_utils.py`、`mypy.ini`）
- **行号漂移**：凡引用 `staging_utils.py`、`mypy.ini` 以及上述 6 个 service 文件的**行号**，引用前必须重新核对；其余行号亦可能受该提交影响，核验方法见 §7
- **口径差异不合成**（同时成立，不是错误）：路由数 **373**（01 号端点数）/ **385**（02 号口径）/ **382**（05 号非测试路由）；测试文件 **148 & 163**（04 号数全部 `.py`）vs **110 & 161**（06 号只数 `test_*.py`）
- **只读声明**：本方案只读审计素材，未改代码/配置/数据库，未重启服务，未跑 pytest/mypy/ruff/前端构建
- **不做性能承诺**：本方案不承诺任何未经测量验证的性能数字；凡性能类表述均标注「结构性推断」或「未验证」

## 目录

- [0. 既有 OPT 状态修正表（编号对接）](#0-既有-opt-状态修正表编号对接)
- [1. 批一 · 上线前必修（P0）](#1-批一--上线前必修p0)
- [2. 批二 · 2–6 周（P1）](#2-批二--26-周p1)
- [3. 批三 · 6–12 周（P2）](#3-批三--612-周p2)
- [4. 门禁与度量改造](#4-门禁与度量改造)
- [5. 不做清单（8 项）](#5-不做清单8-项)
- [6. 方案自身的数据缺口](#6-方案自身的数据缺口)
- [7. 工时与批次自洽性校验](#7-工时与批次自洽性校验)
- [8. 执行纪律](#8-执行纪律)

---

## 0. 既有 OPT 状态修正表（编号对接）

> **判据说明（必须随表阅读）**：`docs/optimization-plan-audit-2026-10-01.md` 只判"方案项**描述是否属实 / 方向是否可行**"，**从不判"是否已执行"**。两个维度正交，不可互相替代。下表"执行状态"一列以 t4 原始运行的结论为权威事实，与 `04-engineering-quality.md` 残片无关（04 号缺 OPT-01..22 状态表，**禁止**作为 OPT 状态证据源、**禁止**引用其行号）。

| 项号 | 标题 | 执行状态（权威事实） | 本轮修正 | 剩余动作 → 去向 |
|---|---|---|---|---|
| OPT-01 | 提交 22 个 WIP 文件 | **已完成** | — | 无 |
| OPT-02 | 修复 6 个 pytest 失败 | **进行中**：6 条中已修 5 条 | 原方案记"6 败"；现剩 1 条 | 修最后 1 条 → 本方案 §1 **OPT-02（续）** |
| OPT-03 | ruff 自动修 + 基线收紧 | **已完成** | — | 无（但 **CI 的 ruff 范围不含 server_manager/scripts**，见 §4.1） |
| OPT-04 | 删除死代码 | **已完成** | — | 无 |
| OPT-05 | 修复 git-bash `_lc` 劫持 | **不可核验**（工件在仓库外） | — | 需要时人工复现 → **本方案 §3.9.3 OPT-05（续）**（批三，1.0 人日） |
| OPT-06 | 根目录审计草稿归档 | **已完成** | — | 无 |
| OPT-07 | web_vital 真实性能画像 | **已完成** | — | 无 |
| OPT-08 | 生产 Python venv 隔离 | **进行中**：只建了 `.venv`，**未改 NSSM**，`erp-prod`/`erp-arq` 仍指向全局 `Python313\python.EXE` | — | 改 NSSM 启动命令 + 低峰窗口重启 → **本方案 OPT-08（续）** |
| OPT-09 | 前端写操作统一 useApiMutation | **进行中**：试点 + 推广①② | 旧度量"仅 4 处"**已过时**：实测 **30 处命中、跨 8 个文件**（定义 `frontend-vite/src/composables/useApiMutation.ts:23`） | 继续逐模块推广 → **本方案 OPT-09（续）** |
| OPT-10 | customer/supplier 迁 UiDataTable | **已完成** | — | 无（`useEnhancedList` 去向问题独立成项，见 §2 **OPT-R2-19**） |
| OPT-11 | API 层 5 处事务违规下沉 service | **已完成** | 本轮再证：`fastapi_app/api/v1/endpoints/order.py:24/:334-335/:342/:374` | 无 |
| OPT-12 | core/config 增加 field_validator | **已完成** | — | 无（配置漂移仍有缺口，见 §1 **OPT-R2-11**） |
| OPT-13 | mypy 覆盖 106 → 全量 | **进行中**：第 1 批，随 `546401ec` 把覆盖 106→110 | **已裁定 110**：正则 `^\s+[A-Za-z_][\w/]*\.py,?\s*$` 漏掉 `mypy.ini:33` 的行内首条 `files = fastapi_app/core/security.py,`，`:34-142` 才是 109 条（109 + 1 = 110；旁证 `aac4c43f:mypy.ini` = 106，`546401ec` 对该文件 +5 −1）——见 §7.5 | 第 2 批（先并"零错未纳入"模块）→ **本方案 §2 OPT-R2-23** |
| OPT-14 | 迁移图 4 根显式收敛 | **已完成** | 与 `docs/adr/2026-10-01-migration-roots-are-cosmetic.md`（不改迁移链）一致 | 无；新增命名规范另立 → §2 **OPT-R2-25** |
| OPT-15 | 前端 bundle 拆分 | **关闭或降级**：前提不成立（构建实证撤销"echarts 在首屏"结论） | — | 无；echarts 动态 import 已存在（`frontend-vite/src/utils/echartsPreload.ts`） |
| OPT-16 | 部署 PG 只读副本 | **关闭或降级**：降为调查项 **16a** | — | 无（只读副本依赖已写未用，见 §2 **OPT-R2-15** 与 §3 **OPT-R2-32**） |
| OPT-17 | 内网 TLS | **未做** | — | → **本方案 OPT-17（续）**，§3 |
| OPT-18 | nginx limit_req | **未做** | — | → **本方案 OPT-18（续）**，§2（依赖 OPT-17） |
| OPT-19 | uploads 免鉴权直出改造 | **未做** | — | → **本方案 OPT-19（续）**，§3 |
| OPT-20 | 进程内状态 Redis 化 | **关闭或降级**：大半不成立 | 佐证：`fastapi_app/api/ws.py:33-41`（票据常量与内存字典）、`:61-76`（同时写 Redis 且 miss 回退） | 无；残余项并入 §3 **OPT-R2-32** |
| OPT-21 | fastapi 0.137.1 → 0.142.2 | **未做** | 佐证：`requirements/base.txt:7` `fastapi==0.137.1` | → **本方案 OPT-21（续）**，§2（依赖 OPT-08） |
| OPT-22 | 备份"解密+校验"演练季度化 | **未做** | 本轮再证：`scripts/restore_drill.py:35-36` 的 glob 选不到 `.enc` 产物 | → **本方案 OPT-22（续）**，§1（**P0**：恢复能力从未端到端验证过） |

**汇总**：已完成 **9** ｜ 进行中 **4**（OPT-02/08/09/13）｜ 关闭或降级 **3**（OPT-15/16/20）｜ 未做 **5**（OPT-17/18/19/21/22）｜ 不可核验 **1**（OPT-05）。
**沿用既有编号的续做项**（批一至批三的续做集合）：OPT-02、OPT-05、OPT-08、OPT-09、OPT-17、OPT-18、OPT-19、OPT-21、OPT-22（**9 项**）。**OPT-13 不在其列**——它的后续工作已在 §2.10 以新号 **OPT-R2-23** 登记（见附录）。
**新增项**：号段 OPT-R2-01 ～ OPT-R2-37，其中 **OPT-R2-09 保留空缺**（说明见附录），**在用 36 项**（含 §0.1 台账 OPT-R2-36 与 §4.1 的 OPT-R2-37；条目见 §1–§3、§4.1 与附录）。

### 0.1 批一首项 · OPT 执行状态台账（OPT-R2-36）

**这是本方案的第一交付物**，因为本轮审计暴露的最大管理洞不是某个技术缺陷，而是**"22 项优化方案在仓库里没有任何地方记录执行状态"**——正因如此，`docs/audit-round2/04-engineering-quality.md` 缺状态表后，本轮只能靠队长给定的 t4 原始运行结论才把状态还原出来。

- **目标**：建立并长期维护一份逐项执行状态台账，使"方案项是否已执行"有唯一可查落点。
- **落点**：新建 `docs/optimization-status-2026-10-01.md`（本轮先落 §0 的修正表 + 新增项清单）。
- **表头（必须含）**：`项号 | 标题 | 状态 | 证据 文件:行 | 核验日期 | 责任人 | 下一动作`
- **状态取值（五选一，与 §0 一致）**：完成 / 进行中 / 降级 / 未做 / 不可核验
- **维护方式**：随每次发布提交更新（一个提交只改台账 + 变更说明）；纳入 `.githooks/pre-commit` 的非阻断提示，并作为 §4 门禁改造的可选检查项（"新增/变更方案项时台账必须同步"目前只能人工确认，**未验证**能否机器判定）。
- **验收**：台账与仓库实际一致——抽查 5 项（含 1 项"进行中"、1 项"未做"）逐条对得上；`docs/optimization-plan-2026-10-01.md` 与 `docs/audit-round2/00-synthesis.md §8.4` 与之三方无冲突。
- **风险与回滚**：纯新增文档，风险近零；如台账口径需调整，直接改文件即可回滚。
- **预估工时**：0.5 人日（含历史 22 项 + 本轮 36 项的首次录入）。**依赖**：无。**批次**：批一（首项）。
> **落点裁定**：本台账落点 `docs/optimization-status-2026-10-01.md` 为**队长裁定**；`docs/audit-round2/00-synthesis.md §5` 若出现同项引用，**以本处落点为准**（findings 26）。

---

## 1. 批一 · 上线前必修（P0）

> **口径**：批一 = "上线前必须做完"。排序原则来自 `00-synthesis.md §5`：① **先堵静默失败**（不报错的问题优先于报错的问题）；② 再做"低成本、零风险、立刻可验证"的收尾；③ 最后做需要设计决策的项。全部为小改 + 可回滚，单项工时 ≤ 1.5 人日。

> **本节映射**：P0 四类 = **A 静默数据正确性 · 类**（1.1）／**B 备份与恢复 · 类**（1.3）／**C 安全面 · 类**（1.6）／**D 暴露面 · 类**（1.9）。四个「类」小节给出该类的问题全貌与证据来源；其后紧跟**可立即执行的具体项**（各自独立编号、独立验收、独立工时），不重复计工时。批一总计 **15 个可执行项 + 1 个台账项（§0.1 OPT-R2-36）**，合计 **12.0 人日**（含台账 0.5 与 OPT-R2-03 的 0.5，见 §7 自洽校验）。类级小节本身不再单列工时，其下子项工时即为该类的实现成本。

### 1.1 【A 类 · 静默数据正确性】问题全貌与证据来源

**为什么是 P0**：这一类的共同特征是「**失败了也不报错**」——请求返回 200，数据却不对。它比任何 5xx 都危险，因为不会被任何人发现，直到几个月后对账。

| 子问题 | 证据 文件:行 | 本轮实测 | 归属项 |
|---|---|---|---|
| 事务提交失败只写日志（响应已发出但未落库） | `fastapi_app/core/database.py:229/:232` | ✔ 已确认 :232 日志文案含"静默丢失风险" | **OPT-R2-01**（1.2） |
| 幂等键全仓仅 1 处落地 | `00-synthesis.md §4`；前端写路径无统一幂等 | ✔ 结构确认；**未统计全量写接口数** | **OPT-R2-14**（§2.1，批二） |
| 单公司/单币种硬编码为不变量 | `00-synthesis.md §4`；`company_id`/`tenant_id`/`multi_company` 于 `fastapi_app`、`migrations` **均 0 命中**；词边界 `currency` 于 `schemas`/`shared_models`/`migrations` **均 0 命中**（本轮当场实测） | ✔ 0 命中已复核 | **OPT-R2-29**（§3.2，批三） |
| 关系 lazy 加载 + 循环内查库（N+1） | `00-synthesis.md §4`（34 处调用点**仅为举例，非清单**） | ✔ 结构确认；**清单需重建** | **OPT-R2-16**（§2.3，批二）+ 重建动作见 §6.2 |
| approval 表同表混用两种时钟 | `fastapi_app/shared_models/approval.py:21/:56/:61/:128/:130` | ✔ 逐行确认：`_utcnow` 与 `datetime.now` 同表并存 | **OPT-R2-03**（1.4） |

> **证据来源**：`docs/audit-round2/00-synthesis.md §4`（A1–A4）、`docs/audit-round2/01-backend-structure.md`、`docs/audit-round2/03-data-layer.md`（**残缺，需重跑补齐**——见 §6.1）。

### 1.2 OPT-R2-01 事务提交失败从"只记日志"改为可告警信号

- **目标**：`get_async_db()` 在 `commit()` 失败时不再只是写一条日志就静默返回，而是产出一个**可被监控抓到的信号**，并让调用方无法把"未提交"当作"成功"。
- **涉及文件:行**：`fastapi_app/core/database.py:203`（`async def get_async_db()`）、`:229`（`await session.commit()`）、`:232`（失败日志，文案含"响应已发送但数据未落库（静默丢失风险）"）、`:247`（`get_async_db_context`）、`:267/:269`（ARQ 上下文）
- **具体改法**：在 `:229` 的 `commit()` 外层捕获异常后，除现有日志外 ① 递增一个模块级计数器/向 `/metrics` 暴露 `db_commit_failures_total`；② 在响应已发出（`response.headers` 已 flush）与未发出两种情形下分别记 different 级别，前者必须 ERROR/WARNING 级；③ 依赖方（`get_async_db_context`、ARQ 上下文）沿用同一出口，不再各自吞异常。
- **验收标准（可命令化）**：
  - `grep -n "commit" fastapi_app/core/database.py` 后人工确认新的失败分支存在且**不是** 仅 `logger`；
  - `python -c "import ast,sys; ast.parse(open('fastapi_app/core/database.py',encoding='utf-8').read())"` 语法通过；
  - 单测：注入一个 `commit()` 抛异常的假 session，断言计数器 +1 且异常/信号可被上层观测（`pytest tests -k commit_failure`，**该项测试需新增**）；
  - `curl -s localhost:8000/metrics | findstr db_commit_failures_total`（部署后）。
- **风险与回滚**：把"仅记日志"改成"抛/报"可能让原本被吞掉的失败变成 500，**行为可见性会上升、可用性可能短暂下降**——这正是不该在上线前留下的东西，但需在低峰验证。回滚 = 还原该文件（单文件、无迁移）。
- **预估工时**：**0.5 人日**（含新增 1 个单测）。**依赖**：无。**批次**：批一。
- **证据来源**：`docs/audit-round2/00-synthesis.md §4`（A 类）；`fastapi_app/core/database.py:203/:229/:232/:247/:267-269`（本轮实测）。

### 1.3 【B 类 · 备份与恢复】问题全貌与证据来源

**为什么是 P0**：备份的**存在性**已被验证（有产物、有定时任务、有 CI 脚本），但**可用性从未端到端验证过**。这是本方案里唯一"一旦需要却不可用就无法补救"的一类。

| 子问题 | 证据 文件:行 | 本轮实测 | 归属项 |
|---|---|---|---|
| 加密口令缺失时**静默降级为明文备份** | `fastapi_app/api/v1/endpoints/backup/_deps.py:162/:167/:169` | ✔ 已确认 :167 提示语、:169 `return False, None` | **OPT-R2-02**（1.4 之后 → 见下） |
| 恢复演练脚本选不对产物（glob 只认 `.zip`，选不到加密产物） | `scripts/restore_drill.py:35/:36/:38/:42` | ✔ 已确认 `:36` 为 `glob('erp_backup_*.zip')` | **OPT-22（续）**（1.5） |
| 冷备后端是否上云/异地未知 | `00-synthesis.md §4`（B 类） | ✖ 未核验 | 并入 **OPT-R2-02** 的验收前置调查 |
| 恢复时间目标（RTO）/恢复点目标（RPO）无书面值 | `00-synthesis.md §4` | ✖ 未核验 | 并入 **OPT-R2-04**（见下） |
| 备份产物未做可还原性校验（校验和/试还原） | `00-synthesis.md §4` | ✖ 未核验 | 并入 **OPT-R2-04**（见下） |

> **证据来源**：`docs/audit-round2/05-ops-security-observability.md`（完整）、`docs/audit-round2/00-synthesis.md §4`（B1–B5）。

### 1.4 OPT-R2-02 备份加密口令缺失改为显式失败 + OPT-R2-04 备份可还原性校验与 RTO/RPO 书面化

> 本节含两个独立可执行项：**OPT-R2-02**（拒绝明文降级）与 **OPT-R2-04**（校验 + 目标值书面化）。

#### 1.4.1 OPT-R2-02 未配置加密口令时拒绝生成"未加密备份"

- **目标**：`BACKUP_ENCRYPTION_PASSWORD` 未配置时，备份任务**显式失败**，而不是生成一个明文包并把风险写在日志里。
- **涉及文件:行**：`fastapi_app/api/v1/endpoints/backup/_deps.py:162`、`:167`（现有提示语）、`:169`（`return False, None`）
- **具体改法**：把 `:169` 的"返回未加密 + 打警告"改为按环境分流：生产环境（`ENV`/`APP_ENV` 为 prod）**抛错并让备份任务失败**；非生产环境保留明文但把警告升级并在产物名中加 `.plaintext` 后缀，使文件系统层面可区分。
- **验收标准（可命令化）**：
  - `grep -n "return False, None" fastapi_app/api/v1/endpoints/backup/_deps.py` 在生产分支上不再命中；
  - 单测：清空环境变量后调用备份入口，断言生产路径抛异常、非生产路径产物名含 `.plaintext`（`pytest tests -k backup_encryption`，**需新增**）；
  - `python scripts/check_config.py`（若存在）或 `grep -rn BACKUP_ENCRYPTION_PASSWORD .env.example` 确认该键已列入示例配置。
- **风险与回滚**：若生产**确实**未配置该口令，改动后备份会**立刻开始失败**——这是期望行为，但上线前必须先确认口令已配置，否则会从"有明文备份"变成"没有备份"。**务必先验证配置再合并**。回滚 = 还原该文件。
- **预估工时**：**0.5 人日**（含 1 个单测 + 配置确认）。**依赖**：无。**批次**：批一。
- **证据来源**：`docs/audit-round2/05-ops-security-observability.md`；`fastapi_app/api/v1/endpoints/backup/_deps.py:162/:167/:169`（本轮实测）。

#### 1.4.2 OPT-R2-04 备份产物可还原性校验 + RTO/RPO 书面化

- **目标**：让"备份能不能还原"从一个信念变成一个**每次备份都自动回答的问题**，并把恢复目标值写进文档。
- **涉及文件:行**：`scripts/restore_drill.py:35-42`（现有演练脚本，见 OPT-22 续）、备份产出路径 `backups/server/`、`docs/`（新增说明）
- **具体改法**：① 备份完成后对产物生成并记录校验和（`sha256`）到 sidecar 文件；② 在 CI 或计划任务里增加**轻量校验步骤**：只做"解开外层容器 + 读 manifest/校验和比对"，**不导入数据库**（保证只读、不碰生产库）；③ 在 `docs` 下写明 RTO/RPO 的目标值与测算依据（本项工时含一个"确认现状"的调查动作，值本身由业务确认）。
- **验收标准（可命令化）**：
  - `Get-ChildItem backups\server\erp_backup_*.sha256` 逐产物存在；
  - 校验步骤可重复运行且退出码 0：`python scripts/verify_backup_artifact.py --latest`（脚本**需新增**，只读）；
  - `grep -n "RTO\|RPO" docs/backup-restore-*.md` 命中且含具体数值与确认人。
- **风险与回滚**：新增只读脚本，风险低；校验步骤若被误配成"响铃"需注意不要在生产库上跑 `pg_restore`。回滚 = 删除新增脚本与 CI 步骤（不影响既有备份链路）。
- **预估工时**：**1.5 人日**（含现状调查与文档）。**依赖**：与 **OPT-22（续）**（1.5）共用 `restore_drill.py` 认知，建议**先做 OPT-22 再做本项**。**批次**：批一。
- **证据来源**：`docs/audit-round2/00-synthesis.md §4`（B 类）；`docs/audit-round2/05-ops-security-observability.md`。

### 1.5 OPT-22（续）恢复演练脚本选对产物 + 真跑一次

- **目标**：把"季度恢复演练"从"脚本存在"变成"演练真的能选到产物并跑通"，闭合 OPT-22。
- **涉及文件:行**：`scripts/restore_drill.py:35`（`def newest_backup()`）、`:36`（`glob('erp_backup_*.zip')`）、`:38`（`SystemExit`）、`:42`（`async def main()`）
- **具体改法**：`:36` 的 glob 扩展为同时匹配 `.zip` 与加密产物后缀（`.enc` 等实际后缀以 `backups/server/` 现有产物为准，**需先列出实际产物名**）；`:38` 的 `SystemExit` 改为明确区分"无产物"与"产物不可用"两种退出码；`:42` 主流程增加"演练到隔离目录/临时库"的显式断言，保证**不碰生产库**。
- **验收标准（可命令化）**：
  - `Get-ChildItem backups\server\ | Select-Object Name` 列出真实产物名，与脚本 glob 模式逐一对照；
  - `python scripts/restore_drill.py --dry-run`（**需新增 dry-run 开关**）退出码 0 且打印选中的产物路径；
  - 一次真实演练记录（人日已含）：产物路径 + 耗时 + 结论，落盘到 `docs/` 或运维记录。
- **风险与回滚**：**演练必须指向隔离环境**——脚本若被指向生产库就是灾难。回滚 = 还原该脚本。
- **预估工时**：**1 人日**（含一次真实演练）。**依赖**：无（但建议与 **OPT-R2-04** 1.4.2 相邻执行，共享产物命名知识）。**批次**：批一。
- **证据来源**：`docs/audit-round2/00-synthesis.md §4`（B 类）；`docs/audit-round2/05-ops-security-observability.md`；`scripts/restore_drill.py:35-42`（本轮实测）。

### 1.6 【C 类 · 安全面】问题全貌与证据来源

**为什么是 P0**：这一类里至少有两项是"**本已具备能力、只差接线**"（权限点、限流键），性价比极高；另有一项是"**明文密钥躺在工作区**"，属于一旦泄露就不可撤销的风险。

| 子问题 | 证据 文件:行 | 本轮实测 | 归属项 |
|---|---|---|---|
| `customer_sampling` 9 个 GET 无权限校验 | `fastapi_app/api/v1/endpoints/customer_sampling.py:63/:66/:71/:90/:109/:241/:370/:382/:394/:408/:426` | ✔ 裸 `APIRouter()` + 12 处 `require_permission` 均在写路径 | **OPT-R2-06**（1.7） |
| 明文密钥/口令文件留在工作区 | `00-synthesis.md §4`（C 类） | ✖ 未核验（**由 05 号报告提供线索**） | **OPT-R2-05**（1.8） |
| 限流键信任 `X-Forwarded-For`，可被伪造绕过 | `fastapi_app/main.py:256/:265/:271` | ✔ 已确认 `:265` 为 `get_remote_address(request)` | **OPT-R2-08**（1.9） |
| JWT payload 缓存在 `request.state` 并在 `deps.py` 短路复用 | `fastapi_app/core/deps.py:195`（`:126/:147` 写入） | ✔ 已确认短路逻辑 | 并入 **OPT-R2-34**？**否**——独立为 **OPT-R2-35（缓存登出窗口）**，但**本条为"未验证"**（见 §6.1），批一仅做**确认** |
| 记录级权限依赖已写未接 | `fastapi_app/core/deps.py:363/:383` | ✔ 函数存在 | **OPT-R2-30**（§3.3，批三） |

> **证据来源**：`docs/audit-round2/05-ops-security-observability.md`（完整）、`docs/audit-round2/01-backend-structure.md`、`docs/audit-round2/00-synthesis.md §4`（C1–C7）。

### 1.7 OPT-R2-06 `customer_sampling` 9 个 GET 补权限点

- **目标**：把该模块**读**操作的权限校验补齐到与写操作同等水平。
- **涉及文件:行**：`fastapi_app/api/v1/endpoints/customer_sampling.py:63`（`router = APIRouter()`，裸）、`:66`（`PERM = 'customer_sampling_manage'`）；缺校验的 9 个 GET 在 `:71/:90/:109/:241/:370/:382/:394/:408/:426`；现有 `require_permission` 出现在 `:126/:149/:182/:199/:215/:261/:294/:312/:328/:360/:444/:462/:483`
- **具体改法**：为 9 个 GET 各自加 `Depends(require_permission(...))`；**读权限与写权限是否共用 `customer_sampling_manage` 需要设计决策**：若共用，等于给所有能改采样单的人自动加上读取全量客户采样数据的权力；建议新增读权限点（`customer_sampling_view`）或复用既有的只读角色权限，**由负责人确认后再落地**（这决定了本项是否只改一个文件）。
- **验收标准（可命令化）**：
  - 逐 GET 核对：`Select-String -Path fastapi_app/api/v1/endpoints/customer_sampling.py -Pattern "@router.get" -Context 0,4`，确认每个 `@router.get` 装饰的函数签名里都有权限依赖（9/9）；
  - `python -m mypy --config-file mypy.ini`（该文件若在清单内）不新增错误；
  - 越权用例：以无该权限的账号请求 9 个端点，全部应返回 403（**需新增测试**，`pytest fastapi_app/tests -k customer_sampling`）。
- **风险与回滚**：**补权限会打断现有前端调用**——若前端某处正是靠"无校验"在跑，上线后会立刻 403。上线前必须用前端实际调用点回归一遍。回滚 = 还原该文件（无迁移、无数据变更）。
- **预估工时**：**1 人日**（含权限模型确认 + 1 组越权测试）。**依赖**：无。**批次**：批一。
- **证据来源**：`docs/audit-round2/00-synthesis.md §4`（C 类）；`docs/audit-round2/01-backend-structure.md`；`customer_sampling.py:63/:66/:71/:90/:109/:241/:370/:382/:394/:408/:426` 与 `:126-:483` 的 `require_permission`（本轮实测）。

### 1.8 OPT-R2-05 明文密钥移出工作区 + 收紧 ACL

- **目标**：让工作区内不再存在"可直接使用的明文凭据"，并让残留风险可被静态检查持续拦住。
- **涉及文件:行**：候选清单由 `docs/audit-round2/05-ops-security-observability.md` 给出（**本项必须先按该报告确认具体文件**，本方案不转抄其清单，避免把未复核路径写成事实）；静态检查入口 `.github/workflows/ci-cd.yml:168-169`（`python scripts/scan_secrets.py --verbose`）
- **具体改法**：① 按 05 号报告逐项确认明文凭据文件，移出工作区（移到受 ACL 保护的位置）或改为从环境/密钥库读取；② 收紧残留文件的 ACL 到"仅服务账号 + 管理员"；③ 把 `scan_secrets.py` 从"单独步骤"提升为**阻断式**（当前为 `:168-169` 普通步骤，非阻断）。
- **验收标准（可命令化）**：
  - `python scripts/scan_secrets.py --verbose` 退出码 0；
  - `icacls <已迁移目录>` 输出中不含 `Users:(F)` 一类宽权限（PowerShell：`icacls <dir>`）；
  - CI 中该步骤在失败时使 job 失败（检查 `.github/workflows/ci-cd.yml` 该步骤无 `continue-on-error: true`）。
- **风险与回滚**：移动凭据文件可能**打断正在使用它的脚本/服务**——必须先全局搜引用再移动。回滚 = 移回原位（保留原文件副本直到验证通过）。
- **预估工时**：**1 人日**（含引用普查 + ACL）。**依赖**：无。**批次**：批一。
- **证据来源**：`docs/audit-round2/05-ops-security-observability.md`；`.github/workflows/ci-cd.yml:168-169`（本轮实测）。

### 1.9 OPT-R2-08 限流键不再信任 XFF

- **目标**：让限流按"真实客户端"计数，而不是按调用方可以随意伪造的头。
- **涉及文件:行**：`fastapi_app/main.py:256`（`def _rate_limit_key`）、`:265`（`get_remote_address(request)`）、`:271`（`limiter.key_func = _rate_limit_key`）；对照 `scripts/restart_backend.py:68`（`--forwarded-allow-ips=*`）
- **具体改法**：`:265` 不再直接用客户端提供的 XFF 取值；改为信任**已确认的反向代理跳数/已知代理 IP 列表**（与 `:271` 的代理配置一致），或改用 nginx 层 `limit_req` + `real_ip`（后者即 OPT-18 续做，见 §2.14）。**关键**：`:68` 的 `--forwarded-allow-ips=*` 使得"信任 XFF"从可配置变成无条件信任，必须一并收紧。
- **验收标准（可命令化）**：
  - `grep -n "forwarded-allow-ips" scripts/restart_backend.py` 结果不再是 `*`；
  - 构造带伪造 XFF 的请求，连续超限后仍应被限流（**需新增集成测试**或手工步骤记录）；
  - `curl -H "X-Forwarded-For: 1.2.3.4" ...` 重复请求，观察限流计数键不随伪造头漂移（日志或 `/metrics`）。
- **风险与回滚**：改限流键会**改变所有客户端的计数归属**，若代理链配置错误可能导致**全部请求被判为同一客户端而被限流**（内网自伤）。先在内网灰度、准备好回滚。回滚 = 还原 `main.py` 与 `restart_backend.py`。
- **预估工时**：**0.5 人日**（不含 nginx 侧改造，后者归 OPT-18）。**依赖**：与 **OPT-18（续）** 强相关，建议同批但本项先落地（纯应用层）。**批次**：批一。
- **证据来源**：`docs/audit-round2/00-synthesis.md §4`（C 类）；`docs/audit-round2/05-ops-security-observability.md`；`fastapi_app/main.py:256/:265/:271`、`scripts/restart_backend.py:66/:68`（本轮实测）。

### 1.10 【D 类 · 暴露面】问题全貌与证据来源

**为什么是 P0**：这一类的核心问题是"**内网不等于安全**"——服务监听面、账户权限、旁路脚本三者叠加，决定了"一台内网机器被拿下"会不会立刻变成"数据库被拿走"。

| 子问题 | 证据 文件:行 | 本轮实测 | 归属项 |
|---|---|---|---|
| 后端启动显式绑 `0.0.0.0` | `scripts/restart_backend.py:66` | ✔ 已确认 | **OPT-R2-07**（1.11） |
| 反向代理无条件信任转发头 | `scripts/restart_backend.py:68` | ✔ 已确认 | 并入 **OPT-R2-08**（1.9） |
| PG 监听范围 / 服务账户权限 / 旁路脚本（cron/计划任务/裸脚本直连库）未普查 | `00-synthesis.md §4`（D 类） | ✖ **未核验**——这是四个"需先重建清单"之一 | **OPT-R2-10**（1.12，**需先重建清单**） |
| `/api/health/db` 等信息面是否外露 | `00-synthesis.md §4` | ✖ 未核验 | **OPT-R2-12**（1.13） |
| 审计日志 `client_ip` 口径不统一 | `00-synthesis.md §4` | ✖ 未核验 | **OPT-R2-13**（1.14） |

> **证据来源**：`docs/audit-round2/00-synthesis.md §4`（D1–D4）、`docs/audit-round2/05-ops-security-observability.md`。

### 1.11 OPT-R2-07 撤销 `restart_backend.py` 的 `--host 0.0.0.0`

- **目标**：后端不再对所有网络接口监听；只监听必要的接口（`127.0.0.1` 或指定内网网卡），由反向代理对外。
- **涉及文件:行**：`scripts/restart_backend.py:66`（`"--host", "0.0.0.0"`）、`:68`（`--forwarded-allow-ips=*`，与 OPT-R2-08 联动）
- **具体改法**：`:66` 改为监听回环或指定网卡；同时收紧 `:68` 的转发头信任范围（与 1.9 一起改，避免只改一半）。若部署形态**确实**需要直接对外监听（例如无反向代理），则改为绑定具体内网 IP 并在防火墙侧限定来源——**需先确认部署拓扑**。
- **验收标准（可命令化）**：
  - `grep -n "0.0.0.0" scripts/restart_backend.py` 无命中（或命中处已带明确说明）；
  - 重启后 `netstat -ano | findstr :8000` 显示监听地址不是 `0.0.0.0`；
  - 反代路径上的正常请求仍 200（回归 3 个主要接口）。
- **风险与回滚**：若实际有**直连后端**的客户端（绕过反代），改绑后会立刻断连——必须先用访问日志确认无直连。回滚 = 还原脚本并重启（重启窗口需安排，见 §8 纪律）。
- **预估工时**：**0.5 人日**（含拓扑确认 + 重启验证）。**依赖**：无（与 OPT-R2-08 同源文件，**建议合并为一个改动窗口**）。**批次**：批一。
- **证据来源**：`docs/audit-round2/00-synthesis.md §4`（D 类）；`scripts/restart_backend.py:66/:68`（本轮实测）。

### 1.12 OPT-R2-10 暴露面收口（PG 监听 / 服务账户 / 旁路脚本普查）★ 需先重建清单

- **目标**：把"内网之外/之内谁能碰到数据库"这件事**查清并收口**——包括 PG 的 `listen_addresses`/`pg_hba.conf`、数据库服务账户的实际权限、以及绕过应用直连数据库的 cron/计划任务/裸脚本。
- **涉及文件:行**：**待普查产出**——本项目前**没有清单**（`00-synthesis.md §4` D 类只给出问题类别与举例，`docs/audit-round2/05-ops-security-observability.md` 给出线索但未构成全量清单）。**这是本方案四个"需先重建清单"项之一。**
- **⚠️ 需先重建清单**：**重建动作**（只读、不需要连库即可完成大部分）：
  1. 静态普查：`grep -rn "psycopg\|asyncpg\|create_engine\|DATABASE_URL" --include=*.py --include=*.ps1 --include=*.bat --include=*.cmd .`（排除 `.venv`、`node_modules`）→ 得到"代码里所有可能的直连点"；
  2. 运行面普查（**需运维配合、只读**）：`schtasks /query /v /fo LIST` 与 `Get-Service` 导出，筛出引用上述脚本的计划任务/服务；
  3. PG 侧（**只读查询**，不改配置）：`SHOW listen_addresses;` 与 `pg_hba.conf` 文本对照（`SELECT * FROM pg_hba_file_rules;`），以及服务账户的 `\du` 输出。
  **重建工时并入本项：+0.5 人日**。
- **具体改法**：依据清单逐项处置：PG 监听收敛到内网必要网卡；`pg_hba` 只保留必要来源；服务账户降权（去掉 `SUPERUSER`/`CREATEDB` 等非必需属性）；旁路脚本改为走应用或专用只读账户。
- **验收标准（可命令化）**：
  - 清单文件落盘（`docs/` 或运维记录），**清单条目数 ≥ 实际发现的直连点数**；
  - `SELECT * FROM pg_hba_file_rules;` 输出与收敛后配置一致，无 `0.0.0.0/0` 条目；
  - `\du` 输出中服务账户无 `Superuser`；
  - 复跑第 1 步静态普查，命中集合与清单一致（无遗漏）。
- **风险与回滚**：**改 `pg_hba`/账户权限会让某些现存连接立刻失败**——这是最可能"改完出事"的一项，必须在维护窗口做，并提前备份 `pg_hba.conf` 原文（回滚 = 还原该文件并 reload）。**本项禁止通过运行 alembic 来"验证"任何数据库状态**（见 §8 纪律）。
- **预估工时**：**1.5 人日**（其中 **0.5 为清单重建**，1.0 为处置与验证）。**依赖**：无前置；与 **OPT-R2-11**（1.13 配置漂移）共享"配置现状"认知。**批次**：批一（**工时含重建，属"待复核"项——见 §6.1**）。
- **证据来源**：`docs/audit-round2/00-synthesis.md §4`（D 类）；`docs/audit-round2/05-ops-security-observability.md`（线索，非全量清单——**缺口已标注**）。

### 1.13 OPT-R2-11 配置漂移门禁化

- **目标**：让"代码里读的配置键"与"`.env`/`.env.example` 里实际提供的键"不再静默漂移（缺键时用默认值继续跑，是最典型的静默失败）。
- **涉及文件:行**：`fastapi_app/core/config.py`（配置定义，OPT-12 已完成 `field_validator` 加固——**沿用编号，不重复**）；对照 `.env.example`；门禁入口 `.github/workflows/ci-cd.yml:173-174`（`scripts/quality_gate.py --verbose`）
- **具体改法**：写一个只读检查脚本，静态提取 `config.py` 中声明的配置键，与 `.env.example` 逐键比对，输出"代码有、示例无"与"示例有、代码无"两张差集；把该检查接入 `quality_gate.py`（或作为独立 CI 步骤）。**注意**：本项只检查**键集合**，不读取也不校验真实密钥值。
- **验收标准（可命令化）**：
  - `python scripts/check_config_drift.py --verbose` 退出码 0（或在确认差集后以基线方式通过）；
  - `python scripts/quality_gate.py --verbose` 输出中包含该检查项；
  - 故意删掉 `.env.example` 里一个键，该检查应失败（自测一次即可）。
- **风险与回滚**：若现存差集很大，首次接入会产生一堆告警→ 用 `quality_gate.py` 既有的**基线机制**（`:177 load_baseline`/`:189 save_baseline`/`:205 --update-baseline`）冻结现状，避免一次性阻断 CI。回滚 = 摘掉 CI 步骤。
- **预估工时**：**1 人日**。**依赖**：`quality_gate.py` 基线机制（已有）；与 **§4.1**（门禁改造）同源，建议与 §4.1 一并设计。**批次**：批一。
- **证据来源**：`docs/audit-round2/00-synthesis.md §5`（批一）；`scripts/quality_gate.py:177/:189/:205`、`.github/workflows/ci-cd.yml:173-174`（本轮实测）。

### 1.14 OPT-R2-12 `/api/health/db` 信息面收敛 + OPT-R2-13 审计 `client_ip` 口径统一

> 本节含两个独立可执行项。两项共同的前提是"**先看清现在暴露/记录了什么**"，因此都含一次只读确认动作，但**不构成"需先重建清单"项**（各自范围小、可当场查完）。

#### 1.14.1 OPT-R2-12 健康检查接口信息面收敛

- **目标**：`/api/health/db` 只在必要时暴露连通性，不暴露库名/版本/连接串片段等可被用于踩点的信息（对内部网络同样适用：内部横向移动者最需要的就是这些）。
- **涉及文件:行**：健康检查实现文件（`fastapi_app` 下 health 相关路由，**确认路径后填写**）；对照 `docs/audit-round2/05-ops-security-observability.md` 中关于 `/metrics` fail-closed 的观察（`health.py:200-214`，t1 归档者已复核）。
- **具体改法**：把响应体收窄为 `{status: "ok"|"degraded"}` 一类的最小结构；详细信息改为仅在内网管理端点或需要鉴权时返回；错误分支不得把异常原文（含库名/主机名）直接回显。
- **验收标准（可命令化）**：`curl -s localhost:8000/api/health/db` 输出不含库名/版本/主机名（人工核对 + `findstr` 关键词检查）；正常路径仍返回 200。
- **风险与回滚**：若有监控/告警依赖原响应字段，需同步调整探针。回滚 = 还原该文件。
- **预估工时**：**0.5 人日**。**依赖**：无。**批次**：批一。
- **证据来源**：`docs/audit-round2/00-synthesis.md §4`（D 类）；`docs/audit-round2/05-ops-security-observability.md`。

#### 1.14.2 OPT-R2-13 审计日志 `client_ip` 口径统一

- **目标**：审计记录里的 `client_ip` 含义唯一（要么恒为"直连对端"，要么恒为"反代还原后的真实客户端"），不因入口不同而不同——否则审计日志在追责时不可用。
- **涉及文件:行**：审计写入点（`fastapi_app` 审计/日志模块）、限流键 `fastapi_app/main.py:256-271`（同一"取客户端 IP"逻辑的两处消费者）、反代配置（`scripts/restart_backend.py:68`）。
- **具体改法**：抽出**唯一**的"取客户端 IP"函数（与 OPT-R2-08 共用），所有审计/限流/日志调用它；明确其语义为"经可信代理还原后的客户端地址"，并在代码注释与文档中写明。
- **验收标准（可命令化）**：`grep -rn "client_ip\|remote_addr\|x-forwarded-for" fastapi_app` 人工核对后确认只保留一个取值入口；新写入的审计记录经一次手工请求后字段值与预期一致（抽 3 条对照）。
- **风险与回滚**：与 OPT-R2-08 同源改动，**必须一起做**否则会出现两套语义。回滚 = 还原相关文件。
- **预估工时**：**0.5 人日**。**依赖**：**OPT-R2-08**（1.9）—— 本项在其后执行。**批次**：批一。
- **证据来源**：`docs/audit-round2/00-synthesis.md §4`（D 类）；`fastapi_app/main.py:256/:265/:271`、`scripts/restart_backend.py:68`（本轮实测）。

### 1.15 OPT-02（续）修最后 1 条 pytest 失败

- **目标**：闭合 OPT-02（6 条失败中已修 5 条，剩 1 条），让"测试全绿"成为可依赖的上线前提。
- **涉及文件:行**：失败用例的定位需**当场跑一次**得到（本方案不预填，避免写成未验证事实）；测试范围与 CI 一致：`pytest.ini:3`（`testpaths = tests fastapi_app/tests`），CI 步骤 `.github/workflows/ci-cd.yml:68-95`（`--ignore` 了 `tests/qa`、`tests/e2e`、`tests/stress`、`tests/performance`）。
- **具体改法**：运行 CI 同口径的 pytest，定位剩余 1 条失败并按"被测代码问题 / 测试本身过时"分流修复。**注意**：`--ignore` 的四类目录**不在 CI 门禁范围内**，本项只修 CI 口径内那 1 条；其余目录的失败情况需单独记录（见 §6.1）。
- **验收标准（可命令化）**：`python -m pytest tests fastapi_app/tests --ignore=tests/qa --ignore=tests/e2e --ignore=tests/stress --ignore=tests/performance -q` **0 failed**（与 CI 完全同口径）。
- **风险与回滚**：若剩余失败源于被测行为"本来就是错的"，修测试会掩盖问题——需在修复说明中写明判定理由。回滚 = 逐文件还原。
- **预估工时**：**0.5 人日**（视失败根因而定，**上限 1 人日**；本项标注为**待复核**——见 §6.1）。**依赖**：无。**批次**：批一。
- **证据来源**：队长给定的 OPT-02 状态（**权威事实，本方案不改写**）；`pytest.ini:3`、`.github/workflows/ci-cd.yml:68-95`（本轮实测）。

### 1.16 OPT-R2-35（批一仅"确认"，不做改造）JWT payload 缓存短路带来的登出窗口

- **目标**：**先确认**"登出/权限变更后，缓存于 `request.state._jwt_payload` 的鉴权结论还能存活多久"这一**未验证**风险是否真实存在；若不存在，关闭该项；若存在，**不在批一改造**（改造需要设计决策），转入 §3 批三。
- **涉及文件:行**：`fastapi_app/core/deps.py:195`（`cached_payload = getattr(request.state, "_jwt_payload", None)` 短路复用）、`:126/:147`（该 state 的两处写入点）
- **具体改法（批一只做确认）**：读 `:195` 上下文的缓存作用域（单请求内还是跨请求/进程级），产出结论："仅单请求内复用（则风险不存在，关闭）"或"跨请求存活（则记录窗口长度，转批三）"。
- **验收标准（可命令化）**：一份**一句话结论 + 证据行号**落盘（写入 `docs/optimization-status-2026-10-01.md` 或本方案后续修订）；结论必须引用 `:195/:126/:147` 的实际代码语义，不接受"应该是"。
- **风险与回滚**：纯只读确认，无风险。回滚不适用。
- **预估工时**：**0.5 人日**。**依赖**：无。**批次**：批一（仅确认动作）。
- **证据来源**：`docs/audit-round2/00-synthesis.md §6`（"未验证"表之一）；`fastapi_app/core/deps.py:195/:126/:147`（本轮实测）。

#### 1.16.1 OPT-R2-03 approval 表时钟混写（A 类）

- **目标**：让 `approval` 表的时间列使用**同一个时钟基准**，消除"同一行数据里两个字段差 8 小时"的静默错误。
- **涉及文件:行**：`fastapi_app/shared_models/approval.py:21`（`def _utcnow()`）、`:56`（`request_time default=_utcnow`）、`:61` 与 `:130`（`updated_at ... default=datetime.now, onupdate=datetime.now`）、`:128`（`action_time default=_utcnow`）
- **具体改法**：把 `:61` / `:130` 的 `updated_at` 改为与 `:56` / `:128` 一致的 `_utcnow`；若仓储层另有"显式赋当前时间"的写法，一并统一到 `_utcnow`。
- **验收标准（可命令化）**：
  - `grep -n "datetime.now" fastapi_app/shared_models/approval.py` **无命中**；
  - 新建并更新一条审批记录后，`updated_at` 与 `request_time` 处于同一基准（差值在秒级，而不是小时级）；
  - **存量数据不迁移**：本项只对新写入生效；存量混写状态在 §6.1 标注（**不得声称已修好历史数据**）。
- **风险与回滚**：历史数据仍是本地时间，跨基准排序/相减会出现偏差——查询与报表侧需注意；本项不改存量。回滚 = 还原该文件（单文件、无迁移）。
- **预估工时**：**0.5 人日**。**依赖**：无（与 OPT-R2-01 同批执行）。**批次**：批一。
- **证据来源**：`docs/audit-round2/00-synthesis.md §4`（A 类）；`fastapi_app/shared_models/approval.py:21/:56/:61/:128/:130`（本轮实测）。

### 1.17 批一小结

- **项数**：**15 个可执行项 + 1 个台账项 = 16 项**。可执行项 = OPT-R2-01 / 02 / 03 / 04 / 05 / 06 / 07 / 08 / 10 / 11 / 12 / 13 / 35 + **OPT-02（续）** + **OPT-22（续）**（OPT-R2-02 与 OPT-R2-04 同列于 1.4；OPT-R2-12 与 OPT-R2-13 同列于 1.14）；台账项 = §0.1 的 **OPT-R2-36**。四类问题全貌见 1.1（A）/ 1.3（B）/ 1.6（C）/ 1.10（D）。
- **工时**：**12.0 人日**（明细与自洽性校验见 §7）。其中 **2.25 人日**是**为批二预备的清单重建**（OPT-R2-10 的 0.5 + OPT-R2-14 的写接口清单 0.5 + OPT-R2-15 的索引清单 1.0 + OPT-R2-17 的池配置键位 0.25），**提前到批一做**是因为批二最大两项（索引、N+1）**没有清单就无法给出可信工时与验收**；扣除这部分，批一自身的上线前整改是 **9.75 人日**。
- **待复核**：**1.0 人日**（OPT-R2-10 的清单重建 0.5 + OPT-02 续的上限浮动 0.5）——见 §6.1。
- **批一完成定义（DoD）**：① §0.1 台账已落盘并录入历史 22 项 + 本轮项；② CI 口径下 pytest 0 failed；③ A/B/C/D 四类中所有"批一"子项各自的命令化验收通过；④ §4 门禁改造中**不改变行为**的部分（4.2、4.4 的检测项）已接入。
- **不在批一的原因（明确边界）**：幂等层（§2.1）、索引收口（§2.2）、N+1 批量化（§2.3）、mypy 扩容（§2.10）、契约对齐（§3.8）等**都重要但都不该在上线前动**——它们要么需要重建清单，要么需要设计决策，要么改动面大到无法在维护窗口内保证可回滚。
- **证据来源**：批一排序原则取自 `docs/audit-round2/00-synthesis.md §5`（批一路线图 9 条）；本节的项拆分与工时为本方案新增，数字口径见 §7。

---

## 2. 批二 · 2–6 周（P1）

> **口径**：批二 = 上线后 **2–6 周**内完成。与批一的差别不是"重要性更低"，而是**改动面更大或需要先重建数据清单**。本节共 **13 个新增项（OPT-R2-14 ～ OPT-R2-26，缺 27 见下文说明）+ 2 个沿用编号项（OPT-18 续、OPT-21 续）+ 1 项 §4 联动（§4.1 门禁聚合入口，本轮修订单列为 **OPT-R2-37**）**，合计 **31.0 人日**（见 §7）。

> **编号说明**：`OPT-R2-27` 被排到 §3.8（字段级 API 契约对齐），因此本节编号跳到 28 之前即止；本节新增项为 14/15/16/17/18/19/20/21/22/23/24/25/26 共 13 项，无缺号。`OPT-R2-27` 属批三。

### 2.1 OPT-R2-14 通用幂等层

- **目标**：让**所有**状态变更接口具备"同一请求重复提交只生效一次"的能力，而不是目前全仓仅 1 处落地。
- **涉及文件:行**：`00-synthesis.md §4`（A 类子问题：幂等键仅 1 处）；参照实现位置由 `docs/audit-round2/01-backend-structure.md` 给出（**本方案不转抄未复核路径**）；中间件挂载点 `fastapi_app/main.py`（应用装配处）。
- **⚠️ 需先重建清单（部分）**：要枚举"哪些写接口需要幂等"，必须先列出全部写接口（POST/PUT/PATCH/DELETE 路由）。**重建动作**：`grep -rn "@router.post\|@router.put\|@router.patch\|@router.delete" fastapi_app/api/v1/endpoints/` 按文件聚合计数（只读、纯静态）。**这是"路由数口径"差异的同一来源**：01 号 373 / 02 号 385 / 05 号 382 三个数字并存，本项**不裁定哪个正确**，重建时以脚本输出为准并注明口径。**重建工时 +0.5 人日**。
- **具体改法**：① 在请求入口统一读取幂等键（建议 `Idempotency-Key` 头，与前端口径对齐）；② 建立"键 → 处理结果"的持久化记录（需要一张表或复用现有表，**表设计需设计决策**）；③ 对重复键返回首次结果而非重复执行；④ 仅对"写且非幂等语义"的接口启用（GET 不启用）。
- **验收标准（可命令化）**：
  - 同一写接口连续提交两次相同幂等键，第二次**不产生新记录**（用例：`POST` 两次 → 查库计数为 1；**需新增集成测试**）；
  - 缺幂等键的写接口要么被显式拒绝要么走明确标记的"非幂等"分支（`grep` 检查白名单存在且非空）；
  - 重建出的写接口清单落盘，覆盖率可核对（已启用数 / 应启用数）。
- **风险与回滚**：**这是批二风险最高的一项**——需要新增持久化结构，若键的清理策略不当会导致表无限增长；若幂等键由客户端生成，前端不配合就会退化为"无幂等"。建议**先在一个接口试点**（与 OPT-09 的试点策略一致），验证后再铺开。回滚 = 摘掉中间件 + 保留表（表中数据无害）。
- **预估工时**：**4 人日**（**待复核**：含 0.5 清单重建、表设计与 1 个试点；若表设计需要评审则 +1～2 人日，见 §6.1）。**依赖**：**OPT-09（续）**（前端需要配合传幂等键，见 §2.14）。**批次**：批二。
- **证据来源**：`docs/audit-round2/00-synthesis.md §4`（A 类）；`docs/audit-round2/01-backend-structure.md`（路由口径注意 373/385/382 并存）。

### 2.2 OPT-R2-15 索引收口（33 个真缺失 + FK 前导索引 + 4 列决策）

- **目标**：把"该有的索引"补齐，并把"不该有的索引"决策掉，同时消除 FK 无前导索引这类典型隐患。
- **涉及文件:行**：**待重建清单**——`docs/audit-round2/03-data-layer.md`（**残片，需重跑补齐**）与 `00-synthesis.md §4` 只给出**举例**，**不构成 33 个索引的逐条清单**。**这是本方案四个"需先重建清单"项之一。**
- **⚠️ 需先重建清单**：**重建动作（必须离线/静态，禁止跑 alembic——见 §8 纪律）**：
  1. 从模型声明静态提取"关系列"（FK 列）：`grep -rn "ForeignKey(" fastapi_app/shared_models/`；
  2. 从迁移或模型静态提取"现有索引"：`grep -rn "Index(\|index=True" fastapi_app/shared_models/` + `grep -rn "op.create_index" migrations/versions/`；
  3. 差集 = FK 列中无前导索引者 → 逐条列出（这就是"33 个真缺失"的**可核对版本**）；
  4. 若要拿到 PG 侧真实索引状态：用**离线模式** `alembic -c migrations/alembic.ini upgrade head --sql` **只看生成的 SQL**（不执行），或纯静态解析迁移链；**不得执行任何 alembic 命令**（`migrations/env.py:43-49`：每条 alembic 命令都会对 `alembic_version` 发 DDL，违反只读约束）。
  **重建工时 +1 人日**。
- **具体改法**：按清单新增缺失索引（每个索引一次迁移或合并为一个迁移）；FK 列补前导索引；对 4 个"待决策列"逐个给出结论（建/不建 + 理由）。
- **验收标准（可命令化）**：
  - 重建出的清单与最终迁移**条目数一致**；
  - `grep -rn "op.create_index" migrations/versions/` 新增条目数与清单一致；
  - **不依赖索引命中率**：本轮审计已判定 `pg_stat_reset` 之后多数表仅 0–30 行，`idx_scan` 统计**不可靠**，因此**验收不得使用"索引被使用次数"作为通过条件**（这是明确禁止的性能数字来源）；
  - 迁移可逆：`downgrade` 路径存在（静态检查迁移文件含 `def downgrade`）。
- **风险与回滚**：**加索引在写密集表上会造成锁与写放大**——必须在维护窗口做，且大表需评估是否用并发建索引（PG 的 `CREATE INDEX CONCURRENTLY` 无法在事务里执行，与当前迁移框架的执行方式可能冲突，**需确认**）。回滚 = 对应 `downgrade`（已作为验收项要求存在）。
- **预估工时**：**3 人日**（**待复核**：含 1 人日清单重建；如某表数据量大需分批/并发建索引则 +1～2 人日，见 §6.1）。**依赖**：无；但**与 §2.3（关系加载）共享同一"清单重建"工作**，建议合并做一次普查。**批次**：批二。
- **证据来源**：`docs/audit-round2/03-data-layer.md`（**残缺——引用需同时声明"需重跑补齐"**）；`docs/audit-round2/00-synthesis.md §4`。

### 2.3 OPT-R2-16 关系 lazy 显式化 + N+1 批量化

- **目标**：消除"关系默认 lazily 加载 + 循环内逐条查库"这一 O(N) 放大模式，改为显式 `selectinload`/`joinedload` 或批量查询。
- **涉及文件:行**：**待重建清单**——`00-synthesis.md §4` 给出的 **34 处循环内查库调用点仅为举例，不是清单**。**这是四个"需先重建清单"项之一。**
- **⚠️ 需先重建清单**：**重建动作（纯静态、只读）**：
  1. `grep -rn -A3 "relationship(" fastapi_app/shared_models/` 找未显式指定 `lazy=` 的关系；
  2. 找"循环体内访问 ORM 关系/执行查询"的模式：`grep -rn -B2 -A6 "for .* in .*:" fastapi_app/services/ | grep -n "select(\|\.query(\|await .*get(" ` （命令需按实际代码风格微调）；
  3. 对每个候选人工确认后登记为清单条目（**必须人工确认**，纯正则会有大量误报）。
  **重建工时 +0.5 人日**。
- **具体改法**：对确认的调用点改为预加载或批量查询（`in_` 一次取回）；对关系声明显式写 `lazy="selectin"` 或 `lazy="select"`，不再依赖默认值。
- **验收标准（可命令化）**：
  - 清单条目逐条有对应改动（条目数 ↔ 改动数可核对）；
  - **不在没有测量的情况下承诺"查询数下降 X%"**：可用 `SQLAlchemy` 的事件钩子**在测试环境**统计单请求 SQL 条数（这是可测量的，但**必须实际测量后才写数字**；本方案不预填）；
  - 现有测试全绿（CI 口径，见 1.15）。
- **风险与回滚**：`selectinload` 在数据量大的场景可能把"多次小查询"变成"一次超大查询"，**方向可能反转**——必须先测量再决定；改关系默认加载方式会影响全局调用点，必须逐文件确认。回滚 = 逐文件还原。
- **预估工时**：**3 人日**（**待复核**：含 0.5 清单重建；实际条目数未知，若超 20 处则 +1～2 人日，见 §6.1）。**依赖**：与 **OPT-R2-15**（2.2）共享普查工作。**批次**：批二。
- **证据来源**：`docs/audit-round2/00-synthesis.md §4`（A 类）；`docs/audit-round2/03-data-layer.md`（残缺）。

### 2.4 OPT-R2-17 连接池参数接线

- **目标**：让数据库连接池参数**真正生效**——目前存在配置项声明了但从未被消费的情况（即"改了配置没用"）。
- **涉及文件:行**：**4 个死配置键位待确认**——`DB_POOL_SIZE` / `DB_MAX_OVERFLOW` / `DB_POOL_RECYCLE` 以及"缺失的 `pool_recycle`"；配置定义处 `fastapi_app/core/config.py`，引擎构造处 `fastapi_app/core/database.py`（`:203` 附近 `create_async_engine`）。
- **⚠️ 部分需先重建清单**：**重建动作（纯静态）**：`grep -rn "DB_POOL\|pool_size\|max_overflow\|pool_recycle" fastapi_app/ --include=*.py` → 区分"声明处"与"消费处"；**声明有、消费无**者即为死键。**重建工时 +0.25 人日**（范围小，可当场完成）。
- **具体改法**：把 `create_async_engine` 的池参数改为从配置读取；补上 `pool_recycle`（避免长连接被中间设备/数据库静默切断后返回陈旧连接——**具体超时值需按数据库侧 `idle_in_transaction_session_timeout` 等实际配置确定，不预填**）。
- **验收标准（可命令化）**：
  - `grep -rn "pool_size\|max_overflow\|pool_recycle" fastapi_app/core/database.py` 命中且来自配置对象；
  - 4 个键在静态普查中不再属于"声明无消费"；
  - 行为验证：设置一个非默认的 `pool_size`，观察连接数上限随之变化（**测试环境**，需实际观察而非推断）。
- **风险与回滚**：池参数设错会导致**连接耗尽或连接风暴**（比不改更糟）。必须保守取值并观察。回滚 = 还原 `database.py`。
- **预估工时**：**1 人日**。**依赖**：无。**批次**：批二。
- **证据来源**：`docs/audit-round2/00-synthesis.md §4`（连接池键位列入"未验证"表）。

### 2.5 OPT-R2-18 统一错误信封

- **目标**：让所有错误响应具有**同一形状**，使前端可以统一处理、日志可以统一解析。
- **涉及文件:行**：`fastapi_app/core/exceptions.py:18/:74/:203-214`（异常定义与处理器）、`fastapi_app/main.py:302`（`@app.exception_handler(AppError)`）、`:313`（`"code": exc.code`）、`:323`（`async def http_exception_handler`）
- **具体改法**：以 `:313` 已有的 `code` 字段为基准，统一"应用异常"与"框架异常（`HTTPException`/`RequestValidationError`）"两条路径的响应体结构（建议 `{code, message, detail?}`）；`:323` 目前是独立实现，需与 `:302` 对齐；校验错误（422）也要走同一信封。
- **验收标准（可命令化）**：
  - 构造四类错误各一次（业务异常 / 404 / 422 校验失败 / 未捕获 500），**四者响应体的键集合一致**（手工 `curl` + `ConvertFrom-Json | Get-Member` 比对，或新增契约测试）；
  - `grep -n "JSONResponse" fastapi_app/main.py fastapi_app/core/exceptions.py` 确认错误响应出口收敛；
  - 现有前端错误处理不回归（至少 1 条主流程手测）。
- **风险与回滚**：**改错误响应形状会打断前端已有的按形状解析逻辑**——必须同时改前端，或保持向后兼容（新增字段而不改既有字段名）。回滚 = 还原后端 + 前端（若已同步改）。
- **预估工时**：**1.5 人日**（含前后端联调）。**依赖**：**OPT-R2-27**（§3.8 契约对齐工具）可复用同一契约描述，但本项不依赖它。**批次**：批二。
- **证据来源**：`docs/audit-round2/00-synthesis.md §5`（批二）；`fastapi_app/core/exceptions.py:18/:74/:203-214`、`fastapi_app/main.py:302/:313/:323`（本轮实测）。

### 2.6 OPT-R2-19 前端通用能力收编

- **目标**：把"已经写好、但几乎没人用"的前端通用能力收编到实际调用点，或明确废弃——消除"能力已具备未收尾"这一错位的具体表现。
- **涉及文件:行（本轮实测，均为确认过的事实）**：
  - `useEnhancedList`：定义 `frontend-vite/src/composables/useEnhancedList.ts:13`；**唯一消费方** `frontend-vite/src/views/product/components/ProductTable.vue:60`（import）、`:90`（调用）——全仓仅 3 处命中
  - `UiFilterBar`：**全仓仅 1 处命中**（`frontend-vite/src/components.d.ts:36`，即自动生成的类型声明，等于零实际使用）；**11 个** `views/**/*.vue` 文件在各自**手写** keyword ref（实测 36 处命中：`BatchView.vue`、`BeileOrderTab.vue`、`CustomerOrderView.vue`、`OrderRecordFilter.vue`、`OutsourceShipDialog.vue`、`OutsourceShipPickPanel.vue`、`CustomerGroupList.vue`、`CustomerGroupSearchBar.vue`、`BomEditor.vue`、`BomRolePicker.vue`、`RecordFilterBar.vue`）——**注**：报告 02 记 12 个文件，本轮实测 11 个；本方案按实测写 11 并注明口径差异
  - `useEventDelegation`：仅自身文件命中（`:7/:9`）→ **零消费方**
  - `useVirtualScrollList`：仅自身文件命中（`:29`）→ **零消费方**
  - `catalog.ts`：`frontend-vite/src/stores/catalog.ts:18`（`CATALOG_TTL_MS`）、`:21`（`CATALOG_PAGE_PARAMS={page:1,per_page:1000}`）、`:30`（`createCatalogEntry`）、`:83/:89/:95/:102`（4 个条目）
  - `patternRoom.ts`：`frontend-vite/src/stores/patternRoom.ts:20`（`PATTERN_ROOM_STALE_MS=30_000`）、`:22`（`PATTERN_ROOM_PAGE_SIZE=20`）、`:24`（`SESSION_KEY`）、`:26`（`MAX_PERSIST_CHARS=300_000`）
- **具体改法**：**逐项二选一**（决策必须留痕，写入 `docs`）：① **收编**——把至少 N 个手写 keyword ref 改用 `UiFilterBar`（N 由负责人定，建议先 3 个试点）；② **废弃**——删除零消费方的 `useEventDelegation`/`useVirtualScrollList`。**不建议**为了"用起来"而强行改 11 个文件——这正是"能力已具备未收尾"的反面陷阱。
- **验收标准（可命令化）**：
  - 每个被处置的模块有一句结论（收编/废弃 + 理由）落盘；
  - 收编项：`grep -rn "UiFilterBar" frontend-vite/src` 命中数从 1 提升到"1 + 试点文件数"；
  - 废弃项：文件已删除且 `grep -rn "<name>" frontend-vite/src` 无残留引用；
  - `cd frontend-vite; npm run lint; npx vitest run`（CI 同口径）通过。
- **风险与回滚**：删组件前必须确认无动态引用（字符串拼接式引用正则抓不到）；收编时行为可能与手写实现有细微差异（如 ref 同步时机），需人工回归。回滚 = git 还原单个文件。
- **预估工时**：**2.5 人日**（决策 0.5 + 收编试点 1.5 + 废弃清理 0.5）。**依赖**：**OPT-R2-20**（2.7 死代码清理）建议在前，避免重复劳动。**批次**：批二。
- **证据来源**：`docs/audit-round2/00-synthesis.md §4`（"能力已具备未收尾"）；`docs/audit-round2/02-frontend-architecture.md`（**⑤ 节中途截断——只引用确实存在的部分**）；以上路径与行号为本轮实测。

### 2.7 OPT-R2-20 前端死代码清理

- **目标**：删除前端确实无人引用的组件/文件，减少搜索噪声与维护面。
- **涉及文件:行**：**候选需逐项确认**。已知锚点：`ProductionEntryDialog.vue` 是"script 72 行、**0 refs、0 functions**"的薄壳（`00-synthesis.md §7` 已给出推翻式核实）；`useEventDelegation`/`useVirtualScrollList` 零消费方（见 2.6）。
- **具体改法**：以"引用计数为 0 且非路由/自动注册入口"为判据逐个确认；确认后删除。**不得**用"文件名看起来像废弃"作为判据。
- **验收标准（可命令化）**：
  - `grep -rn "<组件名>" frontend-vite/src` 无命中（除 `.d.ts` 自动生成文件——**注意**，删除后 `.d.ts` 需重新生成）；
  - `cd frontend-vite; npm run build` 通过（这是**本方案中少数需要跑前端构建的项**，但它是本项自身的验收，不是审计行为）；
  - 构建产物大小变化**记录但不作为通过条件**（未测量的性能数字不得承诺）。
- **风险与回滚**：误删会导致运行时才暴露的报错（如动态 `import()`、字符串引用）——必须靠构建 + 1 轮人工点检兜底。回滚 = git 还原。
- **预估工时**：**1.5 人日**。**依赖**：无。**批次**：批二。
- **证据来源**：`docs/audit-round2/00-synthesis.md §7`（ProductionEntryDialog.vue 实证）；`docs/audit-round2/02-frontend-architecture.md`（残片）。

### 2.8 OPT-R2-21 组件长度门禁改按 `script` 计 + `script` 重灾区拆分

- **目标**：修正门禁**测错对象**的问题——当前 `max_vue_component_length=400` 抓到的 7 个组件里 **6 个是被 CSS 撑大的**，而 script 真正超长的组件**全部低于阈值**、从未被告警。
- **涉及文件:行**：`pyproject.toml:18`（`max_vue_component_length=400`）、`pyproject.toml:13`（`[tool.code-quality]`）、`:15`（`max_function_length=80`）、`:25`（`max_file_size=1600`）；检查实现 `scripts/` 下的组件长度检查脚本（由 `pyproject.toml` 消费）
- **具体改法**：① 度量口径从"整个 `.vue` 文件"改为"仅 `<script>` 块"（或**同时**报告总长与 script 长度两个指标）；② 为 script 长度设新阈值（取值需**先测量现状分布**：把所有 `.vue` 的 script 长度排序，取合理分位——**本方案不预填数字**）；③ 对超标组件做拆分（抽 composable / 抽子组件）。
- **验收标准（可命令化）**：
  - 检查脚本输出中"script 长度"指标存在，且能列出脚本最长的前 N 个组件（排序可用 `--top 10` 之类开关）；
  - 用**旧阈值**跑一次会漏报的组件，在**新口径**下被抓出（自测反例，证明口径改变生效）；
  - `python scripts/quality_gate.py --verbose` 通过（可用基线冻结现存超标项，逐步下降）；
  - **不得**以"构建体积下降"作为验收（未测量）。
- **风险与回滚**：改口径后**告警数量会突然变化**，若新阈值过严会淹没 CI——用 `quality_gate.py` 的基线机制（`:177/:189/:205`）冻结现状再逐步收紧。回滚 = 还原 `pyproject.toml` 与检查脚本。
- **预估工时**：**2 人日**（门禁改造 0.5 + 现状测量 0.5 + 拆分 1.0，拆分只做最严重的 2–3 个组件）。**依赖**：与 **§4.2** 是同一件事的两面（§4.2 讲门禁设计，本项讲落地与拆分），**必须合并规划**。**批次**：批二。
- **证据来源**：`docs/audit-round2/00-synthesis.md §4`（"有门禁但抓错对象"）；`pyproject.toml:13/:15/:18/:25`（本轮实测）。

### 2.9 OPT-R2-22 playwright 死依赖处置

- **目标**：处置"CI 里已经删掉安装步骤、但仓库仍留有痕迹"的 playwright 残留，避免"看起来有 E2E、实际没有"的错觉。
- **涉及文件:行**：`.github/workflows/ci-cd.yml:218-224`（注释自陈：playwright install 步骤已删、仓库无 `playwright.config.*`、无 `e2e/` 目录、无 `test:e2e` 脚本）；`frontend-vite/package.json`（依赖与 scripts，如有残留）
- **具体改法**：**二选一**——① **彻底移除**：清掉 `package.json` 中的 playwright 依赖/脚本与 CI 注释；② **补齐**：写出 `playwright.config.*`、`e2e/` 目录与 `test:e2e` 脚本，并让 CI 真跑（这会显著增加 CI 时间与不稳定性，**本方案倾向 ①**）。决策与理由需落盘。
- **验收标准（可命令化）**：
  - 若选 ①：`grep -rn "playwright" .github/workflows/ frontend-vite/package.json` 无实质命中（注释同步清理）；`cd frontend-vite; npm ci` 通过；
  - 若选 ②：`npx playwright test` 在 CI 中实际执行且非 `continue-on-error`；
  - 二者都必须消除"注释里说没装、配置里却留着"的不一致状态。
- **风险与回滚**：移除依赖可能影响开发者本机已装环境（无害）；若选 ② 则引入 CI 不稳定的风险。回滚 = git 还原。
- **预估工时**：**0.5 人日**（选 ①）／**3 人日**（选 ②，含首批用例）。**依赖**：无。**批次**：批二。
- **证据来源**：`.github/workflows/ci-cd.yml:218-224`（本轮实测）；`docs/audit-round2/00-synthesis.md §4`（"有门禁但抓错对象"的同类表现）。

### 2.10 OPT-R2-23 mypy 覆盖扩容第 2 批

- **目标**：延续 OPT-13 的第 1 批（`546401ec`，覆盖 "106→110"），把覆盖率继续向"全量"推进。
- **涉及文件:行**：`mypy.ini`（142 行，**条目数 = 110**：`:33` 行内首条 `files = fastapi_app/core/security.py,` + `:34-142` 的 109 条，核对见 §7.5；`:17-20` 注释自述"services 层 156 个文件中 74 个仍有类型错误（合计 400 个 error），故仅纳入已零错误的 82 个"）；CI 步骤 `.github/workflows/ci-cd.yml:179-180`（`python -m mypy --config-file mypy.ini`）
- **✅ 数字已对齐（裁定 110）**：队长给定的权威事实为"随 `546401ec` 把 mypy 覆盖 **106→110**"；本轮初测的 "109" 是**正则漏数**——`mypy.ini:33` 的行内首条 `files = fastapi_app/core/security.py,` 未被该正则计入，`:34-142` 才是 109 条，109 + 1 = **110**，与队长数字一致（旁证 `aac4c43f:mypy.ini` = 106，`546401ec` +5 −1）。**核对命令见 §7.5**。本项**不再有待复核标注**。
- **具体改法**：第 2 批优先纳入"**已零错误但尚未进清单**"的模块（成本最低）；对仍有错误的模块，先修错误再纳入，**按模块分批**而不是一次全量（`:17-20` 说明全量会立刻产生大量错误）。
- **验收标准（可命令化）**：
  - `python -m mypy --config-file mypy.ini` 退出码 0；
  - 覆盖条目数单调不减：本次条目数 ≥ 上次（**用同一命令计数**：`(Select-String -Path mypy.ini -Pattern '^\s+[A-Za-z_][\w/]*\.py,?\s*$').Count`）；
  - 差分记录：本批新增了哪些模块、各自此前错误数。
- **风险与回滚**：纳入未清理的模块会让 CI **立刻变红**——必须"先零错误、后纳入"。回滚 = 从 `mypy.ini` 摘除新增条目。
- **预估工时**：**2 人日**/批（每批 10–15 个模块；**待复核**，取决于剩余模块的实际错误密度，见 §6.1）。**依赖**：**OPT-13**（已在做）。**批次**：批二（第 2 批），后续批次滚动。
- **证据来源**：队长给定 OPT-13 状态（**权威事实**）；`mypy.ini`（条目 **110**，已裁定，见 §7.5；`:17-20` 自述）、`.github/workflows/ci-cd.yml:179-180`。

### 2.11 OPT-R2-24 覆盖率棘轮 + 提交信息规范 + 两个检查 job

- **目标**：三项"**让已有的东西真的会拦住人**"的改造：① 覆盖率只升不降；② 提交信息与实际改动可核对；③ 文档引用与编号可机器检查。
- **涉及文件:行**：`.github/workflows/ci-cd.yml:39`（`COVERAGE_MIN: "40"`）、`:140-142`（"Check coverage threshold"，**就地 `exit(1)`**）、`:68-95`（pytest + `--cov`）、`:144`（lint job）、`:245-249`（`check:api` + `check:api:pc` + `check:routes`）
- **具体改法**：
  1. **覆盖率棘轮**：把 `:39` 的固定 `40` 改为"从某处读取上一基线的值，且不得低于它"；基线随每次通过而抬升（写入仓库文件或 CI 变量），**只升不降**。
  2. **提交信息规范**：新增一个轻量 job，检查提交信息中的数字类声明（如 "mypy 覆盖 106→110"）与仓库中对应事实是否可核对——**本次审计暴露的 106/109/110 冲突正是这类问题的实例**；最小可行版本：要求涉及门禁/清单类文件（`mypy.ini`、`pyproject.toml`、`pytest.ini`）变更时，提交信息中必须给出可复现命令（**机器可判定的部分是"是否附了命令"，不是"命令输出是否真实"**，后者仍需人看）。
  3. **文档引用检查**：利用既有的 `check:api`/`check:routes` 机制，扩展为"检查文档中引用的 `文件:行` 是否仍有效"。**注意**：`check:api`/`check:api:pc`/`check:routes` **已存在**（`:245-249`），本项是**扩展**而非新建。
- **验收标准（可命令化）**：
  - 覆盖率下降时 CI 失败（自测：人为降低覆盖率或临时抬高阈值一次，确认失败）；
  - 4 个既有检查（`check:api`/`check:api:pc`/`check:routes`+`lint`）仍绿；
  - 新增 job 在 CI 中真实执行（检查 workflow 中无 `continue-on-error`）。
- **风险与回滚**：覆盖率棘轮若基线被误抬到当前水平且某次重构降低覆盖率，会**阻塞正常提交**；需允许"明确理由下的显式降级"通道（人工 approve）。回滚 = 还原 workflow 片段。
- **预估工时**：**2.5 人日**（棘轮 1.0 + 提交规范 1.0 + 引用检查扩展 0.5）。**依赖**：与 **§4.5**（覆盖率棘轮）是同一件事，**必须合并规划**。**批次**：批二。
- **证据来源**：`docs/audit-round2/00-synthesis.md §4/§5`；`.github/workflows/ci-cd.yml:39/:68-95/:140-142/:144/:245-249`（本轮实测）。

### 2.12 OPT-R2-25 迁移命名规范 + 升级人工清单

- **目标**：让迁移目录可被人读懂、升级步骤可被复现，同时**不改变迁移链**（`OPT-14` 已完成"4 根显式收敛"，且 `docs/adr/2026-10-01-migration-roots-are-cosmetic.md` 明确不改迁移链）。
- **涉及文件:行**：`migrations/versions/`（迁移文件命名）、`migrations/alembic.ini`、`migrations/env.py:43-49`（**关键约束**：每条 alembic 命令都会对 `alembic_version` 发 DDL → **禁止为了检查而运行 alembic**）、`.github/workflows/ci-cd.yml:63-66`（CI 的 "Verify Alembic migrations" 步骤：`upgrade head` + `check`）
- **具体改法**：① 为迁移文件命名定规范（`<revision>_<短描述>.py`，短描述用动词+对象）；② 写一份"人工升级清单"：列出升级前必须确认的事项（备份已完成、维护窗口、`downgrade` 可用、影响表与预估锁时长）；③ **离线核对**迁移链：用 `alembic -c migrations/alembic.ini upgrade head --sql` **仅生成 SQL 文本**（**注意**：该命令本身也可能触发 `env.py` 的 DDL 路径——**必须先静态确认 `env.py:43-49` 在 `--sql` 模式下不发 DDL**，否则改用纯静态解析迁移链；**存疑则不跑**）。
- **验收标准（可命令化）**：
  - `migrations/versions/` 中新增文件命名符合规范（可用 `grep -c` 或脚本核对）；
  - 人工升级清单落盘且包含"备份确认 / 窗口 / 回滚方式 / 影响表"四项；
  - 迁移链静态可解析：纯静态读取 `down_revision` 字段能拼出唯一链（**不执行 alembic**）。
- **风险与回滚**：重命名**已存在**的迁移文件会改变 `alembic_version` 的对应关系（虽然文件名一般不影响 revision id，但**不得重命名已应用过的迁移文件**）——规范**只对新增文件生效**。回滚 = 还原命名。
- **预估工时**：**1 人日**。**依赖**：**OPT-14**（已完成，本项目不重复其内容）。**批次**：批二。
- **证据来源**：`docs/audit-round2/00-synthesis.md §5`；`migrations/env.py:43-49`、`.github/workflows/ci-cd.yml:63-66`（本轮实测）。

### 2.13 OPT-R2-26 前端依赖 pin + `npm ci` + `dist` 清理

- **目标**：让前端构建可复现：锁定依赖版本（不使用 `^` 浮动范围）、确保 CI 用 `npm ci` 而不是 `npm install`、并清理不应入库的 `dist`。
- **涉及文件:行**：`frontend-vite/package.json`（**43 个依赖全部使用 `^` 范围**，见 `00-synthesis.md` "未验证"表）；`.github/workflows/ci-cd.yml:197-226`（frontend job，`:216` 已是 `npm ci`）、`:239-240`（`npm run build`）；`frontend-vite/dist/`（若已入库）
- **具体改法**：① 把 43 个依赖的 `^` 改为精确版本（或改用 `overrides`/`resolutions` 策略，**取哪条需决策**）；② 确认 CI 使用 `npm ci`（`:216` 已满足）且 `package-lock.json` 被跟踪；③ 若 `dist` 入库则加 `.gitignore` 并移出版本控制。
- **验收标准（可命令化）**：
  - `grep -c '"\^' frontend-vite/package.json` 显著下降（目标 0，或对明确允许浮动的项留白并说明）；
  - `git ls-files frontend-vite/dist | Measure-Object` 为空（若曾入库）；
  - `cd frontend-vite; npm ci; npm run build` 通过；
  - `git ls-files frontend-vite/package-lock.json` 非空。
- **风险与回滚**：pin 之后**安全更新不再自动进入**，需要有人定期升级——建议同时建立"依赖巡检"提醒（否则 pin 会变成"长期落后"）。回滚 = 还原 `package.json`。
- **预估工时**：**1 人日**。**依赖**：与 **§4.4** 是同一件事，**必须合并规划**。**批次**：批二。
- **证据来源**：`docs/audit-round2/00-synthesis.md`（"未验证"表第 11 项：前端 43 依赖全 `^`）；`.github/workflows/ci-cd.yml:197-226/:239-240`（本轮实测）。

### 2.14 沿用编号的续做项（批二）

> 这四/三项**不新增编号**，直接沿用既有 OPT 编号。它们之所以在批二而非批一，是因为需要"重启服务"或"设计决策"，成本高于批一的零风险小改。

#### 2.14.1 OPT-08（续）生产 Python venv 隔离收尾

- **目标**：把 `erp-prod` 与 `erp-arq` 两个 NSSM 服务从全局 `Python313\python.EXE` 切到已建好的 `.venv`，闭合 OPT-08。
- **现状（队长权威事实）**：**只建了 `.venv`，未改 NSSM**；两个服务仍指向全局 `Python313\python.EXE`。
- **涉及文件:行**：NSSM 服务配置（**服务配置在外，需运维侧确认参数名**）、已建 `.venv` 路径、`scripts/restart_backend.py`（重启脚本，见 1.11）
- **具体改法**：逐个改 `erp-prod`、`erp-arq` 服务的可执行路径与参数为 `.venv\Scripts\python.exe`（及 `.venv` 下的 uvicorn/arq 入口）；**逐个切换**（先 arq 后 prod 或反之），每切一个验证一个。
- **验收标准（可命令化）**：`nssm get erp-prod Application` 与 `nssm get erp-arq Application` 输出指向 `.venv`；服务重启后接口正常（`curl` 健康检查 + 1 条业务冒烟）；`pip list`（在服务进程解释器下）与 `requirements/base.txt` 一致。
- **风险与回滚**：**切错解释器会让服务起不来**——必须在维护窗口做，且保留原命令字符串（回滚 = `nssm set` 回原值并重启）。
- **预估工时**：**1 人日**（含窗口与验证）。**依赖**：无（`.venv` 已建）。**批次**：批二。
- **证据来源**：队长给定 OPT-08 状态（**权威事实**）。

#### 2.14.2 OPT-09（续）`useApiMutation` 推广收尾

- **目标**：把写操作统一走 `useApiMutation` 的推广继续做完（试点 + 推广①②已完成）。
- **现状修正（**重要**）**：原方案度量"useApiMutation 仅 4 处"**已过时**；本轮实测 **30 处命中、跨 8 个文件**：定义 `frontend-vite/src/composables/useApiMutation.ts:23`；消费点 `useUserManagement.ts:13/70/83/277`、`OutsourcePresetTab.vue:85/179`、`useSupplier.ts:11/75/94/107/142`、`OutsourceAddProcessDialog.vue:49/81/95`、`CustomerView.vue:54`、`useCustomer.ts:11/90/95/100/104/126`、`useStockinEdit.ts:13/18/63/95`、`useCaseRecordActions.ts:8/46/81/110`（**共 7 个消费模块 + 1 个定义文件**）。
- **具体改法**：按模块剩余的手写写操作逐处替换为 `useApiMutation`；**并在此项中同时接入 §2.1 所需的前端幂等键传递**（两件事都改前端写路径，合并做避免二次开file）。
- **验收标准（可命令化）**：
  - 手写写请求数量单调下降（同一命令计数：`grep -rn "axios\.\(post\|put\|patch\|delete\)\|fetch(" frontend-vite/src/composables frontend-vite/src/views`）；
  - `cd frontend-vite; npm run lint; npx vitest run` 通过；
  - 每个被替换模块有 1 条人工冒烟记录（写操作成功 + 失败提示正常）。
- **风险与回滚**：替换会改变错误提示与 loading 语义，需逐个回归。回滚 = 按模块还原。
- **预估工时**：**3 人日**。**依赖**：**OPT-R2-14**（幂等层）需要前端配合，建议**同时或紧随**。**批次**：批二。
- **证据来源**：队长给定 OPT-09 状态（**权威事实**）+ 本轮实测的 30 处/8 文件锚点；`frontend-vite/src/composables/useApiMutation.ts:23`。

#### 2.14.3 OPT-21（续）fastapi 0.137.1 → 0.142.2 升级

- **目标**：把 `fastapi` 从 `0.137.1` 升级到 `0.142.2`，消除已知问题与版本落后。
- **涉及文件:行**：`requirements/base.txt:7`（`fastapi==0.137.1`）；连带 `pydantic`/`starlette` 的兼容约束（`requirements/base.txt`）
- **具体改法**：在 `.venv` 中先升级、跑 CI 口径测试，通过后再落 `requirements/base.txt`；**必须与 OPT-08（续）配合**——否则升级只影响开发环境，"生产实际运行的还是老版本"。
- **验收标准（可命令化）**：`python -c "import fastapi; print(fastapi.__version__)"` 输出 `0.142.2`；`pytest` CI 口径 0 failed；`python -m mypy --config-file mypy.ini` 不新增错误；`pip check` 无冲突。
- **风险与回滚**：跨多个小版本升级可能带来**依赖树冲突与行为变更**（尤其 pydantic v2 相关）。先在测试环境全量跑；回滚 = 还原 `requirements/base.txt` 并重装。
- **预估工时**：**1.5 人日**。**依赖**：**OPT-08（续）**（2.14.1）——顺序上建议 venv 隔离先完成。**批次**：批二。
- **证据来源**：队长给定 OPT-21 状态（**权威事实**）；`requirements/base.txt:7`。

#### 2.14.4 OPT-18（续）nginx `limit_req`

- **目标**：在反向代理层加限流，与应用层限流（OPT-R2-08）形成两层。
- **涉及文件:行**：nginx 配置（**在仓库外或部署侧，需运维确认落点**）；对照 `scripts/restart_backend.py:68`（`--forwarded-allow-ips=*`，与真实 IP 还原冲突）
- **具体改法**：配置 `limit_req_zone` + `limit_req`，并同时配置 `real_ip` 使真实客户端 IP 可还原（**这一步与 OPT-R2-08/OPT-R2-13 的"取客户端 IP"是同一问题**，必须一起设计）。
- **验收标准（可命令化）**：`nginx -T | findstr limit_req` 命中；压测/手工连发超过阈值时返回 429（**记录触发阈值与响应，但不承诺任何吞吐数字**）；应用层限流键与之语义一致（抽 3 条日志对照）。
- **风险与回滚**：限流阈值设错会**误伤正常用户**——先在低阈值观察（log-only 模式）再启用。回滚 = 还原 nginx 配置并 `reload`。
- **预估工时**：**1 人日**。**依赖**：**OPT-17**（内网 TLS，§3.9）非硬依赖，但与 **OPT-R2-08** 强耦合。**批次**：批二。
- **证据来源**：队长给定 OPT-18 状态（**权威事实·未做**）；`scripts/restart_backend.py:66/:68`。

### 2.15 批二小结

- **项数**：**18 项** = 新增 14 项（OPT-R2-14 ～ OPT-R2-26 + §4.1 的 **OPT-R2-37**）+ 沿用编号 4 项（OPT-08 续 / OPT-09 续 / OPT-18 续 / OPT-21 续）。其中 3 项（OPT-R2-21/24/26）与 §4 门禁改造**共享工时，本节只计一次**（明细见 §7）。
- **工时**：**31.0 人日**（18 项明细合计 33.5 = 32.0 + §4.1 的 1.5，扣除与 §4 共享的 2.5）。其中 **3.0 人日**属**待复核**（OPT-R2-14 的 4 中约 3 待定 + OPT-R2-15 的 3 中 1～2 待定 + OPT-R2-16 的 3 中 1～2 待定 + OPT-R2-23 的批次浮动 —— 明细见 §6.1/§7）。
- **批二完成定义（DoD）**：① 4 个"需先重建清单"项中至少 2 个（索引、关系加载）的清单已落盘且清单条目数与迁移/改动数可核对；② OPT-08 续完成（NSSM 已切）——它决定了 OPT-21 续是否真的生效；③ 三处门禁口径修正（组件长度、覆盖率棘轮、依赖 pin）在 CI 中可验证；④ mypy 覆盖条目数**单调不减**且新数字有可复现命令。
- **证据来源**：批二排序取自 `docs/audit-round2/00-synthesis.md §5`（批二 10 条）；项拆分与工时为本方案新增。

---

## 3. 批三 · 6–12 周（P2）

> **口径**：批三 = **6–12 周**，都是"需要设计决策或跨模块协调"的结构性工作。本节共 **8 个新增项（OPT-R2-27 ～ OPT-R2-34）+ 3 个沿用编号项（OPT-17 续、OPT-19 续、OPT-05 确认）**，合计 **39.0 人日**（见 §7）。
> **为什么不能提前**：这些项**都不是"修 bug"**，而是"改形状"——改形状需要先把批一/批二的清单建起来（否则改的对象本身是未知的），且每一次改动都会牵连多个调用方。

### 3.1 OPT-R2-28 分层收尾（循环依赖 / 包聚合环 / `core` 反向依赖）

- **目标**：消除模块分层上的"反向与环形依赖"，让"谁可以 import 谁"从约定变成可检查的事实。
- **涉及文件:行**：`fastapi_app/` 的包顶层（`api` / `services` / `core` / `shared_models`）；具体环的清单需**当场用静态工具产出**——`00-synthesis.md` 指出存在该问题但未给出机器可生成的全量环清单，因此本项**先产出清单再动手**。
- **具体改法**：① 用静态分析产出"包依赖图 + 环"（可用标准库 `ast` 自写脚本，或用 `pydeps`/`import-linter`；**是否引入新依赖需决策**）；② 针对每个环选择"下沉公共部分"或"引入接口/协议"解决（**不得**简单放宽 import 规则了事）；③ 把依赖规则写进 CI（`import-linter` 的 contracts 或自写检查），防止回流。
- **验收标准（可命令化）**：
  - 环清单落盘（文件 + 边的列表），修复前后条目数可对比；
  - 规则检查命令可在 CI 跑且退出码 0（例：`python -m importlinter` 或自写 `python scripts/check_layers.py`）；
  - `python -m mypy --config-file mypy.ini` 不新增错误。
- **风险与回滚**：拆分公共模块会**大面积改动 import 路径**，冲突率高（多人同时改时尤其明显）。建议**在低冲突窗口一次性做完一个环**，不要跨周悬挂。回滚 = 按环还原（因此"一个环一个提交"很重要）。
- **预估工时**：**5 人日**（清单 1 + 环修复 3 + CI 规则 1）。**依赖**：**OPT-R2-16**（2.3，关系加载）建议在前——两者都动 `services` 层，合并可省二次改动。**批次**：批三。
- **证据来源**：`docs/audit-round2/00-synthesis.md §4`；`docs/audit-round2/01-backend-structure.md`（结构分析，完整）。

### 3.2 OPT-R2-29 公司/本位币收敛为配置项

- **目标**：把"单公司/单币种"从**隐含假设**变成**显式配置**——现在它写死在代码各处的字面值/默认值里，导致未来若要多公司必须全库改；这一项**不改业务语义**，只把假设显性化并集中到一处。
- **涉及文件:行**：**实测 0 命中，这本身是关键证据**——`company_id` / `tenant_id` / `multi_company` 在 `fastapi_app` 与 `migrations` 下**均 0 命中**；词边界 `currency` 在 `schemas` / `shared_models` / `migrations` 下**均 0 命中**（本轮当场实测复核）。这意味着**当前没有多公司抽象**，公司/币种以字面值出现在业务逻辑与展示层。
- **具体改法**：① 整理出一个"默认公司 / 默认本位币"的**单一配置入口**（`fastapi_app/core/config.py` + `.env`）；② 把散落的字面值改为引用该配置（**分批做**，每批一个模块，避免一次性全库改动）；③ **不引入**多公司数据模型（那是 §5 不做清单里的项）。
- **验收标准（可命令化）**：
  - 配置键存在且被消费：`grep -rn "DEFAULT_COMPANY\|BASE_CURRENCY" fastapi_app/ --include=*.py` 有"声明 + 消费"两侧命中；
  - 收敛进度可核对：改造前后字面值出现次数下降（同一 `grep` 命令计数，**先记录基线再对比**）；
  - 业务回归：至少 10 条主流程手测（下单/入库/出库/退料/盘点等）结果与改造前一致。
- **风险与回滚**：**这是"看似无害、实则易错"的一项**——字面值替换若漏改一处，会造成"某个报表用的是旧公司/旧币种"的静默不一致。必须逐处对照，且**必须有回归用例**。回滚 = 按模块还原。
- **预估工时**：**6 人日**（配置入口 1 + 分批替换 4 + 回归 1）。**依赖**：**OPT-R2-28**（3.1）建议在前（分层清晰后替换更安全）。**批次**：批三。
- **证据来源**：`docs/audit-round2/00-synthesis.md §2`（单公司/单币种不变量当场实测 0 命中）；`docs/audit-round2/00-synthesis.md §4`。

### 3.3 OPT-R2-30 记录级权限最小切片

- **目标**：把**已经写好但从未被调用**的记录级权限依赖接入至少一个真实场景，证明该能力可用；**不做全量接入**。
- **涉及文件:行**：`fastapi_app/core/deps.py:363`（`resolve_production_view_scope`）、`:383`（`resolve_production_write_scope`）；对照 `fastapi_app/core/deps.py:279`（`def require_permission(permission_name)`）与 `:195`（缓存短路）
- **具体改法**：① 先确认两个函数的语义（返回值形态、与 `require_permission` 的关系）——**这是本项的第一步，未确认前不写调用代码**；② 选 **1 个**读接口 + **1 个**写接口接入，作为最小切片；③ 记录"若全量接入需要改多少处"的估算（**只估算，不实施**）。
- **验收标准（可命令化）**：
  - `grep -n "resolve_production_view_scope\|resolve_production_write_scope" fastapi_app` 从"仅定义处"变为"定义 + 调用点"；
  - 越权用例：不同范围内的账号访问同一接口，返回数据集合不同（**需新增集成测试**）；
  - 全量接入估算落盘（处数 + 人日区间）。
- **风险与回滚**：范围过滤写错会导致**看到不该看的数据**或**看不到该看的数据**（后者更易被发现）。先在 1 个低频接口验证。回滚 = 摘掉 2 处调用。
- **预估工时**：**2 人日**（语义确认 0.5 + 2 处接入 1 + 估算与测试 0.5）。**依赖**：无硬依赖；与 **OPT-R2-06**（1.7，权限点补齐）同属权限体系，建议其之后做。**批次**：批三。
- **证据来源**：`docs/audit-round2/00-synthesis.md §4`（"记录级权限依赖已写未接"）；`fastapi_app/core/deps.py:279/:195/:363/:383`（本轮实测）。

### 3.4 OPT-R2-31 扩展点清单 + 覆盖层规范

- **目标**：建立"**哪些地方允许被客户化/覆盖**"的清单与规范——当前仓库没有扩展点声明（`entry_point` / `plugin` 在 `pyproject.toml` 中 **0 命中**，本轮实测），意味着任何客制化都只能改主代码。
- **涉及文件:行**：`pyproject.toml`（**实测 `entry_point`/`plugin` 0 命中**）；应用装配处 `fastapi_app/main.py`；配置 `fastapi_app/core/config.py`
- **具体改法**：① 盘点"现实中已被客制化过的地方"（从 git 历史与部署差异反推，**这是调查动作**）；② 从中选出 3–5 个高价值点，定义成显式扩展点（配置开关 / 子类覆盖 / 独立模块注册）；③ 写一份"覆盖层规范"：说明扩展点位置、覆盖方式、升级兼容要求。**不引入插件框架**（见 §5 不做清单）。
- **验收标准（可命令化）**：
  - 扩展点清单落盘，每条含"位置 文件:行 + 覆盖方式 + 示例"；
  - 至少 1 个扩展点有可运行的示例实现（小 demo，不进入主流程）；
  - `grep -rn "extension" pyproject.toml` 是否引入 `entry_point` **由决策决定**；若引入需给出理由。
- **风险与回滚**：设计扩展点容易**过度抽象**（为将来不存在的客户做框架）。约束：**只对已发生的客制化建扩展点**。回滚 = 删除新增文档与示例（不影响主流程）。
- **预估工时**：**4 人日**。**依赖**：**OPT-R2-28**（3.1，分层清晰才好定扩展点）。**批次**：批三。
- **证据来源**：`docs/audit-round2/00-synthesis.md §2`（`entry_point`/`plugin` 0 命中实测）；`docs/audit-round2/06-oss-erp-benchmark.md`（开源对照中的 Top5 可借鉴）。

### 3.5 OPT-R2-32 可观测性落地

- **目标**：把 `/metrics` 与健康检查从"存在"做到"可用且有界限"——包括关键业务指标、fail-closed 语义确认、以及 OPT-16 降级后遗留的只读副本议题的收尾。
- **涉及文件:行**：`fastapi_app/api/v1/endpoints/health.py:200-214`（`/metrics` fail-closed，t1 归档者已复核）；与 §1 新增的 `db_commit_failures_total` 计数器（1.2）汇合；OPT-16 降为调查项 16a 与"只读副本依赖已写未用"；`fastapi_app/api/ws.py:33-41`（票据常量与内存字典）、`:61-76`（同时写 Redis 且 miss 回退）——OPT-20 残余项
- **具体改法**：① 定义一小组**业务级**指标（如"每日写入失败次数""备份成功/失败""队列积压"），而不是只暴露技术指标；② 确认 `/metrics` 的 fail-closed 行为符合预期（不可用时**拒绝**而不是返回空）；③ 对"只读副本依赖已写未用"给出结论：接入或删除（**沿用 OPT-16 的降级决定，不再重新讨论是否部署只读副本**）。
- **验收标准（可命令化）**：
  - `curl -s localhost:8000/metrics` 输出包含新定义的业务指标名（列出指标清单与之对照）；
  - fail-closed 行为可复现（停掉依赖后 `/metrics` 的响应符合设计，1 次实验）；
  - "只读副本依赖"处置结论落盘（接入 / 删除 + 理由）。
- **风险与回滚**：暴露新指标可能带出**敏感信息**（如把 SQL 或连接串放进 label）——指标设计必须过一遍信息面审查（与 1.14.1 同源）。回滚 = 移除指标。
- **预估工时**：**3 人日**。**依赖**：**OPT-R2-01**（1.2 的计数器是本项输入）。**批次**：批三。
- **证据来源**：`docs/audit-round2/00-synthesis.md §4`（"只读副本依赖已写未用"）；`docs/audit-round2/05-ops-security-observability.md`；`docs/audit-round2/00-synthesis.md §8.4`（OPT-16/20 降级事实）。

### 3.6 OPT-R2-33 前端 `script` 体积治理（CSS 外置 + 超大 `.ts` 拆分）

- **目标**：治理"组件长在 CSS 上、script 与巨型 `.ts` 无人管"的错位——与 §2.8（门禁口径）配套，本项是**实际拆分工作**。
- **涉及文件:行**：由 §2.8 的测量结果决定（**先测量排序，再选对象**）；已知背景：`max_vue_component_length=400` 抓到的 7 个组件中 **6 个是被 CSS 撑大的**，而 script 重灾区**全部低于阈值**（`00-synthesis.md §4`）；`pyproject.toml:25`（`max_file_size=1600`）会约束超大 `.ts`
- **具体改法**：① 把大组件的样式外置到独立样式文件/原子类（降低"总长"这个被误测的指标）；② 把超大 `.ts`（`max_file_size=1600` 附近/超过者）按职责拆分；③ 每拆一个，确认无行为变化。
- **验收标准（可命令化）**：
  - §2.8 的新口径测量输出中，`script` 长度与文件长度的 Top N 列表前后可对比（**只报可测量的长度，不报构建体积**）；
  - `cd frontend-vite; npm run lint; npx vitest run; npm run build` 通过；
  - `python scripts/file_size_gate.py --all`（CI 中 :182-195 的检查）通过。
- **风险与回滚**：外置 CSS 可能改变**样式优先级与作用域**（尤其是 `scoped` 与深度选择器），容易出视觉回归——需人工点检关键页面。回滚 = 单文件还原。
- **预估工时**：**4 人日**（只做最严重的 3–5 个文件，**不做全量**）。**依赖**：**OPT-R2-21**（2.8）——门禁口径先改，否则治理与否无法度量。**批次**：批三。
- **证据来源**：`docs/audit-round2/00-synthesis.md §4`（"6/7 由 CSS 撑大"）；`pyproject.toml:18/:25`（本轮实测）。

### 3.7 OPT-R2-34 测试双树语义治理

- **目标**：给"两棵测试树"（`tests/` 与 `fastapi_app/tests/`）定下**明确分工并写进文档与门禁**，消除"为什么有两棵树"的长期疑问。
- **关键前提（已由 t2 实证，不得再按旧结论行事）**：两棵树**不是重复测试**——`pytest.ini:3` 的 `testpaths = tests fastapi_app/tests` 明确同时收集；本轮实测 `tests` 148（全部 `.py`）/`110`（`test_*.py`），`fastapi_app/tests` 163/161；收集用例 **3689**；同名 basename 交集 **13**，其中 **11 对 md5 全 DIFF**；**同节点仅 1/3688 ≈ 0.03%**；**真正的重复是 `conftest` 571 行 vs 232 行**。
- **涉及文件:行**：`pytest.ini:3`（`testpaths`）、`tests/` 与 `fastapi_app/tests/` 两棵树的 `conftest.py`（571 行 / 232 行）、`.github/workflows/ci-cd.yml:68-95`（同时跑两棵树，并 `--ignore` `tests/qa`、`tests/e2e`、`tests/stress`、`tests/performance`）
- **具体改法**：① 定分工（建议：`tests/` = 跨模块/端到端与 QA 类；`fastapi_app/tests/` = 模块内单测），写进 `docs`；② 合并 `conftest` 的公共部分（**真重复在这里**，而不是在测试用例上）；③ 对 `--ignore` 的四个目录明确"这些测试谁来跑、什么时候跑"（**当前它们不进门禁**，等于长期不跑）。
- **验收标准（可命令化）**：
  - 分工文档落盘，且与 `pytest.ini:3` 的实际收集范围一致；
  - `conftest` 公共部分抽取后，两树 `conftest` 行数下降且 `pytest --collect-only -q` **收集数不减少**（3689 为改造前基线，**可核对**）；
  - CI 口径测试 0 failed。
- **风险与回滚**：改 `conftest` 会**全局影响 fixture 可见性**，可能一次弄红大量用例——必须小步做（先抽一个 fixture）。回滚 = 还原 `conftest`。
- **预估工时**：**3 人日**。**依赖**：**OPT-02（续）**（1.15，先全绿再动 fixture）**强依赖**——在测试不全绿时重构 `conftest` 会分不清"谁弄红的"。**批次**：批三。
- **证据来源**：`docs/audit-round2/00-synthesis.md §7`（两处修正，含上述全部实测数字）；`pytest.ini:3`、`.github/workflows/ci-cd.yml:68-95`（本轮实测）。

### 3.8 OPT-R2-27 字段级 API 契约对齐

- **目标**：让"前端认为的字段"与"后端实际返回的字段"有**机器可核对的契约**，而不是靠对齐人肉记忆。
- **涉及文件:行**：**已有基础**——CI 中 `.github/workflows/ci-cd.yml:245-249` 已存在 `check:api` + `check:api:pc` + `check:routes` 三个检查（**本项是扩展，不是从零建**）；后端响应模型在 `fastapi_app/schemas/`；前端类型在 `frontend-vite/src/`
- **具体改法**：① 先摸清三个既有检查**已经覆盖到什么粒度**（路由级？字段级？）——**这一步不做完不设计新工具**；② 若已有字段级基础，则补齐缺口；若只有路由级，则从 OpenAPI schema 生成前端类型（FastAPI 自带 `/openapi.json`）并与前端声明的类型做 diff；③ 把 diff 接进 CI。
- **验收标准（可命令化）**：
  - 工具命令可在 CI 跑且退出码 0（例：`cd frontend-vite; npm run check:api` 已有，扩展后可新增 `check:api:fields`）；
  - 反例测试：故意改一个后端字段名，工具应报错（**自测一次**）；
  - 覆盖度声明落盘：哪些模块已字段级对齐、哪些还未（**不夸大覆盖范围**）。
- **风险与回滚**：字段级 diff 会**立刻暴露大量历史不一致**，一次性修复不现实——必须分批并把未对齐模块列白名单（与 `quality_gate` 基线机制同理）。回滚 = 摘掉 CI 步骤。
- **预估工时**：**4 人日**。**依赖**：**OPT-R2-18**（2.5，统一错误信封）建议在前——信封统一后契约面更窄。**批次**：批三。
- **证据来源**：`docs/audit-round2/00-synthesis.md §5`（批三）；`.github/workflows/ci-cd.yml:245-249`（本轮实测，确认三检查已存在）。

### 3.9 沿用编号的续做项（批三）

#### 3.9.1 OPT-17（续）内网 TLS

- **目标**：内网流量加密，闭合 OPT-17（**未做**）。
- **涉及文件:行**：nginx 配置（部署侧/仓库外，需运维确认）；证书签发与轮换流程（**当前不存在，需新建**）
- **具体改法**：签发内网 CA 或使用内网可用的证书（**方式需决策**），配置 nginx 监听 443 并重定向 80；建立证书到期提醒（否则一年后集体不可用）。**必须处理"客户端信任"问题**：内网自签 CA 需要在所有访问终端安装根证书，否则浏览器报错——**这一步的工作量常被低估，须先统计终端数量**。
- **验收标准（可命令化）**：`curl -v https://<host>/` 握手成功且证书链可验证；HTTP 强制跳转 HTTPS；证书到期提醒存在（计划任务或监控项，可列出）。
- **风险与回滚**：**切换 TLS 是一次性全局动作**，若终端未装根证书会立刻大面积不可用；必须先统计并试点。回滚 = nginx 恢复同时监听 80 并保留旧配置。
- **预估工时**：**4 人日**（含证书流程 1 + nginx 1 + 终端铺开 2，**终端数量未知，属待复核**——见 §6.1）。**依赖**：无；是 **OPT-18（续）** 的相邻项。**批次**：批三。
- **证据来源**：队长给定 OPT-17 状态（**权威事实·未做**）。

#### 3.9.2 OPT-19（续）`uploads` 免鉴权直出改造

- **目标**：让上传目录不再被静态直出（或被直出时带鉴权/时效控制），闭合 OPT-19（**未做**）。
- **涉及文件:行**：静态文件挂载处（`fastapi_app/main.py` 中的 `StaticFiles` 挂载，**需确认具体行**）、上传落盘目录 `uploads/`
- **具体改法**：**二选一**——① 改由应用路由提供文件（带权限校验）；② 保留静态直出但改用**带时效签名的 URL**（签名由后端生成）。选 ① 更简单但增加应用负载；选 ② 需前端配合改造。**决策必须落盘**。
- **验收标准（可命令化）**：未授权请求该 URL 应返回 403/404（**需新增测试**）；已授权路径正常返回文件；`grep -rn "StaticFiles" fastapi_app/main.py` 确认改造后行为与决策一致。
- **风险与回滚**：改动会影响**所有**已存在的文件链接（包括历史数据中存储的 URL）——必须评估"旧 URL 是否会失效"，可能需要重定向层。回滚 = 恢复静态挂载。
- **预估工时**：**3 人日**（**待复核**：取决于历史 URL 数量，见 §6.1）。**依赖**：**OPT-R2-06**（1.7）同属权限体系。**批次**：批三。
- **证据来源**：队长给定 OPT-19 状态（**权威事实·未做**）。

#### 3.9.3 OPT-05（续）git-bash `_lc` 劫持复现确认

- **目标**：对"不可核验"的 OPT-05 给出**明确结论**（复现成功 → 修复；复现失败 → 关闭并注明原因），不再让它以"不可核验"状态长期悬挂。
- **现状（队长权威事实）**：**不可核验**——工件在仓库外。
- **涉及文件:行**：无仓库内落点（**这正是它"不可核验"的原因**）；确认所需环境为 git-bash + 特定 shell 初始化路径（**人工复现**）
- **具体改法**：在**真实的 git-bash 环境**（而非 PowerShell）按原描述步骤复现；记录 shell 版本、`_lc` 定义来源、是否劫持成功；据此决定修复方案（可能在仓库外的 git 配置或 shell 初始化文件里）或关闭该项。
- **验收标准（可命令化）**：一份复现记录（环境版本 + 命令 + 输出 + 结论）落盘，结论二选一且非"仍不可核验"。
- **风险与回滚**：纯确认动作，无风险。
- **预估工时**：**1 人日**。**依赖**：无。**批次**：批三（也可以随时插空做——成本低）。
- **证据来源**：队长给定 OPT-05 状态（**权威事实·不可核验**）。

### 3.10 批三小结

- **项数**：**11 项** = 新增 8 项（OPT-R2-27 ～ OPT-R2-34）+ 沿用编号 3 项（OPT-17 续 / OPT-19 续 / OPT-05 续）。
- **工时**：**39.0 人日**（11 项明细合计，无共享扣减）。其中 **3.0 人日**属**待复核**（OPT-17 续的终端铺开 2 + OPT-19 续的历史 URL 1 + 其余浮动 —— 明细见 §6.1/§7）。
- **批三完成定义（DoD）**：① 分层依赖规则进 CI 且环数为 0（或有明确豁免清单）；② 三个"已写未接/已写未用"的能力（记录级权限、只读副本、通用前端能力）**各自有明确结论**（接入或删除），不再悬挂；③ 双树分工文档落盘且 `conftest` 重复已消除；④ 契约对齐工具在 CI 中能对至少 1 个字段级不一致报错。
- **与批一批二的边界**：批三**不含任何"上线前必修"内容**——批一的 DoD（§1.17）不依赖批三任何项。

> **关于 OPT-15 / OPT-16 / OPT-20（关闭或降级项）**：三项**不再作为待办项列出**，其事实与残余已分别并入 —— OPT-15（前提不成立，echarts 动态 import 已存在）→ 无残余；OPT-16（降为调查 16a）→ 残余并入 **§3.5 OPT-R2-32**；OPT-20（大半不成立，佐证 `fastapi_app/api/ws.py:33-41` 票据常量与内存字典、`:61-76` 同时写 Redis 且 miss 回退）→ 残余并入 **§3.5 OPT-R2-32**。
- **证据来源**：批三排序取自 `docs/audit-round2/00-synthesis.md §5`（批三 7 条）；项拆分与工时为本方案新增。

---

## 4. 门禁与度量改造

> **为什么单列一节**：本轮审计的核心判断之一是"**有门禁但抓错对象**"。这一节不是新功能，而是**修正既有门禁的度量口径**——它决定了批一/批二/批三的其他项能否被持续守住。**§4.2/§4.4/§4.5 与 §2 的 OPT-R2-21/24/26 是同一件事的两面，工时只在 §2 计一次**；**§4.3 对应批三的 OPT-R2-27**；**§4.1 在 §2 无对应条目——本轮修订单列为批二新增项 OPT-R2-37（1.5 人日），已计入 §7.1/7.2 的总数与项数**。

### 4.1 `quality_gate` 纳入 ruff / mypy / pytest

- **现状（本轮实测）**：`.github/workflows/ci-cd.yml` 中三者**各自是独立步骤**——`:168-169` `scan_secrets.py`、`:173-174` `quality_gate.py --verbose`、`:176-177` `ruff check fastapi_app tests fastapi_app/tests utils`、`:179-180` `python -m mypy --config-file mypy.ini`、`:68-95` pytest、`:144` lint job。`scripts/quality_gate.py` 自带基线机制（`:177 load_baseline` / `:189 save_baseline` / `:205 --update-baseline` / `:242 比较` / `:271 提示收紧`）。
- **关键发现（本次审计的实证）**：**`:176-177` 的 ruff 范围是 `fastapi_app tests fastapi_app/tests utils`——不含 `server_manager/` 与 `scripts/`**。而本地 `ruff check .` 有 70 条错误，其中 **55 条落在 `server_manager/` 与 `scripts/`**。也就是说：**这 55 条永远不会拦住任何提交**。这不是"ruff 没配好"，而是"ruff 的检查范围比人以为的窄"。
- **具体改法**：① 让 `quality_gate.py` 成为**唯一的门禁聚合入口**（ruff + mypy + pytest 的结论汇入同一份基线/报告），而不是靠 CI 步骤顺序；② **扩大 ruff 范围**到全仓（含 `server_manager/`、`scripts/`），但**先冻结现存 55 条为基线**，之后只降不升（避免一次全红）；③ `quality_gate.py` 的输出明确列出"哪些检查被跳过、为什么"——本轮审计暴露的问题正是"看 CI 绿了以为都过了"。
- **验收标准（可命令化）**：
  - `python scripts/quality_gate.py --verbose` 输出中同时出现 ruff、mypy、pytest 三者的结论行（或"skipped + 原因"）；
  - `ruff check .` 与 CI 中的 ruff 范围**一致**（用同一命令可复现：`ruff check fastapi_app tests fastapi_app/tests utils server_manager scripts`）；
  - 基线文件存在且记录了当前数量（`:189` 的 `save_baseline`）；
  - 反例自测：故意引入 1 条 ruff 错误，`quality_gate.py` 必须失败。
- **风险与回滚**：扩大范围后**首次提交会被 55 条历史错误拦住**——必须用基线冻结（否则团队会立刻绕过门禁，比不改更糟）。回滚 = 还原 workflow 与 `quality_gate.py`。
- **预估工时**：**1.5 人日**。**依赖**：`scripts/quality_gate.py`（已有基线机制，`:177/:189/:205`）；与 §1.13 的 **OPT-R2-11** 同源，建议一并设计。**批次**：**批二**（入账项号 **OPT-R2-37**，见 §7.1/7.2 与附录）。
- **证据来源**：`.github/workflows/ci-cd.yml:168-174/:176-180/:144`（本轮实测）；`scripts/quality_gate.py:11-13/:177/:189/:205/:242/:271`（本轮实测）；`docs/audit-round2/00-synthesis.md §4`（"ruff 70 条里 55 条在 server_manager+scripts"）。

### 4.2 组件长度改按 `script` 计

- **现状（本轮实测）**：`pyproject.toml:18` `max_vue_component_length=400`；配套 `:15` `max_function_length=80`、`:25` `max_file_size=1600`、`:13` `[tool.code-quality]`。
- **关键发现**：`max_vue_component_length=400` 抓到的 7 个组件里 **6 个是被 CSS 撑大的**；而 `script` 真正超长的组件**全部低于阈值、从未被告警**。**度量对象错了**——它测的是"文件行数"，而维护性取决于"逻辑行数"。
- **具体改法**：① 度量口径改为 **`<script>` 块长度**（可同时保留"总长"作为次要指标，但**二者不得混用同一阈值**）；② 新阈值由**现状分布**决定（先测量所有 `.vue` 的 script 长度并排序，取合理分位——**本方案不预填数字**）；③ 检查脚本输出 Top N 便于定位。
- **验收标准（可命令化）**：
  - 检查脚本能输出"script 长度排行"（例：`--top 10`）；
  - **反例自测**：一个"总长 < 400 但 script 很长"的组件，在旧口径下**不报警**、在新口径下**报警**；
  - `python scripts/quality_gate.py --verbose` 通过（新超标项以基线冻结）。
- **风险与回滚**：新口径会让告警集合**完全换一批**；若阈值定得过严会淹没 CI。回滚 = 还原 `pyproject.toml` 与检查脚本。
- **预估工时**：与 **OPT-R2-21**（§2.8）**合并计算**（门禁改造 0.5 人日已计入该项）。
- **证据来源**：`docs/audit-round2/00-synthesis.md §4`；`pyproject.toml:13/:15/:18/:25`（本轮实测）。

### 4.3 前后端契约对齐工具

- **现状（本轮实测，**重要**）**：`check:api` + `check:api:pc` + `check:routes` **已经存在**于 `.github/workflows/ci-cd.yml:245-249`。**因此本项不是"从零建工具"，而是"摸清既有检查的粒度并补齐到字段级"**——若把已存在的东西当新功能报，就会重复劳动。
- **具体改法**：① 先读这三个脚本，确认它们检的是"路由存在性"还是"字段一致性"；② 若为路由级，则以 FastAPI 的 `/openapi.json` 为源生成前端类型/做字段 diff；③ 接入 CI，并把"未对齐模块"列白名单（同 `quality_gate` 基线思路）。
- **验收标准（可命令化）**：
  - `cd frontend-vite; npm run check:api`（既有）+ 扩展后的字段级检查均可运行；
  - **反例自测**：改一个后端响应字段名 → 扩展后的检查报错；
  - 覆盖度声明落盘（已对齐模块清单 / 未对齐模块白名单）。
- **风险与回滚**：字段级 diff 会一次性暴露大量历史不一致，**必须分批 + 白名单**。回滚 = 摘掉新增 CI 步骤。
- **预估工时**：与 **OPT-R2-27**（§3.8）**合并计算**（4 人日已计入该项）。
- **证据来源**：`.github/workflows/ci-cd.yml:245-249`（本轮实测，三检查已存在）；`docs/audit-round2/00-synthesis.md §5`。

### 4.4 依赖 pin + `npm ci`

- **现状（本轮实测）**：CI 前端 job 已在 `.github/workflows/ci-cd.yml:216` 使用 `npm ci`；但 `frontend-vite/package.json` 中 **43 个依赖全部使用 `^` 浮动范围**（`00-synthesis.md` "未验证"表第 11 项）。**注意区分**：`npm ci` 保证"按 lockfile 安装"，但 lockfile 里的版本来自 `^` 解析结果——**`npm ci` 不解决"下次 install 会漂移"**，两者要一起看。
- **具体改法**：① `package.json` 中依赖改为精确版本（或集中用 `overrides`）；② 确保 `package-lock.json` 入库（CI 的 `npm ci` 依赖它）；③ 建立依赖巡检提醒，避免 pin 之后长期不升级。
- **验收标准（可命令化）**：`grep -c '"\^' frontend-vite/package.json` 下降至目标值；`git ls-files frontend-vite/package-lock.json` 非空；`cd frontend-vite; npm ci; npm run build` 通过。
- **风险与回滚**：pin 后安全更新不再自动流入，需配套巡检。回滚 = 还原 `package.json`。
- **预估工时**：与 **OPT-R2-26**（§2.13）**合并计算**（1 人日已计入该项）。
- **证据来源**：`.github/workflows/ci-cd.yml:197-226`（`:216` `npm ci`，本轮实测）；`docs/audit-round2/00-synthesis.md`（43 依赖全 `^`）。

### 4.5 覆盖率棘轮

- **现状（本轮实测）**：`.github/workflows/ci-cd.yml:39` `COVERAGE_MIN: "40"`；`:140-142` 步骤 "Check coverage threshold" **就地 `exit(1)`**；`:68-95` 的 pytest 带 `--cov`。
- **关键点**：当前是**固定阈值 40**，不是棘轮——意味着"覆盖率从 60 掉到 41 也不会有人知道"。棘轮的价值在于**只升不降**。
- **具体改法**：① 把固定 `40` 改为"从仓库中的基线文件读取，且不得低于基线"；② 每次通过时把实测值写回基线（或人工 approve 抬升）；③ 保留"显式降级"通道（需人工理由），否则重构会被误伤。
- **验收标准（可命令化）**：人为把阈值抬高于实测值 → CI 失败；基线文件存在且数值与最近一次 CI 实测一致（可核对）。
- **风险与回滚**：棘轮过严会**阻塞正常重构**；必须保留显式降级路径。回滚 = 还原 workflow 与基线文件。
- **预估工时**：与 **OPT-R2-24**（§2.11）**合并计算**（棘轮 1.0 人日已计入该项）。
- **证据来源**：`.github/workflows/ci-cd.yml:39/:140-142/:68-95`（本轮实测）。

---

## 5. 不做清单（8 项）

> **判据**：每项都标注"**为什么不**"，且理由必须包含"**现在做会付出什么代价**"——不是"暂时没空"，而是"**方向本身不对/代价大于收益**"。本节依据 `docs/audit-round2/00-synthesis.md §2`（"不建议照抄 8 项"表格）与 `§4/§5`。

| # | 不做的事 | 为什么不 | 若将来真要做的前置条件 |
|---|---|---|---|
| 1 | **多公司/多币种内核化** | 当前 `company_id`/`tenant_id`/`multi_company` 在 `fastapi_app`、`migrations` **0 命中**，词边界 `currency` 在 `schemas`/`shared_models`/`migrations` **0 命中**——**现在没有多公司抽象，不是因为没做，而是因为不是这个产品的形态**。为一个不存在的需求在内核里加抽象，会让**每一个**查询、每一张表、每一条迁移都背上额外复杂度。**批三只做 §3.2 的"显式化"（不改业务语义）**。 | 有**已签约的真实多公司需求** + 数据量级评估 + 迁移成本评审 |
| 2 | **Frappe 式自动 DDL** | 让框架按模型自动改库，等于放弃"迁移可审阅、可回滚、可预测"。本项目 CI 已有 `alembic upgrade head` + `alembic check` **硬门禁**（`.github/workflows/ci-cd.yml:63-66`），这是**比自动 DDL 更强的工程约束**，不应放弃。 | 不适用（方向性拒绝） |
| 3 | **RPC 式 API** | 本项目是**字段密集的表格型 ERP**，资源式 REST + 明确的响应模型更利于契约检查（CI 已有 `check:api` 等，`:245-249`）。改 RPC 会让**已建立的契约门禁失效**，收益不确定。 | 出现明确的"跨 20 张表的事务性操作"用例，且 REST 表达确实吃力 |
| 4 | **Playwright 全铺 E2E** | 当前 CI **已删除 playwright install**，且仓库无 `playwright.config.*`、无 `e2e/`、无 `test:e2e`（`:218-224` 注释自陈）。全铺 E2E 会带来**持续的 CI 不稳定性与维护成本**。§2.9 的处置方向是**彻底移除或极少量必备用例**，不是全铺。 | 有专职维护 E2E 的人 + 稳定的测试数据工厂 + 明确只覆盖 3–5 条关键链路 |
| 5 | **插件/扩展框架** | `entry_point`/`plugin` 在 `pyproject.toml` **0 命中**——**没有任何已发生的插件需求**。为不存在的需求建框架是典型的过度抽象。§3.4 只做"**已发生客制化**的显式化"。 | 出现**第二个**独立客户方要求不改主代码地定制 |
| 6 | **全量索引与查询重构（一次性）** | 33 个缺失索引与 34 处循环查库的**完整清单尚不存在**（`03` 号是残片，`00-synthesis` 只给举例）。在清单缺失时"一次性全改"，等于**在未知对象上做大手术**，且 `idx_scan` 统计因 `pg_stat_reset` 后表行数极少而**不可靠**，无法验证收益。**批二只做"先重建清单、再按清单分批"。** | 清单已重建 + 有可信的负载与查询统计（或至少是生产真实流量下的数据） |
| 7 | **README/文档全量重写** | 文档问题主要是**引用会漂移、编号会冲突**，这是**机器可检查**的问题（§2.11 的引用检查 job），不需要一次全量重写——重写会产生巨大 diff 且同样会再次漂移。 | 不适用（方向性拒绝）；只做**增量修正 + 引用检查门禁** |
| 8 | **前端全量迁移到新状态管理/新 UI 库** | 前端已有大量可用资产（`catalog.ts`、`patternRoom.ts` 等 store 与 `UiDataTable`/`UiFilterBar` 等组件），真正的问题是**通用能力零消费方**（§2.6 `useEventDelegation`/`useVirtualScrollList` 零消费方、`UiFilterBar` 全仓仅 1 处命中）——**先收编已有的，而不是引入新的**。迁移会同时牺牲稳定性与进度。 | 现有技术栈出现**阻塞性缺陷**（如安全漏洞无法修补），且已评估迁移窗口 |

---

## 6. 方案自身的数据缺口

> **为什么必须单列**：本方案的**证据源本身是不完整的**。如果把残片当作完整证据使用，就会写出"看起来精确、实际无法执行"的工时与验收。本节把这一类项**全部显式标注**，并给出补齐动作——**这是本方案与其他"看起来很完备的方案"的区别所在**。

### 6.1 因素材残缺而只能给"待复核"工时与验收的项

**素材完整度事实（来自 `docs/audit-round2/README.md §7` 与 t1 归档者实测）**：
- `01-backend-structure.md`：**完整**
- `02-frontend-architecture.md`：**不完整**——恢复件在 **⑤ 节中途截断**
- `03-data-layer.md`：**残片**——原始完整 output 随团队状态目录丢失（现为 2,071 B 报告 + 4,777 B fallback 合并）
- `04-engineering-quality.md`：**不是完整报告**——是 `# TASK AS OF THIS BLOCK (history)` 折叠压缩块，**缺 OPT-01..22 状态表与工程健康度总评**
- `05-ops-security-observability.md`：完整
- `06-oss-erp-benchmark.md`：完整（另有 `06-oss-erp-raw-capture.txt` 原始抓取）

**因此，下列项的工时与验收带有"待复核"标记**（已在各自条目中标注，此处汇总）：

| 项 | 待复核内容 | 为什么待复核 | 复核后可能的偏差 |
|---|---|---|---|
| **OPT-R2-10**（§1.12 暴露面收口） | PG 监听 / 服务账户 / 旁路脚本**无清单** | 只有问题类别与举例，无全量清单 | 工时 **+0～2 人日**（清单条目数未知） |
| **OPT-R2-14**（§2.1 通用幂等层） | 需幂等的写接口数不知 | 路由口径三数并存（373/385/382），且未按写方法切分 | 工时 **+1～2 人日**（若需表设计评审） |
| **OPT-R2-15**（§2.2 索引收口） | 33 个缺失索引的**逐条 DDL** | `03` 号残片，只有举例 | 工时 **+1～2 人日**（若需并发建索引） |
| **OPT-R2-16**（§2.3 N+1） | 34 处调用点的**清单** | 同为残片举例 | 工时 **+1～2 人日**（若实际超 20 处） |
| **OPT-R2-17**（§2.4 连接池） | 4 个死键位的**确认** | 键位来自举例 | 工时 ±0.25 人日（范围小） |
| **OPT-R2-23**（§2.10 mypy 扩容） | 剩余模块的错误密度 | `04` 号缺健康度总评（**mypy 条目数已裁定为 110，不再是冲突项**，见 §7.5） | 每批 **±1 人日** |
| **OPT-02（续）**（§1.15） | 剩余 1 条失败的根因 | 需当场跑测试（本轮未跑） | 0.5 → **上限 1 人日** |
| **OPT-17（续）**（§3.9.1 内网 TLS） | 需装根证书的**终端数量** | 未统计 | 工时 **±2 人日** |
| **OPT-19（续）**（§3.9.2 uploads 改造） | 历史数据中已存储 URL 的数量 | 未统计 | 工时 **±1 人日** |
| **OPT-13 数字对齐**（§2.10，**已关闭**） | 覆盖条目 106→110（**裁定 110**） | ✅ 已裁定：正则漏数 `mypy.ini:33` 行内首条（109 + 1 = 110），旁证 `aac4c43f` 106 + `546401ec`（+5 −1）= 110 | 不影响工时；台账与 §2.10 均已按 110 记录（§7.5） |

> **纪律声明**：**以上任何一项都不得因为"看起来差不多"而被当作已精确估算。** 本方案在这些条目上写的是**区间与前置动作**，不是承诺数字。

**另有一类"未验证"内容不进入任何优化项**（避免把未验证事实写进待办）：`00-synthesis.md §6` 的 12 行"未验证"表中，如"Tryton/iDempiere 版本""Odoo 最新大版本""iDempiere REST 形态""五家覆盖率阈值"等属**外部事实未复抓**，与本仓库整改无关，不列入三批。

### 6.2 补齐素材所需的重跑动作（只读/离线）

> **硬约束**：**禁止运行任何 alembic 命令**。原因：`migrations/env.py:43-49` 显示每条 alembic 命令都会对 `alembic_version` 发 DDL，**违反本轮的只读边界**。需要迁移侧证据时，必须走离线 SQL 生成或纯静态解析。

| 要补齐的素材 | 重跑/重建动作（只读、离线） | 产出 | 工时 |
|---|---|---|---|
| `03` 号数据层报告 | 重跑数据层审计（**纯静态**）：① `grep -rn "ForeignKey(" fastapi_app/shared_models/`；② `grep -rnE "Index\(\[\"\]?index=True" fastapi_app/shared_models/`；③ `grep -rn "op.create_index" migrations/versions/`；④ 三者差集 → 逐条索引清单；⑤ 循环查库点：`grep -rn -A6 "for .* in .*:" fastapi_app/services/` 后**人工确认** | 33 个缺失索引的**逐条清单** + 34 处调用点的**逐条清单** + 20 个 NOT NULL 无默认值时间列的**逐表清单** + 软删除语义逐表清单 | **1.5 人日** |
| `04` 号工程健康度 | 重跑工程健康度审计：① 跑一次 CI 口径 pytest 取真实通过率与耗时（**只读**）；② `mypy.ini` 条目数 vs 提交信息数字对齐（`(Select-String -Path mypy.ini -Pattern '^\s+[A-Za-z_][\w/]*\.py,?\s*$').Count`）；③ `ruff check .` 按目录聚合（`server_manager`/`scripts` vs 其余）；④ 函数长度/组件 script 长度的**现状分布**（供 §4.2 定阈值） | 工程健康度总评 + OPT-01..22 落盘状态表 + 三项门禁的真实达标情况 | **1 人日** |
| `02` 号前端报告（截断部分） | 重跑前端架构审计的后半部分（⑤ 节之后）：依赖清单与 pin 现状、`.vue` script 长度分布、通用能力消费方普查（`useEnhancedList`/`UiFilterBar`/`useEventDelegation`/`useVirtualScrollList`） | 完整前端架构结论 + 11/12 文件口径的最终结论 | **1 人日** |
| 迁移链静态图 | **纯静态**解析 `migrations/versions/*.py` 的 `down_revision` 拼链（**不执行 alembic**）；如需 SQL 形态，**先确认 `env.py:43-49` 在 `--sql` 模式下是否仍发 DDL，存疑则不跑** | 迁移链图 + 4 根收敛的现状确认 | **0.5 人日** |
| PG 侧只读现状（可选） | **仅只读查询**：`SHOW listen_addresses;`、`SELECT * FROM pg_hba_file_rules;`、`\du`。**不执行任何 DDL/DML。** | 暴露面收口（OPT-R2-10）的输入 | 0.5 人日（需运维配合） |

**重跑总工时**：**4.5 人日**（其中 1.5 + 1 + 1 为必做，1 + 0.5 为按需）。**建议**：在批二开始前**先做前两项**（`03`/`04` 补齐），因为它们直接决定批二最大两个项（索引、N+1）的工时与验收是否可信。

**重跑的并行性**：三项重跑彼此独立（数据层 / 工程健康度 / 前端后半），**可由 3 个人并行**，因此日历时间 ≈ 1.5 人日而非 4.5。

---

## 7. 工时与批次自洽性校验

> 本节的目的：让"**工时与批次自洽**"（任务要求）成为**可被第三方核对**的，而不是一句声明。

### 7.1 工时汇总与"共享工时只计一次"处理

| 批次 | 项数 | 工时（人日） | 其中待复核 | 备注 |
|---|---|---|---|---|
| **批一 · 上线前必修** | 15 项 + 1 台账 = **16 项** | **12.0** | 1.0 | 含 **2.25 人日**为批二预备的清单重建（见 7.4） |
| **批二 · 2–6 周** | 14 新增 + 4 沿用 = **18 项** | **31.0** | 3.0 | 明细 33.5（含 §4.1 的 OPT-R2-37 1.5），已扣与 §4 共享的 **2.5**（见 7.2） |
| **批三 · 6–12 周** | 8 新增 + 3 沿用 = **11 项** | **39.0** | 3.0 | 明细 39.0；§4.3 的 4.0 即 OPT-R2-27 自身工时，无重复 |
| **合计** | **45 项**（含 9 项沿用编号） | **82.0** | 7.0 | 12.0 + 31.0 + 39.0 |
| *另：素材重跑（§6.2）* | *3 项必做 + 2 项按需* | *4.5* | — | **建议在批二开工前先行**；与批一部分重建工作重叠，**不得叠加计数**（见 7.4） |

**工时单位与人员假设**：1 人日 = 1 名熟悉本仓库的工程师 1 个工作日（含自测，不含评审等待）。**日历估算**：1 人约 17 周；2 人约 9 周（但批一多项改动集中在同几个文件，**并行收益在批一打折**，建议批一单人串行、批二起并行）。

### 7.2 逐项工时明细（可核对）

**批一（12.0）**：台账 OPT-R2-36 **0.5** + OPT-R2-01 **0.5** + OPT-R2-02 **0.5** + OPT-R2-04 **1.5** + OPT-22 续 **1.0** + OPT-R2-05 **1.0** + OPT-R2-06 **1.0** + OPT-R2-07 **0.5** + OPT-R2-08 **0.5** + OPT-R2-10 **1.5** + OPT-R2-11 **1.0** + OPT-R2-12 **0.5** + OPT-R2-13 **0.5** + OPT-R2-35 **0.5** + OPT-02 续 **0.5** = **11.5**；加 OPT-R2-03 的 **0.5**（§1.16.1）= **12.0** ✔（16 项相加）

**批二（31.0）**：OPT-R2-14 **4.0** + OPT-R2-15 **3.0** + OPT-R2-16 **3.0** + OPT-R2-17 **1.0** + OPT-R2-18 **1.5** + OPT-R2-19 **2.5** + OPT-R2-20 **1.5** + OPT-R2-21 **2.0** + OPT-R2-22 **0.5** + OPT-R2-23 **2.0** + OPT-R2-24 **2.5** + OPT-R2-25 **1.0** + OPT-R2-26 **1.0** + OPT-08 续 **1.0** + OPT-09 续 **3.0** + OPT-18 续 **1.0** + OPT-21 续 **1.5** + OPT-R2-37（§4.1）**1.5** = **33.5**（18 项相加）

**扣减（与 §4 共享，只计一次）**：§4.2 的 0.5 已计入 OPT-R2-21；§4.4 的 1.0 已计入 OPT-R2-26；§4.5 的 1.0 已计入 OPT-R2-24。§4.3 的 4.0 计入**批三**的 OPT-R2-27，**不在批二扣减**；**§4.1 的 1.5 计入批二的 OPT-R2-37，本身即在批二明细内，不扣减**。故批二 = **33.5 − 0.5 − 1.0 − 1.0 = 31.0**。

> **对账说明（避免重复计工）**：批二的 18 项明细合计 **33.5 人日**（含 §4.1 的 OPT-R2-37 1.5），其中 §4.2 的 0.5（组件长度门禁）已计入 OPT-R2-21、§4.4 的 1.0（依赖 pin）已计入 OPT-R2-26、§4.5 的 1.0（覆盖率棘轮）已计入 OPT-R2-24——这三项在 §4 再次出现，**故只计一次，批二取 33.5 − 2.5 = 31.0**。**§4.3 的 4.0（契约对齐）不在批二扣减**，因为它对应批三的 OPT-R2-27，已在批三内部计入（见下）。另：批一的 **2.25 人日清单重建**（OPT-R2-10 的 0.5 + OPT-R2-14 的 0.5 + OPT-R2-15 的 1.0 + OPT-R2-17 的 0.25）与 §6.2 的素材重跑是同一批工作，**不在 §7.1 的 82.0 之外另行叠加**（见 7.4）。

**批三（39.0）**：OPT-R2-27 **4.0** + OPT-R2-28 **5.0** + OPT-R2-29 **6.0** + OPT-R2-30 **2.0** + OPT-R2-31 **4.0** + OPT-R2-32 **3.0** + OPT-R2-33 **4.0** + OPT-R2-34 **3.0** + OPT-17 续 **4.0** + OPT-19 续 **3.0** + OPT-05 续 **1.0** = **39.0** ✔（11 项相加；§4.3 的 4.0 即 OPT-R2-27 自身的工时，已在批三内部，**不重复扣减**）

### 7.3 依赖关系与批次自洽性（无环、批一无前置）

| 检查项 | 结论 |
|---|---|
| **批一是否有前置依赖？** | **否**。批一 **16 项**的"依赖"字段中，唯一指向批一内部的只有 OPT-R2-13 → OPT-R2-08（同批、同源改动，可同一窗口完成）。**批一不依赖批二/批三任何项** ✔ |
| **是否存在跨批反向依赖（批二依赖批三）？** | **否**。批二内唯一跨批引用是"OPT-R2-18 可选复用 OPT-R2-27"，已注明**不是硬依赖** ✔ |
| **依赖图是否有环？** | 逐条核对：OPT-R2-13→08、OPT-R2-19→20、OPT-R2-14→OPT-09 续、OPT-R2-16 与 OPT-R2-15（**仅共享普查，非依赖**）、OPT-R2-32→OPT-R2-01、OPT-R2-27→OPT-R2-18、OPT-R2-33→OPT-R2-21、OPT-R2-34→OPT-02 续、OPT-21 续→OPT-08 续、OPT-R2-29→OPT-R2-28、OPT-R2-31→OPT-R2-28、OPT-R2-28→OPT-R2-16。**全部指向同批或前批，无环** ✔ |
| **批三是否存在"不该等到批三"的项？** | 逐项复查批三 11 项：均为"改形状／需设计决策／需清单"，**无一项属于"不修就会静默出错"**（这一类已在批一）✔ |
| **批一是否有项其实依赖清单重建？** | **有两类**：OPT-R2-10（暴露面清单），以及批二 OPT-R2-15/16（索引与 N+1 清单）。**处理方式**：把清单重建**前移到批一**（2.25 人日，见 §1.17 与 7.4），而不是把整项推到批二 ✔ |
| **工时是否随批次单调？** | 批一 12.0 / 批二 31.0 / 批三 39.0，**递增符合"批次越大改动越深"**；但批一的单位成本最高（平均约 0.75 人日/项，因多为"必须在上线前修完"的小项）——已在 7.1 注明 |
| **是否存在"未测量的性能承诺"？** | 逐条核查全案：**无**。涉及性能的表述均标注为结构性推断，或在验收中明确"必须实际测量后才填数字"（OPT-R2-15 禁用 `idx_scan`、OPT-R2-16 要求测量后再报、OPT-R2-20/33 明确不以构建体积为通过条件）✔ |
| **残片来源是否被冒充为完整证据？** | **否**。`03` 号每次引用均带"残缺／需重跑补齐"声明；`04` 号被明确禁止作为 OPT 状态证据源；`02` 号只用确实存在的小节，且 11 vs 12 的文件口径差异已写明（§2.6）✔ |

### 7.4 与 §6.2 素材重跑的衔接（避免重复计工）

§6.2 列出重跑总工时 **4.5 人日**（`03` 补齐 1.5 + `04` 补齐 1.0 + `02` 补齐 1.0 + 迁移链静态图 0.5 + PG 只读现状 0.5），其中：

- **`03` 号重跑（1.5）** 与批一的"索引清单 1.0"及 OPT-R2-16 的调用点普查，是**同一批工作**的重叠部分；
- **`04` 号重跑（1.0）** 覆盖 mypy 条目数对齐（§7.5）与三项门禁的现状分布（服务于 §4.1/§4.2）。

**结论**：**批一的 2.25 人日清单重建与 §6.2 的重跑是同一批工作，不得重复计算。** 7.1 表把重跑单列为"另"行，并明确"**建议在批二开工前先行**"——它同时服务批一（清单）与批二（工时可信化）。**若把 4.5 直接叠加到 82.0 上，就是重复计工。**

### 7.5 三处数字冲突的处理（mypy 已裁定 110；路由/测试文件为口径差异、不合成）

| 冲突 | 涉及数字 | 本方案的处理 | 核对方法（只读） |
|---|---|---|---|
| mypy 覆盖条目数 | 队长权威事实 **106 → 110**；本轮正则初测得 **109** | **✅ 已裁定 = 110**（不是冲突）：正则 `^\s+[A-Za-z_][\w/]*\.py,?\s*$` **漏掉了 `mypy.ini:33` 的行内首条 `files = fastapi_app/core/security.py,`**，`:34-142` 才是 109 条 ⇒ **109 + 1 = 110** | ① `(Select-String -Path mypy.ini -Pattern '^\s+[A-Za-z_][\w/]*\.py,?\s*$').Count`（→ 109，**+1 = 110**）；② `git show aac4c43f:mypy.ini` 计得 **106**，`546401ec` 对该文件 **+5 −1** ⇒ 106 + 5 − 1 = **110**；③ `python -m mypy --config-file mypy.ini -v` 复核实际解析文件数 |
| 路由数 | **373**（01 号端点数）/ **385**（02 号口径）/ **382**（05 号非测试路由） | **不裁定**，三数并存并写清口径（元信息区）；影响 OPT-R2-14 的清单基线 | `grep -rc"@router.get" ...` 按文件求和（含 `post/put/patch/delete`），与三数分别对照 |
| 测试文件数 | **148 & 163**（04 号数全部 `.py`）vs **110 & 161**（06 号只数 `test_*.py`） | **不合成**，四数同时成立（元信息区）；影响 OPT-R2-34 的双树分工描述 | 两树各跑一次：`(Get-ChildItem -Recurse <树> -Filter *.py).Count` 与 `-Filter test_*.py` |

> **纪律**：三处中 **mypy 条目数已裁定为 110**（原「109」是正则漏数，属**方法错误**，不是口径差异——见上表第一行）；**路由数与测试文件数两处是口径差异而非错误**，本方案不做"择一为真"的判断，凡下游引用必须带口径。**另**：整份审计的证据基线是 `aac4c43f`，写作基线是 `546401ec`（多 1 个提交），因此**所有行号引用在实施时都应重新核对**（尤其 `mypy.ini`；`fastapi_app/services/staging_utils.py` 已被该提交删除，任何指向它的引用均已失效）。

## 8. 执行纪律

### 8.1 只读与安全边界（本方案在实施中同样适用）

- **禁止运行 alembic**：`migrations/env.py:43-49` 显示每条 alembic 命令都会对 `alembic_version` 发 DDL。需要迁移侧证据时只能用**离线 SQL 生成**（且先确认 `--sql` 模式不触发 DDL）或**纯静态解析**。
- **禁止改生产库、禁止擅自重启生产服务**：涉及 PG 配置、NSSM 服务、nginx 的改动一律走维护窗口（§8.3）。
- **临时脚本只写 `%TEMP%\erp_audit_v2\`**，不污染仓库。
- **本方案自身不动代码**：§1–§3 是待执行项，执行者须按各自"证据来源"**重新核对行号后再动手**。

### 8.2 门禁纪律（防止"改完又漂回去"）

1. **先冻结基线，再收紧**：扩大 ruff 范围、改组件长度口径、加覆盖率棘轮都会一次性产生大量新告警，**必须先用 `scripts/quality_gate.py` 的基线机制冻结现状**（`:177` / `:189` / `:205`），再逐步下降。**一次全红等于门禁失效。**
2. **清单必须落盘**：任何"需先重建清单"的项（索引／N+1／暴露面／幂等写接口），**清单文件本身是交付物**，且条目数要与后续改动数可核对。
3. **数字要带命令**：凡在提交信息、文档、台账中出现的数量（mypy 条目、路由数、覆盖率），**必须附可复现命令**——本轮 106/109/110 的冲突正是缺这一步的后果（§2.11 的提交信息规范即为对此的补救）。
4. **不得用不可靠的统计做决策**：`idx_scan` 因 `pg_stat_reset` 后多数表仅 0–30 行而**不可用**（`00-synthesis.md §6`）；索引／查询类决策必须有可信负载，否则明确标注为结构性推断。

### 8.3 变更窗口与回滚准备

| 改动类型 | 是否需要窗口 | 回滚准备 |
|---|---|---|
| 纯代码（批一多数项） | 否 | `git revert` 单个提交 |
| NSSM 服务（OPT-08 续） | **是** | 先记录原 `Application` / `AppParameters` 字符串 |
| PG 配置 / `pg_hba`（OPT-R2-10） | **是** | 备份 `pg_hba.conf` 原文并保留旧文件 |
| 索引创建（OPT-R2-15） | **是**（写密集表） | 每个索引必须有 `downgrade`（已列为验收项） |
| nginx / TLS（OPT-17／18 续） | **是** | 保留旧配置并确认可 `reload` 回退 |
| 依赖升级（OPT-21 续） | 否（测试环境先验证） | 保留旧 `requirements/base.txt` |

### 8.4 每批的验收动作（谁来验、验什么）

- **批一**：§1.17 的 DoD 四项逐条核对；其中"CI 口径 pytest 0 failed"必须由**独立于修改者的人**执行（避免自证）。
- **批二**：§2.15 的 DoD 四项；其中"mypy 覆盖条目数单调不减"用 §7.5 的命令现场跑。
- **批三**：§3.10 的 DoD 四项；其中"契约对齐工具能对 1 个字段级不一致报错"必须用**反例自测**（改一个字段名看工具是否报错），不接受"工具能跑"。
- **台账（OPT-R2-36）**：每批结束时更新 `docs/optimization-status-2026-10-01.md`，并在同一提交内落盘——**"是否已执行"从此有唯一可查落点**，这正是本轮审计暴露的最大管理洞。

### 8.5 本方案自身的已知不足（诚实声明）

1. **证据源不完整**：`02` 截断、`03` 残片、`04` 折叠块（§6.1 已逐项标注）。因此批二中索引与 N+1 两项的工时是**区间**而非承诺。
2. **工时未经过项目评审**：全部为一人估算，**无历史速度数据**（本仓库无可用工时记录），因此 82.0 人日是**量级判断，不是承诺**。
3. **批三的"不做"边界可能需调整**：§5 的 8 项判据基于**当前**"无多公司、无插件需求"的事实；若业务前提变化需重新评审——这正是 §5 每行都写"前置条件"的原因。
4. **未验证项未强行给结论**：`00-synthesis.md §6` 的 12 行"未验证"表中，除已转为待确认项的（如 §1.16 的缓存登出窗口）外，其余**不编入待办**，避免把猜测写成任务。
5. **本轮未运行任何测试或构建**：所有"CI 口径"描述基于 `.github/workflows/ci-cd.yml` 的**文本**，非实际执行结果。**首次实施时必须以实跑结果为准。**

---

## 附：本方案与既有编号的完整对照

| 编号 | 项 | 所属章节 | 批次 |
|---|---|---|---|
| OPT-R2-36 | OPT 执行状态台账 | §0.1 | 批一（首项） |
| OPT-R2-01 | 事务提交失败可告警 | §1.2 | 批一 |
| OPT-R2-02 | 备份加密口令缺失改显式失败 | §1.4.1 | 批一 |
| OPT-R2-03 | approval 表时钟混写 | §1.16.1 | 批一 |
| OPT-R2-04 | 备份可还原校验 + RTO/RPO 书面化 | §1.4.2 | 批一 |
| OPT-22（续） | 恢复演练选对产物 | §1.5 | 批一 |
| OPT-R2-06 | customer_sampling 补权限点 | §1.7 | 批一 |
| OPT-R2-05 | 明文密钥移出工作区 | §1.8 | 批一 |
| OPT-R2-08 | 限流键不信任 XFF | §1.9 | 批一 |
| OPT-R2-09 | （号段保留／缺口说明见下方） | — | — |
| OPT-R2-07 | 撤销 `--host 0.0.0.0` | §1.11 | 批一 |
| OPT-R2-10 | 暴露面收口 | §1.12 | 批一 |
| OPT-R2-11 | 配置漂移门禁化 | §1.13 | 批一 |
| OPT-R2-12 | 健康检查信息面收敛 | §1.14.1 | 批一 |
| OPT-R2-13 | 审计 client_ip 口径统一 | §1.14.2 | 批一 |
| OPT-02（续） | 修最后 1 条 pytest 失败 | §1.15 | 批一 |
| OPT-R2-35 | 缓存登出窗口（批一仅确认） | §1.16 | 批一（确认） |
| OPT-R2-14 | 通用幂等层 | §2.1 | 批二 |
| OPT-R2-15 | 索引收口 | §2.2 | 批二 |
| OPT-R2-16 | 关系 lazy 显式化 + N+1 | §2.3 | 批二 |
| OPT-R2-17 | 连接池参数接线 | §2.4 | 批二 |
| OPT-R2-18 | 统一错误信封 | §2.5 | 批二 |
| OPT-R2-19 | 前端通用能力收编 | §2.6 | 批二 |
| OPT-R2-20 | 前端死代码清理 | §2.7 | 批二 |
| OPT-R2-21 | 组件长度门禁改按 script | §2.8 / §4.2 | 批二 |
| OPT-R2-22 | playwright 死依赖处置 | §2.9 | 批二 |
| OPT-R2-23 | mypy 覆盖扩容第 2 批 | §2.10 | 批二 |
| OPT-R2-24 | 覆盖率棘轮 + 提交规范 + 引用检查 | §2.11 / §4.5 | 批二 |
| OPT-R2-25 | 迁移命名规范 + 升级清单 | §2.12 | 批二 |
| OPT-R2-26 | 依赖 pin + npm ci + dist 清理 | §2.13 / §4.4 | 批二 |
| OPT-R2-37 | `quality_gate` 聚合入口 | §4.1 | 批二 |
| OPT-08（续） | venv 隔离收尾（NSSM） | §2.14.1 | 批二 |
| OPT-09（续） | useApiMutation 推广收尾 | §2.14.2 | 批二 |
| OPT-21（续） | fastapi 0.137.1 → 0.142.2 | §2.14.3 | 批二 |
| OPT-18（续） | nginx limit_req | §2.14.4 | 批二 |
| OPT-R2-27 | 字段级 API 契约对齐 | §3.8 / §4.3 | 批三 |
| OPT-R2-28 | 分层收尾 | §3.1 | 批三 |
| OPT-R2-29 | 公司/本位币收敛为配置 | §3.2 | 批三 |
| OPT-R2-30 | 记录级权限最小切片 | §3.3 | 批三 |
| OPT-R2-31 | 扩展点清单 + 覆盖层规范 | §3.4 | 批三 |
| OPT-R2-32 | 可观测性落地 | §3.5 | 批三 |
| OPT-R2-33 | 前端 script 体积治理 | §3.6 | 批三 |
| OPT-R2-34 | 测试双树语义治理 | §3.7 | 批三 |
| OPT-17（续） | 内网 TLS | §3.9.1 | 批三 |
| OPT-19（续） | uploads 免鉴权直出改造 | §3.9.2 | 批三 |
| OPT-05（续） | git-bash `_lc` 劫持复现确认 | §3.9.3 | 批三 |

**编号占用总览**：既有编号沿用 **9 项**（OPT-02/05/08/09/17/18/19/21/22；**OPT-13 已改号并入 §2.10 的 OPT-R2-23**）｜新增 **36 项**（号段 OPT-R2-01～OPT-R2-37，其中 **OPT-R2-09 保留空缺**；含 §0.1 台账 OPT-R2-36 与 §4.1 的 OPT-R2-37）｜关闭或降级 3 项（OPT-15/16/20，不再列待办）。**OPT-R2-03 说明**：approval 时钟混写在本方案中作为 A 类子问题登记为 OPT-R2-03（§1.16.1），其实做内容与验收随批一执行，**0.5 人日已计入批一的 12.0 合计**（见 §7.2）。

> **编号缺口说明（诚实标注）**：新增号段为 OPT-R2-01 ～ OPT-R2-37，**其中 OPT-R2-09 未使用**（在批一分节时把原拟的"暴露面统一收口"拆为 OPT-R2-07/08/10/11/12/13 六项，9 号随之不再需要）。**该号段保留空缺、不作他用、也不与既有 OPT-01..22 冲突**；若队长要求连号，把 OPT-R2-10 起的各项顺次前移一号即可（不影响任何内容与工时）。**号段末端：OPT-R2-36 为 §0.1 台账、OPT-R2-37 为 §4.1 门禁聚合入口（本轮修订单列）。**
>
> **说明（OPT-R2-03 已独立成项）**：approval 表时钟混写原在 §1.1 的 A 类全貌表中登记，现已补为独立条目 **§1.16.1 OPT-R2-03**（0.5 人日，批一），并已计入批一的 12.0 人日合计——**§1 与 §7 的口径一致，无遗留差异**。
