"""订单 OCR 的产品匹配（含「名称被污染」兜底）

先走共享的 `fuzzy_match_product`；它不中时再用本模块的**包含度**兜底。

为什么需要兜底：OCR 会把无关文字粘在产品名上（备注列、列名、上一行漏下来的尾列），
例如原图识别出「菲菲团子木鱼毛绒挂件盲盒发潜伏期」，而库内是
「《蛋仔派对》团子木鱼毛绒挂件盲盒」。共享匹配器的关键词切分对**整段无标点的中文**
只会切出一个长 token，跟库内的两个关键词都对不上，于是得分 **0.00**；
而把干净核心「团子木鱼毛绒挂件盲盒」单独匹配是 **0.91**。

兜底的做法正是「先把真正用到的名称认出来，再匹配」：对每个库内产品，
取原图文字与产品名的**最长公共子串**，看它覆盖了产品名的多少——覆盖不足则不算命中。

⚠️ 这条兜底只在共享匹配器没给出可信结果时才跑，且它的产出在弹窗里是**待人工确认的
建议**（同时展示原图识别文本），因此不会静默写错。刻意不去改共享匹配器：它同时服务
出货单导入，放宽阈值会影响那条链路。
"""
import re

from fastapi_app.services.ocr_fuzzy_match import fuzzy_match_product

# 采纳兜底匹配所需的产品名覆盖率（产品名的多少字符被原图文字覆盖）
ROBUST_MIN_COVERAGE = 0.7

# 参与累计的公共片段最小长度。定 3 是为了挡掉「按摩」这类 2 字巧合包含
ROBUST_MIN_RUN = 3

# 覆盖字符数的绝对下限
ROBUST_MIN_COVERED = 4

# 「短名称」兜底：字数不超过它时，按「至多差一个字符」来认。
# 用途是 OCR 把近乎独立的产品名多插/漏一个字（实测「鲨的鱼」对应库内「鲨鱼」）。
SHORT_NAME_MAX = 6

# 短名称兜底的下限：两字输入与两字产品名「差一个字」等于差一半，太容易凑上
SHORT_NAME_MIN = 3

# 短名称兜底给出的置信度：认定为命中，但低于精确匹配，弹窗里一眼可辨
SHORT_MATCH_CONFIDENCE = 0.9

# 只统计有信息量的字符：汉字、字母、数字。标点（《》（）空格等）不计，
# 否则产品名里的书名号会把分母抬高、把覆盖率压低。
_MEANINGFUL_RE = re.compile(r'[一-龥a-zA-Z0-9]')


def meaningful_len(text: str) -> int:
    return len(_MEANINGFUL_RE.findall(text))


def longest_common_substring_len(a: str, b: str) -> int:
    """最长公共子串长度（经典 DP）。"""
    if not a or not b:
        return 0
    prev = [0] * (len(b) + 1)
    best = 0
    for ch_a in a:
        curr = [0] * (len(b) + 1)
        for j, ch_b in enumerate(b, start=1):
            if ch_a == ch_b:
                curr[j] = prev[j - 1] + 1
                if curr[j] > best:
                    best = curr[j]
        prev = curr
    return best


def covered_chars(text: str, target: str, min_run: int = ROBUST_MIN_RUN) -> int:
    """target 中有多少字符被 text 中**长度 ≥ min_run 的连续片段**覆盖。

    刻意不用「最长公共子串」：原图名称被插入/截断时会把片段切成两半，单段再长也不够。
    例如「市集拾趣系列试读毛绒公仔挂件盲盒」对「…市集拾趣系列 毛绒公仔挂件盲盒」，
    被插入的「试读」切成 6 字 + 8 字两段——最长段只有 8/18，但累计覆盖是 14/18。
    """
    n, m = len(text), len(target)
    if n == 0 or m == 0:
        return 0
    # 先各自归一化为「有信息量的字符」再比对：否则原文里的书名号会算进命中数，
    # 而分母（meaningful_len）不含标点，两边口径不一致会让覆盖率虚高。
    text = ''.join(_MEANINGFUL_RE.findall(text))
    target = ''.join(_MEANINGFUL_RE.findall(target))
    n, m = len(text), len(target)
    if n == 0 or m == 0:
        return 0
    marked = [False] * m
    for j in range(m):
        for i in range(n):
            if text[i] != target[j]:
                continue
            # 只从片段起点开始数，避免同一片段被重复计入
            if i > 0 and j > 0 and text[i - 1] == target[j - 1]:
                continue
            length = 0
            while i + length < n and j + length < m and text[i + length] == target[j + length]:
                length += 1
            if length >= min_run:
                for k in range(j, j + length):
                    marked[k] = True
    return sum(marked)


