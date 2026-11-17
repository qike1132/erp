"""演练数据验证：manifest `rows = -1` 归 skipped（2026-11-17 上线前审计 V-C）。

## 拦哪种出错

`DrillValidator._validate_data_integrity` 把 manifest 的行数原样当期望值：
`passed = row_count == expected_rows`。但 manifest 里 **`rows = -1` 表示「该表行数未知」**
（导出时计数失败或结构漂移），不是「期望 -1 行」—— 对 -1 恒 `row_count == -1` 为假，
于是**这类表永远判失败**，整轮演练 `overall_success` 恒 False。

证据（审计 §10.1 V-C）：
- 2026-08-23 的一次实测演练产物里 `backup_schedule` / `backup_settings` 两张表就是
  `{"expected": -1, "actual": 0}` —— `-1` 形态**实测存在**；
- 三份 `recovery_test_*.json` 全部 `overall_success=False`，灾备「就绪」结论因此永远拿不到，
  演练本身失去意义（真失败与假失败混成一个红）。

## 本文件各锁一件事

1. `test_unknown_row_count_table_is_skipped_not_failed`：`rows=-1` 的表不再拉低结论，
   但**证据不完整要说出口**（`evidence_incomplete=True`，见下）；
2. `test_all_tables_unknown_is_still_not_ready`：**全是** -1 时 total=0 → 判失败；
3. `test_real_missing_table_still_fails`：期望 114 行、实际 0 行 → 仍然 False；
4. `test_m5_drill_raw_fixture_turns_pass`：拿实测 raw 的 10 张表回放（两张 -1、其余按
   「恢复成功」形态），断言数据比对通过**且** evidence_incomplete 为真。

## 关于「证据不完整」（2026-11-17 OCR 复审 M1）

把 -1 表从分母里剔除能消灭「恒失败」，但 20 张表里 19 张 `rows=-1` + 1 张对齐也会算出
`passed=True` —— 等于把「没数过」记成「通过」。`orchestration/core.py` 对 `-1` 的定义
正是「备份产物中缺失该表行数（覆盖度不完整）」，所以这里改为：
`passed` 仍只表达「**已比对的表全一致**」，同时输出 `evidence_incomplete`
（有表 skipped 即 True），由 `validate_recovery` 让它否决整体成功 ——
既不再恒红，也不虚报就绪。

夹具数据**内联**（不读 `backups/` 下的运行期产物）：该目录被 `.gitignore` 忽略，
CI 干净检出时不存在，测试会以 FileNotFoundError 变红。
"""
from __future__ import annotations

import re

import pytest

from fastapi_app.services.backup.orchestration.drill_validator import DrillValidator

#: 2026-08-23 实测演练产物 `m5_drill_raw_20260823.json` 的 `l1_verification.mismatched`
#: 逐行转录（table, expected）。原文件在 backups/server/recovery_tests/ 下、被 gitignore，
#: 不能作为测试依赖 —— 故内联为字面量夹具。
_M5_DRILL_MISMATCHED: tuple[tuple[str, int], ...] = (
    ('audit_log', 14137),
    ('backup_record', 34),
    ('backup_schedule', -1),
    ('backup_settings', -1),
    ('country', 2),
    ('customer', 3),
    ('daily_production_record', 6),
    ('pattern_maker', 19),
    ('permission', 28),
    ('product', 114),
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
async def test_m5_drill_raw_fixture_compares_ok_but_flags_incomplete_evidence():
    """实测 raw 回放：除两张 -1 外全部「恢复成功」→ 数据比对通过，但证据不完整。

    修复前：两张 -1 表 `row_count == -1` 恒假 → passed=False（恒红）。
    修复后：passed=True（已比对的 8 张全一致）+ evidence_incomplete=True
    （2 张表行数未知，不能据此宣称「灾备就绪」）。
    """
    tables = dict(_M5_DRILL_MISMATCHED)
    # 回放假设：非 -1 的表都恢复正确（actual == expected），-1 的两张照 raw 的实际值 0
    counts = {name: (0 if expected < 0 else expected) for name, expected in tables.items()}
    assert sum(1 for v in tables.values() if v < 0) == 2, '夹具里应有 2 张 rows=-1'

    validator = DrillValidator({})
    result = await validator._validate_data_integrity(_FakeConn(counts), _manifest(tables))

    assert result['passed'] is True, (
        f"剩余表全部一致时仍判失败：{result['failed_tables']} 张失败 / "
        f"skipped={result['skipped_tables']} —— 说明 -1 表仍在拉低结论"
    )
    assert result['skipped_tables'] == 2
    assert result['total_tables'] == len(tables) - 2
    assert result['evidence_incomplete'] is True, (
        '2 张表行数未知却报「证据完整」—— 等于把「没数过」记成「通过」（OCR 复审 M1）'
    )


@pytest.mark.asyncio
async def test_clean_manifest_is_not_flagged_incomplete():
    """没有 -1 表时 evidence_incomplete 必须为假（别把正常演练也标成证据不全）。"""
    validator = DrillValidator({})
    info = _manifest({'product': 114, 'customer': 3})
    conn = _FakeConn({'product': 114, 'customer': 3})

    result = await validator._validate_data_integrity(conn, info)

    assert result['passed'] is True, result
    assert result['skipped_tables'] == 0
    assert result['evidence_incomplete'] is False
