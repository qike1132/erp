# 采购明细与 BOM 实时同步（取代生成时快照）

- 日期：2026-11-11
- 状态：待用户复核
- 相关页面：`/purchase`（工厂内部订单、供应商采购订单）、`/product`（BOM 编辑）

## 背景

采购明细（`purchase_order_item`）由「一键生成 / 自动生成」按**生成那一刻的 BOM** 落库，
之后 BOM 的任何修改都不会回写已生成的采购单。已发生两次生产事故：

- `PO-2611-005`：BOM 换成正式值后，21 条明细仍是旧快照（数量全为 50/5000）；
- `PO-2611-007`：BOM 在 11-11 08:02–08:05 把绿色超柔改成「身体/脚底各 1.0」并删除蓝色超柔，
  采购单仍是 11-10 22:01 的快照（绿色超柔 0.005×10000=50、蓝色超柔孤儿行），
  汇总页出现「推算 20000 / 实际 50」与「身体/脚底合并不拆行」。

结论：快照式落库与「BOM 为唯一真源」的业务口径冲突，必须改为**BOM 变更后实时同步
pending 采购单明细**。

## 用户裁决

1. **BOM 优先**：同步按新 BOM 重算并覆盖数量；`loss_rate`、`unit_price`、备注等非数量字段保留。
2. **仅 `status='pending'`** 的采购单同步；`confirmed` / `completed` 永不动。
3. **BOM 保存成功后即时回写数据库**（post-commit 回调），不做仅展示的实时换算。
4. **上线时全量校正**所有 pending 单，提供 dry-run 报告与幂等执行。
5. **部位拆行改为 BOM 感知**：BOM 有部位就拆行；无部位行（辅料）单独成行、不阻塞拆行。
6. **BOM 已不存在的明细行一律删除**（含手工加行）；写审计日志，backfill dry-run 先列出待删行。
7. **并发保护**：采购单新增 `items_version`；同步与用户编辑都递增；保存携带旧版本不一致返回 409，
   前端提示「BOM 已更新，请刷新后重编辑」。

## 非目标

- 不改变生成路径的落单分组/去重规则（`uq_po_pending_dedup` 等）。
- 不引入 BOM 版本历史，不做读取时实时换算（单一真相源是数据库里的采购明细）。
- 不同步 confirmed/completed 单；不对其做任何历史数据改写。

## 数据流

```
BOM 保存（bom_service）──提交成功──▶ post-commit 回调
   ├─ BOM 为空：撤销该产品 pending 单（现状）→ auto_generate 兜底
   └─ BOM 非空：sync_pending_po_items(product_id)
                    ├─ 找出受影响 pending 单（BOM 感知）
                    ├─ 以 PO 为单位重建目标明细行
                    ├─ 保留 loss_rate/unit_price/remark（按物料键继承）
                    ├─ 增/删/改 + 重算金额 + items_version+1 + 审计日志
                    └─ 失败仅记日志，下次保存 / backfill 兜底
              └─ 随后照旧 auto_generate（未处理订单补生成）
```

## 同步算法（以 PO 为单位重建）

明细表**没有 product_id**，同一张 PO 可跨多 SKU；因此同步必须以整张 PO 为事务单元，
否则无法区分不同 SKU/角色落下的同键物料行（Opus 审核 H1/H2）。

1. **取该 PO 的逐 SKU 快照**：`purchase_order_sku`（产品名/条码/order_qty）；快照缺失的
   旧单回退 `fetch_po_sku_lines_map`（由源订单/备货推导逐 SKU 行）。SKU → product_id
   解析复用撤销链的三层回退（`fetch_po_sku_pids_map`：OrderItem 明细 → po_sku 名称精确匹配
   → 条码/名称兜底）。任一 SKU 解析失败 → **跳过该单并记入报告**，绝不按不完整 BOM 重写（H4）。
2. **重算目标行集合**：抽取生成路径的「BOM 行 → 明细行」为共享函数（复用
   `_material_row` 口径）。逐 SKU、逐角色作用域展开面料/辅料（过滤填充物），
   盲盒 SKU 复用 `allocate_scope_quantities`；数量 = `round_qty(usage × 角色分配数量)`；
   同时产出 `part_name`、`supplier_name`、`category`、`unit_usage=usage`。
3. **字段继承**：为现有明细建立 `(物料, 规格, 单位, 部位, 供应商, 类别)` → 队列
   （按 id 升序）的 `(loss_rate, unit_price, remark)` 继承池；新目标行按同键依次领取，
   领完即丢弃（记日志）。无法按部位匹配时回退 `(物料, 规格, 单位, 供应商, 类别)`。
4. **替换**：删除该 PO 全部旧明细，写入目标行（用批量 `INSERT` 保持确定性顺序）。
   该策略避开同键多行「多对多匹配」歧义；代价是明细 id 会变化——由 `items_version`
   拦住基于旧 id 的用户保存。**无变化短路**：先将目标行与现有行归一为规范序列
   `(物料, 规格, 单位, 部位, 供应商, 类别, 数量, unit_usage)` 排序比较，完全一致则跳过
   重建（不删不插、不递增版本），避免每次保存 BOM 都抖动明细 id。
5. **重算金额**：每行 `_recalc_item_total_price`（HALF-UP、订单级 `spare_rate` 回退），
   订单 `total_amount = Σ行金额`；`items_version += 1`（仅在实际重建时）。
6. **审计**：写一条 `ModificationLog(target_type='purchase_order', field_name='bom_sync')`，
   `new_value` 为 JSON 摘要（增/删/改行数 + 删除行快照：物料/规格/部位/数量/供应商），
   便于事后核对（PO-2611 事故正是靠人工 diff 才被发现）。
