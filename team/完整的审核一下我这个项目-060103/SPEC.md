# 审核 Ultra Spec（SPEC）

> 本轮**不是功能开发**，而是对存量**生产** ERP（滨发协同系统 / binfa-erp）的一次**只读全面审核**。
> 本文件冻结于澄清结论（2026-09-30），是 `T05 规格评审`、`T15 finding 交叉复核`、`T17 交付前门禁` 的**唯一判定依据**。
> 引用纪律：一律写 `<相对路径> · <锚点（函数名 / 字段名 / 唯一字符串）> @ <行号>` —— **锚点是主证据，行号只是阅读辅助**；锚点槽内部不得嵌行号，行号只能出现在末尾那一个行号槽里。

---

## 0. 元信息

| 项 | 值 |
|---|---|
| run-id | `完整的审核一下我这个项目-060103` |
| 工作区 | `D:\erp_system`（**生产主机 = 运维主机**，无独立测试 / 预发环境） |
| 工件根 | `team/完整的审核一下我这个项目-060103/`（下文简称 **run-dir**） |
| 档位 | `standard`（≤6 角色 / ≤30 验收项 / ≤40 派工）· **实际按用户点名的 12 角色编制执行**，超出档位上限（见 `DECISIONS.md` 决策 4） |
| 变更权限 | **只读**（用户 Q1 拍板） |
| 冻结依据 | `RUN.log.md` 的 `decision:user`（5 问澄清）；`error:spec-conflict` 未获裁定前按 Q1 冻结 |
| 判定权威 | 代码与实测输出 > `AGENTS.md` > 其它 `*.md` 报告（`AGENTS.md` §6 明示 `deliverables/`、`*.md` 结论可能已过期） |

### 0.1 澄清结论 → 本 SPEC 的落点（逐字引用用户结论）

| 澄清 | 用户结论（逐字） | 落点 |
|---|---|---|
| Q1 变更权限 | 只读审计：只出报告与整改清单，不动任何业务代码 | §6.1 只读边界；§2.2 inScope 只写 run-dir 工件 |
| Q2 生产环境边界 | 允许跑质量门禁命令（pytest / ruff / mypy / npm test / npm run type-check） | §6.2 生产环境边界；§9 测试计划 |
| Q3 审核重点 | 全维度平均覆盖 | §2.1 十二维度**不得减少**；T06–T14 + T18/T19 每个维度 ≥1 条任务 |
| Q4 交付形态 | 总报告 + 分角色报告 + 可执行整改 backlog（含优先级/证据锚点/验收方式/工作量估算） | §2.2 工件矩阵；A14–A19 |
| Q5 深度预算 | 深度：含修复后的验证与回归（时间最长） | **与 Q1 冲突** → 用户已裁定**取 A（纯只读审计）**；修复后验证不实施，条件任务 **T20 撤销**（`status=cancelled`，条目保留） |

---

## 1. 审核目标

**一句话**：在**不改动任何业务代码、不触碰生产运行时**的前提下，对 `D:\erp_system` 的 12 个维度做**证据化**审核，产出「总报告 + 分角色报告 + 可执行整改 backlog」。

**可判定表述（什么叫「审核完成」）** —— 当且仅当下列 6 条**同时为真**：

1. 12 个维度各自有 ≥1 份落盘工件，且每份工件里**每条 finding** 都带 `路径 · 锚点 @ 行号`；
2. 每条 **P0 / P1** 都带「复现步骤」或「代码路径推理链」二选一（见 §5.2 证据标准）；
3. 全部 finding 经 T15 交叉复核，并给出**撤销率**（被撤销条数 ÷ 提交条数）与撤销清单；
4. 质量门禁基线命令（§9.2）**全部实跑**并贴**原始输出**；跑不起来的逐条标注「**未实跑**」并给出阻塞原因，**不得算通过**；
5. 总报告（`SUMMARY.md`）给出每个维度的**结论 + 健康度评分 + 证据索引**，backlog 每条含**优先级 / 证据锚点 / 验收方式 / 工作量估算**四要素；
6. `T17` 交付前门禁 `verdict=pass`。

> 任一条件为假 ⇒ 本轮**未完成**，不得交付。

---

## 2. 范围（In Scope）

### 2.1 审核维度（13 个 · 只增不减）

> 用户 Q3 = 「全维度平均覆盖」。用户原话列举了 10 项，本 SPEC 补齐到 **13** 项：D11 性能与可观测性、D12 数据一致性与并发（理由见 `DECISIONS.md` 决策 5），以及依 architect 在 `PLAN.md` §2 提出的 G1 缺口新增的 **D13 依赖与供应链**（理由见 `DECISIONS.md` 决策 7）。
>
> **本表是维度编号的唯一权威源**：最后一列给出 architect 在 `PLAN.md` §2 使用的维度叫法，二者是**同一维度的两种叫法，一律以本表编号 D01–D13 为准**。

