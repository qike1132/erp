# 04 · 工程健康度 / 测试双树 / 工具链审计（t4 残片 + 缺口声明）

> **本文件元信息**（由 docs-archivist 于归档时统一添加，正文未改）
>
- **审计轮次**：2026-10-01 第二轮全面审计（binfa-ERP / D:\erp_system）
- **基线**：aac4c43f59a4374e05cdc5aee6c4aaa8afc99026（2026-10-01 14:52:03，成员取证时的 HEAD）
- **归档 HEAD**：546401ec6cfeb0bb14664d21ff5d06a618a4e060（2026-10-01 15:10:43，chore(types): mypy 覆盖 106→110（OPT-13 第一批），顺带删 staging_utils 死代码）
- **来源**：成员报告 `t4-quality.report.md（27,082 B）`（恢复件 27,082 B / 20,278 字符）
- **恢复方式**：captain 从 t4 成员会话转录恢复；恢复件是压缩/折叠后的历史片段（首行 `# TASK AS OF THIS BLOCK (history)`），本文件逐字归档其内容，仅把成员自己的分节标题降一级并归入「成员任务上下文与通用约束」。
- **完整性**：**不完整（等级：高）** —— 记为「完整」但实测为折叠压缩块：缺 OPT-01..22 状态表与工程健康度总评，见下方「完整性缺口声明」。
- **只读声明**：全程只读静态审计：不改代码/配置/数据库，不重启服务、不装依赖、不发起任何攻击性请求；临时脚本仅写 %TEMP%\erp_audit_v2\。本文件是审计产物的**归档副本**，正文结论与 文件:行 证据保持成员原文。
- **归档时间**：2026-10-01（第二轮审计当日）

【硬性提醒】所有 文件:行 均相对基线 aac4c43f 取证；归档时仓库 HEAD = 546401ec6cfeb0bb14664d21ff5d06a618a4e060（2026-10-01 15:10:43）已在其上新增 1 个提交（mypy 覆盖 106→110、顺带删 staging_utils 死代码），行号可能已漂移，引用前请重新核对。

**归档者独立复核（本轮实测，非成员转述）**：抽查 t4 硬事实：`pytest.ini:3` `testpaths = tests fastapi_app/tests`（双树均在采集范围）、`pyproject.toml:15/18/25` `max_function_length = 80` / `max_vue_component_length = 400` / `max_file_size = 1600`（三项门禁阈值逐字命中）、`fastapi_app/services/base_search_service.py` 当前仅 :17 `from sqlalchemy.orm import Query, Session` 与 :89 `query: Query = db.query(model)` —— 归档 HEAD 已无 F821（恢复件中 `:88:16 F821` 是取证时点事实，该问题随后被修复）、`fastapi_app/api/v1/endpoints/order.py:24` 导入 db_transaction、`:335` delete_order、`:342` 事务模式 docstring、`:374` db_transaction(db, error_map=)（OPT-11 已修成立）、`scripts/restore_drill.py:35` newest_backup / `:42` async def main（OPT-22 未做成立）。**未复核**：ruff/mypy 的实际 error 计数与 OPT-01..22 逐项状态（恢复件缺表，无法逐项核）。

---
## 成员任务上下文与通用约束（原始会话片段，压缩格式）


### 任务
AgentTeams 自动派单 t4（成员 quality-analyst，attempt_id 511476f2-94d8-4de2-b459-afa3d109c92a，parent agent id session-b182657c-f02a-48ac-96de-7dc94a41dee7）。已于 t4 status=claimed→in_progress 各调用一次 agent_teams_update_task（均带 attempt_id）。完成时需 update_task(completed/failed) 并 send_message 给 captain，另需 send_message 给 parent agent id 发一份自包含结果。
团队目标：对 D:\erp_system（binfa-ERP）做第二轮全面代码架构审计 + 对比开源 ERP。
t4 具体范围/必答项：①测试双树收敛方案（同名文件清单、重复用例比例、唯一真源、合并步骤与风险）；②mypy/ruff 现状与棘轮分批纳入顺序；③scripts/ 与 fastapi_app 职责重叠与可清理项；④docs/ 文档膨胀（清单、过期/重复）；⑤关键：独立核验 docs/optimization-plan-2026-10-01.md 的 OPT-01..22 真实执行状态，必须自找代码证据，禁止照抄 docs/optimization-plan-audit-2026-10-01.md，并列出该审计报告中错误/过时条目。
产出格式：工程健康度评估 + OPT-01..22 状态表（每项含 状态 / 代码证据 文件:行 / 与既有审计报告的差异）。

