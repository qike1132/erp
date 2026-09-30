# 备品按部位损耗率重算 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让备品数量从「各部位损耗率」派生（公式 A：瓶颈部位决定），使 `/beile-order` 的「生产数量 = 订单数量 + 备品数量」在多部位异损耗场景下准确。

**Architecture:** 新增一个只读查询 + 纯计算的服务模块 `purchase_order_spare.py`，暴露 `recompute_po_spare_from_item_rates(db, po_ids)`；把它挂到 `purchase_order_crud.py` 的三个写入点。备品落库位置不变（`purchase_order.spare_quantity` + `purchase_order_sku.spare_qty/spare_rate`），读路径（`/beile-order`）零改动。所有降级分支向「既有订单级口径」回退，保证旧数据与精简测试库上行为不变。

**Tech Stack:** Python 3 / FastAPI / SQLAlchemy 2.0 async / Alembic（本次**不需要**迁移）/ pytest + pytest-asyncio（`asyncio_mode=auto`，sqlite+aiosqlite 内存库）

**Spec:** `docs/purchase/备品数量按部位差异化损耗率计算方案.md`（提交 `d73523d8`）

## Global Constraints

- **零数据库迁移**：不加表、不加列、不改列类型。`purchase_order_item.loss_rate`（迁移 053）与 `purchase_order_sku.spare_qty/spare_rate`（迁移 047）已具备。
- **P0 零前端改动**：不修改 `frontend-vite/` 下任何文件。
- **响应契约不变**：`save_factory_summary_edits` 返回值键保持 `{'updated_count', 'spare_updated_count'}`；`/orders/factory-summary/save` 的请求/响应形状不变。
- **绝不抛错**：任何一步不可得（表缺失、方言差异、解析失败、BOM 变更）一律降级，`logger.warning` 记录，不得让写路径 500。
- **`filterwarnings = error`**：sqlite 测试库写入必须用 `int`/`float`，**禁止**传 `Decimal`（sqlite 方言不支持，会触发 SAWarning 而失败）。见 `pytest.ini:40`。
- **`asyncio_mode = auto`**：async 测试函数**不加** `@pytest.mark.asyncio` 装饰器。见 `pytest.ini:9`。
- **代码质量门禁**：`scripts/quality_gate.py` 的 `max_function_length=80`、`max_file_size=1600`（`pyproject.toml`）；只拦新增违规。提交前跑 `python scripts/quality_gate.py`、`ruff check .`、`mypy`。
- **提交纪律（重要）**：工作区存在**并发会话的未提交改动**（`frontend-vite/src/views/customer-order/**`、`fastapi_app/services/order/unified.py` 等）。**只 `git add` 本任务明确列出的文件**，**禁止** `git add -A` / `git add .` / `git commit -a`。提交信息写「为什么」，结尾附 `Co-Authored-By` 行。
- **本机 shell 特性**：Bash 工具存在 `_lc` 别名故障，`git`/`npm`/`cat`/`head` 等命令需以 `command git` 形式调用。
- **提交钩子**：`core.hooksPath = .githooks`，pre-commit 会跑密钥扫描；本机未装 `pre-commit`，第④层降级（暂存含 `.py` 时直接跑 `quality_gate.py`）。

## Review Focus

以下输入/失败模式是 spec 隐含但任务测试最容易漏掉的，最可能在生产上咬人，按可能性排序。每一行都必须在「拥有该代码的任务」里落到一条测试：

1. **精简测试库 / 迁移未跑**（Product 或 BOM 表不存在）→ 备品必须回退订单级口径，**不得抛错、不得把备品清零**（Task 2 覆盖）。
2. **SKU 快照存在但该单明细为空**，以及**明细存在但无 SKU 快照** → 双向降级，都不得让 `spare_quantity` 变成 0（Task 2 覆盖）。
3. **`order.spare_rate` 为 NULL 且部分行有率** → 有率的行照常参与 max，NULL 行按 0，**不得**因订单级率为空而把整单备品归 0（Task 2 覆盖）。
4. **率恰为 0（合法「已记录」值）与 NULL（未记录）语义不同** → 0 必须原样保留，不得被当成缺失（Task 2/3 覆盖）。
5. **幂等性** → 同一输入连续重算两次，结果逐字不变（Task 2 覆盖）。
6. **`sku.order_qty` 为 0 / NULL** → 该 SKU 备品 0 且不污染合计（Task 2 覆盖）。

---

### Task 1: BOM 物料键加载（命名口径复用生成路径）

**Files:**
- Create: `fastapi_app/services/purchase_order_spare.py`
- Test: `fastapi_app/tests/services/test_po_spare_from_part_rates.py`

**Interfaces:**
- Consumes: `fastapi_app.services.purchase_order_generate._MATERIAL_SPECS` / `_material_row`（**函数级延迟导入**，见下）；`fastapi_app.shared_models` 的 `ProductMaterial` / `ProductFabric` / `ProductAccessory`
- Produces:
  - `async def _load_bom_item_keys(db: AsyncSession, products: dict[int, str]) -> dict[int, set[tuple[str, str, str]]]` —— `{product_id: {(物料名, 规格, 单位)}}`
  - `def _item_key(item: PurchaseOrderItem) -> tuple[str, str, str]`

**为什么要复用 `_material_row` 而不是自己写一套命名规则**：采购明细的 `material_name` 是生成时按 `_MATERIAL_SPECS` 算出来的（填充类 = `产品名 + '-填充物'`、面料取 `fabric_name` 或 `'面料'`、配件取 `accessory_name` 或 `'配件'`，单位各有默认值）。若本模块另写一套，任何一侧改动都会静默失配。**必须走同一函数**。

**循环导入的处理**：`purchase_order_generate` 在模块级导入 `purchase_order_crud`，而本模块将被 `purchase_order_crud` 导入，故 `_MATERIAL_SPECS` / `_material_row` 必须在**函数体内**延迟导入（本仓已有先例：`purchase_order_generate.py:278`、`beile.py` 的延迟导入）。

- [ ] **Step 1: 写失败测试**

创建 `fastapi_app/tests/services/test_po_spare_from_part_rates.py`：

