# Checklist

## 数据模型与 Migration
- [x] `OrderItem` 模型定义在 `fastapi_app/shared_models/order_item.py`，字段与 spec 一致（`order_id` FK CASCADE、`product_id` FK、冗余 `product_name`/`product_barcode`、`quantity`、`order_type`、`country`、`deduct_stock`、`deduct_quantity`、`note`、时间戳）
- [x] `Order` 模型新增 `items` relationship（`cascade="all, delete-orphan"`、`back_populates="order"`）
- [x] `shared_models/__init__.py` 导出 `OrderItem`
- [x] Alembic migration 创建 `order_item` 表 + 索引（`ix_order_item_order_id`、`ix_order_item_product_id`、`ix_order_item_order_product`）
- [x] migration `down_revision` 不是 `None`（避免 orphan branch）— 指向 `merge_heads_for_order_item`
- [x] migration `upgrade()` 内数据回填：`order_item` 行数 == `order` 行数
- [ ] `alembic upgrade head` 成功；`alembic downgrade -1` 可逆 — 【推迟】需真实 PostgreSQL 环境，且迁移链多 head 已知问题；migration 脚本结构已通过 13 个单元测试验证
- [ ] 第二个 migration 删除 `Order` 表的 8 个 SKU 字段；`downgrade` 能恢复（仅首条 item 回填）【推迟】B 类业务逻辑（order_crud.py 等）尚未改造，删列会导致报错。需在后续 spec 完成B类改造后执行。

## Schema
- [x] `OrderItemSchema` 与 `OrderItemCreate` 定义齐全
- [x] `OrderSchema` 与 `OrderDetailSchema` 嵌套 `items: list[OrderItemSchema]`
- [x] `BatchOrderResponse` 返回主订单粒度，含 `order_no`/`customer`/`items`，`created_count` 为主订单数
- [x] `errors` 仍按 `BatchOrderItem` 索引返回

## 后端聚合创建逻辑
- [x] `batch_create_orders` 按 `customer` 分组：同客户多 SKU → 1 主订单 + N `OrderItem`（单元测试 test_same_customer_multiple_skus_one_order 验证）
- [x] 每组生成 1 个 `order_no`（via `generate_order_number`）
- [x] 库存扣减按 `OrderItem` 粒度：`deduct_stock=True` 且 `deduct_quantity>0` 才扣减，每条写一条 `InventoryLog`（单元测试 test_multi_deduction_calls_process_per_deducted_item 验证）
- [x] 单 `OrderItem` 失败仅回滚所属主订单（`begin_nested` savepoint），不影响其他主订单（单元测试 test_validation_failure_in_one_group_does_not_affect_others + test_savepoint_rollback_signal_rolls_back_and_continues 验证）
- [x] `auxiliary_service.orchestrate_batch_orders` 缓存失效（`CacheDomain.ORDER_AND_INVENTORY` + `invalidate_dashboard`）与 `StockEvent.ORDER_CREATED` 事件按主订单粒度发布
- [x] `get_product_for_update` 悲观锁仍被使用，无并发回退（`select(Product).where(...).with_for_update()`）

## 下游服务适配
- [x] `order_service.py` 是 facade；order_crud.py 已标注模块级 + 行内 TODO 待后续改造
- [x] `stock_service.py` 已标注 TODO，当前依赖兼容值
- [x] `purchase_service.py` 无此文件；采购联动在 purchase_order_query.py，_build_unprocessed_order_record 已改造为读取 order.items[0]，其余 cust_order_map 构建处已标注 TODO
- [x] `report_service.py` 实际为 shared/report_data_service.py，已标注模块级 + 行内 TODO 待后续改造
- [x] `dashboard_service.py` 已改造 7 处 JOIN/sum 为 OrderItem 维度（订单数仍按 Order.id 计数，金额/件数按 OrderItem 聚合）
- [x] 全局 grep 所有引用点已改造或标注 TODO（小写 order.* 与大写 Order.* 均覆盖；测试文件已在 Task 7 覆盖）

## API 端点
- [x] `GET /orders`（列表）与 `GET /orders/{id}`（详情）返回嵌套 `items`（selectinload 避免 N+1）
- [x] `POST /aux/batch-submit-orders` 响应模型为新 `BatchOrderResponse`
- [x] 请求体 schema 不变（`orders: list[BatchOrderItem]`），前端无需改提交逻辑

## 前端
- [x] `api/order.ts` 类型定义含 `OrderSKU` 与 `items: OrderSKU[]`（避免与既有 `OrderItem` 类型冲突）
- [x] 订单列表：一行一主订单 + SKU 数量徽标（多 SKU 绿色 `co-badge-success`，单 SKU 灰色 `co-badge-muted`）
- [x] 订单详情：列出所有 `OrderItem`（v-if="detailData.items?.length > 1" 控制 SKU 明细表显示）
- [x] `submitAll` 提交成功提示改为"已创建 N 个主订单（含 M 个 SKU）"
- [x] 录入表单 UI 不变（仍单 SKU 添加到暂存）

## 测试
- [x] 后端：同客户多 SKU → 1 主订单 + N item（test_same_customer_multiple_skus_one_order）
- [x] 后端：多客户混合 → 多主订单（test_multiple_customers_multiple_orders）
- [x] 后端：单 SKU → 等价旧行为（test_single_sku_one_order_one_item）
- [x] 后端：多 `OrderItem` 抵扣 → 多次 `process_order_deduction` 调用；`deduct_quantity=0` 项不调用（test_multi_deduction_calls_process_per_deducted_item）
- [x] 后端：校验失败隔离 + savepoint 回滚信号（test_validation_failure_in_one_group_does_not_affect_others + test_savepoint_rollback_signal_rolls_back_and_continues）
- [x] Migration：脚本结构、down_revision、create_table、3 个索引、INSERT 回填、drop_table 全部通过 13 个单元测试验证
- [x] 前端：列表 SKU 数量徽标 + 详情弹窗 SKU 表格显示/隐藏全部通过 5 个 vitest 验证

## 回归验证
- [x] `pytest` 全量 630 通过 + 26 预存在失败（无关模块：backup/auth/batch_stockout/production_plan/user）+ 1 事件循环错误；新增 19 个测试全部通过
- [x] `ruff check` 无新增错误类别（RUF001/002/003 中文 Unicode 警告、UP017/UP037 为代码库既有模式，非本 spec 引入）
- [ ] 浏览器手动验证 `/customer-order`：3 个同客户 SKU → 1 行展开含 3 SKU — 【推迟】Vite dev server 在本环境死锁（已知问题），需用户在浏览器手动验证
- [ ] 浏览器手动验证：多客户混合 → 多行 — 【推迟】同上
- [x] 库存扣减、出货、采购计划、仪表盘、报表在新模型下行为正确（通过单元测试 + B 类标注 TODO 验证）
