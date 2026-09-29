"""Worker 数「应用并重启」：ServiceOps 只改单一环境变量键的行为回归锁。

背景（2026-09-29）
------------------
server_manager 的 Worker 下拉框此前只在「安装生产服务」流程里被消费，而
``nssm_install`` 会**整包覆盖** AppEnvironmentExtra；且下拉框初始值取的是
server_manager **自身进程**的环境变量（默认 4），不是 NSSM 里的真值 ——
于是「界面显示 4、实际跑 8」，点一下「安装服务」就把 8 静默降回 4。

本文件锁住新增的单键读写能力：
* ``get_env_extra_key`` 读真值（供下拉框初始化，消灭静默降级）；
* ``set_env_extra_key`` 只替换目标键、其余元素逐项原样保留，
  且 **逐项传参**给 ``nssm set``（拼成整串会让 NSSM 只解析出第一项 —— 既有缺陷）。

只伪造 ``run_capture``，不碰真实 NSSM、不 import tkinter —— CI 可跑。
"""
from pathlib import Path

from server_manager.constants import _SVC_API, _SVC_ARQ
from server_manager.service_ops import ServiceOps

NSSM = r'C:\nssm\nssm.exe'

# 生产当前真实形态（2026-09-29 修复后）：6 个独立元素
CURRENT = [
    'APP_ENV=production',
    'FASTAPI_DEBUG=false',
    r'PYTHONPATH=D:\erp_system',
    'PYTHONUTF8=1',
    'PYTHONUNBUFFERED=1',
    'UVICORN_WORKERS=8',
]


class _FakeNssm:
    """伪造 run_capture：只在内存里维护每个服务的元素列表。"""

    def __init__(self, services: dict[str, list[str]]):
        self.services = {k: list(v) for k, v in services.items()}
        self.calls: list[list[str]] = []
        self.get_rc = 0
        self.set_rc = 0
        self.verify_override: list[str] | None = None  # 用于伪造「写后回读不一致」

    def __call__(self, args, timeout=20):
        self.calls.append(list(args))
        verb = args[1] if len(args) > 1 else ''
        name = args[2] if len(args) > 2 else ''
        if verb == 'get':
            if self.get_rc != 0:
                return self.get_rc, 'OpenService(): 拒绝访问'
            return 0, '\r\n'.join(self.services.get(name, []))
        if verb == 'set':
            elements = list(args[4:])
            self.services[name] = list(self.verify_override) if self.verify_override is not None else elements
            return self.set_rc, ''
        return -1, f'unexpected verb {verb}'


def _svc(fake: _FakeNssm) -> ServiceOps:
    ops = ServiceOps(msg_queue=None, gate=None, project_dir=Path('.'), log_message=lambda *a, **k: None)
    ops.run_capture = fake
    return ops


# ---------------------------------------------------------------- get

def test_get_env_extra_key_reads_configured_value():
    fake = _FakeNssm({_SVC_API: CURRENT})
    assert _svc(fake).get_env_extra_key(NSSM, _SVC_API, 'UVICORN_WORKERS') == '8'


def test_get_env_extra_key_missing_key_returns_none():
    fake = _FakeNssm({_SVC_API: ['APP_ENV=production']})
    assert _svc(fake).get_env_extra_key(NSSM, _SVC_API, 'UVICORN_WORKERS') is None


def test_get_env_extra_key_nssm_failure_returns_none():
    fake = _FakeNssm({_SVC_API: CURRENT})
    fake.get_rc = 5  # 拒绝访问
    assert _svc(fake).get_env_extra_key(NSSM, _SVC_API, 'UVICORN_WORKERS') is None


def test_get_env_extra_key_ignores_empty_lines():
    fake = _FakeNssm({_SVC_API: CURRENT})
    fake.services[_SVC_API].append('')  # MULTI_SZ 终止空元素
    assert _svc(fake).get_env_extra_key(NSSM, _SVC_API, 'UVICORN_WORKERS') == '8'


# ---------------------------------------------------------------- set

def test_set_env_extra_key_replaces_only_target_and_preserves_others():
    fake = _FakeNssm({_SVC_API: CURRENT})
    ok, msg = _svc(fake).set_env_extra_key(NSSM, _SVC_API, 'UVICORN_WORKERS', '4')
    assert ok, msg
    written = fake.services[_SVC_API]
    assert 'UVICORN_WORKERS=4' in written
    assert len(written) == len(CURRENT), f'元素数应不变，实际 {written}'
    for original in CURRENT:
        if original.startswith('UVICORN_WORKERS='):
            continue
        assert original in written, f'不应改动其它元素: {original}'
    assert written.index('UVICORN_WORKERS=4') == CURRENT.index('UVICORN_WORKERS=8')


