"""盲盒 SKU 订单数量分配回归测试（三档口径）。

口径（2026-11-08 需求）：
- 非盲盒：每个角色都用完整订单数量（存量口径，零行为变化）；
- 盲盒、无隐藏款：隐藏款配置不启用，订单数量按「角色数量」均分；
- 盲盒、有隐藏款且配比 P 非空：BOM 须恰有 1 个隐藏款；常规角色按「常规角色
  数量」均分（常规 4 + 隐藏 1 → 10000/4；常规 8 + 隐藏 1 → 10000/8），隐藏款
  额外 ``ceil(N/P)``；**配比留空 = 不额外配隐藏款**，退化为按角色数量均分。

覆盖：纯函数、采购生成、物料计算器、SKU 主数据 schema/服务/端点。
"""
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from fastapi_app.api.v1.endpoints import product as product_ep
from fastapi_app.schemas.product import ProductCreate, ProductUpdate
from fastapi_app.services import product_service
from fastapi_app.services.purchase_order_generate import (
    _bom_rows_by_scope,
    _BomContext,
    _build_material_items,
)
from fastapi_app.services.purchase_product_service import (
    aggregate_materials,
    aggregate_materials_by_scope,
)
from fastapi_app.shared_models.product import Product
from fastapi_app.utils.scope_quantities import (
    allocate_scope_quantities,
    hidden_quantity,
    split_regular_quantities,
)

ROLE_NAMES = {
    106: '角色F',
    102: '角色B',
    107: '隐藏款',
    101: '角色A',
    105: '角色E',
    103: '角色C',
    104: '角色D',
}
REGULAR_IDS = [101, 102, 103, 104, 105, 106]
HIDDEN_ID = 107
ALL_ROLE_IDS = set(ROLE_NAMES)


def _name_of(role_id):
    return ROLE_NAMES.get(role_id)


def _allocate(
    quantity=10000, hidden_carton_ratio=72, role_ids=ALL_ROLE_IDS,
    *, blind_box=True, has_hidden=True,
):
    return allocate_scope_quantities(
        quantity,
        role_ids,
        hidden_carton_ratio=hidden_carton_ratio,
        name_of=_name_of,
        blind_box=blind_box,
        has_hidden=has_hidden,
    )


class TestSplitRegularQuantities:
    """均分内核：floor + 余数按顺序逐份 +1，合计恒等于 N。"""

    def test_10000_example(self):
        assert split_regular_quantities(10000) == [1667, 1667, 1667, 1667, 1666, 1666]

    def test_dynamic_parts_4_and_8(self):
        """需求示例：常规 4 款 → 10000/4；常规 8 款 → 10000/8。"""
        assert split_regular_quantities(10000, 4) == [2500, 2500, 2500, 2500]
        assert split_regular_quantities(10000, 8) == [1250] * 8

    @pytest.mark.parametrize(
        ('total', 'expected'),
        [
            (0, [0] * 6),
            (4, [1, 1, 1, 1, 0, 0]),          # N < 6：只补前 4 款
            (7, [2, 1, 1, 1, 1, 1]),          # 余数 1：仅首款 +1
            (6, [1] * 6),                     # 整除：无余数
            (12, [2] * 6),
        ],
    )
    def test_remainder_walks_fixed_order(self, total, expected):
        assert split_regular_quantities(total) == expected

    @pytest.mark.parametrize('total', range(0, 61))
    def test_sum_invariant_always_holds(self, total):
        assert sum(split_regular_quantities(total)) == total

    def test_negative_total_is_rejected(self):
        with pytest.raises(ValueError, match='采购数量必须是非负整数'):
            split_regular_quantities(-1)

    @pytest.mark.parametrize('parts', [0, -1])
    def test_non_positive_parts_is_rejected(self, parts):
        with pytest.raises(ValueError, match='参与均分的角色数量'):
            split_regular_quantities(100, parts)