7. **并发**：事务内 `SELECT ... FOR UPDATE` 锁 PO 并复核 `status='pending'`；期间已变
   completed/confirmed → 跳过。需要校验 `items_version` 的写接口：
   `save_factory_summary_edits`（汇总弹窗保存）、`update_purchase_order` 带 items 的全量保存、
   `_update_item_prices`（订单详情补录单价）；请求携带旧版本、不一致返回 409
   （错误码 `ITEMS_VERSION_CONFLICT`）。`complete/batch-complete` 只改状态，不校验。

## 受影响采购单识别

对 `status='pending'` 的采购单批量构建 `po_id → [product_id...]`（复用
`fetch_po_sku_pids_map`，覆盖客户订单与备货来源、含名称/条码回退），筛出包含
被修改 product_id 的单。解析失败的单进入报告，不静默跳过。
一次 BOM 保存影响超过 20 张单时打印 warning（便于观察批量化风险）。

## 部位拆行（BOM 感知）

现状 `_split_parts_by_group` 要求「该 PO 全部明细都有部位」，任一缺失（辅料、旧快照）
整组退化为合并模式——这是「身体/脚底」合并成一行的直接原因。

改为：**按 BOM 判定**——该 PO 相关 BOM 行中存在非空部位即启用拆行；匹配时：

- BOM 行有部位 → 用 `items_map_by_part` 精确匹配（含部位键）；
- BOM 行无部位 → 用仅含物料键的 `items_map` 匹配（不再要求整单都有部位）。

聚合键仍按 `part_key = 部位 or ''`。同步保证明细与 BOM 同形后，前端
`perSkuRows` 的坐标（coord）不会漂移；需同步跑
`fastapi_app/tests/services/test_factory_summary_multisku.py` 全族与前端
`perSkuRows` / `useSummaryModal` 测试。历史未同步单（backfill 前）若明细缺部位，
会以「推算 vs 实际」差异横幅暴露，而不再静默合并。

## BOM 保存触发与顺序

`_run_bom_saved`（`fastapi_app/services/purchase/_auto_generate.py`）内：

1. BOM 删空 → 走既有撤销链，**跳过同步**（撤销后由 auto_generate 重新生成）；
2. BOM 非空 → 先同步受影响 pending 单，再执行既有 `_run_auto_generate()`。

同步逐单使用独立短事务，失败隔离；BOM 保存本身永不因同步失败而失败。
同步与撤销互斥，避免「先同步成新行、随后整单被撤销重建」的抖动。

## 数据库迁移

`purchase_order` 新增 `items_version INTEGER NOT NULL DEFAULT 0`（手写迁移，单 head；
**不得对生产库 autogenerate**）。本轮不新增 `is_manual` 列（裁决 6：BOM 唯一真源）。

## 前端改动

- 汇总接口在 group/单级返回 `items_version`；汇总保存、订单明细保存、单价补录请求携带该值。
- 409 → 弹窗提示「BOM 已更新，采购明细已刷新，请重新编辑」，并重新拉取汇总数据。
- 工厂页「产品部位」列在有部位时按行展示；无部位行留空（与 BOM 一致）。

## 上线 backfill

脚本 `scripts/sync_pending_po_items.py`：

- `--dry-run`（默认）：输出四类清单——① 数量变更行 ② 新增行 ③ 删除行（**高亮疑似手工行**：
  无法与任何 BOM 行匹配既有键的行）④ SKU/产品解析失败单；另打印受影响单总数。
- `--apply --product-id N`（可选限制范围）：执行同一同步服务，幂等（重复执行结果一致，
  每次生效则 `items_version+1`）。
- 执行顺序：迁移 →（部署后端）→ dry-run 复核 → apply → 校验汇总两页差异为 0。

## 测试计划

后端：

- 同步服务：多 SKU 跨客户单、盲盒角色分配、同物料多部位、辅料无部位、孤儿行删除、
  非 BOM 手工行删除、`loss_rate/unit_price` 继承、`unit_usage` 同步、金额与总额重算、
  `items_version` 递增。
- 触发：BOM 保存后 pending 单被同步；completed/confirmed 不变；BOM 删空走撤销不同步；
  解析失败单跳过且报告。
- 并发：旧版本保存返回 409；同步与用户保存串行后状态一致。
- 拆行：含无部位辅料 + 同物料跨部位两行时，工厂/供应商汇总按 BOM 拆分且数量相等。
- backfill：dry-run 四类清单、apply 幂等、前后对比。

前端：

- 两页一致性模拟测试扩展（BOM 实时同步后的数据形态：有部位拆行、无部位辅料单独行）。
- 409 冲突提示与刷新流程。

## 风险与回滚

- 重建式同步会删除非 BOM 行——由审计日志 + dry-run 报告兜底；回滚依赖上线前数据库备份。
- 明细 id 变化可能影响外部引用（来料登记仅引用 PO，不引用 item；已核实迁移 FK 仅 order_id）。
- 若同步逻辑异常导致错误删行：停止触发（回滚 BOM 保存回调代码）、按 `ModificationLog`
  的 `bom_sync` 摘要与备份恢复。

## 验收标准

1. 修改 BOM（改用量/增删物料/加部位）并保存后，相关 pending 单明细在同一请求内更新；
   工厂内部订单与供应商采购订单两页数量逐项一致。
2. `PO-2611-007` 类型单据：绿色超柔拆成「身体 10000 / 脚底 10000」两行，无差异横幅。
3. completed/confirmed 单任何字段不变。
4. 用户基于旧版本保存被 409 拦截并提示刷新，不发生静默覆盖。
5. backfill dry-run 报告可读、apply 幂等；上线后全部 pending 单差异为 0。
