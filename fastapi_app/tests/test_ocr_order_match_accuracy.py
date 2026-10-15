"""模糊匹配准确率的模拟测试（种子固定，可复现）

为什么要有这个文件：手挑用例会掩盖系统性弱点。这里用**真实产品库 + 合成 OCR 噪声**
批量跑，量化三件事并设阈值，防止以后悄悄退化：

  1. 召回——产品的噪声变体还能不能匹配到自己（真实库 ≥ 95%）
  2. 精确——**真实库上不允许出现错配**（宁可让人在弹窗里手选，也不能挂错产品）
  3. 保守——无关文本不能乱匹配（误匹配率 ≤ 2%）

噪声模型取自实际观察到的 OCR 瑕疵：多插字、漏字、认错字、前后粘无关词、词间断开、片段重影。

已知且有意接受的两处弱项（不在断言里当成失败）：
  - 两字产品名（如「鲨鱼」）被替换掉一个字 → 拒绝匹配。两字差一半，猜它比不猜更危险。
  - 只差尾词的重名（挂件 / 挂件盲盒 / 摆件）在尾词被破坏时会指向同前缀的兄弟产品，
    这属于人工确认环节兜住的范围。
"""
import random
import zlib
from unittest.mock import MagicMock

import pytest

from fastapi_app.services.ocr._order_match import match_product_robust
from fastapi_app.services.ocr_fuzzy_match import fuzzy_match_product

# 生产库真实产品名（只读查询得到的原样名称）
REAL = [
    '咸鱼按摩捶',
    '鲨鱼',
    '《蛋仔派对》市集拾趣系列 毛绒公仔挂件盲盒',
    '《蛋仔派对》团子木鱼毛绒挂件盲盒',
    '《蛋仔派对》团子木鱼毛绒挂件盲盒-黄蛋 陈列样',
]

_IP = ['《蛋仔派对》', '《宝可梦》', '《线条小狗》', '《名侦探柯南》', '《小黄人》']
_SERIES = ['市集拾趣系列', '街头美食系列', '春日野餐系列', '深海奇遇系列', '办公室日常系列']
_THING = ['团子木鱼', '毛绒公仔', '卡皮巴拉', '小熊', '海豚', '猫头鹰', '水獭', '兔子']
_TAIL = ['挂件', '挂件盲盒', '抱枕', '摆件']

_FILLER = '的了个和与在'
_NOISE_WORDS = ['加急', '发货期', '菲菲', '待确认', '样', '现货', '补货']


def _synthetic(count: int) -> list[str]:
    r = random.Random(20260929)
    return [
        f'{r.choice(_IP)}{r.choice(_SERIES)} {r.choice(_THING)}{r.choice(_TAIL)}'
        for _ in range(count)
    ]


def _insert(s, r):
    p = r.randrange(len(s) + 1)
    return s[:p] + r.choice(_FILLER) + s[p:]


def _delete(s, r):
    p = r.randrange(len(s))
    return s[:p] + s[p + 1:]


def _substitute(s, r):
    p = r.randrange(len(s))
    return s[:p] + r.choice(_FILLER) + s[p + 1:]


def _affix(s, r):
    return f'{r.choice(_NOISE_WORDS)} {s} {r.choice(_NOISE_WORDS)}'


def _space(s, r):
    p = r.randrange(1, max(2, len(s)))
    return s[:p] + ' ' + s[p:]


def _dup(s, r):
    p = r.randrange(len(s) - 1)
    k = r.randrange(2, 4)
    return s[:p] + s[p:p + k] + s[p:]


_NOISES = [_insert, _delete, _substitute, _affix, _space, _dup]


def _product(pid: int, name: str) -> MagicMock:
    p = MagicMock()
    p.id, p.name, p.barcode = pid, name, ''
    return p