### 硬约束（通用约束，所有成员必须遵守）
① 全程只读：不得修改/新增/删除 D:\erp_system 下任何文件（含 git 状态），不得写业务数据库，不得重启服务，不得装依赖；临时脚本只能写 %TEMP%\erp_audit_v2\；② 解析 Python 结构必须用 ast（历史伪影教训：正则曾产出"15 个迁移 head""48 个孤儿模块"，真相是单 head、零孤儿）；统计类结论必须给可复现命令；③ 每条结论必须带 文件路径:行号 或计数证据，禁止无证据泛泛而谈；④ 产出直接写在任务 output 文本里（结构：结论/证据/影响/建议），不落盘。
本机环境：Windows，shell 为 pwsh 工具（可执行 PowerShell）；python 3.13.13 位于 C:\Users\Administrator\AppData\Local\Programs\Python\Python313\python.exe；ruff 0.16.8、mypy 1.20.2 已装。当前日期 2026-10-01 14:54（方案文档与审计报告均为当日）。文件策略 danger-full-access。
重要坑：mypy 读 mypy.ini 时若不带 $env:PYTHONUTF8='1' 会 UnicodeDecodeError: 'gbk' codec can't decode byte 0x80 in position 273（mypy.ini 是 UTF-8 中文）；ruff 必须加 --no-cache 避免在仓库写 .ruff_cache；pytest 必须加 -p no:cacheprovider 并设 PYTHONDONTWRITEBYTECODE=1 避免写仓库；run_code 里 process.env.TEMP 为空，写临时文件要用字面路径 C:\Users\Administrator\AppData\Local\Temp\erp_audit_v2\；pwsh 命令里不要用反引号（TS 模板串会解析失败）。

### 关键上下文：优化方案与既有审计报告（已读全文）
docs/optimization-plan-2026-10-01.md（18,761 字节）：OPT-01..22 清单与详案，含 §0 总览表（编号/事项/优先级/工作量/风险/前置）、§6 度量基线（2026-10-01）：pytest 3491 过/6 败/180 跳；ruff errors 145（78 可自动修）；quality_gate 基线 裸 except 5/9 等 73 处存量；mypy 覆盖 106/536 文件；eslint 0 错/165 警；首屏 JS index 443KB + primevue 672KB；PG 无副本；明文 3000；uploads 免鉴权。关键项摘要：OPT-01 提交 22 个 WIP（拆 4 提交）；OPT-02 修 6 个 pytest 失败（tests/qa/test_smoke.py×3、test_database.py×1、test_numbering_sequence_integration×1、test_customer list total×1）；OPT-03 ruff --fix 78 + 收紧基线；OPT-04 删 useListQuery.ts 与 api/v2 空壳；OPT-05 修 git-bash `_lc` 劫持（embedded-search-startup-*.sh 第 12 行 rg() 语法错）；OPT-06 根目录草稿归档（_qa_tmp/、_ops/audit_scratch/、_beile_detail_*.py）；OPT-07 web_vital 4147 条离线分析；OPT-08 生产 Python venv 隔离（NSSM 五服务指向 .venv）；OPT-09 前端写操作统一 useApiMutation（建 useDomainInvalidation.ts 领域→query key 注册表 + 试点 customer-order→outsource→purchase）；OPT-10 CustomerTable(247行)/SupplierTable(285行) 迁 UiDataTable + 三套列表 composable 合一；OPT-11 API 层 5 处事务违规下沉（endpoints/order.py:334-394 delete_order、customer.py:114,302、purchase_plan.py:112,529、auxiliary.py:275,288、purchase_center/order_routes.py:98,122）；OPT-12 core/config 加 field_validator（备份加密口令联动）；OPT-13 mypy 106→全量（分 3-4 批每批~20 文件）；OPT-14 迁移图 4 根用 alembic merge 收敛；OPT-15 前端 bundle 拆分（primevue/echarts 延迟化）；OPT-16 PG 只读副本；OPT-17 nginx 443 TLS；OPT-18 nginx limit_req；OPT-19 /static/uploads/ secure_link 改造；OPT-20 进程内状态 Redis 化（WS 票据 ws.py:41、L1 广播 deps.py:34-71）；OPT-21 fastapi 0.137.1→0.142.2；OPT-22 备份"解密+校验"演练季度化（scripts/restore_drill.py）。

