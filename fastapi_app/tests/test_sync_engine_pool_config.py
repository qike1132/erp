"""同步引擎不得继承 asyncpg 专属 connect_args（2026-10-17 审计 AUD-09）

缺陷：PgBouncer 模式下 _pool_config 注入 statement_cache_size=0（asyncpg 专属），
psycopg3 同步引擎原样继承 → conninfo 解析阶段报 invalid connection option，
迁移/ARQ 同步任务/scripts 全部不可用。
"""
from unittest.mock import MagicMock

from fastapi_app.core import database


def test_sync_engine_drops_asyncpg_connect_args(monkeypatch):
    captured = {}

    def _fake_create_engine(url, **kwargs):
        captured['url'] = url
        captured['kwargs'] = kwargs
        return MagicMock()

    monkeypatch.setattr(database, 'create_engine', _fake_create_engine)
    monkeypatch.setattr(
        database, '_pool_config',
        {'pool_size': 5, 'connect_args': {'statement_cache_size': 0}},
    )
    monkeypatch.setattr(database, '_sync_engine', None)
    monkeypatch.setattr(database, '_SyncSessionLocal', None)

    try:
        database._init_sync_engine()
    finally:
        monkeypatch.setattr(database, '_sync_engine', None)
        monkeypatch.setattr(database, '_SyncSessionLocal', None)

    # 2026-10-18 OCR 评审：pgbouncer 模式下同步引擎改用 psycopg3 的等价开关
    # prepare_threshold=None；关键是绝不能带 asyncpg 的 statement_cache_size。
    assert 'statement_cache_size' not in captured['kwargs'].get('connect_args', {})
    assert captured['kwargs'].get('connect_args') == {'prepare_threshold': None}
    assert captured['kwargs']['pool_size'] == 5
