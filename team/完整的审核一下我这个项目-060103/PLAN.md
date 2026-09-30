# 审核方法论与计划（PLAN）

> run：`完整的审核一下我这个项目-060103`｜作者：**architect（T03）**｜唯一写者：**architect**
> 本文冻结「**怎么审**」：方法论、证据标准、维度→产出映射、finding 签名契约、防伪影闸门、风险与缓解、DAG。
> **口径引用纪律**：严重度口径、只读边界、生产环境边界、质量门禁命令的**唯一定义在 `SPEC.md`**，本文**只引用不另立**；
> finding schema 与防伪影清单的**唯一定义在本文**（`PLAN.md`），各角色报告只许引用。
> 判定优先级（`SPEC.md` §0 元信息）：代码与实测输出 > `AGENTS.md` > 其它 `*.md` 报告。

---

## 1. 审核方法论（逐维度：方法 / 能证明什么 / 不能证明什么）

> 方法代号：**M-AST**（Python `ast` 解析）· **M-IMP**（全仓导入图）· **M-CONTRACT**（契约比对）· **M-CFG**（配置审计）· **M-DEP**（依赖审计）· **M-RUN**（真机只读命令）· **M-READ**（人工只读阅读）
> **强制**：任何结构类结论（导入关系、迁移依赖图、`__init__.py` 聚合、端点挂载）**只能用 M-AST / M-IMP**；用 grep / 正则得出的结构结论**一律不接受**（`AGENTS.md` §6 · `fastapi_app/api/v1/router.py` · `api_router.include_router(` @ 46 是历史伪影的现场）。

### 1.1 架构与模块边界（SPEC D01 · T06 · architect）

| 项 | 内容 |
|---|---|
| 方法 | **M-AST + M-IMP + M-READ**：`ast.parse` 全仓 `.py` 建导入图；对 `fastapi_app/api/v1/endpoints/` 每个模块求「是否可从 `fastapi_app/api/v1/router.py` 经 import 链到达」；对 `endpoints/` 判「是否直接出现 `AsyncSession` / `select(` 而绕过 `services/`」 |
| 能证明 | 模块可达性（零孤儿 / 真孤儿）、循环导入、`endpoints/` 是否直连 DB、`__init__.py` 聚合路径、目录职责与 `AGENTS.md` §2 表的偏差 |
| 不能证明 | 运行时动态导入（`importlib`、`__getattr__` 惰性导出）与条件导入分支的**实际**执行路径；运行期才成立的依赖注入链；「模块可达」≠「功能正确」 |

### 1.2 后端代码（SPEC D02 · T07 · backend）

| 项 | 内容 |
|---|---|
| 方法 | **M-AST + M-READ + M-RUN**：AST 探针复算 `bare_except`（基线 9）、函数 >80 行（基线 52）、N+1（基线 0）、service 层自行 commit（基线 9）；逐端点核对 `Depends(` 鉴权注入；人工读 `fastapi_app/api/v1/endpoints/` 契约与 `fastapi_app/schemas/` |
| 能证明 | 静态违规计数（与 `scripts/gate_baseline.json` 逐项对照）、鉴权依赖的**声明**位置、事务边界的**代码形状**、请求/响应模型的**声明**字段 |
| 不能证明 | 端点的实际运行时行为（状态码、异常路径、序列化结果）；并发下的真实事务交错；未被执行分支中的缺陷 |

### 1.3 前端代码（SPEC D03 · T08 · frontend）

| 项 | 内容 |
|---|---|
| 方法 | **M-RUN + M-CONTRACT + M-READ**：实跑 `npm run type-check` / `npm run lint` / `npm run check:api` / `check:routes` / `check:dto`；`vite.config.js` 与 `vite.config.ts` 一致性（回归测试 `fastapi_app/tests/test_qa_prod_stack_regression.py` 已断言，**不得**判为重复文件）；`any` / `@ts-ignore` 密度统计；前端 API 客户端 vs 后端路由漂移比对 |
| 能证明 | 类型/lint 的**客观**错误集、五个对齐脚本**实际**覆盖到的漂移、组件长度超基线清单、设计产物一致性 |
| 不能证明 | 视觉与交互正确性、真机浏览器行为、跨页实时失效与 WebSocket 断线重连（**无 e2e 脚手架**，见 §4 防伪影 F-09） |

### 1.4 数据库与迁移（SPEC D04 · T09 · dba）

| 项 | 内容 |
|---|---|
| 方法 | **M-AST + M-CFG + M-READ**：解析 `migrations/versions/` 的 `revision` / `down_revision`，**必须同时处理 `ast.Assign` 与 `ast.AnnAssign`**；与 `scripts/check_alembic_heads.py`（alembic `ScriptDirectory`，`EXPECTED_MAX_BASES=4`）交叉；`fastapi_app/shared_models/` 的 `Base.metadata` vs 迁移 DDL 比对；索引与高频查询匹配 |
| 能证明 | 迁移图拓扑（head 数 / root 数 / 悬空 parent）、迁移**声明**的 DDL、模型**声明**的列与约束、`alembic.ini` 与 `migrations/env.py` 谁是权威（`migrations/env.py` · `target_metadata = Base.metadata` @ 57） |
| 不能证明 | **生产库的实际 schema 状态**（`alembic current` 是否 == head 需只读 SQL，见 `RESEARCH.md` §7 U3）；真实数据分布下的索引选择性；大表 DDL 的实际锁等待 |

### 1.5 安全（SPEC D05 · T10 · sec）

| 项 | 内容 |
|---|---|
| 方法 | **M-CFG + M-READ + M-RUN + M-AST**：只读密钥扫描 `scripts/scan_secrets.py`（入口 `def main(argv: list[str] | None = None) -> int:` @ 237）与 `.githooks/allowlist.txt` 豁免合理性；`Get-Acl`（只读）核对 `_ops/credentials/` ACL；AST 查 SQL 拼接 / `text(` / 路径穿越；读 `config/security-headers.conf`、CORS、uvicorn 绑定面、`/metrics` 暴露面；备份加密**静默降级**的代码路径链 |
| 能证明 | 仓库内明文密钥与凭据入库面、豁免清单的合理性、认证依赖的**声明**覆盖面、配置层暴露面（绑定地址 / 安全头 / CORS）、静默降级的**代码路径** |
| 不能证明 | 真实渗透结果（**本轮不做渗透、不打生产**）；运行进程**实际**加载的是哪个 env 文件（`RESEARCH.md` §7 U1，需读 NSSM 参数）；密钥是否已在外部泄露 |

