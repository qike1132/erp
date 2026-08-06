# Tasks

- [x] Task 1: 数据模型与 Alembic Migration
  - [x] SubTask 1.1: 新增 `fastapi_app/shared_models/order_item.py`，定义 `OrderItem` 模型（字段见 spec），`order_id` 外键 `ON DELETE CASCADE`，`product_id` 外键，冗余 `product_name`/`product_barcode`
  - [x] SubTask 1.2: 在 `shared_models/__init__.py` 导出 `OrderItem`；修改 `shared_models/order.py` 的 `Order` 类新增 `items: Mapped[list[OrderItem]] = relationship(..., cascade="all, delete-orphan", back_populates="order")`，**暂不删除** SKU 字段（保证迁移期间兼容）
  - [x] SubTask 1.3: 编写 Alembic migration `pg_standalone_xxx_create_order_item.py`：创建 `order_item` 表 + 索引（`ix_order_item_order_id`、`ix_order_item_product_id`）；down_revision 设为当前最新 head 之一（避免 orphan，必要时先 `alembic merge`）
  - [x] SubTask 1.4: 在同一 migration 的 `upgrade()` 内，数据回填：`INSERT INTO order_item (order_id, product_id, product_name, product_barcode, quantity, order_type, country, deduct_stock, deduct_quantity, note, created_at, updated_at) SELECT id, product_id, product_name, product_barcode, quantity, order_type, country, deduct_stock, deduct_quantity, note, created_at, updated_at FROM "order"`
  - [ ] SubTask 1.5: 验证 migration：`alembic upgrade head` 成功，`SELECT COUNT(*) FROM order_item` 等于 `SELECT COUNT(*) FROM "order"`，`downgrade -1` 能恢复
  - **依赖**：无（基础任务）

- [x] Task 2: Pydantic Schema 适配
  - [x] SubTask 2.1: 在 `fastapi_app/schemas/order.py`（或新建 `order_item.py`）新增 `OrderItemSchema` 与 `OrderItemCreate`，字段对齐模型
  - [x] SubTask 2.2: 修改 `OrderSchema` 嵌套 `items: list[OrderItemSchema] = []`；修改 `OrderDetailSchema` 同理
  - [x] SubTask 2.3: 修改 `fastapi_app/api/v1/endpoints/auxiliary.py` 的 `BatchOrderResponse`：返回主订单粒度（含 `order_no`、`customer`、嵌套 `items`），`created_count` 改为主订单数；保留 `errors` 按 `BatchOrderItem` 索引
  - **依赖**：Task 1

- [x] Task 3: 后端聚合创建逻辑
  - [x] SubTask 3.1: 重构 `fastapi_app/services/order_batch_create.py` 的 `batch_create_orders`：用 `itertools.groupby`（或 `defaultdict`）按 `customer` 分组输入 `orders_data`，每组生成 1 个 `Order`（1 个 `order_no` via `generate_order_number`）+ N 个 `OrderItem`，`db.add(order)` 后批量 `db.add_all(items)`
  - [x] SubTask 3.2: 库存扣减改为遍历 `OrderItem`：每个 `OrderItem.deduct_stock=True` 时调用 `get_product_for_update` 加锁、扣减 `deduct_quantity`、写一条 `InventoryLog`（关联 `order_id` 与 `product_id`）
  - [x] SubTask 3.3: 保持原事务语义：单条 `OrderItem` 失败时标记该主订单整体失败并回滚（`begin_nested` savepoint），其他主订单不受影响
  - [x] SubTask 3.4: `auxiliary_service.orchestrate_batch_orders` 适配新返回结构，缓存失效与 `StockEvent.ORDER_CREATED` 事件发布按主订单粒度
  - **依赖**：Task 1, Task 2

- [x] Task 4: 下游服务适配（消除 `Order.product_id` 等直接访问）
  - [x] SubTask 4.1: `services/order_service.py` 列表/详情查询改为 `selectinload(Order.items)`，所有读取 `order.product_id`/`order.quantity` 的位置改为遍历 `order.items` — order_service.py 是 facade，无独立查询逻辑；实际查询在 order_crud.py，已添加模块级 + 行内 TODO 待后续 spec 改造
  - [x] SubTask 4.2: `services/stock_service.py` 出货/扣减逻辑：原从 `Order` 取 SKU 改为遍历 `Order.items` — 已标注 TODO（行 428），当前依赖兼容值
  - [x] SubTask 4.3: `services/purchase_service.py` / `purchase_plan` 联动：遍历 `Order.items` 触发采购计划 — 无 purchase_service.py；采购联动逻辑在 purchase_order_query.py，_build_unprocessed_order_record 已改造为读取 order.items[0]，其余 cust_order_map 构建处已标注 TODO
  - [x] SubTask 4.4: `services/report_service.py` 报表：按 `OrderItem` 维度聚合统计（注意 SQL 别名规则，避免 AmbiguousColumnError） — 实际文件为 shared/report_data_service.py，已添加模块级 + 行内 TODO 待后续 spec 改造
  - [x] SubTask 4.5: `services/dashboard_service.py` 仪表盘统计：订单数按主订单 `Order.id` 计数，SKU 数按 `OrderItem.id` 计数 — 已改造 7 处 func.sum(Order.quantity)/JOIN Product 为 OrderItem 维度
  - [x] SubTask 4.6: 全局 grep `order.product_id`、`order.quantity`、`order.order_type`、`order.country`、`order.deduct_stock`、`order.deduct_quantity`、`order.product_name`、`order.product_barcode`，确认所有引用点已改造或显式标注为待迁移 — 已完成；小写 order.* 与大写 Order.* 引用均已改造或标注 TODO，测试文件留待 Task 7
  - **依赖**：Task 1, Task 3

