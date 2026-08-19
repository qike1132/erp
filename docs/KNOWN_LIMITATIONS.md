# 已知限制与 TODO 跟踪

> 本文档记录代码库中所有 TODO/FIXME 注释，按类别分组，附推荐处理方式。
> 最后更新：2026-08-16

## 1. TODO(multi-sku-order) — 多 SKU 订单模型改造（21 处）

**背景**：当前 `Order` 模型使用单一 `product_id`/`quantity` 字段表示订单内容。
未来需改造为 `Order → OrderItem` 一对多关系（多 SKU），届时所有直接读写
`order.product_id`/`order.quantity`/`order.order_type`/`order.country` 的代码
需改为按 `OrderItem` 维度遍历。

**状态**：待业务方确认多 SKU spec 后统一改造，当前依赖"首 item 兼容值"正常运行。

**推荐处理**：创建专项 issue `multi-sku-order-refactor`，在 spec 设计阶段统一处理。

| 文件 | 行 | 说明 |
|------|-----|------|
| `shared_models/order.py` | 32 | 模型层：order.quantity 兼容值定义 |
| `services/order_crud.py` | 7 | 模块级标注 |
| `services/order_crud.py` | 632 | 读取/修改 order.quantity 语义变更 |
| `services/order_crud.py` | 644 | order.product_id 库存调整 |
| `services/approval_service.py` | 7 | 模块级标注 |
| `services/approval_service.py` | 321 | 审批中读写 quantity/product_id |
| `services/stock_service.py` | 489 | 出库时 order_type/country 兼容值 |
| `services/stock_service.py` | 1405 | 按 order_type 分组 sum(quantity) |
| `services/order_batch_service.py` | 3 | keyword 搜索 JOIN Product 依赖 |
| `services/purchase_order_query.py` | 185 | 查询中 product_id/quantity 兼容值 |
| `services/purchase_order_query.py` | 466 | 同上 |
| `services/purchase_order_query.py` | 774 | 同上 |
| `services/purchase_order_query.py` | 871 | 同上 |
| `services/inventory_service.py` | 7 | 模块级标注 |
| `shared/stock_crud_service.py` | 8 | 模块级标注 |
| `shared/report_data_service.py` | 6 | 模块级标注 |
| `shared/report_data_service.py` | 141 | 抵扣备注按 quantity 计算 |
| `shared/report_data_service.py` | 147 | 报表 product.name/quantity |
| `shared/shipment_calc.py` | 44 | 出运计算遍历累加 |
| `api/v1/endpoints/order.py` | 242 | 端点层读取 quantity/order_type/country |

## 2. TODO: BOM filling 结构（1 处）

| 文件 | 行 | 说明 |
|------|-----|------|
| `services/bom_service.py` | 175 | filling 为 1:1 关系（cotton_usage 字段 + 多字段日志），结构与 fabric/accessory 的 1:N 不同，后续统一为 1:N 时需改造 |

**推荐处理**：创建 issue `bom-filling-unify`，在 BOM 模块重构时处理。

## 3. TODO: 备份恢复测试（1 处）

| 文件 | 行 | 说明 |
|------|-----|------|
| `services/backup_recovery_test_service.py` | 456 | 当前恢复测试仅校验文件存在性，未实现基于备份 manifest / SQL dump 的真实可恢复性验证 |

**推荐处理**：创建 issue `backup-restore-verification`，在备份模块增强时实现。

## 4. TODO: 备份 checksum 校验（1 处）

| 文件 | 行 | 说明 |
|------|-----|------|
| `services/backup/format_strategy.py` | 457 | 通过 storage 端口增加 checksum 校验，确保备份文件完整性 |

**推荐处理**：创建 issue `backup-checksum-verify`，在 storage 端口扩展时实现。

## 5. TODO: 采购中心外部同步（1 处）

| 文件 | 行 | 说明 |
|------|-----|------|
| `api/v1/endpoints/purchase_center/customer_routes.py` | 97 | 待业务方明确外部同步目标系统后实现写入逻辑（更新 sync_time 或推送至采购中心服务） |

**推荐处理**：待业务方确认目标系统后创建 issue 实现。

---

## 总结

| 类别 | 数量 | 处理方式 |
|------|------|----------|
| multi-sku-order | 21 | 保留，待专项 spec 改造 |
| BOM filling 结构 | 1 | 保留，待 BOM 重构 |
| 备份恢复测试 | 1 | 保留，待备份增强 |
| 备份 checksum | 1 | 保留，待 storage 扩展 |
| 采购中心同步 | 1 | 保留，待业务确认 |
| **合计** | **25** | **全部保留，无可立即处理的项** |

> 注：tasks.md 原预估 118 处为误报（将格式字符串 `PO-YYYYMMDD-XXXX`、
> `TodoItem` 类名等匹配为 TODO）。经精确扫描，实际 TODO 注释仅 25 处，
> 全部为合理的架构标记或待决事项，无需立即修改。