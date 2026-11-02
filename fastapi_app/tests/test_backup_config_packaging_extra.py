"""备份包必须带上生效 nginx 引用的 TLS 证书与上传签名配置。

缺它们时纯还原后 nginx 起不来（ssl_certificate 缺文件）、上传图片全部 403
（secure_link 无密钥）。
"""
from __future__ import annotations

from fastapi_app.services.backup import _constants


def test_backup_manifest_carries_tls_and_signing() -> None:
    archive_paths = {arc for _, arc in _constants.config_files_to_package()}
    assert 'config/uploads-signing.conf' in archive_paths
    assert 'config/tls/server.crt' in archive_paths
    assert 'config/tls/server.key' in archive_paths


def test_tls_private_key_needs_restore_confirmation() -> None:
    assert 'tls/server.key' in _constants._SENSITIVE_CONFIG_FILES
