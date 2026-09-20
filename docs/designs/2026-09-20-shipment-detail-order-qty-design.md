---
design_type: feature
created_at: 2026-09-20
---

# 发货单明细：新增「订单总数」列

## Intent Contract

```
intent: 在发货单明细表中新增「订单总数」列，展示该明细行对应工序的订单数量（target_qty），位置在「发货数量」左侧。
constraints:
  - 不改变发货单明细的既有字段与展示（发货数量 / 收货数量 / 未收货）
  - 不改变发货与收货的业务逻辑（ship / receive 流程）
  - 不新增数据库列、不做数据迁移（复用既有 process_id 外键关联）
  - 不改动发货单列表接口（仅明细接口增加字段）
success_criteria:
  - 明细表列序为：# | SKU | 工序 | 订单总数 | 发货数量 | 收货数量 | 未收货
  - 订单总数取该行 process_id 关联的外发工序 target_qty
  - process_id 为空（工序已删除）时该列显示 '-'，不报错
  - 后端明细接口返回 order_qty 字段；既有测试全部通过
risk_level: low
```

## Verification Contract

```
verify_steps:
  - run tests: pytest tests/test_outsource.py -k shipment
  - run tests: npx vitest run src/test/OutsourceShipmentDetailDialog.test.ts
  - check: 明细接口响应中每行含 order_qty，且等于该工序的 target_qty
  - run: npm run type-check（本文件无新增报错）
  - confirm: 浏览器实测明细弹窗出现「订单总数」列，列序正确、数值与待发货面板一致
```

## Governance Contract

```
approval_gates:
  - 设计确认后方可实施（本文件）
  - 浏览器实测结果需回报用户
rollback: git checkout -- fastapi_app/services/outsource/_shipments.py fastapi_app/schemas/outsource.py frontend-vite/src/api/outsource.ts frontend-vite/src/views/outsource/components/OutsourceShipmentDetailDialog.vue
ownership: 前后端外发模块维护者
```

## Scope

| 范围 | 内容 |
|---|---|
| In | 后端：明细序列化增加 order_qty（关联 order_outsource_process 取 target_qty） |
| In | 后端：ShipmentItemResponse 增加 order_qty 字段 |
| In | 前端：明细弹窗新增「订单总数」列 + 类型定义 |
| In | 测试：后端明细接口断言、前端明细弹窗断言 |
| Out | 数据库结构变更与历史数据回填 |
| Out | 发货单列表页（不含 items，无需该字段） |
| Out | 发货 / 收货业务逻辑 |

## Decisions

| # | 决策 | 选择 | 否决的替代方案 |
|---|---|---|---|
| 1 | 取数方式 | 通过 process_id 关联 order_outsource_process 取 target_qty | 新增 order_qty 快照列（需迁移 + 回填历史数据，超出本次范围）；前端推算（语义错误） |
| 2 | 列位置 | 「发货数量」左侧 | 放在最右（与「未收货」的派生关系被隔开，不易比对） |
| 3 | 工序已删除 | 显示 '-' | 显示 0（会被误读为订单数量为零） |
| 4 | 字段命名 | order_qty | target_qty（后端工序内部命名，对外语义不清） |

## Surface

**后端接口**：`GET /outsource/shipments/{id}` 的 `items[]` 每行新增 `order_qty`。序列化时批量查询涉及工序的 target_qty，避免逐行查询。

**后端模型**：`OutsourceShipmentItem` 已有 `process_id` 外键（`ON DELETE SET NULL`），无需改表。

**前端**：`ShipmentItem` 类型增加 `order_qty`；明细弹窗表格在「发货数量」前插入一列。

**测试**：后端 `tests/test_outsource.py` 补充明细含 order_qty 的断言；前端明细弹窗测试补充列存在性与取值断言。

## Risks & Open Questions

- **工序删除后取不到值**：`process_id` 为 `ON DELETE SET NULL`，工序删除后该列为空，显示 '-'。这是既有数据模型约束，非本次引入；若需永久保留，需另做快照字段（已列为 Out of Scope）。
- **订单数量的语义**：`target_qty` 是订单要求的该工序总数量，与待发货面板「总量」口径一致；一个发货单可分批发货，故订单总数可能大于发货数量，属正常。
- **待确认**：无。
