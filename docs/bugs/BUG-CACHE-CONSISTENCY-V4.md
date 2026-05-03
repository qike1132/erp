# BUG-CACHE-CONSISTENCY-V4 修复记录

- **修复时间**: 2026-05-01 16:36:07
- **根因分析**: CacheDomain.PRODUCT 自枚举创建以来从未被任何 invalidation 调用；CacheDomain.STOCKOUT 枚举值及 pattern 映射完全缺失；StockService 内部 6 处突变未包含对应子域（STOCKIN/STOCKOUT）
- **影响范围**: products:all 缓存 CRUD 后失效最长 60s；stockouts:list 缓存永不失效；stockins:list 在 StockService 直接调用下不失效
- **修复方案**: 
  - cache.py: 新增 STOCKOUT 枚举值 + pattern stockouts:* + ALL 更新
  - product_service.py: 三处 invalidation 添加 PRODUCT|STOCKIN (共+6 个域引用)
  - stock_service.py: 入库 3 处 +STOCKIN, 出库 3 处 +STOCKOUT (共+6 个域引用)
- **验证结果**: ruff 0 新增错误 / mypy 0 新增错误 ✅
- **变更统计**: 3 文件, 12 行变更
