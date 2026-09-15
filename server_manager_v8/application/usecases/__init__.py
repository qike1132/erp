"""用例层 —— L3 的业务编排。

═══════════════════════════════════════════════════════════════════
一组用例 = 一组「用户可以做的事」
═══════════════════════════════════════════════════════════════════

本包下的每个模块实现一个**完整的用户动作**：

    stop_all            停止全部（服务 + Redis + 残留进程）
    start_dev           启动开发模式
    start_prod          启动生产模式
    switch_mode         切换运行模式（探测真实模式 + 幂等 + 委派）
    kill_port           释放被占用的端口（含杀前留痕与杀后复查）
    install_services    安装服务（L3，需输入确认词）
    uninstall_services  卸载服务（L3，自动先停 + 卸后复查）
    log_ops             审计查询与 hash 链校验
    alert_ops           告警确认 / 静默 / 列表
    backup_ops          配置备份（L2）与恢复（L3，恢复前强制快照）
    config_ops          配置读取、校验、端口/路径/数值写入、重置

═══════════════════════════════════════════════════════════════════
★ 用例层的三条纪律（由门禁强制）
═══════════════════════════════════════════════════════════════════

① **绝不 import `server_manager_v8.adapters`**
   用例只认 `domain.ports` 里的 Protocol。具体实现由 `container.py`
   在装配时注入。一旦 L3 直接依赖 L1，用例就无法被 Fake 替换，
   CI（没有 Windows / 没有真实服务）里也跑不起来。

② **绝不 import 任何 I/O 库**
   subprocess / psutil / socket / urllib / ctypes / pathlib 一律禁止。
   需要 I/O 就定义 Port 方法。`time` 也禁止（时间从 `deps.clock` 取），
   唯一例外是 `pipeline.py` 里给步骤耗时兜底打点。

③ **绝不复制领域判定**
   「什么状态算停止」「哪些服务要挂守卫」「L2 要不要弹窗」这类判断
   全部在 `domain.*` 里，用例只负责**编排顺序**。
   复制一份判定 = 将来改一处忘一处，两边行为漂移。

═══════════════════════════════════════════════════════════════════
导入策略：惰性再导出
═══════════════════════════════════════════════════════════════════

本模块用 `__getattr__` 惰性导入各用例，而不是在顶层 import 所有模块。
理由：用例之间存在交叉引用（`start_dev` 复用 `stop_all` 的流水线、
`switch_mode` 委派给 `start_dev`/`start_prod`、`backup_ops` 复用
`install_services` 的确认词语义），顶层全量导入在将来出现循环引用时
会很难排查。惰性导入让「导入一个用例」与「导入整个包」解耦。

═══════════════════════════════════════════════════════════════════
确认词（L3 需要用户手工输入）
═══════════════════════════════════════════════════════════════════

各用例的确认词**不在本模块 export 的中文常量里硬编码**，
而是由 `install_services.required_confirmation(action)` 统一提供 ——
前端应当调它来渲染提示，而不是自己拼字符串：

    · 安装服务 → `CONFIRM_WORD_INSTALL`   ('安装服务')
    · 卸载服务 → `CONFIRM_WORD_UNINSTALL` ('卸载服务')
    · 恢复备份 → `CONFIRM_WORD_RESTORE`   ('恢复备份')
    · 重置配置 → `CONFIRM_WORD_RESET`     ('重置配置')

一旦文案在前后端各写一份，改一处就会不一致，而用户会照着错误的
提示输入，然后永远无法通过校验。
"""

from __future__ import annotations

from typing import Any

