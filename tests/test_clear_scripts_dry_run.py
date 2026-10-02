"""清库脚本的 `--dry-run` 安全性 + helper 去重回归测试（2026-10-02）。

原缺陷：`scripts/clear_all_data.py` / `clear_purchase_center_data.py` 的各 clear_*
函数**无条件执行 DELETE**，只在 `db.commit()` 上区分 dry-run —— 于是 `--dry-run`
会真的跑删除语句（靠"不 commit"侥幸不落库），且遇外键冲突直接报错，预览根本用不了。
修复：抽出一份共享 helper `_prod_write_guard.affected_rows`，`dry_run=True` 时把
DELETE 换成等价 COUNT（原先两个脚本各写一份、逐字重复）。

本测试钉住三件事：
  1. `affected_rows(..., dry_run=True)` 发出的 SQL 必须是 `SELECT COUNT(*)`、**不含 DELETE**；
  2. 两个脚本里**不再存在** `results[...] = db.execute(text("DELETE ..."))` 这类绕过 helper
     的直写（防回归）；
  3. 两个脚本**不再各自实现** `_affected`（防再次分叉）。
"""
import importlib.util
import pathlib
import re
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / 'scripts'
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


class _FakeResult:
    rowcount = 3

    def scalar(self):
        return 7


class _FakeSession:
    def __init__(self):
        self.statements: list[str] = []

    def execute(self, stmt):
        self.statements.append(str(stmt))
        return _FakeResult()


def _affected_rows():
    from _prod_write_guard import affected_rows
    return affected_rows


def test_affected_dry_run_issues_count_not_delete():
    db = _FakeSession()
    n = _affected_rows()(db, 'DELETE FROM "order"', dry_run=True)
    assert n == 7, 'dry-run 应返回行数（来自 COUNT）'
    assert db.statements, 'dry-run 也必须查询（否则没有预览数字）'
    sql = db.statements[0].upper()
    assert 'DELETE' not in sql, f'dry-run 不得发出 DELETE：{db.statements[0]}'
    assert sql.startswith('SELECT COUNT(*)'), db.statements[0]


def test_affected_execute_still_deletes():
    db = _FakeSession()
    n = _affected_rows()(db, 'DELETE FROM "order"', dry_run=False)
    assert n == 3, 'execute 应返回 rowcount'
    assert 'DELETE' in db.statements[0].upper()
    assert 'SELECT COUNT' not in db.statements[0].upper()


def test_affected_rejects_non_delete_sql():
    """传进来的不是 DELETE FROM 语句时必须抛错，而不是拼出非法 SQL。"""
    with pytest.raises(ValueError):
        _affected_rows()(_FakeSession(), 'SELECT 1', dry_run=True)


@pytest.mark.parametrize('script', ['clear_all_data', 'clear_purchase_center_data'])
def test_no_raw_delete_bypasses_the_helper(script):
    """防回归：不得再有 `results[...] = db.execute(text("DELETE ..."))` 绕过 helper。"""
    src = (SCRIPTS / f'{script}.py').read_text(encoding='utf-8')
    bypasses = re.findall(
        r"results\[[^\]]+\]\s*=\s*db\.execute\(\s*text\(\s*[\"']DELETE", src
    )
    assert not bypasses, f'{script} 仍有 {len(bypasses)} 处绕过 affected_rows 的直写 DELETE'


@pytest.mark.parametrize('script', ['clear_all_data', 'clear_purchase_center_data'])
def test_scripts_do_not_redefine_the_helper(script):
    """防再次分叉：两个脚本都不得再各自实现 `_affected`。"""
    src = (SCRIPTS / f'{script}.py').read_text(encoding='utf-8')
    assert 'def _affected(' not in src, f'{script} 又出现了本地 _affected 实现'


@pytest.mark.parametrize('script', ['clear_all_data', 'clear_purchase_center_data'])
def test_script_module_imports_cleanly(script):
    """冒烟：脚本以模块方式加载时不得因 `_prod_write_guard` 导入失败而崩。

    （脚本自己在头部把 `scripts/` 加进 sys.path，故 importlib 加载也可用。）
    """
    spec = importlib.util.spec_from_file_location(f'{script}_smoke', SCRIPTS / f'{script}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert hasattr(module, 'affected_rows'), '应从共享模块导入 affected_rows'
