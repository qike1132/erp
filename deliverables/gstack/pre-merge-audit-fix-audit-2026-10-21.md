# 合并前逐提交审核报告：fix/audit-2026-10-18 → main（132 提交）

**日期**：2026-10-21
**场景**：合并前代码审查（逐提交裁决 + 门禁实证 + 安全审计）
**参与成员**：reviewer-core（A批）+ reviewer-audit（B批）+ reviewer-data（C批）+ reviewer-frontend（D批）+ qa-gate（门禁实证）+ sec-audit（安全审计）+ 主理人独立复核

---

## 📌 TL;DR（执行摘要）

- 整体结论：**🟡 有条件 Go** —— 分支整体是净改善（修复了 main 上的 P0 越权、更严重的金额口径错误、大量死代码与假成功），HEAD 上**没有未闭环的回归**；静态门禁 16/16 全绿 + 前端 vitest 1313 用例全绿 + 后端提权 pytest 195 passed。存在 1 个 🔴 与 13 个 🟠 须合并后立即处置，以及 1 套必须遵守的发布顺序纪律。
- 132 个提交逐提交裁决：**✅ 106 / ⚠️ 22 / ❌ 4**。4 个 ❌ 中 3 个已被同分支后续提交自愈（bfd2e801→414004cc、2651455e→6f31c042、97cfff27→b4131e9b），1 个（49fae2e5 aiohttp）只是"只升测试档、生产 CVE 未修"，不构成回归。
- 动态测试实证（已补齐）：**前端 vitest 205 文件/1313 用例全绿**（7 条红灯全部可证明源自未提交 TDD 草稿）；**后端提权 pytest 聚焦 7 文件 195 passed / 0 failed**。全量 4353 条回归建议合并后补跑一次。
- 安全审计：**边界显著加强、零"改弱"提交**；密钥面与 frp 暴露面清白；唯一近阻塞项（批量导入三端点无工厂闸门）经主理人核实为 **main 存量洞而非分支引入**（main 上闸门调用点=0），合并是净改善。
- 下一步：① 用户收尾未提交改动（两处工作树改动会阻挡快进，已确认暂不动仓库）；② 提权会话补跑 pytest；③ 按"先代码重启、再人工跑迁移 100-103"的顺序执行合并与发布。

---

## 🎯 核心结论卡片

| 项目 | 内容 |
|------|------|
| Go / No-Go | 🟡 条件 Go（合并动作本身安全且净改善；随附 13 项合并后立即处置 + 1 套发布纪律） |
| 严重度分布 | 🔴 1 / 🟠 13 / 🟡 15 / 🟢 若干（详见 §3，均已去重） |
| 关键行动项 | 9 条（见 §5 行动清单） |
| 逐提交裁决 | ✅ 106 / ⚠️ 22 / ❌ 4（❌ 全部为"批内自愈"或"仅测试档"，HEAD 无残留回归） |
| 安全结论 | 边界显著加强、零"改弱"提交；密钥面与 frp 暴露面清白；唯一近阻塞项（导入三端点无闸门）经核实为 main 存量洞 |
| 建议负责人 | 工程负责人（合并）+ 后端（闸门/幂等键/假成功三组修复） |

**裁决口径说明**：✅=有证据证明修复有效且无回归；⚠️=修复有效但留有缺口/依赖未验证前提；❌=失效或引入回归（标注是否已被后续提交自愈）。

---

## 1. 各成员核心结论

### 🔍 reviewer-core（A 批 #1-33：核心业务 P0/P1）
- 核心判断：26✅/6⚠️/1❌。P0-1 删单回滚、P0-2 工厂闸门、批次闸门、采购 status 三层白名单均**真实有效**（有行为断言级测试，非镜像断言）。
- 关键发现：① 批量导入三端点（`/batch/import-stockins` :142、`/import-stockouts` :164、`/import-comprehensive` :237）**无工厂闸门**——全仓 10 处 `assert_product_factory_scoped` 调用点无一在导入链上，HEAD 复核仍成立；② 皮套导入幂等键过宽（五元组无行号/单号/文件哈希）；③ `auxiliary.py:476` 入库顶层 `success` 硬编码 True，与 :504 出库分支 `all(...)` 口径不一致；④ `49fae2e5` aiohttp 只升测试档，生产 CVE 未修。
- 跨批次回退核查：A 批修复与 7 个守门测试文件**零回退、零丢失**（闸门调用点 6 处全在、用例数只增不减、两处大文件拆分总数守恒 93=74+19 / 66=58+8）。

