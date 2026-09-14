# P0-02　`_recalc_plans_common` 返回元数不一致 → **出货后采购计划静默失准**

> 标题修正：原写「出货创建 500」，但复核确认异常被上层 `except Exception` 吞成 ERROR 日志，
> 实际后果是**数据静默不一致**而非接口报错（详见下文「后果比 500 更严重」）。

| 字段 | 值 |
|---|---|
| 严重度 | 🔴 高（**严重度已较报告上调**，见下） |
| 类型 | 缺陷 · 正确性 |
| 模块 | `fastapi_app/services/purchase_plan_shipment.py` |
| 预估工时 | 20 min（含补测） |
| 批次 | B（若生产日志已出现该异常 → 提到批次 A 热修） |
| 依赖 | 无 |
| **状态** | ✅ **已修复（2026-09-12 23:58）** |

---

## ✅ 执行记录（2026-09-12）

**改动**：`purchase_plan_shipment.py` 仅 +9 / −4 行
1. L151 注解：`-> tuple[dict[int, dict], int]` → `-> tuple[dict[int, dict], int, set[str]]`
   （`PurchasePlan.plan_month: Mapped[str]` → 集合元素为 `str`）
2. L170 早退 A：`return {}, 0` → `return {}, 0, set()`
3. L178 早退 B：`return {}, len(affected_plans)` → `return {}, len(affected_plans), set()`
4. docstring 补「三处 return 必须元数一致」+ 记录 9/10 事故缘由，避免下一个人再踩

**静态检查取证（修复前已确认能抓到，非事后附会）**

`mypy` 在修复前对这个缺陷报了 **3 处**（`--follow-imports=skip` 亦然）：
```
purchase_plan_shipment.py:207: error: Incompatible return value type
    (got "tuple[dict[int, dict[Any, Any]], int, set[Any]]", expected "tuple[dict[int, dict[Any, Any]], int]")
purchase_plan_shipment.py:254: error: Need more than 2 values to unpack
purchase_plan_shipment.py:285: error: Need more than 2 values to unpack
```
修复后 mypy 与 ruff 均 **clean**。
> 注解修正是本工单的**关键防御**：此后任何"新增返回值只改主路径"的漏改都会被静态检查拦住。
> 二进制：`C:/Users/Administrator/.workbuddy/binaries/python/envs/default/Scripts/mypy.exe`

**测试交付物** `fastapi_app/tests/test_shipment_recalc_common.py`（5 个用例，覆盖三处 return）

**双向验证（关键证据）**
```
修复后：5 passed
git stash push -- purchase_plan_shipment.py 后：5 failed
  ValueError: not enough values to unpack (expected 3, got 2)
  purchase_plan_shipment.py:285: in recalc_plans_after_stockout_create
```
traceback **与 2026-09-10 生产日志逐字一致**（同一行 `:285`、同一消息）→ 测试确实复现了生产故障。

**回归**：`test_purchase_plan.py` / `test_stock.py`（两处）/ `test_batch_stockout.py` /
`test_purchase_plan_core.py` / `test_auxiliary.py` / `test_case.py` 合计 **170 passed，0 failed**。

**存量数据一致性**：`docs/tickets/tools/check_shipped_qty_consistency.py`（只读）
```
待核对明细: 7 行，涉及主单 6 张
✅ 一致性通过：7 行明细的 shipped_qty 全部等于重算值
```
→ **未发现被本缺陷污染的存量数据**。该脚本可复用于发布后复检。

### ⚠️ 执行时对本文档下方方案做的 4 处修正

