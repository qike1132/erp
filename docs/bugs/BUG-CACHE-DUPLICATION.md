# BUG-CACHE-DUPLICATION 缓存失效逻辑重复修复记录

- **修复时间**: 2026-04-30
- **Git Commit**: ca097be (working tree)
- **根因分析**: `invalidate_cache("orders:*")` + `invalidate_cache("inventory:*")` 模式在 7 个文件、18+ 处重复出现，缺乏统一抽象。不同文件中参数顺序不一致（order_service 先 orders 后 inventory，stock_service 反之），且 approval.py 的 reject 函数遗漏了 inventory:* 缓存失效。
- **影响范围**: fastapi_app/core/cache.py, services/order_service.py, services/stock_service.py, api/v1/endpoints/approval.py, api/v1/endpoints/auxiliary.py, api/v1/endpoints/product.py, api/v1/endpoints/order.py
- **修复方案**:
  1. 在 cache.py 中引入 `CacheDomain` Flag 枚举，支持按位或组合（ORDER | INVENTORY | STOCKIN | PRODUCT | CUSTOMER | SEARCH）
  2. 实现 `invalidate_related_caches(domains: CacheDomain)` 函数，集中管理缓存域→pattern 映射
  3. 替换所有 19 处直接 `invalidate_cache()` 调用为语义化的 `invalidate_related_caches(CacheDomain.XXX)` 调用
  4. 修复 approval.py reject 函数遗漏 inventory:* 缓存失效的 bug
- **验证结果**:
  - 417 个测试通过（1 个预先存在的失败与本次修改无关）
  - Python 语法编译检查通过
  - Bandit 安全扫描 0 高/中危问题
  - 缓存失效行为完全等价（`invalidate_related_caches` 内部仍调用 `invalidate_cache`）
