# 备货记录批次号 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `/batch` 页的备货(StockIn)记录和订单一样能填批次号、能完成，且与订单共用同一套批次号。

**Architecture:** 给 `stock_in` 表加与 `order` 对齐的三个批次列；`order_batch_service` 的序列化/保存/完成/筛选四条路径都补上备货分支；前端去掉「备货只读」的模板分支，所有 chip 统一渲染输入框+完成按钮，保存时带 `record_type` 区分落表。

**Tech Stack:** Python 3 / FastAPI / SQLAlchemy 2.0 async / Alembic；Vue 3 + TS + Vitest。

**Spec:** [docs/superpowers/specs/2026-10-13-stockin-batch-no-design.md](../specs/2026-10-13-stockin-batch-no-design.md)

## Global Constraints

- **迁移单一 head**；当前 head = `pg_standalone_095_sync_backup_schedule_task_type_comment`。新迁移 `down_revision` 必须指向它。
- **禁止对生产库 `alembic revision --autogenerate`**；迁移在**临时空库**生成/验证（`migrations/README`）。新增列全部 nullable。
- 迁移只做结构变更，**不夹带业务逻辑**；新增破坏性 DDL 会被 `test_migration_autogenerate_safety.py` 拦下。
- **后端 pytest 需提权**（conftest 读根 `.env` 需 Administrators ACL）：用 `logs/_run_pytest_elevated.ps1`（提权全量），或按 `AGENTS.md §4` 的非提权 stub-env 包装跑聚焦用例。**全量 pytest 必须独占单实例**。
- 前端门禁：`cd frontend-vite && npm run type-check`、`npx eslint src/...`、`npx vitest run -t "<名>"`（vitest 需把 `TEMP/TMP` 指进仓内目录，见 `AGENTS.md §4`）。
- **提交只含本任务文件**：本仓常有并发会话预暂存文件；每次 `git status --porcelain` 确认，必要时用 `git commit -- <本任务路径>` 只提交指定路径。
- 批次号长度上限 `String(100)`（对齐 Order）。

## Review Focus

以下输入/边界 spec 隐含但无专门测试，最可能咬人；每条都在对应任务里配了测试：

1. **订单与备货 id 撞号** → 编辑态/保存必须按 `record_type:id` 复合键定位，不得串扰（Task 6）。
2. **混合批次完成**：批次里订单未出货时进 `failed_orders`，但备货照常完成（Task 4）。
3. **清空批次号**（传 `null`）备货也要能落库为 NULL（Task 3）。
4. **备货批次字段为空**时序列化返回 `None`（不是 Mock 值/空串）（Task 2）。
5. **按批次号筛选**：原来备货分支**忽略** `batch_no`（按批次筛选会带出该客户全部备货）→ 筛选某批次时应只出该批次的订单+备货（Task 5）。

---

### Task 1: `stock_in` 批次字段（模型 + 迁移）

**Files:**
- Modify: `fastapi_app/shared_models/stock_in.py`
- Create: `migrations/versions/pg_standalone_096_stockin_batch_fields.py`
- Test: `fastapi_app/tests/test_migration_autogenerate_safety.py`（既有，须通过）

**Interfaces:**
- Produces: `StockIn.batch_no: str | None`、`StockIn.batch_completed_at: datetime | None`、`StockIn.batch_completed_by_id: int | None`、`StockIn.batch_completed_by: User | None`（供 Task 2/3/4 使用）。

- [ ] **Step 1: 改模型**

在 `fastapi_app/shared_models/stock_in.py` 的 `note` 之后、`confirmed_at` 之前插入三列，并在 `__table_args__` 加索引；`is_deleted` 行后补关系：

```python
    batch_no: Mapped[str | None] = mapped_column(String(100), index=True, comment='批次号')
    batch_completed_at: Mapped[datetime | None] = mapped_column(DateTime, comment='批次完成时间')
    batch_completed_by_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey('user.id', ondelete='SET NULL'), comment='批次完成操作人ID'
    )
```

```python
    batch_completed_by: Mapped[User | None] = relationship(
        'User', foreign_keys=[batch_completed_by_id], backref='batch_completed_stockins'
    )
```

```python
        Index('idx_stockin_batch_no', 'batch_no'),
```

- [ ] **Step 2: 空库 `alembic check` 应报差异（红）**

```bash
# 临时空库（仓库规矩：禁止对生产库 autogenerate）
createdb erp_mig_tmp 2>/dev/null || true
python -m alembic -c migrations/alembic.ini upgrade head
python -m alembic -c migrations/alembic.ini check
```
Expected: FAIL — 提示 `add_column` batch_no / batch_completed_at / batch_completed_by_id 与 `add_index` idx_stockin_batch_no。