### 🔍 reviewer-audit（B 批 #34-66：审计 Z 系列 + 备份重构 + 门禁）
- 核心判断：27✅/5⚠️/1❌。937 行死代码删除经 18 个符号名逐个 grep **零残留**；`backup.__all__` 115 项与 mypy.ini 377 条白名单静态校验 DANGLING=[]；清库表清单用 AST 断言"清单==SQL"完全相等。
- 关键发现：① `restore_core.py:288` 失败判定为 `returncode != 0 or error_lines`——真实 dump 中非致命 ERROR（`must be owner of` 等）会把**恢复成功报成失败**，事故现场易诱发对好库重放（主理人 HEAD 复核确认）；② `orchestration/policy_service.py:460` 二级存储同步的 `NotImplementedError` 被**同函数** `except Exception` 吞掉，外层仍返回 `success: True, policy_applied: True`——"假成功"换了个位置继续存在（主理人 HEAD 复核确认）；③ `prod_runner.py:774-777` 先 `shutdown()` 后 `request_stop()`，Ctrl+C 期间主循环仍可 `maybe_restart()` 复活 uvicorn，留下占 :5002 的孤儿。
- 提醒：`bfd2e801` 单提交会让 CI lint 红（mypy 悬挂条目），**必须整支合并，不可从这一段逐提交 cherry-pick**。

### 🔍 reviewer-data（C 批 #67-99：迁移/金额/导入收敛）
- 核心判断：27✅/5⚠️/1❌。迁移链用 alembic `ScriptDirectory` 实跑确认**单一 head**、143 revision、无孤儿、无新增破坏性 DDL（103 已按棘轮登记）；金额公式手算 6 组边界值（含损耗率 0/100%、数量 0）全部正确；`e350fb84` merge 提交经 tree hash 比对**未吃掉任何内容**。
- 关键发现：① **采购金额三个数量口径并存**：数量列/打印用 `ceilMagnifiedByLossRate`（向上取整），金额与导出用 `magnified_purchase_qty`（2 位小数）。qty=10、损耗率 5‰、单价 100 → 页面数量 **11**、金额 **1005.00**、导出数量 **10.05**，每行差 95 元且导出与页面对不上（主理人已独立读码确认三个函数确实并存）；② 迁移 103 是 `DROP COLUMN stock_in.is_deleted`，生产 alembic 实测停在 099（100-103 未应用），**顺序错了（先迁移后重启旧进程）会当场 `UndefinedColumn` 500**；③ Pillow 13.0.0 已热替换到磁盘但 `erp-prod`/`erp-arq` 进程内存仍是 12.3.0，4 个被 mmap 锁住的 `.pyd` 是靠改名绕的——下次重启才是真考验；④ `fc2c2b2f` 备份鉴权断言是空断言（无 Redis 时恒 401，鉴权闸门被删也绿）。

### 🔍 reviewer-frontend（D 批 #100-132：DTO 派生化 + 门禁/诊断）
- 核心判断：26✅/6⚠️/1❌。DTO 豁免 44→8 的派生化经 **10 条逐字段抽查等价**（字段名/可选性/枚举收窄逐项比对）；两处真实回归（`97cfff27` 抹掉可空性、`1bc42555` 放松容器元素）均已在批内被 `b4131e9b`/`3ab15570` 修回，且全仓排查**无同类未修残留**（14 处 `Array|null` 字段逐一核对）。
- 关键发现：① 等价性靠人工一次性核对维持而非门禁维持——`check-mobile-dto.mjs` 逐行判据漏多行写法，`dtoDerivedLock` 只锁 2 个类型（~68 个迁移类型无锁），下次后端加可选字段可能造成"数字静默变空"的报表错误；② 破坏性 DDL 棘线（`destructive_ddl_baseline.json`）**不在 pre-commit 棘轮守卫覆盖范围**（`quality_gate.py` 无 destructive 键），可同提交自证上调，且扫描器对 f-string 盲（100 的键因此消失）；③ CI 的 review packet 步骤（`ci-cd.yml:263-270`）无 `continue-on-error`，`review_packet.py` 抛 `PacketError` 会让 lint job 红——**主理人复核修正：该步骤 `if: pull_request` 仅 PR 事件运行，本次直接 push main 不触发，降为 🟡**；④ pre-commit `find_ruff` 全败时 `return 0` fail-open，且 Python 候选坏 venv 时回落系统解释器会让 pip_audit 扫全机 site-packages。

