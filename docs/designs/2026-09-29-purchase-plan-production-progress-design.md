---
design_type: feature
created_at: 2026-09-29
---

# 采购计划页「进度」口径：已出货 → 已生产

> 状态：**待评审**（未决问题见 §7，需你拍板后才进入实现）
> 日期：2026-09-29
> 前置：本页 UI 已于同日重构为月历 + 右栏双态（commit `b8a3c018`），本稿只动口径，不再动布局

## Intent Contract

```yaml
intent: 把 /purchase-plan（桌面）与 /shipment（移动端）的进度口径从「已出货」换成「已生产」，数据源为 daily_production_record；KPI、月历格子状态与进度条、风险/延期判定、当日明细、月度汇总列、导出 CSV 全线跟随
constraints:
  - 生产量按现有 allocate_fifo 摊到计划行：分组键从 (客户, 产品) 改为 产品 —— 生产记录没有客户字段
  - 三部门（充棉部/手工部/包装部）相加，不按部门过滤。依据：daily_production_service.py:374 的月度汇总口径
  - 关联键用 product_id，不用 barcode。依据：daily_production_record.barcode 是 NOT NULL DEFAULT ''（可为空串），而 stock_inventory_service.py 既有做法就是按 product_id 聚合并 WHERE product_id IS NOT NULL
  - 只统计「出现在该月计划里」的产品（按 product_id 集合），不把工厂当月全部产量算进来
  - 客户筛选（月度汇总 Tab 的 chips）跟随，且**由 FIFO 摊派自然产生**：同一产品的产量按 plan_date 先后摊给各客户的计划行。注意这与问卷里「按该客户计划涉及的产品集合汇总」的字面写法**不同** —— 后者会让每个客户都显示该产品的全部产量（可远超其自身计划量），一旦选了「摊到行」，客户级数字只能来自摊派，否则行级与客户级两个数会自相矛盾
  - 弹窗里真实的「出货记录」子页签、/plans/shipment/* 流水查询一律不动：那是真实出货流水，不是进度
  - daily_production_record 只读，不引入新写路径；不动 FIFO 的写路径（_update_shipped_qty / recalc）
  - 保持 fifo_degraded 的既有降级语义（查询不可用时显式标记，而非返回全 0 误导值）
success_criteria:
  - 3 个端点（/plans/monthly-aggregated、/plans/monthly、/plans/day-details）的进度字段改为生产口径，字段名 shipped_* → produced_*
  - 缓存版本号全部上调，改完立即生效，不出现「改完还是旧数」
  - 前端两处（桌面 /purchase-plan、移动端 MShipmentView）措辞统一为已生产/待生产，含导出 CSV 表头
  - 后端单测覆盖：摊派算法、窗口边界、无生产记录、product_id 为空
  - 前端现有 717 用例不回归；quality_gate.py PASS
risk_level: medium
```

## Verification Contract

```yaml
verify_steps:
  - run tests: python -m pytest fastapi_app/tests/test_purchase_plan.py -v
  - run tests: npm test --prefix frontend-vite
  - check: quality_gate.py PASS（单 .vue ≤ 400 行、函数 ≤ 80 行等）
  - check: 构造同一产品「跨客户 + 跨月」的生产记录，断言 FIFO 摊派结果符合 §3 的公式
  - confirm: 人工刷新 /purchase-plan 与移动端 /shipment，核对 KPI 与格子状态是否随生产数据变化
```

## Governance Contract

```yaml
approval_gates:
  - 本设计稿评审（当前阶段）
  - §7 未决问题定案（取数窗口）
  - 实施完成后 code-review
```

---

## 1. 背景

本页的「进度」目前全部来自**出货记录按 (客户, 产品) 分组、再按 plan_date FIFO 摊派**得到的 `shipped_qty`。三个聚合端点共用同一个收口函数：

```
_build_fifo_shipped_map_from_rows(db, rows, plan_month) → {detail_id: allocated_qty}
    └── _get_shipped_fifo_map_safe(...)  ← 降级包装，异常时返回 {} + fifo_degraded=True
          └── allocate_fifo(plan_details, details_by_key, shipped_by_key)
```

用户的诉求是这套进度改以**生产**为准。好消息是这个收口点只有一个，换来源有干净的位置。

## 2. 口径定义

**产品级生产总量**（单个 product_id）：

```
produced(product_id) = SUM(daily_production_record.quantity)
                       WHERE product_id = :pid
                         AND production_date BETWEEN :window_start AND :window_end
```

不按 department 过滤（三部门相加）。`product_id IS NULL` 的行无法关联，丢弃。

**客户级/筛选后的口径**：不做额外过滤 —— 由 §3 的 FIFO 摊派自然产生（摊派结果落在哪个客户的计划行上，就算给谁）。

## 3. 摊派算法

复用 `allocate_fifo`，只换分组键与累计量：

| | 出货（现状） | 生产（改后） |
|---|---|---|
| 分组键 | `(customer_name, product_name)` | `product_id` |
| 累计量 | 该组出货净量 `SUM(quantity - returned_quantity)`，JOIN StockOut | 该 product_id 的 `SUM(quantity)`，JOIN daily_production_record |
| 排序 | `plan_date ASC` | 同（算法内部已按 plan_date 排序） |

算法本身（累计分配法：累计量按 plan_date 依次填满最早的计划）**一行不改**。只需把 `fifo_allocation.allocate_fifo` 的 `details_by_key` 类型注解从 `dict[tuple[str, str], list]` 放宽为 `dict[Hashable, list]` —— 纯类型注解放宽，无行为变化。

**已知代价（用户已确认接受）**：生产记录没有客户，同产品的产量会按 plan_date 先后摊给不同客户。某个客户可能显示「已生产 100」，而这 100 其实是别家订单的产出。这是「近似」的必然结果，不是 bug。