| # | 维度 | 查什么（具体到可执行动作） | 主责任务 | 主责角色 | PLAN.md §2 叫法（同一维度的另一种叫法 · **以本表编号为准**） |
|---|---|---|---|---|---|
| D01 | 架构与模块边界 | 目录职责 vs `AGENTS.md` §2 表；`fastapi_app/api/v1/router.py` 的 `api_router.include_router` 挂载完整性（**必须 ast**）；`endpoints/` 是否绕过 `services/` 直连 DB；`__init__.py` 聚合造成的**伪孤儿**；循环导入；根 `utils/` 与 `fastapi_app/` 的边界 | T06 | architect | 架构（PLAN §2 #1） |
| D02 | 后端代码 | `fastapi_app/` 全量 `.py`；端点契约（请求/响应模型、状态码、统一错误结构）；service 层事务边界；`bare_except`（基线 9）；函数长度 >80（基线 52）；N+1（基线 0）；鉴权依赖注入是否**逐端点**生效；ARQ 任务注册与回调 | T07 | backend | 后端（PLAN §2 #2） |
| D03 | 前端代码 | `frontend-vite/src` 的 `.vue` / `.ts`；`npm run type-check` 与 `lint` / `check:api` / `check:routes` / `check:dto` 五个对齐脚本的**实际覆盖**；`vite.config.js` 与 `vite.config.ts` 并存的设计产物一致性；组件长度 >400（基线 7）；`any` / `@ts-ignore` 密度；前端 API 客户端 vs 后端路由漂移 | T08 | frontend | 前端（PLAN §2 #3） |
| D04 | 数据库与迁移 | `migrations/versions` 的单 head 判定（**必须 ast**）；模型 `Base.metadata` vs 实际 DDL；索引与高频查询匹配；约束（唯一 / 外键 / 非空 / check）；`alembic.ini` 与 `migrations/env.py` 的**权威性**（见 §7 边界 Case）；迁移是否夹带业务逻辑；大表 DDL 锁风险 | T09 | dba | 数据库与迁移（PLAN §2 #4） |
| D05 | 安全 | 认证 / 授权 / 越权；密钥与凭据入库面（`_ops/credentials/`、`.env`、`config/pgbouncer/userlist.txt`）；`scripts/scan_secrets.py` 与 `.githooks/allowlist.txt` 的豁免合理性；注入面（SQL 拼接、`text()`）；上传 / 下载路径穿越；CORS 与安全头（`config/security-headers.conf`）；uvicorn 绑定面；`/metrics` 暴露面；备份加密的静默降级；**OWASP Top 10 (2021) 逐项 + 等保 2.0 基线对标** | T10 | sec | 安全（PLAN §2 #5） |
| D06 | 运维 / 部署 / CI | 5 个 NSSM 服务（erp-web / erp-prod / erp-arq / erp-redis / erp-redis-broker）配置；`logs/prod_runner.json` 健康口径；`config/nginx-windows.conf` vs 死配置 `config/nginx.conf`；备份 / 恢复 / 清理链路；`start.py` 唯一入口；`.github/` 工作流；`.githooks/pre-commit` 四层与 `pre-commit` 缺失降级；根目录 AI 痕迹目录与散落临时文件 | T11 | devops | 运维部署CI（PLAN §2 #6） |
| D07 | 文档 | `AGENTS.md`（唯一契约）自洽性；`README.md` / `CHANGELOG.md` / `README_DEPLOY.txt`；`docs/` 下 `.md` 与代码的偏差；`deliverables/` 归档的过期结论；文档中的可验证断言是否仍成立 | T12 | docs | 文档（PLAN §2 #7） |
| D08 | UI / UX | 路由与导航一致性；权限可见性（菜单可见 vs 后端鉴权）；表单校验与错误提示；空 / 加载 / 错误三态；可访问性（键盘可达、对比度、label 关联）；响应式断点；`mockups/` 与实现的偏差 | T13 | ui | UI-UX（PLAN §2 #8） |
| D09 | 测试与质量门禁 | `pytest.ini` 的 `testpaths`；`tests/` 全量测试；`scripts/quality_gate.py` 的**棘轮语义**（只拦新增）；`scripts/gate_baseline.json` 八项计数；`pyproject.toml` `[tool.code-quality]` 三阈值；覆盖率；测试是否**隐式依赖生产库 / 网络**；BOM 检查；前端 vitest | T14 | qa | 测试与门禁（PLAN §2 #9） |
| D10 | 需求一致性 | `AGENTS.md` §2/§3/§4/§5 的每条**可验证断言** vs 代码实测（「零孤儿」「单 head」「5 个 NSSM 服务」「唯一启动入口 `start.py`」「`config/nginx.conf` 死配置」「`vite.config.js` 设计产物」…）；端点挂载数 vs `endpoints/` 模块数 | T06 + T12 | architect + docs | 需求一致性（PLAN §2 #10） |
| D11 | 性能与可观测性 | N+1（基线 0）；慢查询与缺失索引；连接池（pgbouncer）；Redis 缓存键与失效策略；ARQ 队列积压；日志分级与脱敏；`config/prometheus.yml` / `grafana/` / `otel-collector.yaml` / `promtail.yml` 是否**真正接线**；`/metrics` 内容 | T18 | backend | 性能与容量（PLAN §2 #12 · 前半） |
| D12 | 数据一致性与并发 | 事务边界（service 层 commit 位置，基线 `service_commit` 9）；并发同键（唯一约束 vs 应用层查重）；幂等；软删与计数残留；备份 / 恢复的一致性口径；跨模块数据流（采购 → 库存 → 生产 → 出货）的守恒校验点 | T19 | dba | 性能与容量（PLAN §2 #12 · 后半） |
| D13 | 依赖与供应链 | `requirements/*.txt` 与 `frontend-vite/package.json` 的版本钉死情况（精确版 vs 范围版）；已知 CVE 面与扫描器现状（`bandit` / `pip-audit` / `npm audit` 是否接线、本机能否跑）；依赖真源与 `pyproject.toml` 无 `[project]` 的关系（白名单 W11）；未使用 / 幽灵依赖；`package-lock.json` 与 `node_modules` 的一致性；供应链面（`_ops/credentials/`、`config/pgbouncer/userlist.txt` 是否入库）。上游未知项：`RESEARCH.md` §7 U12 | T21 | sec | 依赖与供应链（PLAN §2 #11 · 原标「SPEC 无对应编号（缺口）」，**本表补齐为 D13**） |

### 2.2 工件命名与责任矩阵（**文件名即 inScope**）

> 模板既有名（`SPEC.md` / `PLAN.md` / `RESEARCH.md` / `REVIEW.md` / `TEST.md` / `SUMMARY.md` / `AUTHORITY.md` / `DECISIONS.md` / `TASKS.json` / `任务看板.md`）优先复用；模板未覆盖的分角色报告统一用 `AUDIT-<DIM>.md`（命名补充理由见 `DECISIONS.md` 决策 6）。

| 任务 | 角色 | 工件（相对 run-dir） |
|---|---|---|
| T01 | researcher | `RESEARCH.md` + `D:\erp_system\team\REPOWIKI.md` |
| T02 | pm | `SPEC.md` `TASKS.json` `任务看板.md` `DECISIONS.md` |
| T03 | architect | `PLAN.md` |
| T04 | architect | `AUTHORITY.md` |
| T05 | reviewer | `REVIEW.md` |
| T06 | architect | `AUDIT-ARCH.md` |
| T07 | backend | `AUDIT-BACKEND.md` |
| T08 | frontend | `AUDIT-FRONTEND.md` |
| T09 | dba | `AUDIT-DB.md` |
| T10 | sec | `AUDIT-SEC.md` |
| T11 | devops | `AUDIT-OPS.md` |
| T12 | docs | `AUDIT-DOCS.md` |
| T13 | ui | `AUDIT-UIUX.md` |
| T14 | qa | `TEST.md` |
| T15 | reviewer | `FINDINGS.json` + `REVIEW-CROSS.md` |
| T16 | pm | `SUMMARY.md` + `BACKLOG.md` |
| T17 | qa | `GATE.md` |
| T18 | backend | `AUDIT-PERF.md` |
| T19 | dba | `AUDIT-CONSISTENCY.md` |
| T21 | sec（devops 协作） | `AUDIT-DEPS.md` |
| T20（conditional · 用户裁定撤销） | qa | `REPAIR-VERIFY.md`（本轮不产出） |

---

## 3. 范围外（Out of Scope）

