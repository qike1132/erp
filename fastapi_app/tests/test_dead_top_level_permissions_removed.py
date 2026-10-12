"""三个「有权限行、无任何功能」的死顶层权限必须保持被清理（2026-10-12）。

背景：/user「分配权限」弹窗的「其他操作权限」区会列出所有 is_nav=false 的顶层权限。
其中 finance_view / permission_manage / app_update_manage 全仓零引用——没有前端路由、
没有视图、没有后端端点、没有 nginx 配置，是历史开发遗留（用户报障「我都没有这 2 个路由」）。
清理：迁移 092 删库行 + seed_nav.py 删定义。

⚠️ 只删库不够——`seed_nav.py` 是幂等重种的（缺则 INSERT），定义还在就会被种回来。
本测试同时锁住「迁移删哪些」与「种子不再定义」，任一处回退即变红。
"""

import importlib.util
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MIGRATION = (
    _REPO_ROOT
    / "migrations"
    / "versions"
    / "pg_standalone_092_drop_dead_top_level_permissions.py"
)
_SEED = _REPO_ROOT / "scripts" / "seed_nav.py"

_DEAD = ("finance_view", "permission_manage", "app_update_manage")


def _load_migration():
    """按文件路径加载迁移模块（migrations/versions 不是包，不能用 import 语句）。"""
    spec = importlib.util.spec_from_file_location("mig_092_drop_dead_perms", _MIGRATION)
    assert spec is not None and spec.loader is not None, f"无法加载迁移文件：{_MIGRATION}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_drops_exactly_the_three_dead_codes():
    assert tuple(_load_migration()._DROP_CODES) == _DEAD


def test_migration_restore_rows_cover_the_same_codes():
    """downgrade 的还原行必须覆盖同样的三个码，否则回滚会漏掉。"""
    restore = {row[0] for row in _load_migration()._RESTORE_ROWS}
    assert restore == set(_DEAD)


def test_seed_nav_no_longer_defines_them():
    """种子是幂等重种的权威来源——定义还在，跑一次脚本就把它们种回库里了。"""
    text = _SEED.read_text(encoding="utf-8")
    still = [code for code in _DEAD if f"'code': '{code}'" in text]
    assert not still, (
        "scripts/seed_nav.py 仍在定义已清理的死权限，跑一次种子脚本就会把它们种回库里：\n  "
        + "\n  ".join(still)
    )
