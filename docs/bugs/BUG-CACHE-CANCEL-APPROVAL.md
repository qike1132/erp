# BUG-CACHE-CANCEL-APPROVAL 修复记录

- **修复时间**: 2026-04-30 23:05
- **Git Commit**: ca097be (修复前)
- **根因分析**: 两处修改订单/审批状态的路径在 commit 后未调用 invalidate_related_caches，导致 is_locked 状态缓存过期最长 60s(Redis TTL)
- **影响范围**: 
  - P2-01: cancel_approval 端点取消审批后，订单列表中 is_locked 字段缓存不一致
  - P2-02: delete_order 非管理员路径提交删除审批后，订单锁定状态缓存不一致
- **修复方案**:
  - order.py:138 - 在 cancel_approval 服务调用后添加 `await invalidate_related_caches(CacheDomain.ORDER_AND_INVENTORY)`
  - order_service.py:451 - 在非管理员删除审批路径的 db.commit() 后添加 `await invalidate_related_caches(CacheDomain.ORDER_AND_INVENTORY)`
- **验证结果**: 
  - 语法检查: PASS
  - 单元/集成测试: 40/41 PASSED (1 pre-existing failure: test_my_approvals)
  - Bandit 安全扫描: 0 HIGH, 0 MEDIUM
- **健康端点**: http://localhost:5002/health
