# 报表流水五 tab 改造（母行-明细 / 单号可见 / 单 SKU 语义）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `/report` 五个流水 tab 都显示单号、时间到分、按时间倒序，并把订单流水改成「母行=订单 / 子行=SKU」、行内编辑/删除直连到单 SKU。

**Architecture:** 后端新增 `order_item` 级编辑/删除两个端点（补齐单 SKU 语义），并把报表查询从「跨记录分组聚合」改为「一行一记录 / 订单分页带 items」；前端 `ReportTable` 从平铺表格改为按 `order_id` 分组的母行-明细渲染，子行与母行共用同一 `<colgroup>` 保证列对齐。导出侧（第二份实现）同步。

**Tech Stack:** FastAPI + SQLAlchemy(async) + PostgreSQL；Vue 3 + TS + PrimeVue（`UiDataTable` 已透传 `rowGroupMode`）；pytest；vitest。

**Spec:** `docs/superpowers/specs/2026-10-13-report-flow-master-detail-design.md`

## Global Constraints

- 后端 UI 文案/日志用中文；代码注释沿用仓库风格（说明「为什么」，不写「做了什么」）。
- `scripts/quality_gate.py`：`max_function_length=80`、`max_vue_component_length=400`、`max_file_size=1600`（只拦新增违规）。
- 前端 Node >= 22；单 `.vue` ≤ 400 行。
- pytest 必须**提权**跑（`logs/_run_pytest_elevated.ps1`），否则 `.env` ACL 导致整批假红；全量须独占单实例。
- 本次**无迁移**、无数据模型变更；不新增权限码。
- 改后端查询后必须同改导出侧（`report_data_service.py` + `report_exporter.py`）。
- 提交只 `git add` 本任务文件；提交信息写「为什么」。

## Review Focus

- **多 SKU 订单改一个 SKU 后，`order.quantity` 是否等于 Σ items.quantity** —— 它是兼容值，列表页/贝莱页读的是 `first_item.quantity`，不同步会让页面停在旧数量。
- **删掉订单最后一个 SKU** —— 必须等价于删整单（含备份/级联），不能留下 0 项孤儿订单。
- **已抵扣的 SKU 被删** —— 必须拒绝并给明确错误，否则库存对不上。
- **订单 tab 分页口径** —— `total_count` 必须是订单数而非 item 行数，否则分页器与页数错配。
- **子行与母行列对齐** —— 子行必须与母行同 `<colgroup>`，不能内嵌小表或加左缩进。

---

## 评审修订记录（2026-10-13，最强模型对抗性评审 + 主会话逐条核实）

| 发现 | 处置 |
|---|---|
| **High-1** Task 3 CTE 缺 `total_count`，`_query_logs_generic:80` 会 AttributeError | 已改：data_sql 用**标量子查询**给订单数；qty_sql 保持数量合计语义 |
| **High-2** 删末项复用 `delete_order`，非超管走审批，硬编码「已删除」是假话 | 已改：**透传 `delete_order` 返回值**（含 `requires_approval`） |
| **High-3** item 编辑绕过 `_check_order_lock` 与审批 | 已改：补 `_check_order_lock`；**owner 裁决：item 级直改不走审批**（spec §8 补记例外） |
| **High-4** 改数量未重算 `order.status`、未失效缓存 | 已改：补 `compute_order_status_from_db` + 与 `_update_order_directly` 一致的缓存失效序列 + 工厂通知 |
| **High-5** 声称「必须弃用 UiDataTable」 | **部分修正**：核实后**不必弃用**——扁平数组 + 插槽即可；Task 8 已改为该方案 + `UiDataTable` 补 `rowClass` |
| **High-6** 漏重导 `openapi.json` + `gen:api` + `check:types` | 已改：Task 10 补步骤 |
| **Med-2** 去 `STRING_AGG` 会打红既有后端测试 | Task 4 Files 已补测试文件 |
| **Med-3** 删 `parseGroupNos`/`matchRecordsByNos` 打红 `recordRows.test.ts` | Task 9 Files 已补；明确 `reportFlowActions.test.ts` 是**重写** |
| **Med-4** 导出侧本就一行一记录，spec「去分组」错误 | 已改：Task 5 收窄为「只改 exporter 表头」 |
| **Med-6** 抵扣按 `product_id` 匹配，同单同产品多 item 会**过严拒删** | 接受过严（不漏），错误文案写「该产品在本订单已被抵扣」 |
| **Med-7** Task 2 error_map 不完整 | 已改：对齐整单删除的完整 error_map |
| **Med-8** `get_order_logs` 超 80 行 | 已改：SQL 抽模块级常量 |

**核验通过**：`order.quantity = Σ items.quantity` 口径正确（`order_batch_create.py:199`）；锁序 Product→Order 保持（item 锁不参与既有锁环）；端点骨架与 `edit_order` 一致。

### 第二轮复审（修订稿）——上一轮 6 High 全部确认修复，另修新发现

| 发现 | 处置 |
|---|---|
| **B-1/High** Task 3 漏 `row_mapper` 改写（新 SQL 列名全变），照计划执行必 500 | 已改：新增 Step 4 完整 `row_mapper` |
| **B-2/High** Task 2 删末项锁序 Order→Product（`_delete_order_directly:561` 先锁单后锁产品），与出库路径 P→O 互等死锁 | 已改：Task 2 先 `get_product_for_update` 预锁产品再锁订单 |
| **B-3/Med** `db.delete`+flush 后仍读 `item.product_id/quantity` | 已改：先取值再删 |
| **B-4/Med** 无明细历史订单 `item_id` 为 NULL 撞 `int` schema | 已改：`row.item_id or 0` |
| **B-5/Med** `total_count` 相关子查询逐行重复扫描 | 已改：CTE 内 `COUNT(*) OVER()` 算一次 |
| **B-6/Med** 5 个 `seeded_*` 夹具不存在、Step 2「预期红」原因不对 | 已改：Task 1 Step 1 定义夹具 + 说明超管/非超管分支 |
| **B-7/Med** Task 4 只说「去 GROUP BY」，`row_mapper`/`total_count` 未交代 | 已改：给 `get_stockin_logs` 完整范本 |
| **B-8/Med** Task 8 用中文 `label` 判断 tab，改文案即静默错 | 已改：改用 `activeTab === 'order'`（新增 prop） |
| **B-9/Low** 无锁读后 `scalar_one()` 竞态 500 | 已改：`scalar_one_or_none()` + raise |
| **B-10/Low** Task 2 非末项分支缺工厂通知与 ORDER_UPDATED | 已改：补齐，与 Task 1 对称 |
| **B-11/Low** `item_id=0` 前端仍调 `deleteItem(0)` | 已改：Task 9 对 `item_id=0` 不渲染按钮 |