- [ ] **Step 3: 写迁移**

`migrations/versions/pg_standalone_096_stockin_batch_fields.py`：

```python
"""stock_in 增加批次号字段（对齐 order）

Revision ID: pg_standalone_096_stockin_batch_fields
Revises: pg_standalone_095_sync_backup_schedule_task_type_comment
"""
import sqlalchemy as sa
from alembic import op

revision = 'pg_standalone_096_stockin_batch_fields'
down_revision = 'pg_standalone_095_sync_backup_schedule_task_type_comment'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('stock_in', sa.Column('batch_no', sa.String(length=100), nullable=True, comment='批次号'))
    op.add_column('stock_in', sa.Column('batch_completed_at', sa.DateTime(), nullable=True, comment='批次完成时间'))
    op.add_column('stock_in', sa.Column('batch_completed_by_id', sa.Integer(), nullable=True, comment='批次完成操作人ID'))
    op.create_foreign_key(
        'fk_stockin_batch_completed_by', 'stock_in', 'user',
        ['batch_completed_by_id'], ['id'], ondelete='SET NULL',
    )
    op.create_index('idx_stockin_batch_no', 'stock_in', ['batch_no'])


def downgrade() -> None:
    op.drop_index('idx_stockin_batch_no', table_name='stock_in')
    op.drop_constraint('fk_stockin_batch_completed_by', 'stock_in', type_='foreignkey')
    op.drop_column('stock_in', 'batch_completed_by_id')
    op.drop_column('stock_in', 'batch_completed_at')
    op.drop_column('stock_in', 'batch_no')
```

> 若 Step 2 的 `check` 报出的对象名/顺序与上面不同（例如 FK 命名），以 autogenerate 的实际输出为准（在本机 `alembic revision --autogenerate` 生成后逐行核对），不要手改成与实际不符的名字。

- [ ] **Step 4: 空库 `upgrade head` + `check` 通过（绿）**

```bash
python -m alembic -c migrations/alembic.ini upgrade head
python -m alembic -c migrations/alembic.ini check
```
Expected: `upgrade` 成功；`check` 输出无差异（无 "Detected changes"）。

- [ ] **Step 5: 破坏性 DDL 守卫测试**

```bash
python -m pytest fastapi_app/tests/test_migration_autogenerate_safety.py -q
```
Expected: PASS（本迁移无破坏性 DDL）。

- [ ] **Step 6: Commit**

```bash
git add fastapi_app/shared_models/stock_in.py migrations/versions/pg_standalone_096_stockin_batch_fields.py
git commit -m "feat(batch): stock_in 增加批次号/完成字段，对齐 order"
```

---

### Task 2: 备货序列化返回真实批次字段

**Files:**
- Modify: `fastapi_app/services/order_batch_service.py`（`_serialize_batch_stockins`，约 195-220 行）
- Test: `fastapi_app/tests/test_order_batch_service_helpers.py`（`TestSerializeBatchStockins`）

**Interfaces:**
- Consumes: `StockIn.batch_no` / `batch_completed_at`（Task 1）。
- Produces: 备货序列化项含 `batch_no` / `batch_completed_at` / `status`（完成态为 `'批次已完成'`）。

- [ ] **Step 1: 写失败测试**

在 `TestSerializeBatchStockins` 追加：

