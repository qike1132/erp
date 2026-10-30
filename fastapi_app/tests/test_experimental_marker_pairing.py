"""experimental 排除项与标记必须成对（2026-10-30 审计 B-M6）。

`.coveragerc` 把未接线模块排除出覆盖率，`pytest.ini` 登记 `experimental` 标记；
两处必须同时存在/同时移除，否则「接线后忘记撤排除」会让覆盖率静默漏掉新代码。
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COVERAGERC = ROOT / ".coveragerc"
PYTEST_INI = ROOT / "pytest.ini"


def test_experimental_module_is_declared_in_both_places():
    cover = COVERAGERC.read_text(encoding="utf-8")
    ini = PYTEST_INI.read_text(encoding="utf-8")

    assert "purchase_order_spare.py" in cover, "覆盖率排除项缺失"
    assert "experimental:" in ini, "pytest.ini 未登记 experimental 标记"
    assert "experimental" in ini.split("markers =", 1)[-1], "markers 段未包含 experimental"