```python
"""备品按部位损耗率重算（公式 A：瓶颈部位决定）回归测试。

口径见 docs/purchase/备品数量按部位差异化损耗率计算方案.md。
核心不变量：备品 = Σ_SKU ceil(SKU订单数量 × max(该SKU各部位行损耗率)‰)。
降级不变量：任何数据不可得时回退既有订单级口径，绝不抛错、绝不清零。
"""
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from fastapi_app.services.purchase_order_spare import _load_bom_item_keys
from fastapi_app.shared_models import (
    Base,
    MaterialRegistration,
    MaterialRegistrationItem,
    ModificationLog,
    Product,
    ProductAccessory,
    ProductFabric,
    ProductMaterial,
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseOrderSku,
)

_XIAOTU = '兔子公仔'

# 全部用例共用的建表清单：Task 4 的完成路径会写 MaterialRegistration /
# MaterialRegistrationItem / ModificationLog，故一并建出（对 Task 1-3 无害）。
_TABLES = [
    Product.__table__, ProductFabric.__table__, ProductMaterial.__table__,
    ProductAccessory.__table__, PurchaseOrder.__table__,
    PurchaseOrderItem.__table__, PurchaseOrderSku.__table__,
    MaterialRegistration.__table__, MaterialRegistrationItem.__table__,
    ModificationLog.__table__,
]


@pytest_asyncio.fixture
async def db():
    """真实模型的 sqlite 内存库会话。

    不建 Role / Supplier 等表亦可 —— sqlite 不校验 FK 目标是否存在，
    且本模块的 BOM 键加载不依赖角色名（按 role_id 全量读取，不区分作用域）。
    """
    engine = create_async_engine('sqlite+aiosqlite:///:memory:')
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=_TABLES))
    maker = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


async def _seed_product_with_bom(db: AsyncSession, pid: int = 9001) -> int:
    """一个产品 + 三类 BOM 各一行（口径见 _MATERIAL_SPECS）。"""
    db.add(Product(id=pid, name=_XIAOTU))
    db.add(ProductMaterial(
        id=pid * 10 + 1, product_id=pid, cotton_usage=10, specification='填充A', unit='克',
    ))
    db.add(ProductFabric(
        id=pid * 10 + 2, product_id=pid, fabric_name='对条头布',
        specification='S1', quantity=0.2, unit='米',
    ))
    db.add(ProductAccessory(
        id=pid * 10 + 3, product_id=pid, accessory_name='眼睛扣',
        specification='', quantity=2, unit='个',
    ))
    await db.commit()
    return pid


async def test_load_bom_item_keys_matches_generation_naming(db):
    """BOM 键必须与采购明细生成口径逐字一致（三类物料各一行）。"""
    session = db
    pid = await _seed_product_with_bom(session)

    keys = await _load_bom_item_keys(session, {pid: _XIAOTU})

    assert keys[pid] == {
        (f'{_XIAOTU}-填充物', '填充A', '克'),
        ('对条头布', 'S1', '米'),
        ('眼睛扣', '', '个'),
    }


async def test_load_bom_item_keys_empty_products_returns_empty(db):
    """无产品 → 空映射（不得发起查询、不得抛错）。"""
    assert await _load_bom_item_keys(db, {}) == {}


async def test_load_bom_item_keys_missing_tables_degrades(db):
    """BOM 表不可用 → 返回空映射并降级，绝不抛错。"""
    engine = create_async_engine('sqlite+aiosqlite:///:memory:')
    maker = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as bare:
        assert await _load_bom_item_keys(bare, {1: '不存在'}) == {}
    await engine.dispose()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest fastapi_app/tests/services/test_po_spare_from_part_rates.py -v`
Expected: FAIL —— `ModuleNotFoundError: No module named 'fastapi_app.services.purchase_order_spare'`

- [ ] **Step 3: 写最小实现**

创建 `fastapi_app/services/purchase_order_spare.py`：

```python
"""备品按部位损耗率重算（公式 A：瓶颈部位决定）。

公式与口径见 docs/purchase/备品数量按部位差异化损耗率计算方案.md：

    r_eff(SKU) = max{ 该 SKU 各部位行的 loss_rate }（NULL 行回退订单级 spare_rate）
    spare(SKU) = ceil(N_SKU × r_eff / 1000)
    spare(PO)  = Σ_SKU spare(SKU)

「部位」以采购明细行的粒度承载（一行布料 = 一个部位）——BOM 物料表没有部位字段，
故本模块按「该 SKU 的 BOM 物料集 → 匹配采购明细行」还原 SKU 的生效率集合。

**降级契约（任何一步不可得都不得抛错）**：
- SKU 快照表不可用        → 保持既有订单级口径 calc_spare_quantity(product_quantity, spare_rate)
- 产品/BOM 解析不出/无匹配 → 该 SKU 回退订单级 spare_rate
- 该单无 SKU 快照行        → 同上按订单级口径
"""
from __future__ import annotations

import logging
from collections import defaultdict

from sqlalchemy import or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.services.purchase_order_sku import po_sku_available
from fastapi_app.services.purchase_utils import calc_spare_quantity, normalize_spare_rate
from fastapi_app.shared_models import (
    Product,
    ProductAccessory,
    ProductFabric,
    ProductMaterial,
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseOrderSku,
)

logger = logging.getLogger(__name__)


def _item_key(item) -> tuple[str, str, str]:
    """采购明细行的「物料名 + 规格 + 单位」键，与 BOM 键同口径比对。"""
    return (item.material_name or '', item.specification or '', item.unit or '')


async def _load_bom_item_keys(
    db: AsyncSession, products: dict[int, str],
) -> dict[int, set[tuple[str, str, str]]]:
    """加载各产品的 BOM 物料键集合。

    Args:
        db: 异步会话。
        products: ``{product_id: 产品名}``（填充类物料名需要产品名拼接）。

    Returns:
        ``{product_id: {(物料名, 规格, 单位), ...}}``；读取失败时返回空 dict。

    命名口径**直接复用生成路径**的 ``_material_row``，避免两套规则静默失配。
    """
    if not products:
        return {}

    # 延迟导入：purchase_order_generate 在模块级导入 purchase_order_crud，
    # 而本模块被 purchase_order_crud 导入 —— 函数级导入解除循环依赖。
    from fastapi_app.services.purchase_order_generate import _MATERIAL_SPECS, _material_row

    pids = list(products)
    try:
        # savepoint 隔离：PG 下语句失败会中止事务，需回滚到保存点后继续
        async with db.begin_nested():
            filling = (await db.execute(
                select(ProductMaterial).where(ProductMaterial.product_id.in_(pids))
            )).scalars().all()
            fabrics = (await db.execute(
                select(ProductFabric).where(ProductFabric.product_id.in_(pids))
            )).scalars().all()
            accessories = (await db.execute(
                select(ProductAccessory).where(ProductAccessory.product_id.in_(pids))
            )).scalars().all()
    except SQLAlchemyError:
        logger.warning('BOM 读取失败，备品重算降级为订单级口径', exc_info=True)
        return {}

    rows_by_category = {
        'filling': filling, 'fabric': fabrics, 'accessory': accessories,
    }
    keys: dict[int, set[tuple[str, str, str]]] = defaultdict(set)
    for spec in _MATERIAL_SPECS:
        for row in rows_by_category[spec.category]:
            product_name = products.get(row.product_id)
            if not product_name:
                continue
            # qty 传 0：本处只取物料名/规格/单位，数量不参与
            material = _material_row(spec, row, 0, product_name, '', '')
            keys[row.product_id].add(
                (material['material_name'], material['specification'], material['unit'])
            )
    return dict(keys)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest fastapi_app/tests/services/test_po_spare_from_part_rates.py -v`
Expected: PASS（3 个用例）

- [ ] **Step 5: 提交**