docs/optimization-plan-audit-2026-10-01.md（13,987 字节，既有审计，不得照抄）：结论"22 项中 14 项属实，4 项需修正方向，其中 3 项 BLOCKER"。其判定要点（供对比差异）：OPT-01 实际 24 行 WIP；OPT-02 孤立复现 46 过/1 败（test_database.py::TestBatchInsert::test_insert_100_products 因测试库残留 product 撞 product_name_key 唯一键）；OPT-03 精确属实（145/78）；OPT-04 属实；OPT-05 属实且本次审计期间再次干扰（exit 127）；OPT-06 属实；OPT-07 属实；OPT-08 属实且 requirements 完整性差集=0；OPT-09 被低估（实测 113-123 文件 import @/api，写类 27 文件，useApiMutation 仅 4 处、eslint 无禁入规则）；OPT-10 方向错误（usePagedSearch 业务引用=0，3 文件=定义+2 测试；useEnhancedList 业务引用=1 即 ProductTable）；OPT-11 大部不成立（仅 order.py:335-405 delete_order 属实，:364 await db.commit()、:382 post-commit、:388 publish_domain_event；customer.py:114/302 与 purchase_plan.py:112/529 是 docstring；auxiliary.py:275/288 是 commit=False；order_routes.py:98 是 _auto_commit=False）；OPT-12 部分属实（field_validator=0 属实，但非"静默"：crypto.py:57-69 有 warning、config.py:211-225 启动即校验告警）；OPT-13 属实（mypy.ini 106 条✓，services 84 非 82，536 口径含 tests）；OPT-14 BLOCKER（4 根✓、唯一 head✓、99/99 全部收敛到唯一 head pg_standalone_060_fix_updated_at_varchar_columns，merge 无对象；同号 017 实为 3 个）；OPT-15 前提不成立（echarts 被 7 文件引用，动态 import 封装已存在 utils/echartsPreload.ts 的 ensureEcharts/preloadEcharts）；OPT-16 BLOCKER（主机已有 postgresql-replica 与 postgresql-x64-18 两个 Windows 服务、replicator 角色 rolreplication=true、持久 walreceiver 但 replication_slots=0、无 streaming 状态 → 半成品副本）；OPT-17 属实（grep ssl=0）；OPT-18 属实（grep limit_req=0）；OPT-19 属实但风险高估（落盘名 日期/uuid4.hex，storage_service.py:165，不可枚举）；OPT-20 大半不成立（ws.py:41,54 内存票据但同时写 Redis、读路径 ws.py:64-73 miss 回退 Redis → 多实例安全；core/cache.py:56 L1 广播默认关但 ttl 仅 5 秒）；OPT-21 属实；OPT-22 属实（restore_drill.py 全文 56 行仅 ZipFile+restore，无解密无校验和；_constants.py:41-42 有 2026-08-23 事故注释）。

