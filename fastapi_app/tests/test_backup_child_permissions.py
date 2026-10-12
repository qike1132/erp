"""数据备份的 4 个细粒度子权限：迁移与空库种子必须口径一致（2026-10-12）。

背景：备份端点走 `require_any_permission(<细粒度码>, 'backup_manage')`，但这 4 个码
在**全仓（种子/迁移）与生产库都不存在**——细粒度授权成了死配置。修复落在两处，必须一致：

  - 存量库：迁移 pg_standalone_093_backup_child_permissions
  - 空库重建：scripts/init_permissions.py 的 backup 模块

本测试锁住「两处一致」：任一处单独改动即变红。
"""

import importlib.util
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MIGRATION = (
    _REPO_ROOT / "migrations" / "versions" / "pg_standalone_093_backup_child_permissions.py"
)
_INIT_PERMS = _REPO_ROOT / "scripts" / "init_permissions.py"

# 手工推导的期望名（对齐 _deps.py 的权限映射注释：查看/创建/恢复/删除备份）
_EXPECTED = {
    "backup_read": "查看备份",
    "backup_create": "创建备份",
    "backup_restore": "恢复备份",
    "backup_delete": "删除备份",
}


def _load_migration():
    """按文件路径加载迁移模块（migrations/versions 不是包，不能用 import 语句）。"""
    spec = importlib.util.spec_from_file_location("mig_093_backup_children", _MIGRATION)
    assert spec is not None and spec.loader is not None, f"无法加载迁移文件：{_MIGRATION}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_inserts_exactly_the_four_fine_grained_codes():
    rows = {code: name for code, name, _offset in _load_migration()._ROWS}
    assert rows == _EXPECTED


def test_init_permissions_matches_migration():
    """空库重建口径必须与迁移一致（少改一处就会漂移）。"""
    text = _INIT_PERMS.read_text(encoding="utf-8")
    missing = [
        f"{code} -> {name}"
        for code, name in _EXPECTED.items()
        if f"{{'code': '{code}', 'name': '{name}'}}" not in text
    ]
    assert not missing, (
        "scripts/init_permissions.py 与迁移 pg_standalone_093 的备份子权限不一致，缺：\n  "
        + "\n  ".join(missing)
        + "\n新增/改名必须同时改迁移（存量库）与 init_permissions（空库重建）。"
    )
