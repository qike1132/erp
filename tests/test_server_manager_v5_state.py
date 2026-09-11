"""server_manager v5.40 状态判定/配置归一化回归测试(纯函数, 无 Tk 实例)。

背景: 2026-09-11 全量审查(报告: .workbuddy/artifacts/服务器管理器v5.39代码审查报告-2026-09-11.md)
后修复, 本文件锁定四个关键防线, 防止下次改动回退:
  1. _parse_sc_state 四态语义 —— 特别是 PID=1060 不得误判「未安装」(审查 #1)
  2. _load_app_config 标量键归一化 —— 配置写坏不得炸启动(审查 #3)
  3. _apply_config_to_runtime 非法端口必须留痕(审查 #22)
  4. _get_env_value 引号剥离(审查 #19)
运行: python -m pytest tests/test_server_manager_v5_state.py -q
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server_manager as sm  # noqa: E402  (模块级代码无 Tk root, 导入安全)


def _sc_ok(state_line, pid=None):
    """构造一份 sc query 成功输出(字段名与真实 sc 输出一致, 均为英文关键字)。"""
    out = 'SERVICE_NAME: erp-prod\nTYPE               : 10  WIN32_OWN_PROCESS\n'
    out += f'STATE              : {state_line}\n'
    out += 'WIN32_EXIT_CODE    : 0\n'
    if pid is not None:
        out += f'PID                : {pid}\n'
    return out


class TestParseScState:
    """审查 #1 回归: 「未安装」只认 rc==1060 或无 STATE 行的 1060 错误文本。"""

    def test_running_with_pid_1060_must_not_be_absent(self):
        # 旧版 `'1060' in out` 会把 PID=1060 的运行中服务误判「未安装」→ 互杀事故
        assert sm._parse_sc_state(0, _sc_ok('4  RUNNING', pid=1060)).endswith('RUNNING')

    def test_running_normal(self):
        assert sm._parse_sc_state(0, _sc_ok('4  RUNNING', pid=17044)).endswith('RUNNING')

    def test_stopped(self):
        assert sm._parse_sc_state(0, _sc_ok('1  STOPPED')).endswith('STOPPED')

    def test_stop_pending(self):
        assert sm._parse_sc_state(0, _sc_ok('3  STOP_PENDING')).endswith('STOP_PENDING')

    def test_rc1060_is_absent(self):
        assert sm._parse_sc_state(1060, '[SC] EnumQueryServicesStatus:指定的服务未安装。') == '未安装'

    def test_error_text_1060_without_state_is_absent(self):
        # rc 不透传的极端场景: 输出含 1060 但没有 STATE 行 → 仍可判未安装(兜底保留)
        assert sm._parse_sc_state(1, 'OpenService 失败 1060:') == '未安装'

    def test_access_denied_is_unknown(self):
        assert sm._parse_sc_state(5, '拒绝访问。') == '未知'

    def test_ok_without_state_is_unknown(self):
        assert sm._parse_sc_state(0, 'SERVICE_NAME: x\n') == '未知'


class TestSvcStateExceptionPath:
    def test_subprocess_failure_is_unknown(self, monkeypatch):
        def boom(*args, **kwargs):
            raise OSError('sc 被拦截')
        monkeypatch.setattr(sm.subprocess, 'run', boom)
        # _svc_state 不引用 self, 可用 None 伪实例调用
        assert sm.ServerManagerApp._svc_state(None, 'erp-prod') == '未知'


class TestLoadAppConfig:
    """审查 #3 回归: 标量键写坏回落默认, 绝不炸启动。"""

    def _load(self, tmp_path, monkeypatch, stored):
        cfg_file = tmp_path / 'server_manager_config.json'
        cfg_file.write_text(json.dumps(stored), encoding='utf-8')
        monkeypatch.setattr(sm, '_CONFIG_FILE', cfg_file)
        return sm._load_app_config()

    def test_broken_scalar_keys_fall_back(self, tmp_path, monkeypatch):
        cfg = self._load(tmp_path, monkeypatch,
                         {'max_log_lines': 'abc', 'log_keep_lines': [1], 'full_stop_hold_ms': None})
        assert cfg['max_log_lines'] == 2000
        assert cfg['log_keep_lines'] == 1600
        assert cfg['full_stop_hold_ms'] == 1500

    def test_valid_scalar_keys_normalized(self, tmp_path, monkeypatch):
        cfg = self._load(tmp_path, monkeypatch,
                         {'max_log_lines': 500, 'log_keep_lines': 300, 'full_stop_hold_ms': 900})
        assert (cfg['max_log_lines'], cfg['log_keep_lines'], cfg['full_stop_hold_ms']) == (500, 300, 900)

    def test_keep_lines_clamped_below_max(self, tmp_path, monkeypatch):
        cfg = self._load(tmp_path, monkeypatch, {'max_log_lines': 200, 'log_keep_lines': 5000})
        assert cfg['log_keep_lines'] < cfg['max_log_lines']

    def test_corrupt_json_falls_back_to_defaults(self, tmp_path, monkeypatch):
        cfg_file = tmp_path / 'server_manager_config.json'
        cfg_file.write_text('{broken json!!', encoding='utf-8')
        monkeypatch.setattr(sm, '_CONFIG_FILE', cfg_file)
        cfg = sm._load_app_config()
        assert cfg['max_log_lines'] == 2000
        assert cfg['redis_services'] == list(sm._DEFAULT_REDIS_SERVICES)


class TestApplyConfigPorts:
    """审查 #22 回归: 非法端口键必须返回留痕, 不得静默吞掉。"""

    def test_invalid_ports_returned(self):
        assert sm._apply_config_to_runtime(
            {'api_port': 'abc', 'web_port': 70000, 'redis_port': 6379}) == ['api_port', 'web_port']

    def test_valid_ports_applied(self):
        saved = (sm._PORTS.api, sm._PORTS.web, sm._PORTS.redis)
        try:
            assert sm._apply_config_to_runtime(
                {'api_port': 5003, 'web_port': 3001, 'redis_port': 6380}) == []
            assert (sm._PORTS.api, sm._PORTS.web, sm._PORTS.redis) == (5003, 3001, 6380)
        finally:
            sm._PORTS.api, sm._PORTS.web, sm._PORTS.redis = saved


class TestGetEnvValue:
    """审查 #19 回归: .env 值的成对引号必须剥掉。"""

    def _value_of(self, tmp_path, monkeypatch, raw):
        env_file = tmp_path / '.env'
        env_file.write_text(f'REDIS_PASSWORD={raw}\n', encoding='utf-8')
        monkeypatch.setattr(sm, '_PROJECT_DIR', tmp_path)
        return sm.ServerManagerApp._get_env_value(None, 'REDIS_PASSWORD')

    def test_double_quoted(self, tmp_path, monkeypatch):
        assert self._value_of(tmp_path, monkeypatch, '"abc123"') == 'abc123'

    def test_single_quoted(self, tmp_path, monkeypatch):
        assert self._value_of(tmp_path, monkeypatch, "'abc'") == 'abc'

    def test_unbalanced_quote_untouched(self, tmp_path, monkeypatch):
        # 首尾不是成对引号 → 保持原样(实现正确行为, 此用例锁定它)
        assert self._value_of(tmp_path, monkeypatch, "'ab'c") == "'ab'c"

    def test_bare_value_untouched(self, tmp_path, monkeypatch):
        assert self._value_of(tmp_path, monkeypatch, ' abc123 ') == 'abc123'
