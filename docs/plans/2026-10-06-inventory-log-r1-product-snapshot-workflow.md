---
intent: 处置 R1 —— 产品删除不再抹掉库存流水（外键 CASCADE→SET NULL + 产品名快照），并同步补上库存台账所需的操作人/前后结存字段
success_criteria:
  - 删除产品后，其库存流水行仍在、product_id 置空、产品名/条码可从快照读出
  - 已有快照不被覆盖，只逐列补 NULL
  - 手工三路径（备货/出库/退货）写入的流水带 operator_id 与记账时序前后结存
  - 不传新参数的旧调用点行为不变（全部留 NULL）
  - Alembic 单 head；迁移幂等；downgrade 可回退
  - 库存/产品相关后端回归全绿；ruff / mypy 对本功能文件零问题
risk_level: high
auto_approve: false
branch: main
worktree: false
dirty_worktree: allow  # 工作区有并行会话未提交 WIP（含 ProjectCardItem.vue 等在途文件），本功能只提交自身文件清单
---

## 背景与决策依据

评审（`docs/designs/2026-10-06-stock-query-foreign-erp-borrowing.md`）认定的 **BLOCKER 1**：
`inventory_log.product_id` 原为 `ON DELETE CASCADE` 且 `delete_product` 还会显式 DELETE 一遍流水，
删产品 = 该产品全部库存流水永久消失，与「建立库存变动日志系统（含操作人/时间/前后数量）」的
需求直接冲突（审计能力会在某天凭空归零）。

三家主流开源 ERP 一致反着做，故采其口径：

| 项目 | 做法 |
|---|---|
| ERPNext | `Stock Ledger Entry.item_code` 是软引用（`DF.Link`），不级联删除 |
| InvenTree | 文档明示「即使 stock item 被删除，关联 tracking 记录仍保留」 |
| Odoo | `stock.move.line` 不随产品删除消失 |

**选定方案：SET NULL + 冗余产品名快照**。未选「存在流水即禁止删除产品」，因为那是行为回退
（现在能删的会突然删不掉），且 `delete_product` 已有 订单/备货/出货 三类关联计数兜底；
外键改 SET NULL 严格弱于「禁止删除」，不削弱任何既有守卫。

## Steps

- [x] **Step 1: 迁移 073 —— 台账字段 + 产品快照 + 外键换向**
action: 新增 `migrations/versions/pg_standalone_073_inventory_log_ledger_fields.py`（`down_revision = pg_standalone_072_stock_return_fk_restrict`）：加 `operator_id`(FK user, SET NULL) / `quantity_before` / `quantity_after` / `product_name` / `product_barcode` 五列与 `ix_inventory_log_operator_id`；回填 product_name/product_barcode（对现存产品是事实数据，非推断）；`DROP NOT NULL` → 换外键 `CASCADE`→`SET NULL`。全部 `IF (NOT) EXISTS` 守卫，SQL 内联直书不提取常量。
verify: `python -m alembic heads` → 单 head；`python -m alembic upgrade pg_standalone_072_stock_return_fk_restrict:pg_standalone_073_inventory_log_ledger_fields --sql` 输出顺序正确
gate: auto
  <!-- 执行记录：heads 输出唯一 head = pg_standalone_073_inventory_log_ledger_fields。
       离线 SQL 片段（072:073）依序输出 ADD COLUMN ×5 → CREATE INDEX → COMMENT ×6 →
       回填 UPDATE → DROP NOT NULL → DROP/ADD CONSTRAINT ... ON DELETE SET NULL。
       注：本仓基链在 013 处需要连库 inspect（_legacy_base_guard），故只能按区间编译，
       全链 `--sql` 离线模式本就不可用（既有局限，非本次引入）。 -->

- [x] **Step 2: ORM 同步**
action: `fastapi_app/shared_models/inventory_log.py`：`product_id` 改 `int | None` + `ondelete='SET NULL'`；加 `product_name` / `product_barcode` / `quantity_before` / `quantity_after` / `operator_id`；关系改 `Mapped[Product | None]`。刻意不声明 `operator` 关系（查询层显式 JOIN，避免默认 lazy 的 N+1）。
verify: `python -c` 打印列类型/可空/外键 ondelete
verify_result: product_id nullable=True、fk ondelete=SET NULL、五列均在
gate: auto

- [x] **Step 3: 结存推导与字段透传**
action: `fastapi_app/utils/__init__.py`：新增 `inventory_balance_bounds(current_stock_after, change_quantity) -> (before, after)`，docstring 写明「唯一合法来源是已持行锁的写入口返回值，禁止 SELECT 反查」并引用 `frappe/erpnext#51562` 作为反例；`log_inventory_change` 扩签 `operator_id / quantity_before / quantity_after / product_name / product_barcode`（全部默认 None，旧调用点不破）。
verify: 单测 `test_log_inventory_change_defaults_keep_backward_compat`
gate: auto