### 1.6 运维 / 部署 / CI（SPEC D06 · T11 · devops）

| 项 | 内容 |
|---|---|
| 方法 | **M-CFG + M-READ + M-RUN**：读 `server_manager/constants.py` 的 `_SVC_ALL` / `_SVC_DEPENDS` / `_SVC_UVICORN_WORKERS`；读 `config/nginx-windows.conf` 与死配置 `config/nginx.conf`；读 `logs/prod_runner.json` 健康口径（需 `ready: true` 且 `frontend_ok: true`）；读 `.github/workflows/ci-cd.yml` 三 job；读 `.githooks/pre-commit` 四层与 `pre-commit` 缺失降级；`schtasks /query`（只读）核对看门狗计划任务 |
| 能证明 | 服务拓扑、端口、依赖关系的**声明**真源；配置生效性判定；CI 步骤**声明**；提交守卫分层；计划任务存在性 |
| 不能证明 | 5 个服务**此刻**是否真的在运行（`nssm status` / `Get-Service` 属只读，但**不得**启停）；计划任务是否真的成功执行过；NSSM 参数与仓库声明是否一致（需 `nssm get`，见 U1） |

### 1.7 文档（SPEC D07 · T12 · docs）

| 项 | 内容 |
|---|---|
| 方法 | **M-READ + M-CONTRACT**：把 `AGENTS.md` / `README.md` / `CHANGELOG.md` / `docs/**/*.md` 中每条**可验证断言**抽出，逐条对照代码给「一致 / 不一致 / 无法验证」三态；`deliverables/` 与旧报告**只标注过期，不重审** |
| 能证明 | 文档与代码的**偏差清单**、过期结论的定位 |
| 不能证明 | 文档未写但代码存在的意图；历史决策的**动机**（动机只能来自 `docs/adr/` 与提交信息，且可能过期） |

### 1.8 UI / UX（SPEC D08 · T13 · ui）

| 项 | 内容 |
|---|---|
| 方法 | **M-READ + M-CONTRACT + M-CFG**：读 `frontend-vite/src/router` 与导航配置比对；菜单可见性 vs 后端鉴权锚点做矩阵；抽查 ≥15 个页面的空 / 加载 / 错误三态；可访问性静态检查（label 关联、键盘可达、对比度 token）；响应式断点；`mockups/` vs 实现偏差 |
| 能证明 | 源码层的三态缺失、可见性与鉴权的不一致、a11y 静态缺陷、断点声明 |
| 不能证明 | 真机/真浏览器的渲染结果、实际对比度测量、屏幕阅读器行为（**本轮不启动前端服务**，见 §5 风险 R1） |

### 1.9 测试与质量门禁（SPEC D09 · T14 · qa）

| 项 | 内容 |
|---|---|
| 方法 | **M-RUN**：先做 `SPEC.md` §9.1 实跑前置（`tests/conftest.py` 与 `fastapi_app/tests/conftest.py` 静态确认无写库、`pytest --collect-only -q`、Node ≥ 22），再逐条实跑 §9.2 的 C01–C12；每条记录**命令 + 工作目录 + 退出码 + 原始输出片段**；`quality_gate.py` 退出码与 `scripts/gate_baseline.json` 八项计数对照 |
| 能证明 | 门禁的**真实**通过/失败状态、覆盖率**实测**分布、测试对生产库/网络的隐式依赖、八项基线的**独立**计数 |
| 不能证明 | 未跑用例覆盖的行为；「跑绿」≠「无缺陷」（3338 个用例之外的路径）；被 `--ignore` 排除目录内的行为 |

### 1.10 需求一致性（SPEC D10 · T06 + T12 · architect + docs）

| 项 | 内容 |
|---|---|
| 方法 | **M-CONTRACT**：取 `SPEC.md` §11 的 P1–P12 断言清单（出处 `AGENTS.md` §2/§3/§4/§5），逐条实测给三态；端点挂载数 vs `endpoints/` 模块数用 M-AST |
| 能证明 | 契约与代码的**逐条**一致性；「零孤儿」「单 head」「5 个 NSSM 服务」「唯一入口 `start.py`」等断言的真伪 |
| 不能证明 | 契约**未**声明但业务依赖的隐含约定；三态中「无法验证」项的真相（必须如实标 `无法验证`，不得猜） |

### 1.11 依赖与供应链（**T21 新增** · sec + devops）

| 项 | 内容 |
|---|---|
| 方法 | **M-DEP + M-READ**：`requirements/*.txt`（依赖唯一真源，`pyproject.toml` **刻意无** `[project]` / `[build-system]`）与 `frontend-vite/package.json` 的钉版核对；只读跑 `bandit` / `pip-audit`（CI 已在 `.github/workflows/ci-cd.yml` 声明）；`# nosec` 预算 `scripts/check_nosec_budget.py`；Node ≥ 22 硬约束 |
| 能证明 | 钉版与浮动范围、已知 CVE 面（以扫描器输出为准）、可选依赖分拆（`ocr.txt` / `migration.txt` / `s3.txt` / `desktop.txt`）、豁免预算余量 |
| 不能证明 | 第三方包**内部实现**的安全性与许可证合规（`SPEC.md` §3 明确 Out of Scope）；CVE 库的时效性；传递依赖的真实解析结果（无 lockfile 全貌时） |

### 1.12 性能与容量（SPEC D11/D12 · T18 + T19 · backend + dba）

| 项 | 内容 |
|---|---|
| 方法 | **M-AST + M-CFG + M-READ**：N+1（基线 0）、慢查询与缺失索引、连接池（pgbouncer）、Redis 缓存键与失效策略、ARQ 队列积压口径、日志分级与脱敏、`config/prometheus.yml` / `grafana/` / `otel-collector.yaml` / `promtail.yml` **是否真正接线**；`service_commit` 基线 9、并发同键的唯一约束 vs 应用层查重、跨模块守恒校验点 |
| 能证明 | 配置是否接线、静态性能反模式、事务边界与约束的**声明**、可观测性链路的存在性 |
| 不能证明 | **QPS / P95 / 内存 / 连接池真实占用**——**本轮禁止压测**（`SPEC.md` §6.2）；索引在生产数据分布下的真实效果；队列积压的实时值 |

---

## 2. 维度划分与产出映射（12 维度 → 角色 → 工件 → 证据形态）

