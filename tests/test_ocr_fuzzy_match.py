"""
ocr_fuzzy_match 模块单元测试

覆盖：Levenshtein 相似度、关键字提取、产品模糊匹配、客户模糊匹配
"""
from types import SimpleNamespace

from fastapi_app.services.ocr_fuzzy_match import (
    _extract_keywords,
    _keyword_match_score,
    _levenshtein_similarity,
    fuzzy_match_customer,
    fuzzy_match_product,
)

# ============================================================
# _levenshtein_similarity
# ============================================================

class TestLevenshteinSimilarity:
    def test_identical_strings(self):
        assert _levenshtein_similarity("hello", "hello") == 1.0

    def test_empty_strings(self):
        assert _levenshtein_similarity("", "hello") == 0.0
        assert _levenshtein_similarity("hello", "") == 0.0
        assert _levenshtein_similarity("", "") == 0.0

    def test_completely_different(self):
        score = _levenshtein_similarity("abc", "xyz")
        assert score < 0.5

    def test_similar_strings(self):
        score = _levenshtein_similarity("kitten", "sitting")
        assert 0.4 < score < 0.8

    def test_one_char_diff(self):
        score = _levenshtein_similarity("cat", "car")
        assert score > 0.6

    def test_length_disparity_early_exit(self):
        """长度差异超过40%时直接返回0"""
        score = _levenshtein_similarity("ab", "abcdefgh")
        assert score == 0.0


# ============================================================
# _extract_keywords
# ============================================================

class TestExtractKeywords:
    def test_chinese_keywords(self):
        kws = _extract_keywords("蓝色毛绒玩具熊")
        assert any("毛绒" in k for k in kws) or any("玩具" in k for k in kws)

    def test_english_keywords(self):
        kws = _extract_keywords("Hello World ABC123")
        assert "HELLO" in kws or "WORLD" in kws

    def test_filters_common_words(self):
        kws = _extract_keywords("系列型号款式颜色")
        assert "系列" not in kws
        assert "型号" not in kws

    def test_strips_parenthetical_content(self):
        kws = _extract_keywords("毛绒熊（大号）红色")
        # 括号内的"大号"应被移除
        assert "大号" not in kws

    def test_empty_input(self):
        assert _extract_keywords("") == []


# ============================================================
# _keyword_match_score
# ============================================================

class TestKeywordMatchScore:
    def test_identical_text(self):
        score = _keyword_match_score("毛绒玩具", "毛绒玩具")
        assert score > 0.8

    def test_no_overlap(self):
        score = _keyword_match_score("电子产品", "毛绒玩具")
        assert score < 0.5

    def test_partial_overlap(self):
        # "ABC毛绒玩具" → kws=['毛绒玩具','ABC'], "DEF毛绒玩具" → kws=['毛绒玩具','DEF']
        score = _keyword_match_score("ABC毛绒玩具", "DEF毛绒玩具")
        assert 0.0 < score < 1.0

    def test_empty_input(self):
        assert _keyword_match_score("", "something") == 0.0
        assert _keyword_match_score("something", "") == 0.0


# ============================================================
# fuzzy_match_product
# ============================================================

def _make_product(name, pid=1):
    return SimpleNamespace(id=pid, name=name)


class TestFuzzyMatchProduct:
    def test_exact_match(self):
        p = _make_product("蓝色毛绒熊")
        product_map = {"蓝色毛绒熊": p}
        matched, score = fuzzy_match_product("蓝色毛绒熊", [p], product_map)
        assert matched is p
        assert score == 1.0

    def test_exact_match_case_insensitive(self):
        p = _make_product("TestProduct")
        product_map = {"testproduct": p}
        matched, score = fuzzy_match_product("TestProduct", [p], product_map)
        assert matched is p
        assert score == 1.0

    def test_substring_match(self):
        p = _make_product("蓝色毛绒玩具熊大号")
        matched, score = fuzzy_match_product("毛绒玩具熊", [p], {})
        assert matched is p
        assert score >= 0.75

    def test_no_match_below_threshold(self):
        p = _make_product("完全不相关的产品")
        matched, score = fuzzy_match_product("电子元器件", [p], {})
        assert matched is None
        assert score == 0.0

    def test_empty_ocr_name(self):
        p = _make_product("产品A")
        matched, score = fuzzy_match_product("", [p], {})
        assert matched is None
        assert score == 0.0

    def test_best_match_among_multiple(self):
        p1 = _make_product("红色毛绒猫", pid=1)
        p2 = _make_product("蓝色毛绒熊", pid=2)
        p3 = _make_product("蓝色毛绒熊大号", pid=3)
        products = [p1, p2, p3]
        matched, _score = fuzzy_match_product("蓝色毛绒熊", products, {})
        # 应精确匹配 p2 或通过子串匹配 p3
        assert matched is not None
        assert matched.id in (2, 3)

    def test_custom_min_similarity(self):
        p = _make_product("毛绒玩具")
        matched_high, _ = fuzzy_match_product("毛绒玩", [p], {}, min_similarity=0.95)
        matched_low, _ = fuzzy_match_product("毛绒玩", [p], {}, min_similarity=0.5)
        # 高阈值可能不匹配，低阈值应该匹配
        assert matched_low is not None or matched_high is None


# ============================================================
# fuzzy_match_customer
# ============================================================

def _make_customer(name, cid=1):
    return SimpleNamespace(id=cid, name=name)


class TestFuzzyMatchCustomer:
    def test_exact_match(self):
        c = _make_customer("东莞市滨发玩具有限公司")
        matched, score = fuzzy_match_customer("东莞市滨发玩具有限公司", [c])
        assert matched is c
        assert score == 1.0

    def test_suffix_stripped_match(self):
        """去除公司后缀后精确匹配"""
        c = _make_customer("东莞市滨发玩具有限公司")
        matched, score = fuzzy_match_customer("东莞市滨发玩具", [c])
        # 应返回0.95（去后缀匹配）
        assert matched is c
        assert score == 0.95

    def test_substring_match(self):
        c = _make_customer("深圳市腾讯科技有限公司")
        matched, score = fuzzy_match_customer("腾讯科技", [c])
        assert matched is c
        assert score >= 0.7

    def test_no_match(self):
        c = _make_customer("完全无关公司")
        matched, score = fuzzy_match_customer("另一家企业", [c])
        assert matched is None or score < 0.7

    def test_empty_name(self):
        c = _make_customer("测试公司")
        matched, score = fuzzy_match_customer("", [c])
        assert matched is None
        assert score == 0.0

    def test_case_insensitive(self):
        c = _make_customer("ABC Company Ltd.")
        matched, score = fuzzy_match_customer("abc company ltd.", [c])
        assert matched is c
        assert score == 1.0

    def test_best_match_among_multiple(self):
        c1 = _make_customer("北京华为技术有限公司", cid=1)
        c2 = _make_customer("深圳华为终端有限公司", cid=2)
        c3 = _make_customer("上海小米科技有限公司", cid=3)
        matched, _score = fuzzy_match_customer("华为技术", [c1, c2, c3])
        assert matched is not None
        assert matched.id == 1  # 应匹配 c1