---

### Task 1: 后端 — 编辑单个 SKU 端点 `PUT /orders/items/{item_id}`

**Files:**
- Modify: `fastapi_app/api/v1/endpoints/order.py`（在 `edit_order` 之后新增）
- Modify: `fastapi_app/schemas/order.py`（新增 `OrderItemUpdate`）
- Modify: `fastapi_app/services/order/commands.py`（新增 `update_order_item`）
- Test: `tests/test_order_item_endpoints.py`（新建）

**Interfaces:**
- Produces: `update_order_item(db, item_id, quantity, note, current_user) -> dict`；HTTP `PUT /api/v1/orders/items/{item_id}` → `OrderActionResponse`。
- Consumes: 既有 `get_product_for_update`、`_check_order_lock`、`InventoryLog`、`db_transaction`。

- [ ] **Step 1: 写失败测试**（先红；**评审 B-6：夹具须在本文件内定义**）

> `tests/conftest.py` 只有 `async_client`/`auth_headers`，**没有** `seeded_*` 夹具——按 `tests/test_report.py` 既有风格（`db` fixture）在本文件内自建。`auth_headers` 是**超管**（决定删末项断言：超管直接删、订单消失；非超管走审批、订单仍在——两分支都要有对应用例或注释说明）。

```python
# tests/test_order_item_endpoints.py
import pytest
from fastapi_app.shared_models.order import Order
from fastapi_app.shared_models.order_item import OrderItem

@pytest.fixture
def seeded_multi_sku_order(db):                       # db 夹具沿用 tests/ 既有风格
    """1 张订单、2 个 SKU（qty 100 / 200）。返回 (order_id, [item1_id, item2_id])。"""
    order = Order(order_no='SO-T1', customer='C', quantity=300, status='待备货')
    db.add(order); db.flush()
    it1 = OrderItem(order_id=order.id, product_id=1, quantity=100, product_name='A', product_barcode='BA')
    it2 = OrderItem(order_id=order.id, product_id=2, quantity=200, product_name='B', product_barcode='BB')
    db.add_all([it1, it2]); db.flush(); db.commit()
    return order.id, [it1.id, it2.id]

@pytest.mark.asyncio
async def test_update_item_recomputes_order_quantity(async_client, seeded_multi_sku_order, auth_headers):
    """改一个 SKU 的数量后，order.quantity 必须 = Σ items.quantity。"""
    order_id, item_ids = seeded_multi_sku_order       # 2 个 SKU：qty 100 / 200
    resp = await async_client.put(
        f'/api/v1/orders/items/{item_ids[0]}', json={'quantity': 150}, headers=auth_headers,
    )
    assert resp.status_code == 200
    detail = await async_client.get(f'/api/v1/orders/{order_id}', headers=auth_headers)
    assert detail.json()['quantity'] == 350           # 150+200，手算字面量
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_order_item_endpoints.py::test_update_item_recomputes_order_quantity -v`
Expected: FAIL（404 / 405，路由不存在）

- [ ] **Step 3: 加 schema**

```python
# fastapi_app/schemas/order.py
class OrderItemUpdate(BaseModel):
    quantity: int | None = Field(None, gt=0, le=9999999, description="该 SKU 数量")
    note: str | None = Field(None, max_length=500, description="该 SKU 备注")
```

- [ ] **Step 4: 加 service 函数（**评审 High-3/4 修正：必须过锁 + 重算状态 + 失效缓存**）**

> **owner 裁决**：item 级编辑**直改、不走审批**（仅权限码门控）——但**仍须** `_check_order_lock`（被他人锁定/审批中的订单不可改）、重算 `order.status`、失效缓存。spec §8 需补记该例外及理由。

```python
# fastapi_app/services/order/commands.py（本模块已 import Order/OrderItem/StockOut/InventoryLog/
#   get_product_for_update/validate_quantity_range/func/select/compute_order_status_from_db/
#   dispatch_factory_notifications/cache_mgr/CacheDomain/InvalidationStrategy/
#   schedule_post_commit_invalidation/_invalidate_order_domains/_safe_invalidate_purchase_cache/
#   schedule_post_commit_event/StockEvent —— 复用既有 import，勿新增）
async def update_order_item(db, item_id: int, quantity: int | None,
                            note: str | None, current_user) -> dict:
    # 无锁读 item 取 order_id/product_id（后续按 Product→Order→Item 顺序加锁）
    head = (await db.execute(
        select(OrderItem.order_id, OrderItem.product_id).where(OrderItem.id == item_id)
    )).one_or_none()
    if head is None:
        raise ValueError('订单明细不存在')
    # 预锁产品（锁序 Product→Order，与 update_order 一致，避免与出库路径死锁）
    if head.product_id is not None:
        await get_product_for_update(db, head.product_id)
    order = (await db.execute(
        select(Order).where(Order.id == head.order_id).with_for_update()
    )).scalar_one_or_none()
    if not order or order.is_deleted:
        raise ValueError('订单不存在')
    await _check_order_lock(db, order.id, order, current_user, '编辑')
    item = (await db.execute(
        select(OrderItem).where(OrderItem.id == item_id).with_for_update()
    )).scalar_one_or_none()   # 评审 B-9：无锁读到加锁之间可能被并发删除，不能 scalar_one
    if item is None:
        raise ValueError('订单明细不存在')
    old_qty = item.quantity
    if quantity is not None:
        validate_quantity_range(quantity, '订单数量')
        item.quantity = quantity
    if note is not None:
        item.note = note
    # 重算订单兼容值：order.quantity = Σ items.quantity
    total = (await db.execute(
        select(func.coalesce(func.sum(OrderItem.quantity), 0))
        .where(OrderItem.order_id == order.id)
    )).scalar_one()
    order.quantity = int(total)
    if quantity is not None and quantity != old_qty:
        db.add(InventoryLog(
            product_id=item.product_id, change_type='订单修改',
            change_quantity=quantity - old_qty,
            related_id=order.order_no, note=f'订单明细修改：{order.order_no}',
        ))
    await db.flush()
    # 状态是 (抵扣量,出货量,数量) 派生值，数量变了必须重算（否则停在旧状态）
    order.status = await compute_order_status_from_db(db, order)
    try:
        await dispatch_factory_notifications(db, order, 'order_updated', None)
    except Exception as e:  # broad-except: 通知失败不影响改单
        logger.warning('工厂通知派发失败 order_no=%s: %s', order.order_no, e, exc_info=True)
    # 缓存失效序列与 _update_order_directly 一致（ORDER_AND_INVENTORY | REPORT 域 + 采购缓存）
    await cache_mgr.invalidate(
        InvalidationStrategy.DOMAIN,
        CacheDomain.ORDER_AND_INVENTORY | CacheDomain.REPORT,
    )
    schedule_post_commit_invalidation(db, _invalidate_order_domains)
    await _safe_invalidate_purchase_cache()
    schedule_post_commit_event(db, StockEvent.ORDER_UPDATED,
                               {'order_id': order.id, 'order_no': order.order_no})
    return {'success': True, 'message': '明细修改成功'}
```

