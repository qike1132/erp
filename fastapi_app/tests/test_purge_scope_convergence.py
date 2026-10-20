"""审计 F1-6 回归：清库表清单收敛为唯一真相源（scripts/purge_scope.py）。

缺陷：六个清库脚本各自硬编码一份表清单（41 / 58 / 67 张互不同步），**漏表没有任何
自动发现手段** —— purge 漏 4 张 ORM 表（product_customer / finished_stock_remark /
import_file_registry / numbering_audit），cleanup_preserve_users 漏 28 张却打印
「其他数据已彻底清除」，dry-run 预览同样不显示。

修复：
  - 表清单集中在 scripts/purge_scope.py，按语义分 PRODUCTION / DEV_FULL /
    DEV_KEEP_USERS 三个范围；
  - 启动时对照 ORM metadata 做 fail-closed 覆盖校验（新增 ORM 表而未分类 → 拒绝执行）；
  - 漂移脚本移入 scripts/archive/ 并改为无条件拒绝执行。

本文件钉住：范围 ⇄ ORM 全覆盖、守卫真有牙（不是恒空断言）、脚本确实从唯一真相源
取清单、四个漏表已补齐、保留/清除集合不相交。
"""
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS = ROOT / 'scripts'

#: F1-6 实测 purge 曾漏清的 4 张 ORM 表（修复后必须进入清除范围）
PREVIOUSLY_MISSING = {
    'product_customer',
    'finished_stock_remark',
    'import_file_registry',
    'numbering_audit',
}


