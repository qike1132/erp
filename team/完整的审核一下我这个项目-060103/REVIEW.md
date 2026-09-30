# 评审（REVIEW）

> 写者：**reviewer（T05 规格评审门禁）**。本文件是 `AUTHORITY.md` 中「撤销率」事实名的**唯一权威文件**。
> 评审对象：`team/完整的审核一下我这个项目-060103/SPEC.md`、`team/完整的审核一下我这个项目-060103/TASKS.json`、`team/完整的审核一下我这个项目-060103/PLAN.md`、`team/完整的审核一下我这个项目-060103/AUTHORITY.md`、`team/完整的审核一下我这个项目-060103/任务看板.md`（参考输入：`team/完整的审核一下我这个项目-060103/RESEARCH.md`、`team/完整的审核一下我这个项目-060103/DECISIONS.md`、`team/REPOWIKI.md`）。
> 评审方式：**只读**。所有结论均以文件锚点或只读脚本实测为证据；未跑任何 pytest 实体、未起停服务、未写库、未做任何 git 写操作。

## 撤销率

**撤销率 = 被撤销 finding 数 ÷ 提交 finding 数**。

- **分子**：终态为 `rejected` 的 finding 条数（含命中 §6.3 白名单 / PLAN §4 防伪影清单而被 T15 判 `rejected` 者）。
- **分母**：各维度报告**提交**并经 T15 收讫的 finding 条数（`FINDINGS.json.stats.submitted`）。
- 统计口径与落盘位置：`team/完整的审核一下我这个项目-060103/REVIEW-CROSS.md` 的「撤销率」行 + 撤销清单（含撤销理由）；原始计数以 `FINDINGS.json` 的 `stats` 为准（`team/完整的审核一下我这个项目-060103/SPEC.md` · `被撤销条数` @ 41）。
- **撤销率 > 40% ⇒ T15 必须 `verdict=needs_revision`**（`team/完整的审核一下我这个项目-060103/SPEC.md` · `撤销率` @ 131 A08；`team/完整的审核一下我这个项目-060103/PLAN.md` · `撤销率` @ 312 R2）。
- 由 reviewer 维护；本定义式为该事实名的唯一权威定义体（`team/完整的审核一下我这个项目-060103/AUTHORITY.md` · `撤销率` @ 72）。

## 结论

**需返工（`verdict=needs_revision`）**。10 条 finding（P1×2 / P2×5 / P3×3）中，`F-RVW01`、`F-RVW02`、`F-RVW03`、`F-RVW06`、`F-RVW07`、`F-RVW08` 必须修改 SPEC / PLAN 才能过门禁；`F-RVW04`、`F-RVW05`、`F-RVW09`、`F-RVW10` 属权威文件内部不自洽，一并修正后可放行 T06–T14（A25 门禁保持关闭）。

### 逐项核对表（R-A … R-J）

