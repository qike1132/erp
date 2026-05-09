# BUG-PURCHASE-PLAN-CACHE-001 修复记录

- **修复时间**: 2026-05-07 14:21:07
- **Git Commit**: 9955fe3c63f7b9c41ee78db77d20a649225c23a8
- **现象**: 用户在采购计划页面新建每日计划后，"每日计划"和"月度汇总"模块均不显示新建数据
- **根因分析**: 
  1. [P0] 后端 @cache_result 装饰器产生的 pp:monthly/* 和 pp:summary/* 缓存，在7处写入操作(create_plan/update_plan/delete_plan/update_detail/delete_detail/add_details/confirm_staging)后未失效，前端重新请求时返回旧缓存数据(30s~120s)
  2. [P1] 前端 CreateShipmentPlanDialog 手动创建模式中 barcode 硬编码为空字符串，用户选择产品后条码信息丢失
- **影响范围**: purchase_plan_service.py 中7个写入函数 + CreateShipmentPlanDialog.vue 表单提交
- **修复方案**:
  1. 新增 _invalidate_plan_caches() 统一缓存失效函数，替代原 _invalidate_fifo_cache 调用，同时清除 FIFO + pp:monthly + pp:summary 三类缓存
  2. 前端 DetailLine 接口增加 barcode 字段，selectProduct 赋值 barcode，handleSubmit 传递实际 barcode
- **验证结果**: 19/19 pytest passed, Bandit 0 HIGH, cache key wildcard match verified
- **健康端点**: http://localhost:5002/health
