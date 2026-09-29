"""生产报表部门权限种子脚本（用假 session 验证幂等与父子关系）"""
import contextlib

from fastapi_app.core.production_scope import (
    AGGREGATE_MANAGE_CODE,
    dept_permission_rows,
)
from scripts.init_production_dept_permissions import (
    PARENT_CODE,
    seed_dept_permissions,
)


class _FakeQuery:
    def __init__(self, store):
        self._store = store
        self._code = None

    def filter_by(self, **kwargs):
        self._code = kwargs.get('code')
        return self

    def first(self):
        return self._store.get(self._code)


class _FakeSession:
    """只实现脚本用到的最小接口：query().filter_by().first() / add() / commit()"""

    def __init__(self, store):
        self._store = store
        self.commits = 0

    def query(self, _model):
        return _FakeQuery(self._store)

    def add(self, obj):
        self._store[obj.code] = obj

    def commit(self):
        self.commits += 1


def _fake_permission(code, parent_id=None):
    class _P:
        def __init__(self):
            self.code = code
            self.parent_id = parent_id
            self.id = None
    return _P()


def test_parent_code_is_the_aggregate_manage_code():
    assert PARENT_CODE == AGGREGATE_MANAGE_CODE


def test_first_run_creates_all_six_rows():
    store = {PARENT_CODE: _fake_permission(PARENT_CODE)}
    session = _FakeSession(store)

    created, skipped = seed_dept_permissions(session)

    assert (created, skipped) == (6, 0)
    assert set(store) == {PARENT_CODE} | {code for code, _ in dept_permission_rows()}
    assert session.commits == 1


def test_second_run_is_idempotent():
    store = {PARENT_CODE: _fake_permission(PARENT_CODE)}
    session = _FakeSession(store)

    seed_dept_permissions(session)
    created, skipped = seed_dept_permissions(session)

    assert (created, skipped) == (0, 6)


def test_rows_are_hung_under_parent_and_hidden_from_nav():
    parent = _fake_permission(PARENT_CODE)
    parent.id = 42
    store = {PARENT_CODE: parent}
    session = _FakeSession(store)

    seed_dept_permissions(session)

    for code, name in dept_permission_rows():
        perm = store[code]          # 脚本用真实 Permission 类构造，故这些属性可直接断言
        assert perm.name == name
        assert perm.is_nav is False
        assert perm.parent_id == 42  # 不会写出孤儿权限点


def test_missing_parent_raises_instead_of_writing_orphans():
    session = _FakeSession({})
    try:
        seed_dept_permissions(session)
    except RuntimeError as exc:
        assert AGGREGATE_MANAGE_CODE in str(exc)
    else:
        raise AssertionError('父权限缺失时应抛 RuntimeError')


def test_failed_run_writes_nothing():
    session = _FakeSession({})
    with contextlib.suppress(RuntimeError):
        seed_dept_permissions(session)
    assert session.commits == 0