### ✅ qa-gate（门禁与测试实证）
- 核心判断：**静态侧全绿 + 前端单测侧有实证（1313 用例全绿）+ 后端 pytest 待一次提权**。
- 静态：`quality_gate.py` 16 项 check 全 PASS（系统 Python，alembic/bandit 正常）；ruff 后端 0 违规（scripts/server_manager 18 条存量=基线）；前端 type-check 之外 5 项全 PASS（lint / check:api buster 同步 / check:routes / check:dto 443 类型豁免 8 / check:types）。
- type-check 15 条错误：4 个报错文件经 `git cat-file -e HEAD:<path>` 验证**全部不在 HEAD**（未跟踪草稿），且无 `declare global` 不可能掩盖已提交文件错误 → 与 132 提交无关。
- **vitest 实证（第二轮，esbuild 绕法成功）**：复用本仓 `vite-build.mjs` 的方案（esbuild.exe 复制到仓外 Medium 完整性目录 + `ESBUILD_BINARY_PATH`），**205 个测试文件 / 1313 用例跑完，failed=7**。7 条失败 100% 落在 2 个未跟踪 TDD 草稿文件（`stockOutImportSectionFileInput.test.ts` 4/4，文件名自带 "Red" 标注；`stockOutAvailabilityGatesPool.test.ts` 3/6）——**提交内容的 204 个测试文件 0 失败**。遗留：vitest 打印完全部结果后挂起不退出（疑似完整性标签次生效应），数字来自逐文件日志而非官方 summary 行。
- pytest 无法非提权绕过（读了代码确认，非猜测）：两个 conftest 用内建 `open()` 读 `.env`（`tests/conftest.py:75`、`fastapi_app/tests/conftest.py:33`），dotenv stub 拦不到；且测试库凭据与 SECRET_KEY 只在 .env 里（`config.py:368-370` 强制非空）。AGENTS.md 说的 stub 脚本仅存在于单个回填脚本内联，无 pytest 运行器可用。**唯一正路 = 一次 UAC 提权跑 `logs/run_full_tests.sh`**（脚本已 Read 核实：位置参数传 pytest 参数、内部 Start-Process -Verb RunAs 只弹一次 UAC、按 PID 隔离文件、兜底等 25 分钟）。
- **后端 pytest 实证（第三轮，提权成功）**：`logs/run_full_tests.sh` 聚焦 7 文件（test_stock_routes / test_order_delete_multisku_rollback / test_stock_factory_scope / test_outsource / test_purchase_plan_core / test_purchase_loss_rate_amount / fastapi_app/tests/test_backup）→ **195 passed in 40.28s，EXITCODE=0**（logs/_pytest_elevated.1385.log）。覆盖 A 批守门测试、外发、采购计划与金额口径、备份域。
- 变异检查：待后续排期补做（非合并前置）。