> **编号对照**：用户点名的 12 维度（第 1 列）与 `SPEC.md` §2.1 的 D01–D12 编号**并非一一同名**，第 2 列给出 SPEC 编号与**命名差异**；两者都不得删减（`SPEC.md` §2.1「只增不减」）。
> **工件路径一律相对 run-dir**：`team/完整的审核一下我这个项目-060103/`。

| # | 维度（用户点名） | SPEC 编号 · 命名差异 | 归属角色 | 任务 | 产出工件 | 证据形态 |
|---|---|---|---|---|---|---|
| 1 | 架构 | D01 架构与模块边界 | architect | T06 | `AUDIT-ARCH.md` | AST 导入图 + 计数 + 脚本片段；`路径 · 锚点 @ 行号` |
| 2 | 后端 | D02 后端代码 | backend | T07 | `AUDIT-BACKEND.md` | AST 计数 vs 基线；逐端点鉴权清单；契约表 |
| 3 | 前端 | D03 前端代码 | frontend | T08 | `AUDIT-FRONTEND.md` | 五脚本实跑原始输出；漂移清单；超基线组件清单 |
| 4 | 数据库与迁移 | D04 数据库与迁移 | dba | T09 | `AUDIT-DB.md` | `migration_heads` 原始值；模型 vs DDL 差异表 |
| 5 | 安全 | D05 安全 | sec | T10 | `AUDIT-SEC.md` | OWASP Top 10 十行表 + 等保基线；扫描器原始输出 |
| 6 | 运维部署CI | D06 运维 / 部署 / CI | devops | T11 | `AUDIT-OPS.md` | 五服务配置锚点；生效性判定；CI 步骤锚点 |
| 7 | 文档 | D07 文档 | docs | T12 | `AUDIT-DOCS.md` | 断言对照表（一致 / 不一致 / 无法验证）+ 过期标注 |
| 8 | UI-UX | D08 UI / UX | ui | T13 | `AUDIT-UIUX.md` | 菜单 × 鉴权矩阵；三态抽查清单；a11y 逐条锚点 |
| 9 | 测试与门禁 | D09 测试与质量门禁 | qa | T14 | `TEST.md` | 命令 + 退出码 + 原始输出**三元组**；八项基线对照表 |
| 10 | 需求一致性 | D10 需求一致性 | architect + docs | T06 + T12 | `AUDIT-ARCH.md` §一致性 + `AUDIT-DOCS.md` §一致性 | P1–P12 逐条三态对照表 |
| 11 | 依赖与供应链 | **SPEC 无对应编号（缺口）** | sec + devops | **T21（新增）** | `AUDIT-DEPS.md` | `bandit` / `pip-audit` 原始输出；钉版表；`# nosec` 预算 |
| 12 | 性能与容量 | D11 性能与可观测性 + D12 数据一致性与并发 | backend + dba | T18 + T19 | `AUDIT-PERF.md` + `AUDIT-CONSISTENCY.md` | 接线判定表；N+1 计数；commit 位置清单；守恒校验点 |

### 2.1 维度间交叉验证点（**≥8 条 · 必须逐条执行并贴证据**）

> 单维度自证不足以定案；下列交叉点必须由**两个不同角色**各自给出证据，冲突时按 §8 裁决顺序处理，冲突本身记入 `REVIEW-CROSS.md`。

| # | 交叉验证点 | 维度 A（举证） | 维度 B（复核） | 一致判据 | 不一致时的处置 |
|---|---|---|---|---|---|
| X1 | **端点可达性**：`endpoints/` 模块数 vs `router.py` 的 `include_router` 次数 | D01 架构（AST 导入图） | D02 后端（逐端点鉴权清单） | 两方得出**同一**端点集合 | 按 F-20 判伪影；仍不一致 ⇒ 记 `REVIEW-CROSS.md` |
| X2 | **迁移图拓扑**：head 数 / root 数 / 悬空 parent | D04 数据库（`ScriptDirectory`） | D09 门禁（`check_alembic_heads.py` 退出码） | 两方均为「单 head / 4 roots / 零悬空」 | 按 F-19 判伪影；冲突以 `ScriptDirectory` 为准 |
| X3 | **模型 vs DDL**：`shared_models/` 的 `Base.metadata` vs `migrations/versions/` 的 DDL | D04 数据库 | D02 后端（模型使用点） | 列名/类型/可空性逐项一致 | 差异按「代码与实测输出优先」定级 |
| X4 | **运行时实际加载的 env**：`.env.production` 的 `BACKUP_ENCRYPTION_PASSWORD` | D05 安全（配置审计） | D06 运维（NSSM 参数，U1） | 两边指向**同一** env 文件与同一取值 | 无法确定 ⇒ 标 `无法验证`，不得推测 |
| X5 | **备份加密语义**：全量 vs 增量在密码为空时的行为 | D05 安全（`services/backup/crypto.py`） | D12 一致性（`services/backup/incremental.py`） | 两方一致确认「全量静默不加密 / 增量硬失败」 | 语义不一致本身即 finding（归主责维度） |
| X6 | **测试覆盖 vs 业务域**：板房 / 死信队列是否有专用测试 | D09 门禁（`TEST.md` 实测） | D10 需求一致性（P1–P12 断言） | 覆盖矩阵与业务域清单可对齐 | 零覆盖域必须在两方工件中**同名**出现 |
| X7 | **文档断言 vs 代码事实**：`AGENTS.md` / `README.md` 的可验证断言 | D07 文档（断言三态表） | D01/D06（代码与拓扑实测） | 每条断言落到「一致 / 不一致 / 无法验证」 | 不一致以代码为准，并计入 D07 finding |
| X8 | **前端对齐脚本 vs 后端路由**：`check:api` / `check:routes` / `check:dto` 的结论 | D03 前端（脚本原始输出） | D02 后端（路由与 schema 真源） | 脚本报 0 漂移 ⇔ 后端确有对应路由/schema | 脚本「绿」但后端无对应项 ⇒ 记脚本覆盖面缺口 |
| X9 | **依赖钉版 vs 运行时实际引入**：`requirements/*.txt` 与前端 `package.json` | D13 依赖与供应链（钉版表） | D06 运维（部署脚本实际安装命令） | 安装源与钉版一致 | 部署脚本装了清单外的包 ⇒ 记 D06 finding |
| X10 | **性能反模式 vs 真实索引**：N+1 计数与缺失索引 | D11 性能（静态计数） | D04 数据库（索引清单） | 高频查询均有可用索引 | 无索引的静态反模式按「静态可证」定级，**不得**声称实测性能 |
| X11 | **只读边界自身**：本次 run 是否真的没改业务代码 | D06 运维（`git status --porcelain` 前后快照） | T17 交付前门禁（A21 比对） | 快照集合 == 审核开始时快照（见 §5 R5） | 出现新增改动 ⇒ T17 必须 `verdict=needs_revision` |

