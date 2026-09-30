# 事实单源化权威表（AUTHORITY）

> run：`完整的审核一下我这个项目-060103`｜作者：**architect（T04）**｜唯一写者：**architect**
> 本表声明本 run 的**事实单源化**：每一个原子事实只有一个**权威文件**、一个**写者**。
> 其它文件（各角色报告、`FINDINGS.json`、汇总、backlog）**只许引用**，不得另写定义。

## 权威表

| 事实名 | 权威文件 | 写者 |
|---|---|---|
| 严重度判定口径 | SPEC.md | pm |
| 只读边界 | SPEC.md | pm |
| 生产环境边界 | SPEC.md | pm |
| 命令清单 | SPEC.md | pm |
| 审核维度 | SPEC.md | pm |
| 白名单 | SPEC.md | pm |
| 工件命名与责任矩阵 | SPEC.md | pm |
| 需求一致性对照起点 | SPEC.md | pm |
| finding 契约 | PLAN.md | architect |
| 迁移权威 | PLAN.md | architect |
| 审核方法论 | PLAN.md | architect |
| 防伪影清单 | PLAN.md | architect |
| 风险与缓解 | PLAN.md | architect |
| 撤销率 | REVIEW.md | reviewer |

**表体 14 行**（不含表头与分隔行）。**每行三列，不得增减列。**
**第 1 列纪律**：全部为**单一原子事实名**；**不用反引号包裹**；**不用 `、` 或 `/` 做并列枚举**；每个名字都与其它名字**分属不同事实**（同一权威文件承载多个**互不重叠**的事实，不构成冲突）。

## 冲突裁决顺序（唯一）

1. **代码与实测输出** > `AGENTS.md` > 本 run 其它 `*.md`。
   依据：`SPEC.md` §0 元信息 · 判定权威 @ 9-30。
2. 文档之间冲突时按**事实域**分流：**口径类**（严重度判定口径 / 只读边界 / 生产环境边界 / 命令清单 / 审核维度 / 白名单 / 工件命名与责任矩阵 / 需求一致性对照起点）**以 `SPEC.md` 为准**；**契约与方法类**（finding 契约 / 迁移权威 / 审核方法论 / 防伪影清单 / 风险与缓解）**以 `PLAN.md` 为准**；**复核统计类**（撤销率）**以 `REVIEW.md` 为准**。三者不是「谁更正确」，而是**事实域不同**。
3. 与本 run 的**历史归档**（`deliverables/` 106 项、旧审核报告、`docs/deliverables/` 的引用）冲突时，**一律以代码与实测输出为准**，归档件只标注「已过期」。
4. `team/REPOWIKI.md` 与 `team/完整的审核一下我这个项目-060103/RESEARCH.md` 是**调研输入**，不是权威：与 `SPEC.md` / `PLAN.md` 冲突时按第 1 条裁决。

**「文档与代码冲突以代码为准」的三个已发生实例**（均已修复，正是本规则的来源）：

- **实例 1（凭据入库）**：2026-09-17 有 428 个 Edge 凭据入库。原因是 `core.hooksPath` 指向**并不存在**的 `.githooks`，且 `.git/hooks/pre-commit` 也不存在——**配置/文档声明的守卫与代码实际状态不一致**，以实际状态为准才发现守卫根本没生效。现 `.githooks/pre-commit` 三层守卫已就位。依据：`RESEARCH.md` §5.1 @ 186-190；`REPOWIKI.md` §6.3。
- **实例 2（erp-arq 无限重启）**：2026-09-16 事故。`_SVC_DEPENDS` 未声明 `DependOnService`，服务在 Redis 就绪前启动即退出并被 NSSM 无限拉起。**拓扑文档写「erp-arq 依赖 redis-broker」，代码里并没有这条依赖**，以 `server_manager/constants.py` 的实际值为准才定位到根因。依据：`REPOWIKI.md` §4；`RESEARCH.md` §5.1。
- **实例 3（15 个迁移 head / 48 个孤儿端点）**：两份历史报告写「15 个迁移 head」「48 个端点未接线」。用 `alembic ScriptDirectory` 与 `ast` 全仓导入图实测：**单 head**、**零孤儿**（`fastapi_app/api/v1/router.py` · `api_router.include_router(` @ 46 共 34 次挂载）。报告文字与代码事实冲突，以代码为准。依据：`RESEARCH.md` §5.1 / §5.3；`REPOWIKI.md` §7.1 @ 213-215。

## 迁移权威的结论与依据

**结论**：`migrations/env.py` 是**迁移运行期的元数据与连接权威**；`alembic.ini` 只是 **Alembic 的入口配置文件**，其 `sqlalchemy.url` **会被代码覆盖**，因此不是连接与元数据的权威。

- 依据一（覆盖事实）：`migrations/env.py` · `target_metadata = Base.metadata` @ 57；同文件用 `get_sync_engine()` **覆盖** `sqlalchemy.url`（`REPOWIKI.md` §8 记 `migrations/env.py:56`）。
- 依据二（配置文件地位）：`alembic.ini` 于 2026-09-30 补入（`SPEC.md` §10 · S1 @ 410-411），**必须为纯 ASCII**（`REPOWIKI.md` §7.2）；它提供 `script_location` 等入口参数，不定义 schema 真相。
- 依据三（单一 head 的权威判据）：迁移图拓扑的权威判据是 **`alembic ScriptDirectory` 的实际解析**（`scripts/check_alembic_heads.py`，`EXPECTED_MAX_BASES = 4`），**不是**任何 `*.md` 里的文字，也**不是**只用 `ast.Assign` 的自制脚本（会漏 `AnnAssign`，见防伪影 F-19）。唯一 head = `migrations/versions/pg_standalone_060_fix_updated_at_varchar_columns.py` · `revision=` @ 42。
- 推论：任何角色写「迁移权威是 `alembic.ini`」或「迁移权威是某份报告」均为**错误**，T15 应判 `rejected`。