| 原文 | 修正 | 原因 |
|---|---|---|
| 验收项用 `db` fixture | 改用 **`mock_db`** | `fastapi_app/tests/` 的 conftest 提供的是 `mock_db`（+ autouse `override_deps`），无真实 `db` fixture |
| 验收项 4 引用 `fastapi_app/tests/test_shipment_limit.py` | 该文件**不存在**，改跑实际存在的 6 个相关文件 | 路径写错 |
| 验收项 5 给了一条 `SUM(s.quantity)` 的核对 SQL | **废弃该 SQL**，改为调用应用自身 `fifo_allocation` 的只读脚本 | `shipped_qty` 不是 `SUM(quantity)`，而是按 `plan_date ASC` 的**累计 FIFO 分配**，且要扣 `StockOut.returned_quantity`、受出货日期窗口限制、有 product_id / name 双匹配分支；那条 SQL 会产出**假阳性**。另外真实列名是 `StockOut.customer` 而非 `customer_name` |
| （另）NamedTuple 加固建议 | **未采纳** | 注解已声明为 3 元组，mypy 已能拦住同类漏改；且带 `set` 字段的 NamedTuple 不可哈希。改动返回类型收益不抵风险 |

下述「修复方案」「验收标准」段落保留为原始方案记录，**实际以本节为准**。

---

## ⚠️ 严重度上调说明

初审报告写的是"客户名/产品名为空时触发"。**回源码复核后确认触发面比这大得多**：

`_recalc_plans_common` 有 **两处**早退返回 2 元组（`:170` 和 `:178`），而调用方按 3 元组解包。
其中 `:178` 的分支条件是「查不到受影响计划 **或** 查不到关联明细」——

```python
if not affected_plans or not related_details:
    return {}, len(affected_plans)      # ← 2 元组
```

而调用链是**出货创建的主路径**：

```
出货创建 → purchase_plan_service.py:167
        → recalc_plans_after_stockout_create(db, customer_name, product_name)
        → purchase_plan_shipment.py:285
           status_changes, affected_count, affected_plan_months = await _recalc_plans_common(...)   # ← 解包 3 个
```

**即：只要某次出货的「客户 + 产品」组合在采购计划里没有对应行，就会命 `:178` → `ValueError`。**
这在新客户、新产品的首次出货、或采购计划未维护的组合上都很容易发生。

---

## 🔴 实证：该缺陷已在生产触发过（2026-09-10）

**这不是推演，有日志证据。**

```bash
grep -a -n "not enough values to unpack" logs/server_manager_20260910.log
```

```
logs/server_manager_20260910.log:345:[2026-09-10 10:34:28,184] ...
  fastapi_app.services.purchase_plan_service - ERROR - STOCK_OUT_CREATED 处理失败:
  customer=SIMTEST-CUST-20260910 product=SIMTEST-PROD-20260910103426
  error=not enough values to unpack (expected 3, got 2)

logs/server_manager_20260910.log:349:
  File "D:\erp_system\fastapi_app\services\purchase_plan_shipment.py", line 285,
  in recalc_plans_after_stockout_create
logs/server_manager_20260910.log:350:
  status_changes, affected_count, affected_plan_months = await _recalc_plans_common(
```

**行号 `purchase_plan_shipment.py:285` 与本工单定位完全一致。**
触发数据为 `SIMTEST-*`（压力测试夹具），即压测造出"没有采购计划的客户+产品"组合后立即命中。

> 其余日志（`fastapi_20260911/12.log`、`erp-prod.log`、`后端(uvicorn).out.log`）中该错误 **0 次**
> → 9/10 之后未再复现，但不代表已修复：只要再出现一个"客户+产品无采购计划行"的组合就会重演。

### 后果比"500"更严重：静默数据不一致

调用点位于**领域事件订阅器**内，异常被宽泛捕获后**只打日志、不抛出**：

`fastapi_app/services/purchase_plan_service.py:162-178`

```python
        try:
            from fastapi_app.core.database import get_async_db_context
            async with get_async_db_context() as db:
                if need_recalc_create:
                    await recalc_plans_after_stockout_create(db, customer_name, product_name)   # ← 这里抛 ValueError
                ...
            if plan_month:
                await _invalidate_plan_caches(plan_month)
        except Exception as e:  # defensive: 单个事件处理失败不影响其他事件
            logger.error(                                                         # ← 被吞掉，只留 ERROR 日志
                '%s 处理失败: customer=%s product=%s error=%s',
                event_name, customer_name, product_name, e, exc_info=True,
            )
```

因此实际影响是：

