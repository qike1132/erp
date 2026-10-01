# 00 · 第二轮全面审计综合报告（决策者版）

> **一句话结论先行**：**这个系统的结构不是最优，但明显高于同规模内网 ERP 的均值**；它与"最优"的差距不是能力差距，而是**三种错位**——① **能力已具备、但没收尾**（有幂等键只有 1 处、有记录级权限依赖但没接、有只读副本依赖但没人用它做报表、有双树测试基建但 13 组同名文件语义重叠）；② **有门禁、但抓错对象**（`max_vue_component_length=400` 抓到的 7 个组件里 6 个是被 CSS 撑大的，真正的 script 重灾区一个都没进门禁；ruff 70 条报错里 55 条落在 `server_manager/`+`scripts/`，业务代码只有 1 条）；③ **有方案、但没人核验执行状态**（22 项优化方案里 9 项已完成、4 项进行中、**3 项已关闭或降级**、5 项未做、1 项不可核验——**五桶齐全、合计 22，详见 §8.4**，而仓库里没有任何地方记录这个状态——本条审计本身就是在补这个洞）。

> **本文件元信息**
>
- **审计轮次**：2026-10-01 第二轮全面审计（binfa-ERP / `D:\erp_system`）
- **取证基线**：`aac4c43f59a4374e05cdc5aee6c4aaa8afc99026`（2026-10-01 14:52:03 前后，六份成员报告取证时的 HEAD）
- **归档 / 本文件写作基线**：**HEAD = `546401ec6cfeb0bb14664d21ff5d06a618a4e060`（2026-10-01 15:10:43）**，工作树干净
- **与取证基线的差异**：中间新增 **1 个提交** —— `chore(types): mypy 覆盖 106→110`（OPT-13 第一批），顺带删除死代码 `fastapi_app/services/staging_utils.py`
- **素材**：`docs/audit-round2/01`～`06`（6 份成员报告归档副本）+ `README.md` + `06-oss-erp-raw-capture.txt`
- **本轮核实方式**：本文件的每条 `文件:行` 均由写作会话**在 HEAD=546401ec 上打开文件逐行确认**，不照抄成员转述；无法当场确认的一律标注「未验证」
- **只读声明**：**只读静态审计**。未改任何代码/配置/数据库，未重启服务，未跑测试套件，未压测，未构建前端，未做空库重放迁移，未做恢复演练。临时脚本仅写 `%TEMP%\erp_audit_v2\`
- **写作时间窗**：2026-10-01 第二轮审计当日

---

## 目录

1. [结论与三种错位](#1-结论与三种错位)
2. [六份报告的一致结论（证据地图）](#2-六份报告的一致结论证据地图)
3. [开源 ERP 对比：哪些是真的、哪些不适用](#3-开源-erp-对比哪些是真的哪些不适用)
4. [问题清单 P0 / P1 / P2](#4-问题清单-p0--p1--p2)
5. [三批路线图](#5-三批路线图)
6. [证据边界与不确定项](#6-证据边界与不确定项)
7. [对上一轮结论的两处修正](#7-对上一轮结论的两处修正)
8. [素材缺口与信度](#8-素材缺口与信度)
9. [可复现命令与核验清单](#9-可复现命令与核验清单)

---

## 1. 结论与三种错位

回答用户问题「结构是不是最优 + 还有没有提升空间」：**不是最优；提升空间大，但几乎全部落在"收尾 / 校准 / 核验"三件事上，而不是"重写架构"。**

### 1.1 为什么说"高于同规模均值"

第二轮六份报告在四个维度给出了可验证的正面证据：

| 维度 | 证据（`文件:行` / 可复现命令） | 与开源 ERP 的相对位置 |
|---|---|---|
| 迁移纪律 | 单 head 实证 `python -m alembic -c migrations/alembic.ini heads` → `pg_standalone_060_fix_updated_at_varchar_columns`；CI 在 `.github/workflows/ci-cd.yml:63-66` **强制**跑 `alembic upgrade head` + `alembic check` | 五家开源 ERP **没有一家**在 CI 里跑 `alembic check` 等价断言（`06:§1⑥`） |
| 质量棘轮 | `scripts/quality_gate.py:189-198` 基线棘轮（"数字只允许下调"）+ `pyproject.toml:15/18/25` 三条硬阈值（函数 80 行 / .vue 400 行 / .py 1600 行） | Dolibarr 才刚上 pre-commit，iDempiere 的 `.github/workflows` 只有 `sonarqube.yml` 一个（`06:§1⑥`、`06:§6`） |
| 鉴权实现 | ES256 + `jti`/`type`（`fastapi_app/core/auth/token.py:57-58`）、Argon2id（`fastapi_app/core/security.py:13-20`，m=19456,t=2,p=1）、刷新轮换宽限（`fastapi_app/api/v1/endpoints/auth.py:345`）、黑名单（`fastapi_app/core/auth/blacklist.py:61-81`）、登录限流（`auth.py:27-30`） | 达到或超过多数开源 ERP 的默认水位 |
| 可观测性下限 | `/metrics` 生产 **fail-closed**（`fastapi_app/core/health.py:209-211` 无 token 返 503、`:212-213` token 不符返 401） | 很多开源 ERP 默认把监控端点敞着 |

### 1.2 三种错位（本报告的主线）

**错位一 · 能力已具备、没收尾**
- 幂等键只有 **1 个端点**有：`fastapi_app/api/v1/endpoints/purchase_center/order_routes.py:113`（`X-Idempotency-Key`，`:117-118` 同键 10 分钟内复用结果）。全仓 `idempot` 命中 26 处、分布在 17 个文件，其中 8 个是测试文件——**做法对，推广没做**。
- 记录级可见性依赖**已经写好**：`fastapi_app/core/deps.py:363` `resolve_production_view_scope` / `:383` `resolve_production_write_scope`；但客户、订单等敏感实体仍是"端点内手写判断"。
- 只读副本依赖**已经写好**：`fastapi_app/core/database.py:333` `get_async_read_db()`，带 2s 检出超时（`:352`）；生产副本 `postgresql-replica` 却是半成品（`replication_slots=0`、无 streaming 状态）；OPT-16 的**状态**依据队长给定事实：**已降级为调查项 16a**（见 §8.4）——**不引 04 号作证**（04 号缺 OPT 状态表，见 §8.1）。
- 前端通用能力**已经写好**：`UiFilterBar` 全仓仅 1 处命中，而 12 个文件在手写 `keyword` ref；`useEventDelegation.ts` 与 `useVirtualScrollList.ts`（167 行）**零消费方**；`useEnhancedList.ts:13` 的唯一消费方是 `frontend-vite/src/views/product/components/ProductTable.vue:60`（调用在 `:90`）。

**错位二 · 有门禁、抓错对象**
- `max_vue_component_length = 400`（`pyproject.toml:18`）报出 7 个超限组件，其中 **6 个由 CSS 撑大**（BomEditor.vue 570 行里 style 260 行 / script 仅 99 行；CompletedOrdersPanel.vue 495 = style 344 + script 55；BackupView.vue 465 = style 74 + script 308 是少数例外）。**真正的 script 重灾区全部低于门禁阈值**：`VirtualList.vue` 258 行 script、`ProductionView.vue` 229、`DashboardChartsSection.vue` 221、`UiAutocomplete.vue` 216、`UiDataTable.vue` 212。
- `ruff check .` 70 条报错中 55 条在 `server_manager/`（28）+ `scripts/`（27），业务代码 `fastapi_app/` 只有 **1** 条（转引 `04`——**该报告为折叠压缩块残片，缺 OPT-01..22 状态表与工程健康度总评，此处只作线索、非 OPT 状态证据源，需重跑 t4 补齐**；见 §8.1）。
- mypy 棘轮覆盖面 `mypy.ini` 实测 **106** 个文件、已纳入范围 **0 错**；但对 `fastapi_app/services/` 单独全量复核 = **Found 387 errors in 68 files**（`arg-type` 97、`assignment` 60、`attr-defined` 49）。**门禁是绿的，因为它只圈了 106 个文件**；另有 21 个"零错但未纳入"的真实模块可**零成本**纳入（`04:§mypy`——**该报告为折叠压缩块残片，缺 OPT-01..22 状态表与工程健康度总评，此处只作线索、非 OPT 状态证据源，需重跑 t4 补齐**；见 §8.1）。

**错位三 · 有方案、没人核验执行状态**
- 22 项优化方案（`docs/optimization-plan-2026-10-01.md`）逐项执行状态**在仓库里没有任何记录**；本轮由队长以 t4 原始运行结论给定（见 §8.4），仓库存量只留了一份**判描述是否属实**的审计（`docs/optimization-plan-audit-2026-10-01.md`：22 项中 14 属实、4 需修正方向、3 项 BLOCKER）——**它从不判"是否已执行"**。
- 最典型的两个例子：`docs/adr/2026-10-01-migration-roots-are-cosmetic.md` 已明确"不对迁移链做任何修根操作"，而优化方案 OPT-14 仍把"迁移图 4 根"列为待办；OPT-09 的度量基线「useApiMutation 仅 4 处」**已经过时**（本轮实测 30 处命中，定义在 `frontend-vite/src/composables/useApiMutation.ts:23`）。

---

## 2. 六份报告的一致结论（证据地图）

| # | 报告 | 完整性 | 一句话结论（本轮核实口径） |
|---|---|---|---|
| 01 | `docs/audit-round2/01-backend-structure.md` | 完整 | 分层图健康（560 个 .py、ast 解析 `parse_fail=0`、1209 模块 / 2674 边），但**没有仓储层**、`core` 是万能内核（入度 591）、`services/` 184 个文件中 78 个（42%）平铺在根 |
| 02 | `docs/audit-round2/02-frontend-architecture.md` | **不完整（中）** | views 直接调 API = 0（153 个文件经 `@/api` 真调用）、无页面直改 store 内部状态；短板在通用能力零消费方与测试空档 |
| 03 | `docs/audit-round2/03-data-layer.md` | **不完整（高）** | 索引真缺失 **33** 个（ORM 声明 280 vs 库内非主键 256）、单列 FK 86 个中 31 个无前导索引、关系 81 条里 59 条未声明 `lazy`、**approval 表内时钟混写是数据正确性 bug** |
| 04 | `docs/audit-round2/04-engineering-quality.md` | **不完整（高）** | pytest 双树共 3689 个用例但**几乎不重复**（同名并存节点仅 1/3688）；ruff 70 条、mypy 覆盖 106/已纳入 0 错 |
| 05 | `docs/audit-round2/05-ops-security-observability.md` | 完整 | 鉴权强、但**日志静默、ACL 过宽、暴露面大、告警全关**四类叠加；R1–R18 风险清单 |
| 06 | `docs/audit-round2/06-oss-erp-benchmark.md` | 完整 | 本项目在迁移纪律/CI 完整度上超过多数开源 ERP；可抄的是三条**流程级**做法，四类"重体系"明确不抄 |

**统一元信息**：六份报告取证基线均为 `aac4c43f`；归档 HEAD 均为 `546401ec`；每份文首均含"行号可能漂移、引用前必须重新核对"的硬性提醒。

**口径差异（同时成立，不是错误）**——本报告不做合成，原样保留：

| 口径 | 数字 | 出处 | 说明 |
|---|---|---|---|
| 路由数 | **373 / 385 / 382** | 01 / 02 / 05 | 01 数端点装饰器（373 = 48 纯透传 + 289 编排 + 36 不碰 services）；02 从前端视角数；05 数"非测试路由" |
| 测试 .py 文件数 | **148 / 163**（04） vs **110 / 161**（06） | 04 / 06 | 04 数目录内**全部** `.py`；06 只数 `test_*.py`。本轮实测四数**同时成立** |
| pytest 收集用例 | **3689**（tests/ 1465 + fastapi_app/tests 2223） | 04 | `pytest --collect-only` |

---

## 3. 开源 ERP 对比：哪些是真的、哪些不适用

> **证据来源限制**：本会话 `web_search` 不可用（DeepSeek search endpoint 返回 HTTP 401），所有外部结论**只来自官方文档 / 官方源码仓原文**（`06-oss-erp-benchmark.md` 正文逐条附 URL），原始抓取块另存为 `docs/audit-round2/06-oss-erp-raw-capture.txt`（118,267 B）供外部复核。**外部事实本轮未复抓**。

### 3.1 反直觉实证：本项目 CI 门禁比多数开源 ERP 更硬

`.github/workflows/ci-cd.yml`（302 行，仓库**唯一** workflow）实测结构：

| 位置 | 内容 | 性质 |
|---|---|---|
| `:9-141` | `test` job：postgres:16-alpine 服务 + Python 3.13 + `pip install -r requirements.txt` | — |
| `:63-66` | `alembic upgrade head` → **`alembic check`** | **硬门禁**（迁移与 ORM 模型必须一致） |
| `:84-90` | `pytest tests fastapi_app/tests` + `--ignore=tests/qa, e2e, stress, performance` + `--cov=fastapi_app` | 硬门禁（真跑） |
| `:39` + `:140-142` | `COVERAGE_MIN: "40"` + 就地阈值判定（低于即 `exit(1)`） | 硬门禁 |
| `:144-...` | `lint` job（ruff/mypy） | 硬门禁 |
| `:...-139` | 安全扫描 job（bandit / pip-audit 报告落盘） | 硬门禁 |
| `:215-226` | 前端 job：`npm ci` + `npm run lint`；`:218-224` 注释自陈已删除 `playwright install`（**全仓无 playwright.config、无 e2e/ 目录、无 test:e2e 脚本**） | 硬门禁；e2e **未做** |

对照开源 ERP（`06:§1⑥`）：Odoo **不用 GitHub Actions**（自建 Runbot）；iDempiere 的 `.github/workflows` **只有 `sonarqube.yml`**；Dolibarr 22 个 workflow 含 pre-commit/phpstan；Frappe 22 个、erpnext 25 个（含 server-tests-mariadb/postgres、docs-checker、semantic-commits）。**结论**：论"每次提交都强制验证 schema 一致性"，本项目领先；论"发布/文档/提交信息自动化"，本项目落后（无 `semantic-commits`、无 `docs-checker`）。

### 3.2 单公司 / 单币种是架构不变量（不是缺陷，但必须留缝）

本轮在 HEAD=546401ec 上实测（可复现命令见 §9）：

| 检查 | 结果 |
|---|---|
| `company_id\|company_code\|multi_company\|tenant_id` 于 `fastapi_app/**/*.py` | **0 命中** |
| 同四项于 `migrations/versions/*.py` | **0 命中** |
| `\bcurrency\b`（词边界）于 `fastapi_app/schemas/*.py` | **0 命中** |
| `\bcurrency\b` 于 `fastapi_app/shared_models/*.py` | **0 命中** |
| `\bcurrency\b` 于 `migrations/versions/*.py` | **0 命中** |
| `entry_point\|plugin` 于 `pyproject.toml` | **0 命中**（无插件入口） |

**关键背景**：`06:§0` 指出此前统计的"15 处 currency 命中"**全部是 `concurrency` 的误匹配**——这正是本项目"正则解析产出伪影"的又一例（同 `AGENTS.md §6` 记载的"15 个迁移 head""48 个端点模块未接线"两类伪影）。

**为什么"不抄多公司"是对的**：五家开源 ERP **没有一家把 `tenant_id` 铺进业务表**——Odoo/Frappe 是"一个部署 = 一个库 = 多个公司"（Company DocType / `res.company` + `ir.rule`），Tryton 单库单公司集合，Dolibarr 内核单公司，iDempiere 多客户端靠**多实例**（`06:§1④`）。本项目是内网、单公司、单实例，引入多公司会污染 46 个模型文件与全部报表。

**但别躺平**：正确动作是把"公司 / 本位币"**收敛为配置项**（`fastapi_app/core/config.py`）而不是散落业务常量，让未来改造面可控——这条已进 §5 批三。

### 3.3 Top 5 可借鉴（按 收益/成本 比，来自 `06:§3`）

1. **迁移与升级的"可审计契约"**（借鉴 iDempiere `YYYYMMDDHHMM_IDEMPIERE-<n>.sql` 命名 + Tryton 逐 series 的 Before/After 人工 SQL 清单）——新增迁移命名规范 `YYYYMMDD_<需求号>_<动词>`（**不动历史文件**，符合既有 ADR）、runbook/PR 模板增"本次升级需人工核对项"、把 `alembic check` 升格为文档化不变量。**P0**（理由：本机既是生产又是运维主机、无测试环境，人工清单是**唯一**升级安全网）
2. **通用幂等层**（推广 `purchase_center/order_routes.py:113` 的既有做法）——抽 `X-Idempotency-Key` 为可复用 dependency、明确 TTL 与"失败不缓存"语义、补"同键并发"回归用例。**P0**
3. **扩展点清单 + 覆盖层规范（文档先行）**（借鉴 Frappe hooks 清单、Dolibarr "不改核心文件" hooks 原则）——先产出可扩展点清单（`fastapi_app/api/v1/router.py` 挂载点、服务层接口、权限点、配置项）并写明"客户特有逻辑只允许落在 X 目录"。**P1**
4. **权限的记录级最小切片**（借鉴 Odoo `ir.rule` / Tryton 5 层中的 Record Rule，只取一层）——对最敏感的 2~3 类实体（客户、订单）定义声明式"归属过滤"，在查询层统一注入，**禁止端点内手写可见性判断**；保留 `require_permission`（`fastapi_app/core/deps.py:279`）不动。**P1**
5. **发布 / 文档自动化两个轻量 job**（借鉴 ERPNext `semantic-commits.yml` / `docs-checker.yml`）——提交信息规范校验（驱动 CHANGELOG）+ 文档内部引用可达性检查（`docs/` 下 221 篇 `.md`）；顺带把 `COVERAGE_MIN`（`ci-cd.yml:39`）从"固定 40"改成**棘轮式只升不降**，与 `quality_gate.py:189-198` 同构。**P1**

### 3.4 明确不建议照抄的 8 项（来自 `06:§4`）

| # | 不抄什么 | 原因（含本项目证据） |
|---|---|---|
| 1 | Odoo 单库多公司 + 多币种内核化 | `company_id/multi_company/tenant_id` 全仓 0 命中、`\bcurrency\b` 0 命中；会污染 46 个模型与全部报表，且没有第二家公司存在 |
| 2 | Frappe/ERPNext 元数据驱动 + 自动 DDL（MD5 比对 schema、删列不删） | 与既有 ADR（显式 Alembic + 单 head + `alembic check`，`ci-cd.yml:66`）直接冲突；生产单实例上自动 DDL 不可回滚 |
| 3 | Odoo XML-RPC / Tryton JSON-RPC 风格 API | REST + OpenAPI + 前端 TS 类型链路已成型，改 RPC 让类型与文档收益全部作废 |
| 4 | API 前缀版本化（`/api/v2`） | `docs/adr/2026-09-30-api-versioning-and-health-probes.md:9` 已明确拒绝并删除 v2（前端对 v2 请求数为 0）；照抄等于推翻生效决策 |
| 5 | iDempiere 的 OSGi 插件体系 / Java+ZK 技术栈 | 体量与团队严重不匹配（1 个 Python/FastAPI+Vue 团队、Windows 内网、NSSM 托管） |
| 6 | Dolibarr/ERPNext/Odoo 的多分支并行维护与长支持周期 | 无外部调用方、无 SaaS 客户；内网可常驻单版本（与 Odoo "On-premise 可不限期停留"一致） |
| 7 | Odoo Tours / Playwright 端到端全铺 | `ci-cd.yml:87` 已显式 `--ignore=tests/e2e`，`:218-224` 自陈 playwright"已装未用"；正确动作是**先删死依赖或补齐配置** |
| 8 | Tryton 的"人工 SQL 迁移"作为迁移机制本身 | 其前提是 schema 自动管理、只人工处理数据；本项目 Alembic 线性链确定性更强。可借鉴的只是它的**清单/文档形态** |

---

## 4. 问题清单 P0 / P1 / P2

> 全部 `文件:行` 已在本轮 HEAD=546401ec 打开文件确认。**未在本次写作会话当场确认的项已显式标注「未验证」**。

### 4.1 P0-A · 静默数据正确性（用户看到 200，数据可能没落库）

| ID | 问题 | 证据（本轮实测） | 为什么是 P0 |
|---|---|---|---|
| **P0-A1** | **事务提交发生在响应之后，失败只记日志** | `fastapi_app/core/database.py:203` `get_async_db()`；`:226-227` 注释自陈"依赖收尾在响应发送之后执行，commit 失败时客户端已收到成功响应"；`:229` `await session.commit()`；`:230-233` 捕获 `(RuntimeError,OSError,ValueError,SQLAlchemyError)` 后 `logger.error("事务提交失败：响应已发送但数据未落库（静默丢失风险）"…)` | 唯一的最后防线是**一条日志**；日志里连 `request_id` 都没有（注释原文："path 相关信息见请求日志"，即需要人工关联）。写操作会静默丢失 |
| **P0-A2** | **备份加密口令缺失时静默降级为明文** | `fastapi_app/api/v1/endpoints/backup/_deps.py:161-169`：口令三处来源全空时仅 `logger.warning('请求加密备份但未配置密码…本次备份将以未加密形式保存')`，随后 `return False, None` | `AGENTS.md §5.4` 把这条列为红线（"静默降级为不加密备份"），实践中**仍然是静默的** |
| **P0-A3** | **approval 表内时钟混写（8 小时差）** | `fastapi_app/shared_models/approval.py:21-22` `_utcnow()` 返回 naive UTC（注释明确对应 `TIMESTAMP WITHOUT TIME ZONE`）；`:56` `request_time default=_utcnow`；`:61` `updated_at default=datetime.now, onupdate=datetime.now`（**本地 UTC+8**）；另一张表同样：`:128` `action_time default=_utcnow` vs `:130` `updated_at default=datetime.now` | 同一行 `request_time` 与 `updated_at` 相差 8 小时 → **审批时长统计与审计取证同时失真**；这是 t3 全轮唯一被判定为"真 bug"的数据正确性问题 |
| **P0-A4** | **ORM 索引声明在库中不存在（33 个）** | `03:片段A`（**03 号是残片——t3 完整 output 已随团队状态目录丢失，需重跑补齐**）：ORM 声明索引 280、库内非主键索引 256、名不存在 54 个（其中 21 个是同列集改名 = 纯命名漂移，**33 个是真缺失**）。样例：`order.locked_by_id`（ORM 有 `idx_order_locked_by`、库里没有）、`permission.parent_id`（自引用树查询全表扫）、`purchase_order.(created_by, supplier_id+status)` | 缺索引=慢查询；更危险的是**任何人跑 `alembic revision --autogenerate` 会得到一堆 `add_index` + 针对库内 4 个未声明列的 `drop_column` 破坏性 DDL** |

### 4.2 P0-B · 备份与恢复（真出事了恢复不回来）

| ID | 问题 | 证据 | 影响 |
|---|---|---|---|
| **P0-B1** | **恢复演练脚本选错文件，且有 5 周空窗** | `scripts/restore_drill.py:35-36` `newest_backup()` 用 `glob('erp_backup_*.zip')`，实际每日备份是 `erp_auto_daily_*.zip.enc`（加密）→ **选不到当天的备份**；`:42` `async def main()` 只做 ZipFile+restore（全文 56 行）。`recovery_tests/` 最新工件是 `m5_drill_raw_20260823.json`（**超过 5 周**），`disaster_recovery_test_task` 从未入队 | 恢复能力**从未端到端验证过**；这是"备份=有副本，恢复=有把握"的分界线事故 |
| **P0-B2** | **备份文件无定时任务触发** | `erp-watchdog` 计划任务**从未安装**，`watchdog_state.json` 停在 `2026-09-30T18:10:22` | 备份/持仓类自动化链路断在"没有调度器"上 |
| **P0-B3** | **每日全量连续 3 天晚 8 小时** | `schedule_service.py:146` UTC/本地混用（`05` R 清单） | 备份窗口漂移，与本地业务高峰重叠 |
| **P0-B4** | **恢复库口令回落生产口令** | `fastapi_app/services/backup/orchestration/recovery_test_service.py:45/:53` 测试库口令回落 `DB_PASSWORD` → 恢复演练脚本**自带生产库凭据** | 演练反而扩大了凭据暴露面 |
| **P0-B5** | **备份目录里有明文历史包** | `backups/server` 共 130 文件 / 236,843,320 B，09-27 及更早仍是**明文 `.zip`**（加密能力是后加的） | 加密改造只覆盖新增，存量明文未清理 |

### 4.3 P0-C · 安全面

| ID | 问题 | 证据（本轮实测） | 影响 |
|---|---|---|---|
| **P0-C1** | **明文密钥落盘** | `_ops/credentials/_backup_encryption_password.txt:5`、`_ops/credentials/_metrics_bearer_token.txt:1`，以及根目录 `.env.bak-*` | 凭据就在仓库工作区内（虽被 `.gitignore` 覆盖，但能被任何本地进程/备份读到） |
| **P0-C2** | **ACL 过宽：Authenticated Users 对整个应用目录有 Modify** | `Authenticated Users\|Modify` + `BUILTIN\Users\|ReadAndExecute` 继承到 `.env`、`config/jwt/`、`backups/`、`logs/` | 同机任何登录用户可改配置/读日志与备份；与"生产主机=运维主机"叠加后风险放大约束 |
| **P0-C3** | **Redis 口令进命令行与注册表** | 进程 pid 5360/5372 的命令行含口令；NSSM 注册表 `AppParameters` 同样含口令，且 ACL 为 `BUILTIN\Users\|ReadKey` | 口令对普通用户可见 |
| **P0-C4** | **限流键可被 XFF 伪造 + 代理信任全开** | `fastapi_app/main.py:256-265` `_rate_limit_key` → `:262` `_resolve_user_id(request)` → `:265` `return get_remote_address(request)`（未登录时按 IP）；`:271` `limiter.key_func = _rate_limit_key`；`fastapi_app/core/prod_runner.py:268` `"--forwarded-allow-ips=*"` | 未登录端点（登录接口）的限流键可被伪造 `X-Forwarded-For` 绕过；审计 IP 取 XFF 末段与其注释相反 |
| **P0-C5** | **加密生产配置漂移** | `.env.production`：`APP_ENV=development`、`BACKUP_ENCRYPTION_ENABLED=false`，92/94 个键缺失；`fastapi_app/core/config.py:469` `extra='ignore'` | 配置写错**不报错**，静默用默认值 |
| **P0-C6** | **纵向越权读（缺权限点）** | `fastapi_app/api/v1/endpoints/customer_sampling.py:4` docstring 自称"所有端点需登录（router 级 dependencies）"，但 `:63` 是裸 `router = APIRouter()`（**无 `dependencies=`**）；写端点 `:121-126` `api_create_project` 有 `require_permission('customer_sampling_manage')`，而同类 9 个 GET 只挂 `get_read_db` | **任何登录用户可读**这些数据；docstring 与实现不一致，说明这是"以为挂了其实没挂" |
| **P0-C7** | **缓存短路可能绕过黑名单校验** | `fastapi_app/core/deps.py:195-199`：命中 `request.state._jwt_payload` 即 `return int(user_id)`，跳过后续校验路径 | 与 `:71` 的 5 秒权限缓存叠加，登出/吊销后的短窗口内仍可能放行（**影响窗口未验证**） |

### 4.4 P0-D · 暴露面

| ID | 问题 | 证据 | 说明 |
|---|---|---|---|
| **P0-D1** | **PostgreSQL 监听全部地址** | `postgresql.conf:60` `listen_addresses='*'`；对外监听 5432 | 数据库直接可达局域网，绕过 nginx/uvicorn 边界 |
| **P0-D2** | **多个非业务端口对局域网开放** | 21（KMFtp）、7863（wb2api）、3389（RDP）、135/445/5357、`192.168.0.95:139` | 与"内网可信"假设叠加，实为最大攻击面 |
| **P0-D3** | **5 个 NSSM 服务全部 LocalSystem** | `fastapi_app/services/.../service_ops.py:368-405` 不设 `StartName` | 服务被攻破即等于系统权限；`prod_runner` 也不降权 |
| **P0-D4** | **一键把服务绑回 0.0.0.0** | `scripts/restart_backend.py:64-69` `--host 0.0.0.0` | 直接违反 `AGENTS.md §5.3` 红线，且是脚本默认行为 |

### 4.5 P1 · 两到六周内应做

| ID | 问题 | 证据 |
|---|---|---|
| **P1-1** | 33 个真缺失索引 + 31 项无前导索引的 FK | `03:片段A / 片段B ③`（**03 为残片，需重跑补齐**）；建议全部走 `CREATE INDEX CONCURRENTLY`（`migrations/_legacy_base_guard.py:130` `run_concurrently`、`:160` `create_index_if_absent`） |
| **P1-2** | 关系 81 条里 59 条未声明 `lazy`，业务路径真实 N+1 **34 处**（逐条调用点清单属 t3 缺口） | `03:片段B ④`（**03 为残片，需重跑补齐**） |
| **P1-3** | 连接池死配置 + 池未接线 | `03:片段B ⑤`（**03 为残片，需重跑补齐**）：workers=8 → 8×8=64 直连、逼近 `max_connections=100`；`DB_POOL_SIZE/DB_MAX_OVERFLOW/DB_POOL_RECYCLE` **全是死配置**、无 `pool_recycle`（具体配置键位置属 t3 缺口） |
| **P1-4** | 迁移命名双轨制（99 个文件混两套体系）+ 升级人工清单缺失 | `06:§2 #1/#2`；`docs/adr/2026-10-01-migration-roots-are-cosmetic.md` 已禁止改历史文件名 |
| **P1-5** | 前端通用能力零消费方 | `UiFilterBar` 全仓 1 次命中 vs 12 文件手写 `keyword`；`useEventDelegation.ts`、`useVirtualScrollList.ts`（167 行）0 消费方；`useEnhancedList.ts:13` → `frontend-vite/src/views/product/components/ProductTable.vue:60/:90` 唯一消费方 |
| **P1-6** | Pinia 里有两套过期 SWR 实现 | `frontend-vite/src/stores/patternRoom.ts:11-12` 自陈"本 store 为 pattern-room 提供同等能力"（对照 Dashboard 用 TanStack Query）；`:19` `export const PATTERN_ROOM_STALE_MS = 30_000`、`:22` `PATTERN_ROOM_PAGE_SIZE = 20`、`:24` `SESSION_KEY`、`:26` `MAX_PERSIST_CHARS`；`:116-118` 缓存用普通闭包变量（**非 ref，不响应式**） |
| **P1-7** | 死代码 / 未消费导出 | `frontend-vite/src/stores/catalog.ts:18` `CATALOG_TTL_MS`、`:21` `CATALOG_PAGE_PARAMS`、`:83/:89/:95/:102` 四个 `createCatalogEntry`（products/customers/suppliers 三个零消费方）；后端 `fastapi_app/core/exceptions.py:74` `make_error_response(` 为死 helper |
| **P1-8** | 两套错误信封 | `fastapi_app/main.py:302` `@app.exception_handler(AppError)` 输出含 `"code": exc.code`（`:313`）；`:332-341` `http_exception_handler` 信封**没有 `code` 字段**；且 `fastapi_app/core/exceptions.py:203-214` 把全部 `AppError`/`ValueError`/`SQLAlchemyError` 一律**转成 `HTTPException`**，前端永远拿不到业务码 |
| **P1-9** | 前端测试近乎空档 | 348 个 `.vue` 仅 1 个组件测试；`ci-cd.yml` 前端 job 此前从不跑单测（`:228` 注释自陈） |
| **P1-10** | 双树测试语义重叠 + conftest 体量悬殊 | `pytest.ini:3` `testpaths = tests fastapi_app/tests`；`tests/conftest.py` **571 行** vs `fastapi_app/tests/conftest.py` **232 行**（另有 `tests/e2e/conftest.py` 54、`tests/e2e_api/conftest.py` 350） |
| **P1-11** | 依赖无锁、无 `npm ci` | 前端 43 个依赖**全部 `^`**、0 处 `npm ci`；后端依赖唯一来源 `requirements/*.txt`（`pyproject.toml` 无 `[project]`） |

### 4.6 P2 · 六到十二周

| ID | 项 | 依据 |
|---|---|---|
| **P2-1** | 扩展点清单 + 覆盖层规范（文档先行） | §3.3 #3 |
| **P2-2** | 记录级权限最小切片（客户/订单 2~3 类实体） | §3.3 #4 |
| **P2-3** | 提交信息规范校验 + 文档引用检查两个轻量 job | §3.3 #5；`docs/` 221 篇 `.md` |
| **P2-4** | `COVERAGE_MIN`（`ci-cd.yml:39` = 40）改棘轮式只升不降 | 与 `quality_gate.py:189-198` 同构 |
| **P2-5** | 公司/本位币收敛为配置项 | §3.2 |
| **P2-6** | 前端依赖锁定 + `npm ci`；清理 4 个历史 `dist` 目录（15.8 MB） | `02:§短板` |
| **P2-7** | 字段级 API 对齐（现 `npm run check:api` 只校验移动端端点字符串，不校验字段） | `02:§短板` |

---

## 5. 三批路线图

> 排序原则：① **先堵静默失败**（不报错的问题优先于报错的问题）；② 再做"低成本、零风险、立刻可验证"的收尾；③ 最后做需要设计决策的项。每批都给出**验收方式**。

### 批一 · 上线前（本周内，全部为小改 + 可回滚）

| 序 | 动作 | 目标文件 | 验收方式 |
|---|---|---|---|
| 1 | commit 失败从"只记日志"改为**可告警信号**（补 `request_id`/path 到日志，并暴露计数器） | `fastapi_app/core/database.py:226-233` | 日志样例含 request_id；计数器在 `/metrics` 可见 |
| 2 | 备份加密口令缺失改为**显式失败**（或至少升到 ERROR + 落审计） | `fastapi_app/api/v1/endpoints/backup/_deps.py:161-169` | 缺口令时请求加密备份 → 拒绝；补一条回归 |
| 3 | 修 approval 表时钟混写（`:61/:130` 统一走 `_utcnow`） | `fastapi_app/shared_models/approval.py:61,130` | 同一行 `request_time` 与 `updated_at` 差 < 1 分钟（**存量数据需单独评估，未验证**） |
| 4 | 修 `restore_drill.py` 的 glob（覆盖 `.enc`），并**真跑一次**演练 | `scripts/restore_drill.py:35-39` | 演练产出新工件，且恢复库能查到行数 |
| 5 | 明文密钥移出工作区 + 收紧 ACL（`.env`/`config/jwt/`/`backups/`/`logs/` 去掉 Authenticated Users Modify） | `_ops/credentials/*`、目录 ACL | `icacls` 复核；无凭据文件落在仓库路径 |
| 6 | 给 `customer_sampling` 的 9 个 GET 补 `require_permission`（或删掉误导性 docstring） | `fastapi_app/api/v1/endpoints/customer_sampling.py:63,71+` | 未授权用户得到 403，回归用例覆盖 |
| 7 | 撤销 `scripts/restart_backend.py` 的 `--host 0.0.0.0` 默认值 | `scripts/restart_backend.py:64-69` | 脚本默认绑回环；`netstat` 复核 |
| 8 | 限流键不再信任 XFF（显式配置可信代理，或未登录时用连接 IP） | `fastapi_app/main.py:256-265`、`fastapi_app/core/prod_runner.py:268` | 伪造 XFF 不改变限流计数 |
| 9 | **建"执行状态"台账**：把 OPT-01..22 的 已完成/进行中/关闭或降级/未做/不可核验 落到 `docs/`，此后每次方案变更同步 | 新建 `docs/optimization-status-2026-10-01.md`（与 `docs/optimization-plan-2026-10-01-round2.md §0.1` 落点一致；本报告 §8.4 即初版内容） | 台账与仓库实际一致（**这是本轮审计暴露的最大管理洞**） |

### 批二 · 2–6 周

| 序 | 动作 | 依据 |
|---|---|---|
| 1 | 迁移命名规范（`YYYYMMDD_<需求号>_<动词>`，只约束新增）+ runbook/PR 模板"升级人工核对项" | §3.3 #1 |
| 2 | 通用幂等层：抽 `X-Idempotency-Key` 为可复用 dependency，明确 TTL 与"失败不缓存"，补同键并发用例 | §3.3 #2 |
| 3 | 索引收口：33 个真缺失 + 31 项 FK 前导索引，全部 `CREATE INDEX CONCURRENTLY`；同时**决策库内 4 个未声明列**的去留，避免 autogenerate 产出破坏性 DDL | §4.1 P0-A4、§4.5 P1-1 |
| 4 | mypy 覆盖扩容：先把 **21 个零错未纳入模块**并入（零成本），再按模块推进；同步修正 `mypy.ini` 已过时的注释（现称 156 文件/74 有错/400 error） | §1.2 错位二 |
| 5 | 前端通用能力收编：`UiFilterBar` 替换 12 处手写 `keyword`；`useEnhancedList` 从 1 个消费方推广；删 `useEventDelegation`/`useVirtualScrollList` 或补消费方；catalog 三份死条目删除 | §4.5 P1-5/P1-7 |
| 6 | 统一错误信封 + 让业务码能到前端（`AppError` 不再无条件降级为 `HTTPException`） | §4.5 P1-8 |
| 7 | 前端补 e2e 前提：先删/修 playwright 死依赖（`ci-cd.yml:218-224`），再决定是否补 `playwright.config` + spec | §3.4 #7 |
| 8 | 连接池参数接线（消除 4 个死配置）+ 补 `pool_recycle` | §4.5 P1-3 |
| 9 | `COVERAGE_MIN` 棘轮化；提交信息规范 + 文档引用检查两个 job | §3.3 #5 |
| 10 | 恢复演练制度化（季度）+ 演练工件落 `recovery_tests/`（当前最新停在 2026-08-23） | §4.2 P0-B1 |

### 批三 · 6–12 周

| 序 | 动作 | 依据 |
|---|---|---|
| 1 | 扩展点清单 + 覆盖层规范（文档先行，再定目录边界） | §3.3 #3 |
| 2 | 记录级权限最小切片（客户、订单 2~3 类实体），查询层统一注入归属过滤 | §3.3 #4 |
| 3 | 关系 `lazy` 显式化 + 34 处 N+1 批量化（需先补 t3 的调用点清单） | §4.5 P1-2 |
| 4 | 暴露面收敛：PostgreSQL `listen_addresses` 收回环/白名单、逐端口评估 21/3389/445/7863；NSSM 服务改专用账户 | §4.4 |
| 5 | 可观测性落地：告警通道开一条（现 `.env:127-128` 双 false）、`/metrics` 真 scrape、慢查询阈值接中间件 | `05:R` 清单 |
| 6 | 公司/本位币收敛为配置项；多公司与多币种**仍不引入** | §3.2 |
| 7 | 依赖锁定与前端 `dist` 清理；字段级 API 对齐工具 | §4.6 |

---

## 6. 证据边界与不确定项

**本轮审计的硬边界（必须与结论一起阅读）**：

1. **全程只读静态审计**——未改任何代码/配置/数据库，未重启服务，未连生产库做写操作。
2. **未跑测试套件**（`pytest` 未执行；分析基于 `--collect-only` 的静态收集与文件计数）。
3. **未压测**——所有性能类表述（如"缺索引=慢查询""64 连接逼近 100 上限"）是**结构性推断**，不是实测数字。
4. **未构建前端**（无 `npm run build` / `npm run type-check` 实跑）。
5. **未做空库重放迁移**——`alembic upgrade head` 未在空库上验证；`migrations/env.py:43-49` 每次 alembic 命令都会对 `alembic_version` 发 CREATE/ALTER DDL，本身违反只读约束。
6. **未做恢复演练**——恢复路径只有静态阅读（也因此才把 P0-B1 定为 P0）。
7. **`idx_scan` 类索引使用统计不可靠**：自上次 `pg_stat_reset` 起算，且生产数据量极小（多数表 0–30 行），索引收益只能**按结构判断**，不能按命中率判断。
8. **`web_search` 本会话不可用**（HTTP 401）——外部结论**只**来自官方文档/官方源码仓原文抓取，逐条附 URL，原始块存 `docs/audit-round2/06-oss-erp-raw-capture.txt`；**无搜索引擎交叉验证**。
9. **外部事实本轮未复抓**——ERPNext/Frappe、Odoo、Tryton、Dolibarr、iDempiere 的所有结论均转引自 `06`，写作会话未重新 `web_fetch`。

**明确标注为"未验证"的项**：

| 项 | 状态 |
|---|---|
| `deps.py:195-199` 缓存短路对"登出后仍放行"的**实际窗口长度** | **未验证**（未跑鉴权时序测试） |
| P0-A3 时钟混写的**存量数据修复方案**与影响行数 | **未验证**（需连库统计，本轮未连库） |
| 33 个缺失索引的**逐条 DDL 清单** | t3 缺口，**未验证**（只有摘要举例 3 条） |
| 34 处 N+1 的**具体调用点** | t3 缺口，**未验证** |
| 连接池 4 个死配置的**具体配置键位置** | t3 缺口，**未验证** |
| 20 个 NOT NULL 时间列的**逐表清单**与软删除三套语义 | t3 缺口，**未验证** |
| Tryton / iDempiere 的**当前版本号与节奏** | `06:§5` 标注不确定（GitHub 镜像 tag 滞后） |
| Odoo **最新大版本号** | `06:§5` 不声称 |
| iDempiere **REST API 正式形态** | `06:§5` 标注不确定（官方 wiki 相关页 404） |
| 五家开源 ERP 的**覆盖率阈值** | `06:§5` 标注不确定 |
| P1-11 前端 43 依赖"全部 `^`" | 转引 `02`，**本轮未逐条复核** |
| 路由数 385（02 口径）/ 382（05 口径） | 转引各报告口径，**本轮未重算**（只复核了 pytest 文件数 148/163 与 110/161 四数同时成立） |

---

## 7. 对上一轮结论的两处修正

### 修正 1 · **两棵测试树不是"重复测试"**

上一轮的印象是"两个测试目录 = 重复建设"。**实测推翻**：

| 证据 | 数值 |
|---|---|
| `pytest.ini:3` | `testpaths = tests fastapi_app/tests`（**同一份配置里并列**） |
| 静态文件数（本轮实测） | `tests/` ：全部 `.py` **148**、`test_*.py` **110**、根级 `tests/*.py` 101；`fastapi_app/tests/` ：全部 `.py` **163**、`test_*.py` **161** |
| pytest 收集（`--collect-only`） | **3689** 个用例（tests/ 1465 + fastapi_app/tests 2223） |
| 同名 basename 交集 | 13 个（其中 11 对 `test_*` **md5 全部 DIFF**） |
| **完全相同的「相对路径 + 用例名」节点** | **仅 1 个** ⇒ 逐节点重复率 ≈ 1/3688 ≈ **0.03%** |
| 真正的重复负担 | 体量与职责都不同：`tests/conftest.py` **571 行** vs `fastapi_app/tests/conftest.py` **232 行**（另有 `tests/e2e/conftest.py` 54、`tests/e2e_api/conftest.py` 350） |

**修正后的结论**：双树是**同名不同实现的语义重叠风险**，不是机械复制。要做的是"**按职责给树命名**（如 `tests/` = 端到端与契约、`fastapi_app/tests/` = 单元与服务级）并治理同名"，不是删树。**根因补充**：`ci-cd.yml:34-37` 注释记载 `tests/conftest.py` 会用 `{DB_NAME}_test` 派生测试库（`DB_NAME=erp_test` → `erp_test_test`），CI 必须显式给 `TEST_DATABASE_URL` 才能绕开——**两棵树的 fixture 派生逻辑本来就不一样**。

### 修正 2 · **`ProductionEntryDialog.vue` 是薄壳，不是拆分对象**

上一轮把 `ProductionEntryDialog.vue`（21,691 B）列为体积拆分候选。**实测推翻**：该文件 **367 行，其中 `<script>` 只有 72 行、0 个 `ref`、0 个函数**——逻辑全在 `useProductionEntry.ts`（564 行）里，**它已经是薄壳**。

**修正后的结论**：前端拆分预算应投向 `<script>` 真实体量，而不是文件总行数——**真正该动的是** `VirtualList.vue`（script 258 行）、`ProductionView.vue`（229）、`DashboardChartsSection.vue`（221）、`UiAutocomplete.vue`（216）、`UiDataTable.vue`（212），以及超 400 行的 `.ts`：`useSummaryModal.ts`（1084 行 / 50,178 B）、`types/index.ts`（794）、`useBeileOrders.ts`（684）、`useProductionEntry.ts`（564）。**这也直接支撑错位二**：门禁 `max_vue_component_length=400` 度量的是文件行数（含 CSS），与"逻辑复杂度"不同向。

---

## 8. 素材缺口与信度

> 用户要求"每条结论带证据"。下面是**证据本身的可信度**——不做这一步，读者会把残缺素材当成完整证据。

### 8.1 六份素材的完整性实测（t1 归档者复核 + 本报告采用）

| 报告 | 状态 | 残缺范围 | 因此**降级为「待复核」**的结论 |
|---|---|---|---|
| 01 后端 | **完整** | — | — |
| 02 前端 | **不完整（中）** | 恢复件在 ⑤ 节「- 类型安全实测：src（排除 test）」处**中途截断**，缺 ⑥/⑦ 与建议清单 | 前端"建议清单/演进路线"类结论；类型安全章节后半 |
| 03 数据层 | **不完整（高）** | t3 完整 output **随团队状态目录被删而永久丢失**；现存 = 2,071 B 片段 + 4,777 B 收尾摘要 | ① 31 项"表.列 → 引用｜现状｜建议 DDL"**逐条 DDL**；② 34 处 N+1 调用点；③ 连接池 4 个死配置位置；④ 20 个时间列与软删除三套语义逐表清单；⑤ 七问完整证据链与全部可复现命令 |
| 04 工程质量 | **不完整（高）** | 恢复件首行是 `# TASK AS OF THIS BLOCK (history)`——**它是折叠压缩块，不是 t4 原始报告** | **禁止**把 04 号当 OPT 逐项状态的证据源，**禁止**引用其行号支撑 OPT 结论；缺失 OPT-01..22 状态表、工程健康度总评、`scripts/` 与 `fastapi_app` 重叠可清理项、docs 过期/重复判定、quality_gate 收紧项 |
| 05 运维安全 | **完整** | — | — |
| 06 开源对比 | **完整** | — | 外部事实未在写作会话复抓（见 §6.9） |

**引用纪律（本报告已遵守）**：引用 02/03/04 的结论时，**同时**写明"残缺、需重跑补齐"；本报告 §4 的每条 `文件:行` 都是本轮在 HEAD=546401ec 上**打开文件确认**的，不依赖 03/04 的行号。

### 8.2 重跑动作（补齐缺口需要做什么）

| 目标 | 重跑动作 | 注意 |
|---|---|---|
| 补 03 数据层 | 只读连库（`SET default_transaction_read_only = on`），重出七问 + 逐条 DDL 清单 + N+1 调用点 + 池配置位置 | **`migrations/env.py:43-49` 每次 alembic 命令都会对 `alembic_version` 发 CREATE/ALTER DDL**，会违反只读约束——需先处理或在受控环境跑 |
| 补 04 工程质量 | 重跑 t4 的静态统计（ruff / mypy / pytest collect / docs 盘点）与 OPT 逐项核验 | 本次可用队长给定的 t4 原始运行结论替代（见 §8.4），但**不能**替代"工程健康度总评"这类需要判断的部分 |
| 补 02 前端 | 重出被截断的 ⑥/⑦ 节与建议清单 | 前端其余结论（组件体积、composable 消费方、vue-query 采用率）已在本轮抽检复核 |

### 8.3 口径与基线提示（不合成、不抹平）

- **基线漂移**：六份报告取证于 `aac4c43f`（2026-10-01 14:52:03）；归档与本报告写作于 `546401ec`（15:10:43），中间**多 1 个提交**：`chore(types): mypy 覆盖 106→110`，并**删除 `fastapi_app/services/staging_utils.py` 死代码**。⇒ **涉及该文件与 `mypy.ini` 的行号可能漂移**；本报告 §9 给出可复现命令，引用前请重新核对。
- **路由数 373 / 385 / 382**（01 / 02 / 05）与**测试文件 148、163 vs 110、161**（04 / 06）是**口径差异，不是错误**：04 数目录内全部 `.py`、06 只数 `test_*.py`；本轮实测**四数同时成立**。
- **归档者独立复核结论**（t1 实测，本轮沿用）：抽查行号全部命中（`approval.py:21-22/56/61/128/130`、`database.py:203/229/231/333/352/364`、`exceptions.py:74/203-214`、`customer_sampling.py:63/66`、`deps.py:195-199/363/383`、`token.py:57-58`、`health.py:200-214`、`main.py:256-271`、`backup/_deps.py:99`、`catalog.ts:18/21/30/83/89/95/102`、`patternRoom.ts:11-12/20/22/24/26`、`useEnhancedList.ts:13` + `ProductTable.vue:60/90`、`pytest.ini:3`、`pyproject.toml:15/18/25`、`order.py:24/335/342/374`、`restore_drill.py:35/42`）；`tenant_id/company_id/multi_company` 与 `\bcurrency\b` 均 0 命中——**本报告 §4 与 §3.2 已把其中绝大部分再核一遍**（见 §9）。

### 8.4 OPT-01..22 执行状态（**以队长给定的 t4 原始运行结论为准**，与 04 号缺口无关）

| 状态 | 项 | 备注 |
|---|---|---|
| **已完成 9** | OPT-01 / 03 / 04 / 06 / 07 / 10 / 11 / 12 / 14 | OPT-11 本轮再证：`fastapi_app/api/v1/endpoints/order.py:24/:334-335/:342/:374`（`db_transaction + error_map`） |
| **进行中 4** | OPT-02（6 条中已修 5 条）、OPT-08（**只建了 `.venv`**，未改 NSSM，`erp-prod`/`erp-arq` 仍指向全局 `Python313\python.EXE`）、OPT-09（试点 + 推广①②）、OPT-13（第 1 批，随 `546401ec` 把 mypy 覆盖 106→110） | OPT-09 本轮实测：`useApiMutation` 30 处命中（定义 `frontend-vite/src/composables/useApiMutation.ts:23`），**已过时于"仅 4 处"的旧度量** |
| **关闭或降级 3** | OPT-15（前提不成立）、OPT-16（降为调查 16a）、OPT-20（大半不成立） | OPT-15 本轮佐证：`ensureEcharts`/`preloadEcharts` 13 处命中，动态 import 已存在（`frontend-vite/src/utils/echartsPreload.ts`）；OPT-20 佐证：`fastapi_app/api/ws.py:33-41`（票据常量与内存字典）、`:61-76`（同时写 Redis 且 miss 回退） |
| **未做 5** | OPT-17 / 18 / 19 / 21 / 22 | OPT-22 本轮再证：`scripts/restore_drill.py:35-36`（glob 选不到 `.enc`）；OPT-21 佐证：`requirements/base.txt:7` `fastapi==0.137.1`；OPT-17/18 佐证：`config/nginx-windows.conf` 中 `ssl` 与 `limit_req` **0 命中** |
| **不可核验 1** | OPT-05（工件在仓库外） | — |

**一条判据**：`docs/optimization-plan-audit-2026-10-01.md` 只判"方案项描述是否属实 / 方向是否可行"，**从不判"是否已执行"**。因此"14 属实 / 4 需修正方向 / 3 BLOCKER"与上面的执行状态是**两个正交维度**，不可互相替代——这正是错位三的具体形态。

---

## 9. 可复现命令与核验清单

> 全部在 `D:\erp_system`、PowerShell 下执行；本报告 §3.2 / §7 的实测值均由这些命令（或等价的只读检索）产出。

```powershell
# 1) 单 head 实证（外部依赖 alembic，本轮未执行；见 06:§0）
python -B -m alembic -c migrations/alembic.ini heads
#   → pg_standalone_060_fix_updated_at_varchar_columns (pg_standalone) (head)

# 2) 多公司/多租户：全仓 0 命中（本轮实测 0）
Select-String -Path fastapi_app\**\*.py -Pattern 'company_id|company_code|multi_company|tenant_id'

# 3) 单币种：词边界 0 命中（本轮实测 0；此前 15 处是 "concurrency" 误匹配）
Select-String -Path fastapi_app\schemas\*.py,fastapi_app\shared_models\*.py,migrations\versions\*.py -Pattern '\bcurrency\b'

# 4) 无插件入口（本轮实测 0）
Select-String -Path pyproject.toml -Pattern 'entry_point|plugin'

# 5) 测试文件双口径（本轮实测：148/110 与 163/161 同时成立）
(Get-ChildItem tests -Recurse -Filter *.py).Count
(Get-ChildItem tests -Recurse -Filter test_*.py).Count
(Get-ChildItem fastapi_app\tests -Recurse -Filter *.py).Count
(Get-ChildItem fastapi_app\tests -Recurse -Filter test_*.py).Count

# 6) 用例收集数（3689；--collect-only 不执行测试）
python -m pytest --collect-only -q
```

**本报告逐条实测的 `文件:行` 核验清单**（均为 HEAD=546401ec 上打开文件确认）：

| 主题 | 已确认的 `文件:行` |
|---|---|
| 事务静默 | `fastapi_app/core/database.py:203`、`:226-227`、`:229`、`:230-233`；`fastapi_app/core/database.py:333`（只读依赖）、`:352`、`:363-365` |
| 异常信封 | `fastapi_app/core/exceptions.py:18`、`:74`、`:203-214`；`fastapi_app/main.py:302`、`:313`、`:332-341` |
| 时钟混写 | `fastapi_app/shared_models/approval.py:21-22`、`:56`、`:61`、`:128`、`:130` |
| 越权读 | `fastapi_app/api/v1/endpoints/customer_sampling.py:4`、`:63`、`:66`、`:71`、`:121-126` |
| 鉴权链 | `fastapi_app/core/deps.py:71`、`:195-199`、`:248-254`、`:279`、`:363`、`:383`；`fastapi_app/core/auth/token.py:55-59` |
| 监控端点 | `fastapi_app/core/health.py:200`、`:206`、`:209-211`、`:212-213` |
| 限流 | `fastapi_app/main.py:256-265`、`:271`；`fastapi_app/core/prod_runner.py:268` |
| 备份降级 | `fastapi_app/api/v1/endpoints/backup/_deps.py:99`、`:161-169` |
| 门禁阈值 | `pytest.ini:3`；`pyproject.toml:15`、`:18`、`:25`；`scripts/quality_gate.py:189-198`；`.github/workflows/ci-cd.yml:39`、`:63-66`、`:84-90`、`:140-142`、`:215-226` |
| 恢复演练 | `scripts/restore_drill.py:35-36`、`:42` |
| OPT 状态 | `fastapi_app/api/v1/endpoints/order.py:24`、`:334-335`、`:342`、`:374`；`fastapi_app/api/v1/endpoints/purchase_center/order_routes.py:113`、`:117-118`；`requirements/base.txt:7`；`config/nginx-windows.conf`（`ssl`/`limit_req` 0 命中）；`fastapi_app/api/ws.py:33-41`、`:61-76` |
| 前端 | `frontend-vite/src/stores/catalog.ts:18`、`:21`、`:83`、`:89`、`:95`、`:102`；`frontend-vite/src/stores/patternRoom.ts:11-12`、`:19`、`:22`、`:24`、`:26`、`:116-118`；`frontend-vite/src/composables/useEnhancedList.ts:13`；`frontend-vite/src/views/product/components/ProductTable.vue:60`、`:90`；`frontend-vite/src/composables/useApiMutation.ts:23` |
| 迁移 | `migrations/versions/pg_standalone_054_sync_schema_with_orm_metadata.py:20-28` |

---

## 附：本报告的自我限制

- 本报告**不引入任何素材之外的新量化结论**；确需推断处均标注"结构性推断"或"未验证"。
- 本报告不修改任何代码或既有文档，仅新增 `docs/audit-round2/00-synthesis.md`。
- 本报告与 `docs/audit-round2/README.md` 的关系：README 是**归档索引**（方法/基线/摘要表/引用矩阵/缺口表），本报告是**决策视图**（结论/优先级/路线图）。两者数字同源，如有冲突以六份原始报告为准。
