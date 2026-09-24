"""只读副本授权自愈 (Read-only role grant self-healing)

背景：数据库恢复（psql/JSON restore）会重建表或重放备份，导致只读角色
erp_readonly 对 public schema 应用表的 SELECT 授权被清空，进而所有走只读
副本（读写分离）的报表/仪表盘接口返回 500（InsufficientPrivilegeError）。

本模块提供幂等的授权修复：在恢复完成后立即调用，并配合 periodic 对账任务
定时补齐，保证 erp_readonly 始终拥有只读访问权限。

授权在 PRIMARY（erp_app 为表 owner）执行，经流复制自动传播到只读副本。
"""
import logging

from sqlalchemy import text

from fastapi_app.core.database import get_async_db_context

logger = logging.getLogger(__name__)

# 只读角色名（与 config/postgres/init-replication.sh 保持一致）
# 注：历史上还引用了 deploy-windows.ps1，该脚本已删除（commit 15e13a79）。
_READONLY_ROLE = "erp_readonly"

# 幂等 GRANT：已授权时重复执行无副作用
_RESET_GRANTS_SQL = [
    "GRANT USAGE ON SCHEMA public TO {role}",
    "GRANT SELECT ON ALL TABLES IN SCHEMA public TO {role}",
    "GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO {role}",
    "GRANT SELECT ON ALL SEQUENCES IN SCHEMA public TO {role}",
]

# 默认权限：覆盖恢复后/后续新建表，避免仅补偿存量表
_DEFAULT_PRIVILEGES_SQL = [
    "ALTER DEFAULT PRIVILEGES FOR ROLE current_user IN SCHEMA public GRANT SELECT ON TABLES TO {role}",
    "ALTER DEFAULT PRIVILEGES FOR ROLE current_user IN SCHEMA public GRANT USAGE ON SEQUENCES TO {role}",
]


async def check_readonly_grant(db) -> bool:
    """探测 erp_readonly 是否拥有应用表 SELECT 权限（幂等观察，不改状态）。

    以业务必须存在的 `order` 表为探针；表不存在时返回 False，交由修复流程以幂等
    GRANT 兜底（此时 GRANT 无副作用）。
    """
    try:
        has_sel = await db.scalar(
            text("SELECT has_table_privilege(:role, 'order', 'SELECT')"),
            {"role": _READONLY_ROLE},
        )
    except Exception:  # broad-except: 探针异常（如表缺失/占位），降级为需要修复
        logger.debug("只读授权探针查询失败，将按需修复", exc_info=True)
        return False
    return bool(has_sel)


async def ensure_readonly_grants() -> bool:
    """确保 erp_readonly 拥有 public schema 只读权限（幂等）。

    Returns:
        bool: 是否发生了修复（True 表示本次补授了权限）。
    """
    async with get_async_db_context() as db:
        if await check_readonly_grant(db):
            return False

        for stmt in _RESET_GRANTS_SQL:
            await db.execute(text(stmt.format(role=_READONLY_ROLE)))
        for stmt in _DEFAULT_PRIVILEGES_SQL:
            await db.execute(text(stmt.format(role=_READONLY_ROLE)))
        # get_async_db_context 出口处自动 commit
        logger.warning("已为只读角色 %s 重新授予 public schema 只读权限（自愈）", _READONLY_ROLE)
        return True
