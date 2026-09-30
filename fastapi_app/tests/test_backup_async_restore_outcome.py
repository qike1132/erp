"""异步恢复的终态判定：库错误 / 校验未过 / 成功 三分支。

背景
----
`_run_async_file_restore` 原本内联了这段判定，抽取为 `_report_restore_outcome` 时
改变了控制流（if/elif/else → 提前 return），语义必须逐字保持：

- 库状态 `error` **优先于**校验结果；
- `overall_pass` 只有在**显式**为假时才判失败（字段缺失默认通过），
  否则老备份（无该字段）会被误报成失败；
- 失败信息要带上 L1/L2 摘要，运维才看得出差在哪张表。

没有测试锁住这三条，一次"顺手重构"就可能把成功刷成失败、或把失败吞成成功。
"""
from __future__ import annotations

import pytest

from fastapi_app.api.v1.endpoints.backup.restore import _report_restore_outcome


@pytest.fixture
def progress_calls(monkeypatch: pytest.MonkeyPatch) -> dict[str, list]:
    """拦下 complete/fail 两个进度上报，记录调用。"""
    import fastapi_app.core.backup_progress as bp

    recorded: dict[str, list] = {'complete': [], 'fail': []}

    async def _complete(task_id, result):
        recorded['complete'].append((task_id, result))

    async def _fail(task_id, message):
        recorded['fail'].append((task_id, message))

    monkeypatch.setattr(bp, 'complete_progress', _complete)
    monkeypatch.setattr(bp, 'fail_progress', _fail)
    return recorded


async def test_database_error_fails_with_reason(progress_calls: dict) -> None:
    result = {
        'database': {'status': 'error', 'message': 'restore aborted'},
        'verification': {'overall_pass': True},
    }

    await _report_restore_outcome('t1', result)

    assert progress_calls['complete'] == []
    assert progress_calls['fail'] == [('t1', '数据库恢复失败: restore aborted')]


async def test_database_error_wins_over_verification(progress_calls: dict) -> None:
    """库都恢复失败了，就不该再去报告"校验未通过" —— 首因优先。"""
    result = {
        'database': {'status': 'error', 'error': 'boom', 'message': 'ignored'},
        'verification': {'overall_pass': False, 'l1_row_count': {'summary': 'x'}},
    }

    await _report_restore_outcome('t2', result)

    assert progress_calls['fail'] == [('t2', '数据库恢复失败: boom')]


async def test_verification_failure_includes_both_summaries(progress_calls: dict) -> None:
    result = {
        'database': {'status': 'ok'},
        'verification': {
            'overall_pass': False,
            'l1_row_count': {'summary': 'L1 差 3 行'},
            'l2_fingerprint': {'summary': 'L2 指纹不符'},
        },
    }

    await _report_restore_outcome('t3', result)

    assert progress_calls['complete'] == []
    assert progress_calls['fail'] == [('t3', '数据验证未通过: L1 差 3 行; L2 指纹不符')]


async def test_verification_failure_without_l2_has_no_trailing_separator(progress_calls: dict) -> None:
    result = {
        'database': {'status': 'ok'},
        'verification': {'overall_pass': False, 'l1_row_count': {'summary': 'L1 差 1 行'}},
    }

    await _report_restore_outcome('t4', result)

    message = progress_calls['fail'][0][1]
    assert message == '数据验证未通过: L1 差 1 行'
    assert ';' not in message


async def test_missing_overall_pass_is_not_a_failure(progress_calls: dict) -> None:
    """字段缺失 = 无此校验环节，默认通过。老备份没有该字段，误判成失败会吓人。"""
    result = {'database': {'status': 'ok'}, 'verification': {}}

    await _report_restore_outcome('t5', result)

    assert progress_calls['fail'] == []
    assert progress_calls['complete'] == [('t5', result)]


async def test_success_completes_with_full_result(progress_calls: dict) -> None:
    result = {
        'database': {'status': 'ok'},
        'verification': {'overall_pass': True},
        'total_inserted': 42,
    }

    await _report_restore_outcome('t6', result)

    assert progress_calls['fail'] == []
    assert progress_calls['complete'] == [('t6', result)]


async def test_missing_database_section_is_not_an_error(progress_calls: dict) -> None:
    """没有 database 段落（如纯校验结果）不得被当成失败。"""
    await _report_restore_outcome('t7', {'verification': {'overall_pass': True}})

    assert progress_calls['fail'] == []
