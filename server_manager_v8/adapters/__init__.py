"""Adapter 层 —— 所有 I/O 与平台细节。

═══════════════════════════════════════════════════════════════════
本层职责
═══════════════════════════════════════════════════════════════════

  · 封装 `subprocess` / `psutil` / `urllib` / 文件系统 / Win32 调用
  · 实现 Domain 层定义的 Protocol 端口
  · 把外部世界的原始输出（回显文本、退出码、进程列表）**原样**取回来

**禁止**：承载业务判定逻辑。
  「这个服务算未安装还是未知」「这个端口该不该杀」「这次等待算不算超时」
  全部是领域层的职责。适配器写判定会导致同一规则在两处漂移 ——
  v5.36 与 v5.39 两次互杀事故正是「sc 输出的解析规则散落在调用点」造成的。

  唯一例外是那些**本身就是平台知识**的规则（如 `taskkill` 的参数顺序、
  `netstat` 的列布局），它们放在这里是因为领域层不该知道 Windows 命令行语法。

═══════════════════════════════════════════════════════════════════
依赖方向
═══════════════════════════════════════════════════════════════════

    L4 Presentation → L3 Application → L2 Domain ← L1 Adapter

本层（L1）**只能依赖 L2 Domain**，禁止 import L3 / L4。
它通过实现 Domain 的 Protocol 来「被依赖倒置」——
即 Domain 定义接口、Adapter 提供实现、Application 负责装配注入。

═══════════════════════════════════════════════════════════════════
模块导览
═══════════════════════════════════════════════════════════════════

    _proc          子进程调用公共约定（无窗口 / OEM 解码 / 超时）
    service_nssm   Windows 服务：sc query / queryex / nssm 控制 / AppExit guard
    process_win    进程终止、端口占用、残留扫描
    health_http    HTTP 健康探针（直连不走代理）
    clock          真实时间与睡眠（domain.readiness 的注入实现）
    storage_json   配置读写 + schema v1→v2 迁移 + 原子写 + 备份
    audit_jsonl    审计日志：append-only + sha256 hash 链
    metrics_psutil 系统指标采样（psutil 缺失降级返回 None）
    notify_win     托盘气泡 / 弹窗 / 声音（永不抛出）
    port_impls     ★ Port 实现：把上面这些自由函数聚合成符合 Protocol 的对象

═══════════════════════════════════════════════════════════════════
两级 API 的分工（P3 起）
═══════════════════════════════════════════════════════════════════

本层对外有两种用法，用途不同，**不要混用**：

  【自由函数】`query_state('erp-prod')` 等
      用途：适配层内部单元测试、对拍脚本、一次性脚本。
      特点：参数显式（runner/timeout 可注入），便于精确控制。

  【Port 对象】`NssmService().state('erp-prod')` 等（`port_impls` 模块）
      用途：**Application 层（L3）唯一应该使用的形态**。
      特点：符合 domain Protocol，可被 Fake 替换，使 L3 能在无 Windows
            环境的 CI 里测试。

L3 依赖 `domain.ports.ServicePort` 这个**类型**，由 container 在装配时
塞入 `NssmService` 实例。L3 永远不 import 本模块（由门禁强制）。

═══════════════════════════════════════════════════════════════════
可测性约定
═══════════════════════════════════════════════════════════════════

本层虽然允许 I/O，但**所有外部调用都支持注入 runner / opener / 时钟**：

    from server_manager_v8.adapters.service_nssm import query_state

    fake = lambda argv, **kw: SimpleNamespace(returncode=0, stdout='STATE: 4 RUNNING', stderr='')
    q = query_state('erp-prod', runner=fake)

这样适配层的单测**不真的执行 `taskkill`、不真的等 60 秒**，
但能完整覆盖参数拼装、异常分类、结果对象构造等逻辑。
"""

from __future__ import annotations

__all__ = [
    # 时钟
    'SystemClock',
    'monotonic',
    'perf_counter',
    'sleep',
    # 子进程公共约定
    'is_windows',
    'run_capture',
    'run_quiet',
    # 服务
    'ServiceQuery',
    'VerbResult',
    'control_many',
    'detect_installed',
    'find_nssm',
    'has_nssm',
    'query_pid',
    'query_state',
    'request_stop',
    'run_verb',
    'set_restart_guard',
    # 进程 / 端口
    'KillOutcome',
    'PortOccupierInfo',
    'ResidualScan',
    'kill_many',
    'kill_pid',
    'kill_port_sync',
    'kill_tree',
    'port_occupiers',
    'port_pids',
    'resolve_process_name',
    'scan_residual',
    'taskkill_argv',
    # 探针
    'HealthSample',
    'build_direct_opener',
    'make_probe_fn',
    'probe',
    # 存储 / 审计
    'LoadResult',
    'backup',
    'config_path',
    'detect_version',
    'load',
    'load_and_migrate',
    'migrate',
    'save',
    'GENESIS_HASH',
    'JsonlAuditLog',
    'compute_hash',
    # 指标 / 通知
    'PsutilMetrics',
    'WinNotifier',
    'notify_via_webview',
    # ★ Port 实现（L3 唯一应使用的形态）
    'HttpHealth',
    'JsonStorage',
    'NssmService',
    'WinProcess',
]


def __getattr__(name: str):
    """惰性再导出（与 `domain/__init__.py` 同一约定）。

    导入 adapters 包本身不加载任何子模块 —— 避免 import 时就去碰
    subprocess / psutil / urllib（那会让「只想引用一个常量」的代码
    意外带上平台依赖，也让非 Windows 下的测试难以隔离）。

    注意：`health_http.probe` 与 `clock.sleep` 重名于模块级函数 `sleep`，
    因此这里对 `probe` 采用显式别名映射，其余按名字在子模块中查找。
    """
    if name not in __all__:
        raise AttributeError(f'module {__name__!r} has no attribute {name!r}')

    # 〔显式映射〕名字 → (子模块, 子模块内属性名)
    explicit: dict[str, tuple[str, str]] = {
        'probe': ('health_http', 'probe'),
        'sleep': ('clock', 'sleep'),
        'monotonic': ('clock', 'monotonic'),
        'perf_counter': ('clock', 'perf_counter'),
    }

    from . import (  # noqa: PLC0415
        _proc,
        audit_jsonl,
        clock,
        health_http,
        metrics_psutil,
        notify_win,
        port_impls,
        process_win,
        service_nssm,
        storage_json,
    )

    modules = (
        clock, health_http, process_win, service_nssm, _proc,
        storage_json, audit_jsonl, metrics_psutil, notify_win, port_impls,
    )

    if name in explicit:
        modname, attr = explicit[name]
        return getattr(globals()[modname], attr)

    for module in modules:
        if hasattr(module, name):
            return getattr(module, name)

    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')


def __dir__() -> list[str]:
    return sorted(set(__all__) | {'probe'})