| 项 | 结论 | 证据锚点 |
|---|---|---|
| **R-A 覆盖性** | **通过**。SPEC §2.1 的 D01–D13 各有 ≥1 条主责任务（D01→T06、D02→T07、D03→T08、D04→T09、D05→T10、D06→T11、D07→T12、D08→T13、D09→T14、D10→T06+T12、D11→T18、D12→T19、D13→T21）；owner 覆盖 12 角色（architect/backend/dba/devops/docs/frontend/pm/qa/researcher/reviewer/sec/ui）；无「有维度无任务」，无「有任务无维度」（T01/T02/T03/T04/T05/T15/T16/T17/T20 为调研/门禁/汇总/条件腿，非维度任务） | `team/完整的审核一下我这个项目-060103/SPEC.md` · `### 2.1 审核维度` @ 52；`team/完整的审核一下我这个项目-060103/TASKS.json` · `"owner": "sec"` @ 799 |
| **R-B 验收可判性** | **不通过**。A05/A22 与 PLAN §3.1 冻结 schema **互斥**（F-RVW01）；A03 的机判正则与 PLAN §3 允许的表格/JSON 渲染**互斥**（F-RVW06）；A09 与 A10 对「未实跑命令」的口径**冲突**（F-RVW07） | `team/完整的审核一下我这个项目-060103/SPEC.md` · `全部 finding 汇总进` @ 128；`team/完整的审核一下我这个项目-060103/PLAN.md` · `additionalProperties` @ 177 |
| **R-C 只读边界** | **通过**。§6.1 堵死业务代码与配置写路径（含 `AGENTS.md` / `.githooks/` / `pyproject.toml` / `ruff.toml` / `mypy.ini` / `pytest.ini` / `scripts/gate_baseline.json`）；TASKS.json 全部 21 条任务的 `inScope` **越界数 = 0**（全部落在 run-dir 或 `team/REPOWIKI.md`） | `team/完整的审核一下我这个项目-060103/SPEC.md` · `禁止什么` @ 230；`team/完整的审核一下我这个项目-060103/TASKS.json` · `"id": "T05"` @ 208 |
| **R-D 生产边界** | **不通过**。§6.2 允许/禁止清单与用户 Q2 一致，但 C04 `pytest -q` **不可无条件实跑**：`tests/conftest.py` 存在 `DROP SCHEMA public CASCADE` + `create_all` + 提交型 fixture（F-RVW02） | `team/完整的审核一下我这个项目-060103/SPEC.md` · `明确禁止` @ 239；`tests/conftest.py` · `DROP SCHEMA public CASCADE` @ 181 |
| **R-E 白名单完整性** | **不通过**。§6.3 漏 4 条上游条目，且 @ 262 自述上游「12 行」与实际不符（F-RVW03） | `team/完整的审核一下我这个项目-060103/SPEC.md` · `上游全集指路` @ 262；`team/REPOWIKI.md` · `mypy.ini` @ 240 |
| **R-F DAG 正确性** | **通过**（结构）。21 条任务：重复 id = 0、自依赖 = 0、缺依赖 = 0、环 = 0；A25 门禁在依赖图上成立（T06–T14 的 `dependsOn` 均含 `T05`）；T15 依赖 T06–T14+T18+T19+T21；T16 依赖 T15；T17 依赖 T16；T20 `dependsOn=[T17]`、`status=blocked-by-user-decision`、`conditional` 字段存在且未启动。状态**投影**口径另有问题（F-RVW10） | `team/完整的审核一下我这个项目-060103/TASKS.json` · `"id": "T15"` @ 848；`team/完整的审核一下我这个项目-060103/SPEC.md` · `门禁前置` @ 148 |
| **R-G AUTHORITY 合规** | **不通过**（行号）。14 行事实名的定义式**全部逐字命中**对应权威文件（含本文件新落盘的「撤销率」），无同一权威文件多写者；但 SPEC 侧 8 行中 **7 行「命中位置」行号错误**（F-RVW05） | `team/完整的审核一下我这个项目-060103/AUTHORITY.md` · `命中行号即证据` @ 55；`team/完整的审核一下我这个项目-060103/AUTHORITY.md` · `严重度判定口径` @ 59 |
| **R-H 幻觉控制** | **不通过**（计数与锚点）。PLAN §4 的 F-01…F-20 覆盖面成立，但「12 + 12 = 24 行 / 去重后 18 条独立现象」的算术与锚点均不成立，F-09 证据锚点错位（F-RVW04） | `team/完整的审核一下我这个项目-060103/PLAN.md` · `去重说明` @ 274；`team/完整的审核一下我这个项目-060103/PLAN.md` · `playwright` @ 287 |
| **R-I 交付形态** | **通过**。A19 的 12 份分维度工件（T06–T14 九份 + T18/T19/T21 三份）在 DAG 中均有唯一产出任务；T16 覆盖 `SUMMARY.md` + `BACKLOG.md`；工件名冲突 = 0（每条 `inScope` 路径唯一归属一个任务） | `team/完整的审核一下我这个项目-060103/SPEC.md` · `交付形态满足` @ 142；`team/完整的审核一下我这个项目-060103/TASKS.json` · `"id": "T16"` @ 907 |
| **R-J 缺口与风险** | **不通过**。阻塞实现期的点为 F-RVW01 / F-RVW02 / F-RVW03 / F-RVW06 / F-RVW07（均须改 SPEC 或 PLAN），另 F-RVW04 / F-RVW05 / F-RVW08 / F-RVW09 / F-RVW10 为权威文件内部不自洽 | `team/完整的审核一下我这个项目-060103/PLAN.md` · `防伪影清单` @ 271；`team/完整的审核一下我这个项目-060103/SPEC.md` · `静态审计` @ 350 |