| 不查什么 | 为什么 |
|---|---|
| 第三方依赖（pip / npm 包）的**内部实现** | 只审「版本、已知 CVE 面、是否被真实引用」，审包源码不产生可执行整改项 |
| 历史 git 对象、已删除分支、reflog | 只读审核不重写历史；且 Q1 禁止任何 git 写操作 |
| `deliverables/` 与 `docs/` 中**已被代码推翻**的历史结论逐条复核 | `AGENTS.md` §6 明示以代码为准；D07 只做「过期标注」，不重审 |
| 运行期业务数据内容（`backups/`、`logs/` 的数据体） | 生产数据；且可能含凭据明文，读取即扩大暴露面 |
| 生产数据库的写入、DDL、备份 / 恢复演练 | Q2 明确禁止；会直接影响在用业务 |
| **修复实施**（改业务代码、提交、推送） | Q1 只读（Q5 冲突已裁定取 Q1，见 §0.1 与 §7） |
| 前端视觉稿 / 设计系统重做、`mockups/` 的重绘 | 不产生审核价值；D08 只做「实现 vs 意图」偏差 |
| 压测 / 负载测试 / 并发压测 | 会打生产；D11 只做静态与配置层推断 |
| `node_modules/`、`dist/`、`build/` 内的产物内容 | 构建产物，非源码真相 |

---

## 4. 验收标准（26 条 · 全部可机判或可人工核对）

| # | 验收标准 | 判定方式 |
|---|---|---|
| A01 | **13** 个维度各产出 ≥1 份落盘工件，工件头部含 run-id 与维度编号 | 文件存在 + 首 20 行含 `D01`–`D13` 标记 |
| A02 | 每份 `AUDIT-*.md` ≥3000 字节（防空壳交付） | `(Get-Item <path>).Length -ge 3000` |
| A03 | 每条 finding 采用**两种合法渲染之一**：① 单串 `路径 · 锚点 @ 行号`（锚点槽内**不得**出现行号）；② 表格 / JSON **三槽分列**（`file` 字段**带目录** ∧ `anchor` 字段**不含数字、不含 `@`** ∧ `line` 字段为**正整数**）；两种形态与 PLAN §3.1 schema 的 `file` / `anchor` / `line` 三字段一一对应 | ① 正则：findings 段每行含 `·` 与 ` @ <数字>`；**或** ② 三槽分列：`file` 含 `/` ∧ `anchor` 不匹配 `[0-9@]` ∧ `line` 匹配 `^[1-9][0-9]*$`。**命中其一即通过** |
| A04 | 每条 P0 / P1 附「复现步骤」或「代码路径推理链」二选一 | 人工核对；缺一即该 finding 降级为 P3 或撤销 |
| A05 | 全部 finding 汇总进 `FINDINGS.json`，字段齐全（id / severity / dimension / owner / anchor / evidence / status） | JSON schema 校验 + 字段非空 |
| A06 | `FINDINGS.json` 中 P0+P1 条数 ≥ 各维度报告 P0+P1 条数之和（无遗漏） | 计数比对 |
| A07 | T15 给出**撤销率** = 被撤销 finding 数 ÷ 提交 finding 数，并列出撤销清单与撤销理由 | `REVIEW-CROSS.md` 含「撤销率」行与撤销表 |
| A08 | 撤销率 > 40% ⇒ T15 必须 `verdict=needs_revision` 退回重做 | `REVIEW-CROSS.md` 的 verdict 与撤销率一致性 |
| A09 | §9.2 的门禁命令**逐条有记录**：实跑项给「命令 + 退出码 + 原始输出片段」三元组；未实跑项给「命令 + 未实跑 + 阻塞原因」 | `TEST.md` 表格逐行可核对；每行恰为上述两种形态之一 |
| A10 | 未能实跑的命令逐条标注「**未实跑**」+ 阻塞原因；未实跑**不得**计入通过；**A09 的「记录」包含未实跑形态** | `TEST.md` 中 `未实跑` 计数 = 阻塞清单条数 |
| A11 | `scripts/quality_gate.py` 的退出码与 `scripts/gate_baseline.json` 八项计数有一致性对照表 | 对照表存在且八项齐全 |
| A12 | 迁移**单 head** 结论由 `ast` 解析得出，并给出 `migration_heads` 的实际值 | `AUDIT-DB.md` 含 `migration_heads` 原始值 |
| A13 | 「零孤儿端点」结论由 `ast` **全仓导入**分析得出，不得用 grep / 正则 | 报告写明所用方法与脚本片段 |
| A14 | 每条 P0 / P1 都映射到 backlog 的 ≥1 条整改项（无悬空 finding） | finding id 集合 ⊆ backlog 引用集合 |
| A15 | backlog 每条含四要素：优先级 / 证据锚点 / 验收方式 / 工作量估算（人时） | `BACKLOG.md` 表头四列齐全且无空值 |
| A16 | backlog 按 P0→P3 排序；P0 / P1 给出建议修复顺序与依赖关系 | 排序可核对 + 依赖列非空 |
| A17 | `SUMMARY.md` 含 **13** 维度结论表 + 每维度证据索引（指向具体工件与 finding id） | 表格 **13** 行 + 索引列非空 |
| A18 | `SUMMARY.md` 含每维度健康度评分（0–5）及评分理由 | **13** 个评分 + **13** 条理由 |
| A19 | 交付形态满足 Q4：总报告 1 + 分角色/分维度报告 ≥**11**（D13 新增 `AUDIT-DEPS.md` 后实为 12 份）+ backlog 1 | 文件计数 |
| A20 | §6.3 白名单中任一模式**不得**作为 finding 出现在任何报告中 | 全工件 grep 白名单锚点 |
| A21 | 只读边界未被突破：审核期间**无任何可归因于本轮审核的**业务代码变更（判定口径见 §10 S6 —— 以审核开始快照为基线，差异项须能归因到外部；`team/`、`logs/` 的运行期变化除外） | 前后快照比对 + 逐条归因 |
| A22 | 所有 finding 的 `status` 终态为 `confirmed` / `rejected` / `merged`，无 `open` 残留 | `FINDINGS.json` 状态统计 |
| A23 | 安全审计给出 OWASP Top 10 (2021) 十项逐项结论（命中 / 不适用 / 未评估 + 理由） | `AUDIT-SEC.md` 十行表 |
| A24 | D10 把 `AGENTS.md` 可验证断言逐条对照代码，给出「一致 / 不一致 / 无法验证」三态 | 对照表行数 ≥ 8 |
| A25 | T05 规格评审 `verdict=pass` 后，T06–T14 才允许进入 `in_progress`（门禁前置） | 任务状态时序 |
| A26 | T17 交付前门禁 `verdict=pass`，检查项与 A01–A25 逐条对齐（不得新增未定义标准） | `GATE.md` 逐条映射表 |

---

## 5. 业务规则

### 5.1 严重度判定口径（**逐字写死，各角色不得自造**）

