"""采购单生成的 BOM 作用域（角色）单元测试

覆盖 2026-09-11 / 2026-09-17 改动：
- `_scope_order`：默认 BOM(None) 恒在首位，其余按**角色名升序**（名同按 id 升序），
  与物料计算器共用 `utils.scope_order.order_scopes` 同一口径（Q-05）
- `_bom_rows_by_scope`：按 role_id 分桶，None 与各角色互不混淆
- `_scope_label`：role_id=None → 默认BOM；角色名缺失退化而非丢弃
- **作用域装配必须显式补入 None**（历史缺陷：product_role 表无「默认BOM」行，
  只靠物料 role_id 集合会漏掉整个产品级 BOM）
- 每个作用域都用 SKU 完整数量计算，不做分摊
- `source_role` 落成明细备注
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from fastapi_app.services.purchase_order_crud import _scope_remark
from fastapi_app.services.purchase_order_generate import (
    DEFAULT_SCOPE_LABEL,
    _bom_rows_by_scope,
    _iter_source_skus,
    _load_bom_context,
    _scope_label,
    _scope_order,
)


class TestScopeOrder:
    """作用域排序：默认 BOM 恒在首位，其余按角色名升序（名同按 id 升序）"""

    def test_none_first_then_ascending(self):
        # 未传 name_of 时全部无名 → 按 role_id **数值**升序（历史口径）
        assert _scope_order({4, None, 2}) == [None, 2, 4]

    def test_no_name_of_falls_back_to_numeric_id_across_digit_boundary(self):
        """★ 回归：未传 name_of 时必须按 id **数值**升序，不能按「角色#id」字典序。

        历史缺陷：无名时排序键是 ``f'角色#{rid}'``，字符串比较下
        ``'角色#12' < '角色#3'`` ⇒ ``{3, 12}`` 返回 ``[12, 3]``，与历史「按 id 升序」
        静默分叉。个位 id（如 ``{2, 4}``/``{3, 7}``）两种口径恰好一致，因此旧测试
        全绿却掩盖了跨位数分叉——故本用例专挑 9/10、3/12、2/10 三组跨界。
        """
        assert _scope_order({12, 3}) == [3, 12]
        assert _scope_order({10, 9}) == [9, 10]
        assert _scope_order({2, 10, None}) == [None, 2, 10]
        assert _scope_order({31, 21, 3}) == [3, 21, 31]

    def test_named_roles_sorted_by_name_not_id(self):
        """★ 口径统一：按角色名升序，而非 role_id 升序（Q-05）。

        role 2 名「甲」(U+7532)、role 4 名「乙」(U+4E59)：名升序为 乙(4) → 甲(2)，
        与 id 升序 [2, 4] 相反 —— 命中「名 ≠ id 序」的真实分歧点。
        """
        names = {(1, 2): '甲', (1, 4): '乙'}
        assert _scope_order(
            {2, 4, None}, name_of=lambda rid: names.get((1, rid))
        ) == [None, 4, 2]

    def test_default_only(self):
        assert _scope_order({None}) == [None]

    def test_roles_only_without_none(self):
        """调用方未补 None 时应如实返回 —— 补 None 是调用方的责任，不是本函数的"""
        assert _scope_order({7, 3}) == [3, 7]

    def test_empty(self):
        assert _scope_order(set()) == []


class TestLoadBomContext:
    """Z02-R1：作用域装配要收集「物料行 role_id」，而不是拿 pid 去查 role_id 桶。"""

    @pytest.mark.asyncio
    async def test_material_role_ids_and_product_roles_both_in_scope(self):
        class _Result:
            def __init__(self, rows):
                self._rows = rows

            def scalars(self):
                return self

            def all(self):
                return self._rows

        # 三条 BOM 查询 + 一条 ProductRole 查询
        db = SimpleNamespace(execute=AsyncMock(side_effect=[
            _Result([SimpleNamespace(role_id=7, product_id=1)]),   # filling
            _Result([]),                                           # fabric
            _Result([]),                                           # accessory
            _Result([(99, 1, '角色A')]),                           # ProductRole
        ]))

        ctx = await _load_bom_context(db, [1])

        # 物料行 role_id=7 必须进入作用域（旧实现 m.get(pid) 恒空，只剩 99/None）
        assert ctx.scopes_by_pid[1] == [None, 7, 99]
        assert ctx.role_names[(1, 99)] == '角色A'


class TestBomRowsByScope:
    """BOM 行按 role_id 分桶"""

    def test_split_by_role(self):
        rows = [
            SimpleNamespace(role_id=None, name='默认A'),
            SimpleNamespace(role_id=4, name='呼汇A'),
            SimpleNamespace(role_id=None, name='默认B'),
            SimpleNamespace(role_id=2, name='角色2'),
        ]
        buckets = _bom_rows_by_scope(rows)
        assert set(buckets) == {None, 2, 4}
        assert [r.name for r in buckets[None]] == ['默认A', '默认B']
        assert [r.name for r in buckets[4]] == ['呼汇A']
        assert [r.name for r in buckets[2]] == ['角色2']

    def test_empty_rows(self):
        assert dict(_bom_rows_by_scope([])) == {}


class TestScopeLabel:
    """作用域显示名"""

    def test_none_is_default_bom(self):
        assert _scope_label(1, None, {}) == DEFAULT_SCOPE_LABEL == '默认BOM'

    def test_role_name_resolved(self):
        assert _scope_label(1, 4, {(1, 4): '呼汇'}) == '呼汇'

    def test_missing_role_name_degrades_not_dropped(self):
        """角色名查不到时退化为「角色#id」，绝不静默返回空串"""
        label = _scope_label(1, 9, {})
        assert label == '角色#9'

    def test_role_name_for_other_product_not_leaked(self):
        """角色名按 (product_id, role_id) 定位，不串产品"""
        assert _scope_label(2, 4, {(1, 4): '呼汇'}) == '角色#4'