## 问题清单

### F-RVW01 · PLAN 冻结的 finding schema 与 SPEC 验收字段集互斥（含 `additionalProperties: false`）
- severity: P1
- anchor: `team/完整的审核一下我这个项目-060103/PLAN.md` · `additionalProperties` @ 177
- evidence: PLAN §3.1 的 13 字段冻结集为 `id/dimension/severity/title/file/anchor/line/evidence/impact/recommendation/verify/confidence/reverted`，且显式 `"additionalProperties": false`（`team/完整的审核一下我这个项目-060103/PLAN.md` · `字段数` @ 224）。而 SPEC A05 要求 FINDINGS.json 字段齐全「id / severity / dimension / **owner** / anchor / evidence / **status**」（`team/完整的审核一下我这个项目-060103/SPEC.md` · `全部 finding 汇总进` @ 128），A22 要求「所有 finding 的 `status` 终态为 confirmed / rejected / merged」（`team/完整的审核一下我这个项目-060103/SPEC.md` · `所有 finding 的` @ 145）。PLAN §3.1 **既无 `owner` 也无 `status`**，且 §3.2 自述「`status` 终态统计沿用 SPEC §5.3 的 `stats`」（`team/完整的审核一下我这个项目-060103/PLAN.md` · `终态统计` @ 246）——那是**聚合计数**，无法承载 A22 的**逐条** status。T15 的 verify 脚本正是逐条取 `x.get('status')`（`team/完整的审核一下我这个项目-060103/TASKS.json` · `all(x.get` @ 867），与 PLAN §3.1 直接冲突。结论：同一份 FINDINGS.json 无法同时满足 PLAN §3.1（多一个字段即非法）与 SPEC A05/A22（缺字段即不合格）。
- impact: T15 无论怎么写都必有一侧判失败；A22「无 `open` 残留」无法机判；A05 的 schema 校验必然报错。审计在汇总阶段**结构性不可完成**。
- fix-hint: 由 **architect** 在 PLAN §3.1 增加 `owner`（12 角色枚举）与 `status`（`open|confirmed|rejected|merged`，并与 §3.3 第 6 条的 `reverted` 建立「status=rejected ⇔ reverted=true」一致规则），字段数改为 15，同步 §3.2 映射表与 `finding 契约` 定义；或由 **pm** 把 A05/A22 的字段集改为引用 PLAN §3.1。**二选一，须由 lead 裁定唯一权威，不得两边各写一套。**
- status: open