## 定义式逐条核对（第 1 列 × 权威文件）

五种合法定义式：`## 名`（含 `### 5.1 名` 这类编号标题）· `**名**：` · 两列表格 `| 名 | 定义 |` · `「名」：` · `- 名：`。
下表由 `architect` 用脚本逐条核对，**命中行号即证据**（行号一律取**落盘时刻**的实测值：`SPEC.md` 于 T02 修订第二批新增 §6.3 `W15`–`W18` 后，`### 9.2 命令清单` 与 `## 11. 需求一致性对照起点` 各后移 9 行；任何权威文件再改都必须重算本表）。

| 事实名 | 权威文件 · 命中定义式 | 命中位置（锚点 @ 行号） |
|---|---|---|
| 严重度判定口径 | SPEC.md · `### 5.1 严重度判定口径` | `SPEC.md` · `### 5.1 严重度判定口径` @ 155 |
| 只读边界 | SPEC.md · `### 6.1 只读边界` | `SPEC.md` · `### 6.1 只读边界` @ 226 |
| 生产环境边界 | SPEC.md · `### 6.2 生产环境边界` | `SPEC.md` · `### 6.2 生产环境边界` @ 234 |
| 命令清单 | SPEC.md · `### 9.2 命令清单` | `SPEC.md` · `### 9.2 命令清单` @ 364 |
| 审核维度 | SPEC.md · `### 2.1 审核维度` | `SPEC.md` · `### 2.1 审核维度` @ 52 |
| 白名单 | SPEC.md · `### 6.3 白名单` | `SPEC.md` · `### 6.3 白名单` @ 243 |
| 工件命名与责任矩阵 | SPEC.md · `### 2.2 工件命名与责任矩阵` | `SPEC.md` · `### 2.2 工件命名与责任矩阵` @ 74 |
| 需求一致性对照起点 | SPEC.md · `## 11. 需求一致性对照起点` | `SPEC.md` · `## 11. 需求一致性对照起点` @ 446 |
| finding 契约 | PLAN.md · `### finding 契约` | `PLAN.md` · `### finding 契约` @ 226 |
| 迁移权威 | PLAN.md · `### 迁移权威` | `PLAN.md` · `### 迁移权威` @ 260 |
| 审核方法论 | PLAN.md · `## 1. 审核方法论` | `PLAN.md` · `## 1. 审核方法论` @ 11 |
| 防伪影清单 | PLAN.md · `## 4. 防伪影清单` | `PLAN.md` · `## 4. 防伪影清单` @ 271 |
| 风险与缓解 | PLAN.md · `## 5. 风险与缓解` | `PLAN.md` · `## 5. 风险与缓解` @ 307 |
| 撤销率 | REVIEW.md · `## 撤销率` | `REVIEW.md` · `## 撤销率` @ 7 |

## 已知偏差（architect 只报告，不改他人工件）

| # | 偏差 | 归属 | 处置建议 |
|---|---|---|---|
| A1 | **原定第 1 列 `质量门禁命令` 在 `SPEC.md` 中不是五种定义式之一**：@ 26 是 §0.1 澄清结论表的一行（`| Q2 生产环境边界 | 允许跑质量门禁命令（pytest / ruff / mypy / npm test / npm run type-check） |`），事实存在但形态不合规。**已按纪律改用 `命令清单`**（`SPEC.md` · `### 9.2 命令清单` @ 364，即质量门禁命令 C01–C12 的权威定义处） | pm | 若 pm 仍希望保留 `质量门禁命令` 这个名字，须在 `SPEC.md` §6.2 增一行定义式（如 `- 质量门禁命令：见 §9.2 命令清单 C01–C12`），再回本表登记 |
| A2 | **（已消解）`撤销率` 在 `REVIEW.md` 中已有定义体**（`REVIEW.md` · `## 撤销率` @ 7；原「10 行空模板 / 关键词 0 命中」描述作废） | reviewer | 已由 reviewer 于 T05 落盘；T15 只须维护数值，`SPEC.md` §1 第 3 条的计算口径（被撤销条数 ÷ 提交条数）@ 41 不变 |
| A3 | 本表第 1 列**刻意不用反引号、不用 `、`/` 做并列枚举**；加行必须**先**在权威文件写出定义式、**再**回本表登记（顺序不可颠倒） | architect | 违规加行由 T05 判 `needs_revision` |
| A4 | 同一权威文件有多个写者会违反校验规则——本表 `SPEC.md` 只有 pm、`PLAN.md` 只有 architect、`REVIEW.md` 只有 reviewer | 全体 | 任何角色**不得**改别人的权威文件；需要新事实时**请求**该文件的写者补写 |

---

*本表由 architect（T04）冻结。第 1 列的任何改动都必须伴随权威文件里的定义式同步落盘；顺序颠倒即为违规。*
