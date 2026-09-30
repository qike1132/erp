"""清理不得删光所有备份：至少保留一个可还原的回滚点。

背景（/backup 审计，high）
-------------------------
`_mark_files_to_delete` 把「不在 keep 集里」的文件全部标删，并且磁盘压力分支还会
继续从 keep 集里往外删。两条路径都可能把备份目录清空 —— 于是系统**一个回滚点都不剩**。
清理是唯一会删备份的路径，"删光了"这种结果不可逆，必须由代码兜底而不是靠配置自觉。

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


# ---------------------------------------------------------------------------
# 端到端：走 _mark_files_to_delete
# ---------------------------------------------------------------------------

async def test_retention_never_empties_the_backup_dir() -> None:
    """keep 集为空（例如全部健康检查失败被移出）时，删除集仍须留一个。"""
    files = [_file('a.zip', 1), _file('b.zip', 2)]

    result = await _service()._mark_files_to_delete(files, set(), {'needs_cleanup': False})

    assert len(files) - len(result) >= 1, '不允许把备份目录清空'
    assert len(result) == 1 and result == {'b.zip'}


async def test_disk_pressure_cannot_eat_the_last_backup() -> None:
    """磁盘严重不足、keep 集被吃光时，最后一份备份仍要活下来。

    故意让「重要性」与「新旧」指向不同文件：磁盘分支先删低分的 a.zip，
    兜底则按**最新可还原**救回 a.zip。两者一致说明不了兜底按什么在选，
    所以这里断言的是 a.zip（新旧优先），而非 b.zip（分数优先）。
    """
    files = [_file('a.zip', 1, score=10), _file('b.zip', 2, score=90)]
    service = _service()
    service.cleanup_config['min_free_space_gb'] = 10_000  # 逼出「删更多」分支

    result = await service._mark_files_to_delete(
        files, {'a.zip', 'b.zip'}, {'needs_cleanup': True, 'free_gb': 0},
    )

    survivors = [f['name'] for f in files if f['name'] not in result]
    assert survivors == ['a.zip'], f'应恰好留下最新可还原的一份，实际 {survivors}'
