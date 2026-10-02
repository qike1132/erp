"""清库脚本的 `--dry-run` 安全性回归测试（2026-10-02）。

原缺陷：`scripts/clear_all_data.py` / `clear_purchase_center_data.py` 的各 clear_*
函数**无条件执行 DELETE**，只在 `db.commit()` 上区分 dry-run —— 于是 `--dry-run`
会真的跑删除语句（靠"不 commit"侥幸不落库），且遇外键冲突直接报错，预览根本用不了。
修复：`dry_run=True` 时把 DELETE 换成等价 COUNT。

本测试钉住两件事：
  1. `_affected(..., dry_run=True)` 发出的 SQL 必须是 `SELECT COUNT(*)`，**不含 DELETE**；
  2. 两个脚本里**不再存在** `results[...] = db.execute(text("DELETE ..."))` 这类
     绕过 helper 的直写（防回归）。
"""
import importlib.util
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / 'scripts'


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f'{name}.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


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


@pytest.mark.parametrize('script', ['clear_all_data', 'clear_purchase_center_data'])
def test_affected_dry_run_issues_count_not_delete(script):
    mod = _load(script)
    db = _FakeSession()
    n = mod._affected(db, 'DELETE FROM "order"', dry_run=True)
    assert n == 7, 'dry-run 应返回行数（来自 COUNT）'
    assert db.statements, 'dry-run 也必须查询（否则没有预览数字）'
    sql = db.statements[0].upper()
    assert 'DELETE' not in sql, f'dry-run 不得发出 DELETE：{db.statements[0]}'
    assert sql.startswith('SELECT COUNT(*)'), db.statements[0]


@pytest.mark.parametrize('script', ['clear_all_data', 'clear_purchase_center_data'])
def test_affected_execute_still_deletes(script):
    mod = _load(script)
    db = _FakeSession()
    n = mod._affected(db, 'DELETE FROM "order"', dry_run=False)
    assert n == 3, 'execute 应返回 rowcount'
    assert 'DELETE' in db.statements[0].upper()
    assert 'SELECT COUNT' not in db.statements[0].upper()


@pytest.mark.parametrize('script', ['clear_all_data', 'clear_purchase_center_data'])
def test_no_raw_delete_bypasses_the_helper(script):
    """防回归：不得再有 `results[...] = db.execute(text("DELETE ..."))` 绕过 helper。"""
    src = (SCRIPTS / f'{script}.py').read_text(encoding='utf-8')
    bypasses = re.findall(
        r"results\[[^\]]+\]\s*=\s*db\.execute\(\s*text\(\s*[\"']DELETE", src
    )
    assert not bypasses, f'{script} 仍有 {len(bypasses)} 处绕过 _affected 的直写 DELETE'
