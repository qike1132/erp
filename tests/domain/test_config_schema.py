"""config_schema 模块单测。

重点：v5.39 审查 🔴#3 —— 「配置写坏导致启动崩溃」的回归防护。
"""

from __future__ import annotations

import json

import pytest

from server_manager_v8.domain.config_schema import (
    APP_CONFIG_DEFAULTS,
    DEFAULT_FULL_STOP_HOLD_MS,
    DEFAULT_LOG_KEEP_LINES,
    DEFAULT_MAX_LOG_LINES,
    DEFAULT_REDIS_SERVICE_WAIT_S,
    DEFAULT_REDIS_SERVICES,
    FLOOR_FULL_STOP_HOLD_MS,
    FLOOR_LOG_KEEP_LINES,
    FLOOR_MAX_LOG_LINES,
    NormalizedConfig,
    extract_ports,
    normalize_config,
    parse_config_text,
)


class TestDefaults:
    def test_defaults_match_legacy(self):
        """★ 必须与原 _APP_CONFIG_DEFAULTS 逐值一致。"""
        assert APP_CONFIG_DEFAULTS['api_port'] == 5002
        assert APP_CONFIG_DEFAULTS['web_port'] == 3000
        assert APP_CONFIG_DEFAULTS['redis_port'] == 6379
        assert APP_CONFIG_DEFAULTS['max_log_lines'] == 2000
        assert APP_CONFIG_DEFAULTS['log_keep_lines'] == 1600
        assert APP_CONFIG_DEFAULTS['full_stop_hold_ms'] == 1500
        assert APP_CONFIG_DEFAULTS['redis_service_wait_s'] == 30
        assert APP_CONFIG_DEFAULTS['redis_exe'] == ''
        assert APP_CONFIG_DEFAULTS['nssm_path'] == ''
        assert APP_CONFIG_DEFAULTS['redis_services'] == list(DEFAULT_REDIS_SERVICES)

    def test_floors_match_legacy(self):
        """★ v5.40 引入的下限值。"""
        assert FLOOR_MAX_LOG_LINES == 100
        assert FLOOR_LOG_KEEP_LINES == 50
        assert FLOOR_FULL_STOP_HOLD_MS == 200


class TestNormalizeBasics:
    def test_empty_input_gives_defaults(self):
        cfg = normalize_config(None)
        assert cfg['api_port'] == 5002
        assert cfg['max_log_lines'] == 2000
        assert cfg['redis_services'] == list(DEFAULT_REDIS_SERVICES)

    def test_non_dict_input_gives_defaults(self):
        """文件内容是 list / str / 数字 → 全默认（不崩）。"""
        for bad in ([], 'abc', 123, True):
            assert normalize_config(bad)['api_port'] == 5002

    def test_unknown_keys_dropped(self):
        """逐键白名单合并：未知键丢弃。"""
        cfg = normalize_config({'api_port': 8080, 'evil_key': 'x'})
        assert cfg['api_port'] == 8080
        assert cfg.get('evil_key') is None

    def test_valid_values_preserved(self):
        cfg = normalize_config({
            'api_port': 8080, 'web_port': 8081, 'redis_port': 6380,
            'max_log_lines': 5000, 'log_keep_lines': 4000,
        })
        assert cfg['api_port'] == 8080
        assert cfg['max_log_lines'] == 5000
        assert cfg['log_keep_lines'] == 4000


