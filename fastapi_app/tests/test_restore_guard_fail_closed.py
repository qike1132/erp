"""B2 回归锁：恢复中断标记必须 fail-closed（写/读/清除三个环节）。

背景（2026-10-26 上线前检查 B2）
-------------------------------
DROP DATABASE 与后续 psql 单事务导入不是原子操作，中间失败会留下空壳库。
保护机制是「DROP 前落标记、只有成功才清除、启动/readiness 消费标记」，但原实现：

* 写标记失败只 warning，随后照样 DROP（破坏性操作完全没有中断保护）；
* 外层 finally 无条件清标记，失败也清（下次启动再也看不到「可能空壳」）；
* 读标记 I/O 失败返回 None，把「未知」折叠成「无中断」；
* 启动检查只打 CRITICAL，业务 readiness 照常 ready。

本文件把三条都锁住：失败必须让调用方在 DROP 前中止、失败后标记仍在、
不可读 != 无中断且必须让 readiness 失败（但进程与恢复入口保持可用）。
"""
from __future__ import annotations

import json

import pytest

from fastapi_app.services.backup import restore_guard as guard


@pytest.fixture
def marker_dir(tmp_path, monkeypatch):
    backups = tmp_path / 'backups'
    pre = backups / 'pre_restore'
    pre.mkdir(parents=True)
    monkeypatch.setattr(guard, 'BACKUP_DIR', backups)
    monkeypatch.setattr(guard, 'PRE_RESTORE_DIR', pre)
    # 冷却状态复位，避免用例间互相影响日志节流
    monkeypatch.setattr(guard, '_last_state_warn_at', 0.0, raising=False)
    return backups


# ---------------------------------------------------------------------------
# 写：失败必须在 DROP 之前中止
# ---------------------------------------------------------------------------
def test_mark_started_writes_durable_marker(marker_dir):
    path = guard.mark_restore_started('erp_system', 'task-1')

    assert path == marker_dir / guard.MARKER_NAME
    data = json.loads(path.read_text(encoding='utf-8'))
    assert data['db_name'] == 'erp_system'
    assert data['task_id'] == 'task-1'
    assert data['stage'] == 'drop_pending'
    assert data['started_at']


def test_mark_started_raises_when_write_fails(marker_dir, monkeypatch):
    """写失败不得再返回 None 让调用方继续 DROP。"""

    def _boom(*_a, **_k):
        raise OSError('disk full')

    monkeypatch.setattr(guard, '_atomic_write_json', _boom)

    with pytest.raises(guard.RestoreMarkerError, match='无法落盘'):
        guard.mark_restore_started('erp_system', None)


def test_mark_started_raises_when_readback_is_unreadable(marker_dir, monkeypatch):
    """写入"成功"但读不回来 == 没写：必须中止，而不是信一次 write 返回。"""
    monkeypatch.setattr(guard, 'read_marker_state',
                        lambda: (guard.MARKER_UNKNOWN, None))

    with pytest.raises(guard.RestoreMarkerError, match='回读校验失败'):
        guard.mark_restore_started('erp_system', None)


# ---------------------------------------------------------------------------
# 读：三态，unknown 绝不折叠成 absent
# ---------------------------------------------------------------------------
def test_read_state_absent_when_no_file(marker_dir):
    assert guard.read_marker_state() == (guard.MARKER_ABSENT, None)


def test_read_state_present_with_payload(marker_dir):
    guard.mark_restore_started('erp_system', None)
    state, data = guard.read_marker_state()
    assert state == guard.MARKER_PRESENT
    assert data['db_name'] == 'erp_system'


def test_read_state_present_when_json_corrupt(marker_dir):
    """损坏的标记仍意味着「有过一次未确认的还原」，不能当成没有。"""
    (marker_dir / guard.MARKER_NAME).write_text('{not json', encoding='utf-8')

    state, data = guard.read_marker_state()

    assert state == guard.MARKER_PRESENT
    assert data['parse_error'] is True


def test_read_state_unknown_when_unreadable(marker_dir):
    """路径存在但读不了（这里是目录）→ unknown，不得返回 absent。"""
    (marker_dir / guard.MARKER_NAME).mkdir()

    assert guard.read_marker_state() == (guard.MARKER_UNKNOWN, None)


# ---------------------------------------------------------------------------
# 清除：只有成功才清
# ---------------------------------------------------------------------------
def test_finished_clears_only_on_success(marker_dir):
    guard.mark_restore_started('erp_system', None)

    assert guard.mark_restore_finished(success=True) is True
    assert not (marker_dir / guard.MARKER_NAME).exists()
    assert guard.read_marker_state()[0] == guard.MARKER_ABSENT


def test_finished_keeps_marker_and_records_stage_on_failure(marker_dir):
    guard.mark_restore_started('erp_system', None)

    assert guard.mark_restore_finished(success=False, failure_stage='import') is True

    state, data = guard.read_marker_state()
    assert state == guard.MARKER_PRESENT, '失败后标记必须保留，供下次启动告警'
    assert data['failed_stage'] == 'import'
    assert data['failed_at']


def test_finished_reports_false_when_marker_already_gone(marker_dir):
    """失败但标记不见了 = 中断保护缺失，必须让调用方知道（返回 False）。"""
    assert guard.mark_restore_finished(success=False, failure_stage='import') is False


# ---------------------------------------------------------------------------
# 消费端：启动告警 + readiness 失败
# ---------------------------------------------------------------------------
def test_check_interrupted_reports_recovery_required(marker_dir):
    guard.mark_restore_started('erp_system', None)

    result = guard.check_interrupted_restore()

    assert result['state'] == guard.MARKER_PRESENT
    assert result['recovery_required'] is True
    assert result['marker']['db_name'] == 'erp_system'


def test_check_interrupted_noop_when_absent(marker_dir):
    assert guard.check_interrupted_restore() == {
        'state': guard.MARKER_ABSENT, 'recovery_required': False,
    }


def test_check_interrupted_never_raises_on_unknown(marker_dir):
    (marker_dir / guard.MARKER_NAME).mkdir()

    result = guard.check_interrupted_restore()

    assert result['recovery_required'] is True
    assert result['reason'] == 'marker_unreadable'


@pytest.mark.parametrize('kind', ['present', 'unknown'])
def test_readiness_fails_on_pending_or_unknown(marker_dir, kind):
    if kind == 'present':
        guard.mark_restore_started('erp_system', None)
    else:
        (marker_dir / guard.MARKER_NAME).mkdir()

    result = guard.restore_readiness()

    assert result['ok'] is False
    assert result['state'] == kind


def test_readiness_ok_when_no_marker(marker_dir):
    assert guard.restore_readiness() == {'ok': True, 'state': guard.MARKER_ABSENT}