- [ ] **Step 5: 加端点（带 error_map）**

```python
# fastapi_app/api/v1/endpoints/order.py
@router.put('/items/{item_id}', response_model=OrderActionResponse)
async def edit_order_item(
    item_id: int,
    data: OrderItemUpdate,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(require_any_permission('order_manage', 'order_edit')),
) -> OrderActionResponse:
    """编辑单个 SKU（数量/备注）；改后重算订单兼容数量与状态。直改、不走审批。"""
    async with db_transaction(db, error_map={
        ValueError: lambda e: HTTPException(status_code=400, detail=str(e)),
    }):
        result = await order_service.update_order_item(
            db, item_id, data.quantity, data.note, user)
    await cache_mgr.invalidate_dashboard()
    return OrderActionResponse(success=result['success'], message=result['message'])
```

- [ ] **Step 6: 跑测试确认通过**

Run: `python -m pytest tests/test_order_item_endpoints.py::test_update_item_recomputes_order_quantity -v`
Expected: PASS

- [ ] **Step 7: 变异检查（证明测试是真的）**

把 `order.quantity = int(total)` 临时改成 `order.quantity = int(total) + 1`，重跑 Step 6 → **必须红**；改回。

- [ ] **Step 8: 提交**

```bash
git add fastapi_app/api/v1/endpoints/order.py fastapi_app/schemas/order.py fastapi_app/services/order/commands.py tests/test_order_item_endpoints.py
git commit -m "feat(order): 新增单 SKU 编辑端点，改后重算订单兼容数量"
```

---

### Task 2: 后端 — 删除单个 SKU 端点 `DELETE /orders/items/{item_id}`

**Files:**
- Modify: `fastapi_app/api/v1/endpoints/order.py`
- Modify: `fastapi_app/services/order/commands.py`
- Test: `tests/test_order_item_endpoints.py`

**Interfaces:**
- Produces: `delete_order_item(db, item_id, current_user) -> dict`；HTTP `DELETE /api/v1/orders/items/{item_id}` → `OrderActionResponse`。
- Consumes: `order_service.delete_order`（删末 item 时复用整单删除的备份/级联）。

- [ ] **Step 1: 写失败测试**（三条：删非末 item、删末 item、有抵扣拒删）

```python
@pytest.mark.asyncio
async def test_delete_non_last_item_keeps_order(async_client, seeded_multi_sku_order):
    order_id, item_ids = seeded_multi_sku_order
    r = await async_client.delete(f'/api/v1/orders/items/{item_ids[0]}', headers=auth_headers)
    assert r.status_code == 200
    detail = await async_client.get(f'/api/v1/orders/{order_id}', headers=auth_headers)
    assert detail.status_code == 200                 # 订单还在
    assert detail.json()['quantity'] == 200          # 只剩另一 item 的 200

@pytest.mark.asyncio
async def test_delete_last_item_removes_order(async_client, seeded_single_item_order):
    order_id, item_id = seeded_single_item_order
    r = await async_client.delete(f'/api/v1/orders/items/{item_id}', headers=auth_headers)
    assert r.status_code == 200
    detail = await async_client.get(f'/api/v1/orders/{order_id}', headers=auth_headers)
    assert detail.status_code == 404                 # 订单消失

@pytest.mark.asyncio
async def test_delete_item_with_deduction_is_rejected(async_client, seeded_deducted_item):
    item_id = seeded_deducted_item
    r = await async_client.delete(f'/api/v1/orders/items/{item_id}', headers=auth_headers)
    assert r.status_code == 400                      # 明确拒绝
    assert '抵扣' in r.json()['detail']
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_order_item_endpoints.py -k delete -v`
Expected: FAIL（404 路由不存在）

- [ ] **Step 3: 加 service 函数（**评审 High-2 修正：删末项复用 `delete_order` 并透传真实返回**）**

> **关键**：`delete_order`（`commands.py:363-378`）按 `is_super` 分支——非超管走 `_submit_delete_approval`，**订单不会立即删除**。所以删末项时**必须透传它的返回值**（含 `requires_approval` 与真实 message），不能硬编码「订单已删除」。
> **owner 裁决**：删**非末项**（item 级）直改、不走审批；删**末项 = 删整张订单**，属整单级操作，**沿用 `delete_order` 的既有审批/锁定/备份语义**（对非超管会变成提交审批，这是有意为之，见 spec 风险节）。