```python
    @pytest.mark.asyncio
    async def test_serialize_stockins_includes_batch_fields(self):
        """备货序列化应带上真实 batch_no / batch_completed_at；未完成时 status 为 None"""
        mock_stockin = MagicMock()
        mock_stockin.id = 20
        mock_stockin.stockin_no = "SI-020"
        mock_stockin.customer = "客户E"
        mock_stockin.stockin_date = datetime(2026, 3, 1, 9, 0)
        mock_stockin.product_id = 8
        product = MagicMock()
        product.name = "产品Z"
        product.barcode = "690008"
        mock_stockin.product = product
        mock_stockin.quantity = 7
        mock_stockin.batch_no = "B2026"
        mock_stockin.batch_completed_at = None

        result_mock = MagicMock()
        result_mock.unique.return_value.scalars.return_value.all.return_value = [mock_stockin]
        db = AsyncMock()
        db.execute = AsyncMock(return_value=result_mock)

        result = await order_batch_service._serialize_batch_stockins(db, [20])
        assert result[20]['batch_no'] == 'B2026'
        assert result[20]['batch_completed_at'] is None
        assert result[20]['status'] is None

    @pytest.mark.asyncio
    async def test_serialize_stockins_completed_sets_status(self):
        """已完成的备货 status 应为 '批次已完成'，batch_completed_at 为字符串"""
        mock_stockin = MagicMock()
        mock_stockin.id = 21
        mock_stockin.stockin_no = "SI-021"
        mock_stockin.customer = "客户F"
        mock_stockin.stockin_date = datetime(2026, 3, 2, 9, 0)
        mock_stockin.product_id = 9
        mock_stockin.product = None
        mock_stockin.quantity = 3
        mock_stockin.batch_no = "B2026"
        mock_stockin.batch_completed_at = datetime(2026, 3, 3, 12, 0)

        result_mock = MagicMock()
        result_mock.unique.return_value.scalars.return_value.all.return_value = [mock_stockin]
        db = AsyncMock()
        db.execute = AsyncMock(return_value=result_mock)

        result = await order_batch_service._serialize_batch_stockins(db, [21])
        assert result[21]['status'] == '批次已完成'
        assert result[21]['batch_completed_at'] == '2026-03-03 12:00'
```

- [ ] **Step 2: 跑测试确认失败**

```bash
python -m pytest "fastapi_app/tests/test_order_batch_service_helpers.py::TestSerializeBatchStockins::test_serialize_stockins_includes_batch_fields" -q
```
Expected: FAIL（`KeyError: 'batch_no'` 或断言不等）。

- [ ] **Step 3: 实现**

`_serialize_batch_stockins` 的 `serialized_stockins[s.id] = {...}` 里，把三行改为：

```python
                'batch_no': s.batch_no,
                'batch_completed_at': s.batch_completed_at.strftime('%Y-%m-%d %H:%M') if s.batch_completed_at else None,
                'status': '批次已完成' if s.batch_completed_at else None,
```

（`'is_locked': None` 与 `'computed_status': None` 保持不变。）

- [ ] **Step 4: 跑测试确认通过**

```bash
python -m pytest "fastapi_app/tests/test_order_batch_service_helpers.py::TestSerializeBatchStockins" -q
```
Expected: PASS（含既有 3 条）。

- [ ] **Step 5: Commit**

```bash
git add fastapi_app/services/order_batch_service.py fastapi_app/tests/test_order_batch_service_helpers.py
git commit -m "feat(batch): 备货序列化带上真实批次号与完成态"
```

---

### Task 3: 保存批次号支持 `record_type=stockin`

**Files:**
- Modify: `fastapi_app/services/order_batch_service.py`（**新增** `update_stockin_batch_no`；`update_batch_no` 保持原样不动）
- Modify: `fastapi_app/schemas/order_batch.py`（`BatchNoUpdate`）
- Modify: `fastapi_app/api/v1/endpoints/order_batch.py`（`update_order_batch_no`，97-122 行）
- Test: `fastapi_app/tests/test_order_batch_service_helpers.py`（新增 `TestUpdateStockinBatchNo`）

**Interfaces:**
- Consumes: `StockIn.batch_no`（Task 1）。
- Produces: `update_stockin_batch_no(db, *, stockin_id, batch_no, user) -> dict`；`BatchNoUpdate.record_type: str = 'order'`。
- **不重命名/不改动 `update_batch_no`**：它另有调用方 `api/v1/endpoints/order.py:459`（`PUT /orders/batch-no/{order_id}`）与既有测试 `tests/test_order_batch.py:178,188`，改签名会连带破坏——保持原签名，新增独立函数。

> 与 spec 的偏差（保留意图、收紧实现）：spec 写的是「`update_batch_no` 加 `record_type` 分支」，实测该函数有第二个调用方与既有测试，改名会破坏它们；改为**新增 `update_stockin_batch_no`**、由**端点**按 `record_type` 路由，端点契约（body 带 `record_type`）与 spec 一致。

- [ ] **Step 1: 写失败测试**

追加类：

