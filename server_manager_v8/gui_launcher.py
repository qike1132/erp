"""GUI 启动器 —— v8 的程序入口（PyInstaller 的 Analysis 入口脚本）。

═══════════════════════════════════════════════════════════════════
启动顺序为什么是这样
═══════════════════════════════════════════════════════════════════

    ① 单实例守卫   —— 最先，避免两个实例同时操作服务
    ② 日志         —— 其次，后面每一步都要能留下线索
    ③ 环境探测     —— 决定「哪些能力可用」，装配时要据此降级
    ④ 装配容器     —— 把 Protocol 接上真实实现
    ⑤ 降级提示     —— 有功能不可用就明确告诉用户
    ⑥ 启动窗口     —— 最后，前面任何一步失败都不该弹出空窗口

★ 为什么单实例要在最前：
  若先装配再查单实例，第二个实例已经做了「探测环境」这类 I/O，
  然后才退出 —— 浪费且可能在审计里留下两条启动记录。

★ 为什么窗口在最后：
  前面失败时（如配置文件损坏），弹一个窗口再崩，
  用户看到的是「闪一下就没了」，比命令行报错更难排查。

═══════════════════════════════════════════════════════════════════
★ 关于「启动即崩溃」的处理原则
═══════════════════════════════════════════════════════════════════

启动期异常一律**记日志 + 弹窗**，绝不静默退出。
静默退出的表现是「双击没反应」，用户只能来问我们。

弹窗本身也可能失败（无 GUI 环境 / 服务未启动），
所以 `ShowError` 有 try 保护，最差情况退化为打印到 stderr。
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Any

#: 应用名（用于日志与互斥体命名）
APP_NAME = 'ERP 服务器管理器 v8'

log = logging.getLogger('server_manager_v8')


def setup_logging(*, verbose: bool = False) -> Path:
    """配置日志，返回日志文件路径。

    ★ 日志**必须**落盘：GUI 程序没有控制台，崩溃后 stdout 就没了。
      用户报障时我们唯一能要到的就是日志文件。
    """
    level = logging.DEBUG if verbose else logging.INFO

    log_dir = _log_dir()
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / 'server_manager_v8.log'
        handler: logging.Handler = logging.FileHandler(
            log_path, encoding='utf-8', mode='a',
        )
    except OSError as exc:
        # 日志目录不可写（如装在 Program Files 且无权限）→ 退化为 stderr
        print(f'[warn] 无法写日志文件（{exc}），改用 stderr', file=sys.stderr)
        handler = logging.StreamHandler(sys.stderr)
        log_path = Path('<stderr>')

    handler.setFormatter(logging.Formatter(
        '%(asctime)s %(levelname)-7s %(name)s: %(message)s',
        datefmt='%m-%d %H:%M:%S',
    ))
    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(handler)

    # Windows 下也留一份控制台输出（--console 模式调试用）
    if verbose:
        root.addHandler(logging.StreamHandler(sys.stderr))

    return log_path


def _log_dir() -> Path:
    """日志目录：与可执行文件同级的 logs/。

    ★ 不用 CWD：从桌面快捷方式启动时 CWD 可能是 system32，
      写日志会失败（无权限）或写到莫名其妙的地方。
    """
    if getattr(sys, 'frozen', False):
        base = Path(sys.executable).resolve().parent
    else:
        base = Path(__file__).resolve().parent.parent
    return base / 'logs'


def _alert(title: str, message: str) -> None:
    """弹一个错误对话框（失败则退化为 stderr）。

    ★ 用 ctypes MessageBox 而不是 tkinter：
      spec 已把 tkinter 排除（v8 用 pywebview），依赖它会导致打包失败。
    """
    try:
        if sys.platform == 'win32':
            import ctypes  # noqa: PLC0415

            ctypes.windll.user32.MessageBoxW(0, message, title, 0x10)  # MB_ICONERROR
            return
    except Exception:  # noqa: BLE001
        pass
    print(f'[{title}] {message}', file=sys.stderr)


def _confirm_quit_with_services(running: list[str]) -> bool:
    """退出前确认：还有服务在跑。

    ★ 只在「有服务在跑」时问。若什么都关了还问，用户会养成
      无脑点「是」的习惯 —— 等真有服务在跑时这个确认就失效了。
    """
    if not running:
        return True
    try:
        if sys.platform == 'win32':
            import ctypes  # noqa: PLC0415

            names = '、'.join(running[:5])
            if len(running) > 5:
                names += f' 等 {len(running)} 个'
            msg = (
                f'以下服务仍在运行：\n\n  {names}\n\n'
                f'关闭管理器不会停止这些服务，它们会继续在后台运行。\n'
                f'确定要退出吗？'
            )
            #: MB_YESNO | MB_ICONWARNING | MB_DEFBUTTON2（默认选中「否」）
            ret = ctypes.windll.user32.MessageBoxW(0, msg, APP_NAME, 0x24 | 0x100)
            return ret == 6   # IDYES
    except Exception:  # noqa: BLE001
        pass
    return True


def main(argv: list[str] | None = None) -> int:
    """程序入口。返回退出码。"""
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument('--verbose', '-v', action='store_true', help='输出调试日志')
    parser.add_argument('--no-guard', action='store_true',
                        help='跳过单实例检查（仅供调试，勿用于生产）')
    parser.add_argument('--base-dir', default=None,
                        help='配置与日志目录（默认：exe 同级）')
    args = parser.parse_args(argv)

    log_path = setup_logging(verbose=args.verbose)
    log.info('=' * 60)
    log.info('%s 启动', APP_NAME)

    # ── ① 单实例守卫 ─────────────────────────────────────────
    from ._guard import AlreadyRunning, SingleInstanceGuard  # noqa: PLC0415

    guard = SingleInstanceGuard()
    if not args.no_guard:
        try:
            guard.require()
            log.info('单实例守卫：已获取（机制=%s）', guard.mechanism)
        except AlreadyRunning as exc:
            log.warning('已有实例在运行，退出')
            _alert(APP_NAME, str(exc))
            return 2
    else:
        log.warning('单实例检查已跳过（--no-guard）')

    try:
        # ── ③ 环境探测 + ④ 装配 ─────────────────────────────
        from .container import build_container, probe_environment  # noqa: PLC0415

        base = Path(args.base_dir) if args.base_dir else None
        env = probe_environment(base)
        log.info('环境探测：psutil=%s webview=%s config=%s',
                 env.has_psutil, env.has_webview, env.config_path)

        container = build_container(
            base_dir=base, env=env,
            default_role=_default_role(),
        )
        log.info('容器装配完成（降级项 %d 条）', len(container.degraded_notes()))

        # ── ⑤ 降级提示 ──────────────────────────────────────
        notes = container.degraded_notes()
        if notes:
            for note in notes:
                log.warning('功能降级：%s', note)
            # ★ 降级不阻塞启动：多数降级（如无 psutil）不影响核心功能。
            #   只在「服务管理不可用」这种根本级缺失时才提示用户。
            if not env.is_windows:
                _alert(APP_NAME,
                       '当前非 Windows 系统，服务管理功能不可用。\n\n'
                       + '\n'.join(notes))

        # ── ⑥ 启动窗口 ──────────────────────────────────────
        from .presentation.webview_host import WebviewHost  # noqa: PLC0415

        log.info('启动界面…')
        host = WebviewHost(container, title=APP_NAME, debug=args.verbose)
        host.run()

        log.info('窗口已关闭')

        # 退出前：若还有服务在跑，确认一次
        try:
            running = _running_services(container)
            if running and not _confirm_quit_with_services(running):
                log.info('用户取消退出')
                return 0
        except Exception as exc:  # noqa: BLE001
            # 查询失败不应阻止退出
            log.debug('退出前检查失败（忽略）: %s', exc)

        return 0

    except ImportError as exc:
        log.exception('依赖缺失')
        _alert(APP_NAME, f'缺少依赖组件：\n\n{exc}\n\n请重新安装本程序。')
        return 3

    except Exception as exc:  # noqa: BLE001
        log.exception('启动失败')
        _alert(APP_NAME,
               f'启动失败：\n\n{type(exc).__name__}: {exc}\n\n'
               f'详细日志见：\n{log_path}')
        return 1

    finally:
        guard.release()
        log.info('已退出')


def _default_role() -> Any:
    """默认角色：只读。

    ★ 启动即管理员是危险的默认值 —— 用户随手一点就能停生产服务。
      需要更高权限时走界面上的提权流程（有时效、有审计）。
    """
    from .domain.permissions import Role  # noqa: PLC0415

    return Role.VIEWER


def _running_services(container: Any) -> list[str]:
    """当前处于运行中的受管服务名（退出前确认用）。"""
    from .domain.service_state import ServiceStatus  # noqa: PLC0415

    out: list[str] = []
    for name in _managed_names():
        try:
            state = container.deps.service.state(name)
        except Exception:  # noqa: BLE001
            continue
        # ★ 只统计「明确在运行」的；UNKNOWN 不打扰用户
        if state is ServiceStatus.RUNNING:
            out.append(name)
    return out


def _managed_names() -> tuple[str, ...]:
    from .domain.models import MANAGED_NSSM_SERVICES  # noqa: PLC0415

    return tuple(s.name for s in MANAGED_NSSM_SERVICES)


if __name__ == '__main__':
    sys.exit(main())