```python
# fastapi_app/services/order/commands.py
async def delete_order_item(db, item_id: int, current_user) -> dict:
    head = (await db.execute(
        select(OrderItem.order_id, OrderItem.product_id).where(OrderItem.id == item_id)
    )).one_or_none()
    if head is None:
        raise ValueError('订单明细不存在')
    # 预锁产品（锁序 Product→Order，与 update_order_item/update_order 一致）——
    # 评审 B-2：_delete_order_directly（commands.py:561）是在锁订单之后才锁产品，
    # 若不先预锁，新端点会以 Order→Product 参与并发，与出库创建（P→O）互等行锁死锁。
    if head.product_id is not None:
        await get_product_for_update(db, head.product_id)
    order = (await db.execute(
        select(Order).where(Order.id == head.order_id).with_for_update()
    )).scalar_one_or_none()
    if not order or order.is_deleted:
        raise ValueError('订单不存在')
    await _check_order_lock(db, order.id, order, current_user, '删除')
    # 已抵扣（该订单+该产品存在 stockin_id IS NOT NULL 的出货）时拒删
    deducted = (await db.execute(
        select(func.coalesce(func.sum(StockOut.quantity - StockOut.returned_quantity), 0))
        .where(StockOut.order_id == order.id,
               StockOut.product_id == head.product_id,
               StockOut.stockin_id.isnot(None))
    )).scalar_one()
    if int(deducted) > 0:
        raise ValueError('该产品在本订单已被备货抵扣，无法删除')
    siblings = (await db.execute(
        select(func.count()).select_from(OrderItem).where(OrderItem.order_id == order.id)
    )).scalar_one()
    if siblings <= 1:
        # 最后一个 SKU：等价删整张订单 —— 复用 delete_order（含审批/锁定/备份），透传其返回值
        return await delete_order(db, order.id, current_user)
    item = (await db.execute(
        select(OrderItem).where(OrderItem.id == item_id).with_for_update()
    )).scalar_one_or_none()   # 评审 B-9：无锁读到加锁之间可能被并发删除
    if item is None:
        raise ValueError('订单明细不存在')
    # 评审 B-3：先取值再删——delete+flush 后不再读对象属性
    pid, qty = item.product_id, item.quantity
    await db.delete(item)
    await db.flush()
    total = (await db.execute(
        select(func.coalesce(func.sum(OrderItem.quantity), 0))
        .where(OrderItem.order_id == order.id)
    )).scalar_one()
    order.quantity = int(total)
    db.add(InventoryLog(
        product_id=pid, change_type='订单修改',
        change_quantity=-qty,
        related_id=order.order_no, note=f'订单明细删除：{order.order_no}',
    ))
    await db.flush()
    order.status = await compute_order_status_from_db(db, order)
    # 评审 B-10：与 Task 1 对称，删除也发工厂通知与 ORDER_UPDATED 事件
    try:
        await dispatch_factory_notifications(db, order, 'order_updated', None)
    except Exception as e:  # broad-except: 通知失败不影响删单
        logger.warning('工厂通知派发失败 order_no=%s: %s', order.order_no, e, exc_info=True)
    await cache_mgr.invalidate(
        InvalidationStrategy.DOMAIN,
        CacheDomain.ORDER_AND_INVENTORY | CacheDomain.REPORT,
    )
    schedule_post_commit_invalidation(db, _invalidate_order_domains)
    await _safe_invalidate_purchase_cache()
    schedule_post_commit_event(db, StockEvent.ORDER_UPDATED,
                               {'order_id': order.id, 'order_no': order.order_no})
    return {'success': True, 'message': '明细删除成功', 'requires_approval': False}
```

- [ ] **Step 4: 加端点（**评审 Med-7 修正：error_map 对齐整单删除**）**

```python
# fastapi_app/api/v1/endpoints/order.py（error_map 与 :380 整单删除一致）
@router.delete('/items/{item_id}', response_model=OrderActionResponse)
async def delete_order_item(
    item_id: int,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(require_any_permission('order_manage', 'order_delete')),
) -> OrderActionResponse:
    """删除单个 SKU；删到空等价删整单（走整单删除的审批/备份）；已抵扣的拒删。"""
    async with db_transaction(db, error_map={
        IntegrityError: lambda e: HTTPException(status_code=409, detail='订单存在关联数据，无法删除'),
        PermissionDeniedError: lambda e: HTTPException(status_code=403, detail=settings.sanitize_business_error(e)),
        ValueError: lambda e: HTTPException(status_code=400, detail=str(e)),
        OSError: lambda e: HTTPException(status_code=500, detail='删除前备份失败，操作已回滚'),
        SQLAlchemyError: lambda e: HTTPException(status_code=500, detail='数据库操作失败，删除已回滚'),
    }):
        result = await order_service.delete_order_item(db, item_id, user)
    await cache_mgr.invalidate_dashboard()
    return OrderActionResponse(success=result['success'], message=result['message'])
```

- [ ] **Step 5: 跑测试确认通过**

Run: `python -m pytest tests/test_order_item_endpoints.py -k delete -v`
Expected: PASS（3 passed）

- [ ] **Step 6: 提交**

```bash
git add fastapi_app/api/v1/endpoints/order.py fastapi_app/services/order/commands.py tests/test_order_item_endpoints.py
git commit -m "feat(order): 新增单 SKU 删除端点，删末项等价删整单、已抵扣拒删"
```

---

### Task 3: 后端 — `get_order_logs` 改母行-明细结构（按订单分页 + items）

**Files:**
- Modify: `fastapi_app/services/report_service.py:101-177`
- Modify: `fastapi_app/schemas/report.py`（`ReportLogItem` 补字段）
- Test: `tests/test_report_order_logs_multi_sku.py`（既有，扩展）

