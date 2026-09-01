"""CLI 入口 — ``python -m server_manager_v8 <command>``。

P1–P2 阶段提供自检命令；P4 将扩展为完整业务 CLI
（start-dev / start-prod / switch / status），实现「UI 风险与业务风险解耦」。
"""

from __future__ import annotations

import argparse
import importlib
import pkgutil
import sys
from pathlib import Path

from ._guard import RULE_BOOK, Violation, check_package

__all__ = ['main']

_PKG_PATHS: list[str] = [str(Path(__file__).resolve().parent)]


def _cmd_selfcheck(_args: argparse.Namespace) -> int:
    """架构门禁 + 全模块导入冒烟 + Domain 不变式冒烟。"""
    failures = 0

    print('== 1/3 架构门禁（AST 静态检查）==')
    for rule, desc in RULE_BOOK:
        print(f'   {rule}: {desc}')
    violations: list[Violation] = check_package()
    if violations:
        failures += len(violations)
        for v in violations:
            print(f'   ✗ {v}')
        print(f'   {len(violations)} 处违规')
    else:
        print('   ✓ 全部通过')

    print('== 2/3 全模块导入冒烟 ==')

    bad = 0
    for mod in pkgutil.walk_packages(_PKG_PATHS, prefix='server_manager_v8.'):
        try:
            importlib.import_module(mod.name)
            print(f'   ✓ {mod.name}')
        except Exception as e:
            bad += 1
            failures += 1
            print(f'   ✗ {mod.name}: {type(e).__name__}: {e}')
    if not bad:
        print('   （全部模块可导入，杜绝 BUG-01 类死代码）')

    print('== 3/3 Domain 不变式冒烟 ==')
    failures += _domain_smoke()

    print()
    if failures:
        print(f'自检失败：{failures} 处')
        return 1
    print('自检全部通过')
    return 0


def _domain_smoke() -> int:
    """对核心 Domain 不变量做快速冒烟（完整覆盖见 tests/server_manager_v8）。"""
    from .domain import (
        AlertCenter,
        AlertRule,
        Inhibition,
        ModeAction,
        ModeMachine,
        RunMode,
        Severity,
        SilenceBook,
    )

    problems = 0

    def check(cond: bool, label: str) -> None:
        nonlocal problems
        print(f'   {"✓" if cond else "✗"} {label}')
        if not cond:
            problems += 1

    m = ModeMachine()
    m.begin(ModeAction.START_DEV)
    check(m.mode is RunMode.SWITCHING, 'start_dev 进入 SWITCHING')
    check(m.commit() is RunMode.DEV, 'commit 到达 DEV')
    check(m.can(ModeAction.START_PROD).ok, 'DEV→PROD 合法（互斥切换）')
    m.begin(ModeAction.START_PROD)
    m.rollback()
    check(m.mode is RunMode.DEV, 'rollback 回到 DEV')

    center = AlertCenter(
        evaluator=None,
        inhibition=Inhibition(chain_rules=(('pg_down', ('api_5xx',)),)),
        silences=SilenceBook(),
    )
    rule = AlertRule(id='api_health_fail', metric='health_fail', op='ge', threshold=3,
                     severity=Severity.P1, runbook='docs/runbook/api_down.md',
                     suggested_action='restart_api')
    check(rule.validate().ok, '规则校验通过（P1 带 runbook + action）')
    decision = center.ingest(rule.to_alert('api', 5, 1000.0), ts=1000.0)
    check(decision.raised_now and decision.notify, '告警入库并通知')
    check(center.ack('api_health_fail@api').ok, '确认告警')
    check(center.unconfirmed_count() == 0, '确认后角标清零')

    return problems


def _cmd_version(_args: argparse.Namespace) -> int:
    import server_manager_v8

    print(f'ERP 服务器管理器 v8 · server_manager_v8 {server_manager_v8.__version__}')
    print('架构：Presentation → Application → Domain ← Adapters')
    return 0


# ===================== 业务 CLI（P4：CLI 驱动全部业务能力） =====================

def _load_container() -> object:
    """装配生产容器（延迟 import，保持 CLI 启动快）。"""
    from .container import build_container

    return build_container()


def _print_result(result: object) -> int:
    ok = bool(result.ok)
    line = f'{"✓" if ok else "✗"} {result.reason or result.detail or "ok"}'
    print(line)
    return 0 if ok else 1


def _cmd_status(_args: argparse.Namespace) -> int:

    c = _load_container()
    mode = c.machine.mode.value
    print(f'运行模式: {mode}')
    if c.service is not None:
        for name in ('erp-prod', 'erp-arq'):
            state = c.service.state(name)
            pid = c.service.pid(name)
            print(f'  {name}: {state.value}' + (f' (PID {pid})' if pid else ''))
    redis = c.health.probe(__import__(
        'server_manager_v8.domain', fromlist=['HealthTarget'],
    ).HealthTarget(name='redis', kind='redis', port=6379))
    print(f'  redis(6379): {"运行中" if redis.ok else "未运行"}')
    snapshot = c.state.snapshot()
    for key, pid in snapshot.items():
        print(f'  开发进程 {key}: PID {pid}')
    unconfirmed = c.center.unconfirmed_count()
    if unconfirmed:
        print(f'未确认告警: {unconfirmed}')
    return 0


