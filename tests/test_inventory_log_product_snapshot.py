"""R1 回归：产品删除不得抹掉库存流水（迁移 073）

背景
----
``inventory_log.product_id`` 原为 ``ON DELETE CASCADE``，且
``product_service.delete_product`` 还会先显式 DELETE 一遍流水 —— 删产品 =
该产品全部库存流水永久消失，变动历史与审计能力凭空归零。三家主流开源 ERP
一致反着做：ERPNext 的 ``item_code`` 是软引用、InvenTree 明示「删 stock item
仍保留 tracking」、Odoo 的 move.line 不随产品删除消失。

修法（迁移 073 + product_service）：
- 外键改 ``ON DELETE SET NULL``；
- 流水行冗余 ``product_name`` / ``product_barcode`` 快照；
- ``delete_product`` 删除前把该产品名下**尚为 NULL** 的快照补齐，删除后产品标识
  仍可读。

本文件锁定：
1. 删产品后流水行仍在，product_id 置空、产品名/条码可从快照读出；
2. 已有快照不被覆盖（只补 NULL）；
3. 记账时序结存推导函数与 ``log_inventory_change`` 的字段透传；
4. 迁移 073 的结构不变量（幂等守卫、SET NULL、downgrade 顺序）。
"""
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fastapi_app.services import product_service
from fastapi_app.shared_models import InventoryLog, Product
from fastapi_app.utils import inventory_balance_bounds, log_inventory_change

_REPO_ROOT = Path(__file__).resolve().parents[1]
_MIGRATION = _REPO_ROOT / 'migrations' / 'versions' / 'pg_standalone_073_inventory_log_ledger_fields.py'


@pytest_asyncio.fixture
async def db(test_engine):
    """函数级会话 + 事务回滚隔离（复用会话级 test_engine）。"""
    factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False, autoflush=False,
    )
    async with factory() as session:
        async with session.begin() as transaction:
            yield session
            await transaction.rollback()


# ---------------------------------------------------------------------------
# 单元：结存推导与字段透传（不依赖数据库）
# ---------------------------------------------------------------------------

def test_inventory_balance_bounds_deduct_and_add():
    """结存 = 锁内写入口返回值反推：出库把前值推到更高，入库相反。"""
    assert inventory_balance_bounds(90, -10) == (100, 90)   # 出库 10 件
    assert inventory_balance_bounds(110, 10) == (100, 110)  # 入库 10 件
    assert inventory_balance_bounds(0, 5) == (-5, 0)        # 负数前值仍可表达（不夹取）


class _FakeSession:
    """只实现 .add()：log_inventory_change 的唯一会话契约。"""

    def __init__(self):
        self.added = []

    def add(self, obj):
        self.added.append(obj)


def test_log_inventory_change_passes_ledger_and_snapshot_fields():
    """操作人 / 前后结存 / 产品快照必须原样落到流水行上。"""
    db = _FakeSession()
    log_inventory_change(
        db, product_id=1, change_type='入库', change_quantity=5,
        related_id='9', note='n', customer='客户A',
        operator_id=77, quantity_before=10, quantity_after=15,
        product_name='测试产品', product_barcode='BC-1',
    )
    (entry,) = db.added
    assert isinstance(entry, InventoryLog)
    assert (entry.operator_id, entry.quantity_before, entry.quantity_after) == (77, 10, 15)
    assert (entry.product_name, entry.product_barcode) == ('测试产品', 'BC-1')


def test_log_inventory_change_defaults_keep_backward_compat():
    """不传新参数的旧调用点：全部留 NULL，不得报错。"""
    db = _FakeSession()
    log_inventory_change(db, product_id=1, change_type='出库', change_quantity=-1)
    (entry,) = db.added
    assert entry.operator_id is None
    assert entry.quantity_before is None and entry.quantity_after is None
    assert entry.product_name is None and entry.product_barcode is None


# ---------------------------------------------------------------------------
# 集成：删产品后历史仍在
# ---------------------------------------------------------------------------

def _make_product(name: str) -> Product:
    return Product(name=name, barcode=name, current_stock=0, initial_stock=0)


@pytest.mark.integration
async def test_delete_product_keeps_inventory_log_with_snapshot(db):
    """核心回归：删产品 → 流水保留、外键置空、产品名从快照可读。

    删除前该产品名下没有任何订单/备货/出货（否则会被既有守卫挡住），
    这正是「有流水但无单据」的场景（抵扣回滚、导入、生产等路径的产物）。
    """
    product = _make_product('R1-保留历史')
    db.add(product)
    await db.flush()

    # 模拟旧写点：只写 product_id，不带产品名快照
    db.add(InventoryLog(product_id=product.id, change_type='入库', change_quantity=7))
    await db.flush()

    await product_service.delete_product(db, product.id)
    await db.flush()

    assert await db.get(Product, product.id) is None, '产品应已删除'
    logs = (await db.execute(
        select(InventoryLog).where(InventoryLog.product_name == 'R1-保留历史')
    )).scalars().all()
    assert len(logs) == 1, '库存流水必须随产品删除而保留（此前被 CASCADE + 显式 DELETE 抹掉）'
    assert logs[0].product_id is None, 'product_id 应被外键置空而非级联删除行'
    assert logs[0].product_barcode == 'R1-保留历史'
    assert logs[0].change_quantity == 7, '历史数量不得被改动'