class TestHiddenQuantity:
    """隐藏款 ceil(N/P)：不足一箱按一箱。"""

    @pytest.mark.parametrize(
        ('total', 'ratio', 'expected'),
        [
            (10000, 72, 139),   # 138.888… → 139
            (10000, 100, 100),  # 整除
            (10000, 120, 84),   # 83.33… → 84
            (7200, 72, 100),
            (0, 72, 0),
            (1, 100, 1),
        ],
    )
    def test_examples(self, total, ratio, expected):
        assert hidden_quantity(total, ratio) == expected

    @pytest.mark.parametrize('ratio', [0, -1])
    def test_non_positive_ratio_is_rejected(self, ratio):
        with pytest.raises(ValueError, match='盲盒隐藏款装箱配比'):
            hidden_quantity(100, ratio)

    def test_positive_ratio_is_accepted(self):
        assert hidden_quantity(100, 2) == 50

    def test_negative_total_is_rejected(self):
        with pytest.raises(ValueError, match='采购数量必须是非负整数'):
            hidden_quantity(-1, 72)


class TestAllocateScopeQuantities:
    def test_10000_remainder_and_hidden_72(self):
        quantities = _allocate()
        assert [quantities[rid] for rid in REGULAR_IDS] == [
            1667, 1667, 1667, 1667, 1666, 1666,
        ]
        assert sum(quantities[rid] for rid in REGULAR_IDS) == 10000
        assert quantities[HIDDEN_ID] == 139

    @pytest.mark.parametrize(
        ('quantity', 'ratio', 'regular_each', 'hidden'),
        [
            (10000, 100, None, 100),
            (7200, 72, 1200, 100),
            (0, 72, 0, 0),
        ],
    )
    def test_exact_division_and_zero(self, quantity, ratio, regular_each, hidden):
        quantities = _allocate(quantity=quantity, hidden_carton_ratio=ratio)
        assert quantities[HIDDEN_ID] == hidden
        assert sum(quantities[rid] for rid in REGULAR_IDS) == quantity
        if regular_each is not None:
            assert {quantities[rid] for rid in REGULAR_IDS} == {regular_each}

    def test_non_blind_box_keeps_legacy_full_quantity(self):
        """非盲盒：即使配了配比也按存量口径全量（勾选盲盒才生效）。"""
        quantities = _allocate(blind_box=False, has_hidden=False)
        assert quantities[None] == 10000
        assert all(quantities[rid] == 10000 for rid in ALL_ROLE_IDS)

    def test_blind_box_without_hidden_divides_by_role_count(self):
        """盲盒无隐藏款：按角色数量均分（含名为「隐藏款」的角色，共 7 个）。"""
        quantities = _allocate(hidden_carton_ratio=None, has_hidden=False)
        # 10000 = 7×1428 余 4 → id 升序前 4 个 1429，其余 1428
        assert [quantities[rid] for rid in (101, 102, 103, 104)] == [1429] * 4
        assert [quantities[rid] for rid in (105, 106, HIDDEN_ID)] == [1428] * 3
        assert sum(quantities[rid] for rid in ALL_ROLE_IDS) == 10000

    def test_hidden_ratio_blank_falls_back_to_role_split(self):
        """有隐藏款但配比留空：不额外配隐藏款 → 退化为按角色数量均分。"""
        quantities = _allocate(hidden_carton_ratio=None, has_hidden=True)
        assert sum(quantities[rid] for rid in ALL_ROLE_IDS) == 10000
        assert quantities[HIDDEN_ID] in (1428, 1429)

    @pytest.mark.parametrize('regular_count', [1, 2, 4, 8])
    def test_regular_count_is_dynamic(self, regular_count):
        """常规角色数量动态参与均分：4 款 → 10000/4，8 款 → 10000/8。"""
        regular_ids = list(range(201, 201 + regular_count))
        names = {rid: f'角色{rid}' for rid in regular_ids}
        names[999] = '隐藏款'
        quantities = allocate_scope_quantities(
            10000, set(names), hidden_carton_ratio=72, name_of=names.get,
            blind_box=True, has_hidden=True,
        )
        assert sum(quantities[rid] for rid in regular_ids) == 10000
        assert quantities[999] == 139
        regular_quantities = [quantities[rid] for rid in regular_ids]
        assert max(regular_quantities) - min(regular_quantities) <= 1

    def test_default_bom_keeps_full_quantity_when_rule_enabled(self):
        """启用规则时默认 BOM 仍用完整 N（共用物料逐只发生，不参与分摊）。"""
        quantities = allocate_scope_quantities(
            10000, ALL_ROLE_IDS | {None}, hidden_carton_ratio=72,
            name_of=_name_of, blind_box=True, has_hidden=True,
        )
        assert quantities[None] == 10000
        assert quantities[HIDDEN_ID] == 139

    def test_designated_hidden_role_overrides_name(self):
        """右键指定优先：角色名叫「角色G」也能当隐藏款（不改名）。"""
        names = {
            **{rid: f'角色{chr(ord("A") + i)}' for i, rid in enumerate(REGULAR_IDS)},
            107: '角色G',
        }
        quantities = allocate_scope_quantities(
            10000, set(names), hidden_carton_ratio=72,
            name_of=names.get, hidden_role_id=107, blind_box=True, has_hidden=True,
        )
        assert quantities[107] == 139
        assert sum(quantities[rid] for rid in REGULAR_IDS) == 10000

    @pytest.mark.parametrize('bad_name', [' 隐藏款', '隐藏款 ', '隐藏款A', '隐藏款(备)'])
    def test_hidden_name_must_be_exactly_three_chars(self, bad_name):
        """名字识别严格全等：前后空格/后缀/修饰都不算隐藏款（需求 1）。"""
        names = {
            **{rid: f'角色{chr(ord("A") + i)}' for i, rid in enumerate(REGULAR_IDS)},
            107: bad_name,
        }
        with pytest.raises(ValueError, match='恰好 1 个隐藏款'):
            allocate_scope_quantities(
                10000, set(names), hidden_carton_ratio=72,
                name_of=names.get, blind_box=True, has_hidden=True,
            )

    def test_remainder_follows_role_id_order_not_display_name(self):
        """余数按 role_id 升序（角色编码/创建顺序），改名不改变各款分到多少。

        角色名故意与 id 逆序：若实现按名称序分配，前 4 个 id 会拿到 1666。
        """
        names = {
            201: '角色F', 202: '角色E', 203: '角色D',
            204: '角色C', 205: '角色B', 206: '角色A', 207: '隐藏款',
        }
        quantities = allocate_scope_quantities(
            10000, set(names), hidden_carton_ratio=72, name_of=names.get,
            blind_box=True, has_hidden=True,
        )
        assert [quantities[rid] for rid in (201, 202, 203, 204, 205, 206)] == [
            1667, 1667, 1667, 1667, 1666, 1666,
        ]
        assert quantities[207] == 139

    def test_two_hidden_roles_is_explicit_error(self):
        """有隐藏款时隐藏款角色必须恰好 1 个（同名 + 指定同时存在也算两个）。"""
        names = {**{rid: f'角色{chr(ord("A") + i)}' for i, rid in enumerate(REGULAR_IDS)}, 107: '隐藏款'}
        with pytest.raises(ValueError, match='恰好 1 个隐藏款'):
            allocate_scope_quantities(
                10000, set(names) | {108}, hidden_carton_ratio=72, name_of=names.get,
                blind_box=True, has_hidden=True, hidden_role_id=108,
            )

    def test_only_hidden_role_is_explicit_error(self):
        names = {107: '隐藏款'}
        with pytest.raises(ValueError, match='至少需要 1 个常规角色'):
            allocate_scope_quantities(
                10000, {107}, hidden_carton_ratio=72, name_of=names.get,
                blind_box=True, has_hidden=True,
            )

    def test_blind_box_without_any_role_is_explicit_error(self):
        with pytest.raises(ValueError, match='至少需要 1 个角色'):
            allocate_scope_quantities(
                10000, set(), hidden_carton_ratio=None, name_of=_name_of,
                blind_box=True, has_hidden=False,
            )

    @pytest.mark.parametrize('ratio', [0, -1, 1.5, True])
    def test_invalid_ratio_is_rejected(self, ratio):
        with pytest.raises(ValueError, match='盲盒隐藏款装箱配比'):
            _allocate(hidden_carton_ratio=ratio)

    @pytest.mark.parametrize('quantity', [-1, 1.5, Decimal('1.5'), 'abc'])
    def test_blind_box_requires_nonnegative_integer_quantity(self, quantity):
        with pytest.raises(ValueError, match='采购数量必须是非负整数'):
            _allocate(quantity=quantity)

    def test_integral_decimal_and_float_quantities_are_accepted(self):
        assert _allocate(quantity=Decimal('10000'))[HIDDEN_ID] == 139
        assert _allocate(quantity=10000.0)[HIDDEN_ID] == 139


