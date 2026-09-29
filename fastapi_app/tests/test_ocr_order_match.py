"""产品匹配兜底（名称被污染时仍要认出真正用到的产品）

真实背景（2026-09-29 用户实测）：OCR 把无关文字粘到产品名上后，
共享匹配器的关键词切分对整段无标点中文只切出一个长 token，得分直接归零，
用户看到的就是「产品名加几个字就识别不出来」。
"""
from typing import ClassVar
from unittest.mock import MagicMock, patch

import pytest

from fastapi_app.services.ocr._order_match import (
    covered_chars,
    longest_common_substring_len,
    match_product_robust,
    meaningful_len,
    one_edit_equal,
)

# 库内真实存在的产品名（生产库只读查询得到的原样名称）
DUMZI = '《蛋仔派对》团子木鱼毛绒挂件盲盒'
SHIJI = '《蛋仔派对》市集拾趣系列 毛绒公仔挂件盲盒'
ANYU = '咸鱼按摩捶'
SHARK = '鲨鱼'


def product(pid: int, name: str) -> MagicMock:
    p = MagicMock()
    p.id = pid
    p.name = name
    p.barcode = ''
    return p


@pytest.fixture
def catalog():
    items = [product(1, DUMZI), product(2, SHIJI), product(3, ANYU), product(4, SHARK)]
    product_map = {p.name.lower().strip(): p for p in items}
    return items, product_map


class TestScorers:
    def test_meaningful_len_ignores_punctuation(self):
        # 《》（）空格不计入，否则书名号会把分母抬高
        assert meaningful_len(DUMZI) == meaningful_len('蛋仔派对团子木鱼毛绒挂件盲盒')
        assert meaningful_len('咸鱼按摩捶') == 5

    def test_longest_common_substring(self):
        assert longest_common_substring_len('菲菲团子木鱼毛绒挂件盲盒发潜伏期', DUMZI) == 10
        assert longest_common_substring_len('abc', 'xyz') == 0

    def test_covered_chars_counts_multiple_runs(self):
        """被插入字切断时，累计覆盖要能把两段都算上"""
        # 中间被插入「试读」，切成 6 字 + 8 字两段
        assert covered_chars('市集拾趣系列试读毛绒公仔挂件盲盒', SHIJI) == 14
        # 两字片段不计入（挡巧合）
        assert covered_chars('这批不按摩也不推拿', '按摩') == 0

    def test_covered_chars_does_not_double_count(self):
        assert covered_chars(DUMZI, DUMZI) == meaningful_len(DUMZI)


class TestRealUserStrings:
    """用户 2026-09-29 实测表里的「产品名称」列原文（加了字导致匹配失败）

    这批数据的备注列是空的，多余文字**本来就在产品名单元格里**，
    所以问题纯在匹配侧：共享匹配器对整段无标点中文只切一个长 token → 0.00。
    """

    CASES: ClassVar[list[tuple[str, str]]] = [
        ('菲菲 团子木鱼毛绒挂件盲盒  发潜伏期', DUMZI),
        ('市集拾趣系列  试试毛绒公仔挂件盲盒', SHIJI),
        ('咸鱼按摩捶 11菲菲', ANYU),
        ('鲨的鱼', SHARK),
    ]

    @pytest.mark.parametrize('raw, expected', CASES)
    def test_extra_words_in_name_still_match(self, catalog, raw, expected):
        items, product_map = catalog
        matched, confidence = match_product_robust(raw, items, product_map)
        assert matched is not None, raw
        assert matched.name == expected
        assert confidence >= 0.7

    def test_shared_matcher_alone_would_fail(self, catalog):
        """对照组：单靠共享匹配器这两条是 0.00（说明兜底确实在起作用）"""
        from fastapi_app.services.ocr_fuzzy_match import fuzzy_match_product

        items, product_map = catalog
        for raw in ['菲菲 团子木鱼毛绒挂件盲盒  发潜伏期', '市集拾趣系列  试试毛绒公仔挂件盲盒']:
            product, _ = fuzzy_match_product(raw, items, product_map)
            assert product is None, raw

    def test_absent_product_stays_unmatched(self, catalog):
        """库里没有的产品不能被兜底硬凑上"""
        items, product_map = catalog
        matched, _ = match_product_robust('橡皮擦订书机', items, product_map)
        assert matched is None