### 仓库/工具链事实（已实测，可复现）
- git HEAD = aac4c43f59a4374e05cdc5aee6c4aaa8afc99026，分支 main。
- git status --porcelain 首次为 "?? .agent-teams/"（干净）；随后发现 fastapi_app/services/base_search_service.py 变为 M（mtime 2026-10-01 14:55:03，即我审计开始后 24 秒）：diff 把 `model = self.get_model_class()` 改成 `model = type[self.model_type]` 并新增 `query: Query = db.query(model)`（第 88 行），引入 ruff F821 Undefined name `Query`。说明有其它 agent 正在并发修改生产仓库源文件——证据必须钉住 HEAD 并声明工作区漂移。该文件不在 mypy.ini 的 files 列表内。
- 任务里说"docs/architecture-review-2026-10-01.md 有一处未提交修改"已过时：该修改已在 aac4c43f（2026-10-01 14:52:03）提交。commit message：`docs(review): OPT-15 经构建实证关闭——echarts 不在首屏，评估前提修正`；正文说明：临时 outDir 构建产物验证，index.html modulepreload 仅 vue/query/fontawesome/axios 四个 vendor，vendor-echarts 只被 echartsSetup 动态引用、由登录后 preloadEcharts 预载；manualChunks 未破坏动态加载，557KB 常驻的说法不成立（与 web_vital LCP P75 1.2s 互相印证）；primevue 拆分降为可选优化。diff 仅改 docs/architecture-review-2026-10-01.md 2 行（给 vendor-echarts 557KB 句子与 P1 #13 加删除线与复核说明）。
- 今日（2026-10-01）提交序列（git log，新→旧）：aac4c43f(OPT-15 关闭)、9c75e2b3 refactor(customer,supplier) 手写表格迁移 UiDataTable（OPT-10b）、fc68b3af refactor(supplier,user) 行操作与权限保存迁移 useApiMutation（OPT-09 推广②）、2274ad84 refactor(case) 记录编辑/删除迁移 useApiMutation（OPT-09 推广②）、6a826723 chore(frontend) 删除零业务引用的 usePagedSearch（OPT-10a）、09e6cffb refactor(outsource) 工序添加/删除迁移 useApiMutation（OPT-09 推广①）、0c6a39af feat(frontend) 写操作统一 useApiMutation，备货编辑/删除接入（OPT-09 试点）、93ffb916 docs(adr) 迁移链 4 根为外观问题固化'勿动'判定（OPT-14）、9b1b42a7 fix(config) 结构性参数边界启动期拦截（OPT-12）、d97b84e5 fix(order) 删除订单端点事务收敛到 db_transaction（OPT-11）、27e9961a fix(deps) test.txt 补 Faker、d874a5a6 chore(gitignore) 忽略 .venv/、3decc215 test(frontend) 补 TAB 映射契约与备货失效键集回归、991265c3 fix(test) 测试 Redis 隔离到 db15 内存降级缓存逐用例清空（P0.5）、f181ee28 test(qa) 批量插入名称先截断再拼唯一后缀、344a7298 fix(frontend) 备货编辑必填校验、47c93d87 fix(stock) 入库编辑改数量与删除保护对称、10b179db docs 2026-10-01 全面技术评估/优化方案/审计复核、70664a37 chore(gate) 收紧质量基线（裸 except 9→5、超长函数 52→51）、b8825e11 style(lint) ruff --fix 清理 78 处机械违规（145→67）、e2bf3f46 docs(analysis) postgresql-replica 调查、db8d2267 docs(perf) web_vital 真实用户性能基线、ac5092e4/132238c9/ffb5bfb0 fix(test)、173178f8 chore 移除零引用的 useListQuery 与 api/v2 空壳目录、cfc91927 refactor(outsource) 外发 TAB 重排与出货视图拆分、0800cc8a feat(customer-order) 记录查询支持编辑入库记录、436a972e style(report) 筛选栏按钮靠右。另有更早的 ae97b11e/e9c75378/996923ca 等 purchase 相关。
- commit 9b1b42a7（OPT-12）实际实现不是 pydantic `@field_validator`，而是沿用 fastapi_app/core/config.py 的 `__init__` 手写闸门：新增 API_PREFIX 形状、REDIS_PORT/REDIS_DB 边界、令牌时效为正的启动期拦截（+19 行）；跑出 9 个坏值参数化用例的 fastapi_app/tests/test_config_structural_validation.py（+34 行）。备份加密拒绝启动已由 `_validate_production_backup_config` 覆盖（fastapi_app/core/config.py:191 定义，:431 调用）。

### 测试双树（已实测证据）
- 文件数：tests/ 148 个 .py；fastapi_app/tests 163 个 .py；scripts/ 179 个 .py。
- 行数（两种口径都测了）：tests/ Get-Content|Measure-Object -Line = 27,433，[System.IO.File]::ReadAllLines 求和 = 34,043；fastapi_app/tests = 27,700（Measure-Line，剔除空行）/ 34,696（ReadAllLines）。任务简述里"tests 27,433 / fastapi_app/tests 34,696"混用了两种口径。
- 子目录：tests/ 下含 contract、e2e、e2e_api、performance、qa、stress；fastapi_app/tests 下含 schemas、services。
- pytest.ini：`testpaths = tests fastapi_app/tests`（两棵树都在）、asyncio_mode=auto、addopts 含 -v --strict-markers --tb=short、filterwarnings error + ignore::UserWarning/DeprecationWarning、markers 含 unit/integration/functional/boundary/slow/api/model/db/contract。
- pytest --collect-only -q -p no:cacheprovider -o addopts= -o log_cli=false ⇒ "3689 tests collected in 8.59s"（collect.txt 记 3691 行；含 "::" 的节点 3688 条）。按树：tests/ 1465，fastapi_app/tests 2223。
- 同名 basename 交集 13 个：__init__.py、conftest.py、test_approval.py、test_auth.py、test_backup.py、test_customer.py、test_material_registration.py、test_order.py、test_product.py、test_report.py、test_state_machine.py、test_stock.py、test_user.py。（注意 test_auth.py 的 tests/ 侧实际是 tests/stress/test_auth.py。）
- 逐对比较（name | tests/行数 | fastapi_app/tests行数 | tests/节点数 | fatests节点数 | md5 是否相同 | 路径对）：
  conftest.py | 571 | 232 | 0 | 0 | DIFF | tests/conftest.py <> fastapi_app/tests/conftest.py（另 tests/e2e/conftest.py 54 行、tests/e2e_api/conftest.py 350 行）
  __init__.py 三处：tests/e2e(3行)、tests/e2e_api(4行)、tests/qa(1行) vs fastapi_app/tests/__init__.py(0行)
  test_approval.py | 151 | 200 | 12 | 17 | DIFF
  test_auth.py | 24 (tests/stress/) | 168 | 0 | 7 | DIFF
  test_backup.py | 191 | 486 | 15 | 52 | DIFF
  test_customer.py | 399 | 204 | 24 | 16 | DIFF
  test_material_registration.py | 278 | 204 | 20 | 17 | DIFF
  test_order.py | 780 | 361 | 34 | 24 | DIFF
  test_product.py | 438 | 309 | 27 | 30 | DIFF
  test_report.py | 208 | 111 | 15 | 10 | DIFF
  test_state_machine.py | 74 | 82 | 14 | 14 | DIFF
  test_stock.py | 529 | 452 | 26 | 34 | DIFF
  test_user.py | 340 | 466 | 26 | 33 | DIFF
