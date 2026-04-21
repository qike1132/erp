# BUG-REGRESSION-20260421 修复记录

- **修复时间**: 2026-04-21
- **Git Commit**: d9765077edf2365b64bfd24b68b0d39fafd47928 (基线)
- **根因分析**: 前一轮 BUG 修复在 purchase_center_service.py 中引入了模型字段不匹配的回归问题：使用 `creator_id`/`creator_name` 而非模型定义的 `created_by`；访问不存在的 `total_amount` 属性
- **影响范围**: 采购订单创建、列表查询、详情查询、已完成列表、来料登记同步、采购单删除
- **修复项**:
  1. P0-01: `creator_id=user_id` → `created_by=user_id`，删除 `creator_name` (purchase_center_service.py:217-219)
  2. P0-02: `o.total_amount` → `sum(item.total_price for item in o.items)` 动态计算 (purchase_center_service.py:350,378,559)
  3. P0-03(新发现): MaterialRegistration 创建时缺少必填字段 `purchase_order_id`/`purchase_order_no`，且 `creator_id` 应为 `created_by` (purchase_center_service.py:460-468)
  4. P2-01: `delete_purchase_order` 新增 `source_order_ids` JSON 解析，回滚所有关联源订单 (purchase_center_service.py:432-444)
  5. P2-02: order.js console.log 路径更新为 `/api/v1/aux/batch-submit-orders` (order.js:896)
  6. 模型补充: PurchaseOrder 新增 `source_order_ids` 列映射 (purchase_order.py:31)
- **验证结果**: Python 语法检查全部通过，grep 确认无 creator_id/creator_name/o.total_amount 残留
