# BUG-SYNC-001 修复记录

- **修复时间**: 2026-05-04
- **Git Commit**: 待提交
- **根因分析**: 客户订单创建后同步到采购中心的完整链路存在3层故障

## 根因（按严重度排序）

### P0: sync_order_create 调用后缺少 db.commit()
- **文件**: `fastapi_app/api/v1/endpoints/auxiliary.py` line 348-364
- **原因**: sync 在 `batch_create_orders` 的 `db.commit()` (line 339) 之后执行，创建了 PurchaseOrder 并 flush，但从未 commit，导致数据从未持久化
- **同文件**: `fastapi_app/services/order_service.py` line 207-215 也有同样问题

### P0: PurchaseOrder.total_amount 列缺失
- **文件**: `fastapi_app/shared_models/purchase_order.py`
- **原因**: 模型未声明 `total_amount` 列，但 `purchase_order_service.py` 在 20 处引用，导致 AttributeError → API 500
- **修复**: 添加 `total_amount: Mapped[float | None] = mapped_column(Numeric(12,2), default=0)` + ALTER TABLE

### P0: purchase_order_service.py 中 order.note 应为 order.remark
- **文件**: `fastapi_app/services/purchase_order_service.py` line 202, 251, 281, 627
- **原因**: PurchaseOrder 模型字段名是 `remark`，但 service 代码用了 `note`，导致 AttributeError → API 500

### P1: 客户订单→采购中心同步代码被注释但无替代
- **文件**: `fastapi_app/services/order_service.py` line 207-209
- **原因**: 旧 `_sync_order_to_purchase_center` 被注释掉，无替代方案，订单永远不会出现在采购中心
- **修复**: 新增 `order_purchase_sync.sync_order_create()` 函数

### P1: get_unprocessed_orders 中 has_bom 硬编码为 False
- **文件**: `fastapi_app/services/purchase_order_service.py` line 824
- **原因**: 硬编码 `has_bom: False`，导致前端"审核订单"按钮永远不显示
- **修复**: 根据 source_order_id 查询 ProductMaterial 判断 BOM 是否存在

### P1: get_unprocessed_orders 中 o.items 触发 lazy load 异步异常
- **文件**: `purchase_order_service.py` line 849
- **原因**: `bool(o.items)` 触发同步 lazy load，在 async 上下文中抛 MissingGreenlet
- **修复**: 使用批量 COUNT 查询替代 lazy load

### P2: one_click_generate_order 类型不匹配
- **文件**: `fastapi_app/api/v1/endpoints/purchase_center/order_routes.py` line 66
- **原因**: 路由传入 `list[int]` (order_ids)，但 service 期望 `list[dict]`
- **修复**: 路由中展开 BOM 物料后再传给 service

## 修复文件清单

| 文件 | 修改内容 |
|------|---------|
| `fastapi_app/shared_models/purchase_order.py` | 添加 total_amount 列声明 |
| `fastapi_app/services/purchase_order_service.py` | order.note→order.remark (4处)；has_bom 改为批量查询；items_count 批量查询替代 lazy load |
| `fastapi_app/services/order_purchase_sync.py` | 新增 sync_order_create() 函数 |
| `fastapi_app/api/v1/endpoints/auxiliary.py` | batch_submit_orders 后调用 sync_order_create + commit |
| `fastapi_app/services/order_service.py` | create_order 后调用 sync_order_create + commit；order_date 前端传入支持 |
| `fastapi_app/api/v1/endpoints/purchase_center/order_routes.py` | one-click-generate 展开BOM物料 + 更新状态 |
| `fastapi_app/api/v1/endpoints/auxiliary.py` | BatchOrderItem 添加 order_date 字段 |
| `frontend-vite/src/views/customer-order/CustomerOrderView.vue` | 提交时发送 order_date；产品搜索提示优化 |
| `frontend-vite/src/views/purchase/composables/*.ts` | 3个 composable 添加 API 错误提示 |

## 验证结果

- L1 单元测试: PASS (sync_order_create 函数正常)
- L2 集成测试: PASS (PurchaseOrder 持久化正确)
- L3 接口契约测试: PASS (get_unprocessed_orders 返回正确数据)
- L4 端到端测试: PASS (创建订单→同步→采购中心显示，完整链路)
- L5 安全扫描: PASS (bandit 无高危)
