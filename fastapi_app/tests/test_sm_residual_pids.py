"""F3-10：残留进程判据必须限定运行时进程名，避免误杀编辑器/终端。"""
import psutil
import pytest

from server_manager import windows_ops


class _Proc:
    def __init__(self, pid, name, cmdline, cwd):
        self.info = {'pid': pid, 'name': name, 'cmdline': cmdline}
        self._cwd = cwd

    def cwd(self):
        return self._cwd


@pytest.fixture
def fake_procs(monkeypatch, tmp_path):
    project = tmp_path / 'erp'
    project.mkdir()
    other = tmp_path / 'other'
    other.mkdir()
    procs = [
        # 编辑器打开项目文件：命令行含项目路径，但进程名不是运行时 → 不得命中
        _Proc(999001, 'Code.exe', ['Code.exe', str(project / 'a.py')], str(project)),
        # 真正的残留 python：cwd 指向项目 → 命中
        _Proc(999002, 'python.exe', ['python', 'manage.py'], str(project)),
        # 无关 python：cwd/cmdline 都不指向项目 → 不命中
        _Proc(999003, 'python.exe', ['python', 'x.py'], str(other)),
    ]
    monkeypatch.setattr(psutil, 'process_iter', lambda *_: procs)
    return project


def test_editor_with_project_path_is_not_killed(fake_procs):
    pids = windows_ops.find_project_residual_pids(fake_procs)
    assert 999001 not in pids
    assert 999002 in pids
    assert 999003 not in pids
