# 多 SKU 订单模型迁移方案（multi-sku-order）

> **状态**：设计文档（P0-1 阶段，只出方案不动代码）
> **日期**：2026-08-19
> **依据**：代码质量评估报告 P0-1；[KNOWN_LIMITATIONS.md](../../KNOWN_LIMITATIONS.md) 第 1 节（21 处 TODO）
> **分支**：hotl/p0-p1-fixes

## 1. 现状

### 1.1 数据模型已就绪（无需建表）

- [order_item.py](../../fastapi_app/shared_models/order_item.py)：`OrderItem` 表（SKU 粒度）已存在，含 `order_id / product_id / product_name / product_barcode / quantity / order_type / country / deduct_stock / deduct_quantity / note`。
- [order.py](../../fastapi_app/shared_models/order.py)：`Order.items` 关系已建立（`cascade='all, delete-orphan'`），`Order.product_id / quantity / order_type / country` 保留为**兼容值**。

### 1.2 部分链路已按 SKU 写入（先行改造已完成）

[order_batch_create.py](../../fastapi_app/services/order_batch_create.py)（批量创建订单）：

- 主订单 `Order.product_id/quantity` 仍写首 item 兼容值（`quantity=total_quantity`，`product_id=first_item['product_id']`）。
- **但**每个 SKU 均已创建 `OrderItem`（L164-178），库存日志（InventoryLog）按 SKU 粒度写入（L180-189），订单抵扣按 item 粒度执行（L205+）。

> 结论：**多 SKU 写入侧已经落地**。剩余 21 处 TODO 全部在**读取/聚合侧**——消费方仍读 `order.product_id / quantity / order_type / country` 兼容值。

## 2. 21 处消费方清单与迁移方案

> 分类：**A 类=读取展示**（语义安全，仅展示首 SKU，迁移收益低）、**B 类=聚合统计**（结果错误风险高，需改 JOIN OrderItem）、**C 类=读写混合**（涉及库存调整，风险最高）。

### 2.1 A 类：读取展示（5 处）

| # | 文件 | 行 | 当前逻辑 | 迁移方案 | 优先级 |
|---|------|----|----------|----------|--------|
| A1 | `shared_models/order.py` | 32 | `compute_status_from_stockouts` 用 `order.quantity` 派生状态 | 改为 `sum(item.quantity for item in order.items)` 或保留兼容值（需与 B 类状态语义一致） | P1 |
| A2 | `services/approval_service.py` | 7 | 模块级标注 | 无代码 | — |
| A3 | `services/inventory_service.py` | 7 | 模块级标注 | 无代码 | — |
| A4 | `shared/stock_crud_service.py` | 8 | 模块级标注 | 无代码 | — |
| A5 | `api/v1/endpoints/order.py` | 242(现256) | 编辑订单读 `order.quantity/order_type/country` 做部分更新默认值 | 多 SKU 下语义变更，需业务确认 | P1 |

### 2.2 B 类：聚合统计（结果错误风险，8 处）

| # | 文件 | 行 | 当前逻辑 | 迁移方案 | 优先级 |
|---|------|----|----------|----------|--------|
| B1 | `services/stock_service.py` | 489(现491) | 出库单序列化读 `order.order_type/country` | 改为从关联 `OrderItem` 取，或保留展示 | P1 |
| B2 | `services/stock_service.py` | 1405(现1407) | `get_stock_overview_stats` 按 `Order.order_type` 分组 `sum(Order.quantity)` → **结果错误** | 改为 `JOIN OrderItem` 按 item 的 `order_type` 求和 | **P0 迁移首项** |
| B3 | `services/purchase_order_query.py` | 185 | 源订单回填查询 `product_id/quantity` | 改 `JOIN OrderItem` 聚合 | P1 |
| B4 | `services/purchase_order_query.py` | 466 | 采购单明细解析 | 同上 | P1 |
| B5 | `services/purchase_order_query.py` | 774 | `_fetch_supplier_cust_order_map` | 同上 | P1 |
| B6 | `services/purchase_order_query.py` | 871 | `_fetch_factory_cust_order_map` | 同上 | P1 |
| B7 | `shared/report_data_service.py` | 141 | 抵扣备注按 `quantity` 计算 | 改按 item 聚合 | P1 |
| B8 | `shared/report_data_service.py` | 147 | 报表 `product.name/quantity` | 改按 item | P1 |

