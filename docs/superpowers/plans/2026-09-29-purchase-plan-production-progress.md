# 采购计划「进度」口径：已出货 → 已生产 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `/purchase-plan`（桌面）与 `/shipment`（移动端）的进度口径从「已出货」换成「已生产」，数据源为 `daily_production_record`，按现有 FIFO 算法摊到计划行。

**Architecture:** 现有进度全部来自 `fifo_allocation._get_shipped_fifo_map` —— 它按 `(客户, 产品)` 分组、把累计出货净量按 `plan_date` 顺序摊到计划明细上。本计划新增一条**并列**的生产量路径：同样的 `allocate_fifo` 纯函数，但分组键改为 `product_id`（生产记录没有客户字段），累计量改为窗口内的生产量。三个聚合端点（`monthly-aggregated` / `monthly` / `day-details`）改用新映射，响应字段由 `shipped_*` 改名为 `produced_*`，四处缓存升版本。出货路径、出货记录查询、FIFO 写路径一律不动。

**Tech Stack:** Python 3.13 / FastAPI / SQLAlchemy 2.x（async）/ Pydantic v2 / pytest + pytest-asyncio（服务层 mock）/ Vue 3 + TypeScript / vitest + @vue/test-utils

**Spec:** `docs/designs/2026-09-29-purchase-plan-production-progress-design.md`

## Global Constraints

以下取自设计稿，**每个任务的要求都隐含包含本节**：

- 取数窗口 = `[计划月首 − 1 个月, 现在]`。常量 `PRODUCTION_RECORD_LOOKBACK_MONTHS = 1`，注释必须写明「与出货的 12 不同，原因见设计稿 §7」，防止后来者顺手对齐成 12。
- 三部门（`filling` 充棉部 / `handcraft` 手工部 / `packaging` 包装部）**相加**，不按 department 过滤。依据：`daily_production_service.py:374` 的月度汇总口径。
- 关联键用 `product_id`，**不用** `barcode`（`daily_production_record.barcode` 是 `NOT NULL DEFAULT ''`，可为空串）。`product_id IS NULL` 的行丢弃 —— 沿用 `stock_inventory_service.py` 的 `WHERE product_id IS NOT NULL` 惯例。
- 只统计「出现在该查询涉及的计划里」的 `product_id` 集合，不取全厂产量。
- 客户筛选跟随，**由 FIFO 摊派自然产生**；不额外按「客户的产品集合」求和。
- 弹窗里真实的「出货记录」子页签、`ShipmentRecordsTab.vue`、`/plans/shipment/*` 查询**不动**。
- `daily_production_record` 只读，不引入任何写路径；`_update_shipped_qty` / `_recalc_plan_status` 等 FIFO 写路径不动。
- `fifo_degraded` 字段名与语义保持（查询不可用时显式标记，而非返回全 0）。
- 响应字段改名：`shipped_qty`→`produced_qty`、`_shippedPct`→`_producedPct`、`_shippedCount`→`_producedCount`、`shipped_pct`→`produced_pct`、`total_shipped_qty`→`total_produced_qty`。`remaining_qty` / `remain_qty` / `status` / `fifo_degraded` 名字不变。
- 缓存版本号上调：`pp:agg` v1→v2、`pp:monthly` v2→v3、`pp:day` v1→v2、`pp:summary` v2→v3。
- 仓库门禁：单个 `.vue` ≤ 400 行；单个函数有效行 ≤ 80 行（剔空行与纯注释行）。提交前 `python scripts/quality_gate.py` 必须 PASS。

## Review Focus

以下五类输入/失败模式是设计稿隐含但不会自然写进测试的，最可能让人踩到。每一条都在下面某个任务的步骤里配了实测：

1. **生产记录 `product_id` 为空**（历史脏数据）：该行应丢弃、不参与累计；不得让该产品的计划被误算成 0 生产，也不得抛异常 → Task 1 步骤 1/3。
2. **生产量大于计划量**：`allocate_fifo` 必须把每行分配值钳在 `quantity` 以内，多余产量不分配到任何行（否则会出现「已生产 200 / 计划 100」）→ Task 1 步骤 5。
3. **`plan_date` 相同的两条明细**：摊派顺序必须稳定（否则每次刷新同一份数据给出不同数字，用户会认为系统在抖）→ Task 1 步骤 5。
4. **窗口跨年**（计划月为 1 月 → 起点落在上一年 12 月）→ Task 1 步骤 7。
5. **窗口内完全没有生产记录**（`SUM` 无行）：必须得到全部「待生产」而不是 `None` 参与算术报错 → Task 2 步骤 3。

---

## File Structure

**后端**

| 文件 | 职责 | 动作 |
|---|---|---|
| `fastapi_app/services/fifo_allocation.py` | FIFO 分配算法与两条分配缓存的唯一归属地。新增生产量路径（缓存前缀 `plan_prod_fifo`），与出货路径并列 | Modify |
| `fastapi_app/services/purchase_plan_shipment.py` | FIFO 读路径的降级包装（`*_safe`）。新增生产版包装 | Modify |
| `fastapi_app/services/purchase_plan_queries.py` | 三个聚合端点。改用生产映射、字段改名、缓存升版本 | Modify |
| `fastapi_app/schemas/purchase_plan.py` | 只有 `DayDetailsResponse.shipped_pct` 是显式字段（其余是 `list[dict]` 透传） | Modify |
| `tests/test_production_attribution.py` | 新增：窗口 / 分组 / 聚合 / 产品键摊派的纯函数单测 | Create |
| `fastapi_app/tests/test_purchase_plan.py` | 端点 mock 测试中涉及 shipped 字段的断言 | Modify |

**前端**

| 文件 | 动作 |
|---|---|
| `src/views/purchase-plan/components/types.ts` | Modify（字段改名） |
| `src/views/purchase-plan/components/dayStatus.ts` | Modify（读 `_producedPct`） |
| `src/views/purchase-plan/components/PlanMonthGrid.vue` | Modify（2 处读取） |
| `src/views/purchase-plan/components/PurchasePlanDailyTab.vue` | Modify（风险判定读取） |
| `src/views/purchase-plan/components/PlanDayDetail.vue` | Modify（状态文案） |
| `src/views/purchase-plan/components/SkuSummaryTable.vue` | Modify（列头 + 字段 + 配色函数名） |
| `src/views/purchase-plan/components/PurchasePlanKpiStrip.vue` | Modify（prop 名 + 文案） |
| `src/views/purchase-plan/PurchasePlanView.vue` | Modify（sKpi 取数 + prop 传递 + 导出表头） |
| `src/views/purchase-plan/components/PlanDetailDialog.vue` | Modify（`produced_pct` + 计划明细文案；**出货记录子页签不动**） |
| `src/views/purchase-plan/components/PlanDialogPlanList.vue` | Modify（文案 + 字段） |
| `src/views/purchase-plan/components/PlanDialogCustomerList.vue` | Modify（文案 + 字段） |
| `src/mobile/views/shipment/MShipmentView.vue` | Modify（文案 + 字段） |
| `src/test/purchasePlan*.test.ts`、`planDayStatus.test.ts`、`planMonthGrid.test.ts` | Modify（断言改字段名） |

**明确不动**：`ShipmentRecordsTab.vue`、`SkuDetailDialog.vue`、`api/plan.ts`（方法名与字段无关）、`PurchasePlanToolbar.vue`、`PurchasePlanMonthNav.vue`、`CustomerDistPanel.vue`、`PlanRiskList.vue`。

---

### Task 1: 生产量取数窗口 + 分组聚合纯函数，并泛化 FIFO 算法

这一步不碰数据库、不碰端点 —— 只把三件事变成可单测的纯函数：窗口计算、按产品分组、生产量聚合；同时把 `allocate_fifo` 的第三形参从 `shipped_by_key` 改名为中性的 `total_by_key`（它现在要服务两种来源）。

**Files:**
- Modify: `fastapi_app/services/fifo_allocation.py:338-375`（`allocate_fifo`）以及文件顶部常量区
- Test: `tests/test_production_attribution.py`（新建）

**Interfaces:**
- Consumes: 无（第一个任务）
- Produces:
  - `PRODUCTION_RECORD_LOOKBACK_MONTHS: int = 1`
  - `production_window(plan_month: str, now: datetime) -> tuple[date, date]`
  - `group_details_by_product(all_details: list) -> dict[int, list]`
  - `aggregate_produced_by_product(rows: list) -> dict[int, int]`
  - `allocate_fifo(plan_details: list, details_by_key: dict[Hashable, list], total_by_key: dict[Hashable, int]) -> dict[int, int]` —— 第三形参改名，**所有现有调用点都是位置传参，不受影响**

- [ ] **Step 1: 写失败的测试 —— 生产量聚合（含 product_id 为空）**

新建 `tests/test_production_attribution.py`：

