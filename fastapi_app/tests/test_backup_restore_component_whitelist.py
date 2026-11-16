"""组件恢复的成员白名单（2026-11-16 上线前审计 A-55）。

拦哪种错：``root/`` 前缀直接映射到 PROJECT_ROOT，而 zip 成员名是上传者可控的。
没有白名单时，一个「组件包」就能把工作区里的 .py/.ps1/.exe 覆写掉 —— 下次重启即
变成代码执行。超管本来等于主机运维（不是提权），但「恢复配置」没有理由改源码。

变异检查：删掉 ``_reject_non_config_member`` 的调用（或让它恒返回 None），
下面 test_restore_config_skips_source_members 必红。
"""
from __future__ import annotations

import io
import zipfile

import pytest

from fastapi_app.services.backup.filestore import _reject_non_config_member, restore_config


@pytest.mark.parametrize(
    'rel_path',
    [
        'fastapi_app/main.py',
        'root/fastapi_app/main.py',
        'root/scripts/ops/restart_backend.py',
        'server_manager/git_guard.py',
        'migrations/versions/pg_standalone_120_add_order_create_attempt.py',
        'root/.githooks/pre-commit',
        'root/run.ps1',
        'root/tools/patch.bat',
        'root/bin/driver.dll',
        'root/notes.py',
    ],
)
def test_reject_source_and_executable_members(rel_path):
    assert _reject_non_config_member(rel_path), f'{rel_path} 应被拒绝'


@pytest.mark.parametrize(
    'rel_path',
    [
        '.env',
        'root/.env',
        'jwt_private.pem',
        'config/app.yaml',
        'root/nssm-services.json',
        'root/config/nginx-windows.conf',
    ],
)
def test_allow_config_members(rel_path):
    """配置类成员（含运行时 .env 与 nssm 注册表）必须仍可还原，别把灾备堵死。"""
    assert _reject_non_config_member(rel_path) is None, f'{rel_path} 不该被拒绝'


def test_restore_config_skips_source_members(tmp_path, monkeypatch):
    """端到端：组件包里夹带源码成员时，恢复只落配置、并把源码成员记为 error。"""
    import fastapi_app.services.backup.filestore as filestore

    project_root = tmp_path / 'proj'
    config_dir = tmp_path / 'cfg'
    project_root.mkdir()
    config_dir.mkdir()
    monkeypatch.setattr(
        filestore,
        '_restore_roots',
        lambda: (('config/', config_dir), ('root/', project_root)),
    )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        zf.writestr('root/.env', 'APP_ENV=production\n')
        zf.writestr('root/fastapi_app/main.py', 'print("pwned")\n')
        zf.writestr('config/app.yaml', 'key: value\n')
    buf.seek(0)

    with zipfile.ZipFile(buf) as zf:
        # .env 属敏感名单，必须显式确认才还原（REV-09），这里正是要验证它仍能被灾备还原
        result = restore_config(zf, confirm_sensitive=True)

    assert (project_root / '.env').read_text(encoding='utf-8').startswith('APP_ENV=')
    assert (config_dir / 'app.yaml').exists()
    assert not (project_root / 'fastapi_app' / 'main.py').exists(), '源码成员被写进了工作区'
    assert result['status'] == 'partial'
    assert any('fastapi_app/main.py' in e for e in result['errors'])
    # restored 里记的是**去掉命名空间前缀**后的相对路径（root/ 前缀被剥掉）
    assert '.env' in result['restored']
