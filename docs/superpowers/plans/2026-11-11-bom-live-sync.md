# 采购明细与 BOM 实时同步 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 pending 采购单明细始终与当前 BOM 一致——BOM 保存后即时重建明细，上线时全量校正存量单，并提供版本号并发保护。

**Architecture:** 以 PO 为单位、按 `purchase_order_sku` 快照全 SKU 展开 BOM，复用生成路径的 `_material_row` 口径重算目标行；规范序列比较无变化则短路，否则整单替换（保留 loss_rate/unit_price/remark），并递增 `items_version`、写审计日志。BOM 保存 post-commit 回调触发同步；部位拆行改为 BOM 感知。

**Tech Stack:** FastAPI + SQLAlchemy(async) + PostgreSQL + Alembic；Vue3 + TS + vitest；pytest(asyncio, sqlite 夹具)。

**Spec:** `docs/superpowers/specs/2026-11-11-bom-live-sync-design.md`（实现前先读；本计划与 spec 冲突时以 spec 为准）

## Global Constraints

- 生产主机即开发机：所有命令小步执行；迁移手写、保持**单一 head**，**禁止对生产库 `alembic autogenerate`**。
- 仅同步 `PurchaseOrder.status == 'pending'`；`confirmed`/`completed` 一律不动。
- BOM 是唯一真源：同步覆盖数量；`loss_rate`、`unit_price`、`remark` 按物料键继承保留。
- BOM 已不存在的明细行（含手工行）删除，并写 `ModificationLog(field_name='bom_sync')`。
- 并发保护：`purchase_order.items_version` 单调递增；两种写接口校验版本，不一致返回 409（`ITEMS_VERSION_CONFLICT`）。
- 后端测试必须提权跑（根 `.env` ACL）或用仓内既定夹具；前端 vitest 需 `TEMP` 指向仓内 `.vitest-tmp`。
- 每个任务按 TDD：先写失败测试 → 跑红 → 最小实现 → 跑绿 → 提交（只 `git add` 本任务文件）。
- API schema 变更后必须重导 OpenAPI 快照与前端类型（Task 10）。

## Review Focus

1. **用户正在汇总弹窗编辑时 BOM 被保存**：用户旧版本保存必须被 409 拒绝并提示刷新，绝不能静默覆盖同步结果。
2. **completed / confirmed 单**：任何 BOM 变更都不得改动其明细、金额或 `items_version`。
3. **同键多行**（多角色/多 SKU 使用同一物料）：同步后行数与数量必须与生成路径一致，不得合并丢行。
4. **产品改名 / 缺失 sku 快照**：PID 解析失败的单必须**跳过并报告**，不得按不完整 BOM 重写。
5. **BOM 被删空**：走撤销链（订单回到待备货、由自动生成重建），不得保留被同步成空明细的采购单。

---

### Task 1: 数据库迁移与模型字段 `items_version`

**Files:**
- Create: `migrations/versions/pg_standalone_118_add_po_items_version.py`
- Modify: `fastapi_app/shared_models/purchase_order.py`（`PurchaseOrder` 类字段区，约 55-86 行）
- Test: `fastapi_app/tests/services/test_po_items_version_model.py`

**Interfaces:**
- Produces: `PurchaseOrder.items_version: Mapped[int]`（默认 0，NOT NULL），后续任务读写该属性。

- [ ] **Step 1: 写失败测试**

```python
# fastapi_app/tests/services/test_po_items_version_model.py
import pytest
from fastapi_app.shared_models import PurchaseOrder


def test_items_version_defaults_to_zero():
    order = PurchaseOrder(order_no='PO-T-1', product_quantity=100)
    assert order.items_version == 0


def test_items_version_is_int_column():
    col = PurchaseOrder.__table__.c.items_version
    assert col.nullable is False
    assert col.default.arg == 0
```

- [ ] **Step 2: 跑红**

Run: `.venv/Scripts/python.exe -m pytest fastapi_app/tests/services/test_po_items_version_model.py -q`（提权）
Expected: FAIL（`AttributeError` / 无该列）

- [ ] **Step 3: 改模型 + 写迁移**

模型 `PurchaseOrder` 增加（放在 `spare_rate` 之后）：

```python
    items_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default='0',
        comment='采购明细版本号：BOM 同步与用户编辑都递增，用于 409 并发保护',
    )
```

迁移文件（照 117 的结构）：

```python
"""purchase_order 增加 items_version（明细版本号，BOM 同步/编辑冲突保护）

Revision ID: pg_standalone_118_add_po_items_version
Revises: pg_standalone_117_add_role_final_versions
Create Date: 2026-11-11
"""
from alembic import op

from migrations._legacy_base_guard import base_schema_absent

revision = 'pg_standalone_118_add_po_items_version'
down_revision = 'pg_standalone_117_add_role_final_versions'
branch_labels = None
depends_on = None


def upgrade():
    if base_schema_absent():
        return
    op.execute(
        "ALTER TABLE purchase_order "
        "ADD COLUMN IF NOT EXISTS items_version INTEGER NOT NULL DEFAULT 0"
    )
    op.execute(
        "COMMENT ON COLUMN purchase_order.items_version IS "
        "'采购明细版本号：BOM 同步与用户编辑都递增，用于 409 并发保护'"
    )


def downgrade():
    if base_schema_absent():
        return
    op.execute('ALTER TABLE purchase_order DROP COLUMN IF EXISTS items_version')
```