class TestShortNameTier:
    """短名称兜底：OCR 把近乎独立的产品名多插/漏一个字

    实测：「鲨的鱼」对应库内「鲨鱼」（多插了一个「的」）。
    覆盖率那条路对这种输入天然无效——它问的是「产品名有多少出现在原图里」，
    而输入比产品名还短。
    """

    def test_inserted_char_still_matches(self, catalog):
        items, product_map = catalog
        matched, confidence = match_product_robust('鲨的鱼', items, product_map)
        assert matched is not None
        assert matched.name == SHARK
        assert confidence == pytest.approx(0.9)

    def test_same_length_one_char_diff_matches(self):
        """同长度、差一字的判定（此分支由 one_edit_equal 直接覆盖；集成侧受 3 字下限约束）"""
        assert one_edit_equal('鲨色', '鲨鱼') is True
        assert one_edit_equal('鲨鱼', '鲨鱼') is True
        assert one_edit_equal('鱼鱼', '鲨鱼') is True   # 差一字——正因如此才设 3 字下限
        assert one_edit_equal('甲乙', '鲨鱼') is False

    def test_two_char_input_is_not_guessed(self, catalog):
        """两字输入与两字产品名「差一个字」等于差一半，不能凑"""
        items, product_map = catalog
        matched, _ = match_product_robust('鱼鱼', items, product_map)
        assert matched is None

    def test_two_char_exact_still_matches(self, catalog):
        items, product_map = catalog
        matched, confidence = match_product_robust('鲨鱼', items, product_map)
        assert matched is not None and matched.name == SHARK
        assert confidence >= 0.9

    def test_unrelated_short_names_do_not_match(self, catalog):
        items, product_map = catalog
        for raw in ['甲乙', '丙丁', '吗呢', '橡皮擦']:
            matched, _ = match_product_robust(raw, items, product_map)
            assert matched is None, raw

    def test_absent_lookalike_does_not_match(self, catalog):
        """「鹹的鱼」与「鲨鱼」只差首字，仍不该凑上"""
        items, product_map = catalog
        matched, _ = match_product_robust('鹹的鱼', items, product_map)
        assert matched is None


class TestRobustFallback:
    def test_polluted_name_still_matches_core_product(self, catalog):
        items, product_map = catalog
        matched, confidence = match_product_robust('菲菲团子木鱼毛绒挂件盲盒发潜伏期', items, product_map)
        assert matched is not None
        assert matched.name == DUMZI
        assert confidence >= 0.7

    def test_clean_core_still_matches(self, catalog):
        items, product_map = catalog
        matched, _ = match_product_robust('团子木鱼毛绒挂件盲盒', items, product_map)
        assert matched is not None
        assert matched.name == DUMZI

    def test_trailing_junk_does_not_break_match(self, catalog):
        items, product_map = catalog
        matched, _ = match_product_robust('咸鱼按摩捶11菲菲', items, product_map)
        assert matched is not None
        assert matched.name == ANYU

    def test_split_name_still_matches(self, catalog):
        """原图名称被插入字切断（试读）时仍要匹配上"""
        items, product_map = catalog
        matched, confidence = match_product_robust('市集拾趣系列试读毛绒公仔挂件盲盒', items, product_map)
        assert matched is not None
        assert matched.name == SHIJI
        assert confidence >= 0.7

    def test_unrelated_text_does_not_match(self, catalog):
        items, product_map = catalog
        matched, confidence = match_product_robust('鹹的鱼', items, product_map)
        assert matched is None
        assert confidence == 0.0

    def test_long_unrelated_text_does_not_match(self, catalog):
        items, product_map = catalog
        matched, _ = match_product_robust('随便写一段跟产品无关的话abcdef', items, product_map)
        assert matched is None

    def test_short_coincidental_containment_is_rejected(self, catalog):
        """隔离兜底逻辑：库内短名恰好被原图文字包含时不能误判（2 字巧合不算）

        注意要先把共享匹配器屏蔽掉——否则某些输入会先被共享匹配器的关键词逻辑命中
        （实测它对「这批不按摩也不推拿」给 0.806），测的就不是兜底了。
        """
        short = product(9, '按摩')
        items, product_map = catalog
        items = [*items, short]
        with patch('fastapi_app.services.ocr._order_match.fuzzy_match_product',
                   return_value=(None, 0.0)):
            matched, _ = match_product_robust('这批不按摩也不推拿', items, product_map)
        assert matched is None

    def test_defers_to_shared_matcher_when_it_matches(self, catalog):
        """共享匹配器给出结果时不抢：兜底只是它的补充，不改既有判定"""
        items, product_map = catalog
        other = product(42, '别的产品')
        with patch('fastapi_app.services.ocr._order_match.fuzzy_match_product',
                   return_value=(other, 0.81)):
            matched, confidence = match_product_robust('任意文字', items, product_map)
        assert matched is other
        assert confidence == 0.81

    def test_prefers_longer_absolute_match(self, catalog):
        """两个候选都过覆盖率时，命中字符更多的优先"""
        items, product_map = catalog
        # 同时包含「团子木鱼毛绒挂件盲盒」与短名，应选命中更多的那个
        matched, _ = match_product_robust('订单：团子木鱼毛绒挂件盲盒 备注咸鱼', items, product_map)
        assert matched is not None
        assert matched.name == DUMZI

    def test_confidence_is_coverage_of_db_name(self, catalog):
        items, product_map = catalog
        _, confidence = match_product_robust('菲菲团子木鱼毛绒挂件盲盒发潜伏期', items, product_map)
        # 命中 10 字 / 产品名 14 个有效字符
        assert confidence == pytest.approx(10 / 14, abs=0.01)
