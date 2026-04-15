"""
模糊搜索工具模块
使用rapidfuzz实现模糊匹配（已移除废弃的fuzzywuzzy依赖）
"""

try:
    from rapidfuzz import fuzz, process
    HAS_RAPIDFUZZ = True
except ImportError:
    HAS_RAPIDFUZZ = False

from typing import List, Tuple, Any, Optional


class FuzzySearcher:
    """模糊搜索器"""

    def __init__(self, items: List[Any], key_func=None):
        """
        初始化

        Args:
            items: 搜索项列表
            key_func: 提取搜索键的函数
        """
        self.items = items
        self.key_func = key_func or (lambda x: str(x))
        self.choices = {i: self.key_func(item) for i, item in enumerate(items)}

    def search(self, query: str, threshold: int = 70,
               limit: int = 10) -> List[Tuple[Any, int]]:
        """
        模糊搜索

        Args:
            query: 搜索词
            threshold: 相似度阈值 (0-100)
            limit: 返回数量限制

        Returns:
            [(匹配项, 相似度), ...]
        """
        if not query or not HAS_RAPIDFUZZ:
            return []

        results = process.extract(
            query,
            self.choices,
            limit=limit,
            scorer=fuzz.WRatio
        )

        return [(self.items[r[2]], r[1]) for r in results if r[1] >= threshold]

    def find_duplicates(self, threshold: int = 90) -> List[Tuple[Any, Any, int]]:
        """
        查找重复项

        Args:
            threshold: 相似度阈值

        Returns:
            [(项1, 项2, 相似度), ...]
        """
        if not HAS_RAPIDFUZZ:
            return []

        duplicates = []
        keys = list(self.choices.keys())

        for i in range(len(keys)):
            for j in range(i + 1, len(keys)):
                score = fuzz.ratio(
                    self.choices[keys[i]],
                    self.choices[keys[j]]
                )

                if score >= threshold:
                    duplicates.append((
                        self.items[keys[i]],
                        self.items[keys[j]],
                        score
                    ))

        return duplicates


def fuzzy_match(query: str, choices: dict, threshold: int = 70,
                limit: int = 10) -> List[Tuple[str, int, Any]]:
    """
    快速模糊匹配

    Args:
        query: 搜索词
        choices: {key: value} 字典
        threshold: 相似度阈值
        limit: 返回数量限制

    Returns:
        [(匹配值, 相似度, 原始key), ...]
    """
    if not query or not HAS_RAPIDFUZZ:
        return []

    results = process.extract(
        query,
        choices,
        limit=limit,
        scorer=fuzz.WRatio
    )

    return [(r[0], r[1], r[2]) for r in results if r[1] >= threshold]
