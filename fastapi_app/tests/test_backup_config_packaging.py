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
import ast
import inspect
import io
import zipfile

import pytest

from fastapi_app.services.backup import _constants, filestore
from fastapi_app.services.backup._constants import (
    _EXCLUDE_FILES,
    _SENSITIVE_AND_EXCLUDED_FILES,
    _SENSITIVE_CONFIG_FILES,
    CONFIG_DIR,
    PROJECT_ROOT,
    active_jwt_key_relative_paths,
    config_files_to_package,
)
from fastapi_app.services.backup.orchestration import core as backup_core
from fastapi_app.services.backup.orchestration.core import pack_config_files, record_config_includes

_SKIP_NO_KEYS = '未配置 JWT 密钥路径（无 .env 的环境，如 CI）'


def _packaged_archive_paths() -> set[str]:
    """清单里的归档名 —— P0-2 起**自带命名空间**（config/* 或 root/*）。"""
    return {archive for _src, archive in config_files_to_package()}


def _packaged_config_relative() -> set[str]:
    """config/ 命名空间内的相对名（历史口径：清单项曾不带前缀）。"""
    return {a[len('config/'):] for a in _packaged_archive_paths() if a.startswith('config/')}


# --------------------------------------------------------------------------
# 打包侧
# --------------------------------------------------------------------------

def test_packaged_jwt_entries_match_active_keys():
    """归档里的 jwt/* 必须**恰好**是现役密钥（既不漏，也不留退役件）。"""
    active = set(active_jwt_key_relative_paths())
    if not active:
        pytest.skip(_SKIP_NO_KEYS)
    packaged = {a for a in _packaged_config_relative() if a.startswith('jwt/')}
    assert packaged == active, f'打包的密钥 {sorted(packaged)} != 现役 {sorted(active)}'


def test_leaked_retired_key_is_not_packaged():
    """已在 git 历史泄漏的退役钥不得随备份分发（除非它恰好是现役钥）。"""
    if 'jwt/private.pem' in set(active_jwt_key_relative_paths()):
        pytest.skip('本机现役钥就是 private.pem')
    assert 'jwt/private.pem' not in _packaged_config_relative()


def test_runtime_env_is_packaged_from_project_root():
    """运行时 .env（PROJECT_ROOT/.env）必须进包，且归档到 root/ 命名空间。"""
    entries = {archive: src for src, archive in config_files_to_package()}
    assert 'root/.env' in entries, '运行时 .env 未进备份清单'
    assert entries['root/.env'] == PROJECT_ROOT / '.env'


def test_sensitive_set_covers_active_keys_and_runtime_env():
    """现役密钥与 .env 都必须在敏感白名单里（明文包排除 + 还原需确认）。

    P0-2：清单里的归档名是 **root/.env**（带命名空间），所以它必须显式进白名单 ——
    否则打包侧按归档名比对会漏判、明文包会把运行时 .env 一起打进去。
    """
    for rel in active_jwt_key_relative_paths():
        assert f'config/{rel}' in _packaged_archive_paths(), f'现役密钥未带命名空间进清单: config/{rel}'
        assert rel in _SENSITIVE_CONFIG_FILES, f'现役密钥未列入敏感白名单: {rel}'
    assert '.env' in _SENSITIVE_CONFIG_FILES, 'config 内相对名（旧格式）必须保留'
    assert 'root/.env' in _SENSITIVE_CONFIG_FILES, '归档名 root/.env 必须显式进白名单'
    assert 'root/.env' in _SENSITIVE_AND_EXCLUDED_FILES


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

# --------------------------------------------------------------------------
# P0-2：本机 Windows 运行时**真正生效**的配置 + NSSM 服务定义必须进包
# --------------------------------------------------------------------------

_RUNTIME_CONFIG_ENTRIES = (
    'nginx-windows.conf',
    'security-headers.conf',
    'redis-broker.conf',
    'nssm-services.json',
)


def _packaged_entries() -> dict[str, object]:
    return {archive: src for src, archive in config_files_to_package()}


@pytest.mark.parametrize('name', _RUNTIME_CONFIG_ENTRIES)
def test_runtime_config_is_packaged(name):
    """NSSM 服务真正加载的配置与 NSSM 服务定义都必须在备份清单里。

    旧清单只有 Docker 形态的 nginx.conf / redis.production.conf：本机起的是 NSSM
    服务 erp-web（`-c config\nginx-windows.conf`）与 erp-redis-broker
    （config/redis-broker.conf），security-headers.conf 被 server 级 include。
    这些不进包 ⇒ 灾难恢复照包内配置起服务，起成另一个形态。见 config/README.md。
    """
    entries = _packaged_entries()
    archive = f'config/{name}'
    assert archive in entries, f'{archive} 未进备份清单 —— 灾难恢复会缺件'
    assert entries[archive] == CONFIG_DIR / name
    assert entries[archive].is_file(), f'清单声明了 {archive} 但源文件不存在: {entries[archive]}'