- [ ] **Step 4: 跑绿**

Run: `.venv/Scripts/python.exe -m pytest fastapi_app/tests/services/test_po_items_version_model.py -q`
Expected: PASS

- [ ] **Step 5: 迁移 CLI 冒烟（不连生产库）**

Run: `.venv/Scripts/python.exe -m alembic -c migrations/alembic.ini heads`
Expected: 输出唯一 head `pg_standalone_118_add_po_items_version`

- [ ] **Step 6: 提交**

```bash
git add migrations/versions/pg_standalone_118_add_po_items_version.py \
  fastapi_app/shared_models/purchase_order.py \
  fastapi_app/tests/services/test_po_items_version_model.py
git commit -m "feat(purchase): purchase_order 增加 items_version（BOM 同步并发保护）"
```

---

### Task 2: 共享「BOM 行 → 采购明细行」构建函数

**Files:**
- Modify: `fastapi_app/services/purchase_order_generate.py`（`_material_row` 之后）
- Test: `fastapi_app/tests/services/test_build_expected_items.py`

**Interfaces:**
- Produces:
  - `build_expected_items(sku_lines: list[dict], ctx: _BomContext, name_to_pid: dict[str, int], customer_name: str) -> list[dict]`
  - `sku_lines` 元素：`{'product_name': str, 'order_qty': float}`（同一 pid 的多行先合并总数量）
  - 返回行 dict 字段与 `_material_row` 完全一致（`material_name/specification/unit/quantity/supplier_name/part_name/category/unit_usage/...`），`quantity` 已按角色分配与生成路径同口径。
- Consumes: `_load_bom_context`、`_MATERIAL_SPECS`、`_scope_label`、`allocate_scope_quantities`。

- [ ] **Step 1: 写失败测试**

```python
# fastapi_app/tests/services/test_build_expected_items.py
from types import SimpleNamespace

from fastapi_app.services.purchase_order_generate import _BomContext, build_expected_items


def _fabric(pid, name, usage, part=None, supplier='美利达', spec='S1'):
    return SimpleNamespace(product_id=pid, role_id=None, fabric_name=name,
                           specification=spec, part_name=part, supplier_name=supplier,
                           unit='码', quantity=usage, material_code='', supplier_id=None)


def _acc(pid, rid, name, usage):
    return SimpleNamespace(product_id=pid, role_id=rid, accessory_name=name,
                           specification='1条', part_name=None, supplier_name='木棒',
                           unit='个', quantity=usage, material_code='', supplier_id=None)


def test_blind_box_roles_split_and_allocate():
    """6 角色盲盒：默认BOM 两条同物料跨身体/脚底不合并；辅料每角色一行。"""
    ctx = _BomContext()
    ctx.fabric = {None: [_fabric(1, '绿色超柔', 1.0, '身体'), _fabric(1, '绿色超柔', 1.0, '脚底')]}
    ctx.accessory = {rid: [_acc(1, rid, '木棒按摩锤', 1.0)] for rid in range(11, 17)}
    ctx.role_names = {(1, rid): f'角色{rid}' for rid in range(11, 17)}
    ctx.scopes_by_pid = {1: [None, 11, 12, 13, 14, 15, 16]}
    ctx.blind_box_pids = {1}

    items = build_expected_items(
        [{'product_name': '产品A', 'order_qty': 3000}], ctx, {'产品A': 1}, '客户甲',
    )

    green = [i for i in items if i['material_name'] == '绿色超柔']
    assert sorted(i['quantity'] for i in green) == [3000.0, 3000.0]  # 默认BOM 两条 × N
    assert sorted(i['part_name'] for i in green) == ['脚底', '身体']
    wood = [i for i in items if i['material_name'] == '木棒按摩锤']
    assert len(wood) == 6  # 每角色一行
    assert all(i['quantity'] == 500.0 for i in wood)
```

- [ ] **Step 2: 跑红** → `ImportError: cannot import name 'build_expected_items'`

- [ ] **Step 3: 实现**

```python
def build_expected_items(sku_lines, ctx: _BomContext, name_to_pid, customer_name: str) -> list[dict]:
    """按 PO 的逐 SKU 快照重算采购明细行（与生成路径同口径）。

    同一 pid 的多行先合并订单数量；盲盒 pid 合并后整体分配一次（避免重复进位）；
    非盲盒保持历史上限「每个作用域都用完整数量」。
    """
    pid_name_map = {pid: name for name, pid in name_to_pid.items()}
    items: list[dict] = []
    merged: dict[int, dict] = {}
    for line in sku_lines or []:
        name = (line.get('product_name') or '').strip()
        pid = name_to_pid.get(name)
        if pid is None:
            continue
        entry = merged.setdefault(pid, {'qty': 0.0, 'name': name})
        entry['qty'] += float(line.get('order_qty') or 0)

    for pid, entry in merged.items():
        product_name = pid_name_map.get(pid) or entry['name']
        scopes = ctx.scopes_for(pid)
        if pid in ctx.blind_box_pids:
            allocation = allocate_scope_quantities(
                entry['qty'], scopes,
                hidden_carton_ratio=ctx.hidden_ratios.get(pid),
                name_of=partial(_role_name_lookup, ctx.role_names, pid),
                hidden_role_id=ctx.hidden_role_ids.get(pid),
                blind_box=True, has_hidden=pid in ctx.has_hidden_pids,
            )
        else:
            allocation = {role_id: entry['qty'] for role_id in scopes}
        for role_id in scopes:
            scope_qty = allocation.get(role_id, entry['qty'])
            scope_label = _scope_label(pid, role_id, ctx.role_names)
            for spec in _MATERIAL_SPECS:
                for row in getattr(ctx, spec.map_attr).get(role_id, []):
                    if row.product_id != pid:
                        continue
                    items.append(_material_row(spec, row, scope_qty, product_name, customer_name, scope_label))
    return items
```

