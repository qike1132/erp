"""保留策略单一真源 + 伴随文件清理（P0-2 ③）。

背景：同一套保留阈值此前有三份实现 —— `records.cleanup_old_backups` 用**硬编码**
30 天 / 50 份，`orchestration.policy_service` 与 `cleanup.service` 各自读 env（默认
30 天 / 100 份）。后果：策略页显示「保留 100 份」，实际清理按 50 份删；改 env 对
`records` 的清理完全无效。现在三处都以 env（BACKUP_RETENTION_DAYS /
BACKUP_RETENTION_COUNT）为唯一真源。

另一处：删除主文件时只删 `.record`（cleanup 服务）或只删 `.meta`（records），
加密包的 `.zip.enc.meta` 会永久残留。这里锁住「主文件删 ⇒ .meta 与 .record 一起删」。
"""
import ast
import importlib
import inspect
import json
import os
from datetime import datetime
from pathlib import Path

import pytest

from fastapi_app.services.backup import records
from fastapi_app.services.backup._constants import (
    RETENTION_COUNT_DEFAULT,
    RETENTION_COUNT_ENV,
    RETENTION_DAYS_DEFAULT,
    RETENTION_DAYS_ENV,
    retention_count,
    retention_days,
)


@pytest.fixture()
def backup_dir(tmp_path, monkeypatch):
    """把清理目标重定向到 tmp_path，避免测试碰到真实备份目录。"""
    monkeypatch.setattr(records, 'BACKUP_DIR', tmp_path)
    return tmp_path


def _make_backup(directory, name: str, *, age_days: float = 0.0):
    """造一个最小备份文件，mtime 固定在 age_days 天前。"""
    path = directory / name
    path.write_bytes(b'erp-backup-stub')
    stamp = datetime.now().timestamp() - age_days * 86400
    os.utime(path, (stamp, stamp))
    return path


def _write_sidecars(path, *, created_at: str | None = None, suffixes=('.meta', '.record')):
    written = []
    for suffix in suffixes:
        sidecar = path.parent / (path.name + suffix)
        payload = {} if suffix == ".record" else {"created_at": created_at, "encrypted": path.name.endswith(".enc")}
        sidecar.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
        written.append(sidecar)
    return written


# --------------------------------------------------------------------------
# 单一真源：env
# --------------------------------------------------------------------------


def test_retention_helpers_follow_env(monkeypatch):
    """_constants 的取数函数按调用时刻读 env（不是 import 期快照）。"""
    monkeypatch.setenv(RETENTION_DAYS_ENV, '13')
    monkeypatch.setenv(RETENTION_COUNT_ENV, '7')
    assert retention_days() == 13
    assert retention_count() == 7
    monkeypatch.setenv(RETENTION_DAYS_ENV, '31')
    assert retention_days() == 31, '同一进程内改 env 必须立刻生效'


def test_retention_defaults_match_documented_values(monkeypatch):
    """缺省保留天数 7（2026-10-12 起全量-only 策略；原为 30）。"""
    monkeypatch.delenv(RETENTION_DAYS_ENV, raising=False)
    monkeypatch.delenv(RETENTION_COUNT_ENV, raising=False)
    assert RETENTION_DAYS_DEFAULT == 7
    assert RETENTION_COUNT_DEFAULT == 100
    assert retention_days() == 7
    assert retention_count() == 100


def test_policy_service_and_constants_share_the_same_source(monkeypatch):
    """策略页（policy_service）与清理阈值必须同源同值。"""
    from fastapi_app.services.backup.orchestration.policy_service import BackupPolicyService

    monkeypatch.setenv(RETENTION_DAYS_ENV, '17')
    monkeypatch.setenv(RETENTION_COUNT_ENV, '9')
    policy = BackupPolicyService().policy_config
    assert policy['retention_days'] == 17 == retention_days()
    assert policy['retention_count'] == 9 == retention_count()


def test_cleanup_service_reads_the_same_env_keys(monkeypatch):
    """清理服务的保留天数与 _constants 单源同值（份数上限已随全量-only 策略移除）。"""
    from fastapi_app.services.backup.cleanup.service import BackupCleanupService

    monkeypatch.setenv(RETENTION_DAYS_ENV, '13')
    assert BackupCleanupService()._retention_days() == 13 == retention_days()


@pytest.mark.parametrize('module_path', [
    'fastapi_app.services.backup.cleanup.service',
    'fastapi_app.services.backup.orchestration.policy_service',
])
def test_retention_consumers_do_not_read_env_directly(module_path):
    """三个消费方一律走 _constants 单源：源码里不得再出现按保留键名取 env（AST 级）。

    只认真正的取值节点（Call 的实参 / Subscript 下标），docstring 与注释里提到键名
    不算 —— records.py 的说明性 docstring 就写着这两个键名。
    """
    module = importlib.import_module(module_path)
    keys = {RETENTION_DAYS_ENV, RETENTION_COUNT_ENV}
    tree = ast.parse(inspect.getsource(module))

    direct: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            args = [*node.args, *(kw.value for kw in node.keywords)]
            if any(isinstance(arg, ast.Constant) and arg.value in keys for arg in args):
                direct.append(f'{module_path}:{node.lineno} {ast.unparse(node)}')
        elif (
            isinstance(node, ast.Subscript)
            and isinstance(node.slice, ast.Constant)
            and node.slice.value in keys
        ):
            direct.append(f'{module_path}:{node.lineno} {ast.unparse(node)}')

    assert direct == [], f'{module_path} 仍直读保留策略 env，单源被绕过: {direct}'