class _FakeProduct:
    """物料计算器测试用的最小 Product 形状（不查库）。"""

    def __init__(self, hidden_carton_ratio=72, *, is_blind_box=True, has_hidden_role=True):
        self.id = 1
        self.name = '陈列样盲盒'
        self.hidden_carton_ratio = hidden_carton_ratio
        self.is_blind_box = is_blind_box
        self.has_hidden_role = has_hidden_role
        self.roles = [
            SimpleNamespace(id=rid, role_name=name) for rid, name in ROLE_NAMES.items()
        ]
        self._rows = [
            {
                'category': 'filling',
                'material_name': '棉花',
                'unit_usage': 1,
                'unit': '克',
                'supplier_name': '',
                'specification': '',
                'material_code': '',
                'role_id': rid,
            }
            for rid in ALL_ROLE_IDS
        ]

    def has_bom(self):
        return True

    def get_all_materials(self):
        return list(self._rows)


def _record(quantity):
    return SimpleNamespace(
        customer='客户A',
        items=[SimpleNamespace(product_id=1, quantity=quantity)],
    )


def _context(hidden_ratio=72, *, has_hidden=True, blind_box=True):
    """构造采购生成用的 _BomContext：每作用域一条填充物 BOM 行（单件用量 1 克）。

    hidden_ratio=None → 不额外配隐藏款（有隐藏款时退化为按角色数均分）。
    """
    rows = [
        SimpleNamespace(
            product_id=1,
            role_id=rid,
            cotton_usage=1,
            material_code='',
            part_name=None,
            specification='',
            unit='克',
            supplier_name='',
            supplier_id=None,
        )
        for rid in [None, *ALL_ROLE_IDS]
    ]
    return _BomContext(
        filling=_bom_rows_by_scope(rows),
        scopes_by_pid={1: [None, *REGULAR_IDS, HIDDEN_ID]},
        role_names={(1, rid): name for rid, name in ROLE_NAMES.items()},
        hidden_ratios={} if hidden_ratio is None else {1: hidden_ratio},
        blind_box_pids={1} if blind_box else set(),
        has_hidden_pids={1} if (blind_box and has_hidden) else set(),
    )


