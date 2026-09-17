"""里程碑契约·**对抗性**补充测试（T03 计算器口径 / 作用域排序 / 全局角色幂等）。

本文件独立于既有 ``test_calculate_material_scope.py`` / ``test_purchase_order_generate_scope.py``，
只补它们**未覆盖或覆盖为真空**的点，用于在不可逆迁移前做对抗性把关：

1. ``order_scopes`` **输入顺序无关性**（既有用例只传 ``set``，未证明「同一集合不同
   传入顺序 → 同一结果」；且直接测 ``utils.scope_order.order_scopes`` 本体，而非
   仅经 ``purchase_order_generate._scope_order`` 间接覆盖）；
   - ``{3, 12}`` → ``[3, 12]``（**数值**序，非 ``'角色#12' < '角色#3'`` 字典序）；
   - ``{2, 10, None}`` → ``[None, 2, 10]``；
   - 去重、``None`` 至多一次、混合具名/无名。
2. ``Σ(groups) ≡ 扁平`` 恒等式在**含包装类物料 + 同产品多行订单 + 无 BOM 产品**的混合
   输入下成立（既有用例的 ``packaging`` 恒为空集，恒等式对包装类**真空成立**）。
3. ``role_service.ensure_global_role`` 幂等：同名（含大小写/空白归一化）重复调用返回
   **同一 id**，且 ``role`` 表**只落一行**（真实异步 session + ``create_all``）。
"""
import pytest
import pytest_asyncio
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from fastapi_app.services.product.role_service import ensure_global_role
from fastapi_app.services.purchase_product_service import (
    aggregate_materials,
    aggregate_materials_by_scope,
)
from fastapi_app.shared_models import Base, ProductRole, Role
from fastapi_app.utils.scope_order import order_scopes


# ---------------------------------------------------------------------------
# 1) order_scopes：输入顺序无关 + 数值序（跨位数）
# ---------------------------------------------------------------------------

class TestOrderScopesInputOrderIndependence:
    """``order_scopes`` 是集合语义：传入顺序不得影响结果；无名时按 id 数值升序。"""

    def test_cross_digit_numeric_order_not_lexicographic(self):
        # '角色#12' < '角色#3' 是字典序陷阱；数值序必须为 [3, 12]
        assert order_scopes({3, 12}) == [3, 12]
        assert order_scopes({12, 3}) == [3, 12]

    def test_expected_shapes_from_spec(self):
        assert order_scopes({3, 12}) == [3, 12]
        assert order_scopes({2, 10, None}) == [None, 2, 10]

    def test_none_always_first(self):
        assert order_scopes({3, 12, None}) == [None, 3, 12]
        assert order_scopes({12, None, 3}) == [None, 3, 12]

    def test_input_order_independence_list_permutations(self):
        """同一集合以任意顺序（list 而非 set）传入，结果必须完全一致。"""
        import itertools

        items = [None, 3, 12, 2, 10]
        expected = order_scopes(items)
        assert expected == [None, 2, 3, 10, 12]  # 数值序，None 恒首位
        for perm in itertools.permutations(items):
            assert order_scopes(list(perm)) == expected, f'顺序 {perm} 改变了结果'

    def test_dedup_and_none_at_most_once(self):
        assert order_scopes([4, 4, None, None, 2, 2]) == [None, 2, 4]

    def test_mixed_named_and_unnamed(self):
        """name_of 只解析出部分角色时：有名按名升序，无名按 id 数值序混排且稳定。"""
        # role 2 名「乙」，role 10 无名 → 无名退化为「角色#10」的键参与排序
        names = {2: '乙'}
        result = order_scopes({2, 10, None}, name_of=lambda rid: names.get(rid))
        # 「乙」<「角色#10」？取决于 Unicode：比较结果必须**确定且可复现**——
        # 这里断言与「命名键（显示名, id）」升序一致，并断言集合完整、None 首位。
        assert result[0] is None
        assert set(result[1:]) == {2, 10}
        assert result[1:] == sorted(
            [2, 10], key=lambda rid: (('乙' if rid == 2 else f'角色#{rid}'), rid)
        )

    def test_empty_and_single(self):
        assert order_scopes([]) == []
        assert order_scopes({None}) == [None]
        assert order_scopes({7}) == [7]