def one_edit_equal(a: str, b: str) -> bool:
    """a 与 b 是否至多相差一个字符（增、删、改其一）"""
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        # 等长（上面的守卫已保证），strict=True 把这个不变量写实
        return sum(1 for x, y in zip(a, b, strict=True) if x != y) <= 1
    short, longer = (a, b) if len(a) < len(b) else (b, a)
    i = j = 0
    used_skip = False
    while i < len(short) and j < len(longer):
        if short[i] == longer[j]:
            i += 1
            j += 1
        elif used_skip:
            return False
        else:
            used_skip = True
            j += 1
    return True


def _match_short_name(raw: str, all_products: list) -> object | None:
    """短名称兜底：原图文字是「近乎独立的产品名」且只差一个字时认下来。

    例：OCR 把「鲨鱼」读成「鲨的鱼」（多插一个「的」），此时按覆盖率是认不出来的
    ——覆盖率问的是「产品名有多少出现在原图里」，输入比产品名短时天然无效。
    这里换成正向判断：两者归一化后是否至多差一个字符。

    只对短输入启用（≤ SHORT_NAME_MAX 字）：长字符串之间「差一个字符」几乎必然成立，
    那样会把任意文本都凑到某个产品上。命中的选最短产品名（最具体的一个）。
    """
    core = ''.join(_MEANINGFUL_RE.findall(raw))
    # 下限取 3：两字输入与两字产品名「差一个字」等于差一半，太容易凑上
    # （实测「鱼鱼」会凑到「鲨鱼」）。两字只能靠精确或共享匹配。
    if not SHORT_NAME_MIN <= len(core) <= SHORT_NAME_MAX:
        return None
    candidates = []
    for candidate in all_products:
        name_core = ''.join(_MEANINGFUL_RE.findall(str(getattr(candidate, 'name', '') or '')))
        if name_core and one_edit_equal(core, name_core):
            candidates.append((len(name_core), candidate))
    if not candidates:
        return None
    return min(candidates, key=lambda pair: pair[0])[1]


def _match_via_shared(
    raw_name: str,
    all_products: list,
    product_map: dict,
) -> tuple[object | None, float]:
    """走共享匹配器；原样不中时再用「去掉所有空白」重试一次。

    空白差异不该导致失败：OCR 常在词间插入空格（实测「鲨 鱼」对库内「鲨鱼」），
    而共享匹配器是按原样比对的。
    """
    product, confidence = fuzzy_match_product(raw_name, all_products, product_map)
    if product is not None:
        return product, confidence
    compact = ''.join(str(raw_name or '').split())
    if compact and compact != str(raw_name or ''):
        product, confidence = fuzzy_match_product(compact, all_products, product_map)
        if product is not None:
            return product, confidence
    return None, 0.0


def _best_by_coverage(raw: str, all_products: list) -> tuple[object | None, tuple[int, float]]:
    """按「产品名被原图文字覆盖了多少」选最优，返回 (产品 | None, (覆盖字符数, 覆盖率))"""
    best: object | None = None
    best_key = (0, 0.0)
    # 输入太短时这条路天然算不出（分母是产品名长度），跳过而不是提前返回，
    # 否则会连后面的短名称兜底一起错过。
    if meaningful_len(raw) < ROBUST_MIN_COVERED:
        return None, best_key
    for candidate in all_products:
        name = str(getattr(candidate, 'name', '') or '').strip()
        denom = meaningful_len(name)
        if denom == 0:
            continue
        covered = covered_chars(raw, name)
        if covered < ROBUST_MIN_COVERED:
            continue
        coverage = covered / denom
        if coverage < ROBUST_MIN_COVERAGE:
            continue
        key = (covered, coverage)
        if key > best_key:
            best, best_key = candidate, key
    return best, best_key


def match_product_robust(
    raw_name: str,
    all_products: list,
    product_map: dict,
) -> tuple[object | None, float]:
    """共享匹配器 + 兜底层，取「解释原图文字更多」的那个。返回 (产品 | None, 置信度)

    为什么不是「共享匹配器不中才兜底」：近似重名（`…挂件盲盒` 与 `…挂件盲盒-黄蛋 陈列样`）
    里，共享匹配器会因**子串包含**先命中较短的那个并直接返回，更长更具体的正确产品
    就永远没机会——实测真实库上会因此错配。改成两者都算、按「覆盖了原图多少字」择优，
    并列时保留共享匹配器的结果（不改变既有判定）。
    """
    shared, shared_confidence = _match_via_shared(raw_name, all_products, product_map)
    raw = (raw_name or '').strip()
    best, best_key = _best_by_coverage(raw, all_products)

    if shared is not None and best is not None:
        # 覆盖字符更多 = 解释原图文字更充分 = 更具体的那个产品
        if best_key[0] > covered_chars(raw, str(getattr(shared, 'name', '') or '')):
            return best, round(best_key[1], 4)
        return shared, shared_confidence
    if shared is not None:
        return shared, shared_confidence
    if best is not None:
        return best, round(best_key[1], 4)

    short = _match_short_name(raw, all_products)
    if short is not None:
        return short, SHORT_MATCH_CONFIDENCE
    return None, 0.0
