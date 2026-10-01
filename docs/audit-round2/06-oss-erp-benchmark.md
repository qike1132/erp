# 06 · 开源 ERP 架构对比与可借鉴模式（t6 完整报告）

> **本文件元信息**（由 docs-archivist 于归档时统一添加，正文未改）
>
- **审计轮次**：2026-10-01 第二轮全面审计（binfa-ERP / D:\erp_system）
- **基线**：aac4c43f59a4374e05cdc5aee6c4aaa8afc99026（2026-10-01 14:52:03，成员取证时的 HEAD）
- **归档 HEAD**：546401ec6cfeb0bb14664d21ff5d06a618a4e060（2026-10-01 15:10:43，chore(types): mypy 覆盖 106→110（OPT-13 第一批），顺带删 staging_utils 死代码）
- **来源**：成员报告 `t6-oss-erp.report.md（24,652 B）`（恢复件 24,652 B / 16,446 字符）
- **恢复方式**：captain 从 t6 成员会话转录恢复原报告全文，本文件逐字归档（未改排版，原文不含需规范化的分节符）。
- **完整性**：记为「完整」（128 行，6 个分节 + 一句话结论）。原始抓取块另存为同目录 `06-oss-erp-raw-capture.txt`（118,267 B，web_fetch 去转义前的原文），供外部证据复核；正文所有外部结论均带可点击 URL。
- **只读声明**：全程只读静态审计：不改代码/配置/数据库，不重启服务、不装依赖、不发起任何攻击性请求；临时脚本仅写 %TEMP%\erp_audit_v2\。本文件是审计产物的**归档副本**，正文结论与 文件:行 证据保持成员原文。
- **归档时间**：2026-10-01（第二轮审计当日）

【硬性提醒】所有 文件:行 均相对基线 aac4c43f 取证；归档时仓库 HEAD = 546401ec6cfeb0bb14664d21ff5d06a618a4e060（2026-10-01 15:10:43）已在其上新增 1 个提交（mypy 覆盖 106→110、顺带删 staging_utils 死代码），行号可能已漂移，引用前请重新核对。

**归档者独立复核（本轮实测，非成员转述）**：抽查 t6 内部事实：全仓 `tenant_id|company_id|company_code|multi_company` 命中 **0**（本轮 grep 实测，与 §1④ 一致）；`fastapi_app/shared_models/` 下 `currency` 命中 **0**（§0 强调此前 15 处命中全是 concurrency 误匹配，本轮实测确认）。**未复核**：所有外部项目（ERPNext/Frappe、Odoo、Tryton、Dolibarr、iDempiere）结论与 URL 均为 web_fetch 抓取，本轮未复抓。

---
## t6 开源 ERP 架构对比与可借鉴模式（第二轮审计 · 只读）

