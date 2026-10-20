"""死代码删除的**残留**回归（审计 F1-5 / F4-5 闭环）。

背景
----
备份域死代码群（Z05-R18，约 1200+ 行）分批删除时，只删了代码，**没清引用**：
  - `mypy.ini` 的 files 白名单仍指向已删除的 4 个模块（chunks / format_storage /
    format_strategy / format_types）→ CI 的 check_orphan_modules.py 报
    「[A] mypy.ini 白名单指向不存在的模块」并以退出码 1 **阻断** lint job；
  - `fastapi_app/services/backup/__init__.py` 的 `__all__` 仍导出已删除的
    `split_backup_into_chunks` → `from fastapi_app.services.backup import *`
    会直接 AttributeError。

本文件把这两条钉死：白名单不得指向不存在的文件，公开导出不得指向不存在的符号。
"""
import configparser
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent


def _mypy_whitelist() -> list[str]:
    parser = configparser.ConfigParser()
    parser.read(ROOT / 'mypy.ini', encoding='utf-8')
    raw = parser['mypy']['files']
    return [item.strip() for item in raw.replace('\n', ' ').split(',') if item.strip()]


def test_mypy_whitelist_has_no_dangling_entries():
    """白名单里的每个文件都必须真实存在（删文件时必须同步删条目）。"""
    missing = [rel for rel in _mypy_whitelist() if not (ROOT / rel).is_file()]
    assert not missing, f'mypy.ini 白名单指向不存在的模块（删除文件后未同步）: {missing}'


def test_backup_package_exports_have_no_dangling_names():
    """备份包的 __all__ 不得导出已被删除的符号。"""
    import fastapi_app.services.backup as backup

    missing = [name for name in backup.__all__ if not hasattr(backup, name)]
    assert not missing, f'services/backup.__all__ 导出了不存在的符号: {missing}'


@pytest.mark.parametrize('name', [
    'split_backup_into_chunks',
    'create_backup_chunks',
    'restore_from_chunks',
    'DefaultBackupFormatStrategy',
    'LocalBackupStorage',
])
def test_removed_backup_symbols_are_gone(name):
    """Z05-R18 删除的平行实现不得以任何形式复活（含 __all__ 残留）。"""
    import fastapi_app.services.backup as backup

    assert not hasattr(backup, name)
    assert name not in backup.__all__


def test_orphan_utils_module_is_removed():
    """utils/performance_monitor.py 是零入边孤儿（职责已在 core/middleware.py）。

    它让 CI 的孤儿模块检查（阻断型步骤）长期红灯，必须保持删除状态。
    """
    assert not (ROOT / 'utils' / 'performance_monitor.py').exists()


def test_no_production_code_references_performance_monitor():
    """删掉孤儿模块后，生产代码里不得再留下指向它的引用。"""
    offenders: list[str] = []
    for path in (ROOT / 'fastapi_app').rglob('*.py'):
        parts = path.parts
        if '__pycache__' in parts or 'tests' in parts:
            continue
        text = path.read_text(encoding='utf-8', errors='replace')
        if 'performance_monitor' in text:
            offenders.append(str(path.relative_to(ROOT)))
    assert not offenders, f'生产代码仍引用已删除的 performance_monitor: {offenders}'
