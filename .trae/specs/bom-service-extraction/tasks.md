# Tasks

- [x] Task 1: 新增 `bom_service.py` 深模块文件
  - [x]SubTask 1.1: 创建 `fastapi_app/services/bom_service.py`，从现有 4 个服务文件迁移 BOM 函数实现（`has_bom`、`get_bom`、`save_bom`、`copy_bom`、`preview_bom`、`search_for_bom_copy`）
  - [x]SubTask 1.2: 处理迁移中的循环依赖——`bom_service` 依赖 `product_service.get_products` 时使用函数内延迟导入
  - [x]SubTask 1.3: 为 `bom_service` 编写模块级 docstring，说明 6 个入口函数的职责与 3 种物料类型映射规则
  - [x]验证: `python -c "import ast; ast.parse(open('fastapi_app/services/bom_service.py').read())"` 通过

- [ ] Task 2: 旧路径改为重新导出
  - [x]SubTask 2.1: `purchase_product_service.py` 删除 `get_product_bom` / `save_product_bom` / `product_has_bom` 实现，改为 `from fastapi_app.services.bom_service import get_bom as get_product_bom, save_bom as save_product_bom, has_bom as product_has_bom`
  - [x]SubTask 2.2: `purchase_bom_copy_service.py` 删除 `get_bom_preview` / `copy_bom_to_product` 实现，改为重导出 `preview_bom` / `copy_bom`
  - [x]SubTask 2.3: `product_search_service.py` 的 `search_for_bom_copy_sync` 改为重导出 `bom_service.search_for_bom_copy`（注意同步/异步签名差异，保持 sync 版本兼容）
  - [x]SubTask 2.4: `product_service.py` 的 `product_has_bom` 改为重导出 `bom_service.has_bom`
  - [x]验证: `python -c "from fastapi_app.services.purchase_product_service import save_product_bom; from fastapi_app.services.purchase_bom_copy_service import copy_bom_to_product; from fastapi_app.services.product_service import product_has_bom; print('re-exports OK')"` 通过

- [ ] Task 3: 新增 `get_product_barcode_map` 流式查询
  - [x]SubTask 3.1: 在 `product_service.py` 新增 `async def get_product_barcode_map(db, limit=None, batch_size=1000) -> dict[str, str]`，使用 `LIMIT/OFFSET` 分页迭代，仅 SELECT `barcode` 和 `name` 两列
  - [x]SubTask 3.2: 跳过 `barcode` 为空或 None 的记录
  - [x]验证: 单元测试 `test_get_product_barcode_map_skips_empty_barcode` 通过

- [x] Task 4: 调用方迁移至 `get_product_barcode_map`
  - [x]SubTask 4.1: `production_plan_service.py` L268 `all_products = await product_service.get_products(db)` 改为 `barcode_map = await product_service.get_product_barcode_map(db)`，下游 `barcode_set` 和 `product_name_map` 改为基于 `barcode_map.keys()` 和 `barcode_map.items()` 构建
  - [x]SubTask 4.2: `purchase_plan_crud.py` L903 同样迁移，`product_map` 改为 `barcode_map`（下游 L918-919 的 `product_map[record.barcode]['name']` 改为 `barcode_map.get(record.barcode)`）
  - [x]验证: `validate_staging` 端点对未注册 barcode 仍返回"69码未找到产品"错误，对已注册 barcode 正确回填 product_name

- [x] Task 5: 端到端验证
  - [x]SubTask 5.1: 运行 `python -c "from fastapi_app.services import bom_service; print(dir(bom_service))"` 确认 6 个函数均可导入
  - [x]SubTask 5.2: 运行现有测试 `python -m pytest fastapi_app/tests/test_purchase_center.py -k "product_has_bom" -v` 确认向后兼容
  - [x]SubTask 5.3: 运行 `python -m pytest fastapi_app/tests/test_product.py -v` 确认 product_service 测试无回归
  - [x]SubTask 5.4: 启动应用 `python start.py` 确认无导入错误，`/purchase-center/products` 和 `/products/list` 端点正常响应

# Task Dependencies

- [Task 2] depends on [Task 1]（重导出需要 bom_service 先存在）
- [Task 4] depends on [Task 3]（调用方迁移需要新函数先存在）
- [Task 5] depends on [Task 1, 2, 3, 4]（端到端验证需要所有变更完成）
- [Task 1] 和 [Task 3] 可并行（无依赖关系）
