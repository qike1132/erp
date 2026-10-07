"""回归守卫：应用连接池的 pool_recycle 必须小于服务器 idle_session_timeout。

根因（2026-10-07）
------------------
服务器 postgresql.auto.conf 设 ``idle_session_timeout = '5min'``，会终止空闲超过
5 分钟的连接（实测日均 1000+ 次）。应用连接池的 ``pool_recycle`` 原为 1800s（30 分钟）
远大于它，于是池中连接被服务器杀掉后仍被应用取用 —— 表现为 asyncpg 协议错

    cannot switch to state 15; another operation (2) is in progress

（state 2 = PROTOCOL_ERROR_CONSUME），物化视图刷新任务间歇失败
（见 2026-10-07 16:25:00 的 8 次 idle-session timeout）。

本测试把「连接最大存活 < 服务器空闲超时」这一不变量钉死：
- 服务器 ``idle_session_timeout = 0``（禁用）时跳过；
- 否则要求 ``0 < pool_recycle < idle_session_timeout``。
"""
import pytest
from sqlalchemy import text


@pytest.mark.integration
async def test_pool_recycle_below_server_idle_timeout(test_engine):
    from fastapi_app.core.database import _pool_config

    recycle = _pool_config["pool_recycle"]
    assert recycle > 0, "pool_recycle 必须为正（0 表示禁用回收，会让坏连接长期驻留池中）"

    async with test_engine.connect() as conn:
        # current_setting 返回如 '5min' / '0'；cast 成 interval 再取秒，单位无关。
        idle_seconds = (
            await conn.execute(
                text("SELECT extract(epoch FROM current_setting('idle_session_timeout')::interval)")
            )
        ).scalar()

    idle_seconds = float(idle_seconds or 0)
    if idle_seconds == 0:
        pytest.skip("服务器 idle_session_timeout 已禁用，无此不变量约束")

    assert recycle < idle_seconds, (
        f"pool_recycle={recycle}s 必须 < 服务器 idle_session_timeout={idle_seconds:.0f}s，"
        "否则服务器会先杀掉空闲连接，应用取用坏连接会抛 asyncpg "
        "'cannot switch to state ...; another operation ... is in progress'"
    )