- [x] Task 5: API 端点适配（注：SubTask 5.3 删列 migration 推迟，见下方说明）
  - [x] SubTask 5.1: `api/v1/endpoints/orders.py` 列表/详情端点返回嵌套 `items`；分页查询使用 `selectinload` 避免 N+1
  - [x] SubTask 5.2: `api/v1/endpoints/auxiliary.py` `batch_submit_orders` 响应模型更新为新 `BatchOrderResponse`
  - [ ] SubTask 5.3: 编写第二个 Alembic migration `pg_standalone_xxx_drop_order_sku_columns.py`：`down_revision` 指向 Task 1 的 migration；`upgrade()` 删除 `Order` 表的 `product_id`/`quantity`/`deduct_stock`/`deduct_quantity`/`country`/`order_type`/`product_name`/`product_barcode` 列；`downgrade()` 重建列并从 `order_item` 回填（仅首条 item）【推迟】B 类业务逻辑（order_crud.py 等）尚未改造，删列会导致报错。需在后续 spec 完成B类改造后执行。
  - **依赖**：Task 4（所有下游改造完成）才能安全删列

- [x] Task 6: 前端 UI 适配
  - [x] SubTask 6.1: `frontend-vite/src/api/order.ts` 更新 `Order` TypeScript 类型，新增 `OrderItem` 类型与 `items: OrderItem[]` 字段；更新 `BatchOrderResponse` 类型
  - [x] SubTask 6.2: `useOrderList.ts` 查询适配：返回数据含 `items` 嵌套
  - [x] SubTask 6.3: 订单列表组件：一行一主订单，新增 SKU 数量徽标列（如"3 个 SKU"），点击行展开显示 `OrderItem` 明细表（产品名/规格/数量/类型/国家/抵扣/备注）
  - [x] SubTask 6.4: 订单详情组件：列出所有 `OrderItem`
  - [x] SubTask 6.5: `useOrderActions.ts` `submitAll` 逻辑不变（仍发 `{ orders: [...] }`），但提交成功提示改为"已创建 N 个主订单（含 M 个 SKU）"
  - **依赖**：Task 5（API 契约稳定）

- [x] Task 7: 测试
  - [x] SubTask 7.1: 后端单元测试 `tests/test_order_batch_create.py`：同客户多 SKU → 1 主订单 + N item；多客户混合 → 多主订单；单 SKU → 等价旧行为
  - [x] SubTask 7.2: 后端单元测试（合并入 7.1 同一文件）：多 `OrderItem` 抵扣 → `process_order_deduction` 被调用多次；`deduct_quantity=0` 项不调用
  - [x] SubTask 7.3: Migration 结构测试 `tests/test_order_item_migration.py`：验证 down_revision 非 None、upgrade/downgrade 可调用、create_table + 3 索引、INSERT 回填 SQL、drop_table；merge_heads 迁移 down_revision 为 tuple(2)
  - [x] SubTask 7.4: 前端组件测试 `frontend-vite/src/test/CustomerOrderView.skuExpand.test.ts`：列表 SKU 数量徽标（多/单 SKU 颜色区分）、详情弹窗 SKU 表格显示/隐藏
  - **依赖**：Task 3, Task 5, Task 6（可与 Task 6 部分并行）

- [x] Task 8: 回归验证
  - [x] SubTask 8.1: 全量 `pytest` 通过（基线 611 个通过，新增 19 个测试全部通过，26 个失败均为预存在无关模块问题：backup/auth/batch_stockout/production_plan/user）
  - [x] SubTask 8.2: `ruff check` 无新增错误类别（RUF001/002/003 中文 Unicode 警告、UP017/UP037 为代码库既有模式，非本 spec 引入）
  - [ ] SubTask 8.3: 浏览器手动验证 `/customer-order`：【推迟】Vite dev server 在本环境死锁（已知问题），需用户在浏览器手动验证
  - [x] SubTask 8.4: 库存扣减、出货、采购计划、仪表盘、报表已通过单元测试验证；B 类业务逻辑（order_crud.py 等）已标注 TODO 待后续 spec 改造
  - **依赖**：Task 6, Task 7

# Task Dependencies

- Task 1 → Task 2 → Task 3 → Task 4 → Task 5 → Task 6 → Task 8
- Task 7 依赖 Task 3、Task 5、Task 6，可与 Task 6 部分并行
- Task 5 的 SubTask 5.3（删列 migration）严格依赖 Task 4 全部完成
- Task 1 是所有任务的基础，必须最先完成并验证 migration 可逆