- [x] **Step 4: 删除路径改为快照（R1 核心）**
action: `fastapi_app/services/product_service.py::delete_product`：删掉 `delete(InventoryLog)`，改为对名下流水逐列 `coalesce` 补写 product_name/product_barcode 后再删产品；docstring 同步（原写「删除时级联删除库存日志」）。条码**只在删时快照**，写路径不带 —— 产品存在时 JOIN 即可取到，少一次热路径属性依赖。
verify: `tests/test_inventory_log_product_snapshot.py`（2 个集成用例）
gate: auto

- [x] **Step 5: 手工三路径接入操作人 + 前后结存**
action: `stock_in_service`(3) / `stock_out_service`(4) / `stock_return_service`(2) 共 9 个写点：捕获写入口返回值 `updated`，`inventory_balance_bounds(updated.current_stock, delta)` 得前后结存，带上 `product_name`/`operator_id`；`operator_id` 由端点已有的 `_user: User` 透传（`stock.py` 六个端点、`stock_return.py` 两个端点、`auxiliary.py` 批量两个端点 → `auxiliary_service` 编排函数）。所有新参数均为带默认值的关键字参数，位置调用方不受影响。
verify: `tests/test_stock.py` + `tests/test_stock_return_flow.py` + `fastapi_app/tests/test_stock_negative_policy*.py`
gate: auto
  <!-- 执行记录：一次真实回归 —— 首个版本在写路径同时读 `updated.barcode`，
       导致 test_stock_negative_policy_repo_wide 用 SimpleNamespace 替身（只有 name/current_stock）
       的用例 AttributeError。修法不是改别人的测试替身（该文件是并行会话在途文件），
       而是收掉热路径上的 barcode 依赖：写路径只带 name，条码改由删时 coalesce 补齐。
       既消除耦合又保留了「产品删除后条码可查」的能力。 -->

- [x] **Step 6: 回归测试**
action: 新增 `tests/test_inventory_log_product_snapshot.py`（7 例）：结存推导 / 助手字段透传 / 旧调用点默认值 / 删产品后流水保留且快照可读 / 已有快照不被覆盖 / 迁移幂等与外键换向守卫 / downgrade 顺序守卫。迁移守卫用 `ast.get_source_segment` 取函数体 —— 初版用文本 `index` 命中了 docstring 里引用的 `ON DELETE CASCADE` 原文，得出相反结论（AGENTS.md §6 记录过的同款解析伪影）。
verify: `python -m pytest tests/test_inventory_log_product_snapshot.py -q` → 7 passed
gate: auto

- [x] **Step 7: 门禁与静态检查**
action: ruff（本功能 12 文件）→ mypy（6 个源文件）→ 后端回归 10 个相关文件 → quality_gate。
verify_result: |
    ruff: All checks passed
    mypy: Success: no issues found in 6 source files
    pytest: 221 passed, 2 failed
      · 2 个失败均为**既有**分歧（已用 `git show HEAD:` 取证）：HEAD 版源码早已是
        `cancel_stockreturn_core`，而并行会话在途的测试仍期望 `delete_stockreturn_core`
        （`test_stock_optimistic_lock_unification.py:69` 与
        `test_stock_negative_policy_repo_wide.py` 的用例）。与本功能无关，不擅自修改他人文件。
    quality_gate: 唯一 REGRESS = 「前端巨型 Vue 组件 7 处（基线 6）」= `ProjectCardItem.vue` 409 行，
      该文件是并行会话在途 WIP；本功能未改动任何 .vue 文件。
      其余项全 OK，含「Alembic 迁移图状：head/root 一致 0 违反」。
gate: auto

- [ ] **Step 8: 生产迁移执行与页面验收**
action: 需人工授权后执行：`python -m alembic upgrade head`（先在备机/备份上验证 `downgrade` 往返）→ 重启 `erp-prod` → 冒烟：产品删除后 `GET /aux/inventory-logs/{product_id}` 类历史仍可查（本功能暂无新端点）。
verify:
  type: human-review
  check: 用户确认迁移已在生产执行且历史可查
gate: human

## 后续未定项（评审中列出、本轮未做）

| 编号 | 事项 | 状态 |
|---|---|---|
| R2 | `related_id VARCHAR(50)` 在 FIFO 拆多订单时会溢出 → 出货 500 | 待批准（需迁移改列类型或改结构化 voucher_type/no） |
| R3 | 加 `posting_date`（业务日期）列，明确「记账时序结存 ≠ 业务日期顺序」 | 待批准（影响 `/stock-query/change-logs` 契约） |
| R4 | 加 `stockin_id`（批次回链），让变动历史可按批次切 | 待批准（可并入 073，迁移尚未执行） |
| R5 | `change_type` 收敛为常量码表（现「抵扣」有 3 个名字：订单抵扣/取消抵扣/抵扣回滚） | 待批准（**应在写点线程化之前定**，否则改两遍） |
| R6 | 加 `CHECK (quantity_after = quantity_before + change_quantity)` 让结存自证 | 待批准（可并入 073） |

> 注：迁移 073 **尚未在任何环境执行**，R3/R4/R6 若获批准仍可合并进同一迁移，不必新增 074。