### 🛡️ sec-audit（安全审计）
- 核心判断：**这批提交整体是「安全边界显著加强」**——工厂闸门、备份加密单一决策、恢复护栏、危险写护栏、依赖升级全部净收益，未发现任何"改弱"的提交。唯一接近阻塞的是 Excel 批量导入三端点无闸门（P0-2 同类残留）。
- 独立复核结论：**该洞是 main 的存量而非分支引入**——main(946f2a2f) 上三个导入端点原样存在且只挂 `require_permission`，main 上工厂闸门调用点数为 **0**；分支带来 10 处闸门。合并是净改善，定级 🟠"合并后立即修"，不阻塞合并。
- 密钥面清白：docs/ 与 deliverables/ 全量 grep 无真实凭据（仅自指文档引用）；132 提交 `--diff-filter=A` 无任何 .env/credentials/pem/key/userlist 文件；3 个用了 `--no-verify` 的提交产物独立复扫无泄漏。
- frp/暴露面清白：132 提交 0 处触碰 frp/tunnel/nginx 暴露面配置（`.env.bak-frp-*` 为 gitignore 内主机残留，建议按凭据轮换处理）。
- CORS/Cookie/JWT/密码哈希/CSRF/中间件**全部零改动**；uvicorn 仍绑 127.0.0.1:5002；/metrics fail-closed 未动。
- 写端点鉴权盘点：本批新增/改动的写端点 16 组逐个核过，除三个导入端点 ❌ 与 `/batch/import-orders` 建单无订单域闸门（⚠️ 需人工确认创建口径）外，其余全部 ✅。
- 新增发现：① Excel 公式注入清洗只接了 report_exporter 与采购打印，**production_summary/finished_stock/production_plan/daily_production/plan_utils 5 个 xlsx 写点未接**（存量）；② 危险写护栏未统一——`reset_admin_password.py:49`、`migrate_password_hashes.py:196`、`perf_add_indexes.py`、`cleanup_duplicate_purchase_orders.py:116`、`backfill_production_stock_20261006.py:111` 仍无护栏直写生产库，且 `test_write_guard_wiring.py:34-38` 是源码字符串断言（不证明调用先于写库）；③ 备份加密 KEY 回退不对称：加密链认 PASSWORD→KEY，恢复链只认 PASSWORD——只配 KEY 的部署自己解不开自己的备份（fail-closed，可用性缺口非静默明文）。
- 主理人澄清：`.env.production APP_ENV=development` 疑点**不成立**——全仓无任何加载逻辑引用它（`config.py:131` 注释自证两份配置长期漂移），根 `.env` 是唯一权威。保留维护窗口一条只读确认（运行用户跑 `python -c "from fastapi_app.core.config import settings; print(settings.is_production)"`）以彻底闭环。

---

## 2. 逐提交裁决汇总

| 批次 | 范围 | ✅ | ⚠️ | ❌ | ❌ 明细 |
|------|------|----|----|----|---------|
| A（reviewer-core） | #1-33 核心业务 | 26 | 6 | 1 | #15 `49fae2e5` aiohttp 只升测试档（生产 CVE 未修，非回归） |
| B（reviewer-audit） | #34-66 审计/重构 | 27 | 5 | 1 | #50 `bfd2e801` 删除致 CI lint 红（**已由 #63 闭环，整支合并无影响**） |
| C（reviewer-data） | #67-99 迁移/金额 | 27 | 5 | 1 | #85 `2651455e` 导入凭空生成采购单（**已由 #96 自愈，无残留**） |
| D（reviewer-frontend） | #100-132 DTO/门禁 | 26 | 6 | 1 | #121 `97cfff27` WithItems 抹可空性（**已由 #125 修复，同类排查无残留**） |
| 合计 | 132 | 106 | 22 | 4 | HEAD 无未闭环回归 |

⚠️ 存疑清单（修复有效但留缺口，均已计入 §3 发现表）：#2 #4 #11 #19 #23 #28（A）；#36 #39 #46 #58 #60（B）；#70 #74 #82 #97 #98（C）；#102 #112 #114 #122 #131 #132（D）。

---

## 3. 综合审查发现（去重后按严重度排序）

### 🔴 阻塞级（合并后立即处置，处置前有真实业务风险）

| # | 位置 | 问题 | 生产影响 | 建议 |
|---|------|------|---------|------|
| R1 | `batch_import_service.py:443-460` × `90b913a6` | **幂等键过宽被 C 批激活（跨批次叠加）**：键 `(case_id,direction,movement_date,quantity,customer)` 无行号/单号/文件哈希；A 批时时间回退带微秒几乎不命中，`90b913a6` 改业务日零点后**真实生效**。同款键还在 `InventoryLog.idem_key`（`_import_idem_key`，:411/:630/:701，订单/入库/出库三处共用） | 同日同款同量同客户的合法重复行被**静默跳过**，库存只记一次，界面只显示"跳过 N 条"——账实不符且无报错 | 键补行号/单号/文件哈希区分字段，或改"同键且同来源文件哈希"才判重；补"两行合法同值均应导入"用例 |

### 🟠 高（合并后尽快处置）

