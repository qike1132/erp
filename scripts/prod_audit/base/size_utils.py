"""产物体积判据的共享实现（BUNDLE-SIZE 类规则）。

判据是「gzip 后 ≤ 2MB」（见 l1/l7 两层 docstring）。此前两条规则都误用**原始
字节**求体积 —— js 原始字节 3.31MB 时双双误报，而 gzip(9) 后仅约 1.05MB，按规则
自身的判据本应 PASS（评审 2026-10-11）。gzip 级别统一取 9。
"""
from __future__ import annotations

import gzip
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def gzip_size(path: Path) -> int:
    """文件以 ``gzip(level=9)`` 压缩后的字节数。

    读不出内容时**回退到原始大小** —— 体积门禁宁可高估不可低估，绝不能因读取
    失败而漏报超限（这正是本模块要修的那类「门禁说谎」）。原始大小也取不到才返回 0。
    """
    try:
        data = path.read_bytes()
    except OSError as e:
        logger.warning("读取 %s 失败，回退原始大小: %s", path, e)
        try:
            return path.stat().st_size
        except OSError:
            return 0
    return len(gzip.compress(data, 9))