**Interfaces:**
- Produces: `get_order_logs(...)` 返回的 `logs` 每项 = 一行「订单×SKU」，字段：`order_id, order_no, order_date(到分), customer, order_note, item_id, product_name, product_barcode, quantity, item_note, item_count, order_total_qty`；`pagination.total` = 订单数。
- Consumes: 无（纯查询）。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_report_order_logs_multi_sku.py（追加）
async def test_order_logs_paginate_by_order_and_expose_items(async_client, seeded_orders_same_day):
    # 造 2 张订单（一张 2 SKU、一张 1 SKU），同一天
    r = await async_client.get('/api/v1/reports/order-logs?page=1&per_page=15',
                               headers=auth_headers)
    logs = r.json()['logs']
    # 总行数 = 3（2+1 个 SKU 行），但订单数是 2
    assert r.json()['pagination']['total'] == 2
    assert len(logs) == 3
    assert all('order_id' in x and 'item_id' in x for x in logs)
    assert ':' in logs[0]['order_date']            # 时间到分
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_report_order_logs_multi_sku.py::test_order_logs_paginate_by_order_and_expose_items -v`
Expected: FAIL（无 `order_id` 字段 / total 是行数）

- [ ] **Step 3: 重写 `get_order_logs` 的 SQL**

**关键约束（评审 High-1）**：`_query_logs_generic`（`report_service.py:80`）用 `results[0].total_count` 取总数——它必须来自 **data_sql 的某一列**，不是 qty_sql。且 qty_sql 的返回值进 `stats.total_quantity`（**数量合计**语义，不能挪用成订单数）。所以：**data_sql 要自带 `total_count` 列（= 订单数）**，qty_sql 保持「Σ item 数量」。

```python
data_sql_template=f"""WITH page_orders AS (
    SELECT o.id, COUNT(*) OVER () AS total_count
    FROM {order_tbl} o
    LEFT JOIN order_item oi ON oi.order_id = o.id
    LEFT JOIN product p ON p.id = COALESCE(oi.product_id, o.product_id)
    WHERE 1=1 {{where_sql}}
    GROUP BY o.id
    ORDER BY MAX(o.order_date) DESC, o.id DESC
    LIMIT :limit OFFSET :offset
)
SELECT o.id AS order_id, o.order_no,
       to_char(o.order_date, 'YYYY-MM-DD HH24:MI') AS order_date,
       o.customer, o.note AS order_note,
       oi.id AS item_id, {item_name} AS product_name, {item_barcode} AS product_barcode,
       {item_qty} AS quantity, oi.note AS item_note,
       COUNT(*) OVER (PARTITION BY o.id) AS item_count,
       SUM({item_qty}) OVER (PARTITION BY o.id) AS order_total_qty,
       po.total_count
FROM page_orders po
JOIN {order_tbl} o ON o.id = po.id
LEFT JOIN order_item oi ON oi.order_id = o.id
LEFT JOIN product p ON p.id = COALESCE(oi.product_id, o.product_id)
ORDER BY o.order_date DESC, o.id DESC, oi.id"""
```

说明：
- **`total_count` 在 CTE 里用 `COUNT(*) OVER ()`**（评审 B-5 修正）：CTE 已 `GROUP BY o.id`，故每行=一张订单；窗口函数在 `LIMIT` **之前**求值，所以得到的是**全量匹配订单数**——且只算一次，不像相关子查询那样逐行重复扫描。
- qty_sql 保持原样（`SELECT COALESCE(SUM({item_qty}),0) ...`），语义是「数量合计」，不是订单数。
- `order_total_qty` 由 SQL 直接给（`SUM(...) OVER (PARTITION BY o.id)`），前端不再自行求和。
- **函数长度**：`get_order_logs` 现 77 行（`report_service.py:101-177`），贴着 `max_function_length=80`。SQL 模板抽成模块级常量（如 `_ORDER_LOGS_DATA_SQL` / `_ORDER_LOGS_QTY_SQL`）后再引用（评审 Med-8）。

- [ ] **Step 4: 重写 `row_mapper`（评审 B-1：不改必 500）**

现 `row_mapper`（`report_service.py:169-176`）读 `row.order_date_only.strftime(...)`/`row.total_quantity`/`row.order_nos`/`row.notes`/`row.order_count`/`row.status`——**新 SQL 一个都不产出**，不改就是 AttributeError。替换为：

```python
row_mapper=lambda row: {
    'order_id': row.order_id,
    'item_id': row.item_id or 0,            # 评审 B-4：无明细历史订单 LEFT JOIN 出 NULL，schema 是 int
    'order_no': row.order_no or '',
    'order_date': row.order_date or '-',    # 已是 to_char 文本
    'customer': row.customer or '',
    'product_name': row.product_name or '',
    'product_barcode': row.product_barcode or '',
    'quantity': row.quantity or 0,
    'item_note': row.item_note or '',
    'order_note': row.order_note or '',
    'note': row.item_note or row.order_note or '',
    'item_count': row.item_count or 1,
    'order_total_qty': int(row.order_total_qty or 0),
},
```

> `item_count`/`order_total_qty` 对**无明细的历史订单**：`oi` 为 NULL 时 `COUNT(*) OVER(PARTITION BY o.id)` 仍算 1、`SUM(COALESCE(oi.quantity,o.quantity))` 取回退值，语义可接受。

- [ ] **Step 5: `ReportLogItem` 补字段**

```python
# fastapi_app/schemas/report.py
class ReportLogItem(BaseModel):
    # ...既有字段保留...
    record_id: int = 0
    record_no: str = ''
    order_id: int = 0
    item_id: int = 0
    item_count: int = 0
    order_total_qty: int = 0
    item_note: str = ''
```

- [ ] **Step 6: 跑测试确认通过**

Run: `python -m pytest tests/test_report_order_logs_multi_sku.py -v`
Expected: PASS

- [ ] **Step 7: 提交**

```bash
git add fastapi_app/services/report_service.py fastapi_app/schemas/report.py tests/test_report_order_logs_multi_sku.py
git commit -m "feat(report): 订单流水改为按订单分页、一行一SKU、带订单号与时间到分"
```

---

### Task 4: 后端 — 其余四 tab 去分组、补单号/条码/时间

**Files:**
- Modify: `fastapi_app/services/report_service.py`（`get_stockin_logs` / `get_stockout_logs` / `get_deduction_logs` / `get_return_logs`）
- Test: `tests/test_report.py`（扩展）
- Test: `tests/test_report_order_logs_multi_sku.py`（既有，断言 `order_nos`，去分组后需同步）、`fastapi_app/tests/test_report.py`（既有，断言 `stockout_nos`，同步）—— 评审 Med-2

**Interfaces:**
- Produces: 四 tab 的 `logs` 每项 = 一条记录，字段：`record_id, record_no, <date_key>(到分), customer, product_name, product_barcode, quantity, note`。
- Consumes: 无。

- [ ] **Step 1: 写失败测试**

```python
async def test_stockin_logs_one_row_per_record(async_client, seeded_two_stockins_same_key):
    # 两条同日同客户同产品的备货记录，现状会被合并成 1 行；改后应为 2 行
    r = await async_client.get('/api/v1/reports/stockin-logs', headers=auth_headers)
    logs = r.json()['logs']
    assert len(logs) == 2
    assert {x['record_no'] for x in logs} == {'SI-1', 'SI-2'}
    assert ':' in logs[0]['stockin_date']
