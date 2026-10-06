# 迭代审核报告 Round-3 —— 2026-10-05（审核时间约 20:29–21:10）

> 前两轮（available-shipment 修复 / 负库存回滚）的审核见 [iteration-review-2026-10-05.md](iteration-review-2026-10-05.md)，本文不重复。
> Round-3 范围：提交 f2d72fd1（出货记录查询修复）+ 生产正在运行的**全部未提交/未跟踪改动**（后端 NSSM 直接运行工作树；前端 dist 20:07 由并行会话重建）。
> 方法：基于最新代码逐项核对；生产库只读查询取证；vitest / quality_gate / alembic / pytest 实测。

## 审核结论总览

| 项 | 结论 |
|---|---|
| f2d72fd1 出货记录修复 | ✅ 通过（自审无新增问题；线上已验证） |
| 退货管理模块（并行会话，整体未跟踪） | 🔴 **1 个 P0：模型与库结构脱节，缺迁移**；🟡 1 个 P1 权限错配 |
| 未提交后端 diff（备份补跑 / 锁参数 / 导航映射） | ✅ 语义正确，均配测试 |
| 门禁 | vitest 1155 全绿、quality_gate PASS、alembic 单 head、permission 表已 seed |

## 🔴 P0-1 StockReturn.status 列：模型已加、库没有、迁移缺失 —— 退货模块当前在生产上必 500

证据链（全部当晚实测）：

1. `fastapi_app/shared_models/stock_return.py`（未提交改动，20:28:05）新增 `status: Mapped[str] ... nullable=False, default='active'`；
2. 生产库 `stock_return` 表实测**无 status 列**（information_schema，共 11 列）；
3. `migrations/versions/` 无任何为 stock_return 加列的迁移（grep 实证）；`alembic heads` 实测单 head = 069（仅权限 seed）；
4. 后端 20:29:22 / 20:30:26 两度全栈重启（logs/prod_runner.json），**晚于模型修改** → 运行中的 worker 已加载新模型。

影响：任何触碰 StockReturn ORM 的路径（`GET /stock-returns/list`、`POST /stock-returns/create`、`DELETE /stock-returns/{id}`=软取消）均带 status 列 → `UndefinedColumn` → 500。具体写点：`cancel_stockreturn_core` 读 `stockreturn.status`（129 行）与写 `= 'cancelled'`（161 行）；create 路径 INSERT 因模型 default 带上 status 列。`GET /stock-returns/stockout-options` 只查 StockOut，不受影响。

⚠️ 为什么 pytest 全绿却必炸：测试库由模型 metadata `create_all` 建表（**有** status 列），生产库由迁移演进（**无** status 列）——流程测试对这种模型/迁移漂移天然免疫。这正是需要「模型列 ⊆ 库列」守卫的原因。

修复建议（归属：退货模块工作流，二选一）：

1. 新增迁移：`ALTER TABLE stock_return ADD COLUMN status VARCHAR(20) NOT NULL DEFAULT 'active'`，downgrade 对称删列（模块已按 active/cancelled 语义开发，删列方案不现实，迁移是正解）；
2. 补一条「shared_models 表列 ⊆ 生产库列」的结构守卫测试，防再犯。

## 🟡 P1-1 useStockReturn.openStandalone 权限错配：违反模块自身的最小授权设计

- `frontend-vite/src/views/stock-return/composables/useStockReturn.ts:152` 调 `stockApi.stockouts(...)` = `/stock/out/list`，要求 `stockout_manage` 权限；
- 但模块设计三处一致要求最小授权：迁移 069 docstring、`stock_return.py:38-40`（"不应被迫持有 stockout_manage（否则迁移 069 的最小授权模型不成立）"）、`api/stockReturn.ts` 注释（"勿用 /stock/out/list——那是出库管理权限"）；
- 后端已备好专用端点 `GET /stock-returns/stockout-options`（鉴权 `stock_return_manage`，同源数据含 returned_quantity）。

影响：只授退货权限、未授出库管理的用户点"页内发起退货"→ 403 → 出货单下拉恒空（管理员全权限，不会察觉）。

修复：`openStandalone` 改调 `stockReturnApi.stockoutOptions()`；返回的 StockoutCandidate 与 `onStockoutPicked` 所需字段（id/stockout_no/customer/product_name/product/quantity/returned_quantity）完全兼容，只需把 `stockoutOptions` 的类型从 `StockOutRecord[]` 换成 `StockoutCandidate[]`。归属：退货模块工作流（文件属未跟踪模块且当日被多次编辑，审核会话不抢改）。