```python
"""生产量摊派的纯函数单元测试

覆盖（均无数据库依赖）：
    - aggregate_produced_by_product: 生产记录行 → {product_id: 累计量}
    - group_details_by_product: 计划明细按 product_id 分组
    - production_window: 取数窗口（含跨年边界）
    - allocate_fifo 以产品为键的摊派行为
"""
from datetime import date, datetime
from unittest.mock import MagicMock

from fastapi_app.services.fifo_allocation import (
    aggregate_produced_by_product,
    allocate_fifo,
    group_details_by_product,
    production_window,
)


def _make_detail(detail_id: int, quantity: int, plan_date=None, product_id: int = 1, plan_id: int = 1):
    """创建 mock PurchasePlanDetail"""
    d = MagicMock()
    d.id = detail_id
    d.plan_id = plan_id
    d.quantity = quantity
    d.product_name = f'P{product_id}'
    d.plan_date = plan_date
    d.product_id = product_id
    return d


def _make_prod_row(product_id, quantity):
    """创建 mock DailyProductionRecord 行"""
    r = MagicMock()
    r.product_id = product_id
    r.quantity = quantity
    return r


class TestAggregateProducedByProduct:
    def test_sums_same_product(self):
        rows = [_make_prod_row(1, 100), _make_prod_row(1, 50), _make_prod_row(2, 30)]
        assert aggregate_produced_by_product(rows) == {1: 150, 2: 30}

    def test_drops_rows_without_product_id(self):
        """product_id 为空的历史脏数据必须丢弃，不得算进任何产品"""
        rows = [_make_prod_row(None, 999), _make_prod_row(1, 100)]
        assert aggregate_produced_by_product(rows) == {1: 100}

    def test_treats_none_quantity_as_zero(self):
        """quantity 为 NULL 的行按 0 计，不得让 None 参与加法报错"""
        rows = [_make_prod_row(1, None), _make_prod_row(1, 70)]
        assert aggregate_produced_by_product(rows) == {1: 70}

    def test_no_rows(self):
        assert aggregate_produced_by_product([]) == {}
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_production_attribution.py -v`
Expected: FAIL —— `ImportError: cannot import name 'aggregate_produced_by_product'`

- [ ] **Step 3: 实现聚合函数**

在 `fastapi_app/services/fifo_allocation.py` 的 `_aggregate_shipped_by_key` **下方**新增：

```python
def aggregate_produced_by_product(rows: list) -> dict[int, int]:
    """生产记录行 → {product_id: 累计生产量}。

    - 按 product_id 聚合，不按 department 过滤：三部门（充棉/手工/包装）相加，
      与 daily_production_service 的月度汇总口径一致。
    - product_id 为空的行丢弃：daily_production_record.product_id 可空，
      空值无法与计划明细关联，沿用 stock_inventory_service 的
      `WHERE product_id IS NOT NULL` 惯例。
    - quantity 为 NULL 按 0 计：避免 None 参与加法抛 TypeError。
    """
    out: dict[int, int] = {}
    for row in rows:
        if not row.product_id:
            continue
        out[row.product_id] = out.get(row.product_id, 0) + int(row.quantity or 0)
    return out
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_production_attribution.py -v`
Expected: PASS（4 项）

- [ ] **Step 5: 写失败的测试 —— 产品键摊派（钳制、同日期稳定性、空 product_id）**

追加到同一测试文件：

```python
class TestAllocateFifoByProduct:
    def test_fills_earliest_plan_first(self):
        """同一产品的计划按 plan_date 先后被生产量填满"""
        d1 = _make_detail(1, 10, plan_date=date(2026, 9, 20), product_id=7)
        d2 = _make_detail(2, 20, plan_date=date(2026, 9, 5), product_id=7)
        details_by_key = {7: [d2, d1]}          # 调用方保证已按 plan_date ASC 排序
        total_by_key = {7: 15}
        result = allocate_fifo([d1, d2], details_by_key, total_by_key)
        assert result[2] == 15   # 早的那条（9/05）被填
        assert result[1] == 0    # 晚的那条（9/20）没被填

    def test_allocated_never_exceeds_plan(self):
        """生产量远超计划量时，每行分配值钳在 quantity 以内，溢出丢弃"""
        d1 = _make_detail(1, 100, plan_date=date(2026, 9, 1), product_id=7)
        d2 = _make_detail(2, 50, plan_date=date(2026, 9, 2), product_id=7)
        details_by_key = {7: [d1, d2]}
        total_by_key = {7: 9999}
        result = allocate_fifo([d1, d2], details_by_key, total_by_key)
        assert result == {1: 100, 2: 50}

    def test_same_plan_date_is_stable(self):
        """plan_date 相同时按传入顺序分配，结果可复现（不随 set/dict 顺序漂移）"""
        d1 = _make_detail(1, 10, plan_date=date(2026, 9, 1), plan_id=1, product_id=7)
        d2 = _make_detail(2, 10, plan_date=date(2026, 9, 1), plan_id=2, product_id=7)
        details_by_key = {7: [d1, d2]}
        total_by_key = {7: 10}
        first = allocate_fifo([d1, d2], details_by_key, total_by_key)
        second = allocate_fifo([d1, d2], details_by_key, total_by_key)
        assert first == second
        assert first == {1: 10, 2: 0}

    def test_different_products_do_not_cross(self):
        """不同产品的产量互不串门"""
        d1 = _make_detail(1, 10, plan_date=date(2026, 9, 1), product_id=7)
        d2 = _make_detail(2, 10, plan_date=date(2026, 9, 1), product_id=8)
        details_by_key = {7: [d1], 8: [d2]}
        total_by_key = {7: 10}
        result = allocate_fifo([d1, d2], details_by_key, total_by_key)
        assert result == {1: 10, 2: 0}


class TestGroupDetailsByProduct:
    def test_groups_and_preserves_order(self):
        d1 = _make_detail(1, 10, plan_date=date(2026, 9, 1), product_id=7)
        d2 = _make_detail(2, 10, plan_date=date(2026, 9, 2), product_id=7)
        d3 = _make_detail(3, 10, plan_date=date(2026, 9, 3), product_id=8)
        grouped = group_details_by_product([d1, d2, d3])
        assert list(grouped.keys()) == [7, 8]
        assert [d.id for d in grouped[7]] == [1, 2]

    def test_drops_details_without_product_id(self):
        d1 = _make_detail(1, 10, product_id=0)     # product_id=0 视为空
        d2 = _make_detail(2, 10, product_id=7)
        grouped = group_details_by_product([d1, d2])
        assert grouped == {7: [d2]}

    def test_empty(self):
        assert group_details_by_product([]) == {}
```

- [ ] **Step 6: 跑测试确认失败**

Run: `python -m pytest tests/test_production_attribution.py -v`
Expected: FAIL —— `ImportError: cannot import name 'group_details_by_product'`

- [ ] **Step 7: 实现分组函数并把 `allocate_fifo` 的形参改名**

在 `fifo_allocation.py` 的 `aggregate_produced_by_product` 下方新增：

```python
def group_details_by_product(all_details: list) -> dict[int, list]:
    """计划明细按 product_id 分组，保持传入顺序。

    调用方负责先按 (plan_date, id) 排序 —— allocate_fifo 的摊派顺序即传入顺序，
    这里重排会让同 plan_date 的分配结果不可复现。
    product_id 为空的明细无法关联生产记录，丢弃。
    """
    out: dict[int, list] = {}
    for d in all_details:
        if not d.product_id:
            continue
        out.setdefault(d.product_id, []).append(d)
    return out
```

然后把 `allocate_fifo` 的签名与文档改成中性（**只改名字与文档，算法一行不动**）：

```python
def allocate_fifo(
    plan_details: list,
    details_by_key: dict[Hashable, list],
    total_by_key: dict[Hashable, int],
) -> dict[int, int]:
    """累计分配法（核心算法，可独立单元测试）

    对每个键：
        1. 取该键的所有计划明细（已按 plan_date ASC 排序）
        2. 取该键的累计量（出货净量，或生产量 —— 由调用方决定语义）
        3. 用累计分配法：累计量按顺序依次填满最早的计划

    Args:
        plan_details: 当前查询涉及的计划明细列表（用于补零）
        details_by_key: {键: [PurchasePlanDetail, ...]} 已分组+排序。
            出货路径的键是 (customer_name, product_name)，生产路径的键是 product_id。
        total_by_key: {键: 累计量}

    Returns:
        {plan_detail_id: allocated_qty}
    """
```

同时确认函数体内两处 `shipped_by_key` 引用改为 `total_by_key`（第 360 行 `total_shipped = shipped_by_key.get(key, 0)` 与循环体）。`Hashable` 需从 `typing` 或 `collections.abc` 导入：把 `from typing import Hashable` 加到文件顶部导入区。

- [ ] **Step 8: 跑测试确认通过，并确认没有回归**

Run: `python -m pytest tests/test_production_attribution.py tests/test_purchase_plan_core.py -v`
Expected: PASS（新增 12 项 + 既有 allocate_fifo 测试全绿 —— 形参改名不影响既有调用，因为都是位置传参）

- [ ] **Step 9: 写失败的测试 —— 取数窗口（含跨年）**

追加到同一测试文件：