class TestScalarNormalization:
    """★ v5.39 审查 🔴#3 的回归防护：配置写坏不得炸掉启动。"""

    @pytest.mark.parametrize('bad', ['abc', None, [], {}, '12.5'])
    def test_max_log_lines_bad_value_falls_back(self, bad):
        cfg = normalize_config({'max_log_lines': bad})
        assert cfg['max_log_lines'] == DEFAULT_MAX_LOG_LINES
        assert any(w.key == 'max_log_lines' for w in cfg.warnings)

    @pytest.mark.parametrize('bad', ['abc', None, [], {}])
    def test_log_keep_lines_bad_value_falls_back(self, bad):
        cfg = normalize_config({'log_keep_lines': bad})
        assert cfg['log_keep_lines'] == DEFAULT_LOG_KEEP_LINES

    @pytest.mark.parametrize('bad', ['abc', None, [], {}])
    def test_full_stop_hold_ms_bad_value_falls_back(self, bad):
        cfg = normalize_config({'full_stop_hold_ms': bad})
        assert cfg['full_stop_hold_ms'] == DEFAULT_FULL_STOP_HOLD_MS

    def test_no_exception_ever_raised(self):
        """★ 核心承诺：任何畸形输入都不得抛异常（「绝不因配置崩溃」）。"""
        nasty = [
            {'max_log_lines': 'abc', 'log_keep_lines': None, 'full_stop_hold_ms': []},
            {'redis_services': 'not-a-list'},
            {'redis_service_wait_s': 'xyz'},
            {'api_port': 'abc'},
        ]
        for item in nasty:
            normalize_config(item)  # 不抛即通过

    def test_floors_enforced(self):
        """低于下限的值被抬到下限。"""
        cfg = normalize_config({
            'max_log_lines': 5, 'log_keep_lines': 1, 'full_stop_hold_ms': 10,
        })
        assert cfg['max_log_lines'] == FLOOR_MAX_LOG_LINES
        assert cfg['log_keep_lines'] == FLOOR_LOG_KEEP_LINES
        assert cfg['full_stop_hold_ms'] == FLOOR_FULL_STOP_HOLD_MS

    def test_string_numeric_accepted(self):
        """'3000' 形式的字符串能被 int() 接受（原行为）。"""
        cfg = normalize_config({'max_log_lines': '3000'})
        assert cfg['max_log_lines'] == 3000


class TestRedisServices:
    def test_valid_list_preserved(self):
        cfg = normalize_config({'redis_services': ['a', 'b']})
        assert cfg['redis_services'] == ['a', 'b']

    def test_empty_list_falls_back_with_warning(self):
        """★ D5：空列表等于「不再托管任何 Redis 服务」，几乎不可能是本意。"""
        cfg = normalize_config({'redis_services': []})
        assert cfg['redis_services'] == list(DEFAULT_REDIS_SERVICES)
        assert any(w.key == 'redis_services' for w in cfg.warnings)

    def test_non_list_falls_back(self):
        cfg = normalize_config({'redis_services': 'erp-redis'})
        assert cfg['redis_services'] == list(DEFAULT_REDIS_SERVICES)

    def test_list_with_non_str_falls_back(self):
        cfg = normalize_config({'redis_services': ['ok', 123]})
        assert cfg['redis_services'] == list(DEFAULT_REDIS_SERVICES)

    def test_list_with_empty_str_falls_back(self):
        cfg = normalize_config({'redis_services': ['ok', '']})
        assert cfg['redis_services'] == list(DEFAULT_REDIS_SERVICES)

    def test_result_is_independent_copy(self):
        """★ D4：绝不与模块级默认值共享别名（就地修改会污染默认）。"""
        cfg = normalize_config({'redis_services': ['x']})
        cfg['redis_services'].append('MUTATED')
        assert DEFAULT_REDIS_SERVICES == ('erp-redis', 'erp-redis-broker')
        assert APP_CONFIG_DEFAULTS['redis_services'] == list(DEFAULT_REDIS_SERVICES)

        cfg2 = normalize_config(None)
        cfg2['redis_services'].append('MUTATED2')
        assert APP_CONFIG_DEFAULTS['redis_services'] == ['erp-redis', 'erp-redis-broker']


class TestRedisWaitSeconds:
    def test_valid(self):
        assert normalize_config({'redis_service_wait_s': 45})['redis_service_wait_s'] == 45

    def test_zero_becomes_one(self):
        """max(1, ...) —— 0 被抬到 1。"""
        assert normalize_config({'redis_service_wait_s': 0})['redis_service_wait_s'] == 1

    def test_negative_becomes_one(self):
        assert normalize_config({'redis_service_wait_s': -5})['redis_service_wait_s'] == 1

    @pytest.mark.parametrize('bad', ['abc', None, [], {}])
    def test_bad_falls_back_to_default(self, bad):
        cfg = normalize_config({'redis_service_wait_s': bad})
        assert cfg['redis_service_wait_s'] == DEFAULT_REDIS_SERVICE_WAIT_S