def test_runtime_config_entries_are_not_gated_as_sensitive():
    """四项都不是敏感件、也不在显式排除里 ⇒ 明文档也必须带上（补了要真进包）。"""
    for name in _RUNTIME_CONFIG_ENTRIES:
        for path in (f'config/{name}', name):
            assert path not in _SENSITIVE_AND_EXCLUDED_FILES, f'{path} 被敏感闸门拦下'
            assert path not in _EXCLUDE_FILES, f'{path} 被 BACKUP_EXCLUDE_FILES 排除'


def test_runtime_config_round_trips_into_config_dir(isolated_roots):
    """按真实写包布局（config/{name}）还原时，四项都要落回 config/。"""
    zf = _zip_with({f'config/{name}': b'# stub\n' for name in _RUNTIME_CONFIG_ENTRIES})
    result = filestore.restore_config(zf, confirm_sensitive=False)
    assert result['status'] == 'ok', result
    for name in _RUNTIME_CONFIG_ENTRIES:
        target = isolated_roots / 'config' / name
        assert target.read_bytes() == b'# stub\n'
        assert name in result['restored']


# --------------------------------------------------------------------------
# P0-2：归档命名空间一致性 + 运行时 .env 的敏感闸门
#
# 缺陷：打包侧无条件给清单项拼 'config/'，运行时 .env 在包内成了
# config/root/.env —— 还原时命中 config/ 前缀落到 CONFIG_DIR/root/.env（幽灵目录），
# 项目根的 .env 永远不被还原；且那个条目名不在敏感白名单里，明文还原可绕过
# confirm_sensitive 闸门。（打包侧另有一层：明文包本来就不该带 .env。）
# --------------------------------------------------------------------------


@pytest.fixture()
def isolated_pack_roots(tmp_path, monkeypatch):
    """把打包清单的源根重定向到 tmp_path（不碰真实 config/ 与 .env）。

    _constants.config_files_to_package() 在**调用时**读模块级 CONFIG_DIR /
    RUNTIME_ENV_FILE，因此 monkeypatch 这三个名字就能让真实打包路径
    （core.pack_config_files）在隔离目录里跑。
    """
    config_dir = tmp_path / 'config'
    config_dir.mkdir()
    for name in _RUNTIME_CONFIG_ENTRIES:
        (config_dir / name).write_bytes(b'# stub\n')
    (tmp_path / '.env').write_bytes(b'APP_ENV=production\nSECRET_TOKEN=drill\n')
    monkeypatch.setattr(_constants, 'CONFIG_DIR', config_dir)
    monkeypatch.setattr(_constants, 'PROJECT_ROOT', tmp_path)
    monkeypatch.setattr(_constants, 'RUNTIME_ENV_FILE', tmp_path / '.env')
    # 同一条链路要能接着走还原侧：restore_config 的落点也指向 tmp_path。
    monkeypatch.setattr(filestore, 'CONFIG_DIR', config_dir)
    monkeypatch.setattr(filestore, 'PROJECT_ROOT', tmp_path)
    return tmp_path