```python
class TestUpdateStockinBatchNo:
    @pytest.mark.asyncio
    async def test_sets_batch_no(self):
        """写 StockIn.batch_no，不涉及订单同步"""
        mock_stockin = MagicMock()
        mock_stockin.id = 30
        mock_stockin.batch_no = None
        result = MagicMock()
        result.scalar_one_or_none.return_value = mock_stockin
        db = AsyncMock()
        db.execute = AsyncMock(return_value=result)

        user = MagicMock()
        user.id = 1
        user.username = "admin"

        with patch('fastapi_app.services.order_batch_service._safe_publish_event', new=AsyncMock()), \
             patch('fastapi_app.services.order_batch_service._write_audit_log'):
            out = await order_batch_service.update_stockin_batch_no(
                db, stockin_id=30, batch_no='B9', user=user,
            )
        assert mock_stockin.batch_no == 'B9'
        assert out['updated_count'] == 1

    @pytest.mark.asyncio
    async def test_missing_raises(self):
        """备货不存在应抛 ValueError"""
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        db = AsyncMock()
        db.execute = AsyncMock(return_value=result)
        with pytest.raises(ValueError):
            await order_batch_service.update_stockin_batch_no(
                db, stockin_id=999, batch_no='B9', user=MagicMock(),
            )

    @pytest.mark.asyncio
    async def test_clears_batch_no(self):
        """传 null 清空备货批次号"""
        mock_stockin = MagicMock()
        mock_stockin.id = 31
        mock_stockin.batch_no = 'OLD'
        result = MagicMock()
        result.scalar_one_or_none.return_value = mock_stockin
        db = AsyncMock()
        db.execute = AsyncMock(return_value=result)
        with patch('fastapi_app.services.order_batch_service._safe_publish_event', new=AsyncMock()), \
             patch('fastapi_app.services.order_batch_service._write_audit_log'):
            await order_batch_service.update_stockin_batch_no(
                db, stockin_id=31, batch_no=None, user=MagicMock(),
            )
        assert mock_stockin.batch_no is None
```

- [ ] **Step 2: 跑测试确认失败**

```bash
python -m pytest "fastapi_app/tests/test_order_batch_service_helpers.py::TestUpdateStockinBatchNo" -q
```
Expected: FAIL（`AttributeError: module 'order_batch_service' has no attribute 'update_stockin_batch_no'`）。

- [ ] **Step 3: 改 schema**

`fastapi_app/schemas/order_batch.py` 的 `BatchNoUpdate`：

```python
class BatchNoUpdate(BaseModel):
    batch_no: str | None = Field(None, max_length=100, description='批次号')
    sync_same_batch: bool = Field(False, description='是否同步更新同批次其他订单')
    record_type: str = Field('order', pattern='^(order|stockin)$', description='记录类型：order/stockin')
```

- [ ] **Step 4: 加服务函数**

在 `order_batch_service.py` 中 `update_batch_no` 之后**新增**（`update_batch_no` 一字不改）：

```python
async def update_stockin_batch_no(
    db: AsyncSession,
    *,
    stockin_id: int,
    batch_no: str | None,
    user: User,
) -> dict:
    """更新单条备货记录的批次号（订单路径见 update_batch_no）。"""
    result = await db.execute(select(StockIn).where(StockIn.id == stockin_id).with_for_update())
    stockin = result.scalar_one_or_none()
    if not stockin:
        raise ValueError(f"备货记录不存在: {stockin_id}")

    old_batch_no = stockin.batch_no
    stockin.batch_no = batch_no
    _write_audit_log(
        db, batch_no=batch_no or old_batch_no or '', action='batch_number_change',
        order_ids=[stockin_id], user=user, old_value=old_batch_no, new_value=batch_no,
        detail='record_type=stockin',
    )
    await db.flush()
    await _safe_publish_event("batch_no_updated", {"batch_no": batch_no or '', "stockin_ids": [stockin_id]})
    return {'updated_count': 1}
```

- [ ] **Step 5: 改端点（按 record_type 路由）**

`fastapi_app/api/v1/endpoints/order_batch.py` 的 `update_order_batch_no`：把路径参数名 `order_id` 改 `record_id`（仅函数内局部名，URL 不变），并路由：

```python
@router.put('/orders/{record_id}/batch-no', response_model=BatchNoUpdateResponse)
async def update_order_batch_no(
    record_id: int,
    data: BatchNoUpdate,
    db: AsyncSession = Depends(get_async_db),
    user: User = Depends(require_any_permission('batch_manage', 'order_manage')),
) -> BatchNoUpdateResponse:
    """更新单条记录（订单或备货）的批次号，可选同步同批次其他订单。"""
    async with db_transaction(db):
        if data.record_type == 'stockin':
            result = await order_batch_service.update_stockin_batch_no(
                db, stockin_id=record_id, batch_no=data.batch_no, user=user,
            )
        else:
            result = await order_batch_service.update_batch_no(
                db, order_id=record_id, batch_no=data.batch_no, sync_same_batch=data.sync_same_batch, user=user,
            )
    return BatchNoUpdateResponse(success=True, message='批次号更新成功', updated_count=result['updated_count'])
```