| 维度 | 实际情况 |
|---|---|
| 用户侧 | **出货成功，无任何提示**（不是报错，是"看起来一切正常"） |
| 数据侧 | **采购计划的 `shipped_qty` 未重算、状态未更新** → 采购计划与实际出货**静默不一致** |
| 缓存侧 | `_invalidate_plan_caches` 被跳过 → 前端可能继续显示旧值（叠加 30–60 s TTL） |
| 可观测性 | 仅日志一行 ERROR；**没有人会主动去看** |
| 暴露程度 | 这就是缺陷能潜伏至今的原因 —— 用户完全无感 |

**结论：本工单的性质需要重新定义 —— 它不是"接口 500 缺陷"，而是"出货后采购计划数据静默失准"。**
后者更难发现、对业务决策的影响更大（采购计划是补货依据）。

> 另有一条次要路径：若**不经事件包装、直接调用** `recalc_plans_after_stockout_create`，
> `ValueError` 会穿透成 500。两条路径都应覆盖（见验收项 3）。

## 定位

`fastapi_app/services/purchase_plan_shipment.py:141-207`

```python
async def _recalc_plans_common(
    db: AsyncSession,
    customer_name: str,
    product_name: str,
    action_type: str,
    *,
    operator: str = '',
    snapshot_before: dict[int, dict] | None = None,
    extra_old_value: dict | None = None,
    prefetched: tuple[list, list, list] | None = None,
) -> tuple[dict[int, dict], int]:          # ← 注解声明 2 元素
    """...
    返回:
        (状态变更字典, 受影响计划数)          # ← docstring 也只写 2 个
    """
    if not customer_name or not product_name:
        return {}, 0                        # ← L170  早退 A：2 元组

    if prefetched is not None:
        affected_plans, all_affected_details, related_details = prefetched
    else:
        affected_plans, all_affected_details, related_details = await _fetch_affected_plans_and_details(...)

    if not affected_plans or not related_details:
        return {}, len(affected_plans)      # ← L178  早退 B：2 元组（最容易命中）

    ...
    affected_plan_months = {p.plan_month for p in affected_plans if p.plan_month}
    return status_changes, len(affected_plans), affected_plan_months   # ← L207  正常：3 元组
```

调用方（两处，均按 3 元组解包）：

```python
# L254  已在调用前自行做了空值/空结果守卫，故实际只可能命 L178
status_changes, _, affected_plan_months = await _recalc_plans_common(...)

# L285  ⚠️ 无任何守卫，直接调用 → 命 L170 或 L178 任意一条即 500
status_changes, affected_count, affected_plan_months = await _recalc_plans_common(...)
```

## 根因

`affected_plan_months` 是后续新增的返回项（用于 `_invalidate_plan_caches`），
但**只改了正常返回路径和调用方，漏改了两处早退路径与类型注解/docstring**。

一个加剧因素：`:285` 所在的 `recalc_plans_after_stockout_create` 只捕获 `RuntimeError`（上层 `_get_shipped_fifo_map_safe` 亦然），
`ValueError` 一路穿透到全局异常处理器 → 500，**业务上表现为"出货成功但接口报错"或"出货直接失败"**，取决于事务时机。

## 修复方案

```diff
--- a/fastapi_app/services/purchase_plan_shipment.py
+++ b/fastapi_app/services/purchase_plan_shipment.py
@@
-) -> tuple[dict[int, dict], int]:
+) -> tuple[dict[int, dict], int, set]:
     """...
     返回:
-        (状态变更字典, 受影响计划数)
+        (状态变更字典, 受影响计划数, 受影响计划月份集合)
+        注意：三处 return 必须元数一致，调用方统一按 3 元组解包。
     """
     if not customer_name or not product_name:
-        return {}, 0
+        return {}, 0, set()
@@
     if not affected_plans or not related_details:
-        return {}, len(affected_plans)
+        return {}, len(affected_plans), set()
```

> 只有这 3 行是必需的。注解与 docstring 一并修正，避免下一个人又踩同一个坑。

**更彻底的防御（建议同批做，2 行）**：让错误在**定义处**就报错而不是在调用处。可选方案——
把返回改成 `NamedTuple`，则 `return {}, 0` 会在函数内部立刻 `TypeError`，能被测试直接捕获：

