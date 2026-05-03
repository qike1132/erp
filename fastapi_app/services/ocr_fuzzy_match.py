"""
OCR 模糊匹配工具

从 ocr_service.py 拆分，提供产品和客户的模糊匹配算法。
不依赖任何 OCR 引擎或数据库模型，纯文本匹配逻辑。
"""
import logging
import re

logger = logging.getLogger(__name__)


def _levenshtein_similarity(s1: str, s2: str) -> float:
    """计算 Levenshtein 编辑距离相似度（0.0 ~ 1.0）"""
    if not s1 or not s2:
        return 0.0
    if s1 == s2:
        return 1.0

    len1, len2 = len(s1), len(s2)
    if abs(len1 - len2) > max(len1, len2) * 0.4:
        return 0.0

    prev = list(range(len2 + 1))
    for i in range(1, len1 + 1):
        curr = [i] + [0] * len2
        for j in range(1, len2 + 1):
            cost = 0 if s1[i - 1] == s2[j - 1] else 1
            curr[j] = min(curr[j - 1] + 1, prev[j] + 1, prev[j - 1] + cost)
        prev = curr

    max_len = max(len1, len2)
    return 1.0 - prev[len2] / max_len


def _extract_keywords(text: str) -> list[str]:
    """从文本中提取核心关键字"""
    cleaned = re.sub(r'[（(][^）)]*[）)]', '', text)
    cleaned = re.sub(r'^\d+cm|^[\d.]+寸|^[\d.]+m|^尺寸', '', cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.strip()

    keywords = []
    for match in re.finditer(r'[\u4e00-\u9fa5]{2,}', cleaned):
        kw = match.group()
        if kw not in ('系列', '型号', '款式', '颜色', '规格', '尺寸', '数量'):
            keywords.append(kw)

    for match in re.finditer(r'[a-zA-Z]{2,}[a-zA-Z0-9]*', cleaned):
        keywords.append(match.group().upper())

    return keywords


def _keyword_match_score(ocr_text: str, db_text: str) -> float:
    """基于关键字提取的匹配评分"""
    ocr_kws = set(_extract_keywords(ocr_text))
    db_kws = set(_extract_keywords(db_text))

    if not ocr_kws or not db_kws:
        return 0.0

    intersection = ocr_kws & db_kws
    if not intersection:
        for ok in ocr_kws:
            for dk in db_kws:
                if ok in dk or dk in ok:
                    intersection.add(ok)
                    break

    union = ocr_kws | db_kws
    return len(intersection) / len(union) if union else 0.0


def fuzzy_match_product(
    ocr_name: str,
    all_products: list,
    product_map: dict,
    min_similarity: float = 0.7,
) -> tuple[object | None, float]:
    """模糊匹配产品

    匹配优先级：精确 > 子串包含 > 关键字 > 编辑距离
    """
    if not ocr_name:
        return None, 0.0

    ocr_lower = ocr_name.lower().strip()

    product = product_map.get(ocr_lower)
    if product:
        return product, 1.0
    product = product_map.get(ocr_name)
    if product:
        return product, 1.0

    best_product = None
    best_score = 0.0

    for p in all_products:
        db_name = p.name.strip()
        db_lower = db_name.lower()

        if ocr_lower in db_lower or db_lower in ocr_lower:
            len_ratio = min(len(ocr_name), len(db_name)) / max(len(ocr_name), len(db_name))
            score = 0.75 + 0.25 * len_ratio
            if score > best_score:
                best_score = score
                best_product = p
            continue

        kw_score = _keyword_match_score(ocr_name, db_name)
        if kw_score >= 0.6 and kw_score > best_score:
            best_score = kw_score
            best_product = p
            continue

        sim = _levenshtein_similarity(ocr_lower, db_lower)
        if sim >= min_similarity and sim > best_score:
            best_score = sim
            best_product = p

    if best_product and best_score >= min_similarity:
        return best_product, round(best_score, 3)

    return None, 0.0


def fuzzy_match_customer(
    ocr_name: str,
    all_customers: list,
    min_similarity: float = 0.7,
) -> tuple[object | None, float]:
    """模糊匹配客户

    匹配优先级：精确(含去后缀) > 子串包含 > 关键字 > 编辑距离
    """
    if not ocr_name:
        return None, 0.0

    ocr_clean = ocr_name.strip()
    ocr_lower = ocr_clean.lower()

    _suffixes = ['有限公司', '有限责任公司', '股份有限公司', '公司', '集团', 'Co.', 'Ltd.', 'Inc.']
    ocr_core = ocr_clean
    for s in _suffixes:
        if ocr_clean.endswith(s):
            ocr_core = ocr_clean[:-len(s)]
            break

    best_customer = None
    best_score = 0.0

    for c in all_customers:
        db_name = c.name.strip()
        db_lower = db_name.lower()

        if ocr_lower == db_lower:
            return c, 1.0

        db_core = db_name
        for s in _suffixes:
            if db_name.endswith(s):
                db_core = db_name[:-len(s)]
                break
        if ocr_core.lower() == db_core.lower():
            return c, 0.95

        if ocr_lower in db_lower or db_lower in ocr_lower:
            len_ratio = min(len(ocr_clean), len(db_name)) / max(len(ocr_clean), len(db_name))
            score = 0.75 + 0.25 * len_ratio
            if score > best_score:
                best_score = score
                best_customer = c
            continue

        ocr_core_lower = ocr_core.lower()
        db_core_lower = db_core.lower()
        if ocr_core_lower in db_core_lower or db_core_lower in ocr_core_lower:
            len_ratio = min(len(ocr_core), len(db_core)) / max(len(ocr_core), len(db_core))
            score = 0.72 + 0.25 * len_ratio
            if score > best_score:
                best_score = score
                best_customer = c
            continue

        kw_score = _keyword_match_score(ocr_clean, db_name)
        if kw_score >= 0.6 and kw_score > best_score:
            best_score = kw_score
            best_customer = c
            continue

        sim = _levenshtein_similarity(ocr_lower, db_lower)
        if sim >= min_similarity and sim > best_score:
            best_score = sim
            best_customer = c

    if best_customer and best_score >= min_similarity:
        return best_customer, round(best_score, 3)

    return None, 0.0
