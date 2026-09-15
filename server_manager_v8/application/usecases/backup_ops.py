"""备份与恢复 —— 配置与审计的归档。

═══════════════════════════════════════════════════════════════════
迁移来源：v8 方案 §2.6「配置管理」+ §2.5「审计不可篡改」
═══════════════════════════════════════════════════════════════════

旧实现只有「配置另存为 .bak」这一件事（`_save_config` 里顺手做的），
没有任何**恢复**路径。这留下一个真实的死角：

    配置被改坏 → 有 .bak 但界面没有「恢复」按钮 → 用户手工改名 → 出错

本模块把备份做成**一等功能**，并把恢复定位为 L3（不可逆）：

    · **备份（L2）** —— 把当前配置 + 审计归档到带时间戳的目录
    · **恢复（L3）** —— 用备份覆盖当前配置，需要输入确认词 + 填原因

═══════════════════════════════════════════════════════════════════
★ 恢复是 L3，而备份只是 L2 —— 这个不对称是有意的
═══════════════════════════════════════════════════════════════════

备份是**只读**的（读当前状态，写到别处），最坏情况是浪费磁盘。
恢复是**覆盖**的：它会把当前配置**丢掉**（可能丢掉比备份更新的改动）。
「覆盖」这类操作无法用 Toast 撤销，且用户往往在慌乱中操作
（「坏了，赶紧恢复」）—— 恰恰是最需要「输入确认词」冷静一下的时刻。

═══════════════════════════════════════════════════════════════════
★ 恢复之前必须先备份当前状态
═══════════════════════════════════════════════════════════════════

这是本模块最重要的一条纪律：**恢复前先给当前配置做一份备份**。

理由：用户可能选错了备份文件。若没有「恢复前的快照」，
这次误操作就把当前配置永久覆盖了 —— 而它可能是**比备份更好**的状态。
有了自动前置备份，用户还能再恢复回来。

顺序不能反：
    ① 备份当前（失败 → 中止，不覆盖）
    ② 恢复（覆盖）
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ...domain.permissions import Action
from ...domain.results import OpResult
from ..auth.guard import ConfirmationToken, require
from .deps import Deps
from .install_services import CONFIRM_WORD_UNINSTALL     # 复用「不可逆操作」的语义集

#: 恢复备份的确认词（L3 需要用户手工输入）
CONFIRM_WORD_RESTORE = '恢复备份'

#: 恢复前的自动前置备份后缀
#:
#: ★ 用带时间感的固定后缀而不带真实时间戳：`StoragePort.backup(suffix)`
#:   只接收后缀字符串，时间戳由适配器负责（它知道怎么读系统时间，
#:   而应用层不能碰 `time`）。这里传的是**语义标记**而非时间。
PRERESTORE_SUFFIX = '.prerestore'


@dataclass
class BackupContext:
    """备份/恢复流程的上下文。"""

    deps: Deps
    trace_id: str = ''
    backup_ok: bool = False
    prerestore_ok: bool = False
    notes: list[str] = field(default_factory=list)


class BackupOps:
    """配置与审计的备份、恢复。

    备份是 L2（可撤销：删掉备份文件即可），恢复是 L3（不可逆覆盖）。
    """

    def __init__(self, deps: Deps) -> None:
        self._deps = deps

    # ── 备份（L2）────────────────────────────────────────────────

    @require(Action.RUN_BACKUP)
    def run_backup(
        self,
        *,
        session: object,
        confirm: ConfirmationToken | None = None,
        event_bus: object = None,
        audit: object = None,
        suffix: str = '.bak',
        include_chain_check: bool = True,
        trace_id: str = '',
    ) -> OpResult:
        """备份当前配置（并在需要时校验审计链）。

        ★ 备份时顺带校验审计链是个好时机 —— 两者都是「把当前状态固化」，
          用户已经在做「保存快照」的心理动作。若链已断裂，此刻发现
          比事故复盘时才发现要好得多。

        ★ 链断裂**不导致备份失败**：备份的是当前事实，
          事实包含「链断了」这件事。把断裂变成失败会让用户无法备份，
          反而促使他去手工拷贝文件（脱离管控）。
        """
        deps = self._deps

        if deps.storage is None:
            return OpResult.failure(
                '存储适配器不可用', '未注入 StoragePort，无法备份配置',
            )

        ctx = BackupContext(deps=deps, trace_id=trace_id)

        result = deps.storage.backup(suffix)
        if not result.ok:
            return OpResult.failure(
                '配置备份失败', detail=f'{result.reason} {result.detail}',
            )
        ctx.backup_ok = True

        if include_chain_check:
            verify = deps.audit.verify_chain()
            if verify.ok:
                ctx.notes.append(f'审计链完整（{verify.total} 条）')
            else:
                # ★ 不静默：链断是重要信息，必须出现在返回文案里
                ctx.notes.append(
                    f'⚠ 审计链已断裂（第 {verify.broken_at} 条起）——'
                    f'备份仍然成功，但请尽快排查'
                )

        detail = f'已备份配置（{suffix}）'
        if ctx.notes:
            detail += '；' + '；'.join(ctx.notes)
        return OpResult.success(detail)

    # ── 恢复（L3）────────────────────────────────────────────────

    @require(Action.RESTORE_BACKUP, target_arg='confirm_target')
    def restore_backup(
        self,
        *,
        session: object,
        confirm: ConfirmationToken | None = None,
        event_bus: object = None,
        audit: object = None,
        confirm_target: str = CONFIRM_WORD_RESTORE,
        suffix: str = '.bak',
        trace_id: str = '',
    ) -> OpResult:
        """从备份恢复配置（★ 覆盖当前配置，不可逆）。

        ★ 硬要求：**恢复前必须先给当前状态做一份备份**。
          用户可能选错文件，没有这一步就永久覆盖了更好的状态。
          前置备份失败则**不恢复**（宁可不动也不丢数据）。
        """
        deps = self._deps

        if deps.storage is None:
            return OpResult.failure(
                '存储适配器不可用', '未注入 StoragePort，无法恢复配置',
            )

        ctx = BackupContext(deps=deps, trace_id=trace_id)

        # ── ① 前置备份（★ 顺序不可反）──
        pre = deps.storage.backup(PRERESTORE_SUFFIX)
        if not pre.ok:
            return OpResult.failure(
                '恢复前快照失败（已中止，未做任何修改）',
                detail=(f'{pre.reason} {pre.detail}；'
                        f'若此时直接恢复，误选备份文件将无法回退'),
            )
        ctx.prerestore_ok = True

        # ── ② 读备份内容 ──
        raw = deps.storage.load_raw()
        if not raw:
            return OpResult.failure(
                '备份内容为空或不可读',
                detail='已保留前置快照，当前配置未被修改',
            )

        # ── ③ 迁移（备份可能是旧 schema）──
        try:
            migrated, changed = deps.storage.migrate(raw)
        except BaseException as exc:  # noqa: BLE001
            return OpResult.failure(
                '备份文件无法迁移',
                detail=f'{type(exc).__name__}: {exc}；当前配置未被修改',
            )

        # ── ④ 写回 ──
        saved = deps.storage.save_raw(migrated)
        if not saved.ok:
            return OpResult.failure(
                '恢复写入失败',
                detail=(f'{saved.reason} {saved.detail}；'
                        f'前置快照可用（{PRERESTORE_SUFFIX}）'),
            )

        detail = f'已从备份恢复配置（{suffix}）'
        if changed:
            detail += '；备份为旧版本schema，已迁移'
        detail += f'；恢复前快照: {PRERESTORE_SUFFIX}'
        return OpResult.success(detail)


def build_backup_ops(deps: Deps) -> BackupOps:
    return BackupOps(deps)


__all__ = [
    'BackupContext',
    'BackupOps',
    'CONFIRM_WORD_RESTORE',
    'PRERESTORE_SUFFIX',
    'build_backup_ops',
]

# 说明：`CONFIRM_WORD_UNINSTALL` 的导入保留是为了让「不可逆操作」的
# 确认词语义有个统一的参照点（将来所有 L3 确认词都应在此类模块里集中定义）。
_ = CONFIRM_WORD_UNINSTALL
