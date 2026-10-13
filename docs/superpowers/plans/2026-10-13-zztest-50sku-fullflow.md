# 50 SKU 全流程订单数据正确性批量测试计划（修订版 v2）

> 目标路由：`/purchase`、`/stock`、`/report`　目标库：**生产库（本机）**
> v2 修订依据：独立 opus 评审（2026-10-13）。v1 的 1 处硬伤（订单/抵扣日期无法回填）+ 5 处口径漏洞已并入。

---

## 0. 目标

造 **1 客户 + 50 SKU（带价格）**，回填 **N 天**（默认 N=7），每天跑
「生产入库 → 备货入库 → 下单 → 抵扣备货 → 出货」，最后核对三路由的**订单派生数据**
与**从原始台账独立推导的期望值**逐项一致，并覆盖**失败边界**（越权出货/抵扣应被拒）。

**核心测试目的**：验证「日积月累」后 `/purchase`（订单状态）、`/stock`（库存口径）、
`/report`（五类流水）三者反映的数据与业务事实一致、且跨路由自洽。

---

## 1. 安全前提（本机 = 生产库，不可逆）

| 项 | 做法 |
|---|---|
| 备份 | 动手前 `pg_dump` 全库 + 归档校验（复用 `scripts/purge_simulated_data.py::backup_database`） |
| 标记 | 客户名 `ZZTEST_客户A`、SKU 名 `ZZTEST-SKU-01..50`、单据 `note` 含 `ZZTEST`。**50 个 SKU 必须新建**，不复用现有产品（否则清理无法只删测试数据） |
| 写入方式 | 主流程**走 API/服务层**（跑真实业务逻辑与闸门）；**仅日期回填**直连 DB（见 §5，严格 ZZTEST 作用域） |
| 鉴权 | **纯 Bearer token + `Origin: http://127.0.0.1:3000`**（生产 `core/middleware.py:221-241` 要求 cookie/CSRF 或 Origin 命中 `BACKEND_CORS_ORIGINS`）；账号需 `order_manage` 等权限（用管理员）。**先确认该 Origin 在白名单内** |
| 写授权 | `ERP_ALLOW_PROD_WRITE=1`（`scripts/_prod_write_guard.py` fail-closed） |
| 窗口 | **低峰/停机窗口**：`/stock` 统计卡片是全局口径，测试数据会临时抬高真实用户看到的数字；且消耗真实编号序列 |
| 编号 | 会**跳号且不可回收**（除非整库恢复）。验证脚本**不得**断言单号连续性 |
| 清理 | **按 `ZZTEST` 作用域删除**（§7），**不是** `scripts/purge_simulated_data.py`（那是全库清空） |

---

## 2. 数据模型与口径（评审校正）

单条订单**只含 1 个 SKU**（`order.quantity` 在多 SKU 下是兼容值，语义未定——见
`shared_models/order.py:49` TODO），避免踩兼容值。

| 符号 | 定义 |
|---|---|
| `ord(o)` | `Σ order_item.quantity`（无明细回退 `o.quantity`） |
| `ded(o)` | `Σ(stock_out.quantity − returned_quantity)`，`order_id=o AND stockin_id IS NOT NULL` |
| `ship(o)` | 同上，`order_id=o AND stockin_id IS NULL` |
| `si(P)` | `Σ stock_in.quantity`（客户+产品） |
| `consumed(si)` | `Σ(stock_out.quantity − returned_quantity)`，`stockin_id=si.id` |
| `pack(P)` | `Σ daily_production_record.quantity`，`department='packaging'` |
| `logship(P)` | `Σ inventory_log.change_quantity`，`change_type ∈ {出库,出库修改,出库删除,退货,退货取消}` |

**分组键（评审校正——必须与代码一致）**：
- `/report` 订单流水：`(UTC日, 客户, 产品名, **条码**, 状态)`（`report_service.py:165`）
- `/report` 备货/出货/抵扣流水：`(UTC日, 客户, 产品名, **条码**)`（`report_service.py:421,490` 等）
- 时区：`order_date` 存 aware UTC，报表按 `DATE(order_date)`（**UTC 日**）分组；
  备货/出货日期经 `_parse_date_preserve_time` 保留本地时间 → **对账统一按 UTC 日**，
  否则同一业务日会被跨日拆开。

---

## 3. 正确性判据：**推导 SQL 为唯一真相源**（评审核心建议）