- [ ] **Step 6: 跑测试确认通过（含既有订单路径不回归）**

```bash
python -m pytest "fastapi_app/tests/test_order_batch_service_helpers.py::TestUpdateStockinBatchNo" "fastapi_app/tests/test_order_batch.py" -q
```
Expected: PASS（新用例 + 既有 `test_order_batch.py` 全绿）。

- [ ] **Step 7: Commit**

```bash
git add fastapi_app/services/order_batch_service.py fastapi_app/schemas/order_batch.py fastapi_app/api/v1/endpoints/order_batch.py fastapi_app/tests/test_order_batch_service_helpers.py
git commit -m "feat(batch): 保存批次号支持 record_type=stockin"
```

---

### Task 4: 完成批次同时完成备货

**Files:**
- Modify: `fastapi_app/services/order_batch_service.py`（`complete_batch`，约 460-509 行）
- Test: `fastapi_app/tests/test_order_batch_service_helpers.py`（新增 `TestCompleteBatchStockins`）

**Interfaces:**
- Consumes: `StockIn.batch_no` / `batch_completed_at` / `batch_completed_by_id`（Task 1）。
- Produces: `complete_batch` 返回 dict 增加 `completed_stockins: int`。

- [ ] **Step 1: 写失败测试**

```python
class TestCompleteBatchStockins:
    @pytest.mark.asyncio
    async def test_completes_stockins_of_batch(self):
        """完成批次时该批次未完成的备货也被标记完成"""
        mock_stockin = MagicMock()
        mock_stockin.id = 40
        mock_stockin.batch_completed_at = None
        stockin_result = MagicMock()
        stockin_result.scalars.return_value.all.return_value = [mock_stockin]

        order_result = MagicMock()
        order_result.scalars.return_value.all.return_value = []  # 无订单

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[order_result, stockin_result])

        user = MagicMock()
        user.id = 1
        user.username = "admin"

        with patch('fastapi_app.services.order_batch_service._safe_publish_event', new=AsyncMock()), \
             patch('fastapi_app.services.order_batch_service._write_audit_log'):
            out = await order_batch_service.complete_batch(db, batch_no='B9', user=user)

        assert mock_stockin.batch_completed_at is not None
        assert mock_stockin.batch_completed_by_id == 1
        assert out['completed_stockins'] == 1

    @pytest.mark.asyncio
    async def test_no_orders_no_stockins_raises(self):
        """订单与备货都为空时应抛 ValueError"""
        empty = MagicMock()
        empty.scalars.return_value.all.return_value = []
        db = AsyncMock()
        db.execute = AsyncMock(return_value=empty)
        with pytest.raises(ValueError):
            await order_batch_service.complete_batch(db, batch_no='B-none', user=MagicMock())

    @pytest.mark.asyncio
    async def test_mixed_batch_order_failed_stockin_completed(self):
        """批次里订单未出货 → 进 failed_orders；备货照常完成"""
        mock_order = MagicMock()
        mock_order.id = 50
        mock_order.order_no = "PO-50"
        mock_order.status = "待出货"  # != ORDER_STATUS_SHIPPED
        order_result = MagicMock()
        order_result.scalars.return_value.all.return_value = [mock_order]

        mock_stockin = MagicMock()
        mock_stockin.id = 51
        mock_stockin.batch_completed_at = None
        stockin_result = MagicMock()
        stockin_result.scalars.return_value.all.return_value = [mock_stockin]

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[order_result, stockin_result])

        user = MagicMock()
        user.id = 1
        user.username = "admin"
        with patch('fastapi_app.services.order_batch_service._safe_publish_event', new=AsyncMock()), \
             patch('fastapi_app.services.order_batch_service._write_audit_log'):
            out = await order_batch_service.complete_batch(db, batch_no='B9', user=user)

        assert out['completed_count'] == 0
        assert len(out['failed_orders']) == 1
        assert out['completed_stockins'] == 1
        assert mock_stockin.batch_completed_at is not None
```

- [ ] **Step 2: 跑测试确认失败**

```bash
python -m pytest "fastapi_app/tests/test_order_batch_service_helpers.py::TestCompleteBatchStockins" -q
```
Expected: FAIL（`KeyError: 'completed_stockins'` / 未标记备货）。

- [ ] **Step 3: 实现**

`complete_batch`：在取完 `orders` 之后、`if not orders:` 判断改为「订单+备货都空才报错」，并新增备货完成逻辑：

