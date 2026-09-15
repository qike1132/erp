"""子进程调用公共约定 —— 所有 Windows 命令适配器的底座。

═══════════════════════════════════════════════════════════════════
迁移来源：server_manager.py v5.40 `_cap()`（L112-124）
═══════════════════════════════════════════════════════════════════

`_cap()` 只有 12 行，但它是整个程序与 Windows 命令行打交道的**唯一正确姿势**，
踩过的坑全在里面。三条约定缺一不可：

1. **`creationflags=_NO_WINDOW`**
   GUI 程序调用控制台命令时不加这个，会闪出黑框（或从 pythonw 启动时直接异常）。

2. **`encoding='oem'`（OEM 代码页解码）**
   `sc` / `nssm` / `netstat` / `tasklist` / `wmic` 在中文 Windows 上输出的是
   GBK（OEM 936），不是 UTF-8。按 UTF-8 硬解会把中文服务名/路径解成乱码，
   而乱码进到状态判定里就是「查不出来」→ 被判「未知」或「未安装」→ 事故。

3. **`errors='replace'`**
   ★ 尤其致命的一条：`PYTHONUTF8=1` 环境下 text 模式默认按 UTF-8 解码，
   遇到 OEM 输出会在**读取线程**抛 `UnicodeDecodeError`，
   导致 `stdout` **整段丢失**（不是丢几个字符，是丢全部）。
   `errors='replace'` 保证读取线程永不抛。

═══════════════════════════════════════════════════════════════════
为什么单独一个模块
═══════════════════════════════════════════════════════════════════

适配层有 4 个模块要调外部命令（service_nssm / process_win / 未来的 metrics）。
把这套约定集中一处，避免「某个新加的调用忘了加 oem=True」这类错误悄悄扩散。
spec 的 `hiddenimports` 里已把它列为独立模块（`server_manager_v8.adapters._proc`）。

═══════════════════════════════════════════════════════════════════
依赖注入设计
═══════════════════════════════════════════════════════════════════

本模块的函数都接受可选 `runner` 参数（默认 `subprocess.run`）。
这样上层可以用假的 runner 做**不真实执行命令**的单测 ——
适配层虽然允许 I/O，但**单测里不该真的去 taskkill 一个进程**。
"""

from __future__ import annotations

import os
import subprocess
import sys
from typing import Any, Callable, Sequence

# Windows 专有常量：非 Windows 下必须传 0。
# ★ 迁移保真要点：旧实现是
#       _NO_WINDOW = subprocess.CREATE_NO_WINDOW if _IS_WINDOWS else 0
#   即**按平台**取 0 或标志位。若写成 `getattr(subprocess, 'CREATE_NO_WINDOW', 0)`
IS_WINDOWS = os.name == 'nt'

# 命令执行器签名（subprocess.run 兼容）
Runner = Callable[..., Any]


def is_windows() -> bool:
    """当前是否 Windows。

    抽成函数而非直接暴露 `IS_WINDOWS` 常量，是为了让测试可以 monkeypatch ——
    适配层的「非 Windows 行为」分支同样需要被测到。
    """
    return os.name == 'nt'


def no_window_flag() -> int:
    """当前平台应使用的 `creationflags`。

    ★ 迁移保真要点：旧实现是

        _NO_WINDOW = subprocess.CREATE_NO_WINDOW if _IS_WINDOWS else 0

    即**按平台**决定 0 还是标志位。若写成
    `getattr(subprocess, 'CREATE_NO_WINDOW', 0)` 而不判平台，
    在非 Windows 下会漏出 134217728 —— 这是行为漂移（对拍实测报出 8 处差异）。
    """
    return getattr(subprocess, 'CREATE_NO_WINDOW', 0) if is_windows() else 0