| # | 位置 | 问题 | 建议 |
|---|------|------|------|
| H1 | `batch.py:142/164/237` + `batch_import_service.py` | 批量导入三端点（备货/出货/综合）只挂 `require_permission('batch_import')`，服务层直写 StockIn/StockOut，10 处工厂闸门调用点无一在导入链上（HEAD 复核仍成立） | 端点入口按行 product_id 逐项过闸门（参照 `auxiliary.py` 的 `_factory_gate_batch_items` 模式），补 HTTP 级用例 |
| H2 | `orchestration/policy_service.py:460-467` | 二级存储同步"假成功"：NotImplementedError 被同函数 except 吞掉，外层仍 `success: True`，`storage_result.applied` 全仓无消费者，告警分支到不了 | 异常穿透到 `apply_backup_policy` 的 except，或把 `applied is False` 升级为告警 |
| H3 | `scripts/database/restore_core.py:288` | 失败判定 `returncode != 0 or error_lines` 过宽：非致命 ERROR（`must be owner of`、`role does not exist`）把恢复成功报成失败并 exit 1 | 仅 returncode≠0 判失败，ERROR 行降级为 warning 汇总或白名单；**上线前用真实生产 dump 做一次恢复演练** |
| H4 | `prod_runner.py:774-777` vs `:711-726` | Ctrl+C 后先 `shutdown()` 后 `request_stop()`，期间 `maybe_restart()` 可复活 uvicorn → 孤儿占 :5002（本仓历史上的假成功形态） | `request_stop()` 提到 `shutdown()` 之前；`poll/maybe_restart` 入口判 `_stop` |
| H5 | `perSkuRows.ts:90` / `useSummaryModal.ts:51,177,277` / `purchase_order_query.py:483-503` | **金额三口径并存**：数量列/打印 `ceil`，金额/导出 2 位小数。qty=10/5‰/¥100 → 11 vs 1005.00 vs 10.05，每行差 95 元 | **业务裁定**：若按整数下单（数量列权威）→ 金额与导出改 `price×ceil`；若计价数量权威 → 数量列不 ceil。三处必须同一函数 |
| H6 | 迁移 100-103 发布顺序 | 103 `DROP COLUMN stock_in.is_deleted`；旧进程代码 7 处引用该列 → 先迁移后重启 = 备货/批次查询 500。生产现停 099，部署流程不跑 alembic | **先发代码+重启，再单独窗口跑 100-103**；103 跑前确认 `SELECT count(*) FROM stock_in WHERE is_deleted IS TRUE` = 0 |
| H7 | 生产 venv Pillow | 13.0.0 已热替换磁盘但进程内存仍 12.3.0（8 条 CVE 在跑），4 个 `.pyd` 靠改名绕过 | 合并后单独窗口干净重启 + 图片链路探针（缩略图/PDF/GIF/TIFF/EPS），预留回滚 |
| H8 | `auxiliary.py:476` vs `:504` | 批量入库顶层 `success` 硬编码 True（service 层 all_success 修复被端点覆盖），与出库分支口径不一致 | 入库分支对齐出库的 `all(...)` 写法 |
| H9 | `49fae2e5` requirements | aiohttp 只升测试档，`base.txt` 无 aiohttp → 生产 3 条 CVE 未修 | 确认生产 venv aiohttp 来源（传递依赖），在对应档锚定并重建 venv，pip-audit 复验 |
| H10 | `schemas.py:108-125` + `FactorySummaryEditItem` | 行金额校验用加放前数量（损耗率 1000‰ 时实际写库值超校验 2 倍 → 仍 500）；工厂汇总编辑 quantity/loss_rate **无任何 ge/le** | 校验改用加放后数量；`FactorySummaryEditItem` 补边界；`_recalc_item_total_price` 加上限断言转 400 |
| H11 | `bom_service.py:197` vs `product_routes.py:233` | BOM 负数 `_non_negative_decimal` 抛 ValueError，端点只捕 SQLAlchemyError/RuntimeError → 负数用量变 500 且无日志 | 端点补 `except ValueError → 400` |
| H12 | `production_summary_service.py:116/281` 等 5 个 xlsx 写点 | Excel 公式注入清洗未全覆盖：`_sanitize_excel_value` 只接了 report_exporter 与采购打印（fec51384/46d9533d）；production_summary/finished_stock/production_plan/daily_production/plan_utils 的 worker_name/remark/客户名直入 `ws.append`（存量，非本批引入） | 清洗下沉到统一 xlsx 写出 helper |
| H13 | `scripts/reset_admin_password.py:49` 等 5 个脚本 | 危险写护栏未统一：`migrate_password_hashes.py:196`、`perf_add_indexes.py`、`cleanup_duplicate_purchase_orders.py:116`、`backfill_production_stock_20261006.py:111` 无 `require_prod_write_consent` 直写生产库；`test_write_guard_wiring.py:34-38` 是源码字符串断言，不证明护栏先于写库执行 | 5 个脚本补护栏；护栏测试改行为断言 |