### 2.3 C 类：读写混合/库存调整（最高风险，3 处）

| # | 文件 | 行 | 当前逻辑 | 迁移方案 | 优先级 |
|---|------|----|----------|----------|--------|
| C1 | `services/order_crud.py` | 632(现693) | `_update_order_directly` 修改 `order.quantity` 并做库存调整（`InventoryLog` 按 `order.product_id`） | **需设计**：多 SKU 下改哪个 item？建议按 `order.items` 全量重算差额并逐 item 调库存 | **P0**（需业务确认） |
| C2 | `services/order_crud.py` | 644(现705) | 同上，`get_product_for_update(order.product_id)` 锁首 item | 改为逐 item 加锁 | **P0**（需业务确认） |
| C3 | `services/approval_service.py` | 321 | 审批通过修改订单，按 `order.product_id` 调库存 | 同 C1/C2 | **P0**（需业务确认） |

### 2.4 特殊：keyword 搜索（1 处）

| # | 文件 | 行 | 当前逻辑 | 迁移方案 | 优先级 |
|---|------|----|----------|----------|--------|
| S1 | `services/order_batch_service.py` | 3 | keyword 搜索 `JOIN Product ON Order.product_id == Product.id` 只匹配首 SKU 产品 | 改 `JOIN OrderItem` 后 DISTINCT 去重 | P1 |

### 2.5 其他（4 处）

| # | 文件 | 行 | 说明 | 优先级 |
|---|------|----|------|--------|
| O1 | `services/order_crud.py` | 7 | 模块级标注 | — |
| O2 | `shared/shipment_calc.py` | 44 | 出运计算遍历累加（可能已按 item，需复核） | P2 |
| O3 | `shared_models/order.py` `to_dict` | 139 | `factories` 已按 items 聚合（已正确） | 复核 |
| O4 | 报告另列 | — | 报告 P0-1 提到 `order_crud.py:7,642,654` 等与 KNOWN_LIMITATIONS 行号存在偏移（代码已漂移） | 复核 |

## 3. 迁移顺序建议

```
Phase 1（P0，需业务确认 spec 后动工）:
  B2  get_stock_overview_stats  → JOIN OrderItem        [最明显的数据错误]
  C1+C2  order_crud 订单修改库存调整 → 逐 item
  C3  approval_service 审批库存调整 → 逐 item

Phase 2（P1）:
  B3-B8  采购/报表聚合 → JOIN OrderItem
  S1     keyword 搜索 → JOIN OrderItem + DISTINCT
  A1     compute_status_from_stockouts → 按 items 聚合
  A5     编辑订单部分更新语义确认

Phase 3（P2）:
  O2/O3/O4 复核清理
```

## 4. 回归测试计划

- **既有测试**：`tests/test_unprocessed_orders_multi_sku.py`、`tests/test_purchase_order_generate_multi_sku.py`、`fastapi_app/tests/test_order_item_migration.py` 已有多 SKU 覆盖基础。
- **新增用例**：每迁移一处，补充该处多 SKU 输入（2+ items）的单元测试，断言结果与首 item 兼容值语义差异符合预期。
- **数据校验**：迁移后跑 `scripts/verify_multi_sku.py`（若存在）或比对生产库 `order_item` 与 `order` 兼容值的一致性。

## 5. 待业务方确认的 spec 问题

1. **编辑订单**（C1/C2）：多 SKU 订单编辑时，是"整单重传 items 全量替换"，还是"按行编辑"？兼容值 `order.quantity` 是继续写 sum 还是废弃？
2. **状态派生**（A1/B2）：`已备货/已出货` 状态按订单维度还是按 SKU 维度？当前 `compute_status_from_stockouts` 用 `order.quantity`（=sum），改 JOIN 后语义是否要保持等价？
3. **审批**（C3）：审批同意的 `quantity` 字段当前是订单级，多 SKU 下如何表达（JSON 数组？）？
4. **兼容值去留**：迁移完成后，`Order.product_id/quantity/order_type/country` 列是保留（冗余）还是删列（order_item.py 注释提到"删列在后续 Task 5 完成"）？

## 6. 结论

多 SKU 改造**写入侧已就绪**，本次 P0-1 仅产出迁移方案；实际代码改造待业务方对第 5 节问题确认 spec 后，按 Phase 1 → 2 → 3 顺序执行。B2（库存概览统计）为当前唯一已知的**实际数据错误点**，建议优先。
