"""备份族回归（M-20 / M-27，2026-11-21 全量审计）。

M-20：drill_validator 被 env 禁用的验证族此前恒 passed=False，演练必判失败
刷假告警——修复后禁用族标 skipped 并排除出 all()。
M-27：JSON 备份导出此前绕过备份/还原互斥（还原期间产出部分表缺失的损坏包）——
修复后还原进行中 409。
"""


def test_summarize_excludes_skipped_families():
    from fastapi_app.services.backup.orchestration.drill_validator import (
        _summarize_validation,
    )

    results = {
        'schema_validation': {'passed': False, 'skipped': True, 'details': {}},
        'data_validation': {'passed': True, 'details': {}},
        'constraint_validation': {'passed': True, 'skipped': False, 'details': {}},
        'performance_validation': {'passed': True, 'details': {}},
    }
    all_passed, incomplete = _summarize_validation(results)
    assert all_passed is True, all_passed
    assert incomplete is False


def test_summarize_still_fails_on_real_failure():
    from fastapi_app.services.backup.orchestration.drill_validator import (
        _summarize_validation,
    )

    results = {
        'schema_validation': {'passed': True, 'details': {}},
        'data_validation': {'passed': False, 'details': {}},
        'constraint_validation': {'passed': True, 'details': {}},
        'performance_validation': {'passed': True, 'details': {}},
    }
    all_passed, _ = _summarize_validation(results)
    assert all_passed is False


async def test_json_export_rejects_during_restore(async_client, auth_headers, monkeypatch):
    """M-27：还原进行中 JSON 导出必须 409，且不真正执行 legacy 备份。"""
    import fastapi_app.api.v1.endpoints.backup.export as exp

    async def _in_progress():
        return True

    async def _must_not_run(*args, **kwargs):
        raise AssertionError('还原进行中不应执行 legacy 备份导出')

    monkeypatch.setattr(exp, 'is_restore_in_progress', _in_progress)
    monkeypatch.setattr(exp.backup_service, 'execute_legacy_backup_to_bytes', _must_not_run)
    resp = await async_client.get(
        '/api/v1/backup/export', params={'format': 'json'}, headers=auth_headers)
    assert resp.status_code == 409, (resp.status_code, resp.text[:200])


async def test_json_export_still_works_when_no_restore(async_client, auth_headers, monkeypatch):
    """防修复误伤：无还原时 JSON 导出仍可用（stub 掉重活，仅验证守卫放行）。"""
    import fastapi_app.api.v1.endpoints.backup.export as exp

    async def _no_restore():
        return False

    async def _fake_legacy_backup(*args, **kwargs):
        return b'{"tables": {}}'

    monkeypatch.setattr(exp, 'is_restore_in_progress', _no_restore)
    monkeypatch.setattr(exp.backup_service, 'execute_legacy_backup_to_bytes', _fake_legacy_backup)
    resp = await async_client.get(
        '/api/v1/backup/export', params={'format': 'json'}, headers=auth_headers)
    assert resp.status_code == 200, (resp.status_code, resp.text[:200])
