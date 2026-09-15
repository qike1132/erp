"""`adapters._proc` 的测试 —— 子进程调用公共约定。

这一层只有几十行，但守住的是三条**踩过坑**的约定：

  1. 无窗口（GUI 程序调控制台命令会闪黑框）
  2. OEM 代码页解码（中文 Windows 的 sc/netstat 输出是 GBK）
  3. `errors='replace'`（PYTHONUTF8=1 下遇 OEM 输出会在读取线程抛异常，
     导致 stdout **整段丢失**）

第 3 条尤其隐蔽：它不是「中文变乱码」，而是「输出全没了」。
"""

from __future__ import annotations

import subprocess

import pytest

from server_manager_v8.adapters import _proc


class TestCap:
    """`cap()` 迁移自 v5.40 `_cap()`（L112-124）。"""

    def test_has_capture_and_timeout(self):
        kw = _proc.cap(7)
        assert kw['capture_output'] is True
        assert kw['timeout'] == 7

    def test_no_window_flag_on_windows(self, monkeypatch):
        """Windows 下必须带 CREATE_NO_WINDOW，否则 GUI 程序调控制台命令会闪黑框。"""
        monkeypatch.setattr(_proc, 'is_windows', lambda: True)
        assert _proc.cap()['creationflags'] == _proc.no_window_flag()
        assert _proc.cap()['creationflags'] != 0

    def test_creationflags_zero_on_non_windows(self, monkeypatch):
        """★ 迁移保真：旧实现是 `CREATE_NO_WINDOW if _IS_WINDOWS else 0`。

        非 Windows 下必须是 0（对拍实测：写成不判平台的 getattr 会漏出 134217728）。
        """
        monkeypatch.setattr(_proc, 'is_windows', lambda: False)
        assert _proc.cap()['creationflags'] == 0

    def test_no_window_flag_matches_platform(self):
        """`no_window_flag()` 与平台判定一致。"""
        assert _proc.no_window_flag() == (
            getattr(_proc.subprocess, 'CREATE_NO_WINDOW', 0)
            if _proc.is_windows() else 0
        )

    def test_timeout_default_is_15(self):
        """旧实现 `_cap(timeout=15, oem=True)`。"""
        assert _proc.cap()['timeout'] == 15

    def test_oem_true_uses_oem_encoding(self, monkeypatch):
        monkeypatch.setattr(_proc, 'is_windows', lambda: True)
        kw = _proc.cap(oem=True)
        assert kw['encoding'] == 'oem'
        assert kw['errors'] == 'replace'
        assert 'text' not in kw

    def test_oem_false_uses_text_mode_with_replace(self, monkeypatch):
        """★ 第 3 条约定：errors='replace' 必给。

        缺了它，PYTHONUTF8=1 环境下遇 OEM 输出会在读取线程抛
        UnicodeDecodeError，stdout 整段丢失（不是乱码，是没有）。
        """
        monkeypatch.setattr(_proc, 'is_windows', lambda: True)
        kw = _proc.cap(oem=False)
        assert kw['text'] is True
        assert kw['errors'] == 'replace'
        assert 'encoding' not in kw

    def test_non_windows_falls_back_to_text(self, monkeypatch):
        """非 Windows 无 'oem' 编码，必须退到 text 模式（否则 ValueError）。"""
        monkeypatch.setattr(_proc, 'is_windows', lambda: False)
        kw = _proc.cap(oem=True)
        assert kw['text'] is True
        assert kw['errors'] == 'replace'

    def test_errors_replace_always_present(self, monkeypatch):
        """穷举四种组合，errors='replace' 必须恒在。"""
        for is_win in (True, False):
            for oem in (True, False):
                monkeypatch.setattr(_proc, 'is_windows', lambda w=is_win: w)
                assert _proc.cap(oem=oem)['errors'] == 'replace', (is_win, oem)