@pytest.mark.integration
async def test_delete_product_does_not_overwrite_existing_snapshot(db):
    """已有快照（写入时带出的真实产品名）不被删除时的补写覆盖。

    断言**只针对本用例造的两行**：``product_id IS NULL`` 是全局条件，别的用例用裸 SQL
    删产品会留下同样为 NULL 的孤儿行，按全表断言会被跨文件污染（2026-10-09 CI 实测：
    多出一行 ``(None, None)``）。按 id 取行同时仍然验证了外键 SET NULL 语义。
    """
    product = _make_product('R1-快照优先')
    db.add(product)
    await db.flush()

    kept = InventoryLog(
        product_id=product.id, change_type='入库', change_quantity=1,
        product_name='写入时快照名', product_barcode='BC-ORIG',
    )
    filled = InventoryLog(product_id=product.id, change_type='出库', change_quantity=-1)
    db.add(kept)
    db.add(filled)
    await db.flush()
    log_ids = [kept.id, filled.id]

    await product_service.delete_product(db, product.id)
    await db.flush()

    rows = (await db.execute(
        select(InventoryLog.product_id, InventoryLog.product_name, InventoryLog.product_barcode)
        .where(InventoryLog.id.in_(log_ids))
        .order_by(InventoryLog.id)
    )).all()
    assert rows == [
        (None, '写入时快照名', 'BC-ORIG'),
        (None, 'R1-快照优先', 'R1-快照优先'),
    ], '已有快照不得被覆盖；无快照行应补写产品名/条码；两行 product_id 均被外键置空'


# ---------------------------------------------------------------------------
# 迁移结构守卫（读源文件，不连库）
# ---------------------------------------------------------------------------

def _function_source(src: str, name: str) -> str:
    """取迁移中某个函数的源码片段。

    必须用 ast 取函数体：README/docstring 里会**引用** SQL 原文（例如本迁移的
    背景说明就写了 ``ON DELETE CASCADE``），文本级 index 会命中注释里的副本，
    得出与代码相反的结论——这正是 AGENTS.md §6 记录过的解析伪影。
    """
    import ast

    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            segment = ast.get_source_segment(src, node)
            assert segment, f'取不到 {name} 源码片段'
            return segment
    raise AssertionError(f'迁移中不存在函数 {name}')


def test_migration_073_is_idempotent_and_switches_fk_to_set_null():
    upgrade_src = _function_source(_MIGRATION.read_text(encoding='utf-8'), 'upgrade')

    # 幂等守卫：所有新增列/索引都必须带 IF NOT EXISTS
    assert 'ADD COLUMN IF NOT EXISTS operator_id' in upgrade_src
    assert 'ADD COLUMN IF NOT EXISTS quantity_before' in upgrade_src
    assert 'ADD COLUMN IF NOT EXISTS quantity_after' in upgrade_src
    assert 'ADD COLUMN IF NOT EXISTS product_name' in upgrade_src
    assert 'ADD COLUMN IF NOT EXISTS product_barcode' in upgrade_src
    assert 'CREATE INDEX IF NOT EXISTS ix_inventory_log_operator_id' in upgrade_src
    assert 'DROP CONSTRAINT IF EXISTS inventory_log_product_id_fkey' in upgrade_src

    # R1 核心：升级路径转 SET NULL，且升级路径里不得残留 CASCADE。
    # 锚点必须是**产品外键**那一句：operator_id 也是 SET NULL（指向 user），
    # 若只找 'ON DELETE SET NULL' 会命中 operator 那句，把顺序断言对错对象。
    product_fk_src = 'FOREIGN KEY (product_id) REFERENCES product(id) ON DELETE SET NULL'
    assert product_fk_src in upgrade_src
    assert 'ON DELETE CASCADE' not in upgrade_src, '升级路径必须彻底离开 CASCADE'
    product_fk_at = upgrade_src.index(product_fk_src)

    # 先放开 NOT NULL 再换外键（顺序错会在 SET NULL 语义下短暂违反 NOT NULL）
    assert upgrade_src.index('ALTER COLUMN product_id DROP NOT NULL') < product_fk_at
    # 回填必须在换外键之前（若先换，NULL 行已无法关联 product）
    assert upgrade_src.index('SET product_name = p.name') < product_fk_at
    # 旧外键必须先解绑再重建，否则 ADD CONSTRAINT 撞名失败
    assert upgrade_src.index('DROP CONSTRAINT IF EXISTS inventory_log_product_id_fkey') < product_fk_at

    # 产品名快照回填（对现存产品是事实数据）；结存/操作人不回填（无据可推）
    assert 'quantity_before =' not in upgrade_src.replace('quantity_before IS', '')
    assert 'operator_id =' not in upgrade_src


def test_migration_073_downgrade_clears_orphans_before_restoring_not_null():
    """降级先删 product_id 为空的行，再 SET NOT NULL —— 否则必然失败。"""
    downgrade_src = _function_source(_MIGRATION.read_text(encoding='utf-8'), 'downgrade')
    assert 'DELETE FROM inventory_log WHERE product_id IS NULL' in downgrade_src
    assert downgrade_src.index('DELETE FROM inventory_log') < downgrade_src.index('SET NOT NULL')
    assert downgrade_src.index('SET NOT NULL') < downgrade_src.index('ON DELETE CASCADE')