# --------------------------------------------------------------------------
# 伴随文件：.meta / .record（含 .zip.enc.meta）必须随主文件一起删
# （records.cleanup_old_backups 第二套清理实现已删除，行为由下方 cleanup 服务用例覆盖）
# --------------------------------------------------------------------------


async def test_execute_cleanup_removes_sidecars_of_encrypted_package(tmp_path, monkeypatch):
    """cleanup 服务删主包时同步删 .meta（含 .zip.enc.meta）与 .record（P0-2 ③）。

    修复前 cleanup 只删 .record：删掉 .zip.enc 后 .zip.enc.meta 永久残留，
    下次扫描（按 .meta.created_at 判年龄）还会把它算成一份备份。
    """
    from fastapi_app.services.backup.cleanup import service as cleanup_service

    target = _make_backup(tmp_path, 'erp_auto_daily_20260901_000000.zip.enc', age_days=20)
    _write_sidecars(target)

    monkeypatch.setattr(cleanup_service, 'BACKUP_DIR', tmp_path)
    calls: list[list[str]] = []

    # 直接挂在类上按实例方法调用，故保留 self 形参（P0-2 F-01：去掉未使用的 noqa）
    async def _no_db(self, deleted_files):
        calls.append(list(deleted_files))
        return len(deleted_files), False

    monkeypatch.setattr(cleanup_service.BackupCleanupService, '_delete_backup_records', _no_db)
    service = object.__new__(cleanup_service.BackupCleanupService)

    result = await service._execute_cleanup({target.name})

    assert result['deleted_count'] == 1, result
    assert result['success'] is True, result
    assert calls == [[target.name]], 'DB 记录清理仍须收到已删文件名'
    assert [p.name for p in tmp_path.iterdir()] == [], '伴随文件（.meta/.record）不得残留'


def test_delete_backup_sidecars_returns_removed_names(tmp_path):
    """_delete_backup_sidecars 返回实际删掉的伴随文件名（幂等）。"""
    path = tmp_path / 'erp_backup_20260901_000000.zip'
    path.write_bytes(b'x')
    _write_sidecars(path)

    removed = records._delete_backup_sidecars(path)

    assert sorted(removed) == ['erp_backup_20260901_000000.zip.meta', 'erp_backup_20260901_000000.zip.record']
    assert records._delete_backup_sidecars(path) == []

async def test_execute_cleanup_surfaces_sidecar_delete_failure(tmp_path, monkeypatch):
    """伴随文件清理失败必须出现在清理结果里（t38），不再只有一条 ERROR 日志。

    cleanup 路径此前丢弃 _delete_backup_sidecars 的返回值 ⇒ 主文件删了、.meta 残留，
    调用方看到的却是 success=True / error_count=0。现在把 errors 聚合器透传给 helper。
    主文件删除、DB 记录清理、成功路径的返回结构一律不变。
    """
    from fastapi_app.services.backup.cleanup import service as cleanup_service

    target = _make_backup(tmp_path, 'erp_auto_daily_20260901_000000.zip.enc', age_days=20)
    _write_sidecars(target)

    monkeypatch.setattr(cleanup_service, 'BACKUP_DIR', tmp_path)
    calls: list[list[str]] = []

    async def _no_db(self, deleted_files):
        calls.append(list(deleted_files))
        return len(deleted_files), False

    monkeypatch.setattr(cleanup_service.BackupCleanupService, '_delete_backup_records', _no_db)

    real_unlink = type(target).unlink

    def flaky_unlink(self, *args, **kwargs):
        if self.name.endswith('.meta'):
            raise OSError('模拟占用')
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(type(target), 'unlink', flaky_unlink)
    service = object.__new__(cleanup_service.BackupCleanupService)

    result = await service._execute_cleanup({target.name})

    assert result['deleted_count'] == 1, result
    assert result['success'] is False, result
    assert result['error_count'] == 1, result
    assert len(result['errors']) == 1
    assert '伴随文件清理失败' in result['errors'][0]
    assert '.meta' in result['errors'][0] and '模拟占用' in result['errors'][0]
    assert set(result) == {
        'deleted_count', 'deleted_files', 'deleted_records', 'error_count', 'errors', 'success',
    }, '成功路径的返回结构未变'
    assert not target.exists()
    assert not (tmp_path / 'erp_auto_daily_20260901_000000.zip.enc.record').exists()
    assert (tmp_path / 'erp_auto_daily_20260901_000000.zip.enc.meta').exists(), '模拟失败件仍在'
    assert calls == [[target.name]], 'DB 记录清理仍须收到已删文件名'


def test_config_readme_scope_matches_nssm_self_description():
    """(c) config/README.md 的打包口径与 config/nssm-services.json 自述一致（t38）。

    旧口径「打进加密备份包」会让读者以为 nssm-services.json 只随加密包分发，
    实际明文包也包含它（不在敏感白名单、内容不含凭据）。
    """
    repo_root = Path(records.__file__).resolve().parents[3]
    readme = (repo_root / 'config' / 'README.md').read_text(encoding='utf-8')
    description = json.loads(
        (repo_root / 'config' / 'nssm-services.json').read_text(encoding='utf-8')
    )['description']

    assert '打进**加密备份包**' not in readme, '旧口径（只进加密包）应已消除'
    assert 'nssm-services.json' in readme, 'README 未点名该文件'
    assert '明文包与加密包都包含' in readme
    assert '明文包与加密包均包含' in description
    for phrase in ('明文包', '加密包', '不含敏感凭据'):
        assert phrase in readme, phrase