def _pack_to_zip(include_sensitive: bool):
    """走真实打包函数 pack_config_files，返回 (可读 zip, 已打包清单, 被排除清单)。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        added, excluded = pack_config_files(zf, include_sensitive_config=include_sensitive)
    buf.seek(0)
    return zipfile.ZipFile(buf), added, excluded


def test_pack_config_files_uses_namespaced_archive_names(isolated_pack_roots):
    """打包侧照抄清单自带命名空间：.env → root/.env，配置 → config/*，不再自行拼前缀。"""
    zf, added, _excluded = _pack_to_zip(include_sensitive=True)
    names = zf.namelist()
    assert 'root/.env' in names
    assert 'root/.env' in added
    assert 'config/nginx-windows.conf' in names
    assert 'config/root/.env' not in names, '运行时 .env 不得再被打成 config/root/.env'


def test_plain_backup_excludes_runtime_env_and_records_it(isolated_pack_roots):
    """明文包（未加密）不打包运行时 .env，且被排除清单记下归档名 root/.env。"""
    zf, added, excluded = _pack_to_zip(include_sensitive=False)
    names = zf.namelist()
    assert 'root/.env' not in names
    assert 'root/.env' in excluded
    assert 'root/.env' not in added
    assert 'config/nginx-windows.conf' in names, '非敏感配置照常进包'


def test_manifest_records_excluded_runtime_env(isolated_pack_roots):
    """manifest.includes 必须留痕：明文包里被排除的 root/.env 要写进 config_files_excluded。"""
    _zf, added, excluded = _pack_to_zip(include_sensitive=False)
    manifest: dict = {'includes': {}}
    record_config_includes(manifest, added, excluded, include_sensitive_config=False)

    assert manifest['includes']['config_files'] == added
    assert manifest['includes']['config_files_excluded'] == excluded
    assert 'root/.env' in manifest['includes']['config_files_excluded'], '明文包缺件必须可审计'
    assert manifest['includes']['sensitive_config_included'] is False

    encrypted_manifest: dict = {'includes': {}}
    _zf2, added2, excluded2 = _pack_to_zip(include_sensitive=True)
    record_config_includes(encrypted_manifest, added2, excluded2, include_sensitive_config=True)
    assert 'root/.env' in added2
    assert 'config_files_excluded' not in encrypted_manifest['includes'], '没有缺件时不写该键'


def test_full_backup_path_calls_the_manifest_helper():
    """真实写包路径必须调用 record_config_includes。

    只测 helper 本身不足以锁住行为：清单结果的接线在写包函数里，
    被删/被绕过时 manifest 会静默丢掉 config_files_excluded（= 缺件不可审计）。

    2026-10-11（P2-14⑤ 拆分）：写包体从 _do_create_full_backup 移到
    _pack_backup_zip。守卫随之改为两段：①_pack_backup_zip 调用
    pack_config_files/record_config_includes；②_do_create_full_backup 确实
    调用 _pack_backup_zip —— 缺任一段即「接线断了」，与旧守卫等价。
    """
    tree = ast.parse(inspect.getsource(backup_core))

    def _calls_in(func_name: str) -> tuple[bool, set[str]]:
        found = False
        called: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == func_name:
                found = True
                for inner in ast.walk(node):
                    if isinstance(inner, ast.Call) and isinstance(inner.func, ast.Name):
                        called.add(inner.func.id)
        return found, called

    pack_found, pack_called = _calls_in('_pack_backup_zip')
    assert pack_found, '未找到 _pack_backup_zip —— 写包路径改名后本守卫需同步'
    assert 'pack_config_files' in pack_called
    assert 'record_config_includes' in pack_called, '写包路径未把配置清单结果写进 manifest'

    main_found, main_called = _calls_in('_do_create_full_backup')
    assert main_found, '未找到 _do_create_full_backup —— 写包路径改名后本守卫需同步'
    assert '_pack_backup_zip' in main_called, '编排路径未接上 _pack_backup_zip，写包被绕过'


def test_runtime_env_round_trips_to_project_root_via_real_packaging(isolated_pack_roots):
    """真实打包 → restore_config：PROJECT_ROOT/.env **字节级**恢复（P0-2 回归）。"""
    payload = (isolated_pack_roots / '.env').read_bytes()
    zf, _added, _excluded = _pack_to_zip(include_sensitive=True)
    # 先删源文件，确保断言的是「从包里还原」而不是「本来就在」
    (isolated_pack_roots / '.env').unlink()

    result = filestore.restore_config(zf, confirm_sensitive=True)

    assert (isolated_pack_roots / '.env').read_bytes() == payload
    assert not (isolated_pack_roots / 'config' / 'root').exists(), '不得创建 config/root/ 幽灵目录'
    assert '.env' in result['restored']


def test_real_packaging_then_restore_requires_confirmation_for_runtime_env(isolated_pack_roots):
    """同一条真实链路：confirm_sensitive=False 时 .env 不进位并出现在 skipped_sensitive。"""
    zf, _added, _excluded = _pack_to_zip(include_sensitive=True)
    (isolated_pack_roots / '.env').unlink()

    result = filestore.restore_config(zf, confirm_sensitive=False)

    assert not (isolated_pack_roots / '.env').exists()
    assert result['skipped_sensitive'] == ['.env']


def test_legacy_config_root_env_entry_still_lands_at_project_root(isolated_roots):
    """旧包兼容：含 config/root/.env 条目的旧归档仍还原到 PROJECT_ROOT/.env。

    （旧归档是 P0-2 之前打包出来的，直接按 config/ 前缀还原会写出
    CONFIG_DIR/root/.env 幽灵目录、真正的 .env 永不还原。）
    """
    zf = _zip_with({'config/root/.env': b'APP_ENV=production\n'})
    result = filestore.restore_config(zf, confirm_sensitive=True)
    assert (isolated_roots / '.env').read_bytes() == b'APP_ENV=production\n'
    assert not (isolated_roots / 'config' / 'root').exists(), '不得把幽灵目录还原出来'
    assert '.env' in result['restored']

    zf2 = _zip_with({'config/root/.env': b'SHOULD_NOT_BE_WRITTEN=1\n'})
    result2 = filestore.restore_config(zf2, confirm_sensitive=False)
    assert (isolated_roots / '.env').read_bytes() == b'APP_ENV=production\n'
    assert result2['skipped_sensitive'] == ['.env']