```python
class RecalcResult(NamedTuple):
    status_changes: dict[int, dict]
    affected_count: int
    affected_months: set
```
（若团队不接受改动返回类型，跳过此项，仅做上面的 3 行修复即可。）

## 验收标准

1. **新增单测**（本工单的核心交付物）——`fastapi_app/tests/test_shipment_recalc_common.py`
   ```python
   @pytest.mark.asyncio
   async def test_recalc_common_empty_names_returns_three_tuple(db):
       result = await _recalc_plans_common(db, '', 'P1', action_type='recalc_stockout')
       assert len(result) == 3, '早退路径必须返回 3 元组'

   @pytest.mark.asyncio
   async def test_recalc_common_no_matching_plans(db):
       # 客户/产品无匹配计划 → 命 L178
       result = await _recalc_plans_common(db, '不存在的客户', '不存在的产品',
                                           action_type='recalc_stockout')
       assert len(result) == 3

   @pytest.mark.asyncio
   async def test_stockout_create_without_plan_rows(db):
       """回归 L285 主路径：无采购计划行时出货创建不得抛 ValueError"""
       await recalc_plans_after_stockout_create(db, '无计划客户', '无计划产品')
   ```
2. **端到端验证**（真实库 + 事务回滚，沿用项目既有只读式 e2e 套路）：
   建一个客户/产品 → 建出货记录（触发 recalc）→ 断言**不抛异常** → `db.rollback()` → 复查无残留。
3. **静默路径回归（对应 9/10 实证场景）**——确认修复后事件处理器不再打 ERROR：
   ```python
   @pytest.mark.asyncio
   async def test_stockout_event_handler_no_silent_failure(db, caplog):
       """对齐 2026-09-10 的实证场景：客户+产品无采购计划行时，
       出货创建事件处理器不得再抛 ValueError（此前被 except Exception 吞成 ERROR 日志）"""
       with caplog.at_level(logging.ERROR):
           # 直接构造事件 payload 并触发处理器（或调 recalc_plans_after_stockout_create）
           await recalc_plans_after_stockout_create(db, 'SIMTEST-CUST', 'SIMTEST-PROD')
       assert 'not enough values to unpack' not in caplog.text
   ```
4. **出货落库契约不变**——修复只影响重算，不得改变出货本身的行为：
   ```bash
   python -m pytest fastapi_app/tests/test_shipment_limit.py -q
   python -m pytest fastapi_app/tests/test_purchase_plan.py -q
   ```
5. **数据一致性手工校验**（建议在生产做一次抽检）——
   取 9/10 之后的一笔真实出货，核对：
   ```sql
   -- 采购计划明细的已出货量，应与出货记录汇总一致
   SELECT d.id, d.product_name, d.quantity, d.shipped_qty,
          (SELECT COALESCE(SUM(s.quantity),0) FROM stock_out s
             WHERE s.customer_name = p.customer_name AND s.product_name = d.product_name) AS actual_shipped
     FROM purchase_plan_detail d JOIN purchase_plan p ON p.id = d.plan_id
    WHERE d.product_name = '<抽查产品>';
   ```
   `shipped_qty` 与 `actual_shipped` 不一致即为已被本缺陷污染的存量数据（需单独评估是否修数）。
6. 日志中 `not enough values to unpack` 归零。

## 发布动作

后端源码改动 → **必须重启 `erp-prod`**。

## 回归风险

低。改动只是补齐返回元数，不改变正常路径行为。
需注意 `affected_plan_months` 早退时返回 `set()`（而非 `None`），
调用方是 `if affected_plan_months:` 判断 → 空集合为假，行为与原先"返回不到该分支"一致。

## 同类隐患

建议顺手全仓扫一遍返回值元数不一致的模式：

```bash
grep -n "return {}, \|return \[\], \|return None, " fastapi_app/services/*.py
```
本工单暴露的是一类问题：**新增返回值时只改了主路径**。修复后建议在 CI 加 `mypy` 或 `pyright` 的返回值检查（注解已声明为 3 元组后，静态检查能自动拦住这类漏改）。