class TestPurchaseGenerationIntegration:
    def test_material_rows_use_allocated_quantities(self):
        items = _build_material_items([_record(10000)], _context(72), {1: '陈列样盲盒'})
        quantities = {item['source_role']: item['quantity'] for item in items}

        assert quantities['默认BOM'] == 10000
        assert [quantities[ROLE_NAMES[rid]] for rid in REGULAR_IDS] == [
            1667, 1667, 1667, 1667, 1666, 1666,
        ]
        assert quantities['隐藏款'] == 139

    def test_non_blind_box_material_rows_keep_legacy_full_quantity(self):
        items = _build_material_items(
            [_record(10000)], _context(72, blind_box=False), {1: '旧SKU'},
        )
        assert len(items) == 8
        assert {item['quantity'] for item in items} == {10000}

    def test_blind_box_without_hidden_divides_by_role_count(self):
        """盲盒无隐藏款：7 个角色各按 10000/7 均分（隐藏款角色也参与）。"""
        items = _build_material_items(
            [_record(10000)], _context(72, has_hidden=False), {1: '盲盒无隐藏'},
        )
        quantities = {item['source_role']: item['quantity'] for item in items}
        assert quantities['默认BOM'] == 10000
        assert sum(quantities[ROLE_NAMES[rid]] for rid in ALL_ROLE_IDS) == 10000
        assert quantities['隐藏款'] in (1428, 1429)

    def test_same_sku_is_merged_before_nonlinear_allocation(self):
        """同客户组内同 SKU 多行：先合并成 N=10000 再分配，隐藏款只进位一次。

        逐行分配会得 ceil(6000/72)+ceil(4000/72)=84+56=140（多 1 个）；
        合并分配必须得 ceil(10000/72)=139。
        """
        items = _build_material_items(
            [_record(6000), _record(4000)], _context(72), {1: '陈列样盲盒'},
        )
        assert len(items) == 8  # 每（作用域 × BOM 行）只产出一条明细
        quantities = {item['source_role']: item['quantity'] for item in items}
        assert quantities['隐藏款'] == 139
        assert sum(quantities[ROLE_NAMES[rid]] for rid in REGULAR_IDS) == 10000

    def test_misconfigured_sku_fails_closed(self):
        """有隐藏款但 BOM 里没有隐藏款角色：明确报错，绝不静默按全量/错量落单。"""
        bad_ctx = _BomContext(
            filling={},
            scopes_by_pid={1: [None, *REGULAR_IDS]},  # 缺「隐藏款」角色
            role_names={(1, rid): name for rid, name in ROLE_NAMES.items()},
            hidden_ratios={1: 72},
            blind_box_pids={1},
            has_hidden_pids={1},
        )
        with pytest.raises(ValueError, match='恰好 1 个隐藏款'):
            _build_material_items([_record(10000)], bad_ctx, {1: '陈列样盲盒'})