### F-RVW02 · C04 `pytest -q` 会在无校验派生的数据库上执行 `DROP SCHEMA public CASCADE`，SPEC §9.1 前置①对 `tests/conftest.py` 不成立
- severity: P1
- anchor: `tests/conftest.py` · `DROP SCHEMA public CASCADE` @ 181
- evidence: （1）`tests/conftest.py` 的会话级 fixture `test_engine`（`tests/conftest.py` · `test_engine` @ 157）在 @ 181 执行 `await conn.execute(text("DROP SCHEMA public CASCADE"))`、@ 182 `CREATE SCHEMA public`、@ 185 `await conn.run_sync(Base.metadata.create_all)`；docstring @ 178 自述「仅作用于 `erp_system_test` 测试库」。（2）目标库由 @ 96 `TEST_DATABASE_URL = _build_test_db_url()` 决定：@ 80-82 优先取环境变量 `TEST_DATABASE_URL`（**任何值都直接采信**），否则 @ 87-92 取 `os.getenv("DB_NAME","erp_system")` 与 `settings.ASYNC_DATABASE_URL`，用 @ 91 `parsed.path.replace(f"/{db_name}", f"/{db_name}_test", 1)` **纯字符串替换且不校验结果** —— 若 `DB_NAME` 与 URL 中的库名不一致，替换静默不生效，`TEST_DATABASE_URL` 将等于**主库 URL**。（3）@ 193 `app_on_test_db` 是 `scope="session", autouse=True`，且 `pytest.ini` · `testpaths` @ 3 为 `tests fastapi_app/tests`，覆盖整个 `tests/`（该目录下 112 个 `test_*.py`）⇒ 只要跑 `pytest -q` 就必然触发上述 DDL。（4）另有提交型 fixture：@ 298 `await session.commit()`（docstring @ 285 明说「提交模式」）。（5）只读静态核对：`tests/conftest.py` 是 5 个 conftest 中**唯一**含写操作的；`tests/e2e/conftest.py`、`tests/e2e_api/conftest.py`、`fastapi_app/tests/conftest.py`、`scripts/prod_audit/tests/conftest.py` 的写操作命中数均为 0。（6）**现状可达性**：`.env` · `DB_NAME` @ 11 为 `erp_system`，且 `.env` 未设 `ASYNC_DATABASE_URL`（由 `DB_*` 组装）⇒ 当前默认解析为 `erp_system_test`，与生产库 `erp_system` 同实例不同库，**当前不可达生产库**；故按 `team/完整的审核一下我这个项目-060103/SPEC.md` · `满足下列` @ 160 的 P1②（触发 P0 场景但当前不可达）定级。（7）`erp_system_test` 是否实际存在**未验证** —— 本任务禁止连库，属显式未知项。（8）由此 SPEC §9.1 前置①「静态审计 … 确认**没有**对生产库的写操作（`create_all` / `drop_all` / INSERT / 事务回滚外写）」（`team/完整的审核一下我这个项目-060103/SPEC.md` · `静态审计` @ 350）按字面**不可能通过**：该文件确实含 `create_all`、`DROP SCHEMA` 与提交型 fixture；能成立的只是较弱的命题「**在当前 `.env` 下**破坏性目标解析为 `erp_system_test`」。（9）SPEC §9.1 只点名 2 个 conftest，而 testpaths 实际覆盖 3 个（`tests/e2e/`、`tests/e2e_api/` 未点名）。
- impact: T14 若照实写「前置①通过」即为**不实陈述**；若在 `TEST_DATABASE_URL` 被外部设为生产库、或 `DB_NAME` 与 URL 库名漂移的时点执行 C04，将对生产库执行 `DROP SCHEMA public CASCADE`（**不可恢复的数据丢失**）。这同时使 A09（12 条命令逐条三元组）在 C04 上无法诚实满足。
- fix-hint: 由 **pm** 修订 SPEC §9.1：把前置①改为可机判的两步 —— ① 读出并记录解析后的 `TEST_DATABASE_URL`（口令打码），**断言其库名 ≠ `DB_NAME`**；② 若 `TEST_DATABASE_URL` 环境变量已设、或断言不成立 ⇒ C04 判 `blocked-by-policy` 并标「未实跑」+ 阻塞原因。同步修订 A09（见 F-RVW07）。**禁止**在 T14 自行改 `tests/conftest.py`（§6.1 只读边界）。
- status: open

### F-RVW03 · SPEC §6.3 白名单漏收 4 条上游条目，且 @ 262 自述的「上游 12 行」与实际行数不符
- severity: P2
- anchor: `team/完整的审核一下我这个项目-060103/SPEC.md` · `上游全集指路` @ 262
- evidence: §6.3 @ 262 声明「`team/REPOWIKI.md` §7.4 与 `RESEARCH.md` §5.2 的 **12 行**为本白名单的**上游全集**，与 §6.3 必须一致」。逐一比对（不是只看条数）：REPOWIKI §7.4 表体实为 **9 行**（`team/REPOWIKI.md` · `logs/prod_runner.json` @ 234 起，至 `team/REPOWIKI.md` · `max_file_size` @ 242），RESEARCH §5.2 表体实为 **13 行**（`team/完整的审核一下我这个项目-060103/RESEARCH.md` · `logs/prod_runner.json` @ 195 起，至 `team/完整的审核一下我这个项目-060103/RESEARCH.md` · `config/nginx.conf` @ 207）。去重后共 **14 条**独立现象（8 条两表共有 + REPOWIKI 独有 1 条 + RESEARCH 独有 5 条）。§6.3 只落 W1–W14 共 14 行，**漏收 4 条上游条目**：① `mypy.ini` 注释里的两个「真实缺陷」已修复（`team/REPOWIKI.md` · `mypy.ini` @ 240；`team/完整的审核一下我这个项目-060103/RESEARCH.md` · `mypy.ini` @ 201）；② `core.hooksPath` 事故已修复（`team/REPOWIKI.md` · `core.hooksPath` @ 241）；③ `_ops/credentials/` 磁盘明文属预期、需验的是 ACL（`team/完整的审核一下我这个项目-060103/RESEARCH.md` · `_ops/credentials` @ 202）；④ `deliverables/`(106) + `evidence/`(190) + `mockups/`(10) 已入库属历史归档（`team/完整的审核一下我这个项目-060103/RESEARCH.md` · `deliverables/` @ 206）。这 4 条只存在于 `team/完整的审核一下我这个项目-060103/PLAN.md` §4（F-10 / F-11 / F-12 / F-17），§6.3 无对应 W 行。另有 1 条 §6.3 独有而两表皆无者（W6 `pytest.ini` GBK 乱码），属允许的超集。
- impact: §6.3 自称「必须一致」但实际不一致，A20 的「全工件 grep 白名单锚点」在缺项上退化为依赖 PLAN §4；跨文件一致性无法机判，未来轮次极易再次把 `_ops/credentials/` 明文或 `deliverables/` 入库当 finding 上报（上一轮同类坑已复现一次）。
- fix-hint: 由 **pm** 在 SPEC §6.3 补 W15–W18 四条（与 `team/完整的审核一下我这个项目-060103/PLAN.md` · `防伪影清单` @ 271 的 F-10 / F-11 / F-12 / F-17 对齐），并把 @ 262 的「12 行」改为「REPOWIKI §7.4 表体 9 行（@ 234–242）+ RESEARCH §5.2 表体 13 行（@ 195–207），去重 14 条」。**不得**反向删减 PLAN §4。
- status: open

