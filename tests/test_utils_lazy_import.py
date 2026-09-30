"""守卫 ``utils`` 包的惰性导出（PEP 562）。

背景：``utils/__init__.py`` 此前在 import 期 eager 导入 ``batch_upload_utils``
（硬要求 polars + openpyxl）与 ``logger``（sqlalchemy）。桌面壳（PyInstaller 打包，
spec 明确 exclude 这些重依赖）一旦 ``import utils.log_rotation`` 就在启动期
ImportError —— 这正是「轮转实现只能自带一份、与后端各写一套」的根因。

本测试在**子进程**里验证（同进程会受其它测试已导入的模块污染）：
1. ``import utils.log_rotation`` 不会把 openpyxl / polars / sqlalchemy 拉进 sys.modules；
2. 包级旧名字（``utils.logger`` 等）仍可取到 —— 惰性只是延后，不是删除契约。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
HEAVY = ('openpyxl', 'polars', 'sqlalchemy')


def _run(source: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, '-c', source],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=120,
    )


def test_leaf_import_does_not_pull_heavy_deps() -> None:
    code = (
        'import sys\n'
        'import utils.log_rotation\n'
        f'leaked = [m for m in {HEAVY!r} if m in sys.modules]\n'
        'print("|".join(leaked))\n'
    )
    result = _run(code)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == '', f'惰性导入被破坏，连带拉起重依赖: {result.stdout.strip()}'


def test_package_level_names_still_available() -> None:
    """``from utils import logger`` 这类旧用法经 __getattr__ 惰性解析后仍可用。"""
    code = (
        'from utils import logger\n'
        'print("ok" if logger is not None else "none")\n'
    )
    result = _run(code)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == 'ok'


def test_unknown_attribute_raises() -> None:
    result = _run('import utils\nutils.not_a_real_name\n')
    assert result.returncode != 0
    assert 'AttributeError' in result.stderr
