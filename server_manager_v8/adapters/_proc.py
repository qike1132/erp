"""适配层共享工具 — Windows 子进程捕获（v6 ``_cap`` 的显式化迁移）。

v6 约定（Mimosa 合规，必须逐行保留）：
    - 所有 subprocess 调用 argv[0] 为**字符串字面量**
    - 运行时解析的可执行文件绝对路径经 ``executable=`` 命名参数传入
    - 无 shell 参与（列表形式 argv）
    - PYTHONUTF8=1 环境下 sc/nssm 输出按 OEM 代码页解码，否则中文服务名
      被误判为未安装
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass

__all__ = ['IS_WINDOWS', 'NO_WINDOW', 'Capture', 'CommandError', 'run_capture']

IS_WINDOWS = sys.platform == 'win32'
NO_WINDOW = subprocess.CREATE_NO_WINDOW if IS_WINDOWS else 0


class CommandError(Exception):
    """子进程执行失败（超时 / 启动失败 / 非零退出）。msg 面向 UI 展示。"""


@dataclass(frozen=True)
class Capture:
    """一次命令执行的完整结果（显式化：失败原因永不静默）。"""

    returncode: int
    stdout: str
    stderr: str

    @property
    def combined(self) -> str:
        return (self.stdout or '') + (self.stderr or '')

    @property
    def ok(self) -> bool:
        return self.returncode == 0


def run_capture(
    argv: list[str],
    *,
    executable: str | None = None,
    timeout: float = 15.0,
    oem: bool = True,
    env: dict[str, str] | None = None,
    cwd: str | None = None,
) -> Capture:
    """执行命令并捕获输出（无窗口 + OEM 解码）。

    失败语义：超时或启动失败抛 CommandError（调用方转 OpResult.failure），
    非零退出码不抛 —— 由调用方依据业务语义自行判断（如 sc query 返回 1060
    表示服务不存在，是正常业务分支而非异常）。
    """
    kwargs: dict[str, object] = {
        'capture_output': True,
        'timeout': timeout,
        'creationflags': NO_WINDOW,
        'env': env,
        'cwd': cwd,
    }
    if oem and IS_WINDOWS:
        kwargs.update(encoding='oem', errors='replace')
    else:
        kwargs.update(text=True)
    if executable:
        kwargs['executable'] = executable
    try:
        result = subprocess.run(argv, **kwargs)  # type: ignore[arg-type]
    except subprocess.TimeoutExpired as exc:
        raise CommandError(f'命令超时（{timeout:g}s）: {" ".join(argv[:3])}…') from exc
    except OSError as exc:
        raise CommandError(f'无法执行 {argv[0]}: {exc}') from exc
    return Capture(returncode=result.returncode, stdout=result.stdout or '', stderr=result.stderr or '')