class TestRunCapture:
    def test_returns_code_stdout_stderr_triple(self, fake_runner_cls):
        runner = fake_runner_cls().on(['sc', 'query', 'x'], 0, 'OUT', 'ERR')
        code, out, err = _proc.run_capture(['sc', 'query', 'x'], runner=runner.run)
        assert (code, out, err) == (0, 'OUT', 'ERR')

    def test_none_outputs_normalized_to_empty_string(self, fake_runner_cls):
        runner = fake_runner_cls().on(['cmd'], 0, None, None)
        code, out, err = _proc.run_capture(['cmd'], runner=runner.run)
        assert (code, out, err) == (0, '', '')

    def test_stdout_and_stderr_stay_separate(self, fake_runner_cls):
        """★ 与旧代码的差异点：旧实现把两路拼接后交给解析器。

        `sc` 的 1060 错误走 stderr，而运行中服务的 `PID : 1060` 走 stdout，
        一拼就可能凑出「含 1060 但不含 STATE」的组合（v5.39 审查 #1 的成因）。
        本实现分离返回，让调用方决定怎么处理。
        """
        runner = fake_runner_cls().on(['sc'], 1060, '', 'ERROR 1060')
        code, out, err = _proc.run_capture(['sc'], runner=runner.run)
        assert out == ''
        assert err == 'ERROR 1060'

    def test_passes_argv_as_list(self, fake_runner_cls):
        runner = fake_runner_cls().on(['a', 'b'], 0)
        _proc.run_capture(['a', 'b'], runner=runner.run)
        assert runner.argvs == [['a', 'b']]

    def test_executable_injected_when_given(self, fake_runner_cls):
        """nssm 调用需要 executable 指向真实 nssm.exe。"""
        runner = fake_runner_cls().on(['nssm', 'stop', 'x'], 0)
        _proc.run_capture(['nssm', 'stop', 'x'], executable=r'C:\nssm\nssm.exe',
                          runner=runner.run)
        kw = runner.kwargs_for(['nssm', 'stop', 'x'])
        assert kw is not None
        assert kw['executable'] == r'C:\nssm\nssm.exe'

    def test_no_executable_key_when_not_given(self, fake_runner_cls):
        runner = fake_runner_cls().on(['sc'], 0)
        _proc.run_capture(['sc'], runner=runner.run)
        assert 'executable' not in runner.kwargs_for(['sc'])

    def test_timeout_propagates(self, fake_runner_cls):
        """超时**不吞** —— 由调用方区分处理（`run_verb` 要给出专门文案）。"""
        runner = fake_runner_cls().on(['slow'], 0)
        runner.raise_on(['slow'], subprocess.TimeoutExpired('slow', 5))
        with pytest.raises(subprocess.TimeoutExpired):
            _proc.run_capture(['slow'], runner=runner.run)


class TestRunQuiet:
    def test_true_on_zero_exit(self, fake_runner_cls):
        runner = fake_runner_cls().on(['taskkill'], 0)
        assert _proc.run_quiet(['taskkill'], runner=runner.run) is True

    def test_false_on_nonzero_exit(self, fake_runner_cls):
        runner = fake_runner_cls().on(['taskkill'], 1)
        assert _proc.run_quiet(['taskkill'], runner=runner.run) is False

    def test_false_on_exception(self, fake_runner_cls):
        """★ 终止类命令是「尽力而为」语义：进程可能已自行退出，命令报错属正常。"""
        runner = fake_runner_cls()
        runner.raise_on(['taskkill'], OSError('boom'))
        assert _proc.run_quiet(['taskkill'], runner=runner.run) is False

    def test_never_raises(self, fake_runner_cls):
        for exc in (OSError('x'), RuntimeError('y'), subprocess.TimeoutExpired('z', 1)):
            runner = fake_runner_cls()
            runner.raise_on(['cmd'], exc)
            assert _proc.run_quiet(['cmd'], runner=runner.run) is False


class TestIsWindows:
    def test_reflects_platform_and_is_patchable(self, monkeypatch):
        """抽成函数是为了让「非 Windows 分支」可被测到。"""
        monkeypatch.setattr(_proc, 'is_windows', lambda: False)
        assert _proc.is_windows() is False
        monkeypatch.setattr(_proc, 'is_windows', lambda: True)
        assert _proc.is_windows() is True

    def test_real_value_matches_os_name(self):
        import os
        assert _proc.is_windows() == (os.name == 'nt')


class TestPythonExecutable:
    def test_returns_absolute_path(self):
        import os
        p = _proc.python_executable()
        assert p and os.path.isabs(p)
