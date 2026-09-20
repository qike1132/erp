---
intent: 在发货单明细表中新增「订单总数」列，展示该明细行对应工序的订单数量，位置在「发货数量」左侧。
success_criteria: 明细表列序为 #|SKU|工序|订单总数|发货数量|收货数量|未收货；订单总数取 process_id 关联的订单数量；process_id 为空时显示 '-'；既有测试全部通过。
risk_level: low
auto_approve: true
worktree: false
---

## Steps

- [x] **Step 1: 记录改动前基线**
action: 运行 `npx vitest run src/test/OutsourceShipmentDetailDialog.test.ts`，记录当前通过用例数，作为前端回归基线。
loop: false
max_iterations: 1
verify: npx vitest run src/test/OutsourceShipmentDetailDialog.test.ts

- [x] **Step 2: 后端明细序列化补充 order_qty**
action: 编辑 `fastapi_app/services/outsource/_shipments.py`：把 `_serialize_shipment_item(item)` 改造为 `_serialize_shipment_item(item, order_qty=None)`，在返回字典中新增 `'order_qty': order_qty`。改造 `_serialize_shipment(...)`，当 `include_items` 为真时用批量查询出的 `{工序ID: 订单数量}` 映射填充每行 order_qty。
结果: 实际订单数量口径取 `func.coalesce(OrderItem.quantity, Order.quantity)`（与 `_queries.list_shippable_processes` 一致），封装为 `_load_order_qty_map(db, items)` 单条批量查询。
loop: false
max_iterations: 1
verify: python -c "import ast,sys; ast.parse(open(r'd:/erp_system/fastapi_app/services/outsource/_shipments.py',encoding='utf-8').read())"

- [x] **Step 3: 后端响应模型补充 order_qty**
action: 编辑 `fastapi_app/schemas/outsource.py`：在 `ShipmentItemResponse` 中新增字段 `order_qty: int | None = None`。
loop: false
max_iterations: 1
verify: python -c "import ast; ast.parse(open(r'd:/erp_system/fastapi_app/schemas/outsource.py',encoding='utf-8').read())"

- [x] **Step 4: 后端明细接口测试**
action: 在 `fastapi_app/tests/services/test_outsource_shipment.py` 新增 2 个用例：`test_get_shipment_items_include_order_qty`（断言 order_qty 等于订单明细数量 10）、`test_get_shipment_order_qty_none_when_process_deleted`（工序删除后 order_qty 为 None）。
loop: false
max_iterations: 1
verify: python -m pytest fastapi_app/tests/services/test_outsource_shipment.py -q

- [x] **Step 5: 前端类型与明细列**
action: 编辑 `frontend-vite/src/api/outsource.ts` 的 `ShipmentItem` 新增 `order_qty?: number | null`；编辑 `OutsourceShipmentDetailDialog.vue` 在「发货数量」之前插入表头与数据单元格，并新增 `.osdd-order-qty` 弱化样式。
loop: false
max_iterations: 1
verify: npm run type-check

- [x] **Step 6: 前端明细弹窗测试**
action: 新建 `frontend-vite/src/test/OutsourceShipmentDetailDialog.test.ts`，4 个用例覆盖：新列存在且位于「发货数量」左侧、订单总数千分位格式化、order_qty 为 null 显示 `-`、既有列与合计行不受影响。
loop: false
max_iterations: 1
verify: npx vitest run src/test/OutsourceShipmentDetailDialog.test.ts

- [x] **Step 7: 前后端回归修复直到全绿**
action: 运行前端明细测试与后端 shipment 测试，均为全绿（前端 4 passed，后端 8 passed）。
loop: until npx vitest run src/test/OutsourceShipmentDetailDialog.test.ts exits 0
max_iterations: 4
verify: npx vitest run src/test/OutsourceShipmentDetailDialog.test.ts

- [x] **Step 8: 浏览器实测明细弹窗新列**
action: 打开 `http://192.168.0.95:3000/outsource/shipments`，点击首行「明细」打开弹窗。
结果: 表头序列为 `# | SKU | 工序 | 订单总数 | 发货数量 | 收货数量 | 未收货`；首行为 `1 | 王者荣耀 | 电绣 | 999,999 | 500,000 | 0 | 500,000`，第二行 `2 | 王者荣耀 | 转印 | 999,999 | 500,000 | 0 | 500,000`。
备注: 初次实测显示 `-`，根因是后端进程早于代码改动启动（`server_manager.py` 的 `--reload` 未在改动后自动触发）。通过触碰 `main.py` 触发重载后，接口 `/api/v1/outsource/shipments/6` 正确返回 `order_qty: 999999`。
loop: false
max_iterations: 2
verify:
  type: browser
  url: http://192.168.0.95:3000/outsource/shipments
  check: 明细表出现「订单总数」列且位于「发货数量」左侧，数值正确渲染

- [x] **Step 9: 确认发货单列表与收货流程未受影响**
action: 在同一页面确认发货单列表仍正常渲染、表头不含「订单总数」、无 Vite 错误遮罩。
结果: 列表 5 行正常，表头为 `发货时间 | 明细数 | 发货总量 | 状态 | 操作`（无多余新列），`vite-error-overlay` 为 null，Escape 关闭弹窗后列表交互正常。
loop: false
max_iterations: 2
verify:
  type: browser
  url: http://192.168.0.95:3000/outsource/shipments
  check: 列表正常渲染、无多余新列、无构建错误遮罩
