"""
备货管理通用导入函数提取

import_staging_orders/stockins/stockouts_from_excel 的共享逻辑：
清空旧数据 → 解析Excel → 验证 → 创建记录 → 返回摘要
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def clear_and_import_staging(
    db: AsyncSession,
    staging_model,
    staging_objects: list,
    table_name: str,
) -> int:
    """通用暂存导入：清空旧数据并批量创建新记录"""
    if staging_objects:
        await db.execute(staging_model.__table__.delete())
        for obj in staging_objects:
            db.add(obj)
        await db.commit()
    logger.info(f'{table_name} 暂存导入完成: {len(staging_objects)} 条')
    return len(staging_objects)