- 结论性统计：完全相同的"相对路径+用例名"节点在双树同时出现的只有 1 个 → 逐节点重复率 ≈ 1/3688 ≈ 0.03%；但 11 对 test_*.py 同名文件全部内容不同（md5 全 DIFF），属"同名不同实现"的语义重叠风险而非机械复制。
- 双树 conftest 差异大（571 vs 232 行），是合并的主要风险面。

### ruff / mypy / 配置（已实测）
- ruff.toml：target py313、line-length 120、select = E,F,W,I,N,UP,B,SIM,C4,S,RUF、external=["BLE001"]、ignore 列 20 条（E501/B008/SIM108/RUF001-003/S311/S608/S603/S607/S104/S310/S324/E402/F405/N806/SIM117/E702/E701/N815/SIM113/SIM102/E741/UP046）；per-file-ignores：**/tests/**/*.py=[S101,S105,S106,S107,S311,B017,RUF043]、scripts/**/*.py=[S101,S105,S106,S107,S311,S603,S607,E402]、fastapi_app/services/stock_service.py=[S608]、fastapi_app/services/backup/__init__.py=[I001]。
- ruff check . --no-cache（PYTHONDONTWRITEBYTECODE=1）当前 = Found 70 errors（首次运行为 69，差异恰为下面那条 F821，疑与并发改动同时发生；70 为当前稳定值）。规则分布：UP031 24、S110 19、S101 6、S112 4、F841 4、SIM105 3、I001 2[*]、RUF059 2、F821 1、RUF005 1、E731 1、RUF012 1、B904 1、S606 1。仅 2 条可自动修。
  目录分布：server_manager 28、scripts 27、docs 9、(root) 3、tests 2、fastapi_app 1。
  关键命中：fastapi_app/services/base_search_service.py:88:16: F821 Undefined name `Query`（真实 bug，见上文并发修改）；scripts/diag/runtime_mode_probe.py 有 17 条 UP031；server_manager/app.py 有 ~13 条 S110/S112 + RUF012/RUF059/S606/F841；docs/tickets/tools/rebuild_migration.py 5×S101+E731；docs/ui-redesign/one_click_action_component.py:257/259 SIM105+S110；(root) 3 条含 check_workspace_acl.py:85,86,87 UP031、switch_env.py:20 F841、scripts/create_purchase_plan_multi_per_day.py:106 F841；tests/qa/perf_final.py:52 与 tests/qa/performance_benchmark.py:50 I001。