注意：`_role_name_lookup` / `_scope_label` 已存在于 `purchase_order_generate.py`，直接复用；不得另写名称归一逻辑。

- [ ] **Step 4: 跑绿**；同命令。
- [ ] **Step 5: 提交**

```bash
git add fastapi_app/services/purchase_order_generate.py fastapi_app/tests/services/test_build_expected_items.py
git commit -m "feat(purchase): 抽取按 SKU 快照重算明细的共享构建函数"
```

---

### Task 3: 同步服务核心（整单重建 + 版本 + 审计）

**Files:**
- Create: `fastapi_app/services/purchase/bom_sync.py`
- Modify: `fastapi_app/core/exceptions.py`（新增 `ItemsVersionConflict`）
- Test: `fastapi_app/tests/services/test_bom_sync.py`

**Interfaces:**
- Produces:
  - `class ItemsVersionConflict(ConflictError)`：`code='ITEMS_VERSION_CONFLICT'`，status 409。
  - `@dataclass SyncResult(po_id, changed, added, updated, removed, removed_rows, skipped_reason=None)`
  - `async def sync_purchase_order_items(db, po_id, *, expected_version=None, dry_run=False) -> SyncResult`
  - `async def find_pending_po_ids_for_product(db, product_id) -> tuple[list[int], list[int]]`
  - `async def sync_pending_items_for_product(db, product_id, *, dry_run=False) -> dict`
- Consumes: Task 2 `build_expected_items`、`_load_bom_context`、`_load_product_names`、`fetch_po_sku_map`/`fetch_po_sku_lines_map`/`fetch_po_sku_pids_map`、`_recalc_item_total_price`、`ModificationLog`。

- [ ] **Step 1: 写失败测试（覆盖 Review Focus 2/3）**

```python
# fastapi_app/tests/services/test_bom_sync.py
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from fastapi_app.services.purchase.bom_sync import (
    ItemsVersionConflict, find_pending_po_ids_for_product,
    sync_pending_items_for_product, sync_purchase_order_items,
)
from fastapi_app.shared_models import (
    Base, Order, OrderItem, Product, ProductAccessory, ProductFabric,
    ProductRole, PurchaseOrder, PurchaseOrderItem, PurchaseOrderSku,
)


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine('sqlite+aiosqlite:///:memory:')
    tables = [PurchaseOrder.__table__, PurchaseOrderItem.__table__, PurchaseOrderSku.__table__,
              Order.__table__, OrderItem.__table__, Product.__table__,
              ProductFabric.__table__, ProductAccessory.__table__, ProductRole.__table__]
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=tables))
    maker = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


async def _seed(session, *, status='pending', po_id=8101, po_sku_name='产品A',
                source_order_ids='[9101]'):
    """盲盒产品 201：6 角色；绿色超柔跨身体/脚底各 1.0；木棒辅料每角色 1.0。"""
    session.add(Product(id=201, name='产品A', is_blind_box=True, has_hidden_role=False))
    for rid in range(11, 17):
        session.add(ProductRole(id=rid, product_id=201, role_name=f'角色{rid}'))
        session.add(ProductAccessory(
            id=1000 + rid, product_id=201, role_id=rid, accessory_name='木棒按摩锤',
            specification='1条', unit='个', quantity=1.0, supplier_name='木棒'))
    for fid, part in ((1, '身体'), (2, '脚底')):
        session.add(ProductFabric(
            id=fid, product_id=201, role_id=None, fabric_name='绿色超柔',
            specification='234', unit='码', quantity=1.0, part_name=part,
            supplier_name='美利达'))
    session.add(Order(id=9101, order_no='SO-9101', customer='客户甲',
                      product_id=201, quantity=10000, status='已备货'))
    session.add(OrderItem(id=1, order_id=9101, product_id=201,
                          product_name='产品A', quantity=10000))
    session.add(PurchaseOrder(
        id=po_id, order_no=f'PO-{po_id}', customer_name='客户甲', product_name='产品A',
        product_quantity=10000, supplier_name='美利达',
        source_order_ids=source_order_ids, status=status))
    session.add(PurchaseOrderSku(
        id=po_id, po_id=po_id, product_name=po_sku_name, product_barcode='bA',
        order_qty=10000, source_order_id=9101, source_record_type='order'))
    # 旧快照：绿色超柔一行 50（无部位、有率/价）；手工孤儿行 蓝色超柔 890
    session.add(PurchaseOrderItem(
        id=1, order_id=po_id, material_name='绿色超柔', specification='234',
        unit='码', part_name=None, supplier_name='美利达', quantity=50,
        loss_rate=30, unit_price=2, material_category='fabric'))
    session.add(PurchaseOrderItem(
        id=2, order_id=po_id, material_name='蓝色超柔', specification='223',
        unit='码', part_name=None, supplier_name='美利达', quantity=890,
        material_category='fabric'))
    await session.commit()


async def test_sync_rebuilds_rows_for_pending_po_blind_box(db):
    res = await sync_purchase_order_items(db, 8101)
    assert res.changed and res.added == 8  # 绿色身体/脚底 2 行 + 6 条辅料行

    rows = (await db.execute(select(PurchaseOrderItem).where(
        PurchaseOrderItem.order_id == 8101))).scalars().all()
    green = sorted((r.part_name, float(r.quantity)) for r in rows if r.material_name == '绿色超柔')
    assert green == [('脚底', 10000.0), ('身体', 10000.0)]
    # 孤儿行（蓝色超柔）被删除
    assert all(r.material_name != '蓝色超柔' for r in rows)
    # 辅料每角色一行、合计恒等于订单量
    wood = [r for r in rows if r.material_name == '木棒按摩锤']
    assert len(wood) == 6
    assert sum(float(r.quantity) for r in wood) == 10000.0

    po = await db.get(PurchaseOrder, 8101)
    assert po.items_version == 1


async def test_sync_is_noop_when_unchanged(db):
    await sync_purchase_order_items(db, 8101)
    res = await sync_purchase_order_items(db, 8101)
    assert res.changed is False
    po = await db.get(PurchaseOrder, 8101)
    assert po.items_version == 1  # 无变化不抖动


async def test_sync_preserves_loss_rate_and_price_across_parts(db):
    await sync_purchase_order_items(db, 8101)
    green = (await db.execute(select(PurchaseOrderItem).where(
        PurchaseOrderItem.order_id == 8101,
        PurchaseOrderItem.material_name == '绿色超柔'))).scalars().all()
    assert {float(r.loss_rate) for r in green} == {30.0}
    assert {float(r.unit_price) for r in green} == {2.0}
    assert {float(r.total_price) for r in green} == {20600.0}  # 10000×1.03×2


async def test_sync_skips_completed_po(db):
    await _seed(db, status='completed')
    res = await sync_purchase_order_items(db, 8101)
    assert res.changed is False and res.skipped_reason == 'status:completed'


async def test_stale_version_raises_conflict(db):
    with pytest.raises(ItemsVersionConflict):
        await sync_purchase_order_items(db, 8101, expected_version=99)
```