```python
class TestProductionWindow:
    def test_normal_month(self):
        """计划月 2026-09 → 起点 2026-08-01，终点为「今天」"""
        start, end = production_window('2026-09', datetime(2026, 9, 29, 10, 30))
        assert start == date(2026, 8, 1)
        assert end == date(2026, 9, 29)

    def test_year_boundary(self):
        """计划月 2026-01 → 起点落在上一年 12 月"""
        start, end = production_window('2026-01', datetime(2026, 1, 5, 0, 0))
        assert start == date(2025, 12, 1)
        assert end == date(2026, 1, 5)

    def test_end_is_today_not_month_end(self):
        """上界是「现在」而非计划月末：历史月份的数字应随后续生产继续上升"""
        start, end = production_window('2026-03', datetime(2026, 9, 29, 23, 59))
        assert end == date(2026, 9, 29)
        assert start == date(2026, 2, 1)
```

- [ ] **Step 10: 跑测试确认失败**

Run: `python -m pytest tests/test_production_attribution.py::TestProductionWindow -v`
Expected: FAIL —— `ImportError: cannot import name 'production_window'`

- [ ] **Step 11: 实现窗口函数与常量**

在 `fifo_allocation.py` 顶部常量区（`FIFO_CACHE_TTL` 附近）新增：

```python
# 生产量取数窗口的回看月数。
# 与出货的 SHIPMENT_RECORD_LOOKBACK_MONTHS = 12 不同，**不要顺手对齐成 12**：
# 出货量天然被该客户的实际发货量约束，而生产量是产品级的、可远超某个月的计划量，
# 12 个月无上界会让当月计划被历史累计产量全部填满、页面处处 100%。详见设计稿 §7。
PRODUCTION_RECORD_LOOKBACK_MONTHS = 1
```

并在纯函数区新增：

```python
def production_window(plan_month: str, now: datetime) -> tuple[date, date]:
    """生产量取数窗口 [计划月首 − 1 个月, 现在]（定案：设计稿 §7 乙）。

    - 下界回看 1 个月：计划日落在月初时，生产往往在上月末完成（先产后出）。
    - 上界取「现在」而非「计划月末」：本页是跟踪工具，历史月份的完成率应随后续
      生产继续上升；取月末会把数字冻结在过去。
    用月序换算而非 timedelta(days=30)：后者在 2 月与大月之间会漂移出月份。
    """
    year, month = map(int, plan_month.split('-'))
    m = month - PRODUCTION_RECORD_LOOKBACK_MONTHS
    y = year
    while m < 1:
        m += 12
        y -= 1
    return date(y, m, 1), now.date()
```

- [ ] **Step 12: 跑测试确认通过**

Run: `python -m pytest tests/test_production_attribution.py -v`
Expected: PASS（15 项）

- [ ] **Step 13: 提交**

```bash
git add fastapi_app/services/fifo_allocation.py tests/test_production_attribution.py
git commit -m "feat(purchase-plan): 生产量摊派的纯函数与 FIFO 算法泛化"
```

---

### Task 2: 生产量分配映射（查询 + 缓存 + 失效钩子）

这是本次改动最容易埋雷的一步：出货路径除了聚合缓存外还有一层独立的 Redis 分配缓存 `plan_fifo:YYYY-MM`（TTL 30 分钟），且它的失效由 SQLAlchemy 会话事件在 `StockOut` 变更时触发。生产量必须有自己的前缀**和**自己的失效触发 —— 否则「刚录入生产记录，页面数字不变」，用户会认为功能坏了。

**Files:**
- Modify: `fastapi_app/services/fifo_allocation.py`（常量区、`_invalidate_fifo_caches_safe`、`_fifo_before_commit`、文件末尾新增查询函数）
- Test: `tests/test_production_attribution.py`（追加）

**Interfaces:**
- Consumes: Task 1 的 `production_window` / `group_details_by_product` / `aggregate_produced_by_product` / `allocate_fifo`
- Produces:
  - `PRODUCTION_FIFO_CACHE_PREFIX: str = 'plan_prod_fifo'`
  - `async def _get_produced_fifo_map(db: AsyncSession, plan_details: list, plan_month: str = '') -> dict[int, int]` —— 抛 `RuntimeError('FIFO_ALLOCATION_UNAVAILABLE')` 表示查询不可用（与出货路径同款契约）
  - `async def _invalidate_production_fifo_cache(plan_month: str) -> None`

- [ ] **Step 1: 写失败的测试 —— 无生产记录 + 缓存降级**

追加到 `tests/test_production_attribution.py`：

```python
import pytest
from datetime import datetime
from unittest.mock import AsyncMock, patch


class TestGetProducedFifoMap:
    """_get_produced_fifo_map 的查询与缓存行为（DB 与 Redis 均 mock）"""

    @pytest.mark.asyncio
    async def test_no_production_records_yields_zero_allocation(self):
        """窗口内完全没有生产记录 → 每行分配 0（前端显示全部待生产），且不抛异常"""
        d1 = _make_detail(1, 100, plan_date=date(2026, 9, 8), product_id=7)
        db = AsyncMock()
        db.execute.return_value.all.return_value = []      # 生产记录查询命中 0 行

        with patch.object(fifo, 'safe_get', AsyncMock(return_value=None)), \
             patch.object(fifo, 'safe_set', AsyncMock()):
            result = await fifo._get_produced_fifo_map(db, [d1], plan_month='2026-09')

        assert result == {1: 0}

    @pytest.mark.asyncio
    async def test_allocates_by_product_in_plan_date_order(self):
        """生产量按 plan_date 先后摊到该产品的计划行上（跨客户也不分组）"""
        early = _make_detail(1, 100, plan_date=date(2026, 9, 5), product_id=7, plan_id=1)
        late = _make_detail(2, 100, plan_date=date(2026, 9, 20), product_id=7, plan_id=2)
        db = AsyncMock()
        db.execute.return_value.all.return_value = [_make_prod_row(7, 150)]

        with patch.object(fifo, 'safe_get', AsyncMock(return_value=None)), \
             patch.object(fifo, 'safe_set', AsyncMock()):
            result = await fifo._get_produced_fifo_map(db, [early, late], plan_month='2026-09')

        assert result == {1: 100, 2: 50}

    @pytest.mark.asyncio
    async def test_empty_details_short_circuits(self):
        db = AsyncMock()
        with patch.object(fifo, 'safe_get', AsyncMock(return_value=None)), \
             patch.object(fifo, 'safe_set', AsyncMock()):
            assert await fifo._get_produced_fifo_map(db, [], plan_month='2026-09') == {}
        db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_cache_hit_skips_query(self):
        """缓存覆盖了全部需查询的明细 id 时直接返回，不再打 DB"""
        d1 = _make_detail(1, 100, plan_date=date(2026, 9, 8), product_id=7)
        db = AsyncMock()
        with patch.object(fifo, 'safe_get', AsyncMock(return_value={'1': 42})), \
             patch.object(fifo, 'safe_set', AsyncMock()):
            result = await fifo._get_produced_fifo_map(db, [d1], plan_month='2026-09')
        assert result == {1: 42}
        db.execute.assert_not_called()
```

并在该文件的导入区加上 `from fastapi_app.services import fifo_allocation as fifo`（`patch.object` 需要模块对象）。

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_production_attribution.py::TestGetProducedFifoMap -v`
Expected: FAIL —— `AttributeError: module ... has no attribute '_get_produced_fifo_map'`

- [ ] **Step 3: 实现生产量查询与缓存**

在 `fifo_allocation.py` 常量区新增（`FIFO_CACHE_TTL` 下方）：

```python
PRODUCTION_FIFO_CACHE_PREFIX = 'plan_prod_fifo'
```

在 `_invalidate_fifo_cache` 下方新增：

```python
async def _invalidate_production_fifo_cache(plan_month: str) -> None:
    """清除指定月份的生产量分配缓存（与出货缓存分开，键前缀不同）"""
    await cache_mgr.invalidate(InvalidationStrategy.KEYS, [f'{PRODUCTION_FIFO_CACHE_PREFIX}:{plan_month}'])
