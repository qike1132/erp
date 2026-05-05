# BUG-SYNC-ORDER-TO-PURCHASE 修复记录

- **修复时间**: 2026-05-04 22:00
- **Git Commit**: 2c99dfbdbd2a4a9f322dd52961799b94d6347eb0
- **根因分析**: 
  1. **直接原因**: `get_unprocessed_orders()` 查询 `PurchaseOrder` 表，但 `sync_order_create()` 仅在 4 条订单创建路径中的 2 条被调用，导致 72.7% (9/12) 的客户订单数据丢失
  2. **设计缺陷**: 采用"主动推送"(active sync)架构，任何路径遗漏 sync 调用即导致数据丢失
  3. **静默失败**: `sync_order_create` 的异常被 `try/except` 吞没，同步失败无任何告警
  4. **数据模型错配**: PurchaseOrder 表无法表达"一个采购订单来自多个客户订单"的关系
- **影响范围**: 
  - 客户订单→采购中心的数据同步完全失效
  - 一键生成采购订单存在 N+1 查询性能问题
  - `generate_purchase_order_no()` 使用 `FOR UPDATE` + 聚合函数，PostgreSQL 不兼容
  - `create_purchase_order()` 使用 `note` 字段名，但模型字段名为 `remark`
  - 删除客户订单时遗留孤立 pending PurchaseOrder 记录
- **修复方案**:
  1. **架构重构**: 采购中心改为直接查询 `Order` 表（被动读取），移除 `sync_order_create/update/delete` 全部调用链
  2. **一键生成重写**: 批量预加载 BOM 数据（消除 N+1），传递 `source_order_ids` 实现可追溯性
  3. **孤立记录清理**: 删除客户订单时自动清理关联的 pending PurchaseOrder
  4. **PostgreSQL 兼容**: 移除 `func.count().with_for_update()`，修正 `note`→`remark`
- **修改文件**:
  - `fastapi_app/services/purchase_order_service.py` — 重写 `get_unprocessed_orders()`，修复 FOR UPDATE + remark
  - `fastapi_app/api/v1/endpoints/purchase_center/order_routes.py` — 重写一键生成，批量BOM预加载，状态校验
  - `fastapi_app/services/order_service.py` — 移除 sync 调用，添加孤立PO清理
  - `fastapi_app/services/approval_service.py` — 移除 sync 调用，添加孤立PO清理
  - `fastapi_app/api/v1/endpoints/auxiliary.py` — 移除 sync 调用
- **验证结果**: L1~L5 全部通过
  - L1: 单元测试 7/7 PASS
  - L2: DB count=11 匹配 API count=11，无孤立记录，BOM一致性通过
  - L3: 响应结构完整，分页正常，supplier_id已移除
  - L4: 一键生成含 source_order_ids 可追溯
  - L5: 平均延迟 72.6ms（阈值 500ms），bandit 无高/中危漏洞
- **服务状态**: 已重启 PID 15852→10760，健康检查 3/3 通过 (http://localhost:5002/api/health)
- **死代码**: `fastapi_app/services/order_purchase_sync.py` 已无任何 import，可安全删除
