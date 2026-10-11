"""运行时按需依赖白名单守卫（2026-10-11 复核 P2-16）。

python-multipart / tzdata 是「代码内零显式 import」的运行时按需依赖：
- python-multipart：FastAPI UploadFile 的解析后端，缺失时上传接口运行时 500；
- tzdata：Windows 无系统 tz 库，ZoneInfo('Asia/Shanghai') 按需加载，缺失即抛
  ZoneInfoNotFoundError（编号日期段北京口径全挂）。

静态工具（依赖审计/死代码分析）易把它们误判为可删，本测试锁住声明。
"""

from __future__ import annotations

from pathlib import Path

BASE_TXT = Path(__file__).resolve().parents[2] / "requirements" / "base.txt"


def test_python_multipart_declared_in_base() -> None:
    lines = BASE_TXT.read_text(encoding="utf-8").splitlines()
    idx = next(i for i, l in enumerate(lines) if l.startswith("python-multipart=="))
    assert idx > 0, "python-multipart 必须声明在 base.txt（FastAPI 上传运行时依赖）"
    before = "\n".join(lines[max(0, idx - 6):idx])
    assert "上传" in before, "须保留按需依赖说明注释"


def test_tzdata_declared_in_base() -> None:
    content = BASE_TXT.read_text(encoding="utf-8")
    assert any(l.startswith("tzdata>=") for l in content.splitlines()), (
        "tzdata 必须声明在 base.txt（Windows ZoneInfo 运行时依赖）"
    )


def test_zoneinfo_loads_on_windows() -> None:
    """业务时区可直接实例化（tzdata 在位）。"""
    from zoneinfo import ZoneInfo

    tz = ZoneInfo("Asia/Shanghai")
    assert str(tz) == "Asia/Shanghai"
