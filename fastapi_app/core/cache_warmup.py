"""缓存预热（应用启动时加载热点数据到 Redis）。

2026-10-15 自根 ``utils/redis_cache.py`` 迁入：该函数内需要 import
``fastapi_app.core.database`` 与 ``fastapi_app.shared_models``，留在根 utils
会让「utils → fastapi_app」与「fastapi_app → utils」构成包级循环（双向都靠
函数内延迟 import 才不炸——任何一侧提升到模块级即 ImportError；Clean
Architecture ADP 违例）。迁到 core 后，根 ``utils/redis_cache.py`` 是纯
Redis 客户端、零 fastapi_app 依赖，循环解除。
"""
import logging

logger = logging.getLogger(__name__)


async def warmup_cache() -> int:
    """缓存预热 - 应用启动时加载热点数据到Redis

    优先级: 权限 > 产品列表 > 仪表盘 > 库存统计
    """
    # 延迟 import：与 main.py 的启动序一致（本模块被 import 时引擎尚未就绪）
    from fastapi_app.core.database import get_async_db_context
    from utils.redis_cache import redis_cache

    logger.info('开始缓存预热...')
    warmed = 0

    try:
        async with get_async_db_context() as db:
            from sqlalchemy import func as sa_func
            from sqlalchemy import select

            from fastapi_app.shared_models import Permission, Product, User, user_permission

            try:
                # 批量 JOIN 查询：一次获取所有活跃用户及其权限，消除 N+1 问题
                result = await db.execute(
                    select(User.id, Permission.code)
                    .join(user_permission, User.id == user_permission.c.user_id)
                    .join(Permission, Permission.id == user_permission.c.permission_id)
                    .where(User.status.is_(True))  # SQLAlchemy 表达式，语义为 SQL 布尔比较
                )
                user_perms: dict[int, list[str]] = {}
                for uid, code in result.all():
                    user_perms.setdefault(uid, []).append(code)
                for uid, codes in user_perms.items():
                    await redis_cache.set(
                        f'user:permissions:uid_{uid}',
                        codes,
                        3600,
                    )
                    warmed += 1
            except Exception as e:  # defensive: 预热是启动加速项，单域失败不得阻断其余预热
                logger.warning('权限缓存预热失败: %s', e)

            try:
                count_result = await db.execute(select(sa_func.count()).select_from(Product))
                product_count = count_result.scalar() or 0
                await redis_cache.set('product:list:count', product_count, 600)
                warmed += 1
            except Exception as e:  # defensive: 预热是启动加速项，单域失败不得阻断其余预热
                logger.warning('产品计数缓存预热失败: %s', e)

    except Exception as e:  # defensive: 预热失败只降级为冷启动，不得阻断应用启动
        logger.warning('缓存预热数据库连接失败: %s', e)

    logger.info('缓存预热完成，预热 %d 项', warmed)
    return warmed
