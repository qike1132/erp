"""备份包的产出/下载/还原端点仅超管可用。

备份包内含运行时 .env、现役 JWT 私钥、上传签名密钥与全库用户口令哈希，
「备份读写权限」不该等价于「凭据读取权限」。只读列表/状态保持原细粒度权限。
"""
from __future__ import annotations


def test_download_and_restore_are_superuser_only() -> None:
    from fastapi_app.api.v1.endpoints.backup._deps import _SUPERUSER_ONLY

    for name in (
        'download_server_backup',
        'export_backup',
        'export_backup_enhanced',
        'export_backup_chunk',
        'save_backup_to_server',
        'import_backup',
        'restore_server_backup',
        'async_import_backup',
        'async_restore_server_backup',
    ):
        assert name in _SUPERUSER_ONLY, name


def test_read_only_listing_stays_fine_grained() -> None:
    from fastapi_app.api.v1.endpoints.backup._deps import _SUPERUSER_ONLY

    for name in ('list_server_backups', 'backup_status', 'get_backup_records'):
        assert name not in _SUPERUSER_ONLY, name
