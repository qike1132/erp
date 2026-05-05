# BUG-AUDIT-FIX-20260505 修复记录

- **修复时间**: 2026-05-05 00:45:00
- **审计规范**: shenhecode.mdr v12.0
- **修复规范**: bug.mdr v2.4.1-LTS

## 根因分析

基于 shenhecode.mdr v12.0 代码审核发现的 7 个问题（P0:2 / P1:1 / P2:4），全部按 bug.mdr 状态机执行修复。

### BUG-01 (P0) - save_product_bom 预加载策略不完整
- **文件**: `fastapi_app/services/purchase_product_service.py:271-279`
- **根因**: `db.get(Product, product_id)` 替换为 `selectinload` 时仅加载 `material`，未加载 `fabrics`/`accessories`/`packagings`
- **影响**: 若未来在 `save_product_bom` 中新增对未预加载关系的直接访问，将触发 `MissingGreenlet` 500 错误
- **修复**: 添加全部 4 个 `selectinload`，与 `get_product_bom` 保持一致

### BUG-02 (P0) - 路由层内联业务逻辑破坏架构分层
- **文件**: `fastapi_app/api/v1/endpoints/purchase_center/order_routes.py:63-231`
- **根因**: `api_one_click_generate_order` 路由函数内嵌 170+ 行业务逻辑（BOM 聚合、状态更新、孤儿清理）
- **影响**: 路由层承担 5 个职责，无法独立单元测试，违反 Router-Service 分层约定
- **修复**: 提取所有业务逻辑至新服务函数 `generate_purchase_orders_from_customer_orders`，路由恢复为 11 行委托模式

### BUG-03 (P1) - 函数体内延迟导入
- **文件**: `order_routes.py:67-68, 219`
- **根因**: 每次请求执行 `from sqlalchemy import select` 和循环内 `import json`
- **修复**: 随 BUG-02 重构自动消除（业务逻辑移入服务层后使用模块级导入）

### BUG-04 (P2) - 删除物料日志属性名拼接错误
- **文件**: `fastapi_app/services/purchase_product_service.py:404-421`
- **根因**: `getattr(item, f'{category[:-2]}y_name', '')` 产生错误属性名
  - `'fabrics'[:-2]` = `'fabri'` → `'fabriy_name'`（应为 `fabric_name`）
  - `'accessories'[:-2]` = `'accessori'` → `'accessoriy_name'`（应为 `accessory_name`）
- **影响**: ModificationLog 的 deleted 记录 `old_value` 始终为空字符串
- **修复**: 使用 `_delete_meta` 字典显式映射 `{'fabrics': ('fabric', 'fabric_name'), ...}`

## 影响范围

| 文件 | 变更类型 | 行数 |
|------|----------|------|
| `fastapi_app/services/purchase_product_service.py` | L271-279 添加 selectinload / L404-421 修复属性名 | +4/-4 |
| `fastapi_app/services/purchase_order_service.py` | 新增 `generate_purchase_orders_from_customer_orders` | +156 |
| `fastapi_app/services/purchase_center_service.py` | 导出新函数 | +1 |
| `fastapi_app/api/v1/endpoints/purchase_center/order_routes.py` | 路由简化 | -165/+10 |

## 验证结果

- **ruff**: All checks passed ✓
- **bandit**: 1691 lines scanned, 0 issues (0 High/Medium/Low) ✓
- **架构一致性**: 路由层恢复委托模式，与 `api_create_purchase_order` 等一致 ✓
- **API 契约**: 输入 `{order_ids: list[int]}` / 输出 `{success: true, orders: [...], count: N}` 不变 ✓

## 健康端点

`http://localhost:5002/health`