- [ ] **Step 2: 跑红** → ModuleNotFoundError

- [ ] **Step 3: 实现 `bom_sync.py`**

实现要点（逐条落实，不可省略）：

1. `sync_purchase_order_items` 内 `db.get(PurchaseOrder, po_id, with_for_update=True)`；不存在 → `SyncResult(changed=False, skipped_reason='not_found')`；`status != 'pending'` → `skipped_reason=f'status:{status}'`。
2. `expected_version is not None and order.items_version != expected_version` → raise `ItemsVersionConflict()`。
3. 取 sku 行：`fetch_po_sku_map(db, [po_id])`，缺失回退 `fetch_po_sku_lines_map(db, [order])`；空 → 回退单行 `{'product_name': order.product_name, 'order_qty': order.product_quantity}`。
4. `po_pids_map = await fetch_po_sku_pids_map(db, [order])`；`pids = po_pids_map.get(po_id) or []`；任一 sku 行按名称/条码解析不到 pid → `skipped_reason='unresolved_sku'` 并返回（不写库）。
5. `ctx = await _load_bom_context(db, pids)`；`pid_name_map = await _load_product_names(db, pids)`；`expected = build_expected_items(sku_lines, ctx, pid_name_map, order.customer_name or '')`。
6. 现有行按 id 升序；继承池 `pool[(material,spec,unit,part,supplier,category)] -> deque[(loss_rate, unit_price, remark)]`。
   目标行**先按精确键领取（消费式）**；未领到精确键的行，再按回退键
   `(material,spec,unit,supplier,category)` 取「可复用」的率/价（同一回退值应用到所有
   剩余行，不消费）——这样旧单一行跨 `身体/脚底` 两个部位时，两行都继承 30‰ / 单价 2。
7. 目标行补齐继承字段；规范序列比较（排序后的 `(material,spec,unit,part,supplier,category,float(quantity),float(unit_usage or 0))` 列表）——相同则 `changed=False` 直接返回。
8. `dry_run=True`：返回 `SyncResult(changed=True, added=…, removed=…, updated=…, removed_rows=[…])`，**不做任何写操作**。added/removed 由目标键 multiset 与现有键 multiset 差值计算。
9. 写路径：`DELETE` 旧行 → 批量 `db.add(PurchaseOrderItem(...))`（用 `order_id`，字段来自目标行 dict；`total_price` 由 `_recalc_item_total_price(item, order.spare_rate)` 计算）→ `order.total_amount = Σ total_price` → `order.items_version += 1` → `db.add(ModificationLog(target_type='purchase_order', target_id=po_id, field_name='bom_sync', old_value=None, new_value=json.dumps(summary, ensure_ascii=False), modifier_name='system:bom_sync'))` → `await db.flush()`。事务由调用方控制。
10. `find_pending_po_ids_for_product`：查 `PurchaseOrder.status == 'pending'` 全量 → `fetch_po_sku_pids_map`（内部含三层回退）→ 返回 `(含该 pid 的 po_id 列表, 解析失败 po_id 列表)`。
11. `sync_pending_items_for_product(db, product_id, *, dry_run=False)`：用传入会话处理每个受影响 PO，**逐单 `async with db.begin_nested()`（savepoint）** 包住 `sync_purchase_order_items`；单张异常 → 回滚该单并记日志继续（不污染其他单）。返回 `{'synced': n, 'skipped': m, 'results': [...]}`。调用方（BOM 回调 / backfill）负责外层会话与最终提交。