```python
    stockin_result = await db.execute(
        select(StockIn).where(
            StockIn.batch_no == batch_no,
            StockIn.batch_completed_at.is_(None),
            StockIn.is_deleted.isnot(True),
        ).with_for_update()
    )
    stockins = stockin_result.scalars().all()

    if not orders and not stockins:
        raise ValueError(f"批次 {batch_no} 没有可完成的记录")
```

在 `for o in orders:` 循环之后、写审计之前追加：

```python
    for s in stockins:
        s.batch_completed_at = now
        s.batch_completed_by_id = user.id
```

审计 `detail` 与返回、事件带上备货计数：

```python
    _write_audit_log(
        db, batch_no=batch_no, action='batch_complete',
        order_ids=[o.id for o in completed], user=user,
        detail=f"完成{len(completed)}单+{len(stockins)}备货, 失败{len(failed_orders)}单",
    )
    await db.flush()
    await _safe_publish_event("batch_completed", {
        "batch_no": batch_no,
        "completed_count": len(completed),
        "completed_stockins": len(stockins),
        "failed_count": len(failed_orders),
    })
    return {
        'completed_count': len(completed),
        'completed_stockins': len(stockins),
        'failed_orders': failed_orders,
    }
```

（`now` 与 `completed`/`failed_orders` 的既有定义不变；`if not orders:` 旧判断删除，合并进上面的 `if not orders and not stockins:`。）

- [ ] **Step 4: 跑测试确认通过**

```bash
python -m pytest "fastapi_app/tests/test_order_batch_service_helpers.py::TestCompleteBatchStockins" -q
```
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add fastapi_app/services/order_batch_service.py fastapi_app/tests/test_order_batch_service_helpers.py
git commit -m "feat(batch): 完成批次时一并完成该批次备货"
```

---

### Task 5: 按批次号筛选时备货分支生效

**Files:**
- Modify: `fastapi_app/services/order_batch_service.py`（`_build_batch_stockin_branch`，132-148 行；及 `get_batch_query_list` 的调用点）
- Test: `fastapi_app/tests/test_order_batch_service_helpers.py`（`TestBuildBatchStockinBranch`）

**Interfaces:**
- Consumes: `StockIn.batch_no`（Task 1）。
- Produces: `_build_batch_stockin_branch(whitelist, batch_no, customer, keyword)`（新增 `batch_no` 形参）。

- [ ] **Step 1: 写失败测试**

在 `TestBuildBatchStockinBranch` 追加（并给同文件里**既有 4 条** stockin-branch 调用补上 `batch_no=None`）：

```python
    def test_build_stockin_branch_with_batch_no_filter(self):
        """batch_no 非空时应添加 batch_no 等值条件"""
        branch = order_batch_service._build_batch_stockin_branch(
            whitelist=None, batch_no="B9", customer=None, keyword=None,
        )
        compiled = str(branch.compile())
        assert 'batch_no' in compiled
```

- [ ] **Step 2: 跑测试确认失败**

```bash
python -m pytest "fastapi_app/tests/test_order_batch_service_helpers.py::TestBuildBatchStockinBranch" -q
```
Expected: FAIL（`TypeError: ... unexpected keyword argument 'batch_no'`）。

- [ ] **Step 3: 实现**

`_build_batch_stockin_branch` 签名加 `batch_no`，并在 whitelist 之后加过滤：

```python
def _build_batch_stockin_branch(whitelist, batch_no, customer, keyword):
    stockin_branch = select(
        StockIn.stockin_date.label('sort_date'),
        literal('stockin').label('record_type'),
        StockIn.id.label('record_id'),
    )

    if whitelist:
        stockin_branch = stockin_branch.where(StockIn.customer.in_(whitelist))
    if batch_no:
        stockin_branch = stockin_branch.where(StockIn.batch_no == batch_no)
    if customer:
        stockin_branch = stockin_branch.where(StockIn.customer == customer)
    if keyword:
        kw = f"%{escape_like(keyword)}%"
        stockin_branch = stockin_branch.join(Product, StockIn.product_id == Product.id).where(
            or_(StockIn.stockin_no.ilike(kw), Product.name.ilike(kw), Product.barcode.ilike(kw))
        )
    return stockin_branch
```

并更新调用点（`get_batch_query_list` 第 245 行）：把 `stockin_branch = _build_batch_stockin_branch(whitelist, customer, keyword)` 改为 `stockin_branch = _build_batch_stockin_branch(whitelist, batch_no, customer, keyword)`；同时把第 244 行注释 `# 支 2：备货（无 is_deleted/batch_no/status 过滤，与原实现一致）` 改为 `# 支 2：备货（按 batch_no 过滤；无 is_deleted/status 过滤，与原实现一致）`。

