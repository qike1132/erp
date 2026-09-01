"""进程与端口适配器 — 实现 domain.ports.ProcessPort（v6 进程资产的显式化迁移）。

迁移来源（server_manager.py v6）：
    - ``_taskkill`` / ``_taskkill_many`` → kill_tree（taskkill /T /F 进程树）
    - ``_kill_port_sync`` / ``_find_port_pids`` → kill_port / find_port_pids
      （netstat -ano 解析 + 多轮重试 + psutil 直杀回落 taskkill）
    - 开发模式 ``subprocess.Popen`` 启动 → spawn（安全约定保留）

失败语义：所有操作返回显式结果对象，**survivors 非空必须上报**（不静默）。
"""

from __future__ import annotations

import time

from server_manager_v8.domain import (
    KillResult,
    OpResult,
    ProcessHandle,
    SpawnError,
    SpawnSpec,
)

from ._proc import IS_WINDOWS, NO_WINDOW, CommandError, run_capture

__all__ = ['ProcessWinAdapter', 'parse_netstat_pids']

try:
    import psutil
except ImportError:  # pragma: no cover - 依赖可选
    psutil = None


def parse_netstat_pids(output: str, port: int) -> list[int]:
    """解析 netstat -ano 输出，返回占用指定端口的 PID 列表（可单测的纯函数）。

    只统计 LISTENING / TIME_WAIT 状态的连接；PID 必须为正整数。
    """
    pids: set[int] = set()
    for line in output.splitlines():
        if 'LISTENING' not in line and 'TIME_WAIT' not in line:
            continue
        parts = line.split()
        if len(parts) < 5:
            continue
        local = parts[1]
        if ':' not in local:
            continue
        if local.rsplit(':', 1)[-1] != str(port):
            continue
        pid = parts[-1]
        if pid.isdigit() and int(pid) > 0:
            pids.add(int(pid))
    return sorted(pids)


def _pid_alive(pid: int) -> bool:
    """进程是否存活。优先 psutil；缺失时 tasklist 兜底。"""
    if not pid:
        return False
    if psutil is not None:
        try:
            proc = psutil.Process(pid)
            return proc.is_running() and proc.status() not in ('zombie',)
        except psutil.NoSuchProcess:
            return False
        except psutil.Error:  # pragma: no cover - 平台差异
            return False
    try:
        cap = run_capture(['tasklist', '/FI', f'PID eq {pid}', '/FO', 'CSV', '/NH'], timeout=5)
    except CommandError:
        return False
    return pid in cap.stdout or pid in cap.stderr


class ProcessWinAdapter:
    """Windows 进程/端口操作。非 Windows 平台上的写操作返回显式失败。"""

    def _bail(self, msg: str) -> OpResult:
        return OpResult.failure(msg) if IS_WINDOWS else OpResult.failure(f'非 Windows 平台: {msg}')

    # ---- ProcessPort 实现 ----

    def find_port_pids(self, port: int) -> list[int]:
        if not IS_WINDOWS or not port:
            return []
        try:
            cap = run_capture(['netstat', '-ano'], timeout=10)
        except CommandError:
            return []
        return parse_netstat_pids(cap.stdout, port)

    def kill_tree(self, pid: int, *, timeout_s: float = 5.0) -> KillResult:
        start = time.monotonic()
        if not pid:
            return KillResult.failure('PID 为空')
        if not IS_WINDOWS:
            return KillResult.failure('非 Windows 平台，无法 taskkill 进程树')
        try:
            cap = run_capture(
                ['taskkill', '/F', '/T', '/PID', str(pid)],
                timeout=max(5.0, timeout_s),
            )
        except CommandError as exc:
            return KillResult.failure(f'终止进程树失败: {exc}', detail=str(exc))
        killed = [pid]
        if not cap.ok:
            alive = _pid_alive(pid)
            return KillResult(
                ok=not alive,
                reason=f'taskkill 失败（返回码 {cap.returncode}）: {cap.combined.strip()[:120]}',
                killed_pids=tuple(killed),
                survivors=(pid,) if alive else (),
                duration_ms=int((time.monotonic() - start) * 1000),
            )
        if psutil is not None:
            # psutil 双通道兜底：taskkill 未清理干净时强杀残留（v6 资产）
            for child in self._psutil_children(pid):
                try:
                    child.kill()
                    killed.append(child.pid)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    # 进程已退出 / 权限受限 —— 正常竞争，残留由 survivors 上报
                    continue
        survivors = [pid] if _pid_alive(pid) else []
        return KillResult.done(
            killed_pids=tuple(killed),
            survivors=tuple(survivors),
            duration_ms=int((time.monotonic() - start) * 1000),
        )

    def kill_port(self, port: int, *, rounds: int = 3) -> KillResult:
        """清理端口占用：多 PID 多轮重试（v6 语义：每轮间隔 0.5s）。"""
        start = time.monotonic()
        if not IS_WINDOWS or not port:
            return KillResult.failure('非 Windows 平台或端口无效')
        killed: list[int] = []
        for _ in range(max(1, rounds)):
            pids = self.find_port_pids(port)
            if not pids:
                break
            for pid in pids:
                result = self.kill_tree(pid)
                killed.extend(result.killed_pids)
            time.sleep(0.5)
        survivors = self.find_port_pids(port)
        return KillResult.done(
            killed_pids=tuple(dict.fromkeys(killed)),
            survivors=tuple(survivors),
            duration_ms=int((time.monotonic() - start) * 1000),
        )

    def spawn(self, spec: SpawnSpec) -> ProcessHandle:
        """启动子进程，返回进程句柄（安全约定：argv 字面量 + executable= + 无 shell）。

        失败抛 SpawnError（携带 reason，不静默）。
        """
        if not spec.argv:
            raise SpawnError('SpawnSpec.argv 为空')
        import subprocess

        env = None
        if spec.env_extra:
            import os as _os

            env = _os.environ.copy()
            env.update(dict(spec.env_extra))
        kwargs: dict[str, object] = {
            'cwd': spec.cwd or None,
            'env': env,
            'stdout': subprocess.PIPE,
            'stderr': subprocess.STDOUT,
            'creationflags': NO_WINDOW,
            'text': False,
        }
        if spec.executable:
            kwargs['executable'] = spec.executable
        try:
            proc = subprocess.Popen(list(spec.argv), **kwargs)  # type: ignore[arg-type]
        except OSError as exc:
            raise SpawnError(str(exc)) from exc
        return ProcessHandle(pid=proc.pid)

    def handle(self, pid: int) -> ProcessHandle | None:
        if not pid or not _pid_alive(pid):
            return None
        return ProcessHandle(pid=pid)

    # ---- 内部 ----

    @staticmethod
    def _psutil_children(pid: int) -> list[object]:
        if psutil is None:
            return []
        try:
            return psutil.Process(pid).children(recursive=True)
        except psutil.Error:
            return []