class TestMaterialCalculatorParity:
    """计算器（扁平 + 分块）与采购生成共用同一分配：三方恒等。"""

    def test_flat_and_scope_results_use_same_allocation(self):
        product = _FakeProduct(hidden_carton_ratio=72)
        orders = [
            {'product_id': 1, 'quantity': 6000},
            {'product_id': 1, 'quantity': 4000},
        ]

        def name_of(_pid, rid):
            return _name_of(rid)

        flat = aggregate_materials(orders, {1: product})
        groups = aggregate_materials_by_scope(orders, {1: product}, name_of=name_of)

        assert flat['filling'][0]['total_quantity'] == 10139
        by_role = {group['role_id']: group for group in groups}
        assert by_role[HIDDEN_ID]['quantity'] == 139
        assert [by_role[rid]['quantity'] for rid in REGULAR_IDS] == [
            1667, 1667, 1667, 1667, 1666, 1666,
        ]
        assert sum(
            row['total_quantity']
            for group in groups
            for row in group['filling']
        ) == flat['filling'][0]['total_quantity']

    def test_non_blind_box_keeps_legacy_calculator_behavior(self):
        product = _FakeProduct(hidden_carton_ratio=72, is_blind_box=False, has_hidden_role=False)
        orders = [{'product_id': 1, 'quantity': 10000}]

        def name_of(_pid, rid):
            return _name_of(rid)

        flat = aggregate_materials(orders, {1: product})
        groups = aggregate_materials_by_scope(orders, {1: product}, name_of=name_of)

        assert flat['filling'][0]['total_quantity'] == 70000  # 7 个作用域 × 10000
        assert all(group['quantity'] == 10000 for group in groups)

    def test_blind_box_without_hidden_divides_by_role_count(self):
        product = _FakeProduct(hidden_carton_ratio=None, is_blind_box=True, has_hidden_role=False)
        orders = [{'product_id': 1, 'quantity': 10000}]

        def name_of(_pid, rid):
            return _name_of(rid)

        flat = aggregate_materials(orders, {1: product})
        groups = aggregate_materials_by_scope(orders, {1: product}, name_of=name_of)

        # 7 个角色均分 10000（余数 5 → 前 5 个各 1429，其余 1428）
        assert flat['filling'][0]['total_quantity'] == 10000
        assert sum(group['quantity'] for group in groups) == 10000