- [ ] **Step 4: 跑测试确认通过**

```bash
python -m pytest "fastapi_app/tests/test_order_batch_service_helpers.py::TestBuildBatchStockinBranch" -q
```
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add fastapi_app/services/order_batch_service.py fastapi_app/tests/test_order_batch_service_helpers.py
git commit -m "feat(batch): 批次号筛选对备货分支生效"
```

---

### Task 6: 前端所有 chip 渲染输入框 + 完成，保存带 record_type

**Files:**
- Modify: `frontend-vite/src/views/batch/components/BatchGroupList.vue`
- Modify: `frontend-vite/src/types/index.ts`（`BatchNoUpdatePayload`）
- Test: `frontend-vite/src/test/batchGroupListStockin.test.ts`（新建）

**Interfaces:**
- Consumes: `orderBatchApi.updateBatchNo(recordId, { batch_no, record_type })`；`BatchQueryItem.record_type`。
- Produces: 无（叶子组件）。

- [ ] **Step 1: 加类型字段**

`frontend-vite/src/types/index.ts` 的 `BatchNoUpdatePayload`：

```ts
export interface BatchNoUpdatePayload {
  batch_no: string | null
  sync_same_batch?: boolean
  record_type?: 'order' | 'stockin'
}
```

- [ ] **Step 2: 写失败测试**

`frontend-vite/src/test/batchGroupListStockin.test.ts`：

```ts
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import BatchGroupList from '@/views/batch/components/BatchGroupList.vue'

const updateBatchNo = vi.fn().mockResolvedValue({ updated_count: 1 })
vi.mock('@/api', () => ({ orderBatchApi: { updateBatchNo: (...a: unknown[]) => updateBatchNo(...a) } }))
vi.mock('@/composables/useToast', () => ({ showToast: vi.fn() }))

const stockinGroup = [{
  customer: 'MINISO国际',
  products: [{
    key: 'p1', productName: '产品X', productBarcode: '690',
    orders: [{ id: 7, order_no: 'SI-7', customer: 'MINISO国际', order_date: '2026-10-01',
      product_id: 1, product_name: '产品X', product_barcode: '690', quantity: 5,
      deducted_qty: 0, shipped_qty: 0, status: null, computed_status: null,
      batch_no: null, batch_completed_at: null, is_locked: null, record_type: 'stockin' }],
  }],
}]

describe('BatchGroupList 备货 chip', () => {
  beforeEach(() => updateBatchNo.mockClear())

  it('备货 chip 也渲染批次号输入框', () => {
    const w = mount(BatchGroupList, { props: { grouped: stockinGroup } })
    expect(w.find('.bt-batch-input').exists()).toBe(true)
  })

  it('备货保存时带 record_type=stockin', async () => {
    const w = mount(BatchGroupList, { props: { grouped: stockinGroup } })
    const input = w.find('.bt-batch-input')
    await input.setValue('B9')
    await input.trigger('keydown.enter')
    expect(updateBatchNo).toHaveBeenCalledWith(7, { batch_no: 'B9', record_type: 'stockin' })
  })

  it('订单与备货 id 撞号时各按自身 record_type 保存（复合键防串扰）', async () => {
    const row = (record_type: 'order' | 'stockin', order_no: string) => ({
      id: 7, order_no, customer: 'MINISO国际', order_date: '2026-10-01', product_id: 1,
      product_name: '产品Y', product_barcode: '691', quantity: 2, deducted_qty: 0, shipped_qty: 0,
      status: null, computed_status: null, batch_no: null, batch_completed_at: null,
      is_locked: null, record_type,
    })
    const mixed = [{
      customer: 'MINISO国际',
      products: [{ key: 'p2', productName: '产品Y', productBarcode: '691',
        orders: [row('order', 'PO-7'), row('stockin', 'SI-7')] }],
    }]
    const w = mount(BatchGroupList, { props: { grouped: mixed } })
    const inputs = w.findAll('.bt-batch-input')
    expect(inputs.length).toBe(2)
    await inputs[1].setValue('BS')
    await inputs[1].trigger('keydown.enter')
    expect(updateBatchNo).toHaveBeenCalledTimes(1)
    expect(updateBatchNo).toHaveBeenCalledWith(7, { batch_no: 'BS', record_type: 'stockin' })
  })
})
```

- [ ] **Step 3: 跑测试确认失败**

```bash
cd frontend-vite && TEMP="$PWD/.vitest-tmp" TMP="$PWD/.vitest-tmp" npx vitest run src/test/batchGroupListStockin.test.ts
```
Expected: FAIL（找不到 `.bt-batch-input`，因 `v-if` 隐藏了备货输入框）。

- [ ] **Step 4: 改组件**

`BatchGroupList.vue` 模板：去掉 `<template v-if="order.record_type !== 'stockin'">` 包裹，让输入框与完成按钮对所有 chip 生效：

```html
            <span class="bt-chip-date">{{ formatDate(order.order_date) }}</span>
            <span class="bt-chip-qty">{{ order.quantity }}</span>
            <input
              class="bt-batch-input"
              :class="{ 'bt-batch-input--has-value': order.batch_no }"
              :value="editingKey === recordKey(order) ? editingValue : (order.batch_no ?? '')"
              placeholder="批次号"
              @focus="startEdit(order)"
              @input="onBatchInput($event, order)"
              @keydown.enter.prevent="saveBatchNo(order)"
              @keydown.escape="cancelEdit"
              @blur="saveBatchNo(order)"
            />
            <button
              v-if="order.batch_no"
              class="bt-complete-btn"
              @click.stop="openCompleteConfirm(order)"
            >完成</button>