def cap(timeout: float = 15, *, oem: bool = True) -> dict[str, Any]:
    """`subprocess.run` 的公共 kwargs：无窗口 + 捕获输出 + 超时 + OEM 解码。

    迁移自 `_cap()`（L112-124），逐项对齐。

    参数
    ----
    timeout   : 超时秒数
    oem       : True → 按 OEM 代码页解码（sc/nssm/netstat/tasklist/wmic 用）。
                False → UTF-8 text 模式（taskkill 等自身无输出的命令用）。

    为什么 oem=False 时用 text 而非 encoding：
        与旧实现保持一致。旧代码在非 Windows / oem=False 时给的是
        `text=True, errors='replace'`，不改动以免引入行为差异。
    """
    kw: dict[str, Any] = {
        'creationflags': no_window_flag(),
        'capture_output': True,
        'timeout': timeout,
    }
    if oem and is_windows():
        kw.update(encoding='oem', errors='replace')
    else:
        # errors='replace' 必给：见模块文档第 3 条
        kw.update(text=True, errors='replace')
    return kw


def run_capture(
    argv: Sequence[str],
    *,
    timeout: float = 15,
    oem: bool = True,
    executable: str | None = None,
    runner: Runner | None = None,
) -> tuple[int, str, str]:
    """执行命令并返回 `(returncode, stdout, stderr)` 的规范化三元组。

    与旧代码的差别：旧代码各处零散地写
        `r = subprocess.run(...); out = (r.stdout or '') + (r.stderr or '')`
    —— 「拼接 stdout+stderr」这个动作在 `_svc_state`、`_service_one` 各处重复。
    本函数统一返回**分离**的两路输出，由调用方决定怎么合
    （`sc query` 的 1060 错误信息在 stderr，状态在 stdout，混在一起会让
    `domain.service_state.parse_sc_query_output` 的判定变脆）。

    异常语义（与旧实现一致 —— 调用方负责兜住）：
        超时 → 抛 subprocess.TimeoutExpired
        其它 → 原样抛
    旧实现在 `_svc_state` 里 `except Exception: return '未知'`，
    在 `_service_one` 里区分 TimeoutExpired 与 Exception 给出不同文案 ——
    这两种不同的失败语义保留在各自调用方，本函数不替它们做决定。
    """
    run = runner or subprocess.run
    kwargs = cap(timeout, oem=oem)
    if executable:
        kwargs['executable'] = executable
    r = run(list(argv), **kwargs)
    return (
        int(getattr(r, 'returncode', -1)),
        getattr(r, 'stdout', None) or '',
        getattr(r, 'stderr', None) or '',
    )


def run_quiet(
    argv: Sequence[str],
    *,
    timeout: float = 10,
    oem: bool = False,
    executable: str | None = None,
    runner: Runner | None = None,
) -> bool:
    """执行命令、**吞掉一切异常**，只返回是否成功（rc == 0）。

    迁移自 `_taskkill()` 里的 `with contextlib.suppress(Exception): subprocess.run(...)`
    —— 终止类命令是「尽力而为」语义：进程可能已经自己退出了，
    此时命令报错属正常，不该中断调用方流程。

    ★ 注意这个「吞异常」是被审查认可的**有意为之**，不是 D5 的静默失败：
      它不掩盖任何需要决策的信息 —— 调用方随后会**重新查询**目标状态来确认结果
      （见 `kill_port_sync` 的三轮重试与 `service_nssm` 的 wait 确认）。
      静默失败的定义是「失败了但调用方以为成功了」，这里是「失败了，
      但成功与否由后续独立探测判定」。

    返回值只在测试与诊断中有意义，业务路径应依赖后续状态确认。
    """
    run = runner or subprocess.run
    try:
        kwargs = cap(timeout, oem=oem)
        if executable:
            kwargs['executable'] = executable
        r = run(list(argv), **kwargs)
        return int(getattr(r, 'returncode', -1)) == 0
    except Exception:
        return False


def python_executable() -> str:
    """当前解释器路径（供 spawn 子进程用）。"""
    return sys.executable