**客户级数字的推论**：既然摊到行，客户级（KPI 在选中某客户时、月度汇总的客户合计）就只能是「该客户名下计划行摊到的产量之和」。这**不等于**「该客户计划涉及产品的全部产量」—— 后者会超出该客户自己的计划量。走摊派才与行级数字自洽：把某客户所有计划行的 produced_qty 加起来，恰好等于客户级数字。

## 4. 响应字段迁移

选**改名**而非「沿用旧名只换语义」。理由：本仓库对名不副实极不宽容（多处注释专门警告过），且缓存 key 本来就必须换版本，改名的边际成本低。

| 端点 | 现字段 | 改后 |
|---|---|---|
| `/plans/monthly-aggregated` → `rows[]` | `_shippedCount` / `_pendingCount` / `_shippedPct` | `_producedCount` / `_pendingCount` / `_producedPct` |
| ↑ `sku_summary[]` | `shipped_qty` / `remain_qty` / `_pct` | `produced_qty` / `remain_qty` / `_pct` |
| ↑ `sku_date_index[]` | `status`(completed/partial/pending) | 不变（语义改为生产达标） |
| ↑ `customers[]` / `customer_totals` | `shipped_qty` / `total_shipped_qty` | `produced_qty` / `total_produced_qty` |
| `/plans/monthly` → `plans_by_date[][]` | `shipped_qty` | `produced_qty` |
| `/plans/day-details` → `plans[]` / 顶层 | `shipped_qty` / `shipped_pct` | `produced_qty` / `produced_pct` |

`fifo_degraded` 字段名保留（它描述的是「分配是否降级」，与来源无关）。

前端对应的 TS 类型与 7 处措辞同步改（KPI 格、月历格子状态与进度条、风险/延期判定的字段读取、当日明细的产品状态、月度汇总列头与数值、导出 CSV 表头、移动端 MShipmentView）。

## 5. 缓存版本

口径变了但缓存 key 不变，会在 TTL 内读到旧口径结果，表现为「改完还是旧数」这类假故障。四个 key 全部上调：

| 缓存 | 位置 | 现版本 | 改后 |
|---|---|---|---|
| `pp:agg` | get_monthly_aggregated | `v1:` | `v2:` |
| `pp:monthly` | get_monthly_calendar | `v2:` | `v3:` |
| `pp:day` | get_day_details | `v1:` | `v2:` |
| `pp:summary` | get_customer_summary | `v2:` | `v3:` |

顺带记录一处发现：`pp:summary` 对应的 `/plans/customer-summary` **前端无人调用**（api 层声明了 `planApi.customerSummary`，但没有任何组件使用；aggregated 端点的 docstring 已写明「合并原 customer-summary 逻辑」）。本稿只把它一并升版本以保持一致，不删除 —— 是否清理另议。

## 6. 影响面

**后端**
- `services/fifo_allocation.py` —— 类型注解放宽（无行为变化）
- `services/purchase_plan_queries.py` —— 新增生产量取数与摊派；三个聚合改用新映射
- `services/purchase_plan_shipment.py` —— 新增 `_get_produced_fifo_map_safe` 降级包装（与出货那套并列，不替换）
- `schemas/purchase_plan.py` —— 三个 Response 的字段名
- `fastapi_app/tests/test_purchase_plan.py` —— 涉及 shipped 字段的断言
- 新增：摊派与窗口的单测

**前端**
- 桌面 `views/purchase-plan/`（KpiStrip、PlanMonthGrid、PlanDayDetail、SkuSummaryTable、PurchasePlanView 导出、DailyTab 的 risks 读取）
- 移动端 `mobile/views/shipment/MShipmentView.vue`
- 对应挂载测试的断言

**不动**：`PlanDetailDialog` 的「出货记录」子页签、`ShipmentRecordsTab`、`/plans/shipment/*`、出货记录的写路径与 FIFO 重算、库存对比、导入链路。

## 7. 未决问题（需你拍板）

**生产量的取数窗口。** 这是本稿唯一真正的分歧点，也是我不愿意替你猜的地方。

出货那套的窗口是「计划月首往前 12 个月、**无上界**」。这套规则**不能**直接套到生产上：出货量天然被该客户的实际发货量约束，而生产量是产品级的、可以远超某个月的计划量 —— 若照搬 12 个月无上界，一个长期在产的产品会把当月计划全部填满，页面上处处 100%。

两个可选读法：

- **乙（我推荐）「截至现在的生产进度」**：窗口 `[计划月首 − 1 个月, 现在]`。
  语义：本月计划到目前被生产覆盖了多少。月初的计划若在上月末已产出也能算上；没产出来的就是「待生产」→ 现有延期/风险判定继续成立。上限是「现在」而非计划月末，所以历史月份的完成率会随后续生产继续上升（符合「跟踪」的用法）。
- **甲「就统计本月产出」**：窗口 `[计划月首, 计划月末]`。
  语义严格对应「本月已生产」的字面；但它会把「上月末已产出、本月出货」的计划判成「待生产」，延期判定会误报。

上界若取「计划月末」则历史月份的数字会被冻结在过去，不再随后续生产变化 —— 这点也请在定案时一并说明要哪一种。

## 8. 验证方式

- 后端单测：摊派算法（跨客户、跨月、无生产记录、product_id 为空、窗口边界前一日/后一日）
- 前端：现有 717 用例不回归 + 挂载断言改读 `produced_*`
- 门禁：`quality_gate.py` PASS
- 人工：刷新桌面与移动端各一次，核对 KPI 与格子状态随生产数据变化

**诚实边界**：本机开不了浏览器预览，人工渲染验证仍需你来做；我能给的是单测、类型检查、构建与门禁四项证据。