```

- [ ] **Step 2: 跑测试确认失败** → Expected: FAIL（1 行、无 record_no）

- [ ] **Step 3: 四个函数去掉 `GROUP BY`，改为逐行 SELECT（评审 B-7：给完整范本）**

**每个函数都要同时改三处**：① data_sql 去 `GROUP BY`/`STRING_AGG`、时间改 `to_char(..., 'YYYY-MM-DD HH24:MI')`、**补 `COUNT(*) OVER() AS total_count`**（`_query_logs_generic:80` 要求 data_sql 有该列，去分组后改用它）；② row_mapper 改读新列名（现读的是 `row.stockin_date_only.strftime(...)`/`row.notes` 等，全不再产出）；③ 排序改 `ORDER BY <date> DESC, <id> DESC`。

以 `get_stockin_logs` 为范本（其余三个同型替换，**注意别名差异**：`stockout` 用 `so`+`o2`、`deduction` 用 `so`+`o`、`return` 用 `sr`）：

```python
data_sql_template=f"""SELECT
    s.id AS record_id, s.stockin_no AS record_no,
    to_char(s.stockin_date, 'YYYY-MM-DD HH24:MI') AS stockin_date,
    s.customer, p.name AS product_name, p.barcode AS product_barcode,
    s.quantity, s.note,
    COUNT(*) OVER() AS total_count
    FROM stock_in s JOIN product p ON s.product_id = p.id
    WHERE 1=1 {{where_sql}}
    ORDER BY s.stockin_date DESC, s.id DESC
    LIMIT :limit OFFSET :offset""",
qty_sql_template="SELECT COALESCE(SUM(s.quantity), 0) FROM stock_in s JOIN product p ON s.product_id = p.id WHERE 1=1 {where_sql}",
row_mapper=lambda row: {
    'record_id': row.record_id, 'record_no': row.record_no or '',
    'stockin_date': row.stockin_date or '-', 'customer': row.customer or '',
    'product_name': row.product_name or '', 'product_barcode': row.product_barcode or '',
    'quantity': row.quantity or 0, 'note': row.note or '',
},
```

`_string_agg` 的四个 tab 调用删除后，`_string_agg` 若仅剩订单 tab 用（订单 tab 也去掉了）则一并删（确认无引用后）；`_ALLOWED_EXPRS` 里对应项同步清理。

- [ ] **Step 4: 跑测试确认通过** → Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add fastapi_app/services/report_service.py tests/test_report.py
git commit -m "feat(report): 备货/出货/抵扣/退货流水改为一行一记录并补单号"
```

---

### Task 5: 后端 — 导出侧表头补单号/条码

**Files:**
- Modify: `utils/report_exporter.py`（五个 `export_*_logs` 的 `headers` + 五个 `_format_*_row`）
- Test: `tests/test_report_exporter.py`（扩展）

> **评审 Med-4 修正**：导出侧（`fastapi_app/shared/report_data_service.py`）四个非订单 tab **本来就是一行一记录**（`select(StockIn)` 逐行迭代，无 `GROUP BY`/`STRING_AGG`），时间**本就是 `%Y-%m-%d %H:%M`**，单号也已在行里（`stockin_no`/`stockout_no`/`return_no`/`order_no`）。**所以 `report_data_service.py` 不需要改**——原计划「去分组、补单号」是无的放矢。订单侧 `_order_log_row` 已带 `order_no`，时间已是 `%H:%M`。**本任务只需改导出表头/行格式，把已存在的字段渲染出来。**

**Interfaces:**
- Produces: 导出表头 = `下单时间/备货时间/… · 订单号/备货单号/出货单号/退货单号 · 客户 · 产品名称 · 条码 · 数量 · 备注`。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_report_exporter.py（追加）
from io import BytesIO
from openpyxl import load_workbook

def test_order_export_headers_include_order_no_and_barcode():
    exporter = ReportExporter()
    data = exporter.export_order_logs(
        [{'order_date': '2026-10-13 09:12', 'order_no': 'SO-1', 'customer': 'C',
          'product_name': 'P', 'product_barcode': 'B', 'quantity': 1, 'note': ''}],
        {'total_count': 1})
    headers = [c.value for c in load_workbook(BytesIO(data)).active[1]]
    assert '订单号' in headers and '条码' in headers

def test_stockin_export_headers_include_record_no():
    exporter = ReportExporter()
    data = exporter.export_stockin_logs(
        [{'stockin_date': '2026-10-13 09:12', 'stockin_no': 'SI-1', 'customer': 'C',
          'product_name': 'P', 'product_barcode': 'B', 'quantity': 1, 'note': ''}],
        {'total_count': 1})
    headers = [c.value for c in load_workbook(BytesIO(data)).active[1]]
    assert '备货单号' in headers and '条码' in headers
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_report_exporter.py -k headers -v`
Expected: FAIL（表头无「订单号」）

- [ ] **Step 3: 改 `utils/report_exporter.py`**

五处 `headers`（`report_exporter.py:52/82/111/140/169`）在「下单时间/…」后插入单号列、在「产品名称」后插入「条码」；五个 `_format_*_row`（`:290-338`）同步取 `log.get('order_no'|'stockin_no'|'stockout_no'|'return_no')` 与 `log.get('product_barcode','')`，并调 `ws.column_dimensions` 列宽。

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_report_exporter.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add utils/report_exporter.py tests/test_report_exporter.py
git commit -m "feat(report): 导出表头补单号/条码列"
```

---

### Task 6: 前端 — API 层（新增单 SKU 接口 + 报表类型）

**Files:**
- Modify: `frontend-vite/src/api/order.ts`
- Modify: `frontend-vite/src/api/report.ts`
- Test: `frontend-vite/src/test/reportFlowActions.test.ts`（既有，扩展）

**Interfaces:**
- Produces: `orderApi.updateItem(id, {quantity?, note?})`、`orderApi.deleteItem(id)`；`ReportLogItem` TS 类型（含 `order_id/item_id/record_no/...`）。
- Consumes: Task 1/2 的端点路径。

- [ ] **Step 1: 写失败测试**