```

在文件末尾（`allocate_fifo` 之后）新增：

```python
async def _get_produced_fifo_map(db: AsyncSession, plan_details: list, plan_month: str = '') -> dict[int, int]:
    """把窗口内的生产量摊到计划明细上。

    与出货版的差别只有两点：
      1. 分组键是 product_id（生产记录没有客户字段），不是 (customer, product_name)
      2. 累计量来自 daily_production_record，窗口见 production_window

    契约与出货版一致：查询超时/异常抛 RuntimeError('FIFO_ALLOCATION_UNAVAILABLE')，
    由 _get_produced_fifo_map_safe 捕获后标记降级，而不是返回全 0 让业务误读成「没生产」。

    返回: {plan_detail_id: allocated_produced_qty}
    """
    if not plan_details:
        return {}

    cache_key = f'{PRODUCTION_FIFO_CACHE_PREFIX}:{plan_month}' if plan_month else ''
    if cache_key:
        cached = await safe_get(cache_key, context='生产量分配缓存')
        if cached is not None:
            try:
                cached_int_keys = {int(k) for k in cached}
            except (ValueError, TypeError):
                # 缓存脏数据视为未命中并清除，不让其演变为 500（同出货版 L2 修复）
                await _invalidate_production_fifo_cache(plan_month)
                cached = None
            else:
                if {d.id for d in plan_details}.issubset(cached_int_keys):
                    return {int(k): v for k, v in cached.items()}

    try:
        async with asyncio.timeout(10):
            product_ids = sorted({d.product_id for d in plan_details if d.product_id})
            if not product_ids:
                # 全是历史脏数据（product_id 为空）→ 无从关联生产记录
                return {}

            start, end = production_window(plan_month, datetime.now())

            with contextlib.suppress(SQLAlchemyError, OSError):
                await db.execute(text("SET LOCAL statement_timeout = '8s'"))

            result = await db.execute(
                select(
                    DailyProductionRecord.product_id,
                    func.sum(DailyProductionRecord.quantity).label('quantity'),
                )
                .where(
                    and_(
                        DailyProductionRecord.product_id.in_(product_ids),
                        DailyProductionRecord.production_date >= start,
                        DailyProductionRecord.production_date <= end,
                    )
                )
                .group_by(DailyProductionRecord.product_id)
            )
            # 别名取 quantity，让纯聚合函数在「原始行」与「分组行」两种输入上通用
            produced_by_key = aggregate_produced_by_product(result.all())

            allocated = allocate_fifo(
                plan_details,
                group_details_by_product(plan_details),
                produced_by_key,
            )
    except TimeoutError:
        with contextlib.suppress(SQLAlchemyError, OSError):
            await db.execute(text("RESET statement_timeout"))
        logger.exception('生产量分配查询超时 plan_month=%s', plan_month)
        raise RuntimeError('FIFO_ALLOCATION_UNAVAILABLE') from None
    except Exception as e:  # defensive: 同出货版，异常时抛明确异常交由调用方降级
        with contextlib.suppress(SQLAlchemyError, OSError):
            await db.execute(text("RESET statement_timeout"))
        logger.exception('生产量分配查询异常: %s', e)
        raise RuntimeError('FIFO_ALLOCATION_UNAVAILABLE') from e

    if cache_key:
        await safe_set(cache_key, {str(k): v for k, v in allocated.items()},
                       timeout=FIFO_CACHE_TTL, context='生产量分配缓存')

    return allocated
```

文件顶部导入区补上 `func`（`from sqlalchemy import and_, event, func, select, text`）与 `DailyProductionRecord`（加进 `from fastapi_app.shared_models import (...)`）。

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_production_attribution.py -v`
Expected: PASS（19 项）

- [ ] **Step 5: 写失败的测试 —— 生产记录变更必须清缓存**

追加：

```python
class TestProductionCacheInvalidation:
    def test_production_record_write_marks_session_dirty(self):
        """DailyProductionRecord 的增删改必须置脏标记，否则会话提交后不清缓存"""
        record = MagicMock(spec=DailyProductionRecord)
        session = MagicMock()
        session.info = {}
        session.new = [record]
        session.dirty = []
        session.deleted = []
        fifo._fifo_before_commit(session)
        assert session.info.get('fifo_dirty') is True

    def test_unrelated_write_does_not_mark_dirty(self):
        """无关模型的写入不应触发清缓存（避免每次都白清）"""
        session = MagicMock()
        session.info = {}
        session.new = [object()]
        session.dirty = []
        session.deleted = []
        fifo._fifo_before_commit(session)
        assert session.info.get('fifo_dirty') is None
```

导入区补 `from fastapi_app.shared_models import DailyProductionRecord`。

- [ ] **Step 6: 跑测试确认失败**

Run: `python -m pytest tests/test_production_attribution.py::TestProductionCacheInvalidation -v`
Expected: FAIL —— `test_production_record_write_marks_session_dirty` 失败（当前 `_fifo_before_commit` 只认 `StockOut`）

- [ ] **Step 7: 扩展失效钩子**

把 `fifo_allocation.py` 的 `_fifo_before_commit` 改为同时识别生产记录，并让失效函数清两个前缀：

```python
def _fifo_before_commit(session) -> None:
    # 一个标记覆盖两种来源：会话里只要动过出货记录或生产记录，提交后就清两个前缀。
    # 分开标记会让「同一事务既改出货又改生产」需要两处判断，收益不抵复杂度；
    # 生产记录写入频率远低于出货，多清一次的代价可忽略。
    if session.info.get('fifo_dirty'):
        return
    for obj in list(session.new) + list(session.dirty) + list(session.deleted):
        if isinstance(obj, (StockOut, DailyProductionRecord)):
            session.info['fifo_dirty'] = True
            return


async def _invalidate_fifo_caches_safe() -> None:
    try:
        await cache_mgr.invalidate(InvalidationStrategy.PATTERN, ['plan_fifo:*'])
        await cache_mgr.invalidate(InvalidationStrategy.PATTERN, [f'{PRODUCTION_FIFO_CACHE_PREFIX}:*'])
        invalidate_local_cache('plan_fifo:*')
        invalidate_local_cache(f'{PRODUCTION_FIFO_CACHE_PREFIX}:*')
    except Exception:  # defensive: 缓存失效失败不阻断业务，靠 TTL 兜底
        logger.warning("分配缓存全量失效失败（等待 TTL 过期兜底）", exc_info=True)
```

同时把 `_fifo_before_commit` 上方那段长注释里的「StockOut 变更」改为「StockOut 或 DailyProductionRecord 变更」，把 `_fifo_after_commit` 无需改动这点在注释里点明。

- [ ] **Step 8: 跑测试确认通过**

Run: `python -m pytest tests/test_production_attribution.py -v`
Expected: PASS（21 项）

- [ ] **Step 9: 提交**

```bash
git add fastapi_app/services/fifo_allocation.py tests/test_production_attribution.py
git commit -m "feat(purchase-plan): 生产量分配映射与缓存失效（含生产记录写触发）"
```

---

### Task 3: 读路径降级包装与聚合层接入

**Files:**
- Modify: `fastapi_app/services/purchase_plan_shipment.py`（`_get_shipped_fifo_map_safe` 下方）
- Modify: `fastapi_app/services/purchase_plan_queries.py`（`_build_fifo_shipped_map_from_rows` 下方）
- Test: `tests/test_production_attribution.py`（追加）

**Interfaces:**
- Consumes: Task 2 的 `_get_produced_fifo_map`
- Produces:
  - `async def _get_produced_fifo_map_safe(db, details, plan_month='') -> tuple[dict[int, int], bool]`
  - `async def _build_fifo_produced_map_from_rows(db, rows, plan_month='') -> tuple[dict[int, int], bool]` —— 返回 `(detail_produced_map, degraded)`；与出货版不同，**不需要** `customer_name_map`（生产不按客户分组）

- [ ] **Step 1: 写失败的测试 —— 降级时返回空映射 + 标记 True**

追加到 `tests/test_production_attribution.py`：

```python
class TestProducedFifoMapSafe:
    @pytest.mark.asyncio
    async def test_query_failure_degrades_with_flag(self):
        """查询不可用时返回空映射 + degraded=True，不得返回全 0 冒充「没生产」"""
        db = AsyncMock()
        # 注意 patch 的目标是**消费方** purchase_plan_shipment 里的名字：
        # 该模块用 `from ... import _get_produced_fifo_map` 绑定了自己的引用，
        # patch 源模块 fifo_allocation 上的同名属性对它无效（经典 patch 打错地方）。
        with patch.object(pps, '_get_produced_fifo_map',
                          AsyncMock(side_effect=RuntimeError('FIFO_ALLOCATION_UNAVAILABLE'))):
            result, degraded = await _get_produced_fifo_map_safe(db, [_make_detail(1, 10, product_id=7)])
        assert result == {}
        assert degraded is True

    @pytest.mark.asyncio
    async def test_success_passes_through(self):
        db = AsyncMock()
        with patch.object(pps, '_get_produced_fifo_map', AsyncMock(return_value={1: 42})):
            result, degraded = await _get_produced_fifo_map_safe(db, [_make_detail(1, 10, product_id=7)])
        assert result == {1: 42}
        assert degraded is False
```

导入区补：
```python
from fastapi_app.services import purchase_plan_shipment as pps
from fastapi_app.services.purchase_plan_shipment import _get_produced_fifo_map_safe
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_production_attribution.py::TestProducedFifoMapSafe -v`
Expected: FAIL —— `ImportError: cannot import name '_get_produced_fifo_map_safe'`

- [ ] **Step 3: 实现降级包装**

在 `purchase_plan_shipment.py` 的 `_get_shipped_fifo_map_safe` **下方**新增（并在顶部导入 `_get_produced_fifo_map`）：

```python
async def _get_produced_fifo_map_safe(
    db: AsyncSession, details: list, plan_month: str = '',
) -> tuple[dict[int, int], bool]:
    """生产量分配的读路径包装。契约与 _get_shipped_fifo_map_safe 完全一致：

    查询不可用时返回空映射（不预填 0 值，调用方 .get(id, 0) 兜底）+ degraded=True，
    由响应显式告知前端数据不可信 —— 返回全 0 会被业务误读成「这个月一件都没生产」。
    生产记录只读，本包装不服务任何写路径。
    """
    try:
        return await _get_produced_fifo_map(db, details, plan_month), False
    except RuntimeError:
        return {}, True
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_production_attribution.py -v`
Expected: PASS（23 项）

- [ ] **Step 5: 实现聚合层的取映射封装**