```bash
command git add fastapi_app/services/purchase_order_spare.py fastapi_app/tests/services/test_po_spare_from_part_rates.py
command git commit -m "feat(purchase): 备品重算模块——BOM 物料键加载（复用生成路径命名口径）" -m "备品要按「各部位损耗率」重算，前提是把 SKU 的 BOM 物料映射到采购明细行。命名口径直接调用生成路径的 _material_row（填充类=产品名+'-填充物' 等），避免另写一套规则后静默失配。BOM 读取失败时降级为空映射并告警，不抛错。" -m "Co-Authored-By: Claude Haiku 4.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: 备品重算主函数（含全部降级分支）

**Files:**
- Modify: `fastapi_app/services/purchase_order_spare.py`（追加两个函数）
- Test: `fastapi_app/tests/services/test_po_spare_from_part_rates.py`（追加用例）

**Interfaces:**
- Consumes: Task 1 的 `_load_bom_item_keys`、`_item_key`；`calc_spare_quantity(qty, rate) -> int`、`normalize_spare_rate(rate) -> float | None`（`purchase_utils.py:45`、`:74`）；`po_sku_available(db) -> bool`（`purchase_order_sku.py:90`）
- Produces:
  - `async def _resolve_products(db, skus) -> tuple[dict, dict, dict]` —— 返回 `(by_barcode, by_name, name_by_pid)`：前两者把 SKU 快照解析到 `product_id`（条码优先、名称回退），第三者是 `{product_id: 产品名}`（填充类物料名需要产品名参与拼接）
  - `def _effective_rate(matched_items, keys, order_rate) -> float` —— 部位生效率；无匹配行时回退订单级率
  - `async def recompute_po_spare_from_item_rates(db: AsyncSession, po_ids) -> int` —— **后续任务唯一入口**，返回被处理的采购单数

- [ ] **Step 1: 写失败测试**

在测试文件末尾追加（同时在**文件顶部 import 区**补 `from sqlalchemy import select`）：

```python
from sqlalchemy import select

from fastapi_app.services.purchase_order_spare import recompute_po_spare_from_item_rates

_H_TIAO = ('对条头布', 'S1', '米')
_H_SU = ('素色身布', 'S2', '米')


async def _seed_product_two_fabrics(db: AsyncSession, pid: int = 9100) -> int:
    """两部位产品：对条头布 + 素色身布（同一默认 BOM 作用域）。"""
    db.add(Product(id=pid, name=_XIAOTU))
    db.add(ProductFabric(
        id=pid * 10 + 1, product_id=pid, fabric_name='对条头布',
        specification='S1', quantity=0.2, unit='米',
    ))
    db.add(ProductFabric(
        id=pid * 10 + 2, product_id=pid, fabric_name='素色身布',
        specification='S2', quantity=0.8, unit='米',
    ))
    await db.commit()
    return pid


async def _seed_po(
    db: AsyncSession, po_id: int, *, product_quantity: float,
    spare_rate: float | None = None, item_rates: dict | None = None,
    skus: list[dict] | None = None, items: list[dict] | None = None,
) -> int:
    """构造一张采购单 + 明细 +（可选）逐 SKU 快照。

    item_rates 形如 ``{('对条头布', 'S1', '米'): 30}``；值 None 表示该行未配率。
    使用 int/float 写入（filterwarnings=error 下 Decimal 会失败）。
    """
    db.add(PurchaseOrder(
        id=po_id, order_no=f'SP-{po_id}', customer_name='客户A',
        product_name=_XIAOTU, product_quantity=product_quantity,
        supplier_name='供应商甲', spare_rate=spare_rate,
    ))
    rows = items if items is not None else [
        {'material_name': k[0], 'specification': k[1], 'unit': k[2], 'rate': v}
        for k, v in (item_rates or {}).items()
    ]
    for i, row in enumerate(rows, start=1):
        db.add(PurchaseOrderItem(
            id=po_id * 10 + i, order_id=po_id,
            material_name=row['material_name'], specification=row['specification'],
            unit=row['unit'], quantity=100, loss_rate=row.get('rate'),
        ))
    for i, sku in enumerate(skus or [], start=1):
        db.add(PurchaseOrderSku(
            id=po_id * 100 + i, po_id=po_id,
            product_name=sku['product_name'], product_barcode=sku.get('barcode'),
            order_qty=sku['order_qty'], source_order_id=sku.get('source_order_id', 1),
            source_record_type='order',
        ))
    await db.commit()
    return po_id


async def _po_spare(db: AsyncSession, po_id: int) -> tuple[float | None, list]:
    """读回 (主表备品, [(sku备品, sku率), ...])。"""
    order = await db.get(PurchaseOrder, po_id)
    rows = (await db.execute(
        select(PurchaseOrderSku).where(PurchaseOrderSku.po_id == po_id)
        .order_by(PurchaseOrderSku.id)
    )).scalars().all()
    return order.spare_quantity, [(r.spare_qty, r.spare_rate) for r in rows]


async def test_spare_uses_max_part_rate(db):
    """单 SKU 两部位 30/10‰、N=1000 → 备品 30（瓶颈部位决定，不是 10、不是 40）。"""
    session = db
    await _seed_product_two_fabrics(session)
    await _seed_po(
        session, 7001, product_quantity=1000,
        item_rates={_H_TIAO: 30, _H_SU: 10},
        skus=[{'product_name': _XIAOTU, 'order_qty': 1000}],
    )

    assert await recompute_po_spare_from_item_rates(session, [7001]) == 1

    spare, sku_rows = await _po_spare(session, 7001)
    assert float(spare) == 30
    assert sku_rows == [(30, 30)]


async def test_uniform_rate_matches_legacy_behavior(db):
    """【兼容锚】单 SKU 两部位同率 5‰、N=1000 → 备品 1，与改动前逐字一致。

    这是「上线无跳变」的证明：全行同率时 max = R，结果等于旧口径
    ceil(N × R/1000)。
    """
    session = db
    await _seed_product_two_fabrics(session)
    await _seed_po(
        session, 7020, product_quantity=1000,
        item_rates={_H_TIAO: 5, _H_SU: 5},
        skus=[{'product_name': _XIAOTU, 'order_qty': 1000}],
    )

    await recompute_po_spare_from_item_rates(session, [7020])

    spare, _ = await _po_spare(session, 7020)
    assert float(spare) == 1  # ceil(1000 × 5/1000)


async def test_spare_is_per_sku_then_summed(db):
    """多 SKU：各自按自身部位 max，逐 SKU ceil 后求和（不是先求和再 ceil）。"""
    session = db
    await _seed_product_two_fabrics(session)
    await _seed_po(
        session, 7002, product_quantity=100,
        item_rates={_H_TIAO: 30, _H_SU: 10},
        skus=[
            {'product_name': _XIAOTU, 'order_qty': 50},
            {'product_name': _XIAOTU, 'order_qty': 50},
        ],
    )

    await recompute_po_spare_from_item_rates(session, [7002])

    spare, sku_rows = await _po_spare(session, 7002)
    # 每个 SKU: ceil(50 × 30/1000) = ceil(1.5) = 2 → 合计 4（若先求和再 ceil 则为 3）
    assert [int(r[0]) for r in sku_rows] == [2, 2]
    assert float(spare) == 4