不再手抄公式。verify 脚本用**一套从原始台账独立编写的聚合 SQL**（**不复制
`report_service.py` 的复杂 CTE**，以保持独立）算出期望值，再与 API 读数 diff。

| 路由 | 显示字段 | 期望值（独立推导） |
|---|---|---|
| `/stock` 行 | 订单数量 | `max(0, Σord − Σ直出 − Σship)` |
| `/stock` 行 | 备货数量 | `Σ_si (si.quantity − consumed(si))` |
| `/stock` 行 | 出货数量 | `Σ直出 + Σship` |
| `/stock` 行 | 总库存 | 备货数量 + 订单数量 |
| `/stock` 行 | 库存(结余) | `pack(P) − logship(P)`（**产品级**，不分客户） |
| `/stock` 卡片 | 订单/备货数量 | **全局**口径 → 用「测前 vs 测后」增量核对；**快照直连 DB 取**（勿走缓存） |
| `/report` | 五类流水 | §2 口径，按 §2 分组键聚合 |
| `/purchase` | 订单状态 | 见下 |

**订单状态派生**（`shared_models/order.py:41`，优先级从高到低）：
`batch_completed_at→批次已完成`；`ship(o)≥ord(o)→已出货`；`ship(o)>0→待出货`；
`ded(o)≥ord(o)→已备货`；`ded(o)>0→部分备货`；否则`待备货`。

**跨路由不变量**：
1. `/report` 订单流水 quantity 合计 == `Σ order_item.quantity`
2. `/report` 抵扣流水 quantity 合计 == `Σ ded(o)`
3. `/report` 出货流水 quantity 合计 == `Σ stock_out.quantity`（毛量，`stockin_id IS NULL`）
4. `/stock` 各行「备货数量 + 订单数量 == 总库存」自洽
5. 每条订单 `/purchase` 状态 == 按 `ded/ship/ord` 推导的状态

---

## 3.1 Phase 0 实测结论（2026-10-13，已冻结）

用 `scripts/zztest_phase0.py`（1 客户 / 1 SKU / 1 单）实跑，**7 步全 200、闸门按预期放行、三路由与独立推导逐项吻合**。冻结口径：

**inventory_log 实测类型**：`生产入库(+)` / `入库(+)` / `订单(+)` / `订单抵扣(−)` / `出库(−)`。
结余只认 `出库/出库修改/出库删除/退货/退货取消`；`生产入库`、`订单` **不计入**结余（实测吻合）。

**实测 → 推导 对账（全等）**：`order_quantity=0`、`stockin_quantity=200`、`stockout_quantity=300`、
`total_stock=200`、`inventory_balance=700`、`available_stock=400`
== 推导 `remaining=0 / stockin_avail=200 / total_stock=200 / balance=700`。

**其它确认**：
- 客户订单号前缀是 **`PO-`**（非 ORD）。
- 入库日期**保留录入时刻**（非零点）→ 回填日期一律用**当日中午**（`YYYY-MM-DD 12:00:00`），避免 UTC 跨日拆行。
- `available_stock = 全部生产 − 全部出库(抵扣+出货+直出)`；`production_qty` 是**全部门**生产量。
- `/purchase` 的 `unprocessed-orders` = 待生产（未出货）的订单+备货，已出货单**不出现** → 批量测试按客户过滤核对。

**派生公式最终版**（对测试客户 C 的 SKU P）：
`remaining=max(0, ord−direct_ship−ship)`；`stockin_avail=Σ_si(si.quantity−consumed(si))`；
`total_stock=stockin_avail+remaining`；`balance=pack−|logship|`；
`available_stock=production_qty(all depts)−Σ all stockouts`。



`product.current_stock` 是一条**独立状态线**（乐观锁 + 负库存守卫）。**必须先有包装部
生产记录把库存抬起来**，否则出货/抵扣会被拒（脚本满屏 4xx，易被误判为 bug）。

每个模拟日的**正确顺序**：
1. **生产入库**：`POST /production-summary/packaging/create`（`department='packaging'`）→ 抬 `current_stock` 与 `inventory_balance`，日期=D
2. **备货入库**：`POST /stock/in/create`，日期=D（FIFO 依据 `stockin_date`）
3. **下单**：`POST /orders/create` → **直连 DB 回填 `order_date=D`**（§5）
4. **抵扣备货**：`PUT /orders/deduct/{id}` → **直连 DB 回填该抵扣 `stock_out.stockout_date=D`**（§5）
5. **出货**：`POST /stock/out/create`，`stockout_date` 由请求带 D（API 支持）