def _evaluate(names: list[str], trials: int) -> dict:
    """返回 {正确, 错配, 未命中, 总数}"""
    items = [_product(i + 1, n) for i, n in enumerate(names)]
    product_map = {p.name.lower().strip(): p for p in items}
    correct = wrong = miss = 0
    for name in names:
        for noise in _NOISES:
            # 种子必须跨进程稳定：hash(str) 按 PYTHONHASHSEED 加盐，同一文件两次
            # 运行生成不同噪声 → 阈值断言（recall>=95%）在边界处不可复现（Erratic
            # Test，2026-10-15 修）。crc32 无盐，测试因此确定性。
            r = random.Random(zlib.crc32(name.encode('utf-8')) & 0xFFFF)
            for _ in range(trials):
                variant = noise(name, r)
                if not variant.strip():
                    continue
                got, _confidence = match_product_robust(variant, items, product_map)
                got_name = getattr(got, 'name', None)
                if got_name == name:
                    correct += 1
                elif got_name is None:
                    miss += 1
                else:
                    wrong += 1
    return {'correct': correct, 'wrong': wrong, 'miss': miss,
            'total': correct + wrong + miss}


class TestAccuracyOnRealCatalog:
    """真实库上的召回与精确（最要紧的一组）"""

    @pytest.fixture(scope='class')
    def stats(self):
        return _evaluate(REAL, trials=8)

    def test_recall_at_least_95_percent(self, stats):
        assert stats['correct'] / stats['total'] >= 0.95, stats

    def test_no_wrong_match_on_real_catalog(self, stats):
        """真实库上错配必须为 0：宁可让人手选，也不能挂错产品"""
        assert stats['wrong'] == 0, stats

    def test_real_catalog_beats_shared_matcher_alone(self):
        """兜底层的存在价值：真实库上必须比单用共享匹配器更好"""
        items = [_product(i + 1, n) for i, n in enumerate(REAL)]
        product_map = {p.name.lower().strip(): p for p in items}
        base = fallback = 0
        total = 0
        for name in REAL:
            for noise in _NOISES:
                r = random.Random(zlib.crc32(name.encode('utf-8')) & 0xFFFF)
                for _ in range(8):
                    variant = noise(name, r)
                    if not variant.strip():
                        continue
                    total += 1
                    base += getattr(fuzzy_match_product(variant, items, product_map)[0], 'name', None) == name
                    fallback += getattr(match_product_robust(variant, items, product_map)[0], 'name', None) == name
        assert fallback > base, {'baseline': base, 'with_fallback': fallback, 'total': total}


class TestAccuracyOnSyntheticCatalog:
    """更大库上的召回（重名变体多，主要看不会整体崩）"""

    @pytest.fixture(scope='class')
    def stats(self):
        return _evaluate(_synthetic(30), trials=4)

    def test_recall_at_least_90_percent(self, stats):
        assert stats['correct'] / stats['total'] >= 0.90, stats


class TestFalsePositives:
    """保守性：无关文本不该被匹配到任何产品"""

    def test_random_strings_rarely_match(self):
        names = REAL + _synthetic(30)
        items = [_product(i + 1, n) for i, n in enumerate(names)]
        product_map = {p.name.lower().strip(): p for p in items}
        r = random.Random(7)
        pool = '鲨鱼咸按摩捶蛋仔派队市集拾趣系列团子木鱼毛绒公仔挂件盲盒黄陈列样测试甲乙丙丁戊己庚辛'
        total = 500
        matched = 0
        for _ in range(total):
            s = ''.join(r.choice(pool) for _ in range(r.randrange(2, 10)))
            got, _c = match_product_robust(s, items, product_map)
            matched += got is not None
        assert matched / total <= 0.02, f'{matched}/{total}'

    def test_unrelated_phrases_do_not_match(self):
        items = [_product(i + 1, n) for i, n in enumerate(REAL)]
        product_map = {p.name.lower().strip(): p for p in items}
        for raw in ['随便写的一段话', '张三李四王五', '会议纪要', '本月合计', '待办事项']:
            got, _c = match_product_robust(raw, items, product_map)
            assert got is None, raw