- [ ] **Step 4: 跑绿**；再跑 `pytest fastapi_app/tests/services/test_factory_summary_multisku.py -q` 确认无回归。
- [ ] **Step 5: 提交**

```bash
git add fastapi_app/services/purchase/bom_sync.py fastapi_app/core/exceptions.py fastapi_app/tests/services/test_bom_sync.py
git commit -m "feat(purchase): 新增 BOM 明细同步服务（整单重建/版本/审计）"
```

---

### Task 4: 产品级发现与同步报告

**Files:**
- Modify: `fastapi_app/services/purchase/bom_sync.py`
- Test: `fastapi_app/tests/services/test_bom_sync.py`（追加）

**Interfaces:**
- Produces: Task 3 已声明的 `find_pending_po_ids_for_product` / `sync_pending_items_for_product` 的完整实现与报告结构。

- [ ] **Step 1: 写失败测试**

```python
async def test_find_pending_only_and_skip_completed(db):
    await _seed(db)                       # PO 8101 pending，产品 201
    await _seed(db, po_id=8102, status='completed')
    affected, unresolved = await find_pending_po_ids_for_product(db, 201)
    assert affected == [8101]
    assert unresolved == []


async def test_unresolved_sku_is_reported_not_written(db):
    # 无 source_order_ids 且 sku 名称对不上 → 三层回退全部失败 → unresolved
    await _seed(db, po_sku_name='改名前的产品名', source_order_ids=None)
    affected, unresolved = await find_pending_po_ids_for_product(db, 201)
    assert affected == []
    assert unresolved == [8101]
    report = await sync_pending_items_for_product(db, 201)
    assert report['synced'] == 0
```

- [ ] **Step 2: 跑红** → 断言失败/函数未实现
- [ ] **Step 3: 实现**（见 Task 3 第 10/11 条；注意 `fetch_po_sku_pids_map` 的回退链已覆盖「名称改名」场景——若名称完全匹配失败且 OrderItem 也解析不到，才计入 unresolved）
- [ ] **Step 4: 跑绿**
- [ ] **Step 5: 提交**

```bash
git add fastapi_app/services/purchase/bom_sync.py fastapi_app/tests/services/test_bom_sync.py
git commit -m "feat(purchase): BOM 同步的产品级发现与失败报告"
```

---

### Task 5: BOM 保存回调接入同步

**Files:**
- Modify: `fastapi_app/services/purchase/_auto_generate.py:88-108`（`_run_bom_saved`）
- Test: `fastapi_app/tests/services/test_bom_save_hook.py`

**Interfaces:**
- Consumes: Task 4 `sync_pending_items_for_product`。
- Produces: `_run_bom_saved` 新顺序：撤销（若删空）→ 同步 → 自动生成。

- [ ] **Step 1: 写失败测试**

```python
async def test_bom_save_runs_sync_before_auto_generate(monkeypatch):
    calls = []
    async def fake_sync(db, product_id):
        calls.append(('sync', product_id))
    async def fake_generate(*a, **k):
        calls.append(('generate', None))
    monkeypatch.setattr(_auto_generate, 'sync_pending_items_for_product', fake_sync)
    monkeypatch.setattr(_auto_generate, '_run_auto_generate', fake_generate)
    # 用 monkeypatch 替换 require_async_session_local / db_transaction / revoke
    await _auto_generate._run_bom_saved(42)
    assert [c[0] for c in calls] == ['sync', 'generate']
```

（`_run_bom_saved` 现状内嵌 import；实现后把同步调用放在 revoke 之后、`_run_auto_generate()` 之前，并让测试用 monkeypatch 打桩三个依赖。）

- [ ] **Step 2: 跑红**
- [ ] **Step 3: 实现**

```python
    try:
        from fastapi_app.services.purchase.bom_sync import sync_pending_items_for_product
        session_factory = require_async_session_local()
        async with session_factory() as db:
            async with db_transaction(db):
                report = await sync_pending_items_for_product(db, product_id)
        if report.get('synced'):
            logger.info('BOM 变更同步采购明细: product=%s synced=%s', product_id, report['synced'])
    except Exception:  # broad-except: 同步失败不得影响 BOM 保存本身
        logger.warning('BOM 变更同步采购明细失败（不影响本次保存）', exc_info=True)

    await _run_auto_generate()
```

- [ ] **Step 4: 跑绿**
- [ ] **Step 5: 提交**

```bash
git add fastapi_app/services/purchase/_auto_generate.py fastapi_app/tests/services/test_bom_save_hook.py
git commit -m "feat(purchase): BOM 保存后即时同步 pending 采购明细"
```

---

### Task 6: 版本冲突在写接口生效（后端）