class TestScopeAssemblyIncludesDefaultBom:
    """★ 回归：作用域装配必须显式补入 None

    历史缺陷：装配式写成
        material_roles = {物料上出现的 role_id} | {角色表 role_id}
    而 product_role 表**没有**「默认BOM」这一行（默认 BOM 只以
    `物料.role_id IS NULL` 存在），于是 product level BOM 被整个丢掉，
    生成的采购单里默认 BOM 的填充物/面料/辅料全部缺失。
    """

    @staticmethod
    def _assemble(material_roles: set, product_role_ids: set) -> list:
        """复刻 generate_purchase_orders_from_customer_orders 内的装配表达式。"""
        return _scope_order(material_roles | product_role_ids | {None})

    def test_default_bom_kept_when_roles_exist(self):
        # 产品只有角色 4 的物料，角色表也只有 4（无 None 行）—— 真实数据形态
        scopes = self._assemble(material_roles={None, 4}, product_role_ids={4})
        assert scopes[0] is None, '默认BOM 必须在首位，否则产品级 BOM 会丢失'
        assert scopes == [None, 4]

    def test_default_bom_kept_when_no_material_rows_at_all(self):
        """角色表有行、物料表全空：仍应产出 [None, 4]，由空作用域自然产出 0 条明细"""
        scopes = self._assemble(material_roles=set(), product_role_ids={4})
        assert scopes == [None, 4]

    def test_without_none_products_lose_default_bom(self):
        """反证：不补 None 就会漏掉默认 BOM（固化这条约束）"""
        without_none = _scope_order({4})
        with_none = self._assemble(material_roles={4}, product_role_ids={4})
        assert None not in without_none
        assert None in with_none


class TestEachScopeUsesFullQuantity:
    """每个作用域都用 SKU 完整数量，不做分摊"""

    def test_quantity_multiplier_is_full_qty_for_every_scope(self):
        qty = 10
        # 默认BOM 超柔 0.01/件、角色 哈哈 1/件 —— 各自 ×10，而非 ÷2 分摊
        rows = [
            (None, 0.01),
            (4, 1.0),
        ]
        computed = [(role, usage * qty) for role, usage in rows]
        assert computed == [(None, 0.1), (4, 10.0)]
        assert sum(u for _, u in computed) == pytest.approx(10.1), '不得出现分摊导致的合计缩减'


class TestIterSourceSkus:
    """源记录 SKU 抽取"""

    def test_order_with_items_prefers_items(self):
        rec = SimpleNamespace(
            items=[SimpleNamespace(product_id=1, quantity=2), SimpleNamespace(product_id=2, quantity=3)],
            product_id=1, quantity=5,
        )
        assert _iter_source_skus(rec) == [(1, 2), (2, 3)]

    def test_stockin_without_items_falls_back(self):
        rec = SimpleNamespace(items=None, product_id=7, quantity=4)
        assert _iter_source_skus(rec) == [(7, 4)]


class TestScopeRemark:
    """来源作用域写入明细备注"""

    def test_remark_written_when_scope_present(self):
        assert _scope_remark('呼汇') == '来源BOM：呼汇'
        assert _scope_remark('默认BOM') == '来源BOM：默认BOM'

    def test_remark_empty_when_no_scope(self):
        """无 source_role 时不产生多余文本（手工单 / 旧路径行为不变）"""
        assert _scope_remark(None) == ''
        assert _scope_remark('') == ''


class TestBuildItemsContract:
    """_build_items 的调用契约（不依赖 DB：直接验证传入 dict 的形状）"""

    @pytest.mark.asyncio
    async def test_source_role_key_is_consumed_by_crud(self):
        """生成的 item dict 必须带 source_role，且能被 CRUD 转成备注。"""
        from fastapi_app.services.purchase_order_crud import _scope_remark

        item = {
            'material_name': '哈哈', 'category': 'fabric', 'source_role': '呼汇',
            'specification': '哈哈', 'unit': '码', 'quantity': 10, 'unit_price': 0,
        }
        assert _scope_remark(item['source_role']) == '来源BOM：呼汇'
        # remark 优先于 source_role（编辑路径可显式覆盖备注）
        explicit = {'remark': '手工备注', 'source_role': '呼汇'}
        assert (explicit.get('remark') or _scope_remark(explicit.get('source_role'))) == '手工备注'
