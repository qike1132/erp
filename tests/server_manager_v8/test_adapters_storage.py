"""配置存储适配器测试：默认值 / 原子写 / 损坏备份 / v1→v2 迁移。"""
from __future__ import annotations

import json

from server_manager_v8.adapters.storage_json import (
    JsonConfigStorage,
    deep_merge,
    migrate_v1_to_v2,
)

DEFAULTS = {
    'schema_version': 2,
    'app': {'theme': 'light', 'nav_collapsed': False},
    'ports': {'api': 5002, 'web': 3000, 'redis': 6379},
    'logs': {'max_lines': 2000, 'keyword_rules': []},
    'auth': {'pin_hash': '', 'elevate_ttl_s': 1800},
    'audit': {'retention_days': 180, 'hash_chain': True},
}


class TestDeepMerge:
    def test_nested_merge(self) -> None:
        merged = deep_merge(
            {'a': {'x': 1, 'y': 2}, 'keep': 1},
            {'a': {'y': 9}, 'new': 3},
        )
        assert merged == {'a': {'x': 1, 'y': 9}, 'keep': 1, 'new': 3}

    def test_override_non_dict_replaces(self) -> None:
        assert deep_merge({'a': {'x': 1}}, {'a': 5}) == {'a': 5}


class TestMigrateV1ToV2:
    def test_v2_passthrough(self) -> None:
        v2 = {'schema_version': 2, 'app': {}}
        migrated, changed = migrate_v1_to_v2(v2)
        assert not changed and migrated is v2

    def test_v1_flat_to_v2_nested(self) -> None:
        v1 = {
            'theme': 'dark',
            'nav_collapsed': True,
            'api_port': 5002,
            'web_port': 3000,
            'redis_port': 6379,
            'redis_exe': 'C:/Redis/redis-server.exe',
            'nssm_path': '',
            'max_log_lines': 2000,
            'log_keep_lines': 1600,
        }
        v2, changed = migrate_v1_to_v2(v1)
        assert changed
        assert v2['schema_version'] == 2
        assert v2['ports'] == {'api': 5002, 'web': 3000, 'redis': 6379}
        assert v2['paths']['redis_exe'] == 'C:/Redis/redis-server.exe'
        assert v2['app']['theme'] == 'dark'
        assert v2['logs']['max_lines'] == 2000
        assert 'alerts' in v2 and 'auth' in v2 and 'backup' in v2

    def test_unknown_structure_not_migrated(self) -> None:
        migrated, changed = migrate_v1_to_v2({'foo': 1})
        assert not changed and migrated == {'foo': 1}


class TestStorage:
    def test_missing_file_returns_defaults(self, tmp_path) -> None:
        store = JsonConfigStorage(tmp_path / 'cfg.json', DEFAULTS)
        assert store.load() == DEFAULTS

    def test_save_load_roundtrip(self, tmp_path) -> None:
        store = JsonConfigStorage(tmp_path / 'cfg.json', DEFAULTS)
        data = dict(DEFAULTS)
        data['app'] = {**data['app'], 'theme': 'dark'}
        assert store.save(data).ok
        assert store.load()['app']['theme'] == 'dark'

    def test_corrupt_file_backed_up_and_defaults_returned(self, tmp_path) -> None:
        path = tmp_path / 'cfg.json'
        path.write_text('{ 这不是合法 JSON', encoding='utf-8')
        store = JsonConfigStorage(path, DEFAULTS)
        loaded = store.load()
        assert loaded == DEFAULTS
        assert store.last_error
        backups = list(tmp_path.glob('cfg.json.corrupt-*'))
        assert len(backups) == 1  # 损坏文件被备份而非静默丢弃

    def test_save_failure_reports_reason(self, tmp_path) -> None:
        """父路径是普通文件 → mkdir 必然失败 → save 返回显式失败（不静默）。"""
        blocker = tmp_path / 'blocker.txt'
        blocker.write_text('我是文件不是目录', encoding='utf-8')
        store = JsonConfigStorage(blocker / 'cfg.json', DEFAULTS)
        result = store.save(dict(DEFAULTS))
        assert not result.ok and result.reason

    def test_migrate_persists_on_load(self, tmp_path) -> None:
        path = tmp_path / 'cfg.json'
        path.write_text(json.dumps({'theme': 'dark', 'api_port': 5002}), encoding='utf-8')
        store = JsonConfigStorage(path, DEFAULTS)
        loaded = store.load()
        assert loaded['schema_version'] == 2
        stored = json.loads(path.read_text(encoding='utf-8'))
        assert stored['schema_version'] == 2  # 迁移已落盘

    def test_unknown_extra_keys_preserved(self, tmp_path) -> None:
        """v1 中未知键在迁移后保留（前向兼容）。"""
        v1 = {'theme': 'dark', 'future_flag': 1}
        v2, _ = migrate_v1_to_v2(v1)
        assert v2['future_flag'] == 1