**Files:**
- Modify: `fastapi_app/api/v1/endpoints/purchase_center/schemas.py`（`FactorySummarySaveRequest`、`PurchaseOrderUpdateRequest`）
- Modify: `fastapi_app/api/v1/endpoints/purchase_center/order_routes.py`（factory-summary 返回 `items_versions`；两个保存端点传版本）
- Modify: `fastapi_app/services/purchase_order_crud.py`（`save_factory_summary_edits`、`update_purchase_order` 校验）
- Modify: `fastapi_app/services/purchase_order_query.py`（`get_factory_order_summary` 返回 `items_versions`）
- Modify: `fastapi_app/shared_models/purchase_order.py`（`to_dict` 增加 `items_version`）
- Test: `fastapi_app/tests/services/test_items_version_conflict.py`

**Interfaces:**
- Produces:
  - 请求字段：`FactorySummarySaveRequest.items_versions: dict[int, int] = {}`、`PurchaseOrderUpdateRequest.items_version: int | None = None`
  - 响应：factory-summary 顶层 `items_versions: {'<po_id>': int}`；订单 `to_dict()['items_version']`
  - 409：`ItemsVersionConflict`

- [ ] **Step 1: 写失败测试**

服务层（追加到 `fastapi_app/tests/services/test_bom_sync.py`，复用该文件的 `db`/`_seed` 夹具）：

```python
from fastapi_app.services.purchase_order_crud import save_factory_summary_edits, update_purchase_order


async def test_factory_save_rejects_stale_items_version(db):
    await _seed(db)                       # items_version=0
    with pytest.raises(ItemsVersionConflict):
        await save_factory_summary_edits(
            db, [], 'tester', spare_rate=30, order_ids=[8101],
            items_versions={8101: 99},
        )


async def test_update_order_rejects_stale_items_version(db):
    await _seed(db)
    with pytest.raises(ItemsVersionConflict):
        await update_purchase_order(db, 8101, {'items_version': 99})


async def test_factory_summary_exposes_items_versions(db):
    await _seed(db)
    summary = await get_factory_order_summary(db, [8101])
    assert summary['items_versions'] == {8101: 0}
```

路由层 409 映射（追加到 `fastapi_app/tests/test_purchase_center.py`，用全局 `client` 夹具）：

```python
@pytest.mark.asyncio
async def test_factory_save_conflict_maps_to_409(self, client):
    from unittest.mock import AsyncMock, patch
    from fastapi_app.core.exceptions import ConflictError

    with patch(
        'fastapi_app.api.v1.endpoints.purchase_center.order_routes.svc.save_factory_summary_edits',
        AsyncMock(side_effect=ConflictError('BOM 已更新')),
    ):
        resp = await client.post('/api/v1/purchase-center/orders/factory-summary/save', json={
            'edits': [], 'order_ids': [1], 'spare_rate': 1, 'items_versions': {'1': 0},
        })
    assert resp.status_code == 409
```

说明：`ItemsVersionConflict` 继承 `ConflictError`（AppError），路由现有 `except (ValueError, RuntimeError)` 不会兜住它，由全局 AppError 处理器映射 409。

- [ ] **Step 2: 跑红**
- [ ] **Step 3: 实现**
  - `save_factory_summary_edits(db, data, username, spare_rate=None, order_ids=None, items_versions=None)`：收集涉及 po_id（`order_ids ∪ edits 命中 item 的 order_id`），逐单比对 `items_version`，不一致 raise `ItemsVersionConflict`；**校验在任何写入之前**。
  - `update_purchase_order(..., data)`：`data.get('items_version')` 非 None 且不等于当前 → raise；放在 `_apply_order_field_updates` 之前。
  - 路由把 `data.items_versions` / `data.items_version` 传给服务（`exclude_unset` 语义保留）。
  - 汇总接口组装 `items_versions = {str(o.id): o.items_version for o in orders}`。
  - 路由的 `except (OperationalError, ..., ValueError, RuntimeError)` **不要**捕获 `ConflictError`（`ItemsVersionConflict` 必须冒泡到全局 AppError → 409）。
- [ ] **Step 4: 跑绿 + `pytest fastapi_app/tests/test_purchase_center.py -q`**
- [ ] **Step 5: 提交**

```bash
git add fastapi_app/api/v1/endpoints/purchase_center/schemas.py \
  fastapi_app/api/v1/endpoints/purchase_center/order_routes.py \
  fastapi_app/services/purchase_order_crud.py fastapi_app/services/purchase_order_query.py \
  fastapi_app/shared_models/purchase_order.py fastapi_app/tests/services/test_items_version_conflict.py
git commit -m "feat(purchase): 明细写接口 items_version 409 并发保护"
```

---

### Task 7: 部位拆行改为 BOM 感知

**Files:**
- Modify: `fastapi_app/services/purchase/_factory.py`（`_split_parts_by_group`、`_matching_po_items`、`_build_factory_group_map` 调用处）
- Test: `fastapi_app/tests/services/test_factory_summary_multisku.py`（追加）

**Interfaces:**
- Produces: `_split_parts_by_group(orders, items_by_order, cust_order_map, prod_name_map, bom_data, po_pids_map)`；`_matching_po_items` 在拆行模式统一用 `items_map_by_part`（含空部位键）。

- [ ] **Step 1: 写失败测试**