### F-RVW04 · PLAN §4 的去重说明与原始行数声明不成立，F-09 证据锚点错位
- severity: P2
- anchor: `team/完整的审核一下我这个项目-060103/PLAN.md` · `去重说明` @ 274
- evidence: PLAN §4 @ 271 声明「原样收录 REPOWIKI §7.4 的 12 条 + RESEARCH §5.2 的 12 条」，@ 274 声明「源表分别 12 行 … 合并后 **18 条独立现象**；原始条数 **12 + 12 = 24 行**（REPOWIKI §7.4 表体 12 行 @ 234–242，RESEARCH §5.2 表体 12 行 @ 195–207）」。实测：REPOWIKI §7.4 表体 **9 行**，RESEARCH §5.2 表体 **13 行**，原始合计 **22 行**（非 24），去重后 **14 条**（非 18）。且 F-01…F-18 并非两张上游表的去重结果：F-02 / F-03 源自 SPEC §6.3 的 W2 / W8，F-16 / F-18 源自 REPOWIKI §7.1 与 W7，F-09（`package.json` 声明 `playwright` 但无 e2e 脚手架）**不在两张上游表内**，其证据锚点写作「`team/完整的审核一下我这个项目-060103/RESEARCH.md` §5.2 @ 201 附近」（`team/完整的审核一下我这个项目-060103/PLAN.md` · `playwright` @ 287），而 `team/完整的审核一下我这个项目-060103/RESEARCH.md` · `mypy.ini` @ 201 实为 `mypy.ini` 行。另 PLAN R7 @ 317 写「`team/完整的审核一下我这个项目-060103/SPEC.md` §6.3 W1–W8」，实际为 W1–W14（`team/完整的审核一下我这个项目-060103/PLAN.md` · `白名单误报` @ 317）。
- impact: 「控制幻觉率的第一道闸」自身携带 3 处计数/锚点幻觉；T15 / T17 无法按声明核对「18 条」，A20 的检索基数不可信；R7 把白名单范围少写 6 条，会诱导各角色漏检 W9–W14。
- fix-hint: 由 **architect** 修订 PLAN §4 @ 274 为实测值（22 行原始 / 14 条去重），重挂 F-09 的证据锚点（指向 `frontend-vite/package.json` · `playwright`），并把 R7 的「W1–W8」改为「W1–W14」；同时把「18 条独立现象」改为「本表 18 行 F 项（其中 14 条来自两张上游表，另 4 条来自 SPEC §6.3 与 REPOWIKI §7.1）」。
- status: open

