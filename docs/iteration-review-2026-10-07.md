# 迭代审核报告（2026-10-07）

> 审核对象：本工作区全部未提交改动的**本次会话部分**——报表流水接管记录查询 TAB、
> order_edit/order_delete 独立权限点（迁移 075）、/user 权限弹窗级联修复。
> 并行会话的库存日志模块（InventoryLogsTab、迁移 073/074、stock.py 库存端点）属另一会话，不在本轮结论内（其 stock_view 放宽仅在「观察」节提及）。
> 审核方式：基于最新工作区代码逐文件复核（OCR CLI 因本机未配置 LLM 端点未能运行，待配置后可补跑）。
> 基线：前端 vitest/type-check/lint 全绿；后端对齐测试 82 条 + order/stock 路由测试 61 条全过；ruff/quality_gate 过；迁移 075 已应用生产库；线上 hash 已验证。

## 结论：Approve（无 Critical / High）

权限扩散面逐端点核对无削弱：所有写端点均为「原码 + 新码」的 require_any_permission
（向后兼容），新码经 NO_MANAGE_INHERIT 阻断自动继承，对齐回归测试新增 6 条目锁定。
聚合行还原、缓存失效链、弹窗状态收尾均核到位。

## 已核实的关键面（证据）

1. **权限无绕过**：PUT /orders/edit、/orders/deduct → any(order_manage, order_edit)；
   DELETE /orders/delete → any(order_manage, order_delete)；GET /orders/records →
   any(order_manage, order_edit, order_delete)；stock in edit/delete → 原码 + order_edit/order_delete
   （fastapi_app/api/v1/endpoints/order.py:203/301/343/473，stock.py:115/154）。
   工厂隔离在 get_unified_records 内部强制，不因新码放宽。
2. **继承阻断**：user.py NO_MANAGE_INHERIT += order_edit/order_delete——持有「订单流水」
   或「订单列表」不会自动获得操作码，必须显式勾选（沿 outsource_ship/receive 先例）。
3. **缓存一致性**：迁移后的 useOrderDelete/useOrderDetailEdit/useStockinEdit 均保留
   invalidateOrderDerivedQueries；useReportRowActions.refreshAfterWrite 失效
   ['report-data'] 前缀；后端 REPORT 缓存域由写路径级联失效（既有机制）。
4. **视图无残留**：CustomerOrderView / StockOutView 对已删组件零引用（grep 空），
   type-check 背书。
5. **迁移 075**：常量插值 + NOT EXISTS 幂等守卫（nosec 标注合理）；downgrade 先清
   user_permission 关联再删权限行；sort_order 从父行派生无碰撞。

## 发现与处置

### Medium

- **M1 注释过期（已修）**：stock.py:114/153 与 user.py 的注释仍写「订单列表→编辑/删除」，
  迁移 075 父项已按用户澄清改挂「订单流水」(report_manage)。已就地修正；ruff 复核过。
- **M2 级联勾选修复无测试锁定**：togglePermNode 的三条新语义（子⇒父、取消子留父、
  取消父清子）没有 vitest 覆盖，回归风险靠人肉。建议后续为 useUserManagement 补
  纯函数级用例。
- **M3 pytest 存量失败（遗留，非本迭代引入）**：退货域 4 条（_fake_create 的
  operator_id 签名、delete_stockreturn_core 命名等）——上轮已报告，属并行会话域，
  仍未处理。

### Low / 观察

- **工厂绑定用户的必失败路径**：/reports/*-logs 不做工厂隔离、/orders/records 强制
  本厂过滤——工厂绑定用户在报表页看到他厂聚合行时，点操作还原必落
  「未能找到该组对应的明细记录」toast（useReportRowActions docstring 已自知）。
  后续可考虑按钮渲染时按用户工厂预判。
- **缺失单号补查为串行 await（N+1）**：主查询漏单时逐单号补查，组大时慢；现实组规模小，可接受。
- **/orders/records per_page=500 截断**：组内 >500 单理论可截断，已有逐号补查兜底。
- **非超管的「编辑」走审批流**：order_service.update_order 对非超管分流审批（既有行为），
  order_edit 持有者的编辑结果可能是「提交审批」而非直接生效——验收时按此预期。
- **UnifiedRecord→OrderRecord 的 as unknown as**：棘轮计数 39/40 仍绿；后续可给
  OrderRecord 补索引签名消除。
- **级联修复影响所有父子组**：批次号/湖北订单/外发组的勾选行为同步变化（子⇒父），
  语义为「操作蕴含查看」，与后端继承阻断一致；管理员如依赖旧行为需知晓。

### OCR 未运行说明

`ocr review` 因本机无 LLM 端点配置失败（OCR_LLM_URL/ANTHROPIC_* 均未设置）。
配置 `ocr config provider` 后可对同一工作区补跑机器审核；本报告为人工逐文件复核结论。