__all__ = [
    # ── 依赖包 ──
    'Deps',
    'make_deps',
    # ── 模式与生命周期 ──
    'StartDev',
    'StartProd',
    'StopAll',
    'SwitchMode',
    'STARTUP_STEPS',
    'PROD_START_STEPS',
    'REDIS_SERVICES',
    'detect_mode',
    'ModeSnapshot',
    # ── 服务安装/卸载 ──
    'InstallServices',
    'UninstallServices',
    'CONFIRM_WORD_INSTALL',
    'CONFIRM_WORD_UNINSTALL',
    'required_confirmation',
    # ── 端口 ──
    'KillPort',
    'PortOccupierInfo',
    'default_ports',
    # ── 可观测性 ──
    'LogOps',
    'AlertOps',
    'Alert',
    'DEFAULT_SILENCE_S',
    'MAX_SILENCE_S',
    # ── 配置与备份 ──
    'BackupOps',
    'ConfigOps',
    'CONFIRM_WORD_RESTORE',
    'CONFIRM_WORD_RESET',
    'PRERESTORE_SUFFIX',
    'PORT_KEYS',
    'PATH_KEYS',
    'EDITABLE_KEYS',
    # ── 工厂 ──
    'build_alert_ops',
    'build_backup_ops',
    'build_config_ops',
    'build_install_services',
    'build_kill_port',
    'build_log_ops',
    'build_start_dev',
    'build_start_prod',
    'build_stop_all',
    'build_switch_mode',
    'build_uninstall_services',
]

#: 子模块名 → 该模块导出的名字
_EXPORTS: dict[str, tuple[str, ...]] = {
    'deps': ('Deps', 'make_deps'),

    'stop_all': ('StopAll', 'StopAllContext', 'REDIS_SERVICES', 'build_stop_all'),
    'start_dev': ('StartDev', 'StartDevContext', 'STARTUP_STEPS', 'build_start_dev'),
    'start_prod': ('StartProd', 'StartProdContext', 'PROD_START_STEPS',
                   'build_start_prod'),
    'switch_mode': ('SwitchMode', 'SwitchModeContext', 'ModeSnapshot',
                    'detect_mode', 'build_switch_mode'),

    'install_services': ('InstallServices', 'InstallServicesContext',
                         'UninstallServices', 'CONFIRM_WORD_INSTALL',
                         'CONFIRM_WORD_UNINSTALL', 'required_confirmation',
                         'build_install_services', 'build_uninstall_services'),

    'kill_port': ('KillPort', 'KillPortContext', 'PortOccupierInfo',
                  'RECHECK_ATTEMPTS', 'RECHECK_INTERVAL_S',
                  'build_kill_port', 'default_ports'),

    'log_ops': ('LogOps', 'AuditQueryContext', 'DEFAULT_QUERY_LIMIT',
                'MAX_QUERY_LIMIT', 'build_log_ops'),
    'alert_ops': ('AlertOps', 'Alert', 'AlertOpsContext', 'DEFAULT_SILENCE_S',
                  'MAX_SILENCE_S', 'build_alert_ops'),

    'backup_ops': ('BackupOps', 'BackupContext', 'CONFIRM_WORD_RESTORE',
                   'PRERESTORE_SUFFIX', 'build_backup_ops'),
    'config_ops': ('ConfigOps', 'ConfigLoadResult', 'CONFIRM_WORD_RESET',
                   'PORT_KEYS', 'PATH_KEYS', 'NUMERIC_KEYS', 'LIST_KEYS',
                   'EDITABLE_KEYS', 'build_config_ops'),
}

#: 名字 → 子模块（反向索引，供 `__getattr__` 用）
_NAME_TO_MODULE: dict[str, str] = {
    name: module
    for module, names in _EXPORTS.items()
    for name in names
}


def __getattr__(name: str) -> Any:
    """惰性解析 `server_manager_v8.application.usecases.<Name>`。"""
    module_name = _NAME_TO_MODULE.get(name)
    if module_name is None:
        raise AttributeError(
            f'module {__name__!r} has no attribute {name!r}'
        )
    from importlib import import_module  # noqa: PLC0415

    module = import_module(f'.{module_name}', __name__)
    return getattr(module, name)


def __dir__() -> list[str]:
    return sorted(__all__)
