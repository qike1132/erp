"""演练数据验证：manifest `rows = -1` 归 skipped（2026-11-17 上线前审计 V-C）。

## 拦哪种出错

`DrillValidator._validate_data_integrity` 把 manifest 的行数原样当期望值：
`passed = row_count == expected_rows`。但 manifest 里 **`rows = -1` 表示「该表行数未知」**
（导出时计数失败或结构漂移），不是「期望 -1 行」—— 对 -1 恒 `row_count == -1` 为假，
于是**这类表永远判失败**，整轮演练 `overall_success` 恒 False。

证据（审计 §10.1 V-C）：
- `backups/server/recovery_tests/m5_drill_raw_20260823.json:34-43` 里
  `{"table": "backup_schedule", "expected": -1, "actual": 0}` 与
  `{"table": "backup_settings", "expected": -1, "actual": 0}` —— `-1` 形态**实测存在**；
- 三份 `recovery_test_*.json` 全部 `overall_success=False`，灾备「就绪」结论因此永远拿不到，
  演练本身失去意义（真失败与假失败混成一个红）。

## 本文件各锁一件事

1. `test_unknown_row_count_table_is_skipped_not_failed`：`rows=-1` 的表不再拉低结论；
2. `test_all_tables_unknown_is_still_not_ready`：**全是** -1 时 total=0 → 仍判失败
   （没有可比数据不算灾备就绪，不能被这条放宽顺手打开）；
3. `test_real_missing_table_still_fails`：期望 114 行、实际 0 行 → 仍然 False
   （真缺表不许被 skipped 分支放过）；
4. `test_m5_drill_raw_fixture_turns_pass`：拿实测 raw 文件的 10 张表回放（两张 -1、
   其余按实际=期望的「恢复成功」形态），修复前因那两张恒失败 → False，修复后 → True。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from fastapi_app.services.backup.orchestration.drill_validator import DrillValidator

_RAW_FIXTURE = (
    Path(__file__).resolve().parent.parent.parent
    / 'backups' / 'server' / 'recovery_tests' / 'm5_drill_raw_20260823.json'
)

_TABLE_RE = re.compile(r'FROM\s+"?([A-Za-z_][A-Za-z0-9_]*)"?', re.IGNORECASE)


class _FakeResult:
    def __init__(self, value: int) -> None:
        self._value = value

    def scalar(self):
        return self._value


class _FakeConn:
    """按 SQL 里的表名返回预设行数（`_validate_data_integrity` 只做 COUNT(*)。"""

    def __init__(self, counts: dict[str, int]) -> None:
        self.counts = counts
        self.queried: list[str] = []

    async def execute(self, statement):
        sql = str(statement)
        match = _TABLE_RE.search(sql)
        table = match.group(1) if match else ''
        self.queried.append(table)
        return _FakeResult(self.counts.get(table, 0))


def _manifest(tables: dict[str, object]) -> dict:
    return {'manifest': {'tables': {name: {'rows': rows} for name, rows in tables.items()}}}


@pytest.mark.asyncio
async def test_unknown_row_count_table_is_skipped_not_failed():
    """rows=-1 的表：标 skipped、不进分母，其余表的结论照旧。"""
    validator = DrillValidator({})
    info = _manifest({'backup_schedule': -1, 'product': 114})
    conn = _FakeConn({'backup_schedule': 0, 'product': 114})

    result = await validator._validate_data_integrity(conn, info)

    assert result['passed'] is True, result
    assert result['skipped_tables'] == 1, result
    assert result['total_tables'] == 1, '未知行数的表不该进分母'
    assert result['details']['backup_schedule']['skipped'] is True
    assert 'rows=-1' in result['details']['backup_schedule']['skip_reason']


@pytest.mark.asyncio
async def test_all_tables_unknown_is_still_not_ready():
    """全是 -1 → 没有任何可比证据 → 不许判「就绪」。"""
    validator = DrillValidator({})
    info = _manifest({'backup_schedule': -1, 'backup_settings': -1})
    conn = _FakeConn({'backup_schedule': 0, 'backup_settings': 0})

    result = await validator._validate_data_integrity(conn, info)

    assert result['passed'] is False, result
    assert result['total_tables'] == 0
    assert result['skipped_tables'] == 2


@pytest.mark.asyncio
async def test_real_missing_table_still_fails():
    """期望 114、实际 0：真缺表的判定一字不让。"""
    validator = DrillValidator({})
    info = _manifest({'product': 114})
    conn = _FakeConn({'product': 0})

    result = await validator._validate_data_integrity(conn, info)

    assert result['passed'] is False, result
    assert result['failed_tables'] == 1
    assert result['details']['product']['passed'] is False


@pytest.mark.asyncio
async def test_m5_drill_raw_fixture_turns_pass():
    """实测 raw 文件回放：除两张 -1 外全部「恢复成功」→ 修复后应判通过。"""
    raw = json.loads(_RAW_FIXTURE.read_text(encoding='utf-8'))
    mismatched = raw['l1_verification']['mismatched']
    # 回放假设：非 -1 的表都恢复正确（actual = expected），-1 的两张照 raw 的实际值 0
    tables = {row['table']: row['expected'] for row in mismatched}
    counts = {
        row['table']: (0 if row['expected'] < 0 else row['expected'])
        for row in mismatched
    }
    assert sum(1 for v in tables.values() if v < 0) == 2, '夹具里应有 2 张 rows=-1'

    validator = DrillValidator({})
    result = await validator._validate_data_integrity(_FakeConn(counts), _manifest(tables))

    assert result['passed'] is True, (
        f"剩余表全部一致时仍判失败：{result['failed_tables']} 张失败 / "
        f"skipped={result['skipped_tables']} —— 说明 -1 表仍在拉低结论"
    )
    assert result['skipped_tables'] == 2
    assert result['total_tables'] == len(tables) - 2