### 🟡 中（不阻塞，排期处置）

| # | 位置 | 问题 |
|---|------|------|
| M1 | `migrations/...102` NOT VALID CHECK | 存量脏值行迁移后无法 UPDATE；无人 VALIDATE。先跑只读探查 SQL（见 §5 A6）再定 |
| M2 | `stock_inventory_service.py:386-394` | `get_inventory` per_page=100000 静默截断且丢弃 total_items → 超 10 万行时计划少算库存 |
| M3 | `tests/qa/test_forms.py:186-190` | 备份鉴权断言空断言（无 Redis 恒 401，闸门删了也绿）；合法令牌 200 分支零覆盖 |
| M4 | `check-api-alignment.mjs` | 门禁不比对后端 schema→openapi.json，快照漂移无声复发（#98 后靠 D 批 #108 手工补） |
| M5 | `l2_architecture.py:203-210` | core→services 整体摘出禁止清单：从"误报"滑向"漏报"，新增越层不再被发现 |
| M6 | `frontend-vite/scripts/check-mobile-dto.mjs:52-66` | 派生判据逐行判 `{`，多行写法完全放行；`dtoDerivedLock` 只锁 2/~70 类型 |
| M7 | `migrations/destructive_ddl_baseline.json` | 破坏性 DDL 棘线不在 pre-commit 守卫范围，可同提交自证上调；扫描器对 f-string 盲 |
| M8 | `.githooks/pre-commit:300-303` | ruff 全败 `return 0` fail-open；坏 venv 回落系统 python 会让 pip_audit 扫全机 |
| M9 | `ci-cd.yml:263-270` | review packet 无 `continue-on-error`（仅 PR 事件，本次合并不触发；未来 PR 恒红风险） |
| M10 | `sfcVModelConstReactive.test.ts:84` | 预筛漏无参 `v-model="x"` 形态，该形态改动可穿门禁（当前全仓 0 命中，潜伏） |
| M11 | `requirements` / 采购负数 | ① `purchase_order_item` 历史负数行再保存会 422（需只读确认）；② `purchase_plan_queries.py:175-180` 去掉 500 上限后大客户全量进内存 |
| M12 | `190808a5` hook 旁路 | "无 exit code + 出现 modified → 判并发误判"旁路可能被超时/崩溃的 pre-commit 触发，降级为仅 ruff |
| M13 | 备份加密 KEY 回退不对称 | 加密链认 PASSWORD→KEY（crypto.py:95-105），恢复链只认 PASSWORD（restore.py:735-745、_deps.py:147-161）——只配 KEY 的部署自己解不开自己的备份（EncryptedBackupError，fail-closed 非静默明文） | 
| M14 | `.env.production` 疑点（已澄清） | sec-audit 发现其 `APP_ENV=development`；主理人核实全仓无任何加载逻辑引用它（config.py:131 注释自证漂移），根 `.env` 是唯一权威。保留维护窗口只读确认：运行用户跑 `python -c "from fastapi_app.core.config import settings; print(settings.is_production)"`。另确认 `BACKUP_ENCRYPTION_ENABLED=false` = 当前生产备份未加密，运维需认账 |
| M15 | `--no-verify` 流程纪律 | 本批 3 个提交（cd536197/aa383cc1/7743c95a）用了 --no-verify（产物独立复扫无泄漏）；门禁可绕性已被实证两次，应以 CI quality_gate 为权威门禁并流程上禁止 --no-verify |

### 🟢 低（记录在案）
- `48aaec8c` 孤儿图片删除用单槽位登记，两行引用同 key 会误删已提交的图；
- `ea14afd4` bundle 410 时前端 `getExportChunk` 无调用方也无 410 处理（将来接分片下载必须实现）；
- `ddaf8177` `BACKUP_ENCRYPTION_KEY` 新回退：更安全但运维需知情（部分原明文导出会变密文包）；
- `f19f3d8a` buster 哈希行尾归一化未重生成快照（CRLF 检出会假红）；
- 注释漂移：`CustomerOrderView.recordsMerged.test.ts:8`、`d44` 测试路径写错、`PROJECT_MANUAL.md:175` 的 `--yes` 语义说明。

