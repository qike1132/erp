# 路由迁移计划

## 旧架构路由分析（共65个路由）

### 1. 主页和认证路由 (3个)
- `/` -> index
- `/login` -> login
- `/logout` -> logout

### 2. 产品管理路由 (3个)
- `/products` -> products (产品列表)
- `/product/edit/<int:id>` -> edit_product (编辑产品)
- `/product/delete/<int:id>` -> delete_product (删除产品)

### 3. 订单管理路由 (3个)
- `/orders` -> orders (订单列表)
- `/order/edit/<int:id>` -> edit_order (编辑订单)
- `/order/delete/<int:id>` -> delete_order (删除订单)

### 4. 入库管理路由 (4个)
- `/stockins` -> stockins (入库列表)
- `/edit-stockin/<int:id>` -> edit_stockin (编辑入库)
- `/delete-stockin/<int:id>` -> delete_stockin (删除入库)
- `/api/stockin-info/<int:stockin_id>` -> stockin_info (入库信息API)

### 5. 出库管理路由 (4个)
- `/stockouts` -> stockouts (出库列表)
- `/edit-stockout/<int:id>` -> edit_stockout (编辑出库)
- `/delete-stockout/<int:id>` -> delete_stockout (删除出库)

### 6. 库存管理路由 (1个)
- `/inventory` -> inventory (库存查看)

### 7. 用户管理路由 (5个)
- `/users` -> users (用户列表)
- `/user/edit/<int:id>` -> edit_user (编辑用户)
- `/user/delete/<int:id>` -> delete_user (删除用户)
- `/user/toggle/<int:id>` -> toggle_user_status (切换用户状态)
- `/user/permission/<int:user_id>` -> user_permission (用户权限)

### 8. 案件管理路由 (7个)
- `/cases` -> cases (案件列表)
- `/case-products` -> case_products (案件产品)
- `/case-stockins` -> case_stockins_page (案件入库)
- `/case-stockouts` -> case_stockouts_page (案件出库)
- `/case-inventory` -> case_inventory_page (案件库存)
- `/reports` -> reports (报表)

### 9. 批量导入路由 (5个)
- `/batch-import` -> batch_import (批量导入)
- `/batch-import-orders` -> batch_import_orders (批量导入订单)
- `/batch-import-stockins` -> batch_import_stockins (批量导入入库)
- `/batch-import-unified` -> batch_import_unified (统一批量导入)
- `/download-template` -> download_template (下载模板)

### 10. API路由 (30个)
#### 产品相关API (3个)
- `/api/product-search` -> product_search
- `/api/product-available-stock` -> product_available_stock
- `/api/inventory-logs/<int:product_id>` -> get_inventory_logs

#### 入库相关API (4个)
- `/api/available-stockins` -> available_stockins
- `/api/batch-submit-stockins` -> batch_submit_stockins
- `/api/confirm-stockin-deduction` -> confirm_stockin_deduction
- `/api/validate-deduct-quantity` -> validate_deduct_quantity

#### 出库相关API (2个)
- `/api/batch-submit-stockouts` -> batch_submit_stockouts

#### 订单相关API (1个)
- `/api/batch-submit-orders` -> batch_submit_orders

#### 案件相关API (12个)
- `/api/case-search` -> case_search
- `/api/case-product/<int:case_id>` -> delete_case_product
- `/api/case-stockins` -> api_case_stockins
- `/api/case-stockin/<int:stockin_id>` -> get_case_stockin/update_case_stockin/delete_case_stockin
- `/api/case-stockin-info/<int:stockin_id>` -> case_stockin_info
- `/api/case-stockouts` -> api_case_stockouts
- `/api/case-stockout/<int:stockout_id>` -> get_case_stockout/update_case_stockout/delete_case_stockout
- `/api/case-inventory-logs/<int:case_id>` -> case_inventory_logs
- `/api/case-inventory-summary` -> case_inventory_summary
- `/api/available-case-stockins` -> available_case_stockins
- `/api/batch-submit-case-stockins` -> batch_submit_case_stockins
- `/api/batch-submit-case-stockouts` -> batch_submit_case_stockouts

#### 其他API (8个)
- `/api/deduction-logs` -> api_deduction_logs
- `/api/log-operation` -> log_operation
- `/api/test-simple-submit` -> test_simple_submit

### 11. 工具路由 (3个)
- `/upload` -> upload_image
- `/save-template-dialog` -> save_template_dialog
- `/get-desktop-path` -> get_desktop_path
- `/copy-template-to-desktop` -> copy_template_to_desktop

## 迁移策略

### 阶段1: 核心业务路由（优先级高）
1. 创建 product.py 蓝图 - 产品管理
2. 创建 order.py 蓝图 - 订单管理
3. 创建 stock.py 蓝图 - 入库/出库管理
4. 创建 user.py 蓝图 - 用户管理

### 阶段2: 高级功能路由（优先级中）
1. 创建 case.py 蓝图 - 案件管理
2. 创建 batch.py 蓝图 - 批量导入
3. 创建 report.py 蓝图 - 报表统计

### 阶段3: API路由（优先级中）
1. 创建 api.py 蓝图 - 所有API接口

### 阶段4: 工具路由（优先级低）
1. 创建 utils.py 蓝图 - 工具函数

## 蓝图结构设计

每个蓝图文件应包含：
1. 蓝图定义
2. 路由函数
3. 必要的导入
4. 错误处理

## 命名冲突解决方案

将 app.py 重命名为 legacy_app.py，避免与 app/ 包冲突。
