"""告警操作 UseCase — 确认 / 全部确认 / 静默 / 执行推荐修复。"""

from __future__ import annotations

from server_manager_v8.domain import (
    AlertCenter,
    OpResult,
    Silence,
    SilenceBook,
)

__all__ = ['AlertOpsUseCase']


class AlertOpsUseCase:
    """驱动 AlertCenter（纯内存）与 SilenceBook。持久化由 Adapter 层负责。"""

    def __init__(self, center: AlertCenter, silences: SilenceBook | None = None) -> None:
        self._center = center
        self._silences = silences or center.silences

    # ---- 确认（L0，全角色） ----

    def ack(self, key: str, by: str = '') -> OpResult:
        return self._center.ack(key, by=by)

    def ack_all(self, by: str = '') -> OpResult:
        count = self._center.ack_all(by=by)
        return OpResult.success(detail=f'已确认 {count} 条')

    # ---- 静默（L1，Operator+） ----

    def add_silence(
        self,
        service: str,
        duration_s: float,
        reason: str,
        family: str = '',
        created_by: str = '',
    ) -> OpResult:
        """创建静默单。duration_s 为时长（秒），start=now。"""
        import time

        now = time.time()
        silence = Silence(
            id=f'sil_{int(now)}',
            start_ts=now,
            end_ts=now + duration_s,
            service=service,
            family=family,
            reason=reason,
            created_by=created_by,
        )
        return self._silences.add(silence)

    def remove_silence(self, silence_id: str) -> OpResult:
        return self._silences.remove(silence_id)

    def active_silences(self) -> tuple:
        return self._silences.items

    # ---- 推荐修复（半自动自愈，SRE 可行动性） ----

    def suggested_action_for(self, key: str) -> str:
        alert = self._center.get(key)
        if alert is None:
            return ''
        return alert.suggested_action