- mypy.ini：`files = ` 显式列表实测 106 条（fastapi_app/core 15、fastapi_app/shared 2、fastapi_app/shared_models 5、fastapi_app/services 84）；python_version=3.13、check_untyped_defs=True、ignore_missing_imports=True、follow_imports=silent、exclude=(^\.archive/|^tests/|^fastapi_app/tests/)。
- mypy --no-incremental（PYTHONUTF8=1）实测输出："Success: no issues found in 106 source files" → 已纳入范围 0 错，棘轮未破。
- 独立复核 mypy 未纳入范围：`python -m mypy fastapi_app/services/ --no-pretty --no-incremental --ignore-missing-imports --check-untyped-defs --follow-imports=silent` ⇒ "Found 387 errors in 68 files (checked 184 source files)"。错误码分布：arg-type 97、assignment 60、attr-defined 49、operator 46、union-attr 33、var-annotated 30、index 25、dict-item 16、return-value 12、call-overload 8、misc 7、type-var 2。样例：fastapi_app/services/staging/stockout.py:235 与 :244 arg-type（build_entity / extra_row_validations 回调签名不兼容）。
- mypy 覆盖缺口（python 脚本比对 mypy.ini 与错误分布）：services 共 184 个 .py；其中 0 错的 117 个；已纳入 84 个；**33 个"零错但未纳入"**（可直接加进 files 列表、零修复成本）：fastapi_app/services/__init__.py、services/backup/cleanup/__init__.py、services/backup/freshness.py、services/backup/incremental.py、services/backup/metrics/__init__.py、services/backup/orchestration/__init__.py、services/backup/verify/__init__.py、services/case/__init__.py、services/customer_sampling/__init__.py、services/dashboard/__init__.py、services/material_registration/__init__.py、services/numbering_reconcile.py、services/numbering_sequence.py、services/ocr/__init__.py、services/ocr/_order_match.py、services/ocr/_order_parsers.py、services/ocr/_order_preview.py、services/order/__init__.py、services/order/_common.py、services/order/unified.py、services/outsource/__init__.py、services/outsource/_shipments.py、services/plan_utils.py、services/product/__init__.py、services/product/bom_role_resolver.py、services/product/role_service.py、services/purchase/__init__.py、services/purchase_order_sku.py、services/purchase_order_spare.py、services/purchase_plan_common.py、services/purchase_plan_order_quota.py、services/serializers/__init__.py、services/staging/__init__.py。剔除 12 个 __init__.py 后 = 21 个真实模块可直接纳入。
  已纳入但当前有错的 services 文件 = 0（棘轮未破）。
  mypy.ini 注释声称"services 层 156 个文件中 74 个仍有类型错误（合计 400 个 error）"→ 实测已变化（156→184 文件，74→67/68 文件，400→387 error），注释已过时。
  仓库非 vendor .py 总数（排除 .git/.venv/node_modules/__pycache__/frontend-vite/backups/logs）实测 1257 个 → "536" 分母口径需另作说明。