---

## 4. 合并执行方案（用户收尾未提交改动后执行）

**当前事实**：`erp/main`(946f2a2f) 是分支 merge-base → 合并属**快进**，无冲突。但两处未提交改动会阻挡：
- 当前工作树 16 个已改文件（12 个被 132 提交触及）+ 28 个未跟踪（8 个真实源文件按用户决定**不纳入**）；
- `main` 工作树（`C:/Users/Administrator/AppData/Local/Temp/erp_main_check`）`tests/qa/test_forms.py` 有未提交改动（也被 132 提交触及）。

**步骤（待用户叫执行时）**：
1. 备份：`git stash create`（只读对象）+ 两处改动复制到 `backups/merge-audit-20261021/`；
2. main 工作树处理 `test_forms.py`（用户收尾后按其状态决定：提交/还原）；
3. 在 main 工作树执行 `git merge --ff-only erp/fix/audit-2026-10-18`；
4. `git push erp main`；
5. **发布顺序纪律**：重启 `erp-prod`/`erp-arq`（加载新代码）→ 确认健康 → 单独窗口人工跑 `alembic upgrade head`（100-103，含 103 DROP COLUMN）→ 跑迁移漂移探针（`b1c0bb48` 交付的只读命令）确认无漂移。
6. 回滚预案：迁移前 `pg_dump` 全量（`restore_db.py` 已有 fail-closed 前置备份）；代码回滚 = `nssm stop erp-prod` → 分支 worktree 检出 946f2a2f → 重启；103 已执行后回滚需 `downgrade`（列历史值不可恢复，跑前必须确认 is_deleted 全 FALSE）。

---

## 5. 行动清单

| # | 行动 | 负责方 | 紧急度 | 时点 |
|---|------|--------|--------|------|
| A1 | 收尾两处未提交改动（main 工作树 test_forms.py + 当前工作树 16 改文件/8 新文件） | 用户 | P0 | 合并前 |
| A2 | ~~提权会话补跑 pytest~~ 已完成（聚焦 7 文件 195 passed）；全量 4353 条在发布窗口补跑 | 工程 | P1 | 发布窗口 |
| A3 | 修复 esbuild.exe 完整性：`icacls "...@esbuild\win32-x64\esbuild.exe" /setintegritylevel Medium`（建议连 node_modules 全树） | 工程 | P0 | 合并前 |
| A4 | 执行合并（§4 步骤 1-4） | 工程 | P0 | A1 完成后 |
| A5 | 发布窗口：重启 → 人工迁移 100-103 → 漂移探针 | 工程 | P0 | 合并后 |
| A6 | 只读探查：`SELECT status,count(*) FROM purchase_order GROUP BY 1`；`SELECT count(*) FROM purchase_order_item WHERE quantity<0 OR unit_price<0` | 用户 | P0 | 迁移前 |
| A7 | 修 R1 幂等键 + H1 导入闸门 + H2/H3 备份两处 + H4/H8 | 后端 | P0 | 合并后第一批修复 |
| A8 | 业务裁定 H5 金额口径（ceil vs 2 位小数），三处收敛到同一函数 | 业务+工程 | P1 | 一周内 |
| A9 | H6/H7/H9 依赖与迁移纪律 + M1-M12 排期 | 工程 | P1 | 排期 |

---

## 6. ⚠️ 待完善 / 已知局限

- **动态测试已补齐**：vitest 1313 用例 + 提权 pytest 195 用例全绿；但均为聚焦子集，**全量 4353 条 pytest 回归**建议在合并发布窗口补跑一次（同样一次 UAC，约 20-30 分钟）。
- vitest 打印完全部结果后挂起不退出（疑似 esbuild 完整性标签次生效应），数字来自逐文件日志而非官方 summary 行；修完 `icacls ... esbuild.exe /setintegritylevel Medium` 后应复跑拿官方汇总。
- 三个导入端点的实际风险取决于授权面：若生产上**不存在**"厂绑定 + 持 batch_import 权限"的用户组合，H1 可降为 P1（需连库核实 `SELECT count(*) FROM "user" WHERE factory IS NOT NULL AND factory != '' AND id IN (SELECT user_id FROM user_permission WHERE permission='batch_import')`）。
- `/batch/import-orders`（batch.py:76→80）建单无订单域闸门，工厂归属经 product 推导——是否刻意放开需人工确认（sec-audit ⚠️）。
- DTO 派生化等价性结论靠人工逐字段比对（10 条抽查 + 14 处可空性全查），非门禁保证。
- 主理人独立复核覆盖：CI advisory 步骤、policy_service 假成功、restore_core 判定、auxiliary 双分支口径、金额三口径（读码确认）、幂等键升级链。未复核项均已在成员报告中附原始证据行号。

