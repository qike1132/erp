"""reset_admin_password 必须连带 bump token_version（2026-11-16 审计 Low）。

拦哪种错：只 `UPDATE "user" SET password = ...` 的写法 —— 重置口令后，重置前签发的
access/refresh token 仍能用满剩余有效期（默认 2 小时 / 7 天），已建连的 WebSocket 也
不会被 60s 复核踢掉，等于「重置」没把旧会话下线。忘了密码的场景往往正怀疑凭据外泄。

不连库：`create_engine` 换成假对象、`sessionmaker` 换成记录语句的假会话，只断言脚本
真正执行的 SQL 文本（纯文本断言，符合「不要在测试里连库」）。
"""
from types import SimpleNamespace

import pytest

import scripts.reset_admin_password as reset_mod

# 通过 PasswordValidator 的强口令（与建号策略一致）
NEW_PASSWORD = 'Str0ng-Passw0rd!2026'  # secret-scan:allow 测试夹具口令，仅用于断言 SQL 文本，不连库


class _RecordingSession:
    """记录 execute/commit 的假会话（`with SessionLocal() as session` 的对象）。"""

    def __init__(self, captured: dict, rowcount: int = 1) -> None:
        self._captured = captured
        self._rowcount = rowcount

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, statement, params):
        self._captured['sql'] = str(statement)
        self._captured['params'] = dict(params)
        return SimpleNamespace(rowcount=self._rowcount)

    def commit(self) -> None:
        self._captured['committed'] = True

    def rollback(self) -> None:
        self._captured['rolled_back'] = True


@pytest.fixture()
def recorded_sql(monkeypatch) -> dict:
    """把建连/会话替换成假实现，返回记录到的 SQL；不触碰任何数据库。"""
    captured: dict = {}
    session = _RecordingSession(captured)
    monkeypatch.setattr(reset_mod, 'create_engine', lambda _url: object())
    monkeypatch.setattr(reset_mod, 'sessionmaker', lambda **_kwargs: (lambda: session))
    return captured


def test_reset_password_bumps_token_version(recorded_sql: dict):
    """重置语句必须同时自增 token_version（旧会话两端同时失效）。"""
    assert reset_mod.reset_admin_password(NEW_PASSWORD) is True

    sql = recorded_sql['sql']
    assert 'token_version' in sql, f'重置口令未 bump token_version，旧会话仍可继续用: {sql}'
    assert 'token_version = COALESCE(token_version, 0) + 1' in sql
    assert 'password = :password' in sql
    assert recorded_sql['params']['username'] == 'admin'
    assert recorded_sql['committed'] is True


def test_reset_password_still_validates_strength(recorded_sql: dict):
    """弱口令仍要先被拒（不改动既有的建号策略约束）。"""
    with pytest.raises(ValueError):
        reset_mod.reset_admin_password('12345')  # 少于 MIN_LENGTH=6

    assert 'sql' not in recorded_sql, '弱口令不得走到写库'
