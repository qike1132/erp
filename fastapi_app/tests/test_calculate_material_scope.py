"""物料计算器「按产品 × 作用域(角色)分块」单元测试（T03 / ``groups`` 契约）。

覆盖架构设计 §7 完成判据：

- 默认 BOM(``None``) **恒首块**；1 默认 + 2 角色 → 3 块；
- 每个作用域都用该产品的订单**总数量**展开（**不分摊**）；
- 空作用域**不产出块**；``role_name`` 缺失退化为 ``角色#<id>``；
- 扁平合并基线与 ``groups`` **自洽**：逐分类逐物料 ``Σ(groups) ≡ 扁平``。

纯函数部分（``aggregate_materials_by_scope``）不依赖 DB；集成部分用 mock 会话验证
``calculate_material`` 的返回契约（``groups`` + 保留扁平）。
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from fastapi_app.services.purchase_product_service import (
    aggregate_materials,
    aggregate_materials_by_scope,
    calculate_material,
)
from fastapi_app.utils.scope_order import DEFAULT_SCOPE_LABEL

# ---------------------------------------------------------------------------
# 测试替身
# ---------------------------------------------------------------------------

def _mat(category, name, usage, *, role_id=None, supplier='', spec='', unit='', code=''):
    """构造一条 BOM 物料行（字段与 ``get_all_materials()`` 输出同形）。"""
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


class _FakeGlobalRole:
    """全局角色替身（仅需 ``name``）。"""

    def __init__(self, name):
        self.name = name


class _FakeProductRole:
    """``ProductRole`` 替身（``_collect_role_names`` 需 ``id``/``role_name``/``global_role``）。"""

    def __init__(self, rid, *, global_name=None, mirror_name=''):
        self.id = rid
        self.role_name = mirror_name
        self.global_role = _FakeGlobalRole(global_name) if global_name is not None else None


class _FakeProduct:
    """最小 Product 替身：实现 ``has_bom()`` / ``get_all_materials()`` 且有 ``id`` / ``name``。"""

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
    """把 ``{(pid, rid): name}`` 包成 ``(pid, rid) -> name`` 解析函数。"""
    return lambda pid, rid: mapping.get((pid, rid))


def _mock_db(products):
    """构造返回 ``products`` 的 mock 异步会话。"""
    mock_result = MagicMock()
    mock_scalars = MagicMock()
    mock_scalars.unique.return_value.all.return_value = list(products)
    mock_result.scalars.return_value = mock_scalars
    db = MagicMock()
    db.execute = AsyncMock(return_value=mock_result)
    return db


# ---------------------------------------------------------------------------
# 分块顺序 / 数量口径
# ---------------------------------------------------------------------------

class TestScopeGrouping:
    """按「产品 × 作用域」分块：默认首块、名升序、不分摊、空作用域不产出。"""

    @staticmethod
    def _product_with_two_roles():
        # role 2 名「甲」(U+7532)、role 4 名「乙」(U+4E59)：名升序为 乙(4) → 甲(2)，
        # 与 id 升序 [2, 4] 相反 —— 用于固化「按名不按 id」的口径。
        return _FakeProduct(1, '公仔', [
            _mat('fabric', '默认布', 1.0, role_id=None, supplier='S', spec='x', unit='米'),
            _mat('fabric', '甲布', 1.0, role_id=2, supplier='S', spec='x', unit='米'),
            _mat('fabric', '乙布', 1.0, role_id=4, supplier='S', spec='x', unit='米'),
        ])

    def test_default_bom_is_first_block(self):
        product = self._product_with_two_roles()
        groups = aggregate_materials_by_scope(
            [{'product_id': 1, 'quantity': 1}], {1: product},
            name_of=_name_of({(1, 2): '甲', (1, 4): '乙'}),
        )
        assert groups[0]['role_id'] is None
        assert groups[0]['role_name'] == DEFAULT_SCOPE_LABEL == '默认BOM'

    def test_one_default_plus_two_roles_yields_three_blocks(self):
        product = self._product_with_two_roles()
        groups = aggregate_materials_by_scope(
            [{'product_id': 1, 'quantity': 1}], {1: product},
            name_of=_name_of({(1, 2): '甲', (1, 4): '乙'}),
        )
        assert [g['role_id'] for g in groups] == [None, 4, 2], '默认首块 + 其余按角色名升序'
        assert [g['role_name'] for g in groups] == ['默认BOM', '乙', '甲']

    def test_empty_scope_produces_no_block(self):
        # 产品只有 role_4 的物料，没有任何默认 BOM 物料：不得产出空的「默认BOM」块。
        product = _FakeProduct(1, '公仔', [
            _mat('fabric', '乙布', 1.0, role_id=4, supplier='S', spec='x', unit='米'),
        ])
        groups = aggregate_materials_by_scope(
            [{'product_id': 1, 'quantity': 1}], {1: product},
            name_of=_name_of({(1, 4): '乙'}),
        )
        assert [g['role_id'] for g in groups] == [4]

    def test_role_name_degrades_when_missing(self):
        product = _FakeProduct(1, '公仔', [
            _mat('fabric', '默认布', 1.0, role_id=None, supplier='S', spec='x', unit='米'),
            _mat('fabric', '布5', 1.0, role_id=5, supplier='S', spec='x', unit='米'),
        ])
        groups = aggregate_materials_by_scope(
            [{'product_id': 1, 'quantity': 1}], {1: product},
            name_of=_name_of({}),  # role 5 无名
        )
        by_role = {g['role_id']: g['role_name'] for g in groups}
        assert by_role[5] == '角色#5'

    def test_each_scope_uses_full_quantity_not_apportioned(self):
        product = _FakeProduct(1, '公仔', [
            _mat('filling', '超柔', 0.01, role_id=None, supplier='', spec='', unit='克'),
            _mat('filling', '哈哈', 1.0, role_id=4, supplier='', spec='', unit='克'),
        ])
        groups = aggregate_materials_by_scope(
            [{'product_id': 1, 'quantity': 10}], {1: product},
            name_of=_name_of({(1, 4): '乙'}),
        )
        by_role = {g['role_id']: g['filling'][0]['total_quantity'] for g in groups}
        assert by_role[None] == pytest.approx(0.1)   # 0.01 × 10（完整数量）
        assert by_role[4] == pytest.approx(10.0)      # 1.0 × 10（完整数量，非 ÷2 分摊）
        assert sum(by_role.values()) == pytest.approx(10.1)

    def test_quantity_merges_multiple_order_lines_per_product(self):
        product = _FakeProduct(1, '公仔', [
            _mat('fabric', '布', 1.0, role_id=None, supplier='S', spec='x', unit='米'),
        ])
        groups = aggregate_materials_by_scope(
            [{'product_id': 1, 'quantity': 3}, {'product_id': 1, 'quantity': 4}],
            {1: product}, name_of=_name_of({}),
        )
        assert len(groups) == 1
        assert groups[0]['quantity'] == pytest.approx(7.0)
        assert groups[0]['fabric'][0]['total_quantity'] == pytest.approx(7.0)

    def test_product_without_bom_yields_no_group(self):
        product = _FakeProduct(1, '空产品', [])
        groups = aggregate_materials_by_scope(
            [{'product_id': 1, 'quantity': 5}], {1: product}, name_of=_name_of({}),
        )
        assert groups == []


# ---------------------------------------------------------------------------
# 扁平基线 与 groups 自洽（恒等式）
# ---------------------------------------------------------------------------

class TestFlatGroupsConsistency:
    """``Σ(groups) ≡ aggregate_materials``（逐分类逐物料）。"""

    def _products(self):
        p1 = _FakeProduct(1, 'A', [
            _mat('fabric', '布A', 2.0, role_id=None, supplier='甲', spec='s1', unit='米', code='F1'),
            _mat('fabric', '布A', 3.0, role_id=4, supplier='甲', spec='s1', unit='米', code='F1'),
            _mat('accessory', '扣', 4.0, role_id=4, supplier='乙', spec='', unit='颗', code='A1'),
        ])
        p2 = _FakeProduct(2, 'B', [
            _mat('filling', '棉', 0.5, role_id=None, supplier='', spec='', unit='克', code='M1'),
        ])
        return {1: p1, 2: p2}

    def test_groups_sum_equals_flat(self):
        product_map = self._products()
        orders = [{'product_id': 1, 'quantity': 10}, {'product_id': 2, 'quantity': 4}]
        name_of = _name_of({(1, 4): '乙'})

        flat = aggregate_materials(orders, product_map)
        groups = aggregate_materials_by_scope(orders, product_map, name_of=name_of)

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


# ---------------------------------------------------------------------------
# calculate_material 集成契约（mock 会话）
# ---------------------------------------------------------------------------

class TestCalculateMaterialContract:
    """``calculate_material`` 返回 ``groups`` + 保留扁平字段。"""

    @pytest.mark.asyncio
    async def test_returns_groups_and_flat(self):
        product = _FakeProduct(1, '公仔', [
            _mat('fabric', '默认布', 1.0, role_id=None, supplier='S', spec='x', unit='米'),
            _mat('fabric', '乙布', 2.0, role_id=4, supplier='S', spec='x', unit='米'),
        ], roles=[_FakeProductRole(4, global_name='乙')])

        result = await calculate_material(_mock_db([product]), [{'product_id': 1, 'quantity': 1}])

        # 扁平字段仍存在（旧客户端兼容）
        for key in ('filling', 'fabric', 'accessory', 'packaging'):
            assert key in result
        assert 'groups' in result

        first = result['groups'][0]
        assert first['role_id'] is None
        assert first['role_name'] == '默认BOM'
        assert first['product_id'] == 1
        assert first['product_name'] == '公仔'
        # 角色块名取自全局角色名
        role_block = next(g for g in result['groups'] if g['role_id'] == 4)
        assert role_block['role_name'] == '乙'

    @pytest.mark.asyncio
    async def test_empty_orders_returns_groups_key(self):
        result = await calculate_material(MagicMock(), [])
        assert result['groups'] == []
        assert result['packaging'] == []