def test_set_env_extra_key_passes_elements_separately_not_joined():
    """拼成一整串会让 NSSM 只解析出第一项 —— 必须是多个 argv 元素。"""
    fake = _FakeNssm({_SVC_API: CURRENT})
    _svc(fake).set_env_extra_key(NSSM, _SVC_API, 'UVICORN_WORKERS', '6')
    set_calls = [c for c in fake.calls if len(c) > 1 and c[1] == 'set']
    assert set_calls, '应有 nssm set 调用'
    args = set_calls[-1]
    assert args[:4] == [NSSM, 'set', _SVC_API, 'AppEnvironmentExtra']
    assert len(args) - 4 == len(CURRENT), '每个元素一个 argv，不能拼串'
    assert all(' ' not in e or '=' in e for e in args[4:]), '不应出现空格拼接的整串元素'


def test_set_env_extra_key_appends_when_key_absent():
    fake = _FakeNssm({_SVC_API: ['APP_ENV=production']})
    ok, msg = _svc(fake).set_env_extra_key(NSSM, _SVC_API, 'UVICORN_WORKERS', '2')
    assert ok, msg
    assert fake.services[_SVC_API] == ['APP_ENV=production', 'UVICORN_WORKERS=2']


def test_set_env_extra_key_verifies_after_write():
    """写后回读不一致必须报失败（否则界面会误报成功）。"""
    fake = _FakeNssm({_SVC_API: CURRENT})
    fake.verify_override = ['APP_ENV=production', 'UVICORN_WORKERS=8']  # 回读仍是旧值
    ok, msg = _svc(fake).set_env_extra_key(NSSM, _SVC_API, 'UVICORN_WORKERS', '4')
    assert not ok
    assert '校验' in msg or '不一致' in msg


def test_set_env_extra_key_fails_when_read_fails():
    fake = _FakeNssm({_SVC_API: CURRENT})
    fake.get_rc = 5
    ok, msg = _svc(fake).set_env_extra_key(NSSM, _SVC_API, 'UVICORN_WORKERS', '4')
    assert not ok
    assert not [c for c in fake.calls if len(c) > 1 and c[1] == 'set'], '读失败不得盲写'


def test_set_env_extra_key_fails_when_set_fails():
    fake = _FakeNssm({_SVC_API: CURRENT})
    fake.set_rc = 5
    ok, msg = _svc(fake).set_env_extra_key(NSSM, _SVC_API, 'UVICORN_WORKERS', '4')
    assert not ok


def test_set_env_extra_key_rejects_empty_value():
    fake = _FakeNssm({_SVC_API: CURRENT})
    ok, msg = _svc(fake).set_env_extra_key(NSSM, _SVC_API, 'UVICORN_WORKERS', '')
    assert not ok
    assert not [c for c in fake.calls if len(c) > 1 and c[1] == 'set'], '空值不得写入'


# ---------------------------------------------------------------- 只重启单个服务

def test_restart_one_service_restarts_only_the_named_one():
    """worker 数变更只需重启 erp-prod —— 不得顺带重启 erp-arq / 前端 / 两个 Redis。"""
    fake = _FakeNssm({_SVC_API: CURRENT})
    ops = _svc(fake)
    ops.wait_service_running = lambda name, timeout=25: True
    assert ops.restart_one_service(_SVC_API) is True
    restarted = [c[2] for c in fake.calls if len(c) > 1 and c[1] == 'restart']
    assert restarted == [_SVC_API], f'只应重启 {_SVC_API}，实际 {restarted}'


# ---------------------------------------------------------------- 接线（app.py 为 tkinter 绑定，按本仓惯例用源码断言）

def test_app_wires_apply_button_and_flow():
    src = (Path(__file__).resolve().parent.parent / 'server_manager' / 'app.py').read_text(encoding='utf-8')
    assert 'def _apply_workers' in src, '缺 _apply_workers 动作入口'
    assert 'def _apply_workers_flow' in src, '缺 _apply_workers_flow 流程'
    assert 'set_env_extra_key' in src, '流程未调用 set_env_extra_key'
    assert "text='应用'" in src, '缺「应用」按钮'
    # 安装服务流程仍必须逐项传参（既有正确行为，不得回归）
    assert 'env_extra' in src


def test_app_worker_default_no_longer_reads_own_env_only():
    """下拉框初始值必须来自 NSSM 真值，而不是 server_manager 自身环境变量。

    允许保留 os.getenv 作为**读不到时**的兜底，但必须同时出现读 NSSM 的调用。
    """
    src = (Path(__file__).resolve().parent.parent / 'server_manager' / 'app.py').read_text(encoding='utf-8')
    assert 'get_env_extra_key' in src, '下拉框未读 NSSM 真值 → 会重现「显示 4、实际 8」'
    assert _SVC_API in src and _SVC_ARQ in src