async def test_null_item_rate_falls_back_to_order_rate(db):
    """订单级率 20、头布行显式 NULL → 该行按 20 参与 max，结果 20。"""
    session = db
    await _seed_product_two_fabrics(session)
    await _seed_po(
        session, 7003, product_quantity=1000, spare_rate=20,
        item_rates={_H_TIAO: None, ('素色身布', 'S2', '米'): 10},
        skus=[{'product_name': _XIAOTU, 'order_qty': 1000}],
    )

    await recompute_po_spare_from_item_rates(session, [7003])

    spare, _ = await _po_spare(session, 7003)
    assert float(spare) == 20


async def test_order_rate_null_keeps_item_rates(db):
    """订单级率为 NULL、部分行有率 → 有率的行照常生效，备品不得归 0。"""
    session = db
    await _seed_product_two_fabrics(session)
    await _seed_po(
        session, 7004, product_quantity=1000, spare_rate=None,
        item_rates={_H_TIAO: 30, ('素色身布', 'S2', '米'): None},
        skus=[{'product_name': _XIAOTU, 'order_qty': 1000}],
    )

    await recompute_po_spare_from_item_rates(session, [7004])

    spare, _ = await _po_spare(session, 7004)
    assert float(spare) == 30


async def test_all_rates_absent_gives_zero(db):
    """行全 NULL + 订单级 NULL → 备品 0（等价今天「从未设率」的单）。"""
    session = db
    await _seed_product_two_fabrics(session)
    await _seed_po(
        session, 7005, product_quantity=1000, spare_rate=None,
        item_rates={_H_TIAO: None}, skus=[{'product_name': _XIAOTU, 'order_qty': 1000}],
    )

    await recompute_po_spare_from_item_rates(session, [7005])

    spare, sku_rows = await _po_spare(session, 7005)
    assert float(spare) == 0
    assert sku_rows == [(0, 0.0)]


async def test_zero_rate_is_recorded_not_missing(db):
    """率恰为 0 是合法「已记录」值：0 原样写回，不得变 NULL。"""
    session = db
    await _seed_product_two_fabrics(session)
    await _seed_po(
        session, 7006, product_quantity=1000, spare_rate=0,
        item_rates={_H_TIAO: 0}, skus=[{'product_name': _XIAOTU, 'order_qty': 1000}],
    )

    await recompute_po_spare_from_item_rates(session, [7006])

    spare, sku_rows = await _po_spare(session, 7006)
    assert float(spare) == 0
    assert sku_rows[0][1] == 0


async def test_rate_above_thousand_is_clamped(db):
    """率 > 1000 截断为 1000 → 备品 = N。"""
    session = db
    await _seed_product_two_fabrics(session)
    await _seed_po(
        session, 7007, product_quantity=100,
        item_rates={_H_TIAO: 5000}, skus=[{'product_name': _XIAOTU, 'order_qty': 100}],
    )

    await recompute_po_spare_from_item_rates(session, [7007])

    spare, _ = await _po_spare(session, 7007)
    assert float(spare) == 100


async def test_illegal_negative_rate_does_not_poison_max(db):
    """非法负率按 0 处理，不得把合规部位的率拉低或令整单备品归 0。"""
    session = db
    await _seed_product_two_fabrics(session)
    await _seed_po(
        session, 7021, product_quantity=1000,
        item_rates={_H_TIAO: 30, _H_SU: -5},
        skus=[{'product_name': _XIAOTU, 'order_qty': 1000}],
    )

    await recompute_po_spare_from_item_rates(session, [7021])

    spare, _ = await _po_spare(session, 7021)
    assert float(spare) == 30


async def test_zero_or_null_sku_qty_contributes_zero(db):
    """sku.order_qty 为 0 / NULL → 该 SKU 备品 0，且不污染合计。"""
    session = db
    await _seed_product_two_fabrics(session)
    await _seed_po(
        session, 7008, product_quantity=1000,
        item_rates={_H_TIAO: 30},
        skus=[
            {'product_name': _XIAOTU, 'order_qty': 0},
            {'product_name': _XIAOTU, 'order_qty': None},
            {'product_name': _XIAOTU, 'order_qty': 1000},
        ],
    )

    await recompute_po_spare_from_item_rates(session, [7008])

    spare, sku_rows = await _po_spare(session, 7008)
    assert [int(r[0] or 0) for r in sku_rows] == [0, 0, 30]
    assert float(spare) == 30


async def test_unresolvable_sku_degrades_to_order_rate(db):
    """SKU 产品名/条码都对不上产品 → 降级为该单订单级率，不抛错。"""
    session = db
    await _seed_product_two_fabrics(session)
    await _seed_po(
        session, 7009, product_quantity=1000, spare_rate=15,
        item_rates={_H_TIAO: 30},
        skus=[{'product_name': '查无此产品', 'order_qty': 1000}],
    )

    await recompute_po_spare_from_item_rates(session, [7009])

    spare, _ = await _po_spare(session, 7009)
    assert float(spare) == 15


async def test_bom_changed_no_match_degrades_to_order_rate(db):
    """产品 BOM 已改名致匹配为空 → 降级为该单订单级率，不抛错。"""
    session = db
    await _seed_product_two_fabrics(session)  # BOM 里没有「已停产布料」
    await _seed_po(
        session, 7010, product_quantity=1000, spare_rate=15,
        item_rates={('已停产布料', 'X', '米'): 30},
        skus=[{'product_name': _XIAOTU, 'order_qty': 1000}],
    )

    await recompute_po_spare_from_item_rates(session, [7010])

    spare, _ = await _po_spare(session, 7010)
    assert float(spare) == 15


async def test_no_sku_rows_falls_back_to_order_level(db):
    """明细有率但无 SKU 快照 → 保持既有订单级口径（零回归）。"""
    session = db
    await _seed_product_two_fabrics(session)
    await _seed_po(
        session, 7011, product_quantity=1000, spare_rate=5,
        item_rates={_H_TIAO: 30}, skus=[],
    )

    await recompute_po_spare_from_item_rates(session, [7011])

    spare, sku_rows = await _po_spare(session, 7011)
    assert float(spare) == 5  # ceil(1000 × 5/1000)，与旧行为一致
    assert sku_rows == []


async def test_empty_items_with_sku_rows_gives_zero(db):
    """SKU 快照存在但该单明细为空 → 无匹配 → 回退订单级率（NULL 则 0），不抛错。"""
    session = db
    await _seed_product_two_fabrics(session)
    await _seed_po(
        session, 7012, product_quantity=1000, spare_rate=None,
        items=[], skus=[{'product_name': _XIAOTU, 'order_qty': 1000}],
    )

    await recompute_po_spare_from_item_rates(session, [7012])

    spare, _ = await _po_spare(session, 7012)
    assert float(spare) == 0


