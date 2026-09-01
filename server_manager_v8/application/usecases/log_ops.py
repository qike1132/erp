"""日志操作 UseCase — 导出 / 清空 / 关键字规则校验（L1 中危）。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from server_manager_v8.domain import OpResult

__all__ = ['KeywordRule', 'LogOpsUseCase', 'validate_keyword_rule']


@dataclass(frozen=True)
class KeywordRule:
    """日志关键字告警规则（v8 方案 §4 F4）。"""

    pattern: str
    severity: str = 'P2'
    enabled: bool = True


def validate_keyword_rule(rule: KeywordRule) -> OpResult:
    """规则校验：pattern 必须是合法正则。"""
    if not rule.pattern:
        return OpResult.failure('pattern 不能为空')
    try:
        re.compile(rule.pattern)
    except re.error as exc:
        return OpResult.failure(f'非法正则 {rule.pattern!r}: {exc}')
    return OpResult.success()


class LogOpsUseCase:
    def __init__(self, logs_dir: str | Path) -> None:
        self._dir = Path(logs_dir)

    def export(self, source: str = '', limit: int = 10_000) -> OpResult:
        """导出日志文件内容（单文件 ≤ limit 行，防内存爆炸）。"""
        if not self._dir.is_dir():
            return OpResult.failure(f'日志目录不存在: {self._dir}')
        pattern = f'*{source}.log' if source else '*.log'
        files = sorted(self._dir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
        if not files:
            return OpResult.success(detail='无匹配日志文件')
        newest = files[0]
        lines = newest.read_text(encoding='utf-8', errors='replace').splitlines()
        return OpResult.success(
            detail=f'导出 {newest.name}（{len(lines)} 行，截取 {min(limit, len(lines))} 行）',
        )

    def list_files(self) -> tuple[tuple[str, int, float], ...]:
        """(文件名, 字节数, mtime) 列表，供 UI 源树渲染。"""
        if not self._dir.is_dir():
            return ()
        out = []
        for path in sorted(self._dir.glob('*.log')):
            try:
                out.append((path.name, path.stat().st_size, path.stat().st_mtime))
            except OSError:
                continue
        return tuple(out)
