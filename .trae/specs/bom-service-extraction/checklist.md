# Checklist

## BomService 深模块抽取

- [x]`fastapi_app/services/bom_service.py` 文件存在且可被 `ast.parse` 解析
- [x]`bom_service` 模块导出 6 个入口函数：`has_bom`、`get_bom`、`save_bom`、`copy_bom`、`preview_bom`、`search_for_bom_copy`
- [x]`bom_service` 模块级 docstring 说明 3 种物料类型（fabric/filling/accessory）的映射规则
- [x]`bom_service` 不在模块顶层导入 `product_service`（避免循环依赖，必要时用函数内延迟导入）
- [x]`purchase_product_service.save_product_bom` 通过重导出转发到 `bom_service.save_bom`
- [x]`purchase_product_service.get_product_bom` 通过重导出转发到 `bom_service.get_bom`
- [x]`purchase_product_service.product_has_bom` 通过重导出转发到 `bom_service.has_bom`
- [x]`purchase_bom_copy_service.copy_bom_to_product` 通过重导出转发到 `bom_service.copy_bom`
- [x]`purchase_bom_copy_service.get_bom_preview` 通过重导出转发到 `bom_service.preview_bom`
- [x]`product_service.product_has_bom` 通过重导出转发到 `bom_service.has_bom`
- [x]`product_search_service.search_for_bom_copy_sync` 保持 sync 签名兼容（若 bom_service 提供 async 版本，需在重导出层适配）
- [x]运行 `from fastapi_app.services import bom_service; print(dir(bom_service))` 无 ImportError

## get_products 内存峰值优化

- [x]`product_service.get_product_barcode_map(db, limit=None, batch_size=1000)` 函数存在
- [x]该函数仅 SELECT `barcode` 和 `name` 两列，不调用 `to_dict()` 全量序列化
- [x]该函数使用 `LIMIT/OFFSET` 分页迭代，单批最多 `batch_size` 条
- [x]该函数跳过 `barcode` 为空字符串或 None 的记录
- [x]该函数返回 `dict[str, str]` 类型（`{barcode: name}`）
- [x]`production_plan_service.validate_staging`（L268 附近）不再调用 `product_service.get_products`
- [x]`production_plan_service.validate_staging` 改用 `get_product_barcode_map`，下游 `barcode_set` 和 `product_name_map` 基于映射构建
- [x]`purchase_plan_crud.validate_staging`（L903 附近）不再调用 `product_service.get_products`
- [x]`purchase_plan_crud.validate_staging` 改用 `get_product_barcode_map`，下游 `product_map` 改为 `barcode_map`
- [x]`purchase_plan_crud.validate_staging` 中 `product_map[record.barcode]['name']` 改为 `barcode_map.get(record.barcode)`

## 向后兼容与回归

- [x]`product_service.get_products(db, limit=5000)` 函数仍存在（标记 deprecated 但不删除）
- [x]`product_search_service` 仍能正常调用 `get_products`（无 ImportError）
- [x]现有测试 `test_purchase_center.py` 中 `product_has_bom` 相关用例全部通过
- [x]现有测试 `test_product.py` 全部通过，无回归
- [x]`/purchase-center/products` 端点正常响应 200
- [x]`/products/list` 端点正常响应 200
- [x]`/purchase-center/products/{id}/bom` 端点正常返回 BOM 数据
- [x]`/purchase-center/products/{id}/bom` POST 保存端点正常工作
- [x]`/purchase-center/products/{source_id}/bom-preview` 端点正常返回预览
- [x]`/purchase-center/products/{target_id}/copy-bom` 端点正常执行复制
- [x]`validate_staging` 端点对未注册 barcode 仍返回"69码未找到产品"错误
- [x]`validate_staging` 端点对已注册 barcode 正确回填 `product_name`
