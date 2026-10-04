# ERP 重写决策：终止重写，转增量改造

**日期**：2026-10-04
**状态**：用户已确认（路线 1）
**替代**：`2026-10-04-erp-rewrite-design.md`（保留为诊断参考，处方作废）

---

## 决定

**放弃全量重写。** 改写规格中经对抗性评审确认的真实缺口，以增量方式在现有
Vue 3 + FastAPI 系统上落地。

## 为什么放弃重写（评审核验的事实）

1. **一处核心前提被证伪**：`case_movement.quantity` 的 `CHECK (quantity > 0)`
   在迁移 062 第 113-114 行真实存在且已应用于生产。重写规格只查了 ORM 模型
   未查数据库 DDL。
2. **并发方案技术上不成立**：`SELECT SUM(...) FOR UPDATE` 是 PostgreSQL 非法
   SQL；锁已有流水行挡不住并发插入（幻读）；`EXCLUDE gist` 与"不存余额"
   自相矛盾。而现行系统三层防线（`stock_concurrency.py` 锁 Product 行 +
   原子条件 UPDATE + 迁移 061 `ck_product_current_stock_nonneg`）正确在跑。
3. **重写规格的多数支柱已满足或已有增量路径**：金额 NUMERIC 已在用；
   case_movement / daily_production_record 日期已分列；`inventory_reconcile.py`
   每日对账已存在；权限已有 4 个对齐测试文件 24 个用例。
4. **重写独有的部分恰是风险最高、论证最弱的**：React 换栈（扔掉 3491 个测试
   与 15 轮审计战场修复）、2000 行元数据引擎（缓解措施"人工设计骨架"与
   "无人类审阅"约束直接矛盾）、业务流水清零（漏了期初库存迁移）。
5. **违反本项目生存法则**（AGENTS.md §0：改动小步、可回滚）。

## 增量改造清单（按优先级）

### P0 — 活缺陷，立即修

1. **beile_order 权限码错配**：`useBeileOrders.ts:497-499` 前端检查
   `beile_order_confirm / beile_order_export / beile_order_print`，后两者
   在后端零存在；实际导出端点要求 `product_manage / purchase_center_manage`。
   被授予 beile_order_export 的用户看得到按钮、点击 403。
   与 2026-09-30 修复的 22+5 处错配同类。

### P1 — 真缺口的约束补齐（天级）

2. **inventory_log 幂等约束**：`related_id`（String）无 UNIQUE。应用层已有
   去重护栏（`batch_import_core.py:125-173`，2026-10-03 修）盖住已知路径，
   但 DB 层仍缺兜底。方案：新增规范化幂等列（ref_type/ref_id/sku 组合）+
   唯一约束 + 迁移，参照迁移 062 对 case_movement 的做法。
3. **inventory_log 业务日期分列**：`change_date` 单列混用系统/业务时间。
   参照 case_movement（movement_date + create_time）分列。汇总口径只读
   业务日期列。
4. **权限码单源**：收进单一 Python 常量模块 + 生成 TS 常量文件，扩展现有
   4 个对齐测试。不引入实体元数据派生（覆盖不了动作码/页面码/超管门槛
   这 80% 的真实权限面）。

### P2 — 已批准待实施

5. **OpenAPI 生成前端类型**：`2026-10-04-openapi-generated-frontend-types-design.md`
   已批准。接口维度覆盖 80%，DTO 维度 17%（79/460 无损替换），
   `list[dict]` 刻意不动（收紧会剥掉 5 个注入字段）。

### P3 — 结构改善，不阻塞

6. **purchase/ 目录归拢**：顶层 22 + 子包 7 = 29 个碎片文件，搬入
   `services/purchase/` 子包 + 域边界 import 检查脚本。
7. **约束违反测试推广**：为 061/062 的 CHECK/UNIQUE 补"违反即报错"测试
   （评审确认这是重写规格里值得保留的思想）。

## 执行原则

- 每项独立提交、独立可回滚
- 改前 `git status` 确认无并发会话工作
- 每步跑全量门禁（quality_gate + mypy + vue-tsc + pytest）
- P0 的 beile 错配修复需同步检查是否还有同类（grep 全部前端 hasPermission
  码与后端 require_permission 码的差集）