注：Round-3 会话已将该处的**响应解析**从 `resp.stockouts ?? resp.items` 修为 `resp.data ?? []` 并随 17:35/20:07 两次构建上线——解析与权限是两个独立缺陷，后者仍开放。

## 🟡 P1-2 pytest 基线红：守卫测试期望表未跟上 delete→cancel 改名

- `pytest -q`（全量 16:52）：**1 failed / 3884 passed / 181 skipped**；
- 失败项：`test_stock_optimistic_lock_unification.py::test_every_write_point_calls_unified_entry[stock_return_service.py]`；
- 原因：`_EXPECTED_CALL_SITES` 仍期望 `delete_stockreturn_core`，而服务已改名为 `cancel_stockreturn_core`（语义同步从物理删除改为软取消 status='cancelled'；端点 import 也已在 20:36:21 同步改名——审核中途亲眼见其从 delete_stockreturn 演进为 cancel_stockreturn）；
- 统一写入口调用本身两处齐全（create 109 行 / cancel 150 行），守卫只是函数名过期；
- 修复：`test_stock_optimistic_lock_unification.py` 的 `_EXPECTED_CALL_SITES["fastapi_app/services/stock_return_service.py"]` 键名 `delete_stockreturn_core` → `cancel_stockreturn_core`（一行，归属退货模块工作流）。

## 🟡 P2-1 大面积"已上线未提交"（流程风险，非代码缺陷）

生产 = 工作树：整个退货模块（前后端 + 迁移 069 + 两个测试文件）untracked；router.py / nav_context.py / schedule_service.py / auxiliary.py / inventory_service.py / stock_inventory_service.py / StockOutRecords.vue 等未提交。

风险：任何会话的 `git checkout/clean` 或误操作会静默丢失生产正在运行的代码；git 历史缺失使"可回滚"名存实亡。建议退货模块稳定后按内聚分批提交（迁移+模型+服务+端点 / 前端模块 / 行内退货入口）。

## 其余未提交后端 diff 逐项结论（均 ✅）

| 文件 | 结论 |
|---|---|
| `inventory_service.py` lock_orders 参数 | 与 Round-1 审核一致：默认加锁（写路径安全），仅展示端点显式关锁 |
| `auxiliary.py` available-shipment lock_orders=False | 配套改动，注释准确（行锁与超额校验由提交事务兜底） |
| `backup/schedule_service.py` STALE_RUNNING_AFTER=2h | 补跑语义正确：仅 running 超阈值放行，failed/success 是真实终态不补跑；test_backup_m2 新增 TestStaleRunningRefire 双向覆盖 |
| `core/nav_context.py` stock_return_view 展开 | 与 069 的 manage⊇view 命名继承设计一致，前端侧栏"任一命中"所需 |
| `api/v1/router.py` 挂载 /stock-returns | 前缀、鉴权依赖与既有模式一致；`alembic heads` 单 head、`permission` 表已 seed 两行（view sort=6 / manage sort=7） |
| `stock_inventory_service.py` get_stockreturns 增筛选 | escape_like 防通配符注入、日期解析容错，与 get_stockouts 同范式 |
| `schemas/stock_return.py` | 字段校验完备（gt=0 / 长度上限 / 日期格式），业务校验留 service 层——分层正确 |
| 前端 router/index.ts + api/index.ts | /stock-return 路由与 stockReturnApi 导出接线完整 |

## f2d72fd1 自审

- 解析修复（`res.data ?? []`）以后端 `StockListResponse` 实证正确；线上 20:07 重建后的 dist 仍含修复（chunk `data??[]` 命中、live 200）。
- 🟢 存量类型债（本次未动、无消费方）：`StockOutRecord.status`/`.deducted` 为幽灵字段——后端 `/stock/out/list` 从不发送、前端无读取，建议后续清理。
- 全仓残留排查：无其他 `res.stockouts ??` 式坏解析（dashboard 命中为 KPI 字段名，无关）。

## 回归与门禁记录

- vitest：126 文件 / 1155 用例全绿（17:57）。
- quality_gate.py：PASS，pip-audit 0 漏洞（生产 venv 口径）。
- alembic：单 head 069；DB alembic_version 一致；权限 seed 在位。
- pytest 全量：见文末补记。

## pytest 补记

全量 `pytest -q`（后台运行 16:52，20:29 启动）：**1 failed / 3884 passed / 181 skipped**。
唯一失败即上文 P1-2（守卫测试函数名过期），其余含退货流程测试 test_stock_return_flow/api 全绿——但如 P0-1 所述，测试库建表方式使其无法暴露生产库缺列问题。
活体探针：`POST /api/v1/auth/login`（错误凭据）返回 401 JSON → app 引用链完整、正常服务。