# ---------------------------------------------------------------------------
# 2) Σ(groups) ≡ 扁平：混合输入（包装类 / 同产品多行 / 无 BOM 产品）
# ---------------------------------------------------------------------------

def _mat(category, name, usage, *, role_id=None, supplier='', spec='', unit='', code=''):
    """构造与 ``get_all_materials()`` 同形的 BOM 行。"""
    return {
        'category': category,
        'material_name': name,
        'unit_usage': usage,
        'unit': unit,
        'supplier_name': supplier,
        'specification': spec,
        'material_code': code,
        'role_id': role_id,
    }


class _FakeProduct:
    """最小 Product 替身：``has_bom()`` / ``get_all_materials()`` / ``id`` / ``name``。"""

    def __init__(self, pid, name, materials, roles=None):
        self.id = pid
        self.name = name
        self._materials = materials
        self.roles = roles or []

    def has_bom(self):
        return bool(self._materials)

    def get_all_materials(self):
        return list(self._materials)


def _name_of(mapping):
    return lambda pid, rid: mapping.get((pid, rid))


class TestFlatGroupsIdentityMixedInput:
    """恒等式：逐分类逐物料 ``Σ(groups) ≡ aggregate_materials``（含非空 packaging）。"""

    def _product_map(self):
        # p1：默认 + 角色 4，且**含包装类**（既有用例的 packaging 恒空 → 本用例补真空点）
        p1 = _FakeProduct(1, '公仔', [
            _mat('fabric', '布A', 2.0, role_id=None, supplier='甲', spec='s1', unit='米', code='F1'),
            _mat('fabric', '布A', 3.0, role_id=4, supplier='甲', spec='s1', unit='米', code='F1'),
            _mat('accessory', '扣', 4.0, role_id=4, supplier='乙', spec='', unit='颗', code='A1'),
            _mat('packaging', '彩盒', 1.0, role_id=None, supplier='丙', spec='L', unit='个', code='P1'),
            _mat('packaging', '彩盒', 2.0, role_id=4, supplier='丙', spec='L', unit='个', code='P1'),
            _mat('packaging', '贴纸', 0.5, role_id=4, supplier='丁', spec='', unit='张', code='P2'),
        ])
        # p2：仅默认 BOM
        p2 = _FakeProduct(2, '钥匙扣', [
            _mat('filling', '棉', 0.5, role_id=None, supplier='', spec='', unit='克', code='M1'),
        ])
        # p3：无 BOM（不应产出任何块，也不应破坏恒等式）
        p3 = _FakeProduct(3, '空产品', [])
        return {1: p1, 2: p2, 3: p3}

    def test_groups_sum_equals_flat_with_packaging_and_multiline(self):
        product_map = self._product_map()
        # p1 同一产品拆成多行订单（3 + 7 = 10）；p3 无 BOM 也下单
        orders = [
            {'product_id': 1, 'quantity': 3},
            {'product_id': 1, 'quantity': 7},
            {'product_id': 2, 'quantity': 4},
            {'product_id': 3, 'quantity': 5},
        ]
        name_of = _name_of({(1, 4): '乙'})

        flat = aggregate_materials(orders, product_map)
        groups = aggregate_materials_by_scope(orders, product_map, name_of=name_of)

        # packaging 必须非空，否则该分类的恒等式是**真空成立**（无意义）
        assert flat['packaging'], 'packaging 基线为空：恒等式对包装类真空，测试无意义'

        for category in ('filling', 'fabric', 'accessory', 'packaging'):
            flat_map = {
                (r['material_name'], r['supplier_name'], r['specification']): r['total_quantity']
                for r in flat[category]
            }
            grouped: dict[tuple, float] = {}
            for group in groups:
                for row in group[category]:
                    key = (row['material_name'], row['supplier_name'], row['specification'])
                    grouped[key] = grouped.get(key, 0.0) + row['total_quantity']

            assert set(grouped) == set(flat_map), f'{category} 键集不一致'
            for key, value in flat_map.items():
                assert grouped[key] == pytest.approx(value), f'{category}.{key} 不守恒'

    def test_no_bom_product_contributes_nothing(self):
        product_map = self._product_map()
        orders = [{'product_id': 3, 'quantity': 5}]  # 仅无 BOM 产品
        groups = aggregate_materials_by_scope(orders, product_map, name_of=_name_of({}))
        assert groups == [], '无 BOM 产品不得产出任何作用域块'

    def test_packaging_material_is_scoped_not_apportioned(self):
        """包装类同样「按作用域各用完整数量」，严禁跨作用域分摊。"""
        product_map = self._product_map()
        orders = [{'product_id': 1, 'quantity': 10}]
        groups = aggregate_materials_by_scope(
            orders, product_map, name_of=_name_of({(1, 4): '乙'}),
        )
        by_role = {
            g['role_id']: {
                (r['material_name'], r['specification']): r['total_quantity']
                for r in g['packaging']
            }
            for g in groups
        }
        assert by_role[None][('彩盒', 'L')] == pytest.approx(10.0)  # 1.0 × 10
        assert by_role[4][('彩盒', 'L')] == pytest.approx(20.0)     # 2.0 × 10（完整，非 ÷2）
        assert by_role[4][('贴纸', '')] == pytest.approx(5.0)       # 0.5 × 10


