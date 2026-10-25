"""L-1（2026-10-25 上线前审计）：备份文件名前缀/后缀口径单源化。

背景：records（统计）与 cleanup（清理）各持一张硬编码前缀/后缀表且成员不同
（统计含 erp_incremental_/.json，清理不含）——分叉无书面约定，第三处改动
必然再漂移。单源化后：统计=全集（历史文件仍可见），清理=在产格式子集
（legacy 不参与保留期删除，防误删历史档案）。
"""


def test_cleanup_scope_is_documented_subset_of_stats_scope():
    from fastapi_app.services.backup._constants import (
        BACKUP_CLEANUP_PREFIXES,
        BACKUP_CLEANUP_SUFFIXES,
        BACKUP_NAME_PREFIXES,
        BACKUP_RECORD_SUFFIXES,
    )

    assert set(BACKUP_CLEANUP_PREFIXES) < set(BACKUP_NAME_PREFIXES), '清理必须是统计的真子集'
    assert set(BACKUP_NAME_PREFIXES) - set(BACKUP_CLEANUP_PREFIXES) == {'erp_incremental_'}, \
        '差集必须恰为已停产的增量包前缀（书面化既有行为，新增前缀须两表同步决策）'
    assert set(BACKUP_CLEANUP_SUFFIXES) < set(BACKUP_RECORD_SUFFIXES)
    assert set(BACKUP_RECORD_SUFFIXES) - set(BACKUP_CLEANUP_SUFFIXES) == {'.json'}, \
        '差集必须恰为 legacy JSON 包后缀'


def test_consumers_derive_from_constants_not_literals():
    """两个消费方的表必须与 _constants 常量内容一致（不得再各自字面量）。

    用 == 而非 is：全量套件里有用例 reload backup 子包，对象身份会失效
    （2026-10-25 提权全量实测），内容一致才是可移植的口径锁。
    """
    from fastapi_app.services.backup import records
    from fastapi_app.services.backup._constants import (
        BACKUP_CLEANUP_PREFIXES,
        BACKUP_CLEANUP_SUFFIXES,
        BACKUP_NAME_PREFIXES,
        BACKUP_RECORD_SUFFIXES,
    )
    from fastapi_app.services.backup.cleanup import service as cleanup_service

    assert records._BACKUP_NAME_PREFIXES == BACKUP_NAME_PREFIXES
    assert records._BACKUP_FILE_SUFFIXES == BACKUP_RECORD_SUFFIXES
    assert cleanup_service._FULL_PREFIXES == BACKUP_CLEANUP_PREFIXES
    assert cleanup_service._FULL_SUFFIXES == BACKUP_CLEANUP_SUFFIXES