### F-RVW05 · AUTHORITY 定义式核对表的「命中位置」行号 8 行中 7 行错误
- severity: P2
- anchor: `team/完整的审核一下我这个项目-060103/AUTHORITY.md` · `命中行号即证据` @ 55
- evidence: 用只读脚本逐行比对（非采信文档自述），14 行事实名的定义式**全部逐字命中**（`formVerbatim = true`），但 SPEC 侧「命中位置」列 8 行中 7 行行号错误：`严重度判定口径` 记 @ 151 实为 @ 155（`team/完整的审核一下我这个项目-060103/AUTHORITY.md` · `严重度判定口径` @ 59 对 `team/完整的审核一下我这个项目-060103/SPEC.md` · `### 5.1 严重度判定口径` @ 155）；`只读边界` 记 @ 222 实为 @ 226；`生产环境边界` 记 @ 230 实为 @ 234；`命令清单` 记 @ 341 实为 @ 355；`白名单` 记 @ 239 实为 @ 243；`工件命名与责任矩阵` 记 @ 71 实为 @ 74；`需求一致性对照起点` 记 @ 423 实为 @ 437。仅 `审核维度` @ 52 正确。PLAN 侧 5 行（@ 226 / @ 260 / @ 11 / @ 271 / @ 307）全部正确。同一权威文件多写者：**无**（SPEC 只 pm、PLAN 只 architect、REVIEW 只 reviewer）。
- impact: AUTHORITY @ 55 把「命中行号」定义为证据，7 行证据失效；T15 复核时会按错行号读到无关内容而误判「定义式缺失」，或误判已修正的 SPEC 版本。属可核对性缺陷（不改变定义式本身的存在性）。
- fix-hint: 由 **architect** 用脚本重算 §「定义式逐条核对」的 7 个 SPEC 行号（SPEC 侧当前实测值：155 / 226 / 234 / 355 / 52 / 243 / 74 / 437）。**不得**为对齐旧行号而改 SPEC。
- status: open

### F-RVW06 · A03 的机判正则与 PLAN §3 允许的表格/JSON 渲染形态互斥
- severity: P2
- anchor: `team/完整的审核一下我这个项目-060103/SPEC.md` · `每条 finding 采用` @ 126
- evidence: A03 的判定方式是「正则：findings 段每行含 `·` 与 ` @ <数字>`」（`team/完整的审核一下我这个项目-060103/SPEC.md` · `每条 finding 采用` @ 126）。而 PLAN §3 @ 167 明许「**表格或 JSON 均可**」，§3.1 把 `file` / `anchor` / `line` 拆成**三个独立槽**，且 @ 206 规定 `anchor` 的 `pattern` 为 `^[^0-9@]*$`（**不得含数字与 `@`**）（`team/完整的审核一下我这个项目-060103/PLAN.md` · `anchor` @ 203）。因此一份**完全合规**的 PLAN-schema 表格 / JSON 渲染，其 finding 行不会出现 ` @ <数字>` 连写，A03 正则必然判失败；反之要过 A03 就必须改用 §3.2 @ 239 的单串渲染（`file · anchor @ line`）。两套判定对同一份合规交付给出相反结论。
- impact: T17 门禁（A26 要求逐条对齐 A01–A25）会在 A03 上产生「合规但判 fail」的假失败，迫使各角色改渲染形态以迎合正则，或迫使 T17 放宽判定（违反 A26「不得新增未定义标准」）。
- fix-hint: 由 **pm** 把 A03 改为**接受两种合法渲染**：① 单串 `路径 · 锚点 @ 行号`；② 表格 / JSON 的三槽分列（`file` 带目录 ∧ `anchor` 不含数字与 `@` ∧ `line` 为正整数）。或由 **architect** 在 PLAN §3 把「findings 段」限定为单串渲染。**二选一。**
- status: open