```

脚本：把 `editingId: ref<number|null>` 换成复合键：

```ts
const editingKey = ref<string | null>(null)
const editingValue = ref('')
const editingOriginal = ref('')
const saving = ref(false)

/** 订单/备货来自不同表，id 可能撞号 → 用 record_type:id 复合键定位 */
function recordKey(order: BatchQueryItem): string {
  return `${order.record_type ?? 'order'}:${order.id}`
}

function startEdit(order: BatchQueryItem) {
  editingKey.value = recordKey(order)
  editingValue.value = order.batch_no ?? ''
  editingOriginal.value = order.batch_no ?? ''
}

function onBatchInput(event: Event, order: BatchQueryItem) {
  if (editingKey.value !== recordKey(order)) {
    editingKey.value = recordKey(order)
    editingOriginal.value = order.batch_no ?? ''
  }
  editingValue.value = (event.target as HTMLInputElement).value
}

function cancelEdit() {
  editingKey.value = null
  editingValue.value = ''
}

async function saveBatchNo(order: BatchQueryItem) {
  if (saving.value) return
  const newValue = editingValue.value.trim()
  if (newValue === editingOriginal.value) { editingKey.value = null; return }
  if (!newValue) { editingKey.value = null; return }
  saving.value = true
  try {
    await orderBatchApi.updateBatchNo(order.id, { batch_no: newValue || null, record_type: order.record_type === 'stockin' ? 'stockin' : 'order' })
    showToast('批次号已更新', 'success')
    editingKey.value = null
    emit('refresh')
  } catch {
    showToast('批次号更新失败', 'error')
  } finally {
    saving.value = false
  }
}
```

（`openCompleteConfirm` 不变。）

- [ ] **Step 5: 跑测试确认通过**

```bash
cd frontend-vite && TEMP="$PWD/.vitest-tmp" TMP="$PWD/.vitest-tmp" npx vitest run src/test/batchGroupListStockin.test.ts
```
Expected: PASS（3 条）。

- [ ] **Step 6: 前端门禁**

```bash
cd frontend-vite && npm run type-check && npx eslint src/views/batch/components/BatchGroupList.vue src/types/index.ts src/test/batchGroupListStockin.test.ts
```
Expected: 均 exit 0。

- [ ] **Step 7: Commit**

```bash
git add frontend-vite/src/views/batch/components/BatchGroupList.vue frontend-vite/src/types/index.ts frontend-vite/src/test/batchGroupListStockin.test.ts
git commit -m "feat(batch): 备货 chip 也渲染批次号输入框与完成按钮"
```

---

## 收尾（全任务完成后）

- [ ] 聚焦回归：`python -m pytest "fastapi_app/tests/test_order_batch_service_helpers.py" -q`（全绿）。
- [ ] 跨层改动按 `AGENTS.md §4` 跑 CI 三 job 的本地等价物（`quality_gate.py` / `ruff` / `mypy` / 前端四项 `check:*`），或至少后端相关 + 前端 `type-check`+`lint`+`check:api`。
- [ ] 迁移上线顺序：**先迁移（nullable，安全）再前端**；生产升级按 `migrations/README` 用 `_legacy_base_guard` 幂等包装。
- [ ] 评审：按仓库规矩攒到推送前，用 `/open-code-review:delegate-review` 一次审「当前分支相对 main 的 merge-base 起全部提交」，迭代到零 High/Medium 再推。