```python
async def test_c19_split_parts_when_bom_has_parts_ignoring_partless_accessory(db):
    """同物料跨身体/脚底两行 + 无部位辅料：工厂页必须拆成两行，辅料单独一行。"""
    session, _ = db
    # 产品 201：绿色超柔 身体 1.0 / 脚底 1.0；辅料 木棒 1.0 无部位；PO 10000 件，
    # 明细按 BOM 同步后的形态：绿色两行各 10000（part 身体/脚底）+ 木棒 10000（无部位）。
    ...
    group = (await get_factory_order_summary(session, [8101]))['groups'][0]
    mats = [m for s in group['skus'] for m in s['materials'] if m['material_name'] == '绿色超柔']
    assert sorted(m['part_display'] for m in mats) == ['脚底', '身体']
    assert all(float(m['quantity']) == 10000.0 for m in mats)
```

- [ ] **Step 2: 跑红**（当前整单合并为一行「身体/脚底」）
- [ ] **Step 3: 实现**

```python
def _split_parts_by_group(orders, items_by_order, cust_order_map, prod_name_map,
                          bom_data, po_pids_map) -> dict[tuple, bool]:
    """BOM 有非空部位即拆行；无部位明细（辅料/手工行）不再阻塞整组。"""
    split_by_group: dict[tuple, bool] = {}
    for po in orders:
        cust, prod, _order_qty, pid = _resolve_factory_po_info(po, cust_order_map, prod_name_map)
        key = (cust, prod)
        pids = _resolve_po_pids(po_pids_map, po, pid)
        aware = any(
            _norm_part_name(bom.get('part_name'))
            for p_id in pids for bom in bom_data.get(p_id, [])
            if not _is_filling_category(bom.get('category'))
        )
        split_by_group[key] = split_by_group.get(key, False) or aware
    return split_by_group
```

`_matching_po_items`：

```python
def _matching_po_items(po, bom, items_map, items_map_by_part, *, split_parts, part_key):
    if split_parts:
        return (items_map_by_part or {}).get(
            (po.id, bom['material_name'], bom['specification'], bom['unit'], part_key), [],
        )
    return items_map.get((po.id, bom['material_name'], bom['specification'], bom['unit']), [])
```

（BOM 无部位行 `part_key == ''`，同步后的明细 `part_name NULL` 归一为 `''`，精确命中。）

- [ ] **Step 4: 跑绿 + 全族回归**

Run: `.venv/Scripts/python.exe -m pytest fastapi_app/tests/services/test_factory_summary_multisku.py fastapi_app/tests/services/test_factory_summary_hidden_ratio.py fastapi_app/tests/test_supplier_order_breakdown.py -q`
Expected: 全 PASS（含既有 `test_cross_sku_shared_material_lists_every_sku_part`）

- [ ] **Step 5: 提交**

```bash
git add fastapi_app/services/purchase/_factory.py fastapi_app/tests/services/test_factory_summary_multisku.py
git commit -m "fix(purchase): 部位拆行改为 BOM 感知，无部位辅料不再阻塞"
```

---

### Task 8: 存量 pending 单校正脚本（dry-run/apply）

**Files:**
- Create: `scripts/sync_pending_po_items.py`
- Test: `fastapi_app/tests/services/test_sync_backfill_script.py`

**Interfaces:**
- Produces: `python scripts/sync_pending_po_items.py [--dry-run|--apply] [--product-id N]`；
  输出四类清单：`changed`、`added`、`removed`（含 `suspected_manual` 标记：现有关键字不在任何 BOM 目标键中）、`unresolved`。

- [ ] **Step 1: 写失败测试**：构造两张 pending 单（一张需改量、一张含手工行），调用脚本核心函数 `run_backfill(db, dry_run=True, product_id=None)`，断言报告四类计数正确且 dry-run 后数据库未变。
- [ ] **Step 2: 跑红**
- [ ] **Step 3: 实现**

```python
async def run_backfill(db, *, dry_run=True, product_id=None):
    """扫描 pending 单执行同步；dry_run 时不写库。返回四类清单。"""
    # 1) 取 pending PO（可选按 product_id 过滤：find_pending_po_ids_for_product）
    # 2) 逐单调 sync_purchase_order_items(db, po_id, dry_run=dry_run)
    # 3) aggregate：changed / added / removed(含 suspected_manual) / unresolved
```

CLI 用 `argparse` + `asyncio.run`，`--apply` 才写库；退出码 0；报告逐行 print。

- [ ] **Step 4: 跑绿**
- [ ] **Step 5: 提交**

```bash
git add scripts/sync_pending_po_items.py fastapi_app/tests/services/test_sync_backfill_script.py
git commit -m "feat(purchase): pending 采购单 BOM 校正脚本（dry-run/apply）"
```

---

### Task 9: 前端版本字段、409 提示与两页一致性扩展

**Files:**
- Modify: `frontend-vite/src/api/purchase.ts`（`saveFactoryEdits` 增参）
- Modify: `frontend-vite/src/views/purchase/composables/useSummaryModal.ts`（存/传 `items_versions`；409 处理）
- Modify: `frontend-vite/src/views/purchase/components/OrderDetailModal.vue`（单价保存带 `items_version`）
- Modify: `frontend-vite/src/test/supplierQtyMatchesFactory.test.ts`（扩展拆行数据形态）
- Create: `frontend-vite/src/test/summaryVersionConflict.test.ts`

**Interfaces:**
- Consumes: Task 6 响应 `items_versions`、请求字段 `items_versions` / `items_version`。
- Produces: `saveFactoryEdits(edits, spareRate?, orderIds?, itemsVersions?)`；409 → toast + 重新 `openSummary(orderIds)`。