| 级别 | 逐字判定口径 | 典型例 |
|---|---|---|
| **P0** | 满足下列**任一**：① 可导致**数据丢失或不可恢复**；② 存在**未授权访问 / 越权**路径（含凭据明文入库、鉴权可绕过）；③ 可导致**生产中断**（服务起不来、端口冲突、迁移多 head 导致 `alembic upgrade` 失败）；④ **静默降级**安全能力（如备份加密被关闭而不报错） | 凭据入库、uvicorn 绑 `0.0.0.0`、迁移多 head |
| **P1** | 满足下列**任一**：① 有**明确代码证据**的正确性 / 一致性缺陷 —— 给定输入即可推出错误输出 / 错误状态 / 数据不一致，且该输入在当前生产数据与配置下**可达**；② 在**特定输入 / 特定时序**下会触发 P0 场景，但该输入在当前生产数据与配置下**不可达**（无已知触发路径） | 事务边界错误导致部分提交、N+1 在高频列表页、鉴权只在前端隐藏 |
| **P2** | 满足下列**任一**：① 可维护性 / 可观测性 / 性能缺陷，**不直接**导致错误结果，但显著提高故障概率或排障成本；② 与 `scripts/gate_baseline.json` 八项计数**直接对应**的存量违规点（`n_plus_one` / `bare_except` / `function_length` / `vue_component_length` / `service_commit` / `bom` / `alembic_heads` / `env_drift`），且**未**被 §6.3 白名单豁免 | 裸 `except`、函数超长、日志无 traceId、索引缺失 |
| **P3** | 满足下列**任一**：① 风格 / 文档 / 卫生问题，**零功能影响**；② 注释 / 文档的**描述**与代码实际行为不一致，而代码行为**正确**（缺陷在注释侧，不在代码侧） | 死配置、过期文档、根目录临时文件、命名不一致、过期注释 |

**强制规则**：
- **无锚点 ⇒ 无 finding**（降为「观察」并标注 `status=rejected`）。
- **不确定 ⇒ 降级**：拿不准 P1 还是 P2 时取 **P2**；拿不准是否 finding 时**不写**。
- **P0 必须双证**：代码锚点 + 可复现步骤 / 推理链，缺一即降 P1。
- **同一根因跨维度出现** ⇒ 取**最高**级别，归到**主责维度**，其余维度写「见 F-xxx」。

### 5.2 finding 记录格式（唯一合法形态）

`@
### F-<维度><序号> · <一句话标题>
- severity: P0|P1|P2|P3
- anchor: <相对路径> · <锚点> @ <行号>
- evidence: <复现步骤 或 代码路径推理链（P0/P1 必填）>
- impact: <对生产的具体影响>
- fix-hint: <整改方向，不改代码只给方向>
- status: open|confirmed|rejected|merged
`@

**什么算一条 finding**：① 有具体文件锚点；② 能说清「什么输入 / 什么条件下产生什么坏结果」；③ 有复现步骤或从入口到缺陷的完整代码路径。
**什么不算**：① 风格偏好（「我觉得应该用 X 模式」）；② 无证据猜测（「这里可能有并发问题」）；③ 与代码矛盾的文档结论；④ §6.3 白名单命中的模式；⑤ 终端编码 / 乱码 / 环境差异类噪声。

### 5.3 `FINDINGS.json` 结构

`@json
{
  "runId": "完整的审核一下我这个项目-060103",
  "generatedBy": "reviewer",
  "findings": [
    {
      "id": "F-D05-001",
      "severity": "P0",
      "dimension": "D05",
      "owner": "sec",
      "anchor": "<相对路径> · <锚点> @ <行号>",
      "evidence": "<复现步骤或推理链>",
      "impact": "<影响>",
      "fixHint": "<方向>",
      "backlogRef": "B-001",
      "status": "confirmed"
    }
  ],
  "stats": { "submitted": 0, "confirmed": 0, "rejected": 0, "merged": 0, "revocationRate": 0.0 }
}
`@

---

## 边界与禁止项（§6 · 强制 · 沉默 ≠ 允许）

> 每条写成「**禁止什么 → 期望结果 / 期望拒绝 → 验收方式**」。**规格没写的动作，默认视为禁止**（本轮是只读审核，默认拒绝任何写操作）。「期望结果 / 期望拒绝」一列**不得留空** —— 没有拒绝口径的边界视为未定义。

| 边界族 | 规则（禁止什么） | 期望结果 / 期望拒绝 | 验收方式 |
|---|---|---|---|
| 只读边界 | 改 / 建 / 删 `D:\erp_system` 下任何业务代码与配置；任何写 git 历史的操作 | **拒绝**：写盘被 R1 工件归属门禁拦下并回执「不是它的负责人」；违反即**本轮作废** | A21：审核前后 `git status --porcelain` 比对一致 |
| 生产环境边界 | 起 / 停 / 重启服务；写库 / DDL / `alembic upgrade`；备份恢复演练；压测；改 `.env*` 与 `config/` | **拒绝**：命令不执行；发现越界命令立即终止并记 `blocked-by-policy` | §9.2 命令清单逐条附「是否可能写库 / 起进程」判定；A09 / A10 |
| 白名单（有意设计） | 把 §6.3 白名单命中的模式写成 finding | **拒绝**：该 finding 在 T15 被判 `rejected`，并计入撤销率 | A20：全工件检索白名单锚点，命中数必须为 0 |
| 证据标准 | 无锚点 / 无复现步骤 / 用文本匹配代替 `ast` 的结构结论 | **拒绝**：降级为「观察」并标 `status=rejected`；P0/P1 缺双证则降 P1 | A03 / A04 / A12 / A13；T15 逐条复核 |
| 幻觉处置 | 把未复核 finding 派成修复任务；对「未实跑」写「通过」 | **拒绝**：T15 不得给出 `verdict=pass`；T17 判 `reject` | A22（无 `open` 残留）+ A14 + A10 |
| 变更冻结 | 在 T05 规格评审 `pass` 前让 T06–T14 进入 `in_progress` | **拒绝**：任务不得越过门禁启动（依赖未完成不可 claim） | A25：任务状态时序 |

> 每条写成「**禁止什么 → 期望结果 → 验收方式**」。规格没写的动作，默认视为**禁止**（本轮是只读审核，默认拒绝任何写操作）。

### 6.1 只读边界

| 项 | 内容 |
|---|---|
| **禁止什么** | 任何角色**不得**修改 / 创建 / 删除 `D:\erp_system` 下**业务代码与配置**；禁止 `git add` / `commit` / `push` / `reset` / `checkout` / `stash` / 任何写 git 历史的操作；禁止改 `AGENTS.md`、`.githooks/`、`.gitignore`、`pyproject.toml`、`ruff.toml`、`mypy.ini`、`pytest.ini`、`scripts/gate_baseline.json`（**不得用 `--update-baseline` 收紧或放宽基线**） |
| **期望结果** | 唯一可写区域 = run-dir（`team/完整的审核一下我这个项目-060103/`）；唯一例外 = T01 可写 `team/REPOWIKI.md` |
| **验收方式** | A21：审核前后 `git status --porcelain` 比对；违反 ⇒ **本轮作废**，T17 判 `reject` |