async def test_recompute_is_idempotent(db):
    """同一输入连续重算两次，结果逐字不变。"""
    session = db
    await _seed_product_two_fabrics(session)
    await _seed_po(
        session, 7013, product_quantity=1000,
        item_rates={_H_TIAO: 30, ('素色身布', 'S2', '米'): 10},
        skus=[{'product_name': _XIAOTU, 'order_qty': 1000}],
    )

    await recompute_po_spare_from_item_rates(session, [7013])
    first = await _po_spare(session, 7013)
    await recompute_po_spare_from_item_rates(session, [7013])
    second = await _po_spare(session, 7013)

    assert first == second


async def test_empty_po_ids_is_noop(db):
    """空入参 → 返回 0，不抛错。"""
    assert await recompute_po_spare_from_item_rates(db, []) == 0
    assert await recompute_po_spare_from_item_rates(db, None) == 0


async def test_sku_table_unavailable_keeps_order_level(db, monkeypatch):
    """SKU 快照表不可用 → 回退订单级口径，不抛错、不清零。"""
    session = db
    await _seed_product_two_fabrics(session)
    await _seed_po(
        session, 7100, product_quantity=1000, spare_rate=5,
        item_rates={_H_TIAO: 30}, skus=[{'product_name': _XIAOTU, 'order_qty': 1000}],
    )

    async def _unavailable(_db):
        return False

    monkeypatch.setattr(
        'fastapi_app.services.purchase_order_spare.po_sku_available', _unavailable,
    )

    assert await recompute_po_spare_from_item_rates(session, [7100]) == 1
    assert float((await session.get(PurchaseOrder, 7100)).spare_quantity) == 5


@pytest_asyncio.fixture
async def db_recording():
    """带 SQL 语句记录器的会话（性能护栏专用，仿 test_factory_order_summary_spare_rate）。"""
    engine = create_async_engine('sqlite+aiosqlite:///:memory:')
    statements: list[str] = []

    @event.listens_for(engine.sync_engine, 'before_cursor_execute')
    def _record(_conn, _cursor, statement, _params, _context, _many):  # pragma: no cover
        statements.append(statement)

    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=_TABLES))
    maker = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        yield session, statements
    await engine.dispose()


async def test_query_count_is_bounded(db_recording):
    """性能护栏：**读查询**数与 SKU 行数无关，不得随行数线性增长（防 N+1）。

    只比对 SELECT 语句数：写回语句（UPDATE）本就随行数增长，属正常，不参与判据。
    实现为固定几条批量读（主表 + 明细 + SKU + 产品 + 三类 BOM），与单量无关。
    """
    session, statements = db_recording
    await _seed_product_two_fabrics(session)
    await _seed_po(
        session, 7110, product_quantity=1000,
        item_rates={_H_TIAO: 30, _H_SU: 10},
        skus=[{'product_name': _XIAOTU, 'order_qty': 1000}],
    )

    statements.clear()
    await recompute_po_spare_from_item_rates(session, [7110])
    reads_one_sku = [s for s in statements if s.lstrip().lower().startswith('select')]

    await _seed_po(
        session, 7111, product_quantity=3000,
        item_rates={_H_TIAO: 30, _H_SU: 10},
        skus=[
            {'product_name': _XIAOTU, 'order_qty': 1000},
            {'product_name': _XIAOTU, 'order_qty': 1000},
            {'product_name': _XIAOTU, 'order_qty': 1000},
        ],
    )
    statements.clear()
    await recompute_po_spare_from_item_rates(session, [7111])
    reads_three_skus = [s for s in statements if s.lstrip().lower().startswith('select')]

    assert len(reads_one_sku) == len(reads_three_skus), (
        f'读查询数随 SKU 行数增长（1 行 {len(reads_one_sku)} vs 3 行 '
        f'{len(reads_three_skus)}），疑似 N+1'
    )
    assert len(reads_one_sku) <= 10, f'重算读查询数异常偏多（{len(reads_one_sku)} 条）'

```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest fastapi_app/tests/services/test_po_spare_from_part_rates.py -v -k recompute or spare`
Expected: FAIL —— `ImportError: cannot import name 'recompute_po_spare_from_item_rates'`

- [ ] **Step 3: 写最小实现**

在 `purchase_order_spare.py` 末尾追加：

```python
async def _resolve_products(db: AsyncSession, skus) -> tuple[dict, dict, dict]:
    """按 SKU 快照解析产品：条码优先、名称回退（``product.name`` 全局唯一）。

    Returns:
        ``(by_barcode, by_name, name_by_pid)``；任何查询失败返回三个空 dict。
    """
    names = {(s.product_name or '').strip() for s in skus if s.product_name}
    barcodes = {(s.product_barcode or '').strip() for s in skus if s.product_barcode}
    clauses = []
    if names:
        clauses.append(Product.name.in_(names))
    if barcodes:
        clauses.append(Product.barcode.in_(barcodes))
    if not clauses:
        return {}, {}, {}
    try:
        async with db.begin_nested():
            rows = (await db.execute(
                select(Product.id, Product.name, Product.barcode).where(or_(*clauses))
            )).all()
    except SQLAlchemyError:
        logger.warning('产品解析失败，备品重算降级为订单级口径', exc_info=True)
        return {}, {}, {}
    by_barcode = {r.barcode: r.id for r in rows if r.barcode}
    by_name = {r.name: r.id for r in rows if r.name}
    name_by_pid = {r.id: r.name for r in rows if r.name}
    return by_barcode, by_name, name_by_pid


def _effective_rate(matched_items, keys, order_rate: float | None) -> float:
    """部位生效率 = max(匹配行的率)；无匹配则回退订单级率。"""
    matched = [it for it in matched_items if _item_key(it) in keys] if keys else []
    if not matched:
        return normalize_spare_rate(order_rate) or 0.0
    candidates = [
        it.loss_rate if it.loss_rate is not None else order_rate for it in matched
    ]
    # normalize_spare_rate(None) → None（视为「无值」，不参与 max）
    norm = [r for r in (normalize_spare_rate(c) for c in candidates) if r is not None]
    return max(norm) if norm else 0.0


async def recompute_po_spare_from_item_rates(db: AsyncSession, po_ids) -> int:
    """按「部位率 max」重算所涉采购单的备品（公式 A）。返回被处理的采购单数。

    写入 ``purchase_order.spare_quantity``（= Σ 逐 SKU 备品）与
    ``purchase_order_sku.spare_qty / spare_rate``。

    降级链（任一环节不可得即回退，绝不抛错）：
    1. SKU 快照表不可用      → 保持既有订单级口径；
    2. 该单无 SKU 快照行      → 同上；
    3. 产品/BOM 解析不出或无匹配行 → 该 SKU 回退订单级 ``spare_rate``。
    """
    ids = [i for i in dict.fromkeys(po_ids or []) if i]
    if not ids:
        return 0
    orders = (await db.execute(
        select(PurchaseOrder).where(PurchaseOrder.id.in_(ids))
    )).scalars().all()
    if not orders:
        return 0

    if not await po_sku_available(db):
        for order in orders:
            order.spare_quantity = calc_spare_quantity(order.product_quantity, order.spare_rate)
        return len(orders)

    items_by_po: dict[int, list] = defaultdict(list)
    for item in (await db.execute(
        select(PurchaseOrderItem).where(PurchaseOrderItem.order_id.in_(ids))
    )).scalars().all():
        items_by_po[item.order_id].append(item)
    skus_by_po: dict[int, list] = defaultdict(list)
    for sku in (await db.execute(
        select(PurchaseOrderSku).where(PurchaseOrderSku.po_id.in_(ids))
    )).scalars().all():
        skus_by_po[sku.po_id].append(sku)

    all_skus = [s for rows in skus_by_po.values() for s in rows]
    by_barcode, by_name, name_by_pid = await _resolve_products(db, all_skus)
    keys_by_pid = await _load_bom_item_keys(db, name_by_pid)

    for order in orders:
        skus = skus_by_po.get(order.id) or []
        if not skus:
            # 无逐 SKU 快照：保持既有订单级口径（零回归）
            order.spare_quantity = calc_spare_quantity(order.product_quantity, order.spare_rate)
            continue
        total = 0
        for sku in skus:
            pid = by_barcode.get(sku.product_barcode or '') or by_name.get(
                (sku.product_name or '').strip()
            )
            rate = _effective_rate(
                items_by_po.get(order.id) or [], keys_by_pid.get(pid) or set(), order.spare_rate,
            )
            sku.spare_rate = rate
            sku.spare_qty = calc_spare_quantity(sku.order_qty, rate)
            total += int(sku.spare_qty or 0)
        order.spare_quantity = total
    return len(orders)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest fastapi_app/tests/services/test_po_spare_from_part_rates.py -v`
