"""版师服务层

提供版师列表查询与新增。
- 列表：按姓名升序返回全部版师（供打样弹窗下拉选择）
- 新增：姓名唯一，重复抛 BusinessError
"""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.exceptions import BusinessError
from fastapi_app.shared_models import PatternMaker

logger = logging.getLogger(__name__)


async def list_pattern_makers(db: AsyncSession) -> dict:
    """查询全部版师（按姓名升序）"""
    result = await db.execute(
        select(PatternMaker).order_by(PatternMaker.name.asc())
    )
    makers = result.scalars().all()
    return {
        'success': True,
        'items': [{'id': m.id, 'name': m.name} for m in makers],
    }


async def create_pattern_maker(db: AsyncSession, name: str) -> dict:
    """新增版师（姓名唯一）"""
    name = (name or '').strip()
    if not name:
        raise BusinessError('版师姓名不能为空')

    existing = await db.execute(
        select(PatternMaker.id).where(PatternMaker.name == name)
    )
    if existing.scalar_one_or_none() is not None:
        raise BusinessError(f'版师 "{name}" 已存在')

    maker = PatternMaker(name=name)
    db.add(maker)
    await db.flush()

    logger.info('新增版师: id=%s, name=%s', maker.id, name)
    return {'id': maker.id}


async def delete_pattern_maker(db: AsyncSession, maker_id: int) -> dict:
    """删除版师

    关联的打样项目 pattern_maker_id 会被 DB 外键 SET NULL 置空。
    """
    result = await db.execute(
        select(PatternMaker).where(PatternMaker.id == maker_id)
    )
    maker = result.scalar_one_or_none()
    if maker is None:
        from fastapi_app.core.exceptions import NotFoundError
        raise NotFoundError('版师不存在')

    name = maker.name
    await db.delete(maker)
    await db.flush()

    logger.info('删除版师: id=%s, name=%s', maker_id, name)
    return {'id': maker_id}
