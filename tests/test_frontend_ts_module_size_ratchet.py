"""前端 TS 模块体积棘轮（2026-11-16 上线前审计 B-3）。

背景：`scripts/check_ts_module_length.py` 与 `quality_gate` 的 `ts_module_length` 门禁
比较的是**超长文件的个数**，不是行数。于是 4 个已超 600 行的存量文件被一次性记进
`scripts/gate_baseline.json`（= 4）之后，任何一个都可以从 734 行长到 3000 行，
门禁依然绿 —— 棘轮只挡住了「新增第 5 个」，没挡住「既有那个无限膨胀」。

本测试给这 4 个文件各钉一条行数快照：**只许降，不许升**。
需要增长时先拆分；拆到 600 行以下后，把它从 `gate_baseline.json` 的计数里减掉
（基线只允许下调，见 docs/agents/code-review-standard.md §7），并从本表删除。
"""
from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_SRC = PROJECT_ROOT / 'frontend-vite' / 'src'
THRESHOLD = 600

#: 文件 → 审计日（2026-11-16）行数快照。只允许下调。
LINE_SNAPSHOTS: dict[str, int] = {
    'views/purchase/composables/perSkuRows.ts': 734,
    'views/purchase/composables/useSummaryModal.ts': 1141,
    'views/production/composables/useProductionEntry.ts': 957,
    'views/beile-order/composables/useBeileOrders.ts': 794,
}


def _line_count(rel: str) -> int:
    return len((FRONTEND_SRC / rel).read_text(encoding='utf-8').splitlines())


def test_ts_module_length_never_grows() -> None:
    """每个存量超长模块的行数不得超过审计日快照。"""
    grown = {
        rel: (_line_count(rel), cap)
        for rel, cap in LINE_SNAPSHOTS.items()
        if _line_count(rel) > cap
    }
    assert not grown, (
        '前端 TS 模块行数增长（棘轮只许降）：'
        + '; '.join(f'{rel} {cur} > {cap}' for rel, (cur, cap) in grown.items())
        + '。请拆分模块，而不是抬高本快照。'
    )


def test_snapshots_still_exceed_threshold() -> None:
    """快照表必须与门禁口径一致：拆到阈值以下的条目要从本表和基线里一起删掉。"""
    stale = [rel for rel in LINE_SNAPSHOTS if _line_count(rel) <= THRESHOLD]
    assert not stale, (
        f'以下文件已降到 {THRESHOLD} 行以下，请同步删除本表条目并下调 '
        f'scripts/gate_baseline.json 的 ts_module_length 计数：{stale}'
    )