---

## 7. 📚 成员产出索引

- reviewer-core（A 批 + 跨批次回退核查）：本会话消息存档（132 提交中 #1-33 裁决表、10 处闸门调用点 grep、幂等键升级链、A 批零回退证明、迁移 102 探查 SQL）
- reviewer-audit（B 批）：#34-66 裁决表、18 符号删除残留 grep、`__all__`/mypy 白名单静态校验、备份域三处 🟠
- reviewer-data（C 批）：#67-99 裁决表、金额手算 6 组边界、迁移链 alembic 实跑（单 head/143 revision）、迁移清单与生产 alembic=099 实证（`logs/_fix_2026-10-18/VERIFIED_PENDING.md` §六）
- reviewer-frontend（D 批）：#100-132 裁决表、DTO 派生化 10 条逐字段抽查明细、14 处可空性全查、门禁可绕过面 4 项
- qa-gate：16 项门禁全 PASS 实测、type-check 15 条归因（`git cat-file -e` 逐文件验证）、esbuild Low IL 与 `.env` ACL 根因定位
- sec-audit：OWASP Top10 全表 + STRIDE + 写端点鉴权盘点表（16 组）、密钥面/frp 独立复扫清白、Excel 注入 5 写点、危险写护栏 5 脚本缺口、KEY 回退不对称、3 个 --no-verify 提交产物复扫
- 主理人独立复核：CI advisory 步骤（降级 🟡）、policy_service 假成功、restore_core 判定、auxiliary 双分支口径、金额三口径、幂等键升级链、**导入洞为 main 存量**（main 闸门调用点=0）、`.env.production` 为死配置

> 本报告由软件工坊 AI 协作生成，关键决策请由工程负责人复核。

---

## 8. 执行结果（2026-10-21 22:20 追加）

**审查发现已处置、合并已执行。**

| 项 | 结果 |
|----|------|
| 中断会话遗留修复批（16 文件，含 H4/H8） | 已提交 `252b7097`（钩子全过，pre-commit patch 正常恢复） |
| 审查代码级修复（H1/H2/H3/M9 + 报告入库） | 已提交 `93d3216a` |
| H11（BOM 负数 500） | **误报**：`db_transaction` 已把 ValueError 映射 400（exceptions.py:201-203），未修 |
| R1（幂等键） | 未改——`_import_idem_key` docstring 载明业务已确认口径，留业务裁定 |
| 快进阻挡 | main 工作树 test_forms.py 的未提交改动与分支 913212cd **逐字相同**，备份后放弃（backups/merge-audit-20261021/） |
| 合并 | `0c509bbf → 97d30cd8`：快进 134 提交 + 吸收远端 bot 锁刷新 `0f90ea25`（合并提交 `97d30cd8`，无冲突，锁版本核验无回退：Pillow 13.0.0 / aiohttp 3.14.4 / virtualenv .12 / certifi .19 / websockets 17.3） |
| 推送 | `0f90ea25..97d30cd8 main -> main` 到 github.com:qike1132/erp.git ✅ |
| 验证 | 提权 pytest 聚焦 147 passed；quality_gate 16 项全 PASS（function_length 经抽取 `_allocate_and_write_stockout_rows` 回到基线）；ruff 0 |

**⚠️ 尚未执行的发布步骤（生产仍跑旧代码）**：
1. 重启 `erp-prod` / `erp-arq` 加载新代码（同时会第一次真正加载 Pillow 13.0.0——预留回滚窗口）；
2. 健康确认后，单独窗口人工跑 `alembic upgrade head`（100-103；103 是 DROP COLUMN，跑前确认 `SELECT count(*) FROM stock_in WHERE is_deleted IS TRUE` = 0）；
3. 跑迁移漂移探针确认 schema 与代码一致；
4. 发布窗口补跑全量 pytest（4353 条）。