### F-RVW07 · A09 与 A10 对「未实跑命令」的判定口径冲突，T14 自身验收不可同时满足
- severity: P2
- anchor: `team/完整的审核一下我这个项目-060103/SPEC.md` · `门禁命令逐条有` @ 132
- evidence: A09 要求「§9.2 的 12 条门禁命令**逐条**有『命令 + 退出码 + 原始输出片段』三元组」（`team/完整的审核一下我这个项目-060103/SPEC.md` · `门禁命令逐条有` @ 132），A10 同时要求「未能实跑的命令逐条标注『未实跑』+ 阻塞原因；未实跑**不得**计入通过」（`team/完整的审核一下我这个项目-060103/SPEC.md` · `未能实跑的命令逐条标注` @ 133）。未实跑命令**没有退出码与输出片段**，故两条按字面不能同时满足。T14 的 acceptance 把两条原文照抄（`team/完整的审核一下我这个项目-060103/TASKS.json` · `逐条有` @ 655 与 `team/完整的审核一下我这个项目-060103/TASKS.json` · `未实跑的命令逐条标注` @ 656），使 T14 无法同时满足自身两条验收项。结合 F-RVW02（C04 极可能必须判 `blocked-by-policy`），该冲突从「理论张力」变为「必然发生」。
- impact: T14 交付的 `TEST.md` 无论怎么写都会被 T17 判其中一条 fail；A09 与 A10 的组合判定不可机判，A26 的逐条对齐随之失效。
- fix-hint: 由 **pm** 把 A09 改为「**逐条有记录**：实跑项给『命令 + 退出码 + 原始输出片段』；未实跑项给『命令 + 未实跑 + 阻塞原因』」，并在 A10 末尾加一句「A09 的『记录』包含未实跑形态」；同步更新 `team/完整的审核一下我这个项目-060103/TASKS.json` 中 T14 的第 1 条 acceptance（`team/完整的审核一下我这个项目-060103/TASKS.json` · `逐条有` @ 655）。
- status: open

### F-RVW08 · SPEC §6.3 W14 的证据文件路径不存在
- severity: P3
- anchor: `team/完整的审核一下我这个项目-060103/SPEC.md` · `max_file_size` @ 260
- evidence: §6.3 W14 的证据写作「受扫 777 个 `.py` 中仅 2 个超 1200（`fastapi_app/tests/test_purchase_center.py` 1497、`fastapi_app/tests/test_recovery_service.py` 1353）」（`team/完整的审核一下我这个项目-060103/SPEC.md` · `max_file_size` @ 260）。只读文件存在性核对：`fastapi_app/tests/test_recovery_service.py` **不存在**；真实文件是 `fastapi_app/services/backup/orchestration/recovery_test_service.py`。PLAN §4 F-15 写的是正确名（`team/完整的审核一下我这个项目-060103/PLAN.md` · `recovery_test_service.py` @ 293），`team/REPOWIKI.md` · `max_file_size` @ 242 亦同。故为 SPEC 单侧笔误。
- impact: A20 要求「全工件 grep 白名单锚点」，W14 的锚点指向不存在的路径 ⇒ 该行白名单无法被机械核验；T14 按此路径查证会得出「文件不存在」的错误结论。
- fix-hint: 由 **pm** 把 §6.3 W14 的路径改为 `fastapi_app/services/backup/orchestration/recovery_test_service.py`。
- status: open

### F-RVW09 · PLAN §8 G3 的前提为假（SPEC §5.1 的 P1 / P2 / P3 均已各含 2 条编号规则）
- severity: P3
- anchor: `team/完整的审核一下我这个项目-060103/PLAN.md` · `未给` @ 425
- evidence: G3 称「SPEC §5.1 未给 P1 的两条可判定规则（现有 P1 为描述式，P0 有 4 条编号规则，P2 / P3 各 1 条）」（`team/完整的审核一下我这个项目-060103/PLAN.md` · `未给` @ 425）。实测 SPEC §5.1：P0 为 ①②③④ 四条（`team/完整的审核一下我这个项目-060103/SPEC.md` · `满足下列` @ 159）；**P1 为 ①② 两条编号规则**（`team/完整的审核一下我这个项目-060103/SPEC.md` · `满足下列` @ 160）；**P2 为 ①② 两条**（@ 161）；**P3 为 ①② 两条**（@ 162）。故「P1 为描述式」「P2 / P3 各 1 条」均不成立，G3 建议的「为 P0 / P1 / P2 / P3 各补足 2 条编号规则」已被现状满足，属**冗余修订**。
- impact: 若按 G3 执行，pm 会在无需改动的 §5.1 上再改一轮，引入版本漂移并使 AUTHORITY 的行号证据（本已错误，见 F-RVW05）进一步失真。
- fix-hint: 由 **architect** 将 G3 标记为「已满足 · 撤销」或改写为真实残留问题（若确有残留，须给出具体缺口行号）。
- status: open