在 `purchase_plan_queries.py` 的 `_build_fifo_shipped_map_from_rows` **下方**新增：

```python
async def _build_fifo_produced_map_from_rows(
    db: AsyncSession,
    rows: list,
    plan_month: str = '',
) -> tuple[dict[int, int], bool]:
    """从 SQL 查询结果行构建 FIFO 生产量映射。

    与出货版的差别：不需要 customer_name_map（生产记录无客户，分组键是 product_id），
    因此少一次 PurchasePlan 客户名查询。

    Args:
        rows: SQL 查询结果行（必须包含 detail_id 字段）

    Returns:
        (detail_produced_map, degraded)
    """
    if not rows:
        return {}, False
    detail_ids = list({row.detail_id for row in rows})
    detail_result = await db.execute(
        select(PurchasePlanDetail)
        .options(load_only(
            PurchasePlanDetail.id, PurchasePlanDetail.plan_id,
            PurchasePlanDetail.product_name, PurchasePlanDetail.product_id,
            PurchasePlanDetail.plan_date, PurchasePlanDetail.quantity,
        ))
        .where(PurchasePlanDetail.id.in_(detail_ids))
        .order_by(PurchasePlanDetail.plan_date, PurchasePlanDetail.id)
    )
    all_details = detail_result.scalars().all()
    produced_map, degraded = await _get_produced_fifo_map_safe(db, all_details, plan_month=plan_month)
    return {d.id: produced_map.get(d.id, 0) for d in all_details}, degraded
```

导入区补 `_get_produced_fifo_map_safe`（与既有的 `_get_shipped_fifo_map_safe` 同一行 import 里加）。

- [ ] **Step 6: 跑既有后端测试确认没破坏现状**

Run: `python -m pytest fastapi_app/tests/test_purchase_plan.py tests/test_purchase_plan_core.py tests/test_production_attribution.py -v`
Expected: PASS（此时端点仍走出货口径，行为未变）

- [ ] **Step 7: 提交**

```bash
git add fastapi_app/services/purchase_plan_shipment.py fastapi_app/services/purchase_plan_queries.py tests/test_production_attribution.py
git commit -m "feat(purchase-plan): 生产量映射的降级包装与聚合层接入"
```

---

### Task 4: 三个聚合端点切口径、字段改名、缓存升版本

**Files:**
- Modify: `fastapi_app/services/purchase_plan_queries.py`（`get_monthly_calendar:253`、`get_customer_summary:338`、`get_monthly_aggregated:395`、`get_day_details:571` 四个装饰器与其函数体）
- Modify: `fastapi_app/schemas/purchase_plan.py:218` 与两处「FIFO 出货量统计降级标记」注释

**Interfaces:**
- Consumes: Task 3 的 `_build_fifo_produced_map_from_rows(db, rows, plan_month) -> (dict[int, int], bool)`
- Produces: 三个端点的响应字段——`rows[]._producedCount` / `_producedPct`、`sku_summary[].produced_qty`、`sku_date_index[].status`（语义改为「按生产达标」）、`customers[].produced_qty`、`customer_totals.total_produced_qty`、`plans_by_date[].produced_qty`、`plans[].produced_qty`、顶层 `produced_pct`

**范围声明（刻意不动）**：`/plans/list`、`/plans/detail/{id}`、`/plans/shipment/progress`、`/plans/inventory-compare` 仍保留出货口径 —— 它们不在本页展示。改本页不扩大范围。

- [ ] **Step 1: 缓存版本上调（四个装饰器）**

四处 `key_builder` 的版本前缀改为：

| 函数 | key_prefix | 改前 | 改后 |
|---|---|---|---|
| `get_monthly_calendar` | `pp:monthly` | `v2:` | `v3:` |
| `get_customer_summary` | `pp:summary` | `v2:` | `v3:` |
| `get_monthly_aggregated` | `pp:agg` | `v1:` | `v2:` |
| `get_day_details` | `pp:day` | `v1:` | `v2:` |

例：

```python
    key_builder=lambda **kwargs: f"v3:y{kwargs.get('year', 0)}:m{kwargs.get('month', 0)}:c{kwargs.get('customer_id', 0)}",
```

`get_customer_summary` 只升版本、**不切口径**：它的端点 `/plans/customer-summary` 前端无人调用（`planApi.customerSummary` 声明了但无组件使用），按设计稿 §5「一并升版本以保持一致，是否清理另议」处理。计划执行者不要顺手扩大范围。

- [ ] **Step 2: `get_monthly_calendar` 改用生产映射**

```python
    detail_shipped_map, fifo_degraded, _customer_name_map = await _build_fifo_shipped_map_from_rows(db, rows, plan_month)
```
改为：
```python
    detail_produced_map, fifo_degraded = await _build_fifo_produced_map_from_rows(db, rows, plan_month)
```

循环内：
```python
        shp_qty = detail_shipped_map.get(row.detail_id, 0)
```
改为：
```python
        prod_qty = detail_produced_map.get(row.detail_id, 0)
```

产出字典：
```python
                'shipped_qty': shp_qty,
                'remaining_qty': row.quantity - shp_qty,
```
改为：
```python
                'produced_qty': prod_qty,
                'remaining_qty': row.quantity - prod_qty,
```

同时把该函数 docstring 里的 `shipped_qty 使用 FIFO 实时分配（与其他端点一致，不再依赖过时的 shipped_qty 缓存字段）` 改为 `produced_qty 使用 FIFO 实时分配（数据源为每日生产记录，与 /purchase-plan 各端点一致）`。

- [ ] **Step 3: `get_monthly_aggregated` 改用生产映射**

```python
    detail_shipped_map, fifo_degraded, _customer_name_map = await _build_fifo_shipped_map_from_rows(db, rows, plan_month)
```
改为：
```python
    detail_produced_map, fifo_degraded = await _build_fifo_produced_map_from_rows(db, rows, plan_month)
```

循环内四组改动：

```python
        shp_qty = detail_shipped_map.get(row.detail_id, 0)
        qty = row.quantity
        remain = qty - shp_qty
        status = 'completed' if shp_qty >= qty else ('partial' if shp_qty > 0 else 'pending')
```
改为：
```python
        prod_qty = detail_produced_map.get(row.detail_id, 0)
        qty = row.quantity
        remain = qty - prod_qty
        status = 'completed' if prod_qty >= qty else ('partial' if prod_qty > 0 else 'pending')
```

日期聚合初始化与累加：
```python
                'shipped_qty': 0, 'shipped_count': 0, 'pending_count': 0,
```
改为：
```python
                'produced_qty': 0, 'produced_count': 0, 'pending_count': 0,
```
```python
        d['shipped_qty'] += shp_qty
        if status == 'completed':
            d['shipped_count'] += 1
```
改为：
```python
        d['produced_qty'] += prod_qty
        if status == 'completed':
            d['produced_count'] += 1
```

SKU 聚合：
```python
            by_key[sku_key] = {'barcode': row.barcode or '—', 'product_name': product_name,
                               'plan_qty': 0, 'shipped_qty': 0, 'remain_qty': 0, 'customer_name': customer_name}
```
改为把 `'shipped_qty'` → `'produced_qty'`；随后的 `sk['shipped_qty'] += shp_qty` → `sk['produced_qty'] += prod_qty`。

客户汇总（产品级与客户级两层）所有 `'shipped_qty'` → `'produced_qty'`，累加语句里的 `shp_qty` → `prod_qty`。

`rows_list` 构造：
```python
            'totalQty': d['total_qty'], '_shippedCount': d['shipped_count'],
            '_pendingCount': d['pending_count'],
            '_shippedPct': round_qty(d['shipped_qty'] / d['total_qty'] * 100, precision_digits=1) if d['total_qty'] > 0 else 0,
```
改为：
```python
            'totalQty': d['total_qty'], '_producedCount': d['produced_count'],
            '_pendingCount': d['pending_count'],
            '_producedPct': round_qty(d['produced_qty'] / d['total_qty'] * 100, precision_digits=1) if d['total_qty'] > 0 else 0,
```

`sku_summary` 构造：
```python
            'plan_qty': sk['plan_qty'], 'shipped_qty': sk['shipped_qty'],
            'remain_qty': sk['remain_qty'], 'customer_name': sk['customer_name'],
            '_pct': round_qty(sk['shipped_qty'] / sk['plan_qty'] * 100, precision_digits=1) if sk['plan_qty'] > 0 else 0,
```
改为 `'produced_qty': sk['produced_qty']` 与 `_pct` 用 `sk['produced_qty']`。

`customer_totals`：
```python
        'total_shipped_qty': sum(s['shipped_qty'] for s in customers),
```
改为：
```python
        'total_produced_qty': sum(s['produced_qty'] for s in customers),
```

函数 docstring 补一句：`rows / sku_summary / customers 的进度字段为 produced_qty / _producedPct，数据源为每日生产记录（三部门相加，窗口见 production_window）`。

- [ ] **Step 4: `get_day_details` 改用生产映射**

```python
    detail_shipped_map, fifo_degraded, _customer_name_map = await _build_fifo_shipped_map_from_rows(db, rows, plan_month)
```
改为：
```python
    detail_produced_map, fifo_degraded = await _build_fifo_produced_map_from_rows(db, rows, plan_month)
```

