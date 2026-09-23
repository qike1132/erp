---
intent: 批量发货时把选中的多个 SKU（跨订单、跨客户）合并生成一张发货单，order_id/customer 置空。
success_criteria: 一次提交跨订单 / 跨客户多个 SKU 只落库一张 OutsourceShipment，order_id 与 customer 均为 None；通知贝乐收货账号仅一条且 content 省略 customer；前端结果态显示 1 张发货单、底栏 / 确认态文案一致；后端与前端回归测试全部通过。
risk_level: medium
auto_approve: true
---

## Steps

- [x] **Step 1: 后端服务层实现合并发货与通知省略客户名**
action: 编辑 `fastapi_app/services/outsource/_shipments.py`。(1) 修改 `_dispatch_shipment_shipped_notification`：构造 content 时，仅当 customer 非空才写入 'customer' 键（现有 create_shipment 的 customer 恒有值，行为不变）。(2) 新增 `create_merged_shipment(db, items, username=None)`：与 create_shipment 同构但**不加载订单、不校验订单归属**；`order_id=None`、`customer=None`；shipment_no 用 `generate_shipment_number`；循环 items 复用 `ship_order_process(db, process_id, quantity, username)`（行锁 + 数量校验 + 流水），逐条写 `OutsourceShipmentItem`（process_id/product_id/product_name/process_type/shipped_quantity/received_quantity=0），构造 notify_items；通知调用 `_dispatch_shipment_shipped_notification(db, shipment_no, None, None, notify_items)` 且失败仅记日志；最后 selectinload 明细后 `_serialize_shipment(loaded, include_items=True)` 返回。
loop: false
max_iterations: 1
verify: python -c "import ast; ast.parse(open('fastapi_app/services/outsource/_shipments.py', encoding='utf-8').read())"

- [x] **Step 2: 后端新增合并发货 schema 与端点**
action: (1) 编辑 `fastapi_app/schemas/outsource.py`，新增 `class ShipmentMergeCreate(BaseModel)`：`items: list[ShipmentShipItem] = Field(..., min_length=1, max_length=200, description="合并发货明细（跨订单/跨客户）")`，置于 `ShipmentBatchResponse` 之前。(2) 编辑 `fastapi_app/api/v1/endpoints/outsource.py`：在 import 列表（`schemas.outsource` 段）加入 `ShipmentMergeCreate`；在 `POST /shipments` 之后新增 `POST /shipments/merged`，`response_model=ShipmentResponse`，依赖 `require_permission("outsource_ship")`，事务内调 `outsource_service.create_merged_shipment(db, [(i.process_id, i.quantity) for i in data.items], username=user.username)` 并 `return ShipmentResponse(**result)`。确认 `outsource_service`（`fastapi_app/services/outsource_service.py`）导出 `create_merged_shipment`（在 `_shipments` 的 re-export 段新增）。
loop: false
max_iterations: 1
verify: python -c "import ast; ast.parse(open('fastapi_app/api/v1/endpoints/outsource.py', encoding='utf-8').read()); ast.parse(open('fastapi_app/schemas/outsource.py', encoding='utf-8').read())"

- [x] **Step 3: 后端新增合并发货测试并跑通**
action: 编辑 `fastapi_app/tests/services/test_outsource_shipment.py`：在 import 段加入 `create_merged_shipment`；新增 `test_create_merged_shipment_across_orders(db)`——复用 `_seed` 后再种第二个订单（不同客户 order2/item2/process2），调用 `create_merged_shipment(db, [(process.id, 5), (process2.id, 8)], username='shipper')`，断言：返回 `order_id is None`、`customer is None`、`item_count == 2`、`total_shipped == 13`、明细 process_type 集合为 `{'电绣', '转印'}`；`OutsourceShipment` 落库仅 1 行且 order_id/customer 均为 None；两道工序 shipped_quantity 分别为 5/8；`Notification` 仅 1 条且 `json.loads(content)` 不含 'customer' 键、type 为 'outsource_shipment_shipped'。
loop: until pytest fastapi_app/tests/services/test_outsource_shipment.py exits 0
max_iterations: 4
verify: pytest fastapi_app/tests/services/test_outsource_shipment.py

