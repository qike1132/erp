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


#: 服务器 idle_session_timeout 的现值（D:\PostgreSQL\data\postgresql.auto.conf = '30min'）。
#: 部署侧改这个值时同步改这里，否则下面这条静态守卫就失去意义。
SERVER_IDLE_TIMEOUT_SECONDS = 1800

#: 会被复制成运行时 `.env` 的模板/灾备副本（`.env.production` 不入库，缺失时跳过）
POOL_RECYCLE_ENV_FILES = (".env.example", ".env.production", "config/.env.production")


def _read_pool_recycle(path) -> int | None:
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("DB_POOL_RECYCLE="):
            return int(stripped.split("=", 1)[1].strip())
    return None


def test_env_templates_pool_recycle_below_idle_timeout():
    """静态守卫：所有 `.env*` 副本里的 DB_POOL_RECYCLE 都必须小于 idle_session_timeout。

    为什么（2026-11-16 上线前审计 A-31）：上面那条集成测试只校验**代码默认值**与
    活库的 idle_session_timeout，扫不到 `.env.production` 这两份灾备副本——它们在 P0-10
    那次修复里被漏掉，仍写着 1800（= 服务器阈值，不是「小于」）。灾备真按它还原，
    2026-10-07 的连接态错乱会原样回归，而 CI 永远不会红。
    """
    from pathlib import Path

    from fastapi_app.core.database import _pool_config

    root = Path(__file__).resolve().parents[1]
    code_default = _pool_config["pool_recycle"]
    assert code_default == 1500, f"代码默认 pool_recycle 应为 1500s，实际 {code_default}"

    checked = []
    for rel in POOL_RECYCLE_ENV_FILES:
        path = root / rel
        if not path.exists():
            continue  # .env.production 不入库，全新克隆下不存在
        value = _read_pool_recycle(path)
        assert value is not None, f"{rel} 缺少 DB_POOL_RECYCLE 声明"
        assert value == code_default, (
            f"{rel} 的 DB_POOL_RECYCLE={value} 与代码默认 {code_default} 不一致"
            "（灾备按它还原会引入已修复的连接态错乱）"
        )
        assert value < SERVER_IDLE_TIMEOUT_SECONDS, (
            f"{rel} 的 DB_POOL_RECYCLE={value}s 必须 < 服务器 "
            f"idle_session_timeout={SERVER_IDLE_TIMEOUT_SECONDS}s"
        )
        checked.append(rel)

    assert checked, "至少要校验到 .env.example"