- [ ] **Step 1: 写失败测试**

```ts
it('保存时携带 items_versions；409 时提示并刷新', async () => {
  purchaseApi.saveFactoryEdits.mockRejectedValue({ response: { status: 409 } })
  const m = useSummaryModal()
  await m.openSummary([1])
  await expect(m.saveFactoryEdits()).rejects.toBeTruthy()
  expect(toast.warning).toHaveBeenCalledWith(expect.stringContaining('BOM 已更新'))
})
```

- [ ] **Step 2: 跑红**
- [ ] **Step 3: 实现**
  - `FactorySummaryData` 增加 `items_versions?: Record<string, number>`；`openSummary` 存入 `itemsVersions.value`。
  - `saveFactoryEdits` 发送 `items_versions: itemsVersions.value`；catch 中 `e?.response?.status === 409` → `toast.warning('BOM 已更新，采购明细已刷新，请重新编辑')` → `await openSummary(orderIds.value, orderTime.value)`。
  - `OrderDetailModal` 从订单对象读 `items_version`，`updateItemPrices(id, prices, itemsVersion)` 发送；409 同样提示并重新拉取订单。
- [ ] **Step 4: 跑绿**

Run: `TEMP=D:\erp_system\frontend-vite\.vitest-tmp npx vitest run src/test/summaryVersionConflict.test.ts src/test/supplierQtyMatchesFactory.test.ts`

- [ ] **Step 5: 提交**

```bash
git add frontend-vite/src/api/purchase.ts \
  frontend-vite/src/views/purchase/composables/useSummaryModal.ts \
  frontend-vite/src/views/purchase/components/OrderDetailModal.vue \
  frontend-vite/src/test/supplierQtyMatchesFactory.test.ts \
  frontend-vite/src/test/summaryVersionConflict.test.ts
git commit -m "feat(purchase): 汇总/订单保存带 items_version，409 提示刷新"
```

---

### Task 10: OpenAPI 快照、类型生成与全量门禁

**Files:**
- Modify: `frontend-vite/openapi.json`（导出）
- Modify: `frontend-vite/src/types/api.d.ts`（生成）
- Modify: `frontend-vite/src/types/index.ts`（如 schema 名变化需同步手写层）

- [ ] **Step 1: 重导快照**

```bash
python scripts/check_openapi_frontend_alignment.py --export frontend-vite/openapi.json
```

- [ ] **Step 2: 生成前端类型**

```bash
cd frontend-vite && npm run gen:api
```

- [ ] **Step 3: 全量验证（提权 pytest；前端全量）**

```bash
# 后端（提权）
.venv/Scripts/python.exe -m pytest -q
# 前端
cd frontend-vite
TEMP=D:\erp_system\frontend-vite\.vitest-tmp
npm run type-check
npm test
npm run lint
npm run check:api
npm run check:routes
npm run check:dto
npm run check:types
```

- [ ] **Step 4: 门禁**

```bash
python scripts/quality_gate.py
.venv/Scripts/python.exe -m ruff check fastapi_app tests fastapi_app/tests utils scripts
.venv/Scripts/python.exe -m mypy --config-file mypy.ini --no-native-parser
```

- [ ] **Step 5: 提交**

```bash
git add frontend-vite/openapi.json frontend-vite/src/types/api.d.ts
git commit -m "chore(purchase): 重导 OpenAPI 快照与前端生成类型"
```

---

### Task 11: 上线 backfill 执行（人工步骤，进 plan 但不在代码评审范围）

- [ ] 生产迁移：`alembic upgrade head`（确认 `pg_standalone_118` 生效）
- [ ] 部署后端新代码并重启 `erp-prod`（确认 PID CreationDate 更新）
- [ ] `python scripts/sync_pending_po_items.py --dry-run` → 人工复核四类清单（尤其 `removed/suspected_manual`）
- [ ] `python scripts/sync_pending_po_items.py --apply` → 再跑 dry-run 确认报告为空
- [ ] 打开 `/purchase` 汇总校验：工厂/供应商两页差异横幅为 0；`PO-2611-007` 绿色超柔拆成身体/脚底两行

---

## Self-Review

**Spec coverage:** 迁移(items_version)→T1；整单重建/继承/短路/审计/版本→T3；受影响单识别→T4；BOM 保存触发→T5；并发 409→T6；BOM 感知拆行→T7；backfill→T8/T11；前端→T9；OpenAPI/门禁→T10；仅 pending→T3/T4；删非 BOM 行→T3；无变化短路→T3。

**Placeholder scan:** 已逐条检查；T3/T4/T8 中省略号标注的夹具构造需按 `test_factory_summary_multisku._seed` 的既有写法展开，执行者先读该文件。

**Type consistency:** `build_expected_items(sku_lines, ctx, pid_name_map, customer_name)`（T2）在 T3 按同签名调用；`SyncResult` 字段在各任务一致；`items_versions` 类型为 `dict[int,int]`（请求）与 `dict[str,int]`（响应 JSON）。

**Review Focus 对应测试:** ①T6/T9 409；②T3 completed 跳过；③T3 盲盒同键多行；④T4 unresolved；⑤T5 撤销在同步前（`_run_bom_saved` 顺序测试）。