- [x] **Step 4: 前端 API 层新增合并发货方法**
action: 编辑 `frontend-vite/src/api/outsource.ts`：在 `createShipmentsBatch` 之后新增 `createMergedShipment: (items: { process_id: number; quantity: number }[]) => post<Shipment>('/outsource/shipments/merged', { items })`，并加一行注释「合并发货（跨订单/跨客户生成一张发货单）」。
loop: false
max_iterations: 1
verify: npm run type-check

- [x] **Step 5: 前端提交改平铺 + 文案统一为一张发货单**
action: 编辑 `frontend-vite/src/views/outsource/components/OutsourceShipDialog.vue`：(1) `submit()` 里把「按 order_id 分组组装 payloadMap」替换为平铺——遍历 `checkedRows` 的 `splitQty(r)` 结果，收集 `{ process_id: row.process_id, quantity }` 到单个数组 `flatItems`；(2) 提交调用 `outsourceApi.createMergedShipment(flatItems)`，`.then` 中 `result.value = { ok: true, shipments: [res] }`（res 为单张 Shipment）、`toast.success(res.message || '已生成 1 张发货单')`；(3) 模板文案：提交遮罩 `正在生成发货单…（{{ selectedOrderCount }} 单 / {{ shipSum.toLocaleString() }} 件）` 改为 `正在生成发货单…（{{ shipSum.toLocaleString() }} 件）`；确认态 `将按订单生成 {{ selectedOrderCount }} 张发货单` 改为 `将生成 1 张发货单`；底栏 `已选 {{ selectedOrderCount }} 单` 改为 `涉及 {{ selectedOrderCount }} 单`；按钮 `生成发货单（{{ selectedOrderCount }} 单 / {{ shipSum.toLocaleString() }} 件）` 改为 `生成发货单（{{ shipSum.toLocaleString() }} 件）`。不改动 `shipCartModel.ts` 与 `useShipTotals.ts` 逻辑。
loop: false
max_iterations: 1
verify: npm run type-check

- [x] **Step 6: 前端测试更新为合并语义并跑通**
action: 编辑 `frontend-vite/src/test/OutsourceShipDialog.test.ts`：(1) mock 改为 `createMergedShipment: (...args) => createMergedShipmentMock(...args)`（新增 `const createMergedShipmentMock = vi.fn()`，替换原 `createShipmentsBatchMock`）；(2) 所有「按订单分组 payload」断言改为「平铺 items 数组」断言——用例「完整流」期望 `createMergedShipmentMock` 被调用一次、参数为 `[{ process_id: 1, quantity: 50 }, { process_id: 2, quantity: 100 }, { process_id: 3, quantity: 50 }]`；用例「同一 SKU 同一工序跨订单合并」期望 `[{ process_id: 1, quantity: 100 }, { process_id: 2, quantity: 150 }]`；用例「企鹅的订单 6 道工序」期望 `items.length === 6` 且首项 `{ process_id: 1, quantity: 100 }`、其余 quantity 均为 9626；(3) mock 返回值统一为单张 `data: [{ id, shipment_no, order_id: null, customer: null, status: 'shipped', item_count, total_shipped }]`（order_id/customer 置 null），并将确认态/结果态相关断言文案从「N 张发货单」改为「1 张发货单」、确认态断言从「将按订单生成 N 张发货单」改为「将生成 1 张发货单」。
loop: until npx vitest run src/test/OutsourceShipDialog.test.ts exits 0
max_iterations: 4
verify: npx vitest run src/test/OutsourceShipDialog.test.ts

- [x] **Step 7: 全量回归**
action: 分别运行后端外发发货单测试与前端发货弹窗测试，确认全部通过、无既有用例因文案/签名变更被误伤。
loop: false
max_iterations: 1
verify:
  - type: shell
    command: pytest fastapi_app/tests/services/test_outsource_shipment.py
  - type: shell
    command: npx vitest run src/test/OutsourceShipDialog.test.ts
