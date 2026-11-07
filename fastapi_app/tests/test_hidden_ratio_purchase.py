"""陈列样 SKU「隐藏款随箱配比」采购数量回归测试。

口径（2026-11-07 与需求方确认）：
- 常规款 6 款按订单数量均分：``floor(N/6)`` + 余数按固定角色顺序逐款 +1，
  六款合计恒等于 N；
- 隐藏款随箱额外配置：``ceil(N/P)``，P 为 SKU 主数据用户填写的配比；
- P 为空 = 不启用，所有作用域一律完整数量（历史口径，存量 SKU 零变化）；
- 同客户组内同 SKU 先合并数量再分配（隐藏款 ceil 只取整一次）。

覆盖：纯函数（utils/scope_quantities）、采购生成（_build_material_items）、
物料计算器（扁平 + 分块恒等）、SKU 主数据 schema/服务/端点三态。
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


def _allocate(quantity=10000, hidden_carton_ratio=72, role_ids=ALL_ROLE_IDS):
    return allocate_scope_quantities(
        quantity,
        role_ids,
        hidden_carton_ratio=hidden_carton_ratio,
        name_of=_name_of,
    )


class TestSplitRegularQuantities:
    """常规 6 款均分：floor + 余数按顺序逐款 +1。"""

    def test_10000_example(self):
        assert split_regular_quantities(10000) == [1667, 1667, 1667, 1667, 1666, 1666]

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
        with pytest.raises(ValueError, match='隐藏款随箱配比'):
            hidden_quantity(100, ratio)

    def test_positive_ratio_is_accepted(self):
        assert hidden_quantity(100, 2) == 50


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

    def test_unconfigured_sku_keeps_full_quantity_for_every_scope(self):
        """P 为空 = 不启用：所有作用域（含默认 BOM）一律完整数量。"""
        quantities = _allocate(quantity=10000, hidden_carton_ratio=None)
        assert quantities[None] == 10000
        assert all(quantities[rid] == 10000 for rid in ALL_ROLE_IDS)

    def test_default_bom_keeps_full_quantity_when_rule_enabled(self):
        """启用规则时默认 BOM 仍用完整 N（共用物料逐只发生，不参与分摊）。"""
        quantities = allocate_scope_quantities(
            10000,
            ALL_ROLE_IDS | {None},
            hidden_carton_ratio=72,
            name_of=_name_of,
        )
        assert quantities[None] == 10000
        assert quantities[HIDDEN_ID] == 139

    @pytest.mark.parametrize(
        'role_ids',
        [
            set(REGULAR_IDS[:-1]) | {HIDDEN_ID},   # 只有 5 个常规款
            set(REGULAR_IDS),                     # 缺隐藏款
            set(REGULAR_IDS) | {HIDDEN_ID, 108},  # 多出的无名角色
        ],
    )
    def test_invalid_role_composition_is_explicit_error(self, role_ids):
        with pytest.raises(ValueError, match='6 个常规款.*1 个隐藏款'):
            _allocate(role_ids=role_ids)

    @pytest.mark.parametrize('ratio', [0, -1, 1.5, True])
    def test_invalid_ratio_is_rejected(self, ratio):
        with pytest.raises(ValueError, match='隐藏款随箱配比'):
            _allocate(hidden_carton_ratio=ratio)

    @pytest.mark.parametrize('quantity', [-1, 1.5, Decimal('1.5'), 'abc'])
    def test_enabled_rule_requires_nonnegative_integer_quantity(self, quantity):
        with pytest.raises(ValueError, match='采购数量必须是非负整数'):
            _allocate(quantity=quantity)

    def test_integral_decimal_and_float_quantities_are_accepted(self):
        assert _allocate(quantity=Decimal('10000'))[HIDDEN_ID] == 139
        assert _allocate(quantity=10000.0)[HIDDEN_ID] == 139


class _FakeProduct:
    """物料计算器测试用的最小 Product 形状（不查库）。"""

    def __init__(self, hidden_carton_ratio=72):
        self.id = 1
        self.name = '陈列样盲盒'
        self.hidden_carton_ratio = hidden_carton_ratio
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


def _context(hidden_ratio):
    """构造采购生成用的 _BomContext：每作用域一条填充物 BOM 行（单件用量 1 克）。

    hidden_ratio 为 None 时传空 hidden_ratios（= 未启用规则，走历史全量路径）。
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

    def test_unconfigured_material_rows_keep_legacy_full_quantity(self):
        items = _build_material_items([_record(10000)], _context(None), {1: '旧SKU'})
        assert len(items) == 8
        assert {item['quantity'] for item in items} == {10000}

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
        """配了 P 但角色结构不合法：明确报错，绝不静默按全量/错量落单。"""
        bad_ctx = _BomContext(
            filling={},
            scopes_by_pid={1: [None, *REGULAR_IDS]},  # 缺「隐藏款」角色
            role_names={(1, rid): name for rid, name in ROLE_NAMES.items()},
            hidden_ratios={1: 72},
        )
        with pytest.raises(ValueError, match='6 个常规款.*1 个隐藏款'):
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

    def test_unconfigured_product_keeps_legacy_calculator_behavior(self):
        product = _FakeProduct(hidden_carton_ratio=None)
        orders = [{'product_id': 1, 'quantity': 10000}]

        def name_of(_pid, rid):
            return _name_of(rid)

        flat = aggregate_materials(orders, {1: product})
        groups = aggregate_materials_by_scope(orders, {1: product}, name_of=name_of)

        assert flat['filling'][0]['total_quantity'] == 70000  # 7 个作用域 × 10000
        assert all(group['quantity'] == 10000 for group in groups)


class TestProductHiddenCartonRatioMasterData:
    @pytest.mark.parametrize('schema', [ProductCreate, ProductUpdate])
    @pytest.mark.parametrize('ratio', [0, -1, 1.5])
    def test_schema_rejects_non_positive_integer_ratio(self, schema, ratio):
        kwargs = {'name': '陈列样'} if schema is ProductCreate else {}
        with pytest.raises(ValidationError):
            schema(hidden_carton_ratio=ratio, **kwargs)

    def test_product_response_dict_exposes_nullable_ratio(self):
        assert Product(name='旧SKU').to_dict()['hidden_carton_ratio'] is None
        assert Product(name='陈列样', hidden_carton_ratio=72).to_dict()['hidden_carton_ratio'] == 72

    @pytest.mark.asyncio
    async def test_update_three_state_semantics(self, monkeypatch):
        """未提交保持原值；显式 null 清空；提交正整数设置。"""
        product = MagicMock()
        product.name = '陈列样'
        product.initial_stock = 0
        product.current_stock = 0
        product.hidden_carton_ratio = 72
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

    async def test_create_passes_ratio(self, monkeypatch):
        svc = AsyncMock()
        monkeypatch.setattr(product_ep.product_service, 'create_product', svc)
        data = ProductCreate(name='陈列样', hidden_carton_ratio=72)
        await product_ep.create_product(data=data, db=AsyncMock(), _user=self._user())
        assert svc.await_args.kwargs['hidden_carton_ratio'] == 72

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
        data = ProductUpdate(hidden_carton_ratio=100)
        await product_ep.edit_product(product_id=7, data=data, db=AsyncMock(), _user=self._user())
        assert svc.await_args.kwargs['hidden_carton_ratio'] == 100
        assert svc.await_args.kwargs['hidden_carton_ratio_provided'] is True
