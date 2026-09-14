"""ITER-2 决策 1：应用层批内去重的行为测试。

这些测试锁定的核心不变量：
1. **不丢行** —— kept 的行号 ∪ duplicates 的行号 = 输入的全部行号。
   静默丢数据是这类改造最危险的失败模式，必须可断言。
2. **先出现者胜** —— 与现行「逐行 SAVEPOINT、后到者撞唯一约束被跳过」行为一致。
3. **没有唯一键就不去重** —— 宁可留给 DB 约束，也不在内存里猜。
4. **归一化一致** —— 客户/产品名按大小写不敏感 + 去空白匹配，与
   ``_pre_load_product_map`` 的 ``name.lower().strip()`` 同源。
"""
from __future__ import annotations

import pytest

from fastapi_app.services.batch_import_dedup import (
    DEFAULT_FIRST_DATA_ROW,
    DedupResult,
    build_conflict_note,
    composite_key,
    dedupe_by_keys,
)

# ---------------------------------------------------------------------------
# composite_key：归一化
# ---------------------------------------------------------------------------

class TestCompositeKey:

    def test_case_and_whitespace_insensitive(self):
        assert composite_key('Acme') == composite_key('  acme ')
        assert composite_key('ACME') == composite_key('acme')

    def test_composite_of_multiple_fields(self):
        assert composite_key('Acme', 'Widget') == composite_key('acme', 'WIDGET')
        assert composite_key('Acme', 'Widget') != composite_key('Acme', 'Gadget')

    def test_none_or_blank_returns_none(self):
        """任一分量为空 → 无法判定唯一性 → None（调用方据此保留该行）。"""
        assert composite_key(None) is None
        assert composite_key('Acme', None) is None
        assert composite_key('') is None
        assert composite_key('   ') is None
        assert composite_key('Acme', '') is None

    def test_casefold_can_be_disabled(self):
        assert composite_key('Acme', casefold=False) != composite_key('acme', casefold=False)
        assert composite_key(' Acme ', casefold=False) == composite_key('Acme', casefold=False)

    def test_non_string_values_pass_through(self):
        assert composite_key(7) == (7,)
        assert composite_key(7) != composite_key('7')
        assert composite_key(0) == (0,)          # 0 不应被当成空值


# ---------------------------------------------------------------------------
# dedupe_by_keys：核心行为
# ---------------------------------------------------------------------------

def _rows(*keys):
    return [{'k': k, 'v': i} for i, k in enumerate(keys)]


def _key(row):
    return row['k']


class TestDedupeBasics:

    def test_no_duplicates_keeps_everything(self):
        result = dedupe_by_keys(_rows('a', 'b', 'c'), _key)
        assert [r['k'] for r in result.kept_rows] == ['a', 'b', 'c']
        assert result.duplicates == []
        assert result.removed_count == 0

    def test_batch_internal_duplicate_keeps_first(self):
        result = dedupe_by_keys(_rows('a', 'b', 'a'), _key)
        assert [r['k'] for r in result.kept_rows] == ['a', 'b']
        assert result.removed_count == 1
        d = result.duplicates[0]
        assert d.line_no == 4                    # 第 3 个数据行，行号 2+2
        assert '文件内重复' in d.reason

    def test_all_same_key_keeps_exactly_one(self):
        result = dedupe_by_keys(_rows('x', 'x', 'x', 'x'), _key)
        assert len(result.kept) == 1
        assert result.removed_count == 3

    def test_existing_key_beats_batch_key(self):
        """与库中已有的重复 → 原因文案应与「文件内重复」区分开。"""
        result = dedupe_by_keys(_rows('a', 'b'), _key, existing_keys={'a'})
        assert [r['k'] for r in result.kept_rows] == ['b']
        assert '与已有数据重复' in result.duplicates[0].reason

    def test_reason_priority_existing_before_in_batch(self):
        """已存在的键即便是文件内首次出现，也应报「与已有数据重复」。"""
        result = dedupe_by_keys(_rows('a', 'a'), _key, existing_keys={'a'})
        assert result.removed_count == 2
        assert all('与已有数据重复' in d.reason for d in result.duplicates)

    def test_case_insensitive_via_composite_key(self):
        """归一化在 key_fn 里做：composite_key 的缺省口径是大小写不敏感。"""
        result = dedupe_by_keys(_rows('Acme', 'ACME', ' acme '), lambda r: composite_key(r['k']))
        assert len(result.kept) == 1

    def test_case_sensitive_via_composite_key(self):
        """需要区分大小写时显式传 casefold=False。"""
        result = dedupe_by_keys(
            _rows('Acme', 'ACME', ' Acme '),
            lambda r: composite_key(r['k'], casefold=False),
        )
        assert len(result.kept) == 2              # 'Acme' 与 ' Acme ' 归一后相同，'ACME' 不同

    def test_raw_string_keys_are_compared_verbatim(self):
        """不过 key_fn 归一化时按键的原样比较 —— 不做隐式折叠。"""
        result = dedupe_by_keys(_rows('Acme', 'ACME'), _key)
        assert len(result.kept) == 2

    def test_none_key_is_always_kept(self):
        """没有唯一键的行一律保留 —— 不猜、不丢。"""
        result = dedupe_by_keys(_rows(None, None, 'a', 'a'), _key)
        assert len(result.kept) == 3              # 两个 None + 一个 'a'
        assert result.removed_count == 1

    def test_empty_input(self):
        result = dedupe_by_keys([], _key)
        assert isinstance(result, DedupResult)
        assert result.kept == [] and result.duplicates == []
        assert result.total_count == 0