### 6.2 生产环境边界

| 项 | 内容 |
|---|---|
| **允许跑**（用户 Q2） | `python scripts/quality_gate.py`、`ruff check .`、`mypy`、`pytest -q`、`npm run type-check`、`npm test`、`npm run lint`、`npm run check:api` / `check:routes` / `check:dto`，以及 `scripts/` 下的**只读检查脚本**（`check_alembic_heads.py`、`check_bom.py`、`check_bare_except.py`、`check_function_length.py`、`check_vue_component_length.py`、`check_service_commit.py`、`check_n_plus_one.py`、`scan_secrets.py`） |
| **明确禁止** | ① 起 / 停 / 重启任何服务：`python start.py`、`python run.py`、`uvicorn`、`npm run dev` / `vite`、NSSM 增删改、`server_manager.py` 的任何子命令；② 任何**写库**操作：INSERT / UPDATE / DELETE / DDL / `alembic upgrade` / `alembic downgrade` / `alembic stamp`；③ 备份 / 恢复 / 清理演练；④ 压测 / 并发压测 / 长事务；⑤ 修改 `.env*` / `_ops/credentials/` / `config/` 下任何文件；⑥ 删除 `backups/` `logs/` 下任何文件 |
| **期望结果** | 所有命令**只读且短时**（单条 < 10 分钟）；一旦发现命令会写库或起进程，**立即停止**并在报告标注 `blocked-by-policy` |
| **验收方式** | `TEST.md` 中每条命令附「是否可能写库 / 起进程」的判定；A09 / A10 核对 |

### 6.3 白名单：看起来像缺陷、其实是**有意设计**（**命中即不得作为 finding**）

| # | 模式（锚点） | 为什么是设计 |
|---|---|---|
| W1 | `logs/prod_runner.json` · `services.arq.status` @ 17 | 值为 `external` 属**正常设计**：`erp-prod` 以 `--no-arq` 启动，ARQ 由 NSSM 服务 `erp-arq` **单独托管**，故 `prod_runner` 不持有 ARQ 子进程 |
| W2 | `logs/prod_runner.json` · `services.frontend.status` @ 17 附近 | 值同为 `external`：前端由 `erp-web` 托管，`prod_runner` 只做健康汇总 |
| W3 | `config/nginx.conf` · `root /app/...` | Windows 上**永不生效**的死配置；生效的是 `config/nginx-windows.conf`。**不判故障**，但可作为 P3 技术债（清理死文件） |
| W4 | `frontend-vite/vite.config.js` 与 `vite.config.ts` **并存** | js 是 `vue-tsc -b` 编译 `vite.config.ts` 的**设计产物**，且有回归测试 `fastapi_app/tests/test_qa_prod_stack_regression.py` 断言二者一致；**不得**判为重复文件、不得建议删除（红线 5） |
| W5 | `endpoints/backup/`、`endpoints/purchase_center/` 未在 `router.py` 中逐个 `include_router` | 经各自 `__init__.py` **聚合**后再挂载；判定死代码必须按**全仓导入**，不得报「孤儿模块」（历史伪影：曾误报 48 个） |
| W6 | `pytest.ini` 中文注释在 GBK 终端显示为乱码 | 终端编码问题，文件本身为 UTF-8；**不算**文件损坏，**不算** finding |
| W7 | 根目录 `.agent/` `.claude/` `.cursor/` `.codebuddy/` 等 AI 工具痕迹目录 | 已被 `.gitignore` 覆盖（`AGENTS.md` §7），**不算**安全 finding；但**未被忽略**的散落文件属 D06 技术债 |
| W8 | `logs/prod_runner.json` 中 `ready: true` 且 `frontend_ok: true` 而服务状态多为 `external` | 健康口径**以该文件为准**（`AGENTS.md` §3），`external` 不等于不健康 |
| W9 | `fastapi_app/api/v1/router.py` · prefix="/users" 的 `dependencies=[Depends(get_current_user_id)]` @ 130-134；同文件 prefix="/permissions" 同一写法 @ 261-265 | **刻意 fail-open**。原文注释：strict 变体在「Redis 启动即不可用且本地撤销缓存未命中」时会**永久 401**（`redis_cache.init_app` 失败后不重试，只能重启进程回正），本仓库有**开机顺序事故史**。全仓 34 个挂载里**只有 /backup 用 strict**（`fastapi_app/api/v1/router.py` · `include_router(backup_router)` @ 273）。**T10 不得报「认证绕过 / 越权」** |
| W10 | `fastapi_app/api/v1/endpoints/monitoring.py` · 「POST /vitals 由前端 sendBeacon 上报，无法携带 auth header，因此不作认证」 @ 46-47 | 刻意：`sendBeacon` **无法携带 header**。需认证的读端点单独声明在 `fastapi_app/api/v1/endpoints/monitoring.py` · `Depends(get_current_user_id)` @ 225-228。**T10 不得报「敏感端点未鉴权」** |
| W11 | `pyproject.toml` · 唯一表头 `[tool.code-quality]` @ 13 | 刻意**无** `[project]` / `[build-system]`：依赖真源是 `requirements/*.txt`（base / dev / ocr / migration / s3 / desktop / test）。**T11 / T12 不得报「打包元数据缺失」** |
| W12 | `ruff.toml` · `external = ["BLE001"]` @ 11（理由见同文件头部注释） | 刻意：BLE001 由 `scripts/check_bare_except.py` 消费、**不是** ruff 规则；不声明为外部规则会被 RUF100 当冗余指令删掉，而它是质量门禁的**审计豁免凭证**。**D09 / T14 不得报「抑制规则滥用」** |
| W13 | `ruff.toml` · `"fastapi_app/services/backup/__init__.py" = ["I001"]` @ 45（理由见同文件上方注释） | 刻意：该导入顺序与 isort 冲突但**保护契约** —— 否则 Redis 还原锁被 `query_service` 的 advisory 版遮蔽，端点 `finally` 抛 `TypeError`。**D09 / T14 不得报「抑制规则滥用」** |
| W14 | `pyproject.toml` · `[tool.code-quality]` @ 13 | `max_file_size=1600` 看似太松但**有依据**：受扫 777 个 `.py` 中仅 2 个超 1200（项目注释原文：`fastapi_app/tests/test_purchase_center.py` 1497、`fastapi_app/services/backup/orchestration/recovery_test_service.py` 1353；**实测**：1554 / 1354）。**T14 不得报「阈值过松」** |
| W15 | `mypy.ini` 注释里的过期示例（处置口径见 §6.4 @ 271-272） | 注释举例的两个「真实缺陷」**已修复**，属**历史记录**；引用任何注释作证据前必须回代码验证**当前**状态。**D02 / D09 照抄注释会报过期 finding**（与 PLAN §4 F-10 对齐） |
| W16 | `git log` 里的 `core.hooksPath` 事故（428 个凭据入库） | **已修复**：`.githooks/` 目录已存在、pre-commit 三层守卫在位；**不得按现状上报**（与 PLAN §4 F-11 对齐） |
| W17 | `_ops/credentials/` 下的 `.env.bak-*` / `_backup_encryption_password.txt` / `_metrics_bearer_token.txt` | **磁盘明文属预期**：这是指定的凭据存放处，已被 `.gitignore` · `/_ops/` @ 335 覆盖、**未入库**；须验证的是 **ACL**（归 T10）。**不得**把「存在明文」本身当 finding（与 PLAN §4 F-12 对齐） |
| W18 | `deliverables/`（106 项）、`evidence/`（190）、`mockups/`（10）已入库 | **历史归档 / 过程件**：`deliverables/` 是 `AGENTS.md` §2 明示的历史交付物归档（**不是**现行真相），`evidence/`、`mockups/` 属过程件。**不得**当作缺陷重报（与 PLAN §4 F-17 对齐） |