def _load_purge_scope():
    """按路径加载 scripts/purge_scope.py。

    必须先注册进 sys.modules —— 模块里有 @dataclass(frozen=True)，
    dataclasses 会回查 sys.modules[cls.__module__]，未注册时抛 AttributeError。
    """
    for path in (ROOT, SCRIPTS):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    if 'purge_scope' in sys.modules:
        return sys.modules['purge_scope']
    spec = importlib.util.spec_from_file_location('purge_scope', SCRIPTS / 'purge_scope.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules['purge_scope'] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope='module')
def scope():
    return _load_purge_scope()


@pytest.mark.parametrize('scope_name', ['PRODUCTION', 'DEV_FULL', 'DEV_KEEP_USERS'])
def test_every_scope_classifies_all_orm_tables(scope, scope_name):
    """任何范围都必须把每张 ORM 表归入「清」或「留」—— 漏表即红。"""
    assert scope.verify_coverage(scope.SCOPES[scope_name]) == []


@pytest.mark.parametrize('scope_name', ['PRODUCTION', 'DEV_FULL', 'DEV_KEEP_USERS'])
def test_no_scope_registers_deleted_tables(scope, scope_name):
    """清单里不得有已从 ORM 删除的表（否则 DELETE 会直接报错中断事务）。"""
    assert scope.verify_stale(scope.SCOPES[scope_name]) == []


@pytest.mark.parametrize('scope_name', ['PRODUCTION', 'DEV_FULL', 'DEV_KEEP_USERS'])
def test_keep_and_clear_are_disjoint(scope, scope_name):
    current = scope.SCOPES[scope_name]
    assert not (set(current.clear) & set(current.keep))


@pytest.mark.parametrize('scope_name', ['PRODUCTION', 'DEV_FULL', 'DEV_KEEP_USERS'])
def test_scope_has_no_problems(scope, scope_name):
    assert scope.scope_problems(scope.SCOPES[scope_name]) == []


def test_guard_has_teeth(scope, monkeypatch):
    """守卫必须能报出未分类表 —— 用假 ORM 表集体验证它不是恒空断言。"""
    fake_tables = scope.orm_tables() | {'brand_new_table_2099'}
    monkeypatch.setattr(scope, 'orm_tables', lambda: fake_tables)
    assert 'brand_new_table_2099' in scope.verify_coverage(scope.PRODUCTION_SCOPE)
    with pytest.raises(scope.ScopeError) as exc:
        scope.assert_scope_sound('PRODUCTION')
    assert 'brand_new_table_2099' in str(exc.value)


def test_guard_detects_overlap(scope, monkeypatch):
    """同一张表既清又留 = 语义冲突，必须被守卫拦下。"""
    broken = scope.Scope(
        name='BROKEN',
        description='故意冲突',
        clear=scope.CORE_CLEAR_TABLES,
        keep=frozenset({'product'}),
    )
    problems = scope.scope_problems(broken)
    assert any('同时出现在清除与保留清单' in p for p in problems)


def test_previously_missing_tables_are_now_cleared(scope):
    """F1-6 的核心：purge 曾漏清的 4 张表必须进入清除范围。"""
    for table in PREVIOUSLY_MISSING:
        assert table in scope.PRODUCTION_SCOPE.clear, f'{table} 仍漏清'
        assert table in scope.DEV_FULL_SCOPE.clear, f'{table} 仍漏清'


def test_production_scope_keeps_identity_and_config(scope):
    """上线清库必须保留用户 / 客户 / 运行配置。"""
    for table in ('user', 'user_permission', 'permission', 'customer',
                  'customer_access_log', 'order_sync_config',
                  'backup_settings', 'backup_schedule', 'alembic_version'):
        assert table in scope.PRODUCTION_SCOPE.keep
        assert table not in scope.PRODUCTION_SCOPE.clear


def test_dev_keep_users_scope_keeps_users_but_clears_the_rest(scope):
    """「保留用户清业务数据」的能力必须留着（否则清库会把人锁在门外）。"""
    current = scope.DEV_KEEP_USERS_SCOPE
    assert {'user', 'user_permission'} <= set(current.keep)
    assert 'customer' in current.clear
    assert 'product' in current.clear
    assert 'order' in current.clear


def test_dev_full_scope_clears_identity_tables(scope):
    """开发期全清：连用户 / 客户一起清。"""
    for table in ('user', 'user_permission', 'customer'):
        assert table in scope.DEV_FULL_SCOPE.clear


def test_clear_tables_are_fk_ordered(scope):
    """子表必须排在父表之前，否则单事务 DELETE 会撞外键约束。"""
    clear = list(scope.PRODUCTION_SCOPE.clear)
    for child, parent in (('order_item', 'order'), ('stock_out', 'product'),
                          ('purchase_order_item', 'purchase_order'),
                          ('material_registration_item', 'material_registration'),
                          ('outsource_shipment_item', 'outsource_shipment')):
        if child in clear and parent in clear:
            assert clear.index(child) < clear.index(parent), f'{child} 必须排在 {parent} 之前'


def _load_script(rel: str, name: str):
    for path in (ROOT, SCRIPTS):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_clear_all_data_sources_its_lists_from_purge_scope(scope):
    """clear_all_data.py 的表清单必须来自 purge_scope，不得再自带一份真相源。"""
    script = _load_script('scripts/clear_all_data.py', 'clear_all_data_f16')
    assert set(scope.DEV_FULL_SCOPE.clear) == script.CLEARED_TABLES
    assert set(scope.DEV_FULL_SCOPE.keep) == script.KEEP_TABLES


def test_purge_simulated_data_sources_its_lists_from_purge_scope(scope):
    """purge_simulated_data.py 的表清单必须来自 purge_scope。"""
    script = _load_script('scripts/purge_simulated_data.py', 'purge_simulated_data_f16')
    assert list(scope.PRODUCTION_SCOPE.clear) == script.CLEAR_TABLES
    assert scope.ordered_keep(scope.PRODUCTION_SCOPE) == script.KEEP_TABLES


def test_purge_scope_switch_is_available(scope):
    """--scope DEV_KEEP_USERS 让「保留用户」的能力走同一份受保护实现。"""
    script = _load_script('scripts/purge_simulated_data.py', 'purge_simulated_data_f16b')
    script._activate_scope('DEV_KEEP_USERS')
    assert list(scope.DEV_KEEP_USERS_SCOPE.clear) == script.CLEAR_TABLES
    assert set(script.KEEP_TABLES) == set(scope.DEV_KEEP_USERS_SCOPE.keep)
    # 复原默认，避免污染同进程内的其它用例
    script._activate_scope('PRODUCTION')
    assert list(scope.PRODUCTION_SCOPE.clear) == script.CLEAR_TABLES


def test_activate_scope_refuses_broken_scope(scope, monkeypatch):
    """范围与 ORM 不一致时，切范围必须失败（不得带着漏表的清单继续跑）。"""
    script = _load_script('scripts/purge_simulated_data.py', 'purge_simulated_data_f16c')
    fake_tables = scope.orm_tables() | {'brand_new_table_2099'}
    monkeypatch.setattr(scope, 'orm_tables', lambda: fake_tables)
    with pytest.raises(scope.ScopeError):
        script._activate_scope('PRODUCTION')
