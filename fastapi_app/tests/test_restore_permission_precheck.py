"""恢复建库权预检：失败必须发生在任何 DROP 之前（不依赖本机角色权限）。"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from fastapi_app.services.backup import dump


@pytest.mark.asyncio
async def test_admin_capability_false_returns_explicit_refusal():
    proc = SimpleNamespace(returncode=0, stdout=b'false\n', stderr=b'')
    with patch.object(dump, 'resolve_pg_tool', return_value='psql'), \
         patch.object(dump, 'run_proc', AsyncMock(return_value=proc)):
        error = await dump._admin_can_create_database(
            db_host='127.0.0.1', db_port='5432', admin_user='no_createdb', admin_env={},
        )

    assert error is not None
    assert '缺少建库权限' in error
    assert '旧库未被删除' in error


@pytest.mark.asyncio
async def test_rebuild_aborts_before_any_database_command_when_precheck_fails():
    run_proc = AsyncMock()
    with patch.object(
        dump, '_admin_can_create_database',
        AsyncMock(return_value='恢复已中止（旧库未被删除）：缺少建库权限'),
    ), patch.object(dump, 'run_proc', run_proc):
        result = await dump._rebuild_database_with_admin(
            db_host='127.0.0.1',
            db_port='5432',
            admin_user='no_createdb',
            admin_env={},
            db_user='erp_app',
            db_name='erp_system_test',
        )

    assert result['status'] == 'error'
    assert '缺少建库权限' in result['error']
    assert run_proc.await_count == 0, '预检失败后不得执行 DROP/CREATE 等任何数据库命令'
