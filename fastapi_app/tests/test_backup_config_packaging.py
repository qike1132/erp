"""备份包必须带上**现役**配置：JWT 密钥对与运行时 .env（H-3）。

背景：打包清单在 2026-08-22 密钥轮换后没跟着改，仍硬编码 `jwt/private.pem` +
`jwt/public.pem` —— 备份里装的是**退役**（且已在 git 历史泄漏）的那对密钥，而现役
`private_v2`/`public_v2` 与运行时 `.env` 全都不进包。真做灾难恢复时：
ES256 模式下 `JWT_PRIVATE_KEY_PATH` 指向的文件不在，应用直接起不来；若改用包里的
旧钥，等于把已泄漏的密钥重新启用。

这里锁住三件事：
1. 打包清单 = 现役密钥（按 settings 推导，随轮换自动跟进）+ 运行时 .env；
2. 退役钥不再随包分发；
3. 两者都在敏感白名单里（明文包排除、还原需二次确认），历史名保留以兼容旧包。
"""
import io
import zipfile

import pytest

from fastapi_app.services.backup import filestore
from fastapi_app.services.backup._constants import (
    _SENSITIVE_AND_EXCLUDED_FILES,
    _SENSITIVE_CONFIG_FILES,
    PROJECT_ROOT,
    active_jwt_key_relative_paths,
    config_files_to_package,
)

_SKIP_NO_KEYS = '未配置 JWT 密钥路径（无 .env 的环境，如 CI）'


def _packaged_archive_paths() -> set[str]:
    return {archive for _src, archive in config_files_to_package()}


# --------------------------------------------------------------------------
# 打包侧
# --------------------------------------------------------------------------

def test_packaged_jwt_entries_match_active_keys():
    """归档里的 jwt/* 必须**恰好**是现役密钥（既不漏，也不留退役件）。"""
    active = set(active_jwt_key_relative_paths())
    if not active:
        pytest.skip(_SKIP_NO_KEYS)
    packaged = {a for a in _packaged_archive_paths() if a.startswith('jwt/')}
    assert packaged == active, f'打包的密钥 {sorted(packaged)} != 现役 {sorted(active)}'


def test_leaked_retired_key_is_not_packaged():
    """已在 git 历史泄漏的退役钥不得随备份分发（除非它恰好是现役钥）。"""
    if 'jwt/private.pem' in set(active_jwt_key_relative_paths()):
        pytest.skip('本机现役钥就是 private.pem')
    assert 'jwt/private.pem' not in _packaged_archive_paths()


def test_runtime_env_is_packaged_from_project_root():
    """运行时 .env（PROJECT_ROOT/.env）必须进包，且归档到 root/ 命名空间。"""
    entries = {archive: src for src, archive in config_files_to_package()}
    assert 'root/.env' in entries, '运行时 .env 未进备份清单'
    assert entries['root/.env'] == PROJECT_ROOT / '.env'


def test_sensitive_set_covers_active_keys_and_runtime_env():
    """现役密钥与 .env 都必须在敏感白名单里（明文包排除 + 还原需确认）。"""
    for rel in active_jwt_key_relative_paths():
        assert rel in _SENSITIVE_CONFIG_FILES, f'现役密钥未列入敏感白名单: {rel}'
    assert '.env' in _SENSITIVE_CONFIG_FILES


def test_sensitive_set_keeps_legacy_names_for_old_archives():
    """历史名保留：旧备份包里的退役件仍要被闸门拦住。"""
    for legacy in ('jwt/private.pem', 'jwt/public.pem', '.env.production'):
        assert legacy in _SENSITIVE_CONFIG_FILES
        assert legacy in _SENSITIVE_AND_EXCLUDED_FILES


# --------------------------------------------------------------------------
# 还原侧（root/ 命名空间必须落到 PROJECT_ROOT，且受二次确认闸门约束）
# --------------------------------------------------------------------------

def _zip_with(entries: dict[str, bytes]) -> zipfile.ZipFile:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    buf.seek(0)
    return zipfile.ZipFile(buf)


@pytest.fixture()
def isolated_roots(tmp_path, monkeypatch):
    """把还原目标重定向到 tmp_path，避免测试碰到真实的 config/ 与 .env。"""
    config_dir = tmp_path / 'config'
    config_dir.mkdir()
    monkeypatch.setattr(filestore, 'CONFIG_DIR', config_dir)
    monkeypatch.setattr(filestore, 'PROJECT_ROOT', tmp_path)
    return tmp_path


def test_restore_config_puts_runtime_env_at_project_root(isolated_roots):
    """root/.env 必须落到 PROJECT_ROOT/.env（而不是 config/ 下）。"""
    zf = _zip_with({'root/.env': b'APP_ENV=production\n'})
    result = filestore.restore_config(zf, confirm_sensitive=True)
    assert (isolated_roots / '.env').read_bytes() == b'APP_ENV=production\n'
    assert (isolated_roots / 'config' / '.env').exists() is False
    assert result['status'] == 'ok'


def test_restore_config_requires_confirmation_for_runtime_env(isolated_roots):
    """未确认时不得覆盖运行时 .env（敏感闸门）。"""
    zf = _zip_with({'root/.env': b'APP_ENV=production\n'})
    result = filestore.restore_config(zf, confirm_sensitive=False)
    assert not (isolated_roots / '.env').exists()
    assert result['skipped_sensitive'] == ['.env']


def test_restore_config_keeps_config_namespace_behaviour(isolated_roots):
    """原有 config/ 命名空间行为不变。"""
    zf = _zip_with({'config/redis.production.conf': b'port 6379\n'})
    result = filestore.restore_config(zf, confirm_sensitive=False)
    assert (isolated_roots / 'config' / 'redis.production.conf').read_bytes() == b'port 6379\n'
    assert result['restored'] == ['redis.production.conf']


def test_restore_config_rejects_traversal_in_root_namespace(isolated_roots):
    """root/ 命名空间同样要挡目录穿越。"""
    zf = _zip_with({'root/../evil.txt': b'x'})
    result = filestore.restore_config(zf, confirm_sensitive=True)
    assert not (isolated_roots.parent / 'evil.txt').exists()
    assert result['errors'], '越界路径必须记为错误而不是静默通过'
