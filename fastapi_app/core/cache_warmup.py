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

    优先级: 产品列表 > 仪表盘 > 库存统计（权限缓存不预热：见下方说明，
    权限判定读进程内 5s 缓存，Redis 侧无读取方）
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

            from fastapi_app.shared_models import Product

            # P1（2026-10-24）：删除 user:permissions:uid_* 预热。
            # 权限判定走 core/deps.py 的进程内 _PERMISSION_CACHE（TTL 5s），
            # 全仓没有任何读取 user:permissions:uid_* 的调用点 —— 这段预热只做 N 次
            # 无效 Redis 写；更实质的问题是它是一份 TTL 1 小时的权限快照，将来任何人
            # 接上读侧，撤权最长 1h 不生效，与 deps.py 承诺的「最坏 5s」直接冲突。

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
