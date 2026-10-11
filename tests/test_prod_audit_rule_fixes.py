"""prod_audit 规则修复的回归护栏（评审 2026-10-11）。

1. L8 健康端点探测：旧正则只认 ``@app.get`` 装饰器，而 ``core/health.py`` 的探针
   全是**命令式** ``app.get(...)(handler)`` → 稳定误报。本测试锁死「新正则能从
   health.py 源码识别出全部健康端点路径」。
2. BUNDLE-SIZE 类规则：判据是「gzip 后 ≤ 2MB」，旧实现误用原始字节 → 误报。
   本测试锁死 ``gzip_size`` 返回的是**压缩后**字节数。
"""
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_HEALTH_PY = _REPO_ROOT / "fastapi_app" / "core" / "health.py"


def test_l8_route_re_matches_command_style_health_registration():
    """L8 的路由正则 + 路径常量必须能从 health.py 识别出全部健康端点。"""
    from scripts.prod_audit.layers.l8_observability import (
        _HEALTH_ENDPOINT_PATHS,
        _ROUTE_RE,
    )

    src = _HEALTH_PY.read_text(encoding="utf-8")
    found = {m.group(1) for m in _ROUTE_RE.finditer(src)}
    missing = [p for p in _HEALTH_ENDPOINT_PATHS if p not in found]
    assert not missing, (
        f"L8 未从 core/health.py 识别出健康端点（命令式注册漏匹配）：{missing}"
    )


def test_gzip_size_measures_compressed_bytes(tmp_path):
    """gzip_size 必须返回压缩后字节数，而不是原始大小。"""
    from scripts.prod_audit.base.size_utils import gzip_size

    f = tmp_path / "bundle.js"
    f.write_bytes(b"var padding_abcdefgh = 1234567890;\n" * 5000)  # 高度可压缩
    raw = f.stat().st_size
    compressed = gzip_size(f)
    assert 0 < compressed < raw, f"gzip_size 未压缩：raw={raw} got={compressed}"