> **上游全集指路**：`team/REPOWIKI.md` §7.4 表体 **9 行**（@ 234–242）+ `team/完整的审核一下我这个项目-060103/RESEARCH.md` §5.2 表体 **13 行**（@ 195–207）⇒ 原始 **22 行**、去重 **14 条**，为本白名单的**上游全集**，与 §6.3 必须一致；两者冲突时**以 §6.3 为准**，但**任何一方命中即不得作为 finding**（A20 对三者统一判定）。

### 6.4 证据标准

| 项 | 内容 |
|---|---|
| **禁止什么** | 禁止提交**无锚点**、**无复现步骤 / 推理链**的「疑似问题」；禁止把「文档这么说」当作证据（文档可能过期）；禁止把 grep / 正则的文本匹配当作 Python 结构结论 |
| **期望结果** | 每条 finding 满足 §5.2 格式；P0/P1 双证齐全；结构类结论（导入关系、迁移依赖图、`__init__.py` 聚合）**必须用 `ast`**，并贴出所用脚本片段 |
| **验收方式** | A03 / A04 / A12 / A13；T15 逐条复核并给撤销率 |
| **过期注释** | `mypy.ini` 注释里举例的两个「真实缺陷」**已修复**，属**历史记录**：`fastapi_app/services/ocr/_extractors.py` · `_pdf_extracter = _img_extracter = _table_extracter = None` @ 22-24；`fastapi_app/services/batch_import_dedup.py` · `Container[Hashable]` → `Iterable` @ 32 |
| **过期注释 · 处置** | **D02 / D09 照抄注释会报过期 finding**。引用任何注释作为证据前，必须回到代码验证**当前**状态；T15 复核时对「以注释为唯一证据」的 finding 直接判 `rejected` |

### 6.5 幻觉处置

| 项 | 内容 |
|---|---|
| **禁止什么** | 禁止把**未复核**的 finding 直接派成修复任务；禁止在 `SUMMARY.md` 里引用未进 `FINDINGS.json` 的 finding；禁止对「未实跑」的命令写「通过」 |
| **期望结果** | finding 的 `status` 必须由 T15 收敛为 `confirmed` / `rejected` / `merged`；未复核的停在 `open` 且**不得**进入 backlog |
| **验收方式** | A22（无 `open` 残留）+ A14（P0/P1 全映射到 backlog）+ A10 |

---

## 7. 边界 Case

| # | 情形 | 处置（不得「视情况而定」） |
|---|---|---|
| B1 | **代码与文档冲突** | **以代码为准**（`AGENTS.md` §6）。文档侧记为 P3「文档过期」并给出正确结论 |
| B2 | **门禁命令跑不起来**（缺依赖、Node 版本、DB 不可达、超时） | 标注「**未实跑**」+ 阻塞原因 + 已尝试的命令原文；**不得**算通过；**不得**为跑通而改配置或装包 |
| B3 | `alembic.ini` 存在但 `migrations/env.py` 未出现 `alembic.ini` 字样 | 以 `migrations/env.py` + `scripts/check_alembic_heads.py` 的**实测**为准；`alembic.ini` 是否权威由 T09 判定并记录（不得凭文件名下结论） |
| B4 | 解析方法与既有简报结论不一致（例：head 数、孤儿模块数） | **以 `ast` 为准**；报告必须写明「用 X 方法得到 A，用 ast 得到 B，采信 B」 |
| B5 | BOM 位置与既有简报不符 | 以**实测扫描**为准，简报描述标注「**未复现**」；命中文件逐个列出 |
| B6 | 中文乱码 / 终端编码差异 | 不算 finding（§6.3 W6）；若文件**本身**非 UTF-8（如 `-Encoding utf8` 写入的 BOM），才算 D09 finding |
| B7 | 两个角色报同一条 finding | **合并**到主责维度，保留最早 id，其余写 `status=merged` 并交叉引用 |
| B8 | 生产正在被使用（有真实用户） | 只读命令**限时**；发现命令触发长事务 / 大扫描立即终止并记 `blocked-by-policy` |
| B9 | Q1（只读）与 Q5（含修复后验证）冲突（**已裁定取 Q1**） | SPEC 按 Q1 冻结；修复后验证**不实施**，**T20 条件任务已撤销**（`status=cancelled`，条目保留），**不得**执行 |
| B10 | 某维度**确实没有问题** | 仍须产出该维度工件，写明「未发现 P0–P3 问题」+ **已查项清单** + 所用方法；空工件不算交付 |
| B11 | 发现疑似 P0 但无法确认 | 降级为 P1 并标注 `needs-verification`；**不得**直接报 P0 制造恐慌，也**不得**删除 |

---

## 8. 首个可运行里程碑（10 分钟首产物）

> **如实说明**：本项目为**只读审核**，**没有可运行骨架** —— 理由：Q1 只读（不产出业务代码）、Q2 禁止起服务（不能 `python start.py` / `uvicorn` / `npm run dev`）。因此「可运行」退化为「**可复现的现状度量命令**」。

**10 分钟首产物（两件）**：

1. `team/REPOWIKI.md` 落盘（T01 researcher）—— 现状知识地图：目录职责、拓扑、端点挂载、迁移 head、门禁基线。
2. 一条**可复现的现状度量命令**（下例已实跑，原始输出见 §9.4）：

