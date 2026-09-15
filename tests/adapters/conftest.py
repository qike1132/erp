"""Adapter 层测试的公共夹具。

适配层允许 I/O，但**单测里不该真的执行 `taskkill`、不该真的等 60 秒**。
这里提供 `FakeRunner`（伪造 subprocess.run）与 `FakeProc`（伪造 psutil.Process），
让适配器的每个分支都能被确定性地测到。

设计要点：`FakeRunner` 记录**收到的 argv**，因为适配层最容易出错的
恰恰是「参数拼装」（taskkill 的参数顺序、sc 的 verb、nssm 的 Executable 注入）。
只断言返回值而不断言 argv，会漏掉整类 bug。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest


@dataclass
class FakeRunner:
    """伪造 `subprocess.run`。

    用法：
        runner = FakeRunner().on(['sc','query','erp-prod'], 0, 'STATE: 4 RUNNING')
        code, out, err = run_capture(['sc','query','erp-prod'], runner=runner.run)

    未匹配的调用**抛出异常**（而不是返回默认值）—— 这样测试会明确暴露
    「实现调了一个没预期的命令」，而不是悄悄通过。
    """

    responses: list[tuple[list[str], int, str, str]] = field(default_factory=list)
    calls: list[dict[str, Any]] = field(default_factory=list)
    default: tuple[int, str, str] | None = None
    raises: dict[tuple[str, ...], Exception] = field(default_factory=dict)

    def on(
        self,
        argv: list[str],
        code: int = 0,
        stdout: str = '',
        stderr: str = '',
    ) -> FakeRunner:
        """登记一条按 argv 精确匹配的响应。"""
        self.responses.append((list(argv), code, stdout, stderr))
        return self

    def matching(
        self,
        prefix: list[str],
        code: int = 0,
        stdout: str = '',
        stderr: str = '',
    ) -> FakeRunner:
        """登记一条按 argv 前缀匹配的响应（用于 PSID 等可变参数）。

        实现为「把尾部补通配」——匹配时只比对前 len(prefix) 项。
        """
        self.responses.append((list(prefix) + ['\x00WILDCARD'], code, stdout, stderr))
        return self

    def raise_on(self, argv: list[str], exc: Exception) -> FakeRunner:
        self.raises[tuple(argv)] = exc
        return self

    def run(self, argv: Any, **kwargs: Any) -> Any:
        argv_list = list(argv)
        self.calls.append({'argv': argv_list, 'kwargs': kwargs})

        key = tuple(argv_list)
        if key in self.raises:
            raise self.raises[key]

        for exp_argv, code, out, err in self.responses:
            if exp_argv and exp_argv[-1] == '\x00WILDCARD':
                prefix = exp_argv[:-1]
                if argv_list[: len(prefix)] == prefix:
                    return SimpleNamespace(returncode=code, stdout=out, stderr=err)
                continue
            if exp_argv == argv_list:
                return SimpleNamespace(returncode=code, stdout=out, stderr=err)

        if self.default is not None:
            code, out, err = self.default
            return SimpleNamespace(returncode=code, stdout=out, stderr=err)

        raise AssertionError(f'FakeRunner 收到未登记的调用: {argv_list}')

    # ── 断言辅助 ────────────────────────────────────────────────

    @property
    def argvs(self) -> list[list[str]]:
        return [c['argv'] for c in self.calls]

    def called_with(self, argv: list[str]) -> bool:
        return argv in self.argvs

    def count(self, argv: list[str]) -> int:
        return sum(1 for a in self.argvs if a == argv)

    def kwargs_for(self, argv: list[str]) -> dict[str, Any] | None:
        for c in self.calls:
            if c['argv'] == argv:
                return c['kwargs']
        return None


@dataclass
class FakeProc:
    """伪造 `psutil.Process`。

    覆盖残留扫描用到的三个能力：`info` / `children` / `cwd` / `parents` / `kill`。
    """

    pid: int
    name: str = 'python.exe'
    cmdline: list[str] = field(default_factory=list)
    cwd_value: str | None = ''
    cwd_raises: bool = False
    children_list: list[FakeProc] = field(default_factory=list)
    parents_list: list[FakeProc] = field(default_factory=list)
    killed: bool = False
    kill_raises: bool = False

    @property
    def info(self) -> dict[str, Any]:
        return {'pid': self.pid, 'name': self.name, 'cmdline': self.cmdline}

    def children(self, recursive: bool = False) -> list[FakeProc]:
        if not recursive:
            return list(self.children_list)
        out: list[FakeProc] = []
        stack = list(self.children_list)
        while stack:
            node = stack.pop()
            out.append(node)
            stack.extend(node.children_list)
        return out

    def parents(self) -> list[FakeProc]:
        return list(self.parents_list)

    def cwd(self) -> str:
        if self.cwd_raises:
            raise PermissionError('access denied')
        return self.cwd_value or ''

    def kill(self) -> None:
        if self.kill_raises:
            raise PermissionError('access denied')
        self.killed = True


def process_iter_factory(procs: list[FakeProc]):
    """构造一个 `psutil.process_iter` 替身。"""

    def _iter(attrs: Any = None) -> list[FakeProc]:
        return list(procs)

    return _iter


def process_factory(procs: list[FakeProc], *, missing: set[int] | None = None):
    """构造一个 `psutil.Process` 替身；`missing` 中的 pid 会抛异常（模拟已退出）。"""
    by_pid = {p.pid: p for p in procs}
    gone = missing or set()

    def _factory(pid: int) -> FakeProc:
        if pid in gone or pid not in by_pid:
            raise Exception(f'no such process: {pid}')
        return by_pid[pid]

    return _factory


# ═══════════════════════════════════════════════════════════════════
# pytest fixtures
# ═══════════════════════════════════════════════════════════════════


@pytest.fixture
def fake_runner_cls():
    """把 `FakeRunner` 类本身作为夹具暴露给测试（便于 `fake_runner_cls()` 直接实例化）。"""
    return FakeRunner


@pytest.fixture
def runner():
    """一个空的 `FakeRunner` 实例。"""
    return FakeRunner()
