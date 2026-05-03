# BUG-APPROVAL-QTY-ZERO 修复记录

- **修复时间**: 2026-04-30
- **Git Commit**: ca097be (修复前)
- **根因分析**: `create_purchase_order` 函数中 `product_quantity` 被计算为所有 BOM 物料数量（unit_usage * order.quantity）的总和，而非原始订单的产品数量。当 BOM 物料的 `unit_usage` 为 0 时（例如面料 quantity=0），所有 item 的 quantity 均为 0，`product_quantity` 累加结果为 0，前端显示"订单数量"为 0。
- **影响范围**: 采购中心"一键审核"生成的所有采购订单，`product_quantity` 值语义错误（为物料数量总和而非订单数量）。特别是 BOM 中 unit_usage 为 0 的物料会导致整个 product_quantity 为 0。
- **修复方案**:
  1. `one_click_generate_order` 中将 `order.quantity` 通过 `order_quantity` 字段传入 items_data
  2. `create_purchase_order` 中使用 `order_quantity` 作为 `product_quantity`，替代累加逻辑
- **修改文件**:
  - `fastapi_app/services/purchase_center_service.py` 第 308 行（新增 order_quantity 字段）
  - `fastapi_app/services/purchase_center_service.py` 第 220-236 行（替换 product_quantity 计算逻辑）
- **验证结果**: 77/79 测试通过（2个已有失败与本次修改无关），L1 单元测试 PASS
- **健康端点**: http://localhost:5002/health

## 数据修复

对于已存在的错误数据，需执行以下 SQL 回填：

```sql
UPDATE purchase_order po
JOIN `order` o ON po.source_order_id = o.id
SET po.product_quantity = o.quantity
WHERE po.source_order_id IS NOT NULL;
```