- pyproject.toml：只有 [tool.code-quality]：max_function_length=80、max_vue_component_length=400、max_file_size=1600（注释说明 1600 由 scripts/file_size_gate.py 与 CI 从此处读取）；刻意无 [build-system]/[project]，依赖唯一来源是 requirements/*.txt。
- .pre-commit-config.yaml：ruff-pre-commit rev v0.11.0（ruff --fix + ruff-format）+ local hook quality-gate（entry: python scripts/quality_gate.py，always_run）。本机未装 pre-commit（AGENTS.md §4）。

### git-bash / OPT-05 证据
- C:\Program Files\Git\etc\profile.d\ 现仅有 aliases.sh、bash_profile.sh、env.sh、git-prompt.sh、lang.sh、perlbin.csh、perlbin.sh —— 原 embedded-search-startup-*.sh 已不存在；C:\Program Files\Git\etc\bash.bashrc 无 lean/embedded/_lc/rg() 命中。
- 实测 `& "C:\Program Files\Git\bin\bash.exe" -lc "npm --version; ls -1 | head -3; echo RC=$?"` ⇒ 11.12.1 / _ops AGENTS.md alembic.ini / RC=True —— 命令不再报 _lc: command not found。

### docs / 根目录清单（已实测）
- docs/ 顶层 10 个 md：architecture-review-2026-10-01.md 34677、CODE_REVIEW_OPTIMIZATION_PLAN.md 18937、ERP_上线前代码质量审查报告.md 50732、ERP_上线前全面代码质量审查报告_2026-09-29.md 49359、ERP_上线前优化方案.md 38447、erp-benchmark-baseline.md 14484、optimization-plan-2026-10-01.md 18761、optimization-plan-audit-2026-10-01.md 13987、performance-baseline.md 7252、TRANSACTION_BOUNDARY_GUIDE.md 4906。
- docs/ 递归 .md 总数 221（分组：bugs 38、designs 34、plans 30、ui-redesign 21、tickets 11、superpowers/plans 10、docs 顶层 10、analysis 9、reports 7、upgrade 6、tickets/iterations 5、decisions 5、superpowers/specs 5、ui-redesign/backup-center 4、purchase 4、backup-restore 3、adr 3、ui-redesign/backup-page-v2 3、runbooks 3、beile-order-sync 2、bom-multi-role 2、ui-redesign/v3 2、tickets/artifacts/benchmark 1、ops 1、outsource 1、perf 1）。
- docs 子目录共 24 个：adr analysis backup-restore backups beile-order-sync bom-multi-role bugs decisions designs ops outsource perf plans purchase reports runbooks superpowers tickets ui-redesign upgrade。
- docs/perf/web-vitals-baseline-2026-10.md 存在（2657 字节）→ OPT-07 已落盘。
- docs/adr/2026-10-01-migration-roots-are-cosmetic.md 存在（OPT-14 的 ADR，第 9 行"不对迁移链做任何修根操作"，第 13 行"99 个迁移单 head: pg_standalone_060_fix_updated_at_varchar_columns"，第 20 行新增迁移以 060 系为 down_revision，第 21 行明确不做线性化）。
- 仓库根非目录文件：.brooks-lint-history.json 213、AGENTS.md 7629、CHANGELOG.md 29629、dsh-web-dump-config.txt 201738、GEMINI.md 581、README.md 4075、README_DEPLOY.txt 3728、requirements.txt 938、server_manager_config.json 293。根目录下划线开头项仅有 _ops（DIR）。
- _ops/ 下：audit_scratch DIR、credentials DIR、scratch-archive-2026-10 DIR、README.md 1801。_ops/audit_scratch 仍有 30 个文件（_audit_backup_crypto.py、_audit_be_tests.txt、_audit_cov.txt、_audit_cov_full.txt、_audit_fe.txt、_audit_fe2.txt、_audit_git_history{,2,3,4}.{json,py}、_audit_migrations.{json,py}、_audit_net.{json,py}、_audit_scale.{json,py}、_probe_tables.py、_probe_token.py、_probe_users.py、_qa_tmp_beile_probe2..5.py、_qa_tmp_diffstat.txt、_qa_tmp_status.txt）。_ops/scratch-archive-2026-10/ 已收纳 agent-teams、_dsh_research、_qa_tmp、__pycache__、_beile_detail_align_check.py、_beile_detail_meta_check.py、_probe2.py、_probe3.py、_proc5002.json、_tmp_env_probe.py、_uvicorn_restart_err.log、_uvicorn_restart_out.log、_asar_*.mjs、_scan_asar.mjs、_dsh_research_awesome1.md。根目录散落草稿（_qa_tmp/、_beile_detail_*.py）已不在根 → OPT-06 部分完成。

### 前端 / nginx / 其他 OPT 证据（部分）
- config/ 下 nginx 配置只有 config/nginx-windows.conf（7918）与 config/nginx.conf（6456）。nginx-windows.conf:37-38 `listen 3000 default_server;` + `listen [::]:3000 default_server;`，:94 `alias D:/erp_system/static/uploads/;`；grep ssl|limit_req|secure_link 均 0 命中 → OPT-17/18/19 未做。
- requirements/base.txt:7 `fastapi==0.137.1` → OPT-21 未做。requirements/base.txt:67 opentelemetry-instrumentation-fastapi==0.51b0、:78 sentry-sdk[fastapi]==2.29.1。
- scripts/restore_drill.py 全文约 56 行，仅 zipfile.ZipFile + newest_backup()（:35-38 glob backups/server/erp_backup_*.zip）+ :42 async def main()，无解密、无校验和 → OPT-22 未做。
- .venv 目录已存在（含 Include,Lib,Scripts,share,.gitignore），且 d874a5a6 已 gitignore .venv → OPT-08 至少已建环境，NSSM 是否切换待查。
- frontend-vite/src/composables/ 现有：notificationMemoryCache.ts、useApiMutation.ts、useConfirmDialog.ts、useDebouncedRef.ts、useDebouncedSearch.ts、useDevice.ts、useEnhancedList.ts、useEventDelegation.ts、useExport.ts、useImagePaste.ts、useMaterialCalculator.ts、useNotificationCenter.ts、useNotifications.ts、usePerfMark.ts、usePermission.ts、useTableVirtualScroll.ts、useToast.ts、useVirtualScrollList.ts、useWebSocket.ts。useListQuery.ts 与 usePagedSearch.ts 均已删除 → OPT-04、OPT-10a 已完成。**useEnhancedList.ts 仍在**，引用仅 frontend-vite/src/views/product/components/ProductTable.vue:60 与 :90。**useDomainInvalidation.ts 不存在**（OPT-09 计划的领域注册表未建）。
- useApiMutation 引用点（30 处命中）：定义在 frontend-vite/src/composables/useApiMutation.ts:23；使用方 customer-order/composables/useStockinEdit.ts:18,63,95（试点）、outsource/components/OutsourceAddProcessDialog.vue:49,81,95、outsource/components/OutsourcePresetTab.vue:85,179、case/composables/useCaseRecordActions.ts:8,81,110、user/composables/useUserManagement.ts:13,70,83,277、supplier/composables/useSupplier.ts:11,75,94,107,142、customer/composables/useCustomer.ts:11,90,95,100,104。useApiMutation.ts 头部注释（:10-12）说明 invalidateKeys 平铺键 vs invalidate 函数（utils/queryKeys 具名领域失效，"OPT-09 起推荐后者"）；:17-21 说明新增 run(vars)（失败不抛，返回 undefined）用于弹窗场景，并注明"全部迁移完成前不启用『view 禁入写函数』的 lint 规则"。跨页失效测试存在：frontend-vite/src/test/customerOrderCrossPageInvalidation.test.ts。
- CustomerTable/SupplierTable 已迁 UiDataTable：frontend-vite/src/views/customer/components/CustomerTable.vue 239 行（原 247）、UiDataTable 命中=YES；frontend-vite/src/views/supplier/components/SupplierTable.vue 191 行（原 285）、UiDataTable 命中=YES → OPT-10b 已完成。
- OPT-11 已修复：fastapi_app/api/v1/endpoints/order.py:24 `from fastapi_app.core.exceptions import AppError, NotFoundError, db_transaction`；delete_order 定义在 :335，:342 docstring 说明"事务模式：db_transaction + error_map（TRANSACTION_BOUNDARY_GUIDE §2.3）"，:374 `async with db_transaction(db, error_map={`；缓存失效 :385 invalidate_dashboard()，领域事件 :390 publish_domain_event。该文件多处 await db.commit() 已消失（改为 db_transaction 上下文）。
- frontend-vite/src/api/ 目录文件：approval auth auxiliary backup batch case customer dashboard index material notification ocr order orderBatch outsource patternMaker patternRoom plan product production purchase report request role stock supplier user（27 个）。
- OPT-20 复核：fastapi_app/api/ws.py:35 `_WS_TICKET_PREFIX = "ws:auth_ticket:"`、:44 async def _issue_ws_ticket、:47 secrets.token_urlsafe(32)、:54 `_WS_PENDING_TICKETS[ticket] = user_id`（内存）同时 :49 safe_set 写 Redis；:58 async def _consume_ws_ticket，:64 先 pop 内存、:66 再 safe_get Redis、:73/:75 safe_delete → 与既有审计"多实例安全"结论一致。

### Open objectives（原文保留）
- 完成 t4：产出「工程健康度评估 + OPT-01..22 状态表（状态/代码证据 文件:行/与既有审计报告差异）」，写入 t4 output，update_task(completed) + send_message(captain) + send_message(parent session-b182657c-f02a-48ac-96de-7dc94a41dee7)。(m00001)
- 尚需补：OPT-02 抽样快速子集实跑、OPT-08 NSSM 是否指向 .venv、OPT-15 vite.config.ts manualChunks 复核、OPT-16 docs/analysis 副本调查文档与 PG 副本现状、scripts/ 与 fastapi_app 职责重叠与可清理项（③）、docs/ 过期/重复文档判定（④）、quality_gate.py + gate_baseline.json 现状与棘轮收紧数字。

---

## ⚠️ 完整性缺口声明（归档者添加，必读）

- **本文件不是 t4 完整报告，而是从成员会话转录恢复的「压缩/折叠片段」**：恢复件首行即 `# TASK AS OF THIS BLOCK (history)`（历史压缩块标记），大量条目在字符数附近被截断，末尾仍保留 `## Open objectives（原文保留）` 这类过程性块。
- **构成**：约 20,279 字符，其中相当篇幅是「任务派单 + 硬约束 + 关键上下文」的过程记录；属于审计结论的分节为「仓库/工具链事实」「测试双树（已实测证据）」「ruff / mypy / 配置」「docs / 根目录清单」「前端 / nginx / 其他 OPT 证据」。
- **已知缺失（必须重跑 t4 才能补齐）**：① **工程健康度评估**总评段；② **OPT-01..22 状态表**（每项「状态 / 代码证据 文件:行 / 与既有审计报告的差异」）—— 恢复件只有 OPT-05/08/11/12/13/14/15/20/21/22 的零散证据，**没有完整 22 项状态表**；③ scripts/ 与 fastapi_app 职责重叠与可清理项；④ docs/ 过期/重复文档判定清单；⑤ quality_gate.py 与 gate_baseline 收紧项。
- **恢复件两处自述截断**：`## 前端 / nginx / 其他 OPT 证据（部分，后续步骤继续补）` 标题已声明「部分」；`## Open objectives` 第二条（「尚需补：…」）在 `quality_gate.py + gate_ba` 处被截断。
- **重跑建议**：t4 的可复现命令与已知坑（`PYTHONUTF8=1`、`ruff --no-cache`、`pytest -p no:cacheprovider`）在恢复件「关键上下文」一节中已完整保留，重跑成本低。

