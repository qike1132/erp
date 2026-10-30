"""备份端点权限映射：声明与实现必须一致（2026-10-30 审计 A-H1）。

`/backup/restore/plan` 的 docstring 声明「权限:backup_read」，但 `_deps.py` 的
`permission_map` 曾漏登记该键，回退成 `backup_manage`——只有 backup_read /
backup_restore 的用户能发起还原却拿不到预览，前端确认按钮永久禁用。
"""
from fastapi_app.api.v1.endpoints.backup._deps import _get_backup_permission


def test_restore_plan_maps_to_backup_read():
    assert _get_backup_permission('restore_plan') == 'backup_read'


def test_restore_endpoints_keep_backup_restore():
    assert _get_backup_permission('restore_server_backup') == 'backup_restore'
    assert _get_backup_permission('async_restore_server_backup') == 'backup_restore'
    assert _get_backup_permission('async_import_backup') == 'backup_restore'


def test_unknown_endpoint_falls_back_to_manage():
    """未登记端点仍按 backup_manage 兜底（保持既有安全默认）。"""
    assert _get_backup_permission('__not_registered__') == 'backup_manage'