class TestNoSilentDataLoss:
    """不丢行：这是本模块最重要的不变量。"""

    @pytest.mark.parametrize('keys', [
        ('a', 'b', 'c'),
        ('a', 'a', 'a'),
        ('a', None, 'a', None, 'b'),
        (None, None, None),
        (),
    ])
    def test_line_numbers_are_a_partition(self, keys):
        rows = _rows(*keys)
        result = dedupe_by_keys(rows, _key)
        expected = set(range(DEFAULT_FIRST_DATA_ROW, DEFAULT_FIRST_DATA_ROW + len(rows)))
        actual = {ln for ln, _ in result.kept} | {d.line_no for d in result.duplicates}
        assert actual == expected, '有行号既不在 kept 也不在 duplicates —— 存在静默丢行'

    def test_custom_start_index_is_respected(self):
        result = dedupe_by_keys(_rows('a', 'a'), _key, start_index=100)
        assert [ln for ln, _ in result.kept] == [100]
        assert result.duplicates[0].line_no == 101

    def test_relative_order_of_kept_rows_preserved(self):
        keys = ('c', 'a', 'c', 'b', 'a')
        result = dedupe_by_keys(_rows(*keys), _key)
        assert [r['k'] for r in result.kept_rows] == ['c', 'a', 'b']


class TestErrorMessages:

    def test_messages_carry_line_numbers(self):
        result = dedupe_by_keys(_rows('a', 'a'), _key, label='订单编号')
        msg = result.error_messages()[0]
        assert msg.startswith('行3:')
        assert '订单编号' in msg

    def test_limit_truncates_with_summary(self):
        result = dedupe_by_keys(_rows(*['x'] * 50), _key)
        msgs = result.error_messages(limit=5)
        assert len(msgs) == 6
        assert msgs[-1].startswith('…另有')
        assert '44' in msgs[-1]                   # 49 条重复 - 5 条列出

    def test_limit_not_reached_no_summary(self):
        result = dedupe_by_keys(_rows('a', 'a'), _key)
        msgs = result.error_messages(limit=10)
        assert len(msgs) == 1

    def test_no_duplicates_yields_no_messages(self):
        assert dedupe_by_keys(_rows('a', 'b'), _key).error_messages() == []


class TestCompositeKeyIntegration:
    """贴近真实用法：客户 + 产品 的复合自然键。"""

    def test_customer_product_pair(self):
        rows = [
            {'customer': 'Acme', 'product': 'Widget'},
            {'customer': 'acme ', 'product': 'widget'},
            {'customer': 'Acme', 'product': 'Gadget'},
        ]
        result = dedupe_by_keys(
            rows, lambda r: composite_key(r['customer'], r['product']), label='客户+产品'
        )
        assert len(result.kept) == 2
        assert result.duplicates[0].line_no == 3

    def test_incomplete_row_is_not_deduped(self):
        """客户缺失的行没有唯一键 → 保留，交由后续校验处理。"""
        rows = [
            {'customer': 'Acme', 'product': 'Widget'},
            {'customer': '', 'product': 'Widget'},
            {'customer': 'Acme', 'product': ''},
        ]
        result = dedupe_by_keys(rows, lambda r: composite_key(r['customer'], r['product']))
        assert len(result.kept) == 3
        assert result.removed_count == 0

    def test_existing_db_values_are_respected(self):
        """种子来自库中的既有键（与 _pre_load_product_map 的归一化口径一致）。"""
        existing = {composite_key('Acme', 'Widget')}
        rows = [
            {'customer': 'ACME', 'product': 'WIDGET'},   # 与库中重复
            {'customer': 'Acme', 'product': 'Gadget'},   # 新
        ]
        result = dedupe_by_keys(
            rows, lambda r: composite_key(r['customer'], r['product']), existing_keys=existing
        )
        assert len(result.kept) == 1
        assert result.kept_rows[0]['product'] == 'Gadget'


class TestConflictNote:
    """并发冲突只能减少、不能消除 —— rowcount 核对必须回显差异。"""

    def test_no_difference_returns_none(self):
        assert build_conflict_note(100, 100) is None

    def test_rowcount_unavailable_returns_none(self):
        assert build_conflict_note(100, None) is None

    def test_fewer_rows_than_expected_reports_conflict(self):
        note = build_conflict_note(100, 97)
        assert note is not None
        assert '少 3 行' in note
        assert 'ON CONFLICT' in note

    def test_more_rows_than_expected_reports_anomaly(self):
        note = build_conflict_note(100, 105)
        assert note is not None
        assert '多 5 行' in note