Expected: PASS（全部用例）

- [ ] **Step 5: 跑质量门禁与类型检查**

Run: `python scripts/quality_gate.py && ruff check fastapi_app/services/purchase_order_spare.py && mypy fastapi_app/services/purchase_order_spare.py`
Expected: 无新增违规；无 lint/类型错误

- [ ] **Step 6: 提交**

```bash
command git add fastapi_app/services/purchase_order_spare.py fastapi_app/tests/services/test_po_spare_from_part_rates.py
command git commit -m "feat(purchase): 备品按部位损耗率重算——公式 A 瓶颈部位决定 + 全套降级链" -m "备品从「订单级单率」改为「各 SKU 部位率 max」派生：逐 SKU ceil 后求和，与 /beile-order 既有逐 SKU 口径同源。降级链覆盖 SKU 表不可用、该单无快照、产品/BOM 解析不出三种情况，一律回退既有订单级口径——保证旧数据与精简库上行为逐字不变。0 与 NULL 语义严格区分（0 是合法已记录值）。" -m "Co-Authored-By: Claude Haiku 4.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: 挂载到汇总保存路径（修复核心缺陷）

**Files:**
- Modify: `fastapi_app/services/purchase_order_crud.py`（`_write_spare_rate_to_orders` 约 :285-307；`save_factory_summary_edits` 约 :413-476）
- Test: `fastapi_app/tests/services/test_po_spare_from_part_rates.py`（追加「保存路径」用例组）

**Interfaces:**
- Consumes: Task 2 的 `recompute_po_spare_from_item_rates(db, po_ids) -> int`
- Produces: 无新接口；`save_factory_summary_edits` 与原 `_write_spare_rate_to_orders` 的签名与返回键**保持不变**

**这是本次缺陷的修复点**：今天 `save_factory_summary_edits` 只在顶层 `spare_rate` 非 None 时才写备品；行率（`edits[].loss_rate`）落库后备品**一动不动**。修法是：编辑应用完毕后，对**本次涉及的全部采购单**（`involved_po_ids`，它已由 `it.order_id` 累积而来）无条件重算。注意当 `spare_rate is None` 时 `_write_spare_rate_to_orders` 会提前 return —— 所以重算**必须写在它的外面**，不能塞进去。

- [ ] **Step 1: 写失败测试**

在测试文件末尾追加：

```python
from fastapi_app.services.purchase_order_crud import save_factory_summary_edits


async def _seed_save_fixture(db: AsyncSession, po_id: int = 7200) -> dict:
    """保存路径用的采购单：两部位行 + 一条 SKU 快照，全部未配率。"""
    await _seed_product_two_fabrics(db)
    await _seed_po(
        db, po_id, product_quantity=1000, spare_rate=None,
        item_rates={_H_TIAO: None, _H_SU: None},
        skus=[{'product_name': _XIAOTU, 'order_qty': 1000}],
    )
    items = (await db.execute(
        select(PurchaseOrderItem).where(PurchaseOrderItem.order_id == po_id)
        .order_by(PurchaseOrderItem.id)
    )).scalars().all()
    return {'po_id': po_id, 'head_item_id': items[0].id, 'body_item_id': items[1].id}


async def test_row_rate_save_recomputes_spare(db):
    """【核心缺陷】只保存行率（spare_rate=None）也必须重算备品。

    旧行为：行率落库后备品一动不动，仍是上次的值（此处为 0）。
    新行为：备品 = ceil(1000 × 30/1000) = 30。
    """
    session = db
    fx = await _seed_save_fixture(session)

    await save_factory_summary_edits(
        session, [{'item_ids': [fx['head_item_id']], 'loss_rate': 30}], 'tester',
    )

    spare, sku_rows = await _po_spare(session, fx['po_id'])
    assert float(spare) == 30
    assert sku_rows == [(30, 30)]


async def test_row_rate_save_lower_rate_recomputes_down(db):
    """行率改小后备品必须跟着降：30 → 5 时备品 30 → 5。"""
    session = db
    fx = await _seed_save_fixture(session)
    await save_factory_summary_edits(
        session, [{'item_ids': [fx['head_item_id']], 'loss_rate': 30}], 'tester',
    )
    assert float((await _po_spare(session, fx['po_id']))[0]) == 30

    await save_factory_summary_edits(
        session, [{'item_ids': [fx['head_item_id']], 'loss_rate': 5}], 'tester',
    )

    spare, _ = await _po_spare(session, fx['po_id'])
    assert float(spare) == 5


async def test_top_rate_save_still_writes_and_recomputes(db):
    """顶层统一率路径（edits=[] + spare_rate）仍写率，且备品按部位率算。"""
    session = db
    fx = await _seed_save_fixture(session)

    res = await save_factory_summary_edits(session, [], 'tester', 30, [fx['po_id']])

    assert res['spare_updated_count'] == 1
    order = await session.get(PurchaseOrder, fx['po_id'])
    assert float(order.spare_rate) == 30
    assert float(order.spare_quantity) == 30


async def test_save_keeps_response_shape(db):
    """契约护栏：返回键必须仍是 updated_count + spare_updated_count。"""
    session = db
    fx = await _seed_save_fixture(session)

    res = await save_factory_summary_edits(
        session, [{'item_ids': [fx['head_item_id']], 'loss_rate': 30}], 'tester',
    )

    assert set(res.keys()) == {'updated_count', 'spare_updated_count'}