## 0. 方法与可复现性
- 外部证据：全部 via 官方文档/官方源码仓原文抓取（web_fetch）。本会话 `web_search` 不可用（DeepSeek search endpoint 返回 HTTP 401），因此未用搜索引擎交叉验证，只用可点击原文 URL；每条外部结论后附 URL。
- 内部证据：全程只读。解析用 `ast`（`python -B` + `PYTHONDONTWRITEBYTECODE=1`，不落 __pycache__）；临时脚本写 `%TEMP%\erp_audit_v2\`。未改动 D:\erp_system 任何文件、未连库、未重启服务。
- 可复现命令（PowerShell，工作目录 D:\erp_system）：
  1) `python -B -m alembic -c migrations/alembic.ini heads` → `pg_standalone_060_fix_updated_at_varchar_columns (pg_standalone) (head)`（单 head 实证）
  2) `Select-String -Path fastapi_app\**\*.py -Pattern 'company_id|company_code|multi_company|tenant_id'` → **0 命中**
  3) `Select-String -Path fastapi_app\schemas\*.py,fastapi_app\shared_models\*.py,migrations\versions\*.py -Pattern '\bcurrency\b'` → **0 命中**（此前 15 处命中全是 "concurrency" 误匹配）
  4) `Select-String -Path pyproject.toml -Pattern 'entry_point|plugin'` → **0 命中**
  5) 计数：endpoints 32 模块 / services 13 包 369 文件 / src 288 个 .vue（components 目录 194）/ docs 221 md / 测试 110(tests)+161(fastapi_app/tests)
- 方法论自查：我 ast 初版统计迁移图得 3 个 head，原因是漏处理带注解的 `down_revision: str | None = '...'`（AnnAssign）——与项目"正则产出 15 个 head"同类伪影。补齐后与 `alembic heads` 及 `docs/adr/2026-10-01-migration-roots-are-cosmetic.md:9-16` 一致。

---

## 1. 七维对比矩阵（ERPNext/Frappe、Odoo、Tryton、Dolibarr、iDempiere）

### ① 模块划分与扩展/插件机制
- **Frappe/ERPNext**：app = Python 包，目录 `apps/<app>/<app>/{hooks.py, patches.txt, modules.txt, public/, www/, templates/}`，`bench new-app` 生成骨架；扩展靠 `hooks.py`，`frappe.get_hooks()` 聚合**所有已安装 app** 的同名 hook，冲突为 "last writer wins"（最后安装的 app 优先，可在 Installed Applications 页调整解析顺序）——即"不改核心文件即可覆盖/扩展"。URL: https://docs.frappe.io/framework/user/en/basics/apps ， https://docs.frappe.io/framework/user/en/python-api/hooks
- **Odoo**：模块 = 带 `__manifest__.py` 的 Python 包（name/version/depends/license/data/demo），`depends` 形成模块图；扩展靠 Python 类继承 + 视图 XML 继承（XPath），不改核心。URL: https://raw.githubusercontent.com/odoo/documentation/17.0/content/developer/reference/backend/module.rst
- **Tryton**：模块 = `trytond/modules/<mod>` 目录，含 `__init__.py` + `tryton.cfg`（version/depends/extras_depend/xml/include_dirs/test_include_dirs）；核心只带 `ir`、`res`，其余全是可插拔模块；视图扩展用 XPath（`View.inherit` + `<xpath expr position>`）。URL: https://docs.tryton.org/projects/server/en/latest/topics/modules/index.html ， https://docs.tryton.org/projects/server/en/latest/topics/views/extension.html
- **Dolibarr**：模块有描述符 `class modXxx extends DolibarrModules`（`$this->rights[$r][0..5]` 定义权限、`$this->module_parts` 声明钩子/模板/子模块）；独立的 **Hooks 系统**官方定位为"无需修改核心文件即可向核心插入自定义代码，从而简化升级"，与 triggers（业务事件）区分。URL: https://wiki.dolibarr.org/index.php/Module_development ， https://wiki.dolibarr.org/index.php?title=Hooks_system
- **iDempiere**：OSGi/Equinox bundle 化，核心 bundle `org.adempiere.base` / `org.adempiere.server`（+Jetty），插件靠 Fragment / Buddy Classloading 侵入类加载路径。URL: https://wiki.idempiere.org/en/OSGi

### ② 数据层与迁移策略
- **Frappe/ERPNext**：**元数据驱动 + 自动 DDL**。`bench migrate` 先跑 before_migrate hook → patches → 同步 schema/后台任务/fixtures/桌面图标/翻译/搜索索引 → after_migrate；DocType 以 **MD5 校验和**比对决定是否 reload（v13 前用 mtime，官方称 error-prone 故改 hash）；删/改字段时旧列**不删**（避免不可逆）。URL: https://docs.frappe.io/framework/user/en/database-migrations
- **Odoo**：显式**版本目录化**升级脚本 `$module/migrations|upgrades/$version/{pre,post,end}-*.py`，入口 `migrate(cr, version)`，仅在模块被更新时执行，且 `$version` 必须高于已安装版本。URL: https://raw.githubusercontent.com/odoo/documentation/17.0/content/developer/reference/upgrades/upgrade_scripts.rst
- **Tryton**：schema 由模型定义驱动，**数据迁移是人工 SQL 清单**：官方 Migration 页逐 series 列 Before/After 必执行 SQL，并规定"不能跳过超过 2 个以 .0 结尾的 series"。URL: https://docs.tryton.org/en/latest/migration.html
- **Dolibarr**：模块自带 `.sql`，模块激活/升级时执行；内核无多公司/多币种概念。URL: https://wiki.dolibarr.org/index.php/Module_development
- **iDempiere**：**显式版本化 SQL 迁移**，按 series 目录 + 时间戳 + issue 编号命名：`migration/iD14/{oracle,postgresql}/YYYYMMDDHHMM_IDEMPIERE-<n>.sql`（iD14/postgresql 下 34 个），另有 `processes_post_migration`、`zip_2pack`。URL: https://api.github.com/repos/idempiere/idempiere/contents/migration/iD14/postgresql
- **横切结构（多公司/多币种）**：Odoo 为**单库多公司**（共享部分数据、隔离部分实体，授权用户可同时选多公司做聚合报表）URL: https://raw.githubusercontent.com/odoo/documentation/17.0/content/applications/general/companies/multi_company.rst ；ERPNext 以 Company DocType + 逐 DocType 声明 company-dependent；Tryton 用 Company 基础模块 + 模型/字段归属；Dolibarr 内核单公司。

### ③ API 设计
- **Frappe/ERPNext**：**REST 自动生成**，`/api/method/<dotted.path>` + `/api/resource/<DocType>`；token（`api_key:api_secret`）或 cookie 认证，按用户角色校验权限；前缀**不带版本号**。URL: https://docs.frappe.io/framework/user/en/api/rest
- **Odoo**：**XML-RPC/JSON-RPC**，端点 `/xmlrpc/2/common`、`/xmlrpc/2/object`（`execute(db, uid, pwd, model, method, args)`），模型-方法式 RPC 而非资源式 REST；支持 API Key；路径不版本化。URL: https://raw.githubusercontent.com/odoo/documentation/17.0/content/developer/reference/external_api.rst ， https://raw.githubusercontent.com/odoo/documentation/17.0/content/developer/howtos/web_services.rst
- **Tryton**：**JSON-RPC 1.0 + XML-RPC**，URL `<database>/rpc/`，`common.db.login`/`logout`，Basic 或 session 认证。URL: https://docs.tryton.org/projects/server/en/latest/topics/rpc.html
- **Dolibarr**：REST，路径 `/api/index.php/<resource>`，需激活 API REST 模块，附 explorer 与 `sqlfilters` 过滤参数——**把查询能力直接下放给调用方**，是明显的安全/性能权衡点。URL: https://wiki.dolibarr.org/index.php?title=Module_Web_Services_API_REST_(developer)
- **iDempiere**：有 REST 插件路线（社区插件形态），核心仍为 Java 服务层；REST 细节**不确定**（见 §5）。URL: https://idempiere.org/

### ④ 权限与多租户/多公司
- **Frappe/ERPNext**：User–Role–**DocType Permission**–Permission Level + **User Permission**（记录级）+ Role Permission Manager（UI 配置），另有登录限流与 OAuth。URL: https://docs.frappe.io/framework/user/en/basics/users-and-permissions
- **Odoo**：`res.groups` + `ir.model.access`（模型级 ACL，**累加式**：多组取并集）+ 记录规则 ir.rule；无组即无权限。URL: https://raw.githubusercontent.com/odoo/documentation/17.0/content/developer/reference/backend/security.rst
- **Tryton**：**5 层**——Model / Action / Field / Button / Record Rule，均基于用户组，任一层违反即报错；受 `Transaction.context['_check_access']` 与 root 影响。URL: https://docs.tryton.org/projects/server/en/latest/topics/access_rights.html
- **Dolibarr**：权限以"权限 ID + action/subaction"在模块描述符声明（`$this->rights`），粒度偏功能点，无内核级记录规则。URL: https://wiki.dolibarr.org/index.php/Module_development
- **多租户**：五家**均非多租户**——Odoo/Frappe 是"一个部署=一个库=多个公司"；Tryton 单库单公司集合；Dolibarr 内核单公司；iDempiere 多客户端靠多实例。结论：**没有一家把 tenant_id 铺进业务表**。

### ⑤ 前端技术栈与组件化
- **Odoo**：自研 **OWL**（QWeb 模板 + 类 Vue/React 声明式组件；Owl 由独立仓库 odoo/owl 维护，v14 起各版本共用同一 Owl 版本）。URL: https://raw.githubusercontent.com/odoo/documentation/17.0/content/developer/reference/frontend/owl_components.rst
- **Frappe/ERPNext**：Desk 为服务端 Jinja + 浏览器端 `frappe.ui`（元数据驱动表单/列表自动生成）；新应用走独立 Vue3 UI 库 https://github.com/frappe/frappe-ui —— 即"框架视图"与"应用视图"分层。
- **Tryton**：桌面客户端（GTK）+ Web 客户端 + REST 客户端库，**视图是数据**（服务端 `View` 记录，客户端渲染），与 Odoo 同源思路。URL: https://docs.tryton.org/
- **Dolibarr**：PHP 服务端渲染 + jQuery/原生 JS 页面 + 可被模块覆盖的 `.tpl`。URL: https://wiki.dolibarr.org/index.php/Module_development
- **iDempiere**：**ZK（ZKoss）** 服务端组件式 AJAX；官网自述技术栈 "Java, ZK, OSGi, Oracle, PostgreSQL, Maven"。URL: https://idempiere.org/

### ⑥ 测试与发布流程（CI 证据取自各仓库 `.github/workflows` 目录清单）
- **Frappe/ERPNext**：frappe 22 个 workflow（server-tests/ui-tests/linters/initiate_release/create-release/backport_reminder/vouch-check-pr/stale）；erpnext 25 个（server-tests-mariadb、server-tests-postgres、docs-checker、semantic-commits、patch、linters）。**双分支并行发版**：2026-09-30 同日发 ERPNext v16.37.0 与 v15.121.6、frappe v16.36.1 与 v15.121.3。URL: https://api.github.com/repos/frappe/erpnext/releases ， https://api.github.com/repos/frappe/frappe/releases
- **Odoo**：**不用 GitHub Actions**（`odoo/odoo` 的 `.github/workflows` 返回 Not Found），用自建 **Runbot**（抓取时页面显示 Testing: 1375/1888）；测试三类：Python 单测 + JS 单测 + **Tours**（端到端）；每个大版本支持 3 年，On-premise 可不限期停留，Odoo Online 小版本约每 2 个月。URL: https://runbot.odoo.com/ ， https://raw.githubusercontent.com/odoo/documentation/17.0/content/developer/reference/backend/testing.rst ， https://raw.githubusercontent.com/odoo/documentation/17.0/content/administration/upgrade.rst
- **Tryton**：文档有 Testing 章节，但仓库在自有基础设施（GitHub 镜像 tag 滞后，见 §5），无公开 CI 清单 → **CI 细节不确定**。URL: https://docs.tryton.org/projects/server/en/latest/topics/testing.html
- **Dolibarr**：22 个 workflow，含 phpstan/phan/pre-commit/ci-on-push/ci-on-cron-windows，另有 PR 描述、文件清单、配额检查与 stale 自动化。**长周期多分支**：最新 24.0.1(2026-09-07)、24.0.0(2026-08-20)，同时仍在给 23.0.4/22.0.5/18.0.10 发补丁；官网标注 "Last version 24.0.1"。URL: https://api.github.com/repos/Dolibarr/dolibarr/releases ， https://www.dolibarr.org/
- **iDempiere**：`.github/workflows` 仅 `sonarqube.yml` → CI 轻，质量主要靠 SonarQube + 社区评审。URL: https://api.github.com/repos/idempiere/idempiere/contents/.github/workflows

### ⑦ 文档与社区治理
- **Frappe/ERPNext**：docs.frappe.io 按空间分层（Framework/ERPNext/Builder…），有 `docs-checker.yml` 守文档；论坛 https://discuss.frappe.io/ ；`vouch-check-pr.yml` 表明首次贡献者需"担保（vouch）"后才跑 CI。
- **Odoo**：官方文档仓与代码仓分离（`odoo/documentation`，按 series 分支 17.0/master），社区治理核心是 **OCA**：https://www.odoo-community.org/
- **Tryton**：**Tryton Foundation**（比利时私法基金会）持有商标与治理权：https://www.tryton.org/foundation
- **Dolibarr**：官网 + wiki（开发者文档主入口）+ 论坛 + Dolistore 插件市场：https://wiki.dolibarr.org/index.php/Developer_documentation
- **iDempiere**：社区驱动（Founders/Sponsors/Organizations/Contributors 分层），无单一商业实体：https://idempiere.org/community/

---

## 2. 映射分析：借鉴点 → 本项目现状（文件:行证据）→ 成本/风险 → 收益 → 优先级

| # | 借鉴点（来源） | 本项目现状（证据） | 落地成本/风险 | 预期收益 | 优先级 |
|---|---|---|---|---|---|
| 1 | 迁移文件携带"日期+需求号"语义（iDempiere `YYYYMMDDHHMM_IDEMPIERE-n.sql`） | 99 个迁移文件名混合两套体系（`pg_standalone_0xx_*` 与 `add_*_*`），无日期/无需求号；单 head 已实证；`docs/adr/2026-10-01-migration-roots-are-cosmetic.md:9-16` 明确**不改历史文件名** | 极低（只约束新增）；风险=零 | 事故回溯可按时间线直接定位"哪次上线改了什么表" | **P0** |
| 2 | 升级前/后人工步骤清单制度化（Tryton Migration 页逐 series 列 Before/After SQL） | 有 `docs/runbooks` 与 ADR，但没有"本次 Alembic 升级必须人工核对/执行什么"的强制清单；CI 只跑 `alembic upgrade head`+`alembic check`（`.github/workflows/ci-cd.yml:63-66`） | 低（文档+PR 模板字段）；风险=清单形式化 | 本机既是生产又是运维、无测试环境，人工清单是**唯一**升级安全网 | **P0** |
| 3 | 幂等键作为通用能力 | `fastapi_app/api/v1/endpoints/purchase_center/order_routes.py:113` 收 `X-Idempotency-Key`（`:117` 10 分钟内同键复用结果，`:149` 透传）；其余写端点无统一幂等层（全仓 `idempot` 26 处/17 文件，近半是测试） | 中（抽 dependency/中间件 + Redis 键）；风险=键 TTL 与失败重试语义定义不清 | 防重复提交/重试重复入库——生产最贵的一类事故 | **P0** |
| 4 | 扩展点清单文档化（Frappe 有完整 List of available hooks） | 扩展点隐式：`fastapi_app/api/v1/router.py:5-38` 绝对导入 + 34 处 `include_router`（`:279-320`）；`pyproject.toml` 无 entry_points/plugin（0 命中）；无"允许定制的点"清单 | 低（一页文档）；风险=文档漂移 | 后续会话/新人不必重推"哪里能挂" | **P1** |
| 5 | 轻量"定制覆盖层"（Dolibarr hooks 原则：不改核心文件） | 客户特有逻辑直接进 `fastapi_app/services/`（最大服务 61KB `services/backup/orchestration/recovery_test_service.py`、`services/bom_service.py` 45KB），无 `custom/` 隔离层 | 高（覆盖语义+测试策略）；风险=过早抽象、双路径漂移 | 后续"仅此客户要"的需求不污染主干 | **P2** |
| 6 | 权限分层最小切片：**记录级**规则（Odoo `ir.rule`；Tryton 5 层含 Record Rule） | 现为权限名集合+层级树：`fastapi_app/core/deps.py:279` `require_permission(name)`，`:250` `joinedload(User.permissions).selectinload(Permission.children)`，`:71` TTL 5s 缓存；`fastapi_app/shared_models/permission.py`；审计中间件记录 required/held（`core/audit_middleware.py:187-213`） | 中（查询层注入过滤）；风险=过滤遗漏致越权或性能回退 | 客户/订单的"按归属可见"若靠端点手写判断，长期必漏 | **P1** |
| 7 | 前端"UI 库与应用分离"（frappe-ui 独立版本化 Vue3 库） | 已是 Vue 3.5.34 + TS + Vite 7 + PrimeVue 4.5.5 + Pinia 3 + TanStack Query；`src` 288 个 .vue（components 目录 194），api 27 文件、stores 4、composables 19 | 中高（抽包+版本管理）；风险=内网单前端收益有限 | 若 mobile 端与 Web 复用组件，可消两套实现 | **P2** |
| 8 | 发布/文档自动化（ERPNext `semantic-commits.yml`/`docs-checker.yml`/`patch.yml`） | 发布靠 `release.bat`+`CHANGELOG.md` 手工；CI 无提交信息规范校验、无文档链接检查；`docs/` 221 篇 .md（`docs/adr/` 3 篇） | 低（两个轻量 job）；风险=文档检查误报需白名单 | 221 篇文档的内部引用极易失效；提交规范可驱动 CHANGELOG 自动生成 | **P1** |
| 9 | 测试分层明确化（Odoo：Python 单测/JS 单测/Tours） | 测试面已宽（271 个 test_*.py；CI 跑 pytest 双根+vitest+vue-tsc，`ci-cd.yml:84-95,236-237`），但 e2e 被显式排除（`:87` `--ignore=tests/e2e`），playwright 是**已装未用**死依赖（`:218-224` 注释自陈） | 低（先清死依赖）；真做 e2e 则中 | 消除"看似有 e2e 实则没有"的错觉 | **P2** |
| 10 | 覆盖率**棘轮式**提升（本项目已有 `COVERAGE_MIN` 与就地判定） | `ci-cd.yml:39` `COVERAGE_MIN: "40"` + `:140-142` 就地判定；另有 `scripts/quality_gate.py` 棘轮（`:173-174`）与文件体积门禁（`:182-195`，`pyproject.toml:25` max_file_size=1600） | 极低（改一个常量）；风险=抬太快阻塞 PR | 覆盖率只升不降，与既有棘轮同心智 | **P1** |
| 11 | 应用/数据版本并行维护分支（Dolibarr 4 条、ERPNext 2 条、Odoo 3 年支持） | 单体内网、无外部调用方；`docs/adr/2026-09-30-api-versioning-and-health-probes.md:9` 已删 `/api/v2`，`:33-39` 仅留触发条件 | 高（分支+回移）；风险=明显为负 | 当前场景无 | **不抄** |
| 12 | 多公司/多币种内核化（Odoo 单库多公司） | **完全不存在**：`company_id/company_code/multi_company/tenant_id` 全仓 0 命中；`\bcurrency\b` 在 schemas/shared_models/migrations 0 命中 → 单公司+隐含本币 | 极高（污染 46 个模型文件与全部报表）；风险=过度设计 | 当前场景无 | **不抄**（建议留接缝） |
| 13 | 元数据驱动+自动 DDL（Frappe `bench migrate` 按 MD5 同步 schema、删列不删） | 本项目是对立选择：显式 Alembic、**单 head**、CI 强制 `alembic check`（`ci-cd.yml:66`），并有 ADR 固化"不修根/不 squash"（`docs/adr/2026-10-01-migration-roots-are-cosmetic.md:9-21`） | 极高；风险=生产单实例不可回滚且与 ADR 冲突 | 无 | **不抄** |
| 14 | RPC 式 API（Odoo XML-RPC 模型-方法；Tryton JSON-RPC） | 本项目 REST+OpenAPI（`config.py:295` `API_PREFIX="/api/v1"`，`main.py:393` 单点挂载），前端 TS 类型与 `npm run check:api` 对齐 | 极高（前后端全改）；风险=丢类型校验 | 无 | **不抄** |

---

## 3. 真能借鉴的 Top 5（按 收益/成本 比）

1. **迁移与升级的"可审计契约"**（借鉴 iDempiere 文件名语义 + Tryton 人工步骤清单）— 新增迁移命名规范 `YYYYMMDD_<需求号>_<动词>`（不动历史文件，符合既有 ADR）；runbook/PR 模板增"本次升级需人工核对项"；把 `alembic check`（`ci-cd.yml:63-66`）升格为文档化不变量。**P0**
2. **通用幂等层**（推广 `purchase_center/order_routes.py:113` 的既有做法）— 抽 `X-Idempotency-Key` 为可复用 dependency/装饰器（Redis 存键+结果摘要，明确 TTL 与"失败不缓存"语义），逐个写端点启用，补"同键并发"回归用例。**P0**
3. **扩展点清单 + 覆盖层规范（文档先行）**（借鉴 Frappe hooks 清单、Dolibarr hooks 原则）— 先产出可扩展点清单（`router.py:5-38` 挂载点、服务层接口、权限点、配置项）并写明"客户特有逻辑只允许落在 X 目录"。**P1**
4. **权限的记录级最小切片**（借鉴 Odoo `ir.rule` / Tryton Record Rule，只取一层）— 对最敏感的 2~3 类实体（客户、订单）定义声明式"归属过滤"，在查询层统一注入，禁止端点内手写可见性判断；保留 `require_permission`（`core/deps.py:279`）不动。**P1**
5. **发布/文档自动化两个轻量 job**（借鉴 ERPNext `semantic-commits.yml`/`docs-checker.yml`）— 提交信息规范校验（驱动 CHANGELOG 生成）+ 文档内部引用可达性检查（`docs/` 221 篇）；顺带把 `COVERAGE_MIN`（`ci-cd.yml:39`）改棘轮式（只升不降），与 `quality_gate`（`:173-174`）同构。**P1**

---

## 4. 明确不建议照抄（及原因）

1. **Odoo 单库多公司 + 多币种内核化** — `company_id/multi_company/tenant_id` 全仓 0 命中、`\bcurrency\b` 0 命中，是"单公司+本币"的有意简化；内网单公司场景下引入会污染 46 个模型与全部报表，且没有第二家公司存在。**但别躺平**：把"公司/本位币"收敛为配置项（`fastapi_app/core/config.py`）而非散落业务常量，未来改造成本可控。
2. **Frappe/ERPNext 元数据驱动 + 自动 schema 同步（MD5 比对、删列不删）** — 与既有 ADR（显式 Alembic + 单 head + `alembic check`）直接冲突；生产单实例上自动 DDL 不可回滚。
3. **Odoo XML-RPC / Tryton JSON-RPC 风格 API** — REST+OpenAPI+前端 TS 类型链路已成型，改 RPC 会让类型与文档收益全部作废。
4. **API 前缀版本化（`/api/v2`）** — `docs/adr/2026-09-30-api-versioning-and-health-probes.md:9-30` 已明确拒绝并删除 v2（理由：前端对 v2 请求数为 0、两套等价端点只会漂移）；照抄等于推翻生效决策，`:33-39` 已给出重新引入的触发条件。
5. **iDempiere 的 OSGi 插件体系 / Java+ZK 技术栈** — 体量与团队严重不匹配（本项目 1 个 Python/FastAPI+Vue 团队、Windows 内网、NSSM 托管）；OSGi 的类加载/包版本治理成本远超收益。
6. **Dolibarr/ERPNext/Odoo 的多分支并行维护与长支持周期** — 无外部调用方、无 SaaS 客户，维护多分支/backport 只把人切成碎片；Odoo "On-premise 可不限期停留"恰恰说明内网可常驻单版本，与本项目一致。
7. **Odoo Tours / Playwright 端到端全铺** — 本项目 e2e 已被 CI 显式排除（`ci-cd.yml:87`），playwright 已装未用（`:218-224`）；正确动作是**先删死依赖或补齐配置**，而非为对齐 Odoo 引入没人维护的 e2e。
8. **Tryton 的"人工 SQL 迁移"作为迁移机制本身** — 其前提是 schema 自动管理、只人工处理数据；本项目 Alembic 线性链确定性更强。可借鉴的只是它的**清单/文档形态**（Top5 #1），不是机制。

---

## 5. 不确定项（未核实即不当结论）

- **Tryton 当前 series 与发版节奏**：官方文档站最新章节为 8.2/8.0（`migration.html`），但 GitHub 镜像 `tryton/trytond` tag 仅到 6.6.1 → 判断镜像滞后，**具体当前版本号与节奏无法核实**。URL: https://docs.tryton.org/en/latest/migration.html ， https://api.github.com/repos/tryton/trytond/tags
- **iDempiere 当前发布版本**：GitHub tag 仅 v2.0/v1.0c（镜像滞后），官网 download 页未给版本号 → **不引用具体版本号**；仅确认迁移目录含 iD10~iD14。URL: https://idempiere.org/download/ ， https://api.github.com/repos/idempiere/idempiere/contents/migration
- **Odoo 最新大版本号**：仅验证 17.0 与 master 文档站存在（`/documentation/17.0/...`、`/master/`），**不声称最新版本是哪个**。
- **iDempiere REST API 正式形态**：wiki 的 `/en/REST_API`、`/en/Migration`、`/en/Plugin_Development` 均 404，站内搜索与 api.php 亦不可用 → 标注**不确定**。
- **各项目覆盖率硬性要求**：五家官方文档均未给出统一阈值（我未逐文件精读其 CI 配置）→ **不确定**，故 §2#10 只主张"棘轮式提升"，不对标任何具体数字。
- **Dolibarr 自动化测试覆盖范围**：仅验证 workflow 名单（phpstan/phan/pre-commit），未逐文件精读 → **不确定**。
- **web_search 不可用**：本会话 DeepSeek search endpoint HTTP 401，**没有**搜索引擎交叉验证；所有外部结论均来自上列官方 URL 原文。若要更广的第三方评测数据，需修复 search 配置后补做。

---

## 6. 一句话结论

本项目在**迁移纪律（单 head + `alembic check` + 文件体积/质量棘轮）、权限缓存与审计中间件、CI 三 job 分层的完整度**上已达到甚至超过多数开源 ERP 的工程水位（Dolibarr 才刚上 pre-commit，iDempiere 只有 SonarQube 一个 workflow）；真正值得抄的不是它们的"体系"，而是三条**流程级**做法——迁移文件的可审计命名 + 升级人工步骤清单（iDempiere/Tryton）、幂等键通用化（推广已有单点）、发布与文档的轻量自动化（ERPNext）。多公司/多币种、RPC API、OSGi 插件、多分支维护这四类"重体系"在内网单公司场景下是负收益，明确不抄。