class TestProductBlindBoxMasterData:
    @pytest.mark.parametrize('schema', [ProductCreate, ProductUpdate])
    @pytest.mark.parametrize('ratio', [0, -1, 1.5, True, False])
    def test_schema_rejects_non_positive_integer_ratio(self, schema, ratio):
        """bool 必须在 before 阶段拒绝：Pydantic 宽松模式会把它隐式转成 1/0。"""
        kwargs = {'name': '陈列样'} if schema is ProductCreate else {}
        with pytest.raises(ValidationError):
            schema(hidden_carton_ratio=ratio, **kwargs)

    def test_blind_box_flags_default_off(self):
        data = ProductCreate(name='普通公仔')
        assert data.is_blind_box is False and data.has_hidden_role is False
        assert ProductUpdate().is_blind_box is None

    def test_product_response_dict_exposes_blind_box_flags(self):
        plain = Product(name='旧SKU').to_dict()
        assert plain['is_blind_box'] is False and plain['has_hidden_role'] is False
        blind = Product(name='盲盒', is_blind_box=True, has_hidden_role=True).to_dict()
        assert blind['is_blind_box'] is True and blind['has_hidden_role'] is True

    @pytest.mark.asyncio
    async def test_update_three_state_semantics(self, monkeypatch):
        """未提交保持原值；显式 null 清空；提交正整数设置。"""
        product = MagicMock()
        product.name = '陈列样'
        product.initial_stock = 0
        product.current_stock = 0
        product.hidden_carton_ratio = 72
        product.is_blind_box = True
        product.has_hidden_role = True
        product.to_dict.return_value = {'id': 1}
        db = MagicMock()
        db.info = {}
        db.flush = AsyncMock()
        db.refresh = AsyncMock()
        monkeypatch.setattr(
            product_service, 'get_product_for_update', AsyncMock(return_value=product),
        )
        monkeypatch.setattr(product_service.cache_mgr, 'invalidate', AsyncMock())

        common = {
            'name': None,
            'barcode': None,
            'image': None,
            'initial_stock': None,
        }

        # 1) 未提交该字段：已配的 72 必须保持（旧客户端只改价格/条码）
        await product_service.update_product(db, 1, **common)
        assert product.hidden_carton_ratio == 72
        assert product.is_blind_box is True

        # 2) 显式提交 null（provided=True）：清空停用
        await product_service.update_product(
            db, 1, **common, hidden_carton_ratio=None, hidden_carton_ratio_provided=True,
        )
        assert product.hidden_carton_ratio is None

        # 3) 提交正整数：设置
        await product_service.update_product(
            db, 1, **common, hidden_carton_ratio=100, hidden_carton_ratio_provided=True,
        )
        assert product.hidden_carton_ratio == 100

    @pytest.mark.asyncio
    async def test_turn_off_blind_box_clears_hidden_config(self, monkeypatch):
        product = MagicMock()
        product.name = '陈列样'
        product.initial_stock = 0
        product.current_stock = 0
        product.hidden_carton_ratio = 72
        product.is_blind_box = True
        product.has_hidden_role = True
        product.to_dict.return_value = {'id': 1}
        db = MagicMock()
        db.info = {}
        db.flush = AsyncMock()
        db.refresh = AsyncMock()
        monkeypatch.setattr(
            product_service, 'get_product_for_update', AsyncMock(return_value=product),
        )
        monkeypatch.setattr(product_service.cache_mgr, 'invalidate', AsyncMock())

        await product_service.update_product(
            db, 1, name=None, barcode=None, image=None, initial_stock=None,
            is_blind_box=False,
        )
        assert product.is_blind_box is False
        assert product.has_hidden_role is False
        assert product.hidden_carton_ratio is None

    @pytest.mark.asyncio
    async def test_ratio_only_update_on_disabled_product_is_cleared(self, monkeypatch):
        """只提交配比、开关都未提交：非「盲盒 + 有隐藏款」时配比不得留存（OCR M5）。

        否则会存下一个永不生效的休眠值，将来有人打开开关时突然变成有效配置。
        """
        product = MagicMock()
        product.name = '普通公仔'
        product.initial_stock = 0
        product.current_stock = 0
        product.hidden_carton_ratio = None
        product.is_blind_box = False
        product.has_hidden_role = False
        product.to_dict.return_value = {'id': 2}
        db = MagicMock()
        db.info = {}
        db.flush = AsyncMock()
        db.refresh = AsyncMock()
        monkeypatch.setattr(
            product_service, 'get_product_for_update', AsyncMock(return_value=product),
        )
        monkeypatch.setattr(product_service.cache_mgr, 'invalidate', AsyncMock())

        await product_service.update_product(
            db, 2, name=None, barcode=None, image=None, initial_stock=None,
            hidden_carton_ratio=72, hidden_carton_ratio_provided=True,
        )
        assert product.hidden_carton_ratio is None

    @pytest.mark.asyncio
    async def test_create_drops_ratio_when_not_enabled(self, monkeypatch):
        """新建时非「盲盒 + 有隐藏款」不得把配比入库（OCR M4）。"""
        db = MagicMock()
        db.info = {}
        db.flush = AsyncMock()
        db.refresh = AsyncMock()
        db.add = MagicMock()
        empty = MagicMock()
        empty.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=empty)
        monkeypatch.setattr(product_service.cache_mgr, 'invalidate', AsyncMock())

        await product_service.create_product(
            db, name='普通公仔', barcode=None, image=None, initial_stock=0,
            hidden_carton_ratio=72, is_blind_box=False, has_hidden_role=False,
        )
        created = db.add.call_args.args[0]
        assert created.hidden_carton_ratio is None
        assert created.is_blind_box is False and created.has_hidden_role is False


