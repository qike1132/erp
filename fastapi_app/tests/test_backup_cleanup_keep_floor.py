"""清理不得删光所有备份：至少保留一个可还原的回滚点。

背景（/backup 审计，high）
-------------------------
清理（全量-only，2026-10-12 起）是唯一会**删备份**的路径，而"删光了"意味着
系统从此没有回滚点，这种结果不可逆，必须由代码兜底而不是靠配置自觉。

修法：`_enforce_keep_floor` 只在「会删光」时介入，从删除集里救回最新且未被判定损坏的
一个（列表按 mtime 倒序，首个非 corrupted 即最新可还原者）。
"""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi_app.services.backup.cleanup.service import BackupCleanupService


def _file(name: str, days_ago: int, *, corrupted: bool = False, score: int = 0) -> dict:
    return {
        'name': name,
        'size_bytes': 1024 * 1024,
        'mtime': datetime.now() - timedelta(days=days_ago),
        'importance_score': score,
        'health_status': 'corrupted' if corrupted else 'healthy',
    }


def _service() -> BackupCleanupService:
    return BackupCleanupService()


# ---------------------------------------------------------------------------
# 兜底本身
# ---------------------------------------------------------------------------

def test_keeps_one_when_everything_would_be_deleted() -> None:
    files = [_file('new.zip', 1), _file('old.zip', 10)]
    to_delete = {'new.zip', 'old.zip'}

    result = _service()._enforce_keep_floor(files, to_delete)

    assert len(files) - len(result) == 1, '必须恰好保留一个'
    assert 'new.zip' in files[0]['name'], '输入约定按 mtime 倒序'


def test_survivor_is_the_newest_restorable() -> None:
    files = [_file('new.zip', 1), _file('mid.zip', 5), _file('old.zip', 30)]

    result = _service()._enforce_keep_floor(files, {'new.zip', 'mid.zip', 'old.zip'})

    assert result == {'mid.zip', 'old.zip'}, '应救回最新的 new.zip'


def test_skips_corrupted_when_a_healthy_one_exists() -> None:
    files = [_file('broken-newest.zip', 1, corrupted=True), _file('ok.zip', 4)]

    result = _service()._enforce_keep_floor(files, {'broken-newest.zip', 'ok.zip'})

    assert result == {'broken-newest.zip'}, '优先留下可还原的 ok.zip'


def test_keeps_one_even_when_all_corrupted() -> None:
    """全损坏也要留一个：损坏不等于不可人工抢救，而删光则完全不可逆。"""
    files = [_file('a.zip', 1, corrupted=True), _file('b.zip', 2, corrupted=True)]

    result = _service()._enforce_keep_floor(files, {'a.zip', 'b.zip'})

    assert len(files) - len(result) == 1


def test_no_intervention_when_something_survives() -> None:
    files = [_file('keep.zip', 1), _file('drop.zip', 9)]

    result = _service()._enforce_keep_floor(files, {'drop.zip'})

    assert result == {'drop.zip'}, '还有存活者时不得改动删除集'


def test_empty_input_is_harmless() -> None:
    assert _service()._enforce_keep_floor([], set()) == set()