```ts
// reportFlowActions.test.ts
it('updateItem 调 PUT /orders/items/:id', async () => {
  await orderApi.updateItem(7, { quantity: 150 })
  expect(fetchMock).toHaveBeenCalledWith('/api/v1/orders/items/7', expect.objectContaining({ method: 'PUT' }))
})
```

- [ ] **Step 2: 跑测试确认失败** → `npx vitest run -t "updateItem"` Expected: FAIL

- [ ] **Step 3: 实现**

```ts
// frontend-vite/src/api/order.ts
updateItem: (id: number, data: { quantity?: number; note?: string }) =>
  put<OrderItem>(`/orders/items/${id}`, data),
deleteItem: (id: number) => del(`/orders/items/${id}`),
```

```ts
// frontend-vite/src/api/report.ts
export interface ReportLogItem {
  order_id: number; item_id: number; record_id: number; record_no: string
  order_no: string; order_date: string; stockin_date: string
  stockout_date: string; deduction_time: string; return_date: string
  customer: string; product_name: string; product_barcode: string
  quantity: number; note: string; item_note: string
  item_count: number; order_total_qty: number
}
```

- [ ] **Step 4: 跑测试确认通过** → PASS

- [ ] **Step 5: 提交**

```bash
git add frontend-vite/src/api/order.ts frontend-vite/src/api/report.ts frontend-vite/src/test/reportFlowActions.test.ts
git commit -m "feat(report): 前端 API 补单 SKU 编辑/删除与报表新字段类型"
```

---

### Task 7: 前端 — 列定义（`useReportConfig.ts`）

**Files:**
- Modify: `frontend-vite/src/views/report/composables/useReportConfig.ts`
- Test: `frontend-vite/src/test/reportViewRedesign.test.ts`（既有，扩展）

**Interfaces:**
- Produces: `reportColumns` = `展开 · 下单时间 · 订单号 · 客户 · 产品名称 · 条码 · 数量 · 备注 · 操作`；`TabConfig` 增 `noLabel`（订单号/备货单号/出货单号/退货单号）。

- [ ] **Step 1: 写失败测试**

```ts
it('列定义含订单号与条码，且无状态列', () => {
  const { reportColumns } = useReportConfig(ref('order'), ref(true))
  const fields = reportColumns.value.map(c => c.field)
  expect(fields).toContain('order_no')
  expect(fields).toContain('product_barcode')
  expect(fields).not.toContain('status')
})
```

- [ ] **Step 2: 跑测试确认失败** → FAIL

- [ ] **Step 3: 改列定义**（九列，含 `expand` 占位列与 `noLabel` 表头）。

- [ ] **Step 4: 跑测试确认通过** → PASS

- [ ] **Step 5: 提交**

```bash
git add frontend-vite/src/views/report/composables/useReportConfig.ts frontend-vite/src/test/reportViewRedesign.test.ts
git commit -m "feat(report): 列定义补订单号/条码，末列改备注"
```

---

### Task 8: 前端 — `ReportTable` 母行-明细渲染（同 colgroup 对齐）

**Files:**
- Modify: `frontend-vite/src/views/report/components/ReportTable.vue`
- Test: `frontend-vite/src/test/reportViewRedesign.test.ts`（扩展）

**Interfaces:**
- Consumes: Task 6 的 `ReportLogItem`；Task 7 的列定义。
- Produces: 分组行渲染（`order` tab 按 `order_id` 分组；多 SKU 母行+子行，单 SKU 压一行；其余 tab 平铺）。

- [ ] **Step 1: 写失败测试**

```ts
it('多 SKU 订单渲染母行 + 子行，子行与母行同列', () => {
  const logs = [
    { order_id: 1, order_no: 'SO-1', customer: 'C', item_count: 2, order_total_qty: 350, order_note: '', order_date: '2026-10-13 09:12' },
    { order_id: 1, item_id: 11, product_name: 'A', product_barcode: 'B1', quantity: 150, item_note: '' },
    { order_id: 1, item_id: 12, product_name: 'B', product_barcode: 'B2', quantity: 200, item_note: '' },
  ]
  const wrapper = mount(ReportTable, { props: { logs, columns, currentCfg: TAB_CONFIG.order, /*...*/ } })
  expect(wrapper.findAll('tr.order-row')).toHaveLength(1)   // 母行 1
  expect(wrapper.findAll('tr.child-row')).toHaveLength(2)   // 子行 2
  // 子行的产品名称单元格与表头同列（无内嵌小表）
  expect(wrapper.findAll('tr.child-row td.pname').length).toBe(2)
})
```

- [ ] **Step 2: 跑测试确认失败** → FAIL

- [ ] **Step 3: 实现分组渲染（扁平化数组 + 插槽，**保留 `UiDataTable`**）**

**评审 High-5 修正**：不需要弃用 `UiDataTable`。母行-明细可以**喂一个扁平数组**给它——母行与子行都是普通行，共用同一 `<colgroup>`，用 `column-body-*` 插槽按行类型渲染（母行 `产品名称` 格显示「共 N 个 SKU」、`操作` 格留空；子行显示 SKU 名/条码/数量/备注/操作），展开/折叠 = 前端增删子行。这正是 v4 稿的形态。

```ts
// ReportTable.vue —— 按 tab 决定行数组（评审 B-8：用稳定 key，不用中文 label）
// 新增 prop：activeTab: TabType（ReportView 传入 ref(activeTab).value）
const rows = computed(() => {
  if (props.activeTab !== 'order') return props.logs               // 四 tab 平铺
  const out: Record<string, unknown>[] = []
  for (const g of groupByOrder(props.logs)) {                      // 按 order_id 聚
    if (g.items.length === 1) {
      out.push({ ...g.items[0], ...orderLevel(g), _kind: 'single' })  // 单 SKU 压一行
    } else {
      out.push({ ...orderLevel(g), _kind: 'parent' })                 // 母行
      if (expanded.value.has(g.order_id)) {
        out.push(...g.items.map(it => ({ ...it, _kind: 'child' })))   // 展开的子行
      }
    }
  }
  return out
})
```

- **`ReportTable` 新增 `activeTab: TabType` prop**（`ReportView` 传入），判断用 `activeTab === 'order'`——**不要用 `currentCfg.label`（中文显示名）**：改文案会静默把订单 tab 当平铺渲染（评审 B-8）。