class _Tx:
    async def __aenter__(self):
        return None

    async def __aexit__(self, *exc):
        return False


class TestEndpointWiring:
    """端点透传 + model_fields_set 三态。"""

    @pytest.fixture(autouse=True)
    def _patch_infra(self, monkeypatch):
        monkeypatch.setattr(product_ep, 'db_transaction', lambda db: _Tx())
        monkeypatch.setattr(product_ep.cache_mgr, 'invalidate', AsyncMock())
        monkeypatch.setattr(product_ep, 'assert_product_factory_scoped', AsyncMock())

    @staticmethod
    def _user():
        return MagicMock(factory=None, is_super=True)

    async def test_create_passes_blind_box_fields(self, monkeypatch):
        svc = AsyncMock()
        monkeypatch.setattr(product_ep.product_service, 'create_product', svc)
        data = ProductCreate(
            name='盲盒', hidden_carton_ratio=72, is_blind_box=True, has_hidden_role=True,
        )
        await product_ep.create_product(data=data, db=AsyncMock(), _user=self._user())
        kwargs = svc.await_args.kwargs
        assert kwargs['hidden_carton_ratio'] == 72
        assert kwargs['is_blind_box'] is True
        assert kwargs['has_hidden_role'] is True

    async def test_create_without_ratio_passes_none(self, monkeypatch):
        svc = AsyncMock()
        monkeypatch.setattr(product_ep.product_service, 'create_product', svc)
        data = ProductCreate(name='旧SKU')
        await product_ep.create_product(data=data, db=AsyncMock(), _user=self._user())
        assert svc.await_args.kwargs['hidden_carton_ratio'] is None

    async def test_edit_omission_means_no_change(self, monkeypatch):
        """请求体没带配比字段：provided=False，服务层不动原值。"""
        svc = AsyncMock()
        monkeypatch.setattr(product_ep.product_service, 'update_product', svc)
        data = ProductUpdate(price=1)
        await product_ep.edit_product(product_id=7, data=data, db=AsyncMock(), _user=self._user())
        assert svc.await_args.kwargs['hidden_carton_ratio_provided'] is False
        assert svc.await_args.kwargs['is_blind_box'] is None

    async def test_edit_explicit_null_clears(self, monkeypatch):
        """请求体显式带 null：provided=True + 值 None → 清空停用。"""
        svc = AsyncMock()
        monkeypatch.setattr(product_ep.product_service, 'update_product', svc)
        data = ProductUpdate(hidden_carton_ratio=None)
        await product_ep.edit_product(product_id=7, data=data, db=AsyncMock(), _user=self._user())
        assert svc.await_args.kwargs['hidden_carton_ratio'] is None
        assert svc.await_args.kwargs['hidden_carton_ratio_provided'] is True

    async def test_edit_explicit_value_sets(self, monkeypatch):
        svc = AsyncMock()
        monkeypatch.setattr(product_ep.product_service, 'update_product', svc)
        data = ProductUpdate(hidden_carton_ratio=100, is_blind_box=True, has_hidden_role=True)
        await product_ep.edit_product(product_id=7, data=data, db=AsyncMock(), _user=self._user())
        assert svc.await_args.kwargs['hidden_carton_ratio'] == 100
        assert svc.await_args.kwargs['hidden_carton_ratio_provided'] is True
        assert svc.await_args.kwargs['is_blind_box'] is True
        assert svc.await_args.kwargs['has_hidden_role'] is True


class TestMaterialCalculatorErrorMapping:
    """物料计算器的业务错误必须是可读 400，而不是伪装成服务故障的 500。"""

    @pytest.mark.asyncio
    async def test_configuration_error_maps_to_400(self, monkeypatch):
        from fastapi import HTTPException

        from fastapi_app.api.v1.endpoints.purchase_center import product_routes

        svc = SimpleNamespace(
            calculate_material=AsyncMock(
                side_effect=ValueError('配置了盲盒隐藏款装箱配比=72 的 SKU 需要恰好 1 个隐藏款'),
            ),
        )
        monkeypatch.setattr(product_routes, 'svc', svc)

        with pytest.raises(HTTPException) as exc:
            await product_routes.api_calculate_material(
                data=SimpleNamespace(orders=[]), db=AsyncMock(), _current_user=None,
            )
        assert exc.value.status_code == 400
        assert '恰好 1 个隐藏款' in str(exc.value.detail)