async def test_save_zero_rate_preserved(db):
    """通过保存路径写入 0 → 备品 0 且率写回 0（0 不是缺失）。"""
    session = db
    fx = await _seed_save_fixture(session)

    await save_factory_summary_edits(
        session, [{'item_ids': [fx['head_item_id']], 'loss_rate': 0}], 'tester',
    )

    spare, sku_rows = await _po_spare(session, fx['po_id'])
    assert float(spare) == 0
    assert sku_rows[0][1] == 0
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest fastapi_app/tests/services/test_po_spare_from_part_rates.py -v -k "row_rate or top_rate or response_shape or save_zero"`
Expected: FAIL —— `test_row_rate_save_recomputes_spare` 与 `test_row_rate_save_lower_rate_recomputes_down` 断言失败（备品仍为 0 / 30，未随行率变化）。`test_top_rate_save_still_writes_and_recomputes` 与 `test_save_keeps_response_shape` 应当**已经通过**（既有行为），这是回归锚。

- [ ] **Step 3: 写最小实现**

修改 `fastapi_app/services/purchase_order_crud.py`。

**3a. 顶部导入**（在 `from fastapi_app.services.purchase_order_sku import resync_po_sku_spare` 一行之后追加）：

```python
from fastapi_app.services.purchase_order_spare import recompute_po_spare_from_item_rates
```

**3b. `_write_spare_rate_to_orders` 末尾**——把逐 SKU 同率覆盖换成部位率重算。原代码（`:305-307`）：

```python
    # 逐 SKU 快照的备品按新率同步重算（保持逐 SKU 行与主表备品口径一致）
    await resync_po_sku_spare(db, applied_ids, spare_rate)
    return written
```

改为：

```python
    # 逐 SKU 备品由「部位率 max」重算（备品来源见 purchase_order_spare）。
    # 注意：_apply_spare_rate 刚写入的 spare_quantity 是订单级口径的临时值，
    # 由本次重算覆盖为逐 SKU 求和——重算是备品的最终写者。
    await recompute_po_spare_from_item_rates(db, applied_ids)
    return written
```

**3c. `save_factory_summary_edits` 末尾**（`:472-476`）：

```python
    # 编辑应用完毕后，再批量覆盖写所涉采购单的损耗率 / 备品（一次查询，无 N+1）
    spare_written = await _write_spare_rate_to_orders(db, involved_po_ids, spare_rate)

    # 【缺陷修复】行率（edits[].loss_rate）可能刚被改写：无论本次是否携带顶层
    # spare_rate，都要按「部位率 max」重算所涉采购单的备品。此前只在顶层
    # spare_rate 非 None 时才写备品，行率改动完全不触发重算 → /beile-order 的
    # 生产数量在多部位异损耗场景下失真。
    if involved_po_ids:
        await recompute_po_spare_from_item_rates(db, involved_po_ids)

    await db.flush()
    return {'updated_count': updated, 'spare_updated_count': spare_written}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest fastapi_app/tests/services/test_po_spare_from_part_rates.py -v`
Expected: PASS（全部用例）

- [ ] **Step 5: 跑既有回归，确认零回归**

Run: `python -m pytest fastapi_app/tests/services/test_purchase_order_sku.py fastapi_app/tests/services/test_qa_beile_adversarial.py fastapi_app/tests/test_purchase_center.py -v`
Expected: 全绿。`test_resync_po_sku_spare_*` 仍应通过（该函数保留未删）；`test_qa_save_factory_summary_edits_*` 仍应通过（降级链保证精简库不抛错）。

- [ ] **Step 6: 提交**

```bash
command git add fastapi_app/services/purchase_order_crud.py fastapi_app/tests/services/test_po_spare_from_part_rates.py
command git commit -m "fix(purchase): 部位损耗率落库后重算备品，修「生产数量」在多部位异损耗下失真" -m "根因：save_factory_summary_edits 只在顶层 spare_rate 非 None 时写备品，行率（edits[].loss_rate）落库后不触发任何重算，备品始终由订单级单率决定。改为编辑应用后对所涉采购单无条件按「部位率 max」重算；逐 SKU 同率覆盖（resync_po_sku_spare）被部位率重算取代，该函数暂留以兼容既有直接调用方。" -m "Co-Authored-By: Claude Haiku 4.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: 挂载到完成下单路径

**Files:**
- Modify: `fastapi_app/services/purchase_order_crud.py`（`complete_purchase_order` :344-347；`batch_complete_purchase_orders` :398-407）
- Test: `fastapi_app/tests/services/test_po_spare_from_part_rates.py`（追加「完成路径」用例）

**Interfaces:**
- Consumes: Task 2 的 `recompute_po_spare_from_item_rates`
- Produces: 无新接口；两个完成函数的签名与返回值保持不变

**口径说明（有意为之）**：仅在 `spare_rate is not None` 时重算——与今天的条件一致。行率未在本路径改动（行率的改动走 Task 3 的保存路径，那里已经重算），故此处无需要重算；保持条件不变是最保守的选择，避免「完成一张旧单时静默改变其备品」。

- [ ] **Step 1: 写失败测试**

在测试文件末尾追加：

```python
from fastapi_app.services.purchase_order_crud import (
    batch_complete_purchase_orders,
    complete_purchase_order,
)


async def _seed_completable(db: AsyncSession, po_id: int) -> int:
    """一张 pending 采购单：部位率已配（头 30、身 10），订单级率空缺。"""
    await _seed_product_two_fabrics(db)
    await _seed_po(
        db, po_id, product_quantity=1000, spare_rate=None,
        item_rates={_H_TIAO: 30, ('素色身布', 'S2', '米'): 10},
        skus=[{'product_name': _XIAOTU, 'order_qty': 1000}],
    )
    return po_id


async def test_complete_order_recomputes_spare_by_part_rates(db):
    """完成单张订单并携带统一率 5：备品仍应按部位率 max（30）算，而非 5。"""
    session = db
    po_id = await _seed_completable(session, 7300)

    await complete_purchase_order(session, po_id, 'tester', spare_rate=5)

    spare, sku_rows = await _po_spare(session, po_id)
    assert float(spare) == 30, '部位率存在时不得被顶层统一率覆盖'
    assert sku_rows == [(30, 30)]


async def test_batch_complete_recomputes_spare_by_part_rates(db):
    """批量完成路径同样按部位率 max 算备品。"""
    session = db
    await _seed_completable(session, 7310)
    await _seed_completable(session, 7311)

    res = await batch_complete_purchase_orders(session, [7310, 7311], 'tester', spare_rate=5)

    assert res['completed'] == 2
    for pid in (7310, 7311):
        spare, _ = await _po_spare(session, pid)
        assert float(spare) == 30
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest fastapi_app/tests/services/test_po_spare_from_part_rates.py -v -k complete`
Expected: FAIL —— 断言得到 5（顶层统一率的旧口径）而非 30

- [ ] **Step 3: 写最小实现**