> **回填必须在「出货」之前**：`calculate_available_shipment_quantity` 按 `order_date`
> 升序做 FIFO，回填晚于出货会按错误顺序分配。

---

## 5. 日期回填方案（选 1：直连 DB 回填时间戳）

`OrderCreate` 无 `order_date` 字段（`schemas/order.py:10-14`），服务端填 `now()`
（`shared_models/order.py:75`）；抵扣出库 `stockout_date` 同为 `now()`
（`order/deduction.py:139`）。故：

- **订单**：`UPDATE "order" SET order_date=:D WHERE id=:id AND customer LIKE 'ZZTEST\_%'`
- **抵扣**：`UPDATE stock_out SET stockout_date=:D WHERE order_id=:id AND stockin_id IS NOT NULL AND customer LIKE 'ZZTEST\_%'`

**硬约束**：每条 UPDATE 的 WHERE 必须带 `ZZTEST` 作用域；只改时间戳列，不碰业务字段；
先 `SELECT` 预览命中行数再 `UPDATE`。回填脚本单独成 `zztest_backfill_dates.py`，可 dry-run。

---

## 6. 执行阶段

- **Phase 0 · 标定**（1 客户 / 1 SKU / 1 单）：跑通最小闭环，实测「抵扣 vs 出货」的交互
  （`备货量只能通过订单抵扣使用，不能直接出货`，`inventory_service.py:29-32`），
  **冻结 §3 的推导 SQL**。
- **Phase 1 · 造数**：1 客户 + 50 SKU（名/条码/价格，全 `ZZTEST`）。
- **Phase 2 · 生命周期**（单次回填 N 天）：按 §4 顺序循环 N 天；每天随机对部分 SKU 跑全链，
  并**故意触发失败边界**（越量出货、越量抵扣、库存不足出货、无订单出货 → 均应被拒）。
- **Phase 3 · 全量核对**：
  - **先清缓存**：Redis `erp:*` + 等待 `local_ttl`（`inventory:paginated` ttl=120/local=60，
    `report_service` 各流水 ttl=30/local=10）——否则把旧缓存当 bug。
  - 三路由 API 全量拉取 → 与推导 SQL diff → 输出差异清单（数量/状态/跨路由不一致）。
- **Phase 4 · 报告 + 清理**：出报告（通过/失败项 + 证据）→ §7 清理 → 复核残留为 0。

---

## 7. 清理（严格依赖顺序，先 dry-run）

按 `ZZTEST` 作用域，**先子后父**删除：
`inventory_log` → `stock_return` → `stock_out` → `stock_in` → `daily_production_record`
→ `order_item` → `order` → `product`（**最后**，否则留孤儿流水——本仓既有教训）。
旁表：`notification`、`approval_request`、`staging_*`、`purchase_plan*` 重算产物、
物化视图 `REFRESH`。
脚本 `zztest_cleanup.py --dry-run` 先打印每表命中行数，确认后再执行；结束后逐表复核为 0。

---

## 8. 交付物

1. `scripts/zztest_generate.py`（造数，带护栏+`ZZTEST` 标记）
2. `scripts/zztest_lifecycle.py`（N 天驱动，走 API + 调回填）
3. `scripts/zztest_backfill_dates.py`（日期回填，dry-run）
4. `scripts/zztest_verify.py`（推导 SQL + 三路由 diff）
5. `scripts/zztest_cleanup.py`（作用域清理 + 残留复核）
6. 测试报告 `docs/…/zztest-report-YYYYMMDD.md` + 备份路径

---

## 9. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 误删真实数据 | 清理严格 `ZZTEST` 作用域 + dry-run + 复核为 0 |
| 干扰真实用户 | 低峰窗口；全局统计临时抬高；测完即清 |
| 期望值推导错 | §3 独立 SQL + Phase 0 标定；不手抄公式 |
| 缓存脏读假红 | Phase 3 先清缓存 + 等 local_ttl |
| 闸门误拒被当 bug | §4 先生产后出货；失败用例**预期**为拒 |
| 中途失败留半成品 | 脚本幂等可重入；按标记清理 |
| 编号跳号 | 不回收；验证脚本不断言连续性 |

---

## 10. 待 owner 确认
- N 天取值（默认 7）
- 该 Origin 是否在生产 `BACKEND_CORS_ORIGINS` 白名单
- 是否接受编号跳号 + 全局统计临时抬高