class TestKeepVsMax:
    def test_keep_less_than_max_preserved(self):
        cfg = normalize_config({'max_log_lines': 3000, 'log_keep_lines': 2000})
        assert cfg['log_keep_lines'] == 2000

    def test_keep_equal_max_is_adjusted(self):
        """★ keep >= max 会让日志裁剪退化为空操作。"""
        cfg = normalize_config({'max_log_lines': 3000, 'log_keep_lines': 3000})
        assert cfg['log_keep_lines'] == 2800   # max - 200

    def test_keep_greater_than_max_is_adjusted(self):
        cfg = normalize_config({'max_log_lines': 3000, 'log_keep_lines': 9999})
        assert cfg['log_keep_lines'] == 2800

    def test_adjustment_respects_floor(self):
        """max=200 时 max-200=0，须被 floor 抬到 50。"""
        cfg = normalize_config({'max_log_lines': 200, 'log_keep_lines': 200})
        assert cfg['log_keep_lines'] == FLOOR_LOG_KEEP_LINES

    def test_default_keep_less_than_default_max(self):
        cfg = normalize_config(None)
        assert cfg['log_keep_lines'] < cfg['max_log_lines']


class TestStringKeys:
    @pytest.mark.parametrize('key', ['redis_exe', 'nssm_path'])
    def test_non_str_falls_back_to_empty(self, key):
        cfg = normalize_config({key: 123})
        assert cfg[key] == ''
        assert any(w.key == key for w in cfg.warnings)

    @pytest.mark.parametrize('key', ['redis_exe', 'nssm_path'])
    def test_valid_str_preserved(self, key):
        cfg = normalize_config({key: r'C:\nssm.exe'})
        assert cfg[key] == r'C:\nssm.exe'


class TestParseConfigText:
    def test_valid_json(self):
        cfg = parse_config_text(json.dumps({'api_port': 8080}))
        assert cfg['api_port'] == 8080

    def test_malformed_json_falls_back(self):
        """★ 解析失败回落默认 + 记警告，不抛异常。"""
        cfg = parse_config_text('{not valid json')
        assert cfg['api_port'] == 5002
        assert any(w.key == '<file>' for w in cfg.warnings)

    def test_empty_text_falls_back(self):
        cfg = parse_config_text('')
        assert cfg['api_port'] == 5002

    def test_json_array_falls_back(self):
        cfg = parse_config_text('[1,2,3]')
        assert cfg['api_port'] == 5002


class TestExtractPorts:
    def test_valid_ports(self):
        cfg = normalize_config({'api_port': 8080, 'web_port': 8081, 'redis_port': 6380})
        ports, invalid = extract_ports(cfg)
        assert (ports.api, ports.web, ports.redis) == (8080, 8081, 6380)
        assert invalid == []

    def test_invalid_ports_recorded_not_blocking(self):
        """★ v5.40 审查 #22：配置损坏必须留痕，不静默；但也不阻断启动。"""
        cfg = normalize_config({'api_port': 'abc', 'web_port': 70000, 'redis_port': 6379})
        ports, invalid = extract_ports(cfg)
        assert set(invalid) == {'api_port', 'web_port'}
        # 非法的回落默认值
        assert ports.api == 5002
        assert ports.web == 3000
        assert ports.redis == 6379

    def test_zero_port_invalid(self):
        cfg = normalize_config({'api_port': 0})
        ports, invalid = extract_ports(cfg)
        assert 'api_port' in invalid
        assert ports.api == 5002

    def test_accepts_plain_dict(self):
        ports, invalid = extract_ports({'api_port': 9000, 'web_port': 9001, 'redis_port': 9002})
        assert (ports.api, ports.web, ports.redis) == (9000, 9001, 9002)
        assert invalid == []

    def test_returns_immutable_port_config(self):
        """★ 返回 frozen PortConfig，杜绝原实现的全局单例就改（v8 D3）。"""
        ports, _ = extract_ports(normalize_config(None))
        with pytest.raises(Exception):
            ports.api = 1  # type: ignore[misc]