```python
        shp = detail_shipped_map.get(row.detail_id, 0)
```
改为：
```python
        prod = detail_produced_map.get(row.detail_id, 0)
```

计划字典与累计：
```python
            'barcode': row.barcode, 'quantity': qty, 'shipped_qty': shp,
            'remaining_qty': qty - shp, 'plan_date': date_str,
```
改为：
```python
            'barcode': row.barcode, 'quantity': qty, 'produced_qty': prod,
            'remaining_qty': qty - prod, 'plan_date': date_str,
```
```python
        total_qty += qty
        shipped_qty += shp
```
改为：
```python
        total_qty += qty
        produced_qty += prod
```
并把局部变量声明 `shipped_qty = 0` → `produced_qty = 0`。

返回体：
```python
        'shipped_pct': round_qty(shipped_qty / total_qty * 100, precision_digits=1) if total_qty > 0 else 0,
```
改为：
```python
        'produced_pct': round_qty(produced_qty / total_qty * 100, precision_digits=1) if total_qty > 0 else 0,
```

- [ ] **Step 5: 改 schema**

`fastapi_app/schemas/purchase_plan.py`：

```python
class DayDetailsResponse(BaseModel):
    """指定日期明细响应（6.9：按需加载当日明细）"""
    date: str
    weekday: str = ''
    plans: list[dict] = []
    by_customer: dict[str, list] = {}
    shipped_pct: float = 0.0
    fifo_degraded: bool = False
```
改为把 `shipped_pct` → `produced_pct`，并把 docstring 补为 `（6.9：按需加载当日明细；produced_pct 为按每日生产记录计算的生产达标率）`。

`PlanListResponse` 与 `MonthlyCalendarResponse` 里那两行注释「FIFO 出货量统计降级标记（服务异常时为 True，前端可提示数据可能不完整）」统一改为「FIFO 分配降级标记（服务异常时为 True，前端可提示数据可能不完整）」—— 它现在同时服务出货与生产两条路径。

**不要**动 `PurchasePlanDetailItem.shipped_qty`、`ShipmentProgressItem.shipped_qty`、`PurchasePlanItem.total_shipped`、`CustomerSummaryItem.shipped_qty`、`CustomerSummaryResponse.total_shipped_qty`：它们属于 §范围声明 里刻意不动的端点。

- [ ] **Step 6: 跑后端测试**

Run: `python -m pytest fastapi_app/tests/test_purchase_plan.py tests/test_purchase_plan_core.py tests/test_production_attribution.py -v`
Expected: `test_purchase_plan.py` 中出现与 `shipped_pct` 相关的 FAIL（Task 5 修）；其余 PASS

- [ ] **Step 7: 提交**

```bash
git add fastapi_app/services/purchase_plan_queries.py fastapi_app/schemas/purchase_plan.py
git commit -m "feat(purchase-plan): 三个聚合端点改用生产口径并改名 produced_*，缓存升版本"
```

---

### Task 5: 更新后端既有测试的断言

这一步不是形式主义：`test_purchase_plan.py` 是 mock 服务层的，它的 canned payload 就是「服务契约的备忘」。若不改，mock 会继续宣告 `shipped_pct` 这个已不存在的字段 —— 下次有人照着它写代码就会踩空。

**Files:**
- Modify: `fastapi_app/tests/test_purchase_plan.py`

**Interfaces:**
- Consumes: Task 4 的字段名
- Produces: 与真实契约一致的 mock payload

- [ ] **Step 1: 改 `/plans/day-details` 的 mock 与断言**

`test_purchase_plan.py` 中共三处 `shipped_pct`（mock payload 里约第 470、494 行，断言里约第 485 行）：

```python
            'shipped_pct': 20.0,
```
→
```python
            'produced_pct': 20.0,
```
```python
        assert data['shipped_pct'] == 20.0
```
→
```python
        assert data['produced_pct'] == 20.0
```

- [ ] **Step 2: 改 `/plans/monthly` 与 `/plans/monthly-aggregated` 的 mock payload 字段**

把这两组测试 payload 里表示**进度**的 `shipped_qty` 改成 `produced_qty`：

- `/plans/monthly`：`plans_by_date` 里那条 `{'product_id': 1, ..., 'total_qty': 200, 'shipped_qty': 50}` 与 `customers` 里那条 —— 改 `shipped_qty` → `produced_qty`
- `/plans/monthly-aggregated`：其 `rows` / `sku_summary` / `customers` mock 里的 `shipped_qty` → `produced_qty`，`_shippedCount` → `_producedCount`，`_shippedPct` → `_producedPct`，`total_shipped_qty` → `total_produced_qty`（含对应的 `assert ... == ...` 断言）

**不要**动 `/plans/list`、`/plans/detail/*` 相关 payload 里的 `shipped_qty` / `total_shipped` —— 那些端点仍走出货口径（见 Task 4 范围声明）。判断依据：看该 payload 属于哪个 `client.get(...)` 调用。

- [ ] **Step 3: 跑测试确认通过**

Run: `python -m pytest fastapi_app/tests/test_purchase_plan.py -v`
Expected: PASS（全绿）

- [ ] **Step 4: 全量后端测试**

Run: `python -m pytest fastapi_app/tests/ tests/ -q`
Expected: PASS。若有与本次无关的既有失败，先 `git stash` 不动它、记录下来并在提交信息里说明——但**不要**为了让全绿而改别人的断言。（注：记忆里 policy 类测试在本机会因环境差异必红，属既有现象。）

- [ ] **Step 5: 提交**

```bash
git add fastapi_app/tests/test_purchase_plan.py
git commit -m "test(purchase-plan): 端点 mock 与断言跟进 produced_* 字段"
```

---

### Task 6: 前端桌面（类型、读取点、文案、导出）

顺序很关键：**先改 `types.ts`，再跑 `npm run type-check`** —— 类型检查器会把所有还读旧字段的地方逐个列出来，比人工 grep 可靠。文案与字段要一起改，不能只改字段留下「已出货」的字。

**Files:**
- Modify: `src/views/purchase-plan/components/types.ts`
- Modify: `src/views/purchase-plan/composables/useSkuSummary.ts`（`fieldMap`）
- Modify: `src/views/purchase-plan/components/dayStatus.ts`
- Modify: `src/views/purchase-plan/components/PlanMonthGrid.vue`
- Modify: `src/views/purchase-plan/components/PurchasePlanDailyTab.vue`
- Modify: `src/views/purchase-plan/components/PlanDayDetail.vue`
- Modify: `src/views/purchase-plan/components/SkuSummaryTable.vue`
- Modify: `src/views/purchase-plan/components/PurchasePlanKpiStrip.vue`
- Modify: `src/views/purchase-plan/PurchasePlanView.vue`
- Modify: `src/views/purchase-plan/components/PlanDetailDialog.vue`
- Modify: `src/views/purchase-plan/components/PlanDialogPlanList.vue`
- Modify: `src/views/purchase-plan/components/PlanDialogCustomerList.vue`
- Test: `src/test/planDayStatus.test.ts`、`src/test/purchasePlanDailyTab.test.ts`、`src/test/purchasePlanKpiStrip.test.ts`、`src/test/purchasePlanMonthlySummary.test.ts`

**Interfaces:**
- Consumes: Task 4 的响应字段（`_producedPct` / `_producedCount` / `produced_qty` / `produced_pct`）
- Produces: 前端类型与后端契约同名；`useSkuSummary` 的排序字段键由 `shipped` 改为 `produced`

- [ ] **Step 1: 先把测试改成目标字段，跑出红灯**

`src/test/planDayStatus.test.ts` 的 `row()` 助手：
```ts
const row = (date: string, shippedPct: number, pendingCount: number) => ({
  date,
  _shippedPct: shippedPct,
  _pendingCount: pendingCount,
})
```
改为：
```ts
const row = (date: string, producedPct: number, pendingCount: number) => ({
  date,
  _producedPct: producedPct,
  _pendingCount: pendingCount,
})
```

`src/test/purchasePlanDailyTab.test.ts` 的 `row()` 助手：`_shippedPct:` / `_shippedCount:` 改为 `_producedPct:` / `_producedCount:`。

`src/test/purchasePlanKpiStrip.test.ts`：`KPI` 常量里的 `shippedQty: 14065` 改为 `producedQty: 14065`。

`src/test/purchasePlanMonthlySummary.test.ts` 的 `sku()` 助手：返回体里的 `shipped_qty: shipped` 改为 `produced_qty: shipped`（本地参数名 `shipped` 可保留，它只是构造用的临时名）。同时把「已出货配色分级」那条用例里对 `.td-num` 的断言保持不变（配色规则不变，只是字段换名）。

Run: `npm test --prefix frontend-vite -- src/test/planDayStatus.test.ts src/test/purchasePlanDailyTab.test.ts src/test/purchasePlanKpiStrip.test.ts src/test/purchasePlanMonthlySummary.test.ts`
Expected: FAIL —— 类型不匹配 / 断言失败

- [ ] **Step 2: 改类型**

