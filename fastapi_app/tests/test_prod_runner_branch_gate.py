"""P2-101 回归：prod_runner 启动前必须过 git 分支闸门。

NSSM 崩溃自愈直接重启 `python -m fastapi_app.core.prod_runner`，不经过
server_manager；若工作区不在 main，会把分支代码跑进生产。
"""
from fastapi_app.core import prod_runner


def test_main_refuses_non_main_branch(monkeypatch):
    monkeypatch.setattr(prod_runner, '_load_dotenv', lambda: None)
    monkeypatch.setattr(prod_runner, '_init_log_streams', lambda: None)
    monkeypatch.setattr(
        'server_manager.git_guard.check_production_branch',
        lambda *a, **k: (False, '当前分支为 dev，生产启停只允许 main'),
    )

    class _NoSupervisor:
        def __init__(self, *a, **k):
            raise AssertionError('分支闸门拒绝后不得构造 Supervisor')

    monkeypatch.setattr(prod_runner, 'Supervisor', _NoSupervisor)
    assert prod_runner.main([]) == 3