# ---------------------------------------------------------------------------
# 3) ensure_global_role 幂等（真实异步 session）
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def _role_session():
    """真实异步内存 SQLite（含 btrim UDF），仅建 role / product_role 表。"""
    engine = create_async_engine(
        'sqlite+aiosqlite:///:memory:',
        poolclass=StaticPool,
        connect_args={'check_same_thread': False},
    )

    @event.listens_for(engine.sync_engine, 'connect')
    def _register_btrim(dbapi_connection, _record):  # pragma: no cover
        dbapi_connection.create_function(
            'btrim', 1, lambda v: v.strip() if isinstance(v, str) else v,
        )

    async with engine.begin() as conn:
        await conn.run_sync(
            lambda c: Base.metadata.create_all(
                c, tables=[Role.__table__, ProductRole.__table__],
            )
        )
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        yield session
    await engine.dispose()


class TestEnsureGlobalRoleIdempotent:
    """同名「查找或新建」幂等：重复调用返回同一 id，且只落一行。"""

    @pytest.mark.asyncio
    async def test_same_name_returns_same_id_single_row(self, _role_session):
        db = _role_session
        first = await ensure_global_role(db, '源角色A')
        second = await ensure_global_role(db, '源角色A')
        assert first.id == second.id, '同名二次调用必须复用同一全局角色'
        total = await db.scalar(select(func.count()).select_from(Role))
        assert total == 1, f'不得重复插入，实得 {total} 行'

    @pytest.mark.asyncio
    async def test_idempotent_across_commit(self, _role_session):
        """提交后再次调用仍幂等（跨事务边界）。"""
        db = _role_session
        first = await ensure_global_role(db, '源角色B')
        await db.commit()
        again = await ensure_global_role(db, '源角色B')
        assert again.id == first.id
        total = await db.scalar(select(func.count()).select_from(Role))
        assert total == 1

    @pytest.mark.asyncio
    async def test_whitespace_and_case_are_same_key(self, _role_session):
        """trim + 大小写归一同键：'  源角色C  ' 与 '源角色c' 视为同一角色。"""
        db = _role_session
        first = await ensure_global_role(db, '源角色C')
        second = await ensure_global_role(db, '  源角色c  ')
        assert second.id == first.id, 'trim/大小写归一后应命中同一行'
        total = await db.scalar(select(func.count()).select_from(Role))
        assert total == 1

    @pytest.mark.asyncio
    async def test_distinct_names_create_distinct_rows(self, _role_session):
        db = _role_session
        a = await ensure_global_role(db, '甲')
        b = await ensure_global_role(db, '乙')
        assert a.id != b.id
        total = await db.scalar(select(func.count()).select_from(Role))
        assert total == 2