`types.ts` 四处字段改名（`remaining_qty` / `remain_qty` / `status` 不动）：
```ts
export interface Plan {
  ...
  produced_qty: number;      // 原 shipped_qty
  remaining_qty: number;
  ...
}
```
```ts
export interface Row {
  ...
  _producedCount: number;    // 原 _shippedCount
  _pendingCount: number;
  _producedPct: number;      // 原 _shippedPct
  ...
}
```
```ts
export interface SkuRow {
  ...
  produced_qty: number;      // 原 shipped_qty
  remain_qty: number;
  ...
}
```
```ts
export interface CustSumItem {
  ...
  produced_qty: number;      // 原 shipped_qty
  remaining_qty: number;
  ...
}
```

- [ ] **Step 3: 让类型检查器列出所有待改点**

Run: `npm run type-check --prefix frontend-vite`
Expected: 列出全部仍读旧字段的文件与行号 —— 用这份清单逐条改，不要凭记忆

- [ ] **Step 4: 改 `dayStatus.ts`**

```ts
export function dayMarkFor(
  row: Pick<Row, 'date' | '_shippedPct' | '_pendingCount'>,
  todayMs: number,
): DayMark {
  if (row._shippedPct === 100) return { cls: 'st-g', lbl: '✓ 完成' }
```
改为 `Pick<Row, 'date' | '_producedPct' | '_pendingCount'>` 与 `if (row._producedPct === 100)`。该文件顶部注释里的「已全部出货 → 完成」改为「已全部生产 → 完成」。

- [ ] **Step 5: 改读旧字段的四个组件**

`PlanMonthGrid.vue` 两处（进度条）：
```html
          <i :class="barCls(c.row._shippedPct)" :style="{ width: c.row._shippedPct + '%' }" />
```
→
```html
          <i :class="barCls(c.row._producedPct)" :style="{ width: c.row._producedPct + '%' }" />
```

`PurchasePlanDailyTab.vue`（风险判定）：
```ts
    if (r._shippedPct === 100 || r._pendingCount <= 0) continue
```
→
```ts
    if (r._producedPct === 100 || r._pendingCount <= 0) continue
```

`SkuSummaryTable.vue`：
- `SORT_COLS` 的键与表头文案：
```ts
const SORT_COLS = [
  { key: 'plan', label: '计划数量' },
  { key: 'shipped', label: '已出货' },
  { key: 'remain', label: '待出货' },
] as const
```
→
```ts
const SORT_COLS = [
  { key: 'plan', label: '计划数量' },
  { key: 'produced', label: '已生产' },
  { key: 'remain', label: '待生产' },
] as const
```
- 数据绑定与配色函数：
```html
          <td class="td-num num" :class="shippedCls(s)">{{ fmt(s.shipped_qty) }}</td>
```
→
```html
          <td class="td-num num" :class="producedCls(s)">{{ fmt(s.produced_qty) }}</td>
```
```ts
/** 一件未出点红、出完点绿、出了部分点琥珀 —— 只判「是否为 0」会把「出了一点点」也显示成完成 */
function shippedCls(s: SkuRow): string {
  if (Number(s.shipped_qty || 0) <= 0) return 'td-zero'
  if (Number(s.shipped_qty || 0) >= Number(s.plan_qty || 0)) return 'td-done'
  return 'td-part'
}
```
→
```ts
/** 一件未生产点红、产完点绿、产了部分点琥珀 —— 只判「是否为 0」会把「只产了一点点」也显示成完成 */
function producedCls(s: SkuRow): string {
  if (Number(s.produced_qty || 0) <= 0) return 'td-zero'
  if (Number(s.produced_qty || 0) >= Number(s.plan_qty || 0)) return 'td-done'
  return 'td-part'
}
```

`useSkuSummary.ts` 的 `fieldMap`（与上面 `SORT_COLS` 的键必须一致）：
```ts
    const fieldMap: Record<string, keyof SkuRow> = { customer: 'customer_name', barcode: 'barcode', plan: 'plan_qty', shipped: 'shipped_qty', remain: 'remain_qty' };
```
→
```ts
    const fieldMap: Record<string, keyof SkuRow> = { customer: 'customer_name', barcode: 'barcode', plan: 'plan_qty', produced: 'produced_qty', remain: 'remain_qty' };
```

- [ ] **Step 6: 改 KPI 格与页面取数**

`PurchasePlanKpiStrip.vue`：
```html
      <span class="sp-kpi-l">本月已出</span>
      <span class="sp-kpi-v num">{{ fmt(shippedQty) }}</span>
      <span class="sp-kpi-s num">件 · 待出 {{ fmt(remainQty) }}</span>
```
→
```html
      <span class="sp-kpi-l">本月已生产</span>
      <span class="sp-kpi-v num">{{ fmt(producedQty) }}</span>
      <span class="sp-kpi-s num">件 · 待生产 {{ fmt(remainQty) }}</span>
```
props 里 `shippedQty: number` → `producedQty: number`。

`PurchasePlanView.vue`：
```ts
  let planQty = 0, shipQty = 0, remainQty = 0;
  for (const c of cs) {
    planQty += Number(c.plan_qty || 0);
    shipQty += Number(c.shipped_qty || 0);
    remainQty += Number(c.remaining_qty || 0);
  }
  const pct = planQty > 0 ? Math.floor(shipQty / planQty * 1000) / 10 : 0;
  return {
    allQty: String(planQty),
    allShipped: String(shipQty),
```
改为把 `shipQty` 换成 `prodQty`、`c.shipped_qty` 换成 `c.produced_qty`、返回键 `allShipped` 换成 `allProduced`：
```ts
  let planQty = 0, prodQty = 0, remainQty = 0;
  for (const c of cs) {
    planQty += Number(c.plan_qty || 0);
    prodQty += Number(c.produced_qty || 0);
    remainQty += Number(c.remaining_qty || 0);
  }
  const pct = planQty > 0 ? Math.floor(prodQty / planQty * 1000) / 10 : 0;
  return {
    allQty: String(planQty),
    allProduced: String(prodQty),
```
```ts
const shippedQtyNum = computed(() => Number(sKpi.value.allShipped || 0));
```
→
```ts
const producedQtyNum = computed(() => Number(sKpi.value.allProduced || 0));
```
模板里的 prop 传递：
```html
            :shipped-qty="shippedQtyNum"
```
→
```html
            :produced-qty="producedQtyNum"
```
导出 CSV：
```ts
  const h = buildCsvRow(['客户名称', '产品名称', '商品条码', '计划数量', '已出货', '待出货', '进度']);
  const ls = [h];
  for (const s of list) ls.push(buildCsvRow([s.customer_name, s.product_name, s.barcode, s.plan_qty, s.shipped_qty, s.remain_qty, s._pct + '%']));
```
→
```ts
  const h = buildCsvRow(['客户名称', '产品名称', '商品条码', '计划数量', '已生产', '待生产', '进度']);
  const ls = [h];
  for (const s of list) ls.push(buildCsvRow([s.customer_name, s.product_name, s.barcode, s.plan_qty, s.produced_qty, s.remain_qty, s._pct + '%']));
```

- [ ] **Step 7: 改当日明细弹窗的三个组件**

`PlanDetailDialog.vue`：
```ts
const shippedPct = computed(() => (dayData.value?.shipped_pct as number) ?? props.detail?._shippedPct ?? 0);
```
→
```ts
const producedPct = computed(() => (dayData.value?.produced_pct as number) ?? props.detail?._producedPct ?? 0);
```
模板两处 `shippedPct` → `producedPct`（`:style="{ width: ... }"` 与 `{{ ... }}%`）。
```ts
function getShipmentStatus(quantity: number, shippedQty: number): string {
  if (shippedQty >= quantity) return 'completed';
  if (shippedQty > 0) return 'partial';
  return 'pending';
}
```
→
```ts
function getProductionStatus(quantity: number, producedQty: number): string {
  if (producedQty >= quantity) return 'completed';
  if (producedQty > 0) return 'partial';
  return 'pending';
}
```
调用点 `getShipmentStatus(p.quantity, p.shipped_qty)` → `getProductionStatus(p.quantity, p.produced_qty)`。
导出当日 CSV：
```ts
  const h = '客户,产品,条码,数量,已出,待出,状态';
```
→
```ts
  const h = '客户,产品,条码,数量,已生产,待生产,状态';
```
（该函数里 `st === 'completed' ? '已出货' : st === 'partial' ? '部分出货' : '待出货'` 文案同步改为 `'已生产' / '部分生产' / '待生产'`。）

**不动**：同一文件里 `ShipmentRecordsTab` 那段（模板 `v-else` 分支与 import）与 `planApi.shipmentRecords` —— 那是真实出货流水。

`PlanDialogPlanList.vue`：
```html
        <span>计划</span>
        <span>已出</span>
        <span>待出</span>
```
→
```html
        <span>计划</span>
        <span>已生产</span>
        <span>待生产</span>
```
```html
                <span class="sp-plan-qty-value sp-qty-green">{{ p.shipped_qty }}</span>
```
→
```html
                <span class="sp-plan-qty-value sp-qty-green">{{ p.produced_qty }}</span>
```