### F-RVW10 · 任务状态投影与状态机口径不自洽（T20 用了未声明状态值；看板与已落盘产物不同步）
- severity: P3
- anchor: `team/完整的审核一下我这个项目-060103/任务看板.md` · `pending → claimed` @ 77
- evidence: （1）`team/完整的审核一下我这个项目-060103/任务看板.md` @ 77 声明的状态机为「`pending → claimed → in_progress → completed｜failed｜cancelled`」，另 `rework` 为 review 返工过渡态；而 T20 的 `status` 取值为 `blocked-by-user-decision`（`team/完整的审核一下我这个项目-060103/TASKS.json` · `blocked-by-user-decision` @ 1006），**不在该枚举内**；TASKS.json 亦未声明任何状态枚举，故该状态属未定义扩展，A25 / A26 的「任务状态时序」无法机判。（2）`team/完整的审核一下我这个项目-060103/任务看板.md` · `已派工待启动` @ 14 记「T03 / T04 已派工待启动」，但 `team/完整的审核一下我这个项目-060103/PLAN.md` · `本文由 architect` @ 431 与 `team/完整的审核一下我这个项目-060103/AUTHORITY.md` · `已知偏差` @ 74 均自述已由 architect（T03 / T04）冻结落盘；`team/完整的审核一下我这个项目-060103/TASKS.json` · `"status": "in_progress"` @ 110 记 T02 为 `in_progress`，而 SPEC.md 已完整冻结。状态投影落后于实际产物。
- impact: T17 以「任务状态时序」为 A25 证据时，读到的是计划期快照而非执行期事实；T20 的 blocked 语义无法被门禁脚本识别。不阻塞实现期，但削弱 A25 的可核对性。
- fix-hint: 由 **pm** 在 `team/完整的审核一下我这个项目-060103/任务看板.md` @ 77 的状态机中显式加入 `blocked-by-user-decision`（并说明与 `conditional` 的关系），并在每次派工 / 完成时刷新状态表；T20 的 `conditional` 字段语义建议在 TASKS.json 顶层补一段说明。
- status: open

## 门禁判定

- `A25`（T05 `verdict=pass` 后 T06–T14 才允许 `in_progress`）：**门禁保持关闭**。本文件 `verdict=needs_revision`，T06–T14 / T18 / T19 / T21 **不得**启动。
- 放行条件（须全部满足后由 reviewer 复审一次）：
  1. **architect** 改 `team/完整的审核一下我这个项目-060103/PLAN.md` §3.1 / §3.2 / `finding 契约`：补 `owner` + `status`（或由 lead 裁定改为引用 SPEC），消除 F-RVW01。
  2. **pm** 改 `team/完整的审核一下我这个项目-060103/SPEC.md` §9.1 前置① + A09：加入 `TEST_DATABASE_URL` 断言与「未实跑」记录形态，消除 F-RVW02 与 F-RVW07。
  3. **pm** 改 `team/完整的审核一下我这个项目-060103/SPEC.md` §6.3：补 W15–W18 并修正 @ 262 的上游行数，消除 F-RVW03；同时改 W14 路径（F-RVW08）。
  4. **pm** 改 `team/完整的审核一下我这个项目-060103/SPEC.md` A03：接受单串与三槽两种渲染，消除 F-RVW06。
  5. **architect** 改 `team/完整的审核一下我这个项目-060103/PLAN.md` §4 @ 274 / R7 / F-09 锚点（F-RVW04）与 §8 G3（F-RVW09）；改 `team/完整的审核一下我这个项目-060103/AUTHORITY.md` 定义式核对表 7 处行号（F-RVW05）。
  6. **pm** 改 `team/完整的审核一下我这个项目-060103/任务看板.md` 状态机（F-RVW10）。
- 未启动项确认：T20 保持 `blocked-by-user-decision`，未启动（`team/完整的审核一下我这个项目-060103/TASKS.json` · `blocked-by-user-decision` @ 1006），符合 Q1 / Q5 冲突按 Q1 冻结的裁定。
- 只读边界自证：本轮评审仅写入本文件（`team/完整的审核一下我这个项目-060103/REVIEW.md`），未修改任何业务代码、配置或他人权威文件；未执行 git 写操作、未起停服务、未连库、未跑 pytest 实体。

---

*本文件由 reviewer（T05）落盘。任何角色若认为上述 finding 不成立，须给出反证锚点，**不得**直接改本文件（唯一写者 = reviewer）。*