def _cmd_start_dev(args: argparse.Namespace) -> int:
    from .application.usecases import DevStartSpec

    c = _load_container()
    cfg = c.config.load() if c.config else {}
    spec = DevStartSpec(
        python_exe=cfg.get('paths', {}).get('python') or sys.executable,
        project_dir=cfg.get('paths', {}).get('project') or str(Path.cwd()),
        frontend_dir=str(Path(cfg.get('paths', {}).get('project') or Path.cwd()) / 'frontend-vite'),
        api_port=int(cfg.get('ports', {}).get('api', 5002)),
        web_port=int(cfg.get('ports', {}).get('web', 3000)),
        redis_port=int(cfg.get('ports', {}).get('redis', 6379)),
        redis_exe=cfg.get('paths', {}).get('redis_exe', ''),
    )
    return _print_result(c.start_dev.run(spec, trace_id='cli'))


def _cmd_start_prod(args: argparse.Namespace) -> int:
    from .application.usecases import ProdStartSpec

    c = _load_container()
    cfg = c.config.load() if c.config else {}
    spec = ProdStartSpec(api_port=int(cfg.get('ports', {}).get('api', 5002)))
    return _print_result(c.start_prod.run(spec, trace_id='cli'))


def _cmd_stop(_args: argparse.Namespace) -> int:
    c = _load_container()
    return _print_result(c.stop_all.run())


def _cmd_switch(args: argparse.Namespace) -> int:
    c = _load_container()
    return _print_result(c.switch.run(args.target))


def _cmd_kill_port(args: argparse.Namespace) -> int:
    c = _load_container()
    return _print_result(c.kill_port.run(args.port))


def _cmd_alerts(args: argparse.Namespace) -> int:
    c = _load_container()
    if args.op == 'list':
        alerts = c.center.alerts
        if not alerts:
            print('暂无告警')
            return 0
        for a in alerts:
            mark = '' if a.firing else '（已确认）'
            print(f'[{a.severity.value}] {a.title} · {a.service or "global"} · {a.key}{mark}')
        return 0
    if args.op == 'ack':
        return _print_result(c.alerts.ack(args.key or '', by='cli'))
    if args.op == 'ack-all':
        return _print_result(c.alerts.ack_all(by='cli'))
    print(f'未知操作 {args.op}')
    return 1


def _cmd_config(args: argparse.Namespace) -> int:
    c = _load_container()
    if args.op == 'show':
        import json

        data = c.config.load()
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0
    if args.op == 'migrate':
        return _print_result(c.config.migrate())
    print(f'未知操作 {args.op}')
    return 1


def _cmd_install(args: argparse.Namespace) -> int:
    from .application.usecases import InstallSpec

    c = _load_container()
    cfg = c.config.load() if c.config else {}
    spec = InstallSpec(
        python_exe=cfg.get('paths', {}).get('python') or sys.executable,
        project_dir=cfg.get('paths', {}).get('project') or str(Path.cwd()),
        api_port=int(cfg.get('ports', {}).get('api', 5002)),
    )
    return _print_result(c.install_services.run(spec, reason=args.reason or 'CLI 安装'))


def _cmd_uninstall(args: argparse.Namespace) -> int:
    c = _load_container()
    return _print_result(c.uninstall_services.run(reason=args.reason or 'CLI 卸载'))


def _cmd_gui(_args: argparse.Namespace) -> int:
    """启动 v8 桌面 GUI（pywebview 装壳）。"""
    from .presentation.webview_host import run_gui

    c = _load_container()
    return run_gui(c)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog='python -m server_manager_v8',
        description='ERP 服务器管理器 v8（四层架构重构版）',
    )
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('selfcheck', help='架构门禁 + 导入冒烟 + Domain 不变式自检')
    sub.add_parser('version', help='显示版本信息')
    sub.add_parser('gui', help='启动桌面 GUI（pywebview 装壳）')
    sub.add_parser('status', help='查看运行模式 / 服务状态 / Redis / 未确认告警')
    sub.add_parser('start-dev', help='启动开发模式（前后端 + Redis）')
    sub.add_parser('start-prod', help='启动生产模式（NSSM 服务）')
    sub.add_parser('stop', help='停止全部服务')
    p_switch = sub.add_parser('switch', help='切换模式：dev / prod / idle')
    p_switch.add_argument('target', choices=('dev', 'prod', 'idle'))
    p_kill = sub.add_parser('kill-port', help='清理端口占用（L2 高危）')
    p_kill.add_argument('port', type=int)
    p_alerts = sub.add_parser('alerts', help='告警操作：list / ack / ack-all')
    p_alerts.add_argument('op', choices=('list', 'ack', 'ack-all'))
    p_alerts.add_argument('key', nargs='?', default='')
    p_cfg = sub.add_parser('config', help='配置操作：show / migrate')
    p_cfg.add_argument('op', choices=('show', 'migrate'))
    p_inst = sub.add_parser('install-services', help='安装生产服务（L3 极高危）')
    p_inst.add_argument('--reason', default='', help='变更原因（L3 必填）')
    p_uninst = sub.add_parser('uninstall-services', help='卸载生产服务（L3 极高危）')
    p_uninst.add_argument('--reason', default='', help='变更原因（L3 必填）')

    args = parser.parse_args(argv)
    handlers = {
        'selfcheck': _cmd_selfcheck,
        'version': _cmd_version,
        'gui': _cmd_gui,
        'status': _cmd_status,
        'start-dev': _cmd_start_dev,
        'start-prod': _cmd_start_prod,
        'stop': _cmd_stop,
        'switch': _cmd_switch,
        'kill-port': _cmd_kill_port,
        'alerts': _cmd_alerts,
        'config': _cmd_config,
        'install-services': _cmd_install,
        'uninstall-services': _cmd_uninstall,
    }
    return handlers[args.command](args)


if __name__ == '__main__':
    sys.exit(main())