**汇总与门禁工件**（非维度）：

| 任务 | 角色 | 工件 | 证据形态 |
|---|---|---|---|
| T05 | reviewer | `REVIEW.md` | 规格评审 verdict + 不可判定项清单 |
| T15 | reviewer | `FINDINGS.json` + `REVIEW-CROSS.md` | 全量 finding + 撤销率 + 撤销清单 |
| T16 | pm | `SUMMARY.md` + `BACKLOG.md` | 12 维度结论表 + 健康度评分 + 四要素 backlog |
| T17 | qa | `GATE.md` | A01–A26 逐条映射 + 最终 verdict |

**角色编制（12 角色）**：researcher · pm · architect · reviewer · backend · frontend · dba · sec · devops · docs · ui · qa。

---

## 3. finding 的 JSON Schema（**签名级契约 · 冻结**）

> **本 schema 是全部角色报告的唯一合法结构**（表格或 JSON 均可，**字段名不得改**）。
> **唯一定义在本文**；`SPEC.md` §5.2 的 `F-` 文本形态视为本 schema 的**渲染形态**，二者字段一一对应（见 §3.2 映射）。

### 3.1 Schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "finding",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "id", "dimension", "severity", "owner", "status", "title", "file", "anchor", "line",
    "evidence", "impact", "recommendation", "verify", "confidence", "reverted"
  ],
  "properties": {
    "id": {
      "type": "string", "pattern": "^FIND-[A-Z0-9]+-[0-9]{3}$",
      "description": "形如 FIND-<维度>-<序号>；跨轮稳定（复核/返工/合并后不得改 id）"
    },
    "dimension": {
      "type": "string", "enum": ["D01","D02","D03","D04","D05","D06","D07","D08","D09","D10","D11","D12","D13"],
      "description": "D13 = 依赖与供应链（本 PLAN §2 新增维度）；枚举值即 SPEC §2.1 编号"
    },
    "severity": {
      "type": "string",
      "enum": ["P0","P1","P2","P3"],
      "description": "口径唯一定义在 SPEC.md §5.1（严重度判定口径）；本文不另立"
    },
    "owner": { "type": "string", "enum": ["pm","architect","researcher","ui","backend","frontend","dba","sec","reviewer","qa","devops","docs"], "description": "finding 的归属角色；枚举 = 本 PLAN §2 的 12 个角色 id（与 TASKS.json 的 assignee 同集）" },
    "status": { "type": "string", "enum": ["open","confirmed","rejected","merged"], "default": "open", "description": "逐条终态（SPEC.md A05 / A22）；硬性一致规则 status=rejected ⇔ reverted=true（见 §3.3 第 6 条）" },
    "title": { "type": "string", "minLength": 8, "maxLength": 80 },
    "file": {
      "type": "string",
      "description": "仓库相对路径，**必须带目录**（如 fastapi_app/services/backup/crypto.py）；不得只写文件名"
    },
    "anchor": {
      "type": "string",
      "minLength": 1,
      "pattern": "^[^0-9@]*$",
      "description": "函数名 / 字段名 / 唯一字符串；**内部不得嵌行号、不得含 @**（行号只能进 line）"
    },
    "line": { "type": "integer", "minimum": 1 },
    "evidence": {
      "type": "string",
      "minLength": 20,
      "description": "复现步骤 或 推理链（P0/P1 必填且必须可被第三方独立重放）"
    },
    "impact": { "type": "string", "minLength": 10, "description": "对生产的具体影响" },
    "recommendation": { "type": "string", "minLength": 10, "description": "整改方向；本轮只给方向，不改代码" },
    "verify": { "type": "string", "minLength": 5, "description": "复核/复现命令或步骤（T15 据此复核）" },
    "confidence": { "type": "string", "enum": ["high","medium","low"] },
    "reverted": { "type": "boolean", "description": "是否已被 T15 撤销（初值恒为 false）" }
  }
}
```

**字段数 = 15**（`id` / `dimension` / `severity` / `owner` / `status` / `title` / `file` / `anchor` / `line` / `evidence` / `impact` / `recommendation` / `verify` / `confidence` / `reverted`）。**硬性一致规则**：`status=rejected` ⇔ `reverted=true`（二者互为充要；`status=merged` 时 `reverted` 必须为 `false`）。

### finding 契约

**定义**：`finding 契约` = §3.1 的 JSON Schema + §3.3 的 7 条硬性校验规则，二者**共同且唯一**地定义一条 finding 的合法形态；**字段数 15**（`id` / `dimension` / `severity` / `owner` / `status` / `title` / `file` / `anchor` / `line` / `evidence` / `impact` / `recommendation` / `verify` / `confidence` / `reverted`）。

- 唯一写者：**architect**（本文件）。
- 唯一权威文件：**`PLAN.md`**；各角色报告、`FINDINGS.json`、`REVIEW-CROSS.md` 只许**引用**，不得另立字段或改字段名。
- 冲突处置：与 `SPEC.md` §5.2 / §5.3 的形态差异**不是冲突**，而是**渲染对照**（见 §3.2）；字段名一律以本契约的 15 个为准。

### 3.2 与 `SPEC.md` §5.2 / §5.3 的字段映射（**不是第二套 schema，只是渲染对照**）

| 本 schema | SPEC §5.2 文本形态 | SPEC §5.3 `FINDINGS.json` | 说明 |
|---|---|---|---|
| `id` | `F-<维度><序号>` | `id`（`F-D05-001`） | 统一为 `FIND-<维度>-<序号>`，**跨轮稳定** |
| `file` + `anchor` + `line` | `anchor: <路径> · <锚点> @ <行号>` | `anchor`（单串） | 本 schema **拆三槽**；渲染回单串时用 ` · ` 与 ` @ ` 连接 |
| `recommendation` | `fix-hint` | `fixHint` | 同义，取本 schema 名 |
| `dimension` | 维度号（`D05`） | `dimension` | 一致 |
| `severity` | `severity` | `severity` | 一致；口径在 `SPEC.md` §5.1 |
| `evidence` / `impact` | 同名 | 同名 | 一致 |
| `verify` / `confidence` / `reverted` | 无 | 无 | **本 schema 新增**：`verify` 供 T15 复核，`confidence` 供撤销率归因，`reverted` 供统计（与 `status` 的充要关系见 §3.1） |
| `title` | 标题行 | 无 | **本 schema 新增** |
| `owner` / `status` | `status: open\|confirmed\|rejected\|merged` | `owner` / `status` / `stats` | **`owner` 为本 schema 新增**（枚举 = 12 角色 id）；`status` 逐条落 `FINDINGS.json`（SPEC.md A22 机判），聚合统计**沿用 SPEC §5.3 的 `stats`**（`submitted` / `confirmed` / `rejected` / `merged` / `revocationRate`），由 T15 维护 |

### 3.3 硬性校验规则（T15 逐条执行）

1. `id` 唯一且匹配 `^FIND-[A-Z0-9]+-[0-9]{3}$`；**跨轮稳定**。
2. `anchor` 不得含数字与 `@`（行号只能进 `line`）——防止「锚点里嵌行号」导致行号漂移后无法定位。
3. `file` 必须带目录前缀；只写文件名判**不合格**。
4. `severity` ∈ {P0,P1,P2,P3}，判定口径**只引** `SPEC.md` §5.1。
5. `confidence = low` 且 `severity ∈ {P0,P1}` ⇒ 必须降级为 P2 或撤销（`SPEC.md` §7 B11 同口径）。
6. `reverted = true` ⇒ 必须出现在 `REVIEW-CROSS.md` 的撤销清单中并给理由；且 **`status=rejected` ⇔ `reverted=true`**（互为充要，任一侧不成立即该 finding 不合格）。
7. 命中 §4 防伪影清单任一条 ⇒ **不得上报**；已上报者 T15 判 `rejected` 并计入撤销率。

---

### 迁移权威

**结论**：`migrations/env.py` 是**迁移运行期的元数据与连接权威**；`alembic.ini` 只是 Alembic 的**入口配置文件**，其 `sqlalchemy.url` 会被代码覆盖，因此不是连接与元数据的权威。迁移图拓扑的权威判据是 **`alembic ScriptDirectory` 的实际解析**（`scripts/check_alembic_heads.py`，`EXPECTED_MAX_BASES = 4`），不是任何 `*.md` 文字，也不是只用 `ast.Assign` 的自制脚本。

- 依据一（覆盖事实）：`migrations/env.py` · `target_metadata = Base.metadata` @ 57；同文件用 `get_sync_engine()` **覆盖** `sqlalchemy.url`（`REPOWIKI.md` §8 记 `migrations/env.py:56`）。
- 依据二（配置文件地位）：`alembic.ini` 于 2026-09-30 补入（`SPEC.md` §10 · S1 @ 410-411），**必须为纯 ASCII**（`REPOWIKI.md` §7.2）；它提供 `script_location` 等入口参数，不定义 schema 真相。
- 依据三（单 head 判据）：唯一 head = `migrations/versions/pg_standalone_060_fix_updated_at_varchar_columns.py` · `revision=` @ 42，共 99 个迁移文件、4 个 root、零悬空（`SPEC.md` §9.4 @ 368-406）。
- **推论**：任何角色写「迁移权威是 `alembic.ini`」或「迁移权威是某份报告」均为**错误**，T15 应判 `rejected`。

---

## 4. 防伪影清单（**原样收录** `REPOWIKI.md` §7.4 表体 9 行 + `RESEARCH.md` §5.2 表体 13 行；两表去重 14 条）

> **以下现象不是缺陷。任何角色不得上报为 finding。** 命中即由 T15 判 `rejected`，并计入撤销率（`SPEC.md` §6.3 同口径）。
> 去重说明：两张表**内容高度重叠**（源表分别 9 行与 13 行），原始 **22 行**（`REPOWIKI.md` §7.4 表体 9 行 @ 234–242 + `RESEARCH.md` §5.2 表体 13 行 @ 195–207），去重 **14 条**；本表共 **18 行 F 项**（其中 14 条来自两张上游表，另 4 条来自 `SPEC.md` §6.3 与 `REPOWIKI.md` §7.1）。
> 这是本轮**控制幻觉率的第一道闸**。

| # | 现象（锚点） | 真相 | 证据锚点 |
|---|---|---|---|
| F-01 | `logs/prod_runner.json` 里 `services.arq.status = "external"` | **正常设计**：`erp-prod` 以 `--no-arq` 启动，ARQ 由 NSSM `erp-arq` 单独托管，不在 prod_runner 进程树内 → `pid` 恒 None | `fastapi_app/core/prod_runner.py` · `status` @ 440-443；`RESEARCH.md` §5.2 @ 195 |
| F-02 | `logs/prod_runner.json` 里 `services.frontend.status = "external"` | 前端由 `erp-web`（nginx）托管，`prod_runner` 只做健康汇总 | `SPEC.md` §6.3 · `W2` @ 244 |
| F-03 | `ready: true` + `frontend_ok: true` 而多服务为 `external` | 健康口径**以该文件为准**；`external` ≠ 不健康 | `SPEC.md` §6.3 · `W8` @ 250 |
| F-04 | `user` / `permission` 端点认证是 fail-open（`get_current_user_id`） | 刻意取舍：strict 变体在「Redis 启动即不可用」时**永久 401**；**只有 `/backup` 用 `get_current_user_id_strict`** | `fastapi_app/api/v1/router.py` · `get_current_user_id` @ 46 起；`RESEARCH.md` §5.2 @ 196 |
| F-05 | `/monitoring` 无认证依赖 | POST `/vitals` 走 `sendBeacon` **无法带 header**；需认证的 `GET /vitals/summary` 在模块内单独声明 | `fastapi_app/api/v1/endpoints/monitoring.py` · `sendBeacon`；`RESEARCH.md` §5.2 @ 197 |
| F-06 | `config/nginx.conf` 的 `root /app/frontend-vite/dist;` | **死配置**，Windows 永不生效；生效的是 `config/nginx-windows.conf`。可作 P3 技术债（清理死文件），**不判故障** | `config/nginx.conf` · `root /app/frontend-vite/dist;` @ 107 |
| F-07 | `pyproject.toml` 没有 `[project]` / `[build-system]` | 刻意：依赖唯一真源是 `requirements/*.txt`，该文件只承载 `[tool.code-quality]` | `pyproject.toml` · `[tool.code-quality]` @ 13 |
| F-08 | `frontend-vite/vite.config.js` 与 `vite.config.ts` 并存 | **设计产物**：`.js` 是 `vue-tsc -b` 编译 `.ts` 的结果，且有回归测试断言一致；**删了会打挂构建**（红线 5） | `fastapi_app/tests/test_qa_prod_stack_regression.py` · 断言；`RESEARCH.md` §5.2 @ 200 |
| F-09 | `package.json` 声明 `playwright` 但仓库无 e2e 脚手架 | 现状事实（无 `playwright.config.*`、无 e2e 目录、无 `test:e2e` 脚本），**但「依赖声明」本身不是缺陷**；能力缺口由 `RESEARCH.md` §6 P1-4 承担，不得重复上报 | `frontend-vite/package.json` · `playwright` @ 45（`devDependencies` 声明） |
| F-10 | `mypy.ini` 注释里的两个「真实缺陷」 | **均已修复**：`services/ocr/_extractors.py` 已显式声明三个单例；`services/batch_import_dedup.py` 已把 `Container[Hashable]` 收窄为 `Iterable`。把注释当现状会**误报** | `fastapi_app/services/ocr/_extractors.py` · 单例声明 @ 22-24；`fastapi_app/services/batch_import_dedup.py` · `Iterable` @ 32 |
| F-11 | `git log` 里的 `core.hooksPath` 事故（428 个凭据入库） | **已修复**：`.githooks/` 目录已存在，pre-commit 三层守卫在位 | `.githooks/pre-commit` · 事故记录 @ 1-30 |
| F-12 | `_ops/credentials/` 下有 `.env.bak-*`、`_backup_encryption_password.txt`、`_metrics_bearer_token.txt` | **设计**：这是指定的凭据存放处，已被 `.gitignore` 覆盖。**磁盘明文属预期**；需验证的是 **ACL**（归 T10，见 U2），不得把「存在明文」本身当 finding | `_ops/credentials/` · `.gitignore` 覆盖；`RESEARCH.md` §5.2 @ 202 |
| F-13 | `ruff.toml` 的 `external = ["BLE001"]` | 刻意：RUF100 会自动删除 `# noqa: BLE001`，而它是质量门禁的**审计豁免凭证** | `ruff.toml` · `external`；`REPOWIKI.md` §6.3 @ 202 |
| F-14 | `ruff.toml` 给 `services/backup/__init__.py` 关 `I001` | 刻意：Redis 还原锁三件套**必须**排在所有星号导入之后，否则被 `query_service` 的 advisory 版遮蔽 → 端点 finally 抛 `TypeError` | `fastapi_app/services/backup/__init__.py` · 导入顺序；`RESEARCH.md` §5.2 @ 204 |
| F-15 | `pyproject.toml` 的 `max_file_size=1600` 看似太松 | 有依据：受扫 777 个 `.py` 中仅 2 个超 1200（`test_purchase_center.py`、`recovery_test_service.py`；项目注释原文 1497 / 1353；**实测** 1554 / 1354） | `pyproject.toml` · `max_file_size` @ 13；`REPOWIKI.md` §7.4 @ 242 |
| F-16 | `endpoints/backup/`、`endpoints/purchase_center/` 未在 `router.py` 中逐个 `include_router` | 经各自 `__init__.py` **聚合**后再挂载；判死代码**必须按全仓导入**。历史伪影曾误报「48 个孤儿」 | `fastapi_app/api/v1/router.py` · `api_router.include_router(` @ 46；`REPOWIKI.md` §7.1 @ 215 |
| F-17 | `deliverables/`（106 项）、`evidence/`（190）、`mockups/`（10）已入库 | `deliverables/` 是 `AGENTS.md` 明示的**历史归档**（不是现行真相）；`evidence/`、`mockups/` 属过程件，按 `RESEARCH.md` §6 P3 处置，**不得**当作缺陷重报 | `AGENTS.md` §2 目录职责表 @ 27；`RESEARCH.md` §5.2 @ 206 |
| F-18 | 根目录 `.agent/` `.claude/` `.cursor/` `.codebuddy/` 等 AI 工具痕迹目录 | 已被 `.gitignore` 覆盖，**不算安全 finding**；**未被忽略**的散落文件才属 D06 技术债 | `AGENTS.md` §7 忽略清单 @ 87-88；`SPEC.md` §6.3 · `W7` @ 249 |

**另外两条「方法级」防伪影**（`RESEARCH.md` §5.3 / `REPOWIKI.md` §7.1，必须写进各角色方法说明）：

- **F-19 · 迁移依赖图伪影**：只用 `ast.Assign` 找 `revision` / `down_revision` 会漏掉 `AnnAssign`（本仓大量带类型注解），从而伪造「4 heads（含 null）+ missing parents `pg_standalone_003` / `pg_standalone_007` + 5 roots」。真相：**单 head** `pg_standalone_060_fix_updated_at_varchar_columns`、零悬空、4 roots。正解用 `alembic ScriptDirectory`（`scripts/check_alembic_heads.py`）。证据：`RESEARCH.md` §5.3 @ 210；`REPOWIKI.md` §7.1 @ 213。
- **F-20 · 孤儿端点伪影**：只用「是否被 `router.py` 直接引用」判断，会伪造「48 个端点模块未接线」。真相：`router.py` **34 次** `include_router` 覆盖全部 32+2 个端点模块，**零孤儿**。证据：`fastapi_app/api/v1/router.py` · `api_router.include_router(` @ 46；`REPOWIKI.md` §7.1 @ 215。

**已修复事故（不得按现状上报）**：`erp-arq` 无限重启（`_SVC_DEPENDS` 已声明）· OCR `NameError`（`services/ocr/_extractors.py` @ 22-24 已修复）· prod_runner 系统代理误判（`_HTTP_DIRECT` 已修复）· 428 个凭据入库（`.githooks/` 已就位）。证据：`RESEARCH.md` §5.1 @ 186-190。

---

## 5. 风险与缓解

| # | 风险 | 缓解措施 | 责任 |
|---|---|---|---|
| R1 | **只读审核漏掉运行时问题**（行为、并发、内存、真实配置加载） | ① qa 真机实跑门禁（`SPEC.md` §9.2 C01–C12）；② 未知项 **U1–U12 逐条明确归属角色与只读核实方式**（见 §5.1）；③ 所有「无法验证」项必须显式标注，**不得**用推测填空 | qa + 各维度 owner |
| R2 | **单角色自审漏判 / 自证** | ① T15 reviewer 对全量 finding 做交叉复核；② 统计**撤销率** = 撤销数 ÷ 提交数（`REVIEW.md` 为权威）；③ 撤销率 > 40% ⇒ T15 必须 `verdict=needs_revision`（`SPEC.md` A08）；④ T05 规格评审前置于 T06–T14 | reviewer |
| R3 | **生产主机跑 pytest 可能连生产库并写库** | ① 先静态审计 `tests/conftest.py` 与 `fastapi_app/tests/conftest.py` 确认无 `create_all` / `drop_all` / 提交型 fixture；② 先 `pytest --collect-only -q`；③ **发现写库用例立即停**，该条标注「**未实跑**」+ 阻塞原因，**不得**算通过（`SPEC.md` §7 B2）；④ 禁止 `alembic upgrade` / 恢复演练 / 压测 | qa |
| R4 | **大仓库上下文爆炸**（6 705 文件 / 527 个后端 .py / 284 个 .vue） | ① 每角色**只读** `team/REPOWIKI.md` + 自己维度的代码（`readScope` 已在 `TASKS.json` 逐任务声明）；② 结构类结论先跑 AST 探针拿**计数**，再定点阅读命中的少数文件；③ 不重复 T01 已完成的调研 | 全体 |
| R5 | **审计对象错位**（以 `HEAD` 为准会漏掉 19 个已修改 + 3 个未跟踪文件） | 审计对象**必须是工作区**；A21 的前后比对基线是**审核开始时的 `git status --porcelain` 快照**，不是「全空」；既有改动由 T11 在 `AUDIT-OPS.md` 独立记录（`RESEARCH.md` §6 P0-1 · `SPEC.md` §10 S6） | 全体 + devops |
| R6 | **解析伪影复现**（迁移 head 数、孤儿模块数） | 结构类结论**只接受 M-AST / M-IMP**，且必须贴出脚本片段与原始值；与既有简报冲突时按 `SPEC.md` §7 B4 写明「用 X 得 A，用 ast 得 B，采信 B」 | architect + dba |
| R7 | **白名单误报**（把有意设计当缺陷） | §4 防伪影清单（原始 22 行 / 去重 14 条 / 本表 18 行 F 项）+ `SPEC.md` §6.3 W1–W18；命中即 `rejected` 并计入撤销率；A20 全工件检索白名单锚点，命中数必须为 0 | 全体 + reviewer |
| R8 | **未实跑被写成通过** | 每条命令必须有「命令 + 退出码 + 原始输出片段」三元组；未实跑逐条标注并给阻塞原因，**不计入通过**（A09 / A10） | qa |

### 5.1 未知项 U1–U12 的归属（**逐条点名，不得悬空**）

| # | 问题 | 归属 | 只读核实方式 |
|---|---|---|---|
| U1 | 生产运行时实际加载哪个 env 文件；`BACKUP_ENCRYPTION_PASSWORD` 在**运行进程**里是否非空 | sec + devops | `nssm get erp-prod AppEnvironment`（只读）+ `logs/prod_runner.json`；**不得重启服务** |
| U2 | `_ops/credentials/` 的 NTFS ACL 是否只对管理员开放；凭据是否已轮换 | sec | `Get-Acl`（只读）+ `docs/ops/` 轮换手册 |
| U3 | 生产 PG 大版本、`pg_stat_statements` / pgaudit、慢查询；`alembic current` 是否 == head | dba | 只读 SQL：`SHOW server_version`、`SELECT * FROM alembic_version` |
| U4 | `migrations/add_fabric_color_no.py` 的手工 DDL 是否已在生产执行、是否与 `versions/` 重复 | dba | 查 `information_schema.columns` 的 `customer_sampling_part.fabric_color_no` |
| U5 | 真机 a11y 与首屏性能 | ui + frontend | 跑 `scripts/prod_audit/layers/l10_frontend.py`（只读）+ 查 `frontend-vite/dist` 产物体积 |
| U6 | 移动端（`src/mobile/`、Capacitor）字段重映射残留；`android/` 产物 | frontend | 读 `src/mobile/` + `src/types/` |
| U7 | 覆盖率真实分布（哪些域 <40% / 0%） | qa | `pytest --cov=fastapi_app --cov-report=term-missing`（只读；需测试库） |
| U8 | `tests/stress/` / `tests/performance/` 历史报告是否仍代表当前性能 | qa + devops | 读报告日期 + 对照 `git log` |
| U9 | 看门狗计划任务是否真的在跑 | devops | `schtasks /query`（只读） |
| U10 | 恢复演练最近一次成功的证据；`backups/` 产物是否加密（扩展名 / 魔数） | devops + sec | 只读列目录 + 文件头魔数判断 |
| U11 | 19 个未提交改动是「功能未完成」还是「已上线没提交」；与生产实际运行代码是否一致 | pm + devops | `git diff` 对照 + 询问业务方 |
| U12 | `bandit` / `pip-audit` 最近结果；`# nosec` 预算余量 | sec | 跑只读扫描 `python scripts/check_nosec_budget.py` |

---

## 6. 质量门禁命令清单（**权威定义在 `SPEC.md` §9.2**，此处仅列引用锚点供执行者对照）

> 本节**不定义**命令口径；命令的允许/禁止边界、失败处置、实跑前置**一律**以 `SPEC.md` §6.2 与 §9.1–§9.2 为准。

| # | 命令（工作目录） | 引用 |
|---|---|---|
| C01 | `python scripts/quality_gate.py`（`D:\erp_system`） | `SPEC.md` §9.2 @ 345 |
| C02 | `ruff check .` | `SPEC.md` §9.2 @ 346 |
| C03 | `mypy` | `SPEC.md` §9.2 @ 347 |
| C04 | `pytest -q` | `SPEC.md` §9.2 @ 348 |
| C05 | `npm run type-check`（`frontend-vite`） | `SPEC.md` §9.2 @ 349 |
| C06 | `npm test`（`frontend-vite`） | `SPEC.md` §9.2 @ 350 |
| C07 | `npm run lint`（`frontend-vite`） | `SPEC.md` §9.2 @ 351 |
| C08 | `npm run check:api`（`frontend-vite`） | `SPEC.md` §9.2 @ 352 |
| C09 | `npm run check:routes`（`frontend-vite`） | `SPEC.md` §9.2 @ 353 |
| C10 | `npm run check:dto`（`frontend-vite`） | `SPEC.md` §9.2 @ 354 |
| C11 | `python scripts/check_alembic_heads.py` | `SPEC.md` §9.2 @ 355 |
| C12 | `python scripts/scan_secrets.py` + `python scripts/check_bom.py` | `SPEC.md` §9.2 @ 356 |

**工件自检 verify**（canonical，各任务 inScope 复用；把 `AUDIT-BACKEND.md` 换成自己的工件名）：

```powershell
python -c "import pathlib,sys,re;p=pathlib.Path('team/完整的审核一下我这个项目-060103/AUDIT-BACKEND.md');t=p.read_text('utf-8') if p.exists() else '';sys.exit(0 if p.exists() and p.stat().st_size>=3000 and len(re.findall(r'@\s*\d+',t))>=10 else 1)"
```

---

## 7. 任务 DAG（与 `TASKS.json` 一致 · 本文**只描述**，不写 `TASKS.json`）

> `TASKS.json` 的**唯一写者是 pm**。本节只给出 architect 视角的 DAG 描述与依赖语义。

```
T01 researcher 现状调研 ────────────► (T02)
T02 pm Ultra Spec + 任务 DAG ────────► (T03, T04, T05)
T03 architect PLAN ─────────────────► (T05)
T04 architect AUTHORITY ────────────► (T05)
T05 reviewer 规格评审 [review] ─────► (T06, T07, T08, T09, T10, T11, T12, T13, T14)
T06 architect 架构审计 ─┐
T07 backend 后端审计    │
T08 frontend 前端审计   │
T09 dba 数据库与迁移    ├─► T15 reviewer finding 交叉复核 + 撤销率 [review] ─► T16 pm 总报告 + backlog ─► T17 qa 交付前门禁 [review]
T10 sec 安全审计        │
T11 devops 运维/CI      │
T12 docs 文档审计       │
T13 ui UI/UX 审计       │
T14 qa 门禁实跑         │
T18 backend 性能与可观测性 ┤
T19 dba 数据一致性与并发   ┘
T20 qa 修复后验证 [conditional · blocked-by-user-decision] ◄─ T17
T21 sec+devops 依赖与供应链 ◄─ T05（**新增 · 编号待 pm 确认**）
```

| 任务 | 角色 | kind | 依赖 | 产出 |
|---|---|---|---|---|
| T01 | researcher | work | — | `RESEARCH.md` + `team/REPOWIKI.md` |
| T02 | pm | requirements | — | `SPEC.md` `TASKS.json` `任务看板.md` `DECISIONS.md` |
| T03 | architect | work | T02 | `PLAN.md`（本文） |
| T04 | architect | work | T02 | `AUTHORITY.md` |
| T05 | reviewer | **review** | T02, T03, T04 | `REVIEW.md` |
| T06 | architect | work | T05 | `AUDIT-ARCH.md` |
| T07 | backend | work | T05 | `AUDIT-BACKEND.md` |
| T08 | frontend | work | T05 | `AUDIT-FRONTEND.md` |
| T09 | dba | work | T05 | `AUDIT-DB.md` |
| T10 | sec | work | T05 | `AUDIT-SEC.md` |
| T11 | devops | work | T05 | `AUDIT-OPS.md` |
| T12 | docs | work | T05 | `AUDIT-DOCS.md` |
| T13 | ui | work | T05 | `AUDIT-UIUX.md` |
| T14 | qa | work | T05 | `TEST.md` |
| T18 | backend | work | T05 | `AUDIT-PERF.md` |
| T19 | dba | work | T05 | `AUDIT-CONSISTENCY.md` |
| T15 | reviewer | **review** | T06–T14, T18, T19 | `FINDINGS.json` + `REVIEW-CROSS.md` |
| T16 | pm | work | T15 | `SUMMARY.md` + `BACKLOG.md` |
| T17 | qa | **review** | T16 | `GATE.md` |
| T20 | qa | work（conditional） | T17 | `REPAIR-VERIFY.md`（**未裁定前不得启动**） |
| **T21** | sec + devops | work（**新增**） | T05 | `AUDIT-DEPS.md` |

**依赖语义**：`T05 verdict=pass` 是 `T06–T14 / T18 / T19 / T21` 的前置门禁（`SPEC.md` A25：依赖未完成不可 claim）；`T15` 必须等**全部 12 维度工件**终态；`T16` 必须等 `T15` 收敛出终态 finding；`T17` 必须等 `T16`；`T20` 由 `T17` 之后**仅当用户裁定允许修复**才可启动。

---

## 8. 已知偏差与待办（**architect 只报告，不改他人工件**）

| # | 偏差 | 影响 | 建议处置（归属） |
|---|---|---|---|
| G1 | **`TASKS.json` 无「依赖与供应链」维度任务** | 12 维度中的第 11 维无 owner / 无工件，`SPEC.md` A01 的「12 维度各 ≥1 工件」将无法满足 | pm 在 `TASKS.json` 增加 **T21**（sec + devops，`AUDIT-DEPS.md`）；`SPEC.md` §2.1 增加 D13 |
| G2 | **`SPEC.md` §2.1 的维度名与本轮点名的 12 维度名不一致**（如「性能与可观测性 / 数据一致性与并发」vs「性能与容量」；SPEC 无「依赖与供应链」） | 角色可能按不同名字重复或漏审 | pm 在 `SPEC.md` §2.1 增加「用户点名 12 维度 ↔ D01–D12/D13」对照列；**编号只增不减** |
| G3 | **（已撤销）原判「`SPEC.md` §5.1 未给 P1 的两条可判定规则」前提为假** | 实测 §5.1 **已全编号**：P0 四条（`SPEC.md` @ 159）、P1 两条（@ 160）、P2 两条（@ 161）、P3 两条（@ 162），故原「P1 为描述式 / P2、P3 各 1 条」均不成立 | **已满足 · 撤销**（pm 于 T02 修订第二批落地）；不再需要补足规则，`severity` 口径仍唯一以 `SPEC.md` §5.1 为准 |
| G4 | **（已消解）**`REVIEW.md` 已落「撤销率」定义式 | AUTHORITY 中「撤销率 → REVIEW.md → reviewer」的权威文件**已有定义体**（`REVIEW.md` · `## 撤销率` @ 7） | 已由 reviewer 于 T05 落盘；T15 只须维护数值，无须再补定义式 |
| G5 | `RESEARCH.md` §6 P0-1 记 19 个 `M`，`SPEC.md` §10 S6 记 18 个 `M` | 工作树快照口径不一致 | devops 在 T11 以**审核开始时**的实测 `git status --porcelain` 为准，两处数字都标注为「快照时点不同」 |

---

*本文由 architect（T03）冻结。任何角色若认为某条方法不可执行或某条契约不可判定，须在 T05 规格评审提出，**不得**在执行阶段自行改契约。*
