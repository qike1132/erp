---
design_type: feature
created_at: 2026-09-23
---

# 外发发货单：批量发货合并成一单

## Intent Contract

```
intent: 批量发货时把选中的多个 SKU（跨订单、跨客户）合并生成一张发货单，order_id/customer 置空。
constraints:
  - 不破坏现有按订单批量发货端点 POST /outsource/shipments/batch 及单订单 create_shipment
  - 工序发货复用既有 ship_order_process（行锁 / 数量校验 / 流水）不变
  - 发货单明细行仍保留 process_id，order_qty 口径不变
  - 无数据库 schema 变更
success_criteria:
  - 一次提交跨订单 / 跨客户多个 SKU 只落库一张 OutsourceShipment，order_id 与 customer 均为 None
  - 通知贝乐收货账号仅一条，且 content 中省略 customer 字段
  - 前端结果态显示 1 张发货单，底栏 / 确认态文案一致（不再按订单计数）
  - 后端与前端回归测试全部通过
risk_level: medium
```

## Verification Contract

```
verify_steps:
  - run tests: pytest fastapi_app/tests/services/test_outsource_shipment.py
  - run tests: npx vitest run src/test/OutsourceShipDialog.test.ts
  - check: 新增 create_merged_shipment 用例断言合并单 order_id/customer 为 None、明细数量正确、通知 content 无 customer
  - confirm: 前端提交 payload 断言为平铺 items（不再按订单分组），确认态与结果态文案为「1 张发货单」
```

## Governance Contract

```
approval_gates:
  - 设计批准（本步）
  - 实现完成后 code-review（HOTL）
rollback: git revert 单次提交；无 schema 变更，无需迁移回滚
ownership: 外发发货单模块维护者
```

## Scope

| 范围 | 内容 |
| --- | --- |
| 改后端 | `_shipments.py` 新增 `create_merged_shipment`；`schemas/outsource.py` 新增 `ShipmentMergeCreate`；`api/v1/endpoints/outsource.py` 新增 `POST /shipments/merged` |
| 改前端 | `api/outsource.ts` 新增 `createMergedShipment`；`OutsourceShipDialog.vue` 提交改平铺 + 文案；`useShipTotals.ts` 涉及订单口径收敛为「1 单」 |
| 不动 | `/shipments/batch`、`/shipments`（单订单）、模型 / 迁移、`OutsourceShipResultView` 结构 |
| 测试 | 后端新增合并单用例；前端更新 payload / 文案断言 |

## Decisions

| # | 决策 | 选择 | 备选（弃用） |
| --- | --- | --- | --- |
| 1 | 合并单如何生成 | 新增 `create_merged_shipment`（平铺 items，不校验订单归属） | 复用 create_shipment 改造 order_id 可选 |
| 2 | 端点形态 | `POST /outsource/shipments/merged`，响应单张 `ShipmentResponse` | 复用 batch 加 merge 开关 |
| 3 | 通知 | 复用 `_dispatch_shipment_shipped_notification`，customer 传 None 且 content 省略 customer 字段 | 新增独立通知分支 |
| 4 | 前端提交 | submit 平铺 splitQty 结果，一次调用新端点 | 保留按订单分组 |

## Surface

- **API**：新增 `POST /outsource/shipments/merged`，请求体 `{ items: [{ process_id, quantity }] }`，响应 `ShipmentResponse`（单张含 items）。权限点 `outsource_ship`。
- **存储**：无 schema 变更；`outsource_shipment.order_id` 与 `customer` 置空，明细行照常写 `outsource_shipment_item`。
- **前端**：`outsourceApi.createMergedShipment`；`OutsourceShipDialog.vue` 提交改为平铺调用，`useShipTotals` 的「涉及订单数」在合并模式下固定为 1；结果态与确认态文案由「N 单」改为「1 张发货单」。

## Risks & Open Questions

- **跨客户合并的合规性**：确认收货仍由贝乐对整张单闭环，跨客户不区分；如需按客户拆分后续再议。
- **通知省略 customer**：合并单通知 content 不携带 customer，贝乐端卡片不展示客户名，属于预期行为。
