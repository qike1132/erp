"""配置 schema 纯逻辑 — 深合并与 v1→v2 版本迁移（Domain 层，零 I/O）。

v8 方案 §3.6：v1 扁平配置（v6 server_manager_config.json）升级为 v2 分组嵌套。
迁移结果可单测；适配层（storage_json）负责读写与落盘。
"""

from __future__ import annotations

__all__ = ['CONFIG_V2_DEFAULTS', 'SCHEMA_VERSION', 'deep_merge', 'migrate_v1_to_v2']

SCHEMA_VERSION = 2

CONFIG_V2_DEFAULTS: dict = {
    'schema_version': SCHEMA_VERSION,
    'app': {
        'theme': 'dark',
        'nav_collapsed': False,
        'reduced_motion': 'auto',
    },
    'ports': {'api': 5002, 'web': 3000, 'redis': 6379},
    'paths': {'redis_exe': '', 'nssm': '', 'python': '', 'project': ''},
    'health': {'api_path': '/api/health', 'timeout_s': 2, 'retries': 30, 'interval_s': 1},
    'logs': {
        'max_lines': 2000,
        'keep_lines': 1600,
        'retention_days': 14,
        'keyword_rules': [],
    },
    'alerts': {
        'rules': [],
        'group_by': ['service', 'family'],
        'group_window_s': 300,
        'inhibitions': [],
        'silences': [],
    },
    'auth': {
        'pin_hash': '',
        'elevate_ttl_s': 1800,
        'default_role': 'viewer',
        'require_reason_for_l3': True,
    },
    'audit': {'retention_days': 180, 'hash_chain': True},
    'backup': {'schedule': 'manual', 'target_dir': '', 'encrypt': True},
}


def deep_merge(base: dict, override: dict) -> dict:
    """递归合并：override 深覆盖 base，保留 base 中未出现的键。"""
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def migrate_v1_to_v2(data: dict) -> tuple[dict, bool]:
    """v1 扁平配置 → v2 分组配置。返回 (迁移后数据, 是否发生了迁移)。

    v1 键（v6）: theme / nav_collapsed / api_port / web_port / redis_port /
        redis_exe / nssm_path / max_log_lines / log_keep_lines
    """
    if data.get('schema_version') == SCHEMA_VERSION:
        return data, False
    flat_keys = ('api_port', 'web_port', 'redis_port', 'redis_exe', 'nssm_path')
    if not any(k in data for k in flat_keys):
        return data, False  # 已是 v2 或未知结构
    v2 = dict(CONFIG_V2_DEFAULTS)
    v2['schema_version'] = SCHEMA_VERSION
    v2['app'].update({
        'theme': data.get('theme', 'light'),
        'nav_collapsed': bool(data.get('nav_collapsed', False)),
    })
    v2['ports'].update({
        'api': data.get('api_port', 5002),
        'web': data.get('web_port', 3000),
        'redis': data.get('redis_port', 6379),
    })
    v2['paths'].update({
        'redis_exe': data.get('redis_exe', ''),
        'nssm': data.get('nssm_path', ''),
    })
    v2['logs'].update({
        'max_lines': data.get('max_log_lines', 2000),
        'keep_lines': data.get('log_keep_lines', 1600),
    })
    # 保留 v1 中未映射的键（前向兼容）
    for key, value in data.items():
        if key not in v2 and key != 'schema_version':
            v2[key] = value
    return v2, True
