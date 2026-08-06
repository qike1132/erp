# BomService 深模块抽取 & get_products 内存峰值优化 Spec

## Why

当前 BOM 领域逻辑分散在 4 个服务文件中（`product_service.product_has_bom`、`product_search_service.search_for_bom_copy_sync`、`purchase_product_service` 的 BOM CRUD、`purchase_bom_copy_service` 的预览/复制），模块边界不清导致 `product_has_bom` 被迫搬迁以解循环依赖——这是浅模块症状。同时 `product_service.get_products(limit=5000)` 一次性将最多 5000 条产品全量加载到内存并 `to_dict()` 序列化，被 `production_plan_service` 和 `purchase_plan_crud` 调用，存在内存峰值风险，且调用方实际只需要 `barcode` 和 `name` 两个字段做映射构建。

## What Changes

- 新增 `fastapi_app/services/bom_service.py` 深模块，统一封装 BOM 领域逻辑（get / save / copy / preview / has_bom / search_for_bom_copy），对外仅暴露 6 个入口函数
- `purchase_product_service`、`purchase_bom_copy_service`、`product_search_service`、`product_service` 中的 BOM 相关函数改为从 `bom_service` 重新导出（保持向后兼容，不破坏现有调用方）
- 新增 `product_service.get_product_barcode_map(db, limit=None)` 流式分页迭代器，按需返回 `{barcode: name}` 映射
- `production_plan_service.validate_staging` 和 `purchase_plan_crud.validate_staging` 改用 `get_product_barcode_map` 替代 `get_products`
- 保留 `product_service.get_products` 以兼容测试和搜索服务（标记为 deprecated，不删除）

### 非目标（Out of Scope）
- 不重写 BOM CRUD 的 SQL 逻辑，仅做接口聚合与重导出
- 不修改前端 BOM 相关 API 契约
- 不修改 `purchase_center/product_routes.py` 端点签名（调用方仍走 `svc.save_product_bom` 等旧名，由重导出转发）

## Impact

- **Affected specs**: 无（首次规范）
- **Affected code**:
  - 新增: `fastapi_app/services/bom_service.py`
  - 修改: `fastapi_app/services/product_service.py`（新增 `get_product_barcode_map`）
  - 修改: `fastapi_app/services/production_plan_service.py`（L268 调用方迁移）
  - 修改: `fastapi_app/services/purchase_plan_crud.py`（L903 调用方迁移）
  - 修改: `fastapi_app/services/purchase_product_service.py`（BOM 函数改为重导出）
  - 修改: `fastapi_app/services/purchase_bom_copy_service.py`（BOM 函数改为重导出）
  - 修改: `fastapi_app/services/product_search_service.py`（BOM 搜索改为重导出）
  - 不变: 所有端点文件、前端代码、测试断言（通过重导出保持兼容）

## ADDED Requirements

### Requirement: BomService 深模块

系统 SHALL 提供一个 `bom_service` 模块，作为 BOM 领域逻辑的唯一入口，隐藏 3 种物料类型（fabric/filling/accessory）的复杂映射细节。

接口签名（6 个入口函数）：
- `has_bom(product) -> bool` — 判断产品是否配置了 BOM
- `get_bom(db, product_id) -> dict` — 加载产品 BOM 详情
- `save_bom(db, product_id, data, username) -> str` — 保存 BOM（含物料 CRUD）
- `copy_bom(db, target_product_id, data, username) -> dict` — 复制 BOM 到目标产品
- `preview_bom(db, source_product_id) -> dict` — 预览源产品 BOM
- `search_for_bom_copy(db, keyword) -> list[dict]` — 搜索可复制 BOM 的产品

#### Scenario: 调用方通过 bom_service 访问 BOM 能力
- **WHEN** 任意服务或端点需要查询/修改/复制 BOM
- **THEN** 应从 `fastapi_app.services.bom_service` 导入对应函数
- **AND** 不应直接依赖 `purchase_product_service` / `purchase_bom_copy_service` / `product_search_service` 的 BOM 函数

#### Scenario: 向后兼容
- **WHEN** 现有代码仍通过旧路径（如 `purchase_product_service.save_product_bom`）调用
- **THEN** 旧路径 SHALL 通过重新导出转发到 `bom_service`
- **AND** 行为与重构前完全一致

### Requirement: 产品条码映射流式查询

系统 SHALL 提供 `product_service.get_product_barcode_map(db, limit=None)` 函数，以分页迭代方式构建 `{barcode: name}` 映射，避免一次性加载全量产品到内存。

#### Scenario: 调用方构建条码映射
- **WHEN** `production_plan_service.validate_staging` 或 `purchase_plan_crud.validate_staging` 需要按 barcode 查找产品名
- **THEN** 应调用 `get_product_barcode_map(db)` 而非 `get_products(db)`
- **AND** 内存占用应从 O(N) 全量 dict 降低到分页批次大小（默认 1000 条/批）

#### Scenario: 条码为空的产品被跳过
- **WHEN** 产品 `barcode` 为空字符串或 None
- **THEN** 不应出现在返回映射中（与现有 `if p.get('barcode')` 过滤行为一致）

## MODIFIED Requirements

### Requirement: product_service.get_products

`get_products(db, limit=5000)` 保留但标记为 deprecated。新增 `get_product_barcode_map` 作为 validate_staging 场景的推荐替代。调用方迁移后，`get_products` 仅被 `product_search_service` 和测试使用。

## REMOVED Requirements

无删除项。所有现有函数通过重导出保留，仅内部实现位置迁移。