`@
$code = @'
import ast, os, json
d = r"migrations/versions"
rev, down = {}, {}
for f in sorted(os.listdir(d)):
    if not f.endswith(".py"):
        continue
    raw = open(os.path.join(d, f), "rb").read()
    t = ast.parse(raw.decode("utf-8-sig"))
    for n in t.body:
        if isinstance(n, (ast.Assign, ast.AnnAssign)):
            tgts = n.targets if isinstance(n, ast.Assign) else [n.target]
            for tg in tgts:
                if isinstance(tg, ast.Name) and n.value is not None:
                    if tg.id == "revision":
                        rev[f] = ast.literal_eval(n.value)
                    elif tg.id == "down_revision":
                        down[f] = ast.literal_eval(n.value)
ref = set()
for v in down.values():
    if isinstance(v, str):
        ref.add(v)
    elif isinstance(v, (tuple, list)):
        ref.update(x for x in v if isinstance(x, str))
print(json.dumps({"files": len(rev), "heads": sorted(f for f, r in rev.items() if r not in ref)}))
'@
$code | python -
`@

**期望输出**：`{"files": 99, "heads": ["pg_standalone_060_fix_updated_at_varchar_columns.py"]}`
**失败处置**：若 Python 不可用 ⇒ 改用仓库原生 `python scripts/check_alembic_heads.py`；两者都不可用 ⇒ 标注「未实跑」并按 B2 处置。

---

## 9. 测试计划（qa 实跑清单）

### 9.1 实跑前置（**必须先做，否则禁止实跑**）

1. **前置①（可机判两步，缺一不可）**：
   - **①-a** 读出并记录**解析后的** `TEST_DATABASE_URL`（口令打码），**断言**其库名 ≠ `DB_NAME` **且**以 `_test` 结尾；
   - **①-b** 若环境变量 `TEST_DATABASE_URL` **已被设置**、或上述断言**不成立** ⇒ C04 判 `blocked-by-policy`，在 `TEST.md` 标「**未实跑**」+ 阻塞原因，**不得**算通过；
   - **覆盖范围** = `pytest.ini` · `testpaths` @ 3 实际覆盖的**全部** conftest：`tests/conftest.py`、`tests/e2e/conftest.py`、`tests/e2e_api/conftest.py`、`fastapi_app/tests/conftest.py`（共 4 个；`tests/` 下 112 个 `test_*.py`）；
   - **依据（写操作实测）**：`tests/conftest.py` · `TEST_DATABASE_URL = _build_test_db_url()` @ 96 优先**直接采信**环境变量 `TEST_DATABASE_URL`（@ 80-82，任何值、不校验），否则 @ 91 用 `parsed.path.replace` 把库名后缀替换为 `_test`（**纯字符串替换、不校验结果**）；`tests/conftest.py` · `DROP SCHEMA public CASCADE` @ 181、`CREATE SCHEMA public` @ 182、`create_all` @ 185、提交型 fixture `await session.commit()` @ 298；
   - **显式禁止**：T14 **不得**修改 `tests/conftest.py`（§6.1 只读边界）；
2. 用 `pytest --collect-only -q` 先收集，确认不触发连接生产库的 fixture；
3. 确认 `npm` 与 Node ≥ 22（`frontend-vite/package.json` · `engines.node`）；
4. 每条命令记录：命令原文 + 工作目录 + 退出码 + 原始输出（截断时保留首尾各 30 行）。

### 9.2 命令清单（12 条 · 与 A09 / A11 对齐）

| # | 命令（工作目录） | 预期 | 失败处置 |
|---|---|---|---|
| C01 | `python scripts/quality_gate.py`（`D:\erp_system`） | 退出码 0（棘轮：**不超过** `gate_baseline.json` 计数） | 逐条记录超基线项（文件 + 锚点 + 行号）；**禁止** `--update-baseline` |
| C02 | `ruff check .` | 0 违规 | 记录规则号 + 文件锚点；区分存量 / 新增 |
| C03 | `mypy` | 0 error（或全部为已记录存量） | 记录 error 行；与 `mypy.ini` 的排除项对照 |
| C04 | `pytest -q` | 全绿；注意 `pytest.ini` 的 `filterwarnings = error`（警告即失败） | 贴失败摘要；判定存量 / 新增；**不得**改配置绕过 |
| C05 | `npm run type-check`（`frontend-vite`） | 0 error | 记录 `vue-tsc` 报错文件 + 行号 |
| C06 | `npm test`（`frontend-vite`） | 全绿 | 记录失败用例名 + 断言 |
| C07 | `npm run lint`（`frontend-vite`） | 0 违规 | 记录规则 + 文件 |
| C08 | `npm run check:api`（`frontend-vite`） | 通过 | 记录漂移的端点清单（前端调用 vs 后端路由） |
| C09 | `npm run check:routes`（`frontend-vite`） | 通过 | 记录未挂载 / 未使用路由 |
| C10 | `npm run check:dto`（`frontend-vite`） | 通过 | 记录 DTO 不一致字段 |
| C11 | `python scripts/check_alembic_heads.py` | 单 head | 与 §9.4 的 ast 结论交叉验证 |
| C12 | `python scripts/scan_secrets.py` + `python scripts/check_bom.py` | 无未豁免命中 | 命中逐条列「文件 · 锚点 @ 行号」；区分真密钥 / 误报（误报处置见 `AGENTS.md` §4） |

**补充**（按需，不强制）：`check_n_plus_one.py` / `check_bare_except.py` / `check_function_length.py` / `check_vue_component_length.py` / `check_service_commit.py` —— 分别给出八项基线中对应项的**独立计数**，用于 A11 对照表。

### 9.3 工件自检命令（canonical `verify` · 各任务 inScope 直接复用）

`@
python -c "import pathlib,sys,re;p=pathlib.Path('team/完整的审核一下我这个项目-060103/AUDIT-BACKEND.md');t=p.read_text('utf-8') if p.exists() else '';sys.exit(0 if p.exists() and p.stat().st_size>=3000 and len(re.findall(r'@\s*\d+',t))>=10 else 1)"
`@

含义：工件存在 ∧ ≥3000 字节 ∧ 至少 10 处行号锚点。各任务把 `AUDIT-BACKEND.md` 换成自己的工件名即可。

### 9.4 已实跑基线度量（pm 在 T02 期间实跑，**只读 ast 探针**，非门禁命令）

原始输出（节选，完整探针见 `RESEARCH.md` / T01）：

`@
{
 "router_include_router_count": 34,
 "router_lines": 324,
 "migration_files": 99,
 "migration_revision_count": 99,
 "migration_heads": ["pg_standalone_060_fix_updated_at_varchar_columns.py"],
 "migration_roots": ["add_product_factory.py","add_product_price.py","add_purchase_plan_composite_indexes.py","pg_standalone_001_pg_standalone_initial_schema.py"],
 "py_files_fastapi_app": 527,
 "endpoints_py": 33,
 "vue_files_frontend": 284,
 "ts_files_frontend": 281,
 "tests_files": 144,
 "docs_md": 209,
 "alembic_ini_exists": true,
 "prod_runner": {"ready": true, "frontend_ok": true, "mode": "production", "workers": 8, "api_port": 5002, "web_port": 3000},
 "gate_baseline.counts": {"n_plus_one":0,"bare_except":9,"function_length":52,"vue_component_length":7,"service_commit":9,"bom":0,"alembic_heads":0,"env_drift":0}
}
`@

