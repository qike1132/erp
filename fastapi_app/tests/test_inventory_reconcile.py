"""P1-1 库存只读对账测试：三分类结果、只读证明、ARQ 接线与开关语义。

不依赖真实数据库（``fastapi_app/tests/conftest.py`` 已把 ``_AsyncSessionLocal`` 置
None），因此对账走假会话返回构造行；纯函数 ``summarize_rows`` 直接被喂构造数据。
只读由 AST 断言锁死：两个新模块内不得出现写 SQL 或 add / delete / flush / commit。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

from fastapi_app.core import arq_app
from fastapi_app.services import inventory_reconcile as svc
from fastapi_app.tasks import inventory_reconcile_task as task_mod

#: 构造行：(product_id, name, initial_stock, current_stock, log_sum)
ROWS = [
    (1, '零差异-有流水', 100, 100, 100),
    (2, '正差异-漏写流水', 150, 150, 120),
    (3, '负差异-账面偏低', 95, 80, 95),
    (4, '零差异-无流水', 0, 0, 0),
]

#: 只读证明：源码里不得出现的写 SQL 模式与写方法名
FORBIDDEN_SQL = re.compile(
    r'\b(?:INSERT\s+INTO|UPDATE\s+\w+\s+SET|DELETE\s+FROM|TRUNCATE|ALTER\s+TABLE|DROP\s+TABLE|GRANT|REVOKE)\b',
    re.IGNORECASE,
)
FORBIDDEN_METHODS = frozenset(
    {
        'add',
        'add_all',
        'delete',
        'flush',
        'commit',
        'rollback',
        'begin',
        'bulk_insert_mappings',
        'bulk_update_mappings',
    }
)
SOURCE_FILES = (
    'fastapi_app/services/inventory_reconcile.py',
    'fastapi_app/tasks/inventory_reconcile_task.py',
)


class _FakeResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = list(rows)

    def all(self) -> list[Any]:
        return list(self._rows)


class _FakeSession:
    """最小只读会话桩：只有 execute，没有 add / delete / flush / commit。"""

    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows
        self.statements: list[Any] = []

    async def execute(self, statement: Any) -> _FakeResult:
        self.statements.append(statement)
        return _FakeResult(self._rows)


class _FakeSessionCtx:
    def __init__(self, session: _FakeSession) -> None:
        self._session = session

    async def __aenter__(self) -> _FakeSession:
        return self._session

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        return False


def _source_paths() -> list[Path]:
    root = Path(__file__).resolve().parents[2]
    return [root / rel for rel in SOURCE_FILES]


def _docstring_nodes(tree: ast.Module) -> set[int]:
    holders = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
    found: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, holders):
            body = getattr(node, 'body', [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                if isinstance(body[0].value.value, str):
                    found.add(id(body[0].value))
    return found


def test_classify_diff_three_way() -> None:
    assert svc.classify_diff(0) == svc.STATUS_MATCHED
    assert svc.classify_diff(7) == svc.STATUS_POSITIVE
    assert svc.classify_diff(-7) == svc.STATUS_NEGATIVE


def test_summarize_rows_classifies_zero_positive_negative() -> None:
    report = svc.summarize_rows(ROWS)

    assert report['checked_products'] == 4
    assert report['matched'] == 2
    assert report['positive_count'] == 1
    assert report['negative_count'] == 1
    assert report['diff_count'] == 2
    assert report['net_diff'] == 30 - 15
    assert report['abs_diff_total'] == 45
    assert report['truncated'] is False

    by_id = {item['product_id']: item for item in report['diffs']}
    assert set(by_id) == {2, 3}  # 零差异产品不进差异清单
    assert by_id[2]['status'] == svc.STATUS_POSITIVE
    assert by_id[2]['diff'] == 30
    assert by_id[2]['log_sum'] == 120
    assert by_id[3]['status'] == svc.STATUS_NEGATIVE
    assert by_id[3]['diff'] == -15


def test_summarize_rows_truncates_detail_but_keeps_totals() -> None:
    report = svc.summarize_rows(ROWS, diff_limit=1)

    assert report['truncated'] is True
    assert report['diff_count'] == 2
    assert len(report['diffs']) == 1
    assert report['diffs'][0]['product_id'] == 2  # |diff| 30 > 15，取最大漂移


def test_reconcile_statement_is_single_select_join() -> None:
    sql = str(svc.build_reconcile_statement()).upper()

    assert sql.startswith('SELECT')
    assert 'INVENTORY_LOG' in sql
    assert 'LEFT OUTER JOIN' in sql
    assert 'GROUP BY' in sql
    assert not FORBIDDEN_SQL.search(sql)


async def test_reconcile_inventory_reads_once_and_reports() -> None:
    session = _FakeSession(ROWS)
    report = await svc.reconcile_inventory(session)

    assert report['checked_products'] == 4
    assert report['diff_count'] == 2
    assert isinstance(report['checked_at'], str)
    # 单条集合式查询：不逐产品查流水（无 N+1）
    assert len(session.statements) == 1


async def test_task_returns_report_without_writes(monkeypatch: Any) -> None:
    session = _FakeSession(ROWS)
    monkeypatch.setattr(task_mod, 'require_async_session_local', lambda: (lambda: _FakeSessionCtx(session)))

    report = await task_mod.inventory_reconcile_task({'job_id': 'test-inventory-reconcile'})

    assert report['checked_products'] == 4
    assert report['diff_count'] == 2
    assert len(session.statements) == 1
    for forbidden in ('add', 'add_all', 'delete', 'flush', 'commit'):
        assert not hasattr(session, forbidden)


def test_is_enabled_defaults_off_and_reads_env(monkeypatch: Any) -> None:
    # 键名以字面量出现（常量间接层已删，见下方门禁可见性用例）
    monkeypatch.delenv('INVENTORY_RECONCILE_ENABLED', raising=False)
    assert svc.is_enabled() is False

    monkeypatch.setenv('INVENTORY_RECONCILE_ENABLED', 'true')
    assert svc.is_enabled() is True

    monkeypatch.setenv('INVENTORY_RECONCILE_ENABLED', '0')
    assert svc.is_enabled() is False


def test_enabled_env_key_is_literal_and_registered_in_template() -> None:
    """t29：键名必须字面量传给 os.getenv，且 .env.example 已登记 —— 缺一即 env_drift fail。"""
    source = Path(svc.__file__).read_text(encoding='utf-8')
    assert re.search(r"os\.getenv\(\s*['\"]INVENTORY_RECONCILE_ENABLED['\"]", source), (
        'is_enabled() 必须以字面量键调用 os.getenv，'
        '否则 scripts/ops/check_env_drift.py 的 CODE_REFS 看不到该键'
    )

    template = Path(__file__).resolve().parents[2] / '.env.example'
    declared: set[str] = set()
    for line in template.read_text(encoding='utf-8').splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            continue
        match = re.match(r'^([A-Za-z_][A-Za-z0-9_]*)\s*=', stripped)
        if match:
            declared.add(match.group(1))
    assert 'INVENTORY_RECONCILE_ENABLED' in declared, '.env.example 缺 INVENTORY_RECONCILE_ENABLED'


def test_arq_worker_loads_task_and_gates_cron_by_env() -> None:
    names = [func.__name__ for func in arq_app.WorkerSettings.functions]
    assert 'inventory_reconcile_task' in names

    registered = [s for s in arq_app.cron_schedules if s['name'] == task_mod.CRON_NAME]
    # 默认不启用：cron 是否注册必须与 env 开关（arq_app 导入期取值）一致
    assert bool(registered) is svc.is_enabled()
    # 无论是否注册，cron_schedules 里的条目都必须能被 cron() 展开
    assert all({'name', 'func', 'cron'} <= set(s) for s in arq_app.cron_schedules)


def test_cron_entry_is_low_frequency_daily() -> None:
    entry = task_mod.inventory_reconcile_cron_entry()

    assert entry['name'] == 'inventory-reconcile'
    assert entry['func'] is task_mod.inventory_reconcile_task
    assert entry['cron'] == {'hour': 3, 'minute': 30}
    assert entry['schedule'] == '3:30'
    assert entry['timeout'] == 300


def test_new_modules_are_read_only_by_ast() -> None:
    for path in _source_paths():
        source = path.read_text(encoding='utf-8')
        tree = ast.parse(source)
        docstrings = _docstring_nodes(tree)

        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr not in FORBIDDEN_METHODS, f'{path.name} 调用了写方法 {node.func.attr}'
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if id(node) in docstrings:
                    continue
                assert not FORBIDDEN_SQL.search(node.value), f'{path.name} 含写 SQL：{node.value!r}'

    # 任务模块只做装配：读路径全部落在服务的单条 select() 上
    # 任务模块只做装配：读路径全部落在服务的单条 select() 上
    assert 'reconcile_inventory' in _source_paths()[1].read_text(encoding='utf-8')