`PlanDialogCustomerList.vue`：
```html
            <span class="sp-customer-summary-item sp-customer-summary-shipped"><b>{{ entry.plans.reduce((s: number, p: Plan) => s + Number(p.shipped_qty || 0), 0) }}</b> 已出</span>
```
→
```html
            <span class="sp-customer-summary-item sp-customer-summary-shipped"><b>{{ entry.plans.reduce((s: number, p: Plan) => s + Number(p.produced_qty || 0), 0) }}</b> 已生产</span>
```
（CSS 类名 `sp-customer-summary-shipped` 属于内部命名，不改；同文件「待出」文案改为「待生产」。）

- [ ] **Step 8: 类型检查与测试全绿**

Run: `npm run type-check --prefix frontend-vite`
Expected: 干净（无输出）

Run: `npm test --prefix frontend-vite`
Expected: PASS（全部，含 Task 6 Step 1 改过的四个测试文件）

- [ ] **Step 9: 构建**

Run: `npm run build --prefix frontend-vite`
Expected: `✓ built in ...`

- [ ] **Step 10: 提交**

```bash
git add frontend-vite/src/views/purchase-plan frontend-vite/src/test
git commit -m "refactor(purchase-plan): 前端进度口径与措辞改为已生产/待生产"
```

---

### Task 7: 移动端出货页

**Files:**
- Modify: `src/mobile/views/shipment/MShipmentView.vue`

**Interfaces:**
- Consumes: Task 4 的 `/plans/monthly` → `plans_by_date[].produced_qty`
- Produces: 无（末端消费者）

- [ ] **Step 1: 改字段与汇总变量（含模板三处文案）**

模板摘要卡（第 40-47 行）：
```html
            <div class="m-summary-item">
              <span class="m-summary-label">已出货</span>
              <span class="m-summary-val m-summary-done">{{ fmtQty(dateShipped) }}</span>
            </div>
            <div class="m-summary-item">
              <span class="m-summary-label">剩余</span>
              <span class="m-summary-val m-summary-remain">{{ fmtQty(dateRemain) }}</span>
            </div>
```
→
```html
            <div class="m-summary-item">
              <span class="m-summary-label">已生产</span>
              <span class="m-summary-val m-summary-done">{{ fmtQty(dateProduced) }}</span>
            </div>
            <div class="m-summary-item">
              <span class="m-summary-label">待生产</span>
              <span class="m-summary-val m-summary-remain">{{ fmtQty(dateRemain) }}</span>
            </div>
```
（「剩余」→「待生产」是设计稿 success_criteria「措辞统一为已生产/待生产」的要求，不是可选项。第 38 行的「计划总量」与第 51-53 行的 `datePct` 不动。）

列表项（第 71 行）：
```html
                <span class="m-item-sub">已出{{ p.shipped_qty }} | 剩{{ p.remaining_qty }}</span>
```
→
```html
                <span class="m-item-sub">已生产{{ p.produced_qty }} | 待生产{{ p.remaining_qty }}</span>
```

脚本汇总变量：
```ts
const dateShipped = computed(() => selectedPlans.value.reduce((s, p) => s + Number(p.shipped_qty || 0), 0))
const dateRemain = computed(() => dateTotal.value - dateShipped.value)
const datePct = computed(() => dateTotal.value > 0 ? Math.floor(dateShipped.value / dateTotal.value * 1000) / 10 : 0)
```
→
```ts
const dateProduced = computed(() => selectedPlans.value.reduce((s, p) => s + Number(p.produced_qty || 0), 0))
const dateRemain = computed(() => dateTotal.value - dateProduced.value)
const datePct = computed(() => dateTotal.value > 0 ? Math.floor(dateProduced.value / dateTotal.value * 1000) / 10 : 0)
```
`dateShipped` 在模板第 42 行还有一处引用（已在上面的替换里改为 `dateProduced`）。改完用 `grep -n "dateShipped" frontend-vite/src/mobile` 确认无残留。

- [ ] **Step 2: 改状态文案**

```ts
function statusLabel(status: string) {
  const map: Record<string, string> = { shipped: '已出货', completed: '已出货', partial: '部分出货', pending: '待出货' }
  return map[status] || '待出货'
}
```
→
```ts
function statusLabel(status: string) {
  const map: Record<string, string> = { shipped: '已生产', completed: '已生产', partial: '部分生产', pending: '待生产' }
  return map[status] || '待生产'
}
```
`dotClass` / `statusClass` 里的状态键（`shipped` / `completed` / `partial`）**不改** —— 它们是内部标识，不是展示文案。

- [ ] **Step 3: 顺手修一个既有缺陷（如不想扩大范围可跳过本步）**

发现：这三个函数收到的 `p.shipment_status` **恒为 `undefined`** —— 它读的是 `Plan` 类型上的字段，而 `/plans/monthly` 的 `plans_by_date[]` 根本不返回该字段（见 `get_monthly_calendar` 的产出字典）。因此移动端的状态圆点与文案**一直显示「待生产/待出货」**，与数据无关。这是本次改动之前就存在的缺陷，与口径无关。

既然 Task 4 已把 `produced_qty` 与 `quantity` 都送到前端，就地推导即可让这个状态真正工作（规则与后端 `status` 一致）：

```ts
function statusOf(p: Plan): string {
  const qty = Number(p.quantity || 0)
  const produced = Number(p.produced_qty || 0)
  if (qty > 0 && produced >= qty) return 'completed'
  if (produced > 0) return 'partial'
  return 'pending'
}
```
模板三处 `p.shipment_status` 改为 `statusOf(p)`：
```html
              <div :class="['m-item-dot', dotClass(statusOf(p))]" />
```
```html
                <span :class="['m-item-status', statusClass(statusOf(p))]">
                  {{ statusLabel(statusOf(p)) }}
                </span>
```

若决定跳过本步，请在提交信息里写明「移动端状态字段不可用属既有缺陷，另议」，不要留着不说。

- [ ] **Step 4: 类型检查与构建**

Run: `npm run type-check --prefix frontend-vite`
Expected: 干净

Run: `npm run build --prefix frontend-vite`
Expected: `✓ built in ...`

- [ ] **Step 5: 提交**

```bash
git add frontend-vite/src/mobile/views/shipment/MShipmentView.vue
git commit -m "refactor(shipment-mobile): 进度口径与措辞改为已生产，并修复恒为 undefined 的状态字段"
```

---

### Task 8: 全量验证与门禁

**Files:** 无新增；只跑验证。若发现遗漏则回到对应任务补正。

- [ ] **Step 1: 后端全量**

Run: `python -m pytest fastapi_app/tests/ tests/ -q`
Expected: PASS（记录任何与本次无关的既有失败，不要为凑绿改他人断言）

- [ ] **Step 2: 前端全量**

Run: `npm run type-check --prefix frontend-vite && npm test --prefix frontend-vite && npm run build --prefix frontend-vite`
Expected: 三项依次通过

- [ ] **Step 3: 门禁**

Run: `python scripts/quality_gate.py`
Expected: `[PASS]`，退出码 0，且「前端巨型 Vue 组件」计数与基线一致（本次未新增超 400 行文件）

- [ ] **Step 4: 残留检查 —— 确认没有漏网的旧字段**

Run（应无输出）：
```bash
grep -rn "_shippedPct\|_shippedCount\|shipped_pct" frontend-vite/src fastapi_app/services/purchase_plan_queries.py fastapi_app/services/fifo_allocation.py
```
Run（下列命中应**只剩**刻意不动的端点：`/plans/list`、`/plans/detail/*`、`/plans/shipment/progress`、`/plans/inventory-compare`、`get_customer_summary`、`ShipmentRecordsTab`）：
```bash
grep -rn "shipped_qty" fastapi_app/services fastapi_app/schemas frontend-vite/src
```

- [ ] **Step 5: 人工验收（必须由人做）**

本机开不了浏览器预览，以下只能由用户完成：

1. 桌面 `/purchase-plan`：KPI 显示「本月已生产」；月历格子的状态色与进度条随生产记录变化；点某天，右栏明细的产品状态为 已生产/部分/待生产。
2. 月度汇总 Tab：列头为「已生产/待生产」，导出 CSV 表头一致。
3. 弹窗：计划明细列头为「已生产/待生产」；**出货记录子页签仍显示真实出货流水**（这是预期，不是回退）。
4. 移动端 `/shipment`：数量与状态随生产数据变化。
5. 造数验证：给某产品在本月窗口内录入一条生产记录，刷新后该产品所有计划行的「已生产」应上升；删除该记录后应回落（验证 Task 2 的缓存失效钩子真的生效 —— 若刷新后不变，就是钩子没接上）。

- [ ] **Step 6: 提交（若前几步有补正）**

```bash
git add -A frontend-vite/src fastapi_app docs
git commit -m "chore(purchase-plan): 生产口径迁移的收尾补正"
```

---

## 交付后的交接说明

- 本计划**不改**出货记录相关的任何读写路径。用户若在页面上看到「出货记录」子页签仍叫出货、仍显示出货流水，那是预期行为 —— 进度口径与出货流水是两件事。
- `get_customer_summary` 只升了缓存版本、未切口径（其端点前端无人调用）。若后续要清理该端点，属独立任务。
- 移动端 Task 7 Step 3 修复的是一个本次之前就存在的缺陷；若被跳过，需另开任务。




