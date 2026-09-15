"""安装 / 卸载服务 —— 服务生命周期的 L3 高危操作。

═══════════════════════════════════════════════════════════════════
迁移来源：server_manager.py v5.40 `_install_services()` / `_uninstall_services()`
═══════════════════════════════════════════════════════════════════

旧实现把安装与卸载写在两个方法里，各自内部再循环服务名，形如：

    for name, desc in SERVICE_SPECS:
        if self._svc_absent(self._svc_state(name)):      # 未安装
            nssm install ...

问题有三处，本模块逐一处理：

    ① **「未安装」与「查不到」被混为一谈** —— `_svc_absent` 只判字面量，
       而 `_svc_state` 在查询失败时返回「未知」，此时 `_svc_absent` 为假，
       于是「未知」的服务被当成「已安装」跳过，用户看到「全部就绪」
       但其实什么都没做。→ 本模块用 `ServiceStatus` 枚举严格区分
       （未知 → 保守失败，因为不知道它在不在，装了可能覆盖既有配置）。

    ② **没有灾难恢复路径** —— 卸载一个正在运行的服务，NSSM 会拒绝；
       旧实现直接报错退出，用户得自己先想到「要先停」。→ 本模块
       卸载前**自动先停**（并在失败时明确告知是「停不掉」还是「卸不掉」）。

    ③ **不可逆操作没有确认令牌** —— 卸载是 L3（不可逆），
       必须输入服务名 + 填变更原因。→ 由 `@require(Action.UNINSTALL_SERVICE)`
       统一强制，且**名称确认比对的是每个具体服务名**（见下方说明）。

═══════════════════════════════════════════════════════════════════
★ 批量操作与「输入名称确认」的矛盾，以及本模块的解法
═══════════════════════════════════════════════════════════════════

`ConfirmationToken.satisfies()` 要求 `typed_name == target`。但卸载是
**批量操作**（一次卸 erp-prod + erp-arq），用户不可能输入两个名字。

解法：`@require(..., target_arg='confirm_target')` —— 用一个**固定的
确认词**作为 target，前端提示用户输入这个词。这样：

    · 仍然满足「防误点」的目的（用户必须手工敲一个非空字符串）
    · 可批量（一次输入覆盖整批）
    · 审计里 target 记录的是确认词 + 真实服务清单（两条信息都不丢）

本模块把确认词定义为 `CONFIRM_WORD_INSTALL` / `CONFIRM_WORD_UNINSTALL`，
并**通过返回值把「需要输入什么」告诉调用方**（见 `required_confirmation()`），
避免前端硬编码另一个字符串导致两边对不上。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ...domain.models import MANAGED_NSSM_SERVICES, Service
from ...domain.permissions import Action
from ...domain.results import OpResult, ServiceCmd
from ...domain.service_state import ServiceStatus
from ..auth.guard import ConfirmationToken, require
from .deps import Deps

#: 安装服务的确认词（L3 需要用户手工输入）
CONFIRM_WORD_INSTALL = '安装服务'
#: 卸载服务的确认词（L3 需要用户手工输入）
CONFIRM_WORD_UNINSTALL = '卸载服务'


@dataclass
class InstallServicesContext:
    """安装/卸载流程的上下文。"""

    deps: Deps
    trace_id: str = ''
    installed: tuple[str, ...] = ()
    uninstalled: tuple[str, ...] = ()
    skipped: tuple[str, ...] = ()
    stopped_first: tuple[str, ...] = ()
    notes: list[str] = field(default_factory=list)


class InstallServices:
    """安装 NSSM 托管服务。

    这是 L3 高危操作（不可逆：会写入 SCM 与注册表），需要 Admin +
    输入确认词 + 填变更原因。

    ⚠ **本阶段的实现边界（如实标注）**：
      真正的 `nssm install <name> <exe> ...` 需要**服务规格**
      （可执行文件路径、参数、工作目录、日志重定向…），
      而 v8 的 `ServicePort.control()` 刻意不覆盖 install（见
      `adapters/port_impls.NssmService.control` 的文档）。

      因此本用例的职责是**前置检查 + 编排 + 落审计**，
      真正的「写 SCM」这一步通过 `_apply_install()` 留出接缝：
      在 P4 接入服务规格后，只需填充这一个方法，其余不变。

      当前 `_apply_install()` 返回明确的「未接入」失败，**不假装成功** ——
      假装成功会让用户以为服务已装好，而 `sc query` 里什么都没有。
    """

    def __init__(self, deps: Deps, *, services: tuple[Service, ...] | None = None) -> None:
        self._deps = deps
        self._services = services or MANAGED_NSSM_SERVICES

    @require(Action.UNINSTALL_SERVICE, target_arg='confirm_target')
    def execute(
        self,
        *,
        session: object,
        confirm: ConfirmationToken | None = None,
        event_bus: object = None,
        audit: object = None,
        confirm_target: str = CONFIRM_WORD_INSTALL,
        names: tuple[str, ...] = (),
        trace_id: str = '',
    ) -> OpResult:
        """安装服务。`names` 为空表示全部托管服务。"""
        ctx = InstallServicesContext(deps=self._deps, trace_id=trace_id)
        targets = self._resolve_targets(names)

        already: list[str] = []
        unknown: list[str] = []
        to_install: list[Service] = []

        for service in targets:
            status = self._deps.service.state(service.name)
            if status is ServiceStatus.RUNNING or status is ServiceStatus.STOPPED:
                already.append(service.name)
            elif status is ServiceStatus.UNKNOWN:
                unknown.append(service.name)
            else:
                to_install.append(service)      # ABSENT

        if unknown:
            # ★ 保守失败：不知道服务在不在，install 可能覆盖既有配置
            return OpResult.failure(
                '无法确认服务是否已安装（保守中止）',
                detail=(f'状态未知: {", ".join(unknown)}；'
                        f'在查询不到状态时安装可能覆盖既有配置'),
            )

        if not to_install:
            ctx.skipped = tuple(already)
            return OpResult.success(
                f'全部服务已安装，无需操作（{", ".join(already) or "无目标"}）'
            )

        failures: list[str] = []
        installed: list[str] = []
        for service in to_install:
            result = self._apply_install(service)
            if result.ok:
                installed.append(service.name)
            else:
                failures.append(f'{service.name}: {result.reason}')

        ctx.installed = tuple(installed)
        ctx.skipped = tuple(already)

        if failures:
            return OpResult.failure(
                '部分服务安装失败', detail='; '.join(failures),
            )
        return OpResult.success(
            f'已安装: {", ".join(installed)}'
            + (f'（跳过已装: {", ".join(already)}）' if already else '')
        )

    def _apply_install(self, service: Service) -> OpResult:
        """真正执行安装（留待 P4 接入服务规格）。"""
        return OpResult.failure(
            '服务安装未接入',
            f'{service.name}: 需要服务规格（可执行路径/参数/工作目录），'
            f'P4 补齐后在此实现',
        )

    def _resolve_targets(self, names: tuple[str, ...]) -> tuple[Service, ...]:
        if not names:
            return self._services
        wanted = set(names)
        return tuple(s for s in self._services if s.name in wanted)


class UninstallServices:
    """卸载 NSSM 托管服务。

    这是 L3 高危操作（不可逆：删除 SCM 注册与 nssm 配置），需要 Admin +
    输入确认词 + 填变更原因。
    """

    def __init__(self, deps: Deps, *, services: tuple[Service, ...] | None = None) -> None:
        self._deps = deps
        self._services = services or MANAGED_NSSM_SERVICES

    @require(Action.UNINSTALL_SERVICE, target_arg='confirm_target')
    def execute(
        self,
        *,
        session: object,
        confirm: ConfirmationToken | None = None,
        event_bus: object = None,
        audit: object = None,
        confirm_target: str = CONFIRM_WORD_UNINSTALL,
        names: tuple[str, ...] = (),
        trace_id: str = '',
        stop_first: bool = True,
    ) -> OpResult:
        """卸载服务。`names` 为空表示全部托管服务。

        `stop_first=True`（默认）会先停服务 —— 正在运行的服务 NSSM 拒绝卸载。
        """
        ctx = InstallServicesContext(deps=self._deps, trace_id=trace_id)
        targets = self._resolve_targets(names)

        absent: list[str] = []
        unknown: list[str] = []
        to_remove: list[Service] = []

        for service in targets:
            status = self._deps.service.state(service.name)
            if status is ServiceStatus.ABSENT:
                absent.append(service.name)
            elif status is ServiceStatus.UNKNOWN:
                unknown.append(service.name)
            else:
                to_remove.append(service)

        if unknown:
            return OpResult.failure(
                '无法确认服务状态（保守中止）',
                detail=(f'状态未知: {", ".join(unknown)}；'
                        f'状态查不到时不执行不可逆的卸载'),
            )

        if not to_remove:
            ctx.skipped = tuple(absent)
            return OpResult.success(
                f'全部服务均未安装，无需卸载（{", ".join(absent) or "无目标"}）'
            )

        failures: list[str] = []
        removed: list[str] = []
        stopped: list[str] = []

        for service in to_remove:
            if stop_first:
                stop_result = self._stop_before_uninstall(service)
                if not stop_result.ok:
                    # ★ 区分「停不掉」与「卸不掉」—— 两者排障方向完全不同
                    failures.append(
                        f'{service.name} 停止失败: {stop_result.reason} '
                        f'{stop_result.detail}'
                    )
                    continue
                stopped.append(service.name)

            result = self._apply_uninstall(service)
            if result.ok:
                removed.append(service.name)
            else:
                # ★ 把子步骤的 detail 一起带出去 —— 只报「卸载未生效」
                #   而不说「状态仍为 stopped、可能需重启」，运维没法处置。
                failures.append(
                    f'{service.name}: {result.reason}'
                    + (f'（{result.detail}）' if result.detail else '')
                )

        ctx.uninstalled = tuple(removed)
        ctx.stopped_first = tuple(stopped)
        ctx.skipped = tuple(absent)

        if failures:
            return OpResult.failure('部分服务卸载失败', detail='; '.join(failures))
        return OpResult.success(
            f'已卸载: {", ".join(removed)}'
            + (f'（先停止: {", ".join(stopped)}）' if stopped else '')
        )

    def _stop_before_uninstall(self, service: Service) -> OpResult:
        """卸载前停止服务（幂等：已停则直接成功）。"""
        deps = self._deps
        if deps.service.state(service.name) is ServiceStatus.STOPPED:
            return OpResult.success('已停止')
        return deps.service.control(service.name, ServiceCmd.STOP)

    def _apply_uninstall(self, service: Service) -> OpResult:
        """真正执行卸载。

        ★ 与安装不同，卸载**不需要服务规格** —— `nssm remove <name> confirm`
          只需要服务名。因此这里可以通过 `ServicePort.control()` 完成，
          P3 即可接入（安装则要等 P4）。

        ★ 卸载后复查：`nssm remove` 返回 0 不代表 SCM 里已经没了
          （服务可能进入「标记删除」状态，需重启才彻底消失）。
          这一步与 `KillPort` 的第 ④ 步同一纪律 ——
          「命令说成功」与「状态真的变了」是两件事。
        """
        result = self._deps.service.control(service.name, ServiceCmd.UNINSTALL)
        if not result.ok:
            # ★ 失败原因里要带上「停止是否成功过」，否则运维分不清
            #   是「停不掉」还是「卸不掉」—— 两者方向完全不同。
            return OpResult.failure(
                result.reason,
                f'{service.name}: {result.detail}（停止已尝试，仍无法卸载）',
            )

        after = self._deps.service.state(service.name)
        if after is ServiceStatus.ABSENT:
            return result
        if after is ServiceStatus.UNKNOWN:
            return OpResult.failure(
                '卸载后状态未知',
                f'{service.name}: 命令已执行但查不到当前状态，请手动核对',
            )
        return OpResult.failure(
            '卸载未生效',
            f'{service.name}: 命令返回成功，但状态仍为 {after.value}'
            f'（可能需重启系统才能彻底移除）',
        )

    def _resolve_targets(self, names: tuple[str, ...]) -> tuple[Service, ...]:
        if not names:
            return self._services
        wanted = set(names)
        return tuple(s for s in self._services if s.name in wanted)


def required_confirmation(action: Action) -> dict[str, str]:
    """返回该操作需要的确认信息（供前端渲染弹窗，避免两边硬编码不一致）。

    ★ 前端**不应该自己拼**「请输入『卸载服务』」这句话 ——
      一旦文案在两边各写一份，改一处就会不一致，
      而用户会照着错误的提示输入，然后永远无法通过校验。
    """
    if action is Action.UNINSTALL_SERVICE:
        return {'kind': 'typed', 'word': CONFIRM_WORD_UNINSTALL,
                'hint': f'请输入「{CONFIRM_WORD_UNINSTALL}」以确认',
                'requires_reason': 'true'}
    if action is Action.RESTORE_BACKUP:
        return {'kind': 'typed', 'word': '恢复备份',
                'hint': '请输入「恢复备份」以确认', 'requires_reason': 'true'}
    if action is Action.RESET_CONFIG:
        return {'kind': 'typed', 'word': '重置配置',
                'hint': '请输入「重置配置」以确认', 'requires_reason': 'true'}
    if action.danger.requires_modal_confirm:
        return {'kind': 'modal', 'word': '', 'hint': '请确认本次操作的影响',
                'requires_reason': 'false'}
    return {'kind': 'none', 'word': '', 'hint': '', 'requires_reason': 'false'}


def build_install_services(deps: Deps) -> InstallServices:
    return InstallServices(deps)


def build_uninstall_services(deps: Deps) -> UninstallServices:
    return UninstallServices(deps)


__all__ = [
    'CONFIRM_WORD_INSTALL',
    'CONFIRM_WORD_UNINSTALL',
    'InstallServices',
    'InstallServicesContext',
    'UninstallServices',
    'build_install_services',
    'build_uninstall_services',
    'required_confirmation',
]