- `UiDataTable` 需补一个 **`rowClass` 透传**（PrimeVue DataTable 原生支持 `rowClass`），让母行/子行/单行带 `order-row`/`child-row` 类名（样式见 v4 稿的底色 + 左侧竖线）。
- 展开态：`expanded = ref<Set<number>>()`，箭头按钮 toggle。母行的「展开」列渲染箭头，子行渲染 `└`。
- 分页/排序沿用 `UiDataTable` 现有 props，**不需要换 `UiPagination`**。
- **400 行预算**：`ReportTable.vue` 现 228 行，扁平化 + 分组逻辑可能逼近 `max_vue_component_length=400`；把 `groupByOrder`/`rows` 计算抽到 `composables/useReportRows.ts`（新文件），`ReportTable.vue` 只留渲染。

- [ ] **Step 4: 跑测试确认通过** → PASS

- [ ] **Step 5: 视觉核对**（`npm run dev` 或 build 后看 `/report`，与 v4 稿一致）。

- [ ] **Step 6: 提交**

```bash
git add frontend-vite/src/views/report/components/ReportTable.vue frontend-vite/src/components/ui/UiDataTable.vue frontend-vite/src/views/report/composables/useReportRows.ts frontend-vite/src/test/reportViewRedesign.test.ts
git commit -m "feat(report): 订单流水母行-明细渲染（扁平数组+插槽），子行与母行同列对齐"
```

---

### Task 9: 前端 — 行内操作直连单 SKU（去掉 picker 还原流程）

**Files:**
- Modify: `frontend-vite/src/views/report/composables/useReportRowActions.ts`
- Modify: `frontend-vite/src/views/report/ReportView.vue`（移除 picker 绑定，如无其他引用）
- Test: `frontend-vite/src/test/reportFlowActions.test.ts`（**重写**——现有 99-259 行用例全建立在「聚合行还原」流程上）
- Test: `frontend-vite/src/test/recordRows.test.ts`（**删除或迁移**——整文件测 `parseGroupNos`/`matchRecordsByNos`；评审 Med-3）

**Interfaces:**
- Consumes: Task 6 的 `orderApi.updateItem/deleteItem`。
- Produces: `onRowAction('order','edit'|'delete', row)` 直接用 `row.item_id` 调单 SKU 接口（不再 `resolveRecords` + picker）。

- [ ] **Step 1: 写失败测试**

```ts
it('订单 tab 行内删除直接调 deleteItem(item_id)', async () => {
  await actions.onRowAction('order', 'delete', { item_id: 12, product_name: 'B' })
  expect(orderApi.deleteItem).toHaveBeenCalledWith(12)
})
```

- [ ] **Step 2: 跑测试确认失败** → FAIL

- [ ] **Step 3: 实现**：订单 tab 走 `updateItem`/`deleteItem`；其余 tab 走各自单条接口（`stockApi.editStockout/deleteStockout`、`stockReturnApi.update/remove`、`stockApi.editStockin/deleteStockin`）。删除确认文案带上产品名/单号。
  - **评审 B-11**：订单行若 `item_id` 为 `0`（无明细的历史订单，见 B-4 兜底），**不渲染操作按钮**，避免调 `deleteItem(0)`。

- [ ] **Step 4: 跑测试确认通过** → PASS

- [ ] **Step 5: 删除死代码**：确认 `ReportRecordPicker.vue`、`parseGroupNos`、`matchRecordsByNos` 零引用后删除（`npm run lint` 会抓未用导出）。

- [ ] **Step 6: 提交**

```bash
git add frontend-vite/src/views/report/composables/useReportRowActions.ts frontend-vite/src/views/report/ReportView.vue frontend-vite/src/test/reportFlowActions.test.ts
git commit -m "feat(report): 行内编辑/删除直连单 SKU，移除聚合行还原与选择弹窗"
```

---

### Task 10: 门禁与全量验证

**Files:** 无（仅验证）

- [ ] **Step 1: 后端门禁**

Run: `python scripts/quality_gate.py && ruff check .`
Expected: exit 0

- [ ] **Step 2: 后端聚焦 + 全量测试（提权）**

Run: `powershell -File logs/_run_pytest_elevated.ps1 > /tmp/pytest.log 2>&1` 后 `tail`/`grep`
Expected: `0 failures`（全量须独占单实例）

- [ ] **Step 3: 重导 OpenAPI 快照与前端生成类型（评审 High-6，CI 必红项）**

新增了 `PUT/DELETE /orders/items/{id}`，必须同步两份生成物，否则 CI 的 `check_openapi_frontend_alignment.py` 报「快照已过期」：

```bash
python scripts/check_openapi_frontend_alignment.py --export frontend-vite/openapi.json
cd frontend-vite && npm run gen:api
```

Expected: `openapi.json` 与 `src/types/api.d.ts` 更新，无 diff 残留。

- [ ] **Step 4: 前端门禁**

```bash
cd frontend-vite
npm run type-check
npm test
npm run lint
npm run check:api
npm run check:types      # 计划原漏跑（评审 High-6）
npm run check:routes
npm run check:dto
```

Expected: 全绿

- [ ] **Step 5: 修复失败项后重跑**（不放行任何一项）。

- [ ] **Step 6: 提交（如有修复）**，随后按 `AGENTS.md §4` 进入「推送前一次评审」。

---

## Self-Review

- **Spec 覆盖**：§3 五 tab 粒度 → Task 3/4；§4 决策 → Task 7/8/9；§5 母行-明细 → Task 8；§6.1 新接口 → Task 1/2；§6.2 查询 → Task 3/4；§6.3 导出 → Task 5；§7 前端 → Task 6/7/8/9；§9 测试 → 各 Task 内 + Task 10。无缺口。
- **占位符扫描**：无 TBD/TODO；每个代码步给出实际片段。
- **类型一致性**：`ReportLogItem` 字段（`order_id/item_id/record_no/...`）在 Task 3 定义、Task 6 前端镜像、Task 8 消费，命名一致。
- **Review Focus**：5 条均落到 Task 1（quantity 重算）、Task 2（末项删单 / 抵扣拒删）、Task 3（分页口径）、Task 8（列对齐）的测试中。