**由此确认的基线锚点**（供各角色直接引用，勿重复推导）：

| 事实 | 锚点 | 行号 |
|---|---|---|
| 单 head 迁移 | `migrations/versions/pg_standalone_060_fix_updated_at_varchar_columns.py` · `revision = 'pg_standalone_060_fix_updated_at_varchar_columns'` | 42 |
| 路由挂载起点 | `fastapi_app/api/v1/router.py` · `api_router.include_router(` | 46 |
| 门禁基线文件 | `scripts/quality_gate.py` · `BASELINE_PATH = PROJECT_ROOT / "scripts" / "gate_baseline.json"` | 40 |
| 三阈值配置 | `pyproject.toml` · `[tool.code-quality]` | 13 |
| 测试路径 | `pytest.ini` · `testpaths = tests fastapi_app/tests` | 3 |
| 前端类型门禁 | `frontend-vite/package.json` · ``type-check`: `vue-tsc --noEmit`` | 21 |
| ARQ 外置设计 | `logs/prod_runner.json` · `services.arq.status` | 17 |
| 迁移元数据 | `migrations/env.py` · `target_metadata = Base.metadata` | 57 |
| 密钥扫描入口 | `scripts/scan_secrets.py` · `def main(argv: list[str] | None = None) -> int:` | 237 |

**已知伪影警告**：若解析迁移依赖图时只处理 `ast.Assign` 而忽略 `ast.AnnAssign`（本仓大量 `down_revision` 带类型注解），会得出 **3 个 head** 的**错误**结论；同理，若按「是否被 `router.py` 直接引用」判定死代码，会误报孤儿模块。**两次方法结论不一致时，一律采信 `ast`。**

---

## 10. 假设与「已修正的输入偏差」

| # | 输入简报的说法 | 实测 | 处置 |
|---|---|---|---|
| S1 | 「本仓库**无** `alembic.ini`」 | `alembic.ini` **存在**（2071 字节，含 `script_location`）；但 `migrations/env.py` 未出现 `alembic.ini` 字样 | 按 B3 由 T09 判定权威性；本 SPEC 不预设结论 |
| S2 | `scripts/prod_audit/*.py` 与 `tests/qa/__init__.py` 带 UTF-8 BOM | 实测 **未命中**；实际命中 BOM 的是 `scripts/migrate_erp_web.ps1`、`scripts/phase1_switch.ps1`、`tests/stress/stress_output.log` | 按 B5 标注「未复现」；以 T14 的 `check_bom.py` 实测为准 |
| S3 | `logs/prod_runner.json` 里 `arq.status="external"` | 实为 `services.arq.status = "external"`（**嵌套在 `services` 下**，顶层无 `arq` 键） | 白名单 W1 已按实际 JSON 指针写死 |
| S4 | 「`docs/deliverables/` 是历史归档」 | `docs/deliverables/` **不存在**；历史归档在仓库根 `deliverables/` | Out of Scope 已按实际路径表述 |
| S5 | 「12 维度」但只列举了 10 项 | 实列 10 项 | 补齐 D11 / D12，理由见 `DECISIONS.md` 决策 5 |
| S6 | （本轮实测新增）假定工作树干净 | `git status --porcelain` 实测 **22 行**：18 个 `M`（`fastapi_app/services/` 3 个 + `fastapi_app/shared_models/` 1 个 + `fastapi_app/tests/` 1 个 + `frontend-vite/src/` 13 个）+ 3 个 `??` 未跟踪前端/Python 测试 + `?? team/` | **A21 的比对基线必须是「审核开始时」的快照，而非「`git status` 全空」**；T17 据此判定「本轮未新增改动」。这些既有改动**不属于本轮审核责任**，但必须由 T11 在 `AUDIT-OPS.md` 中作为「生产工作树与 HEAD 不一致」独立记录（证据：`git status --porcelain` 原始输出）。**追加实测（T02 修订批次）**：非 `team/` 的 dirty 行数已由 **22 → 24**（20 `M` + 3 `??` 测试 + `?? team/`）；对全部 `M` 文件取 `LastWriteTime` 得 16 个集中在 `09-30 14:04:42`，另 4 个为 `14:07:17` / `14:15:33` / `14:16:03` / `14:16:24`，**均晚于审核开始快照** ⇒ **生产工作树在审核窗口内被外部持续修改**。故 A21 **不得**按「`git status` 前后完全一致」判定（该口径必然 FAIL 并误判本轮），只判「无本轮归因变更」；T11 须把这一并发修改事实及其对「审核结论时效性」的影响写进 `AUDIT-OPS.md` |

---

## 11. 需求一致性对照起点（D10 的输入清单 · 供 T06/T12 使用）

以下 `AGENTS.md` 断言**必须逐条实测**，输出「一致 / 不一致 / 无法验证」：

| # | 断言 | 出处 |
|---|---|---|
| P1 | `router.py` 以绝对导入挂载全部端点模块，**零孤儿** | `AGENTS.md` §2 |
| P2 | 迁移必须保持**单一 head** | `AGENTS.md` §2 / §5.7 |
| P3 | 生产由 **5 个 NSSM 服务**托管 | `AGENTS.md` §3 |
| P4 | uvicorn 仅绑 **回环 127.0.0.1:5002** | `AGENTS.md` §3 / §5.3 |
| P5 | 生效 nginx 配置是 `config/nginx-windows.conf`，`config/nginx.conf` 是死配置 | `AGENTS.md` §3 |
| P6 | **唯一启动入口**是 `python start.py` | `AGENTS.md` §3 |
| P7 | `core.hooksPath = .githooks`，`pre-commit` **未安装**导致第 ④ 层降级 | `AGENTS.md` §4 |
| P8 | `pytest.ini` 的 `testpaths` **同时**包含 `tests` 与 `fastapi_app/tests` | `AGENTS.md` §2 |
| P9 | `frontend-vite/vite.config.js` 是 `vue-tsc -b` 的**设计产物**，有回归测试断言一致 | `AGENTS.md` §5.5 |
| P10 | `_ops/credentials/` 与 `config/pgbouncer/userlist.txt` **不入库** | `AGENTS.md` §5.2 |
| P11 | `BACKUP_ENCRYPTION_PASSWORD` 为空且 `BACKUP_ENCRYPTION_ENABLED=true` 时**静默降级为不加密** | `AGENTS.md` §5.4 |
| P12 | 未安装 `pre-commit` 时，暂存含 `.py` / `.vue` 会直接跑 `quality_gate.py` | `AGENTS.md` §4 |

---

*本 SPEC 由 pm（T02）冻结。任何角色若认为某条验收标准不可判定，须在 T05 规格评审提出，**不得**在执行阶段自行改标准。*