**3a. `complete_purchase_order`**（原 `:343-347`）：

```python
    # 携带损耗率则覆盖写率；None 时保留该单已存值（PRD Q1）
    if spare_rate is not None:
        _apply_spare_rate(order, spare_rate)
        # 备品按「部位率 max」重算（顶层率只作 NULL 行的回退基线）
        await recompute_po_spare_from_item_rates(db, [order.id])
```

**3b. `batch_complete_purchase_orders`**（原 `:396-400` 循环内保持只收集 id，`:405-407` 改为）：

```python
    # 逐 SKU 备品按「部位率 max」批量重算（一次查询，无 N+1）
    if resync_ids:
        await recompute_po_spare_from_item_rates(db, resync_ids)
```

（循环体内的 `resync_ids.append(order.id)` 与 `_apply_spare_rate(order, spare_rate)` 保持不变。）

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest fastapi_app/tests/services/test_po_spare_from_part_rates.py -v -k complete`
Expected: PASS

- [ ] **Step 5: 删除已失效的导入**

`resync_po_sku_spare` 在 `purchase_order_crud.py` 中已无调用点（三个挂载点全部改为部位率重算）。**保留函数定义**（`purchase_order_sku.py:214`，其直接调用方测试 `test_purchase_order_sku.py:172-194` 仍在使用），但删除本文件里未使用的导入，避免 lint 报 F401。

Run: `ruff check fastapi_app/services/purchase_order_crud.py`
若报 `F401 'resync_po_sku_spare' imported but unused`，删除 `purchase_order_crud.py:20` 的该行导入，并在 `purchase_order_sku.py:214` 的 docstring 首行补一句：

```python
    """损耗率变更后按新率重算逐 SKU 备品（**已被 purchase_order_spare 的部位率重算取代**，
    保留以供直接调用方与既有测试使用）。
```

- [ ] **Step 6: 提交**

```bash
command git add fastapi_app/services/purchase_order_crud.py fastapi_app/tests/services/test_po_spare_from_part_rates.py
command git commit -m "fix(purchase): 完成下单路径的备品改按部位率重算" -m "complete / batch_complete 原先用顶层统一率覆盖逐 SKU 备品，会把部位率算出的结果打回单率口径。改为按「部位率 max」重算；顶层率仅作 NULL 行的回退基线。未携带 spare_rate 时不重算（与既有条件一致，避免完成旧单时静默改变备品）。" -m "Co-Authored-By: Claude Haiku 4.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: 全量门禁与零回归验证

**Files:**
- Modify: `docs/purchase/备品数量按部位差异化损耗率计算方案.md`（追加「实施状态」小节）
- 不改任何代码

- [ ] **Step 1: 后端全量回归**

Run: `python -m pytest -q`
Expected: 与改动前同一通过集合；**无新增失败**。若出现失败，先看错误类型：失败若来自 `tests/`（非 `fastapi_app/tests/`）中的 policy/env 差异类用例，属本机既有假信号，需逐个确认是否与本次改动相关。

- [ ] **Step 2: 后端质量门禁**

Run: `python scripts/quality_gate.py`
Expected: 通过（违规数不超过 `scripts/gate_baseline.json`）

Run: `ruff check .`
Expected: 无错误

Run: `mypy`
Expected: 无新增错误

- [ ] **Step 3: 前端零回归（本次未改前端，验证既有用例全绿）**

Run: `cd frontend-vite && npm test`
Expected: 全绿。重点确认 `useSummaryModal.groupLossRate` / `useSummaryModal.lossRateHardening` / `SummaryModal.multisku` / `QaSummaryModalLossRate.adversarial` / `BeileOrderTab.*` / `customerOrderCrossPageInvalidation` 均通过。

（若 `npm test` 因本机 `_lc` 别名故障报错，用 `command npm test`。）

- [ ] **Step 4: 端到端人工核对**

Run: `python -c "import asyncio,os;print('确认服务健康: 读取 logs/prod_runner.json 需 ready=true 且 frontend_ok=true')"`
Expected: 仅作提示——**本任务不做生产部署**。真正的端到端核对在生产环境按需进行：选一张多部位订单，在 `/purchase` 改部位率 → 确认 `/beile-order` 的「生产数量」= 订单数量 + 该 SKU 部位率 max 折件数。

- [ ] **Step 5: 文档同步**

在 `docs/purchase/备品数量按部位差异化损耗率计算方案.md` 的 `> 性质：**纯设计文档，不修改任何代码**` 一行之后插入：

```markdown
> **实施状态（2026-09-30）**：已实施。代码见 `fastapi_app/services/purchase_order_spare.py`
> 与 `purchase_order_crud.py` 的三个挂载点；测试见
> `fastapi_app/tests/services/test_po_spare_from_part_rates.py`。零迁移、零前端改动。
```

- [ ] **Step 6: 提交**

```bash
command git add docs/purchase/备品数量按部位差异化损耗率计算方案.md
command git commit -m "docs(purchase): 标记备品部位率计算方案已实施" -m "方案文档补实施状态与代码落点，便于后续追溯「设计 → 实现」对应关系。" -m "Co-Authored-By: Claude Haiku 4.5 (1M context) <noreply@anthropic.com>"
```

---

## 附录：本计划的关键判断与理由

| 判断 | 理由 |
| --- | --- |
| 公式取 max 而非求和/加权 | 备品是整件，短板决定；全行同率时与现行为逐字一致（无迁移跳变）；行业备品率 0.5-3% 落在毛绒 2-5% 惯例内。详见 spec §1.3 |
| 逐 SKU 独立 ceil 后求和 | 与 `/beile-order` 既有 `_rollup_sku_rows` 口径同源，避免「先求和再 ceil」的口径分裂 |
| 复用 `_material_row` 而非另写命名规则 | 采购明细的物料名由生成路径算出；两套规则必然漂移，且失效是静默的 |
| 函数级延迟导入 `purchase_order_generate` | `purchase_order_generate` 模块级导入 `purchase_order_crud`，硬导入会成环 |
| 降级改按「该单**全部明细** max」（原表述「降级一律回退订单级口径」**违反 spec §2.2/§4，已更正**） | 产品无法解析 / BOM 匹配为空时，回退到明细 max 永远给出有意义的数（NULL 行仍按订单级率兜底），而回退 NULL 顶层率会**静默产出 0**（终审 I1）。仅「SKU 快照表不可用」分支仍保持 `calc_spare_quantity(product_quantity, spare_rate)` 订单级口径（精简测试库 / 迁移未跑），保证零回归 |
| 完成路径仅在 `spare_rate is not None` 时重算 | 行率改动已在保存路径重算；此处收紧可避免「完成旧单时静默改变备品」 |
| `resync_po_sku_spare` 保留不删 | 其直接调用方测试仍在用；本仓明令「勿凭没被引用就删模块」（AGENTS.md §6） |
| 不实现「备品计入布料」联动 | spec §6 明确列为范围外旧账（各部位加放基数为订单量 N，非生产量 N+S） |
