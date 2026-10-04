"""导入文件指纹闸门（P1-a 第 1 层幂等）

对文件上传型导入做 DB 层幂等：同一文件内容（sha256）在同一导入类型下
只允许导入一次。消灭「重传同一 Excel 导致库存翻倍 / 重复建单」——
该缺陷在出货、订单导入路径上此前零防护。

正确性依赖请求级事务（get_async_db 在请求结束提交）：登记行与导入
产生/消费的业务行处于同一事务，任一方失败即整体回滚 —— 成功的导入
留下永久登记，失败的导入不留痕、可原样重试。

行为：命中重复登记 → 409 友好提示（区别于旧备货路径的「静默跳过
重复行」）。用户若要重试部分失败，需先删除已成功的行再上传（内容
变化 → 新哈希 → 放行）。

**已知缺口（本层拦不住）**：仅比对字节。用 Excel 打开再保存会改变
zip 时间戳 → 新哈希 → 放行。真正覆盖「编辑后重传」的是第 2 层
（``inventory_log.idem_key`` 部分唯一索引 + 规范化业务键），当前仅建
了地基、**尚未接线**；在此之前出货/订单导入对「编辑后重传」无防护。
"""
from __future__ import annotations

import hashlib
import io
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import HTTPException, UploadFile
from sqlalchemy import inspect as sa_inspect
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.shared_models import ImportFileRegistry, User

#: 各导入端点的类型标识（与 import_file_registry.import_type 一致）
TYPE_ORDERS = 'orders'
TYPE_STOCKINS = 'stockins'
TYPE_STOCKOUTS = 'stockouts'
TYPE_CASE_STOCKINS = 'case_stockins'
TYPE_CASE_STOCKOUTS = 'case_stockouts'
TYPE_PRODUCTS = 'products'
TYPE_COMPREHENSIVE = 'comprehensive'


def _duplicate_detail(import_type: str, prior_at: Any) -> str:
    when = ''
    if hasattr(prior_at, 'strftime'):
        when = f'{prior_at:%Y-%m-%d %H:%M} '
    return (
        f'该文件与{when}已导入的文件完全相同，已拒绝重复导入。'
        '如需重试失败行，请删除已成功的行后重新上传。'
    )


def _row_total(result: Any) -> int | None:
    """导入行数。综合导入的 ``imported`` 是 dict（各 Sheet 计数），取和。"""
    imported = getattr(result, 'imported', None)
    if isinstance(imported, dict):
        return sum(v for v in imported.values() if isinstance(v, int))
    return imported if isinstance(imported, int) else None


def _result_summary(result: Any) -> dict[str, Any]:
    imported = getattr(result, 'imported', None)
    if isinstance(imported, dict):
        return {'by_type': imported}
    return {'skipped': getattr(result, 'skipped', None)}


def _is_meaningful_success(result: Any) -> bool:
    """是否值得留存登记。

    要求 ``success`` 为真**且实际写入了行**。理由：
    - 综合导入的 ``success`` 恒为 True（Sheet 级失败只进 ``errors``），
      不额外要求导入量会把「全部 Sheet 失败」的文件哈希永久锁死；
    - 零导入（空 Sheet / 全被去重跳过）没有需要防的重复，锁哈希只会
      让用户无法原样重试，故一律不锁。
    """
    if not getattr(result, 'success', False):
        return False
    imported = getattr(result, 'imported', None)
    if isinstance(imported, dict):
        return any(isinstance(v, int) and v > 0 for v in imported.values())
    return isinstance(imported, int) and imported > 0


async def run_guarded_import[T](
    db: AsyncSession,
    file: UploadFile,
    import_type: str,
    user: User,
    runner: Callable[[UploadFile], Awaitable[T]],
) -> T:
    """哈希上传文件 → 查/写指纹登记 → 交给 runner 导入 → 按结果落定登记。

    Args:
        db: 请求级异步会话（事务由 get_async_db 收尾）。
        file: 上传的 Excel。
        import_type: 导入类型标识，见本模块 TYPE_* 常量。
        user: 当前用户（登记 uploaded_by）。
        runner: 接收「可重放的上传对象」并执行导入，返回带 ``success`` 的结果。

    Raises:
        HTTPException: 409 —— 同文件同类型已导入过（含并发双击）。
    """
    content = await file.read()
    digest = hashlib.sha256(content).hexdigest()

    prior = await db.scalar(
        select(ImportFileRegistry.created_at).where(
            ImportFileRegistry.file_hash == digest,
            ImportFileRegistry.import_type == import_type,
        )
    )
    if prior:
        raise HTTPException(status_code=409, detail=_duplicate_detail(import_type, prior))

    registry = ImportFileRegistry(
        file_hash=digest,
        import_type=import_type,
        original_filename=file.filename or '',
        uploaded_by=getattr(user, 'id', None),
    )
    db.add(registry)
    try:
        # flush 触发 UNIQUE(file_hash, import_type)：并发双击时第二个事务
        # 阻塞至第一个提交后立即违反唯一约束 —— 这是唯一原子的拦截点。
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=_duplicate_detail(import_type, None)) from exc

    replay = UploadFile(file=io.BytesIO(content), filename=file.filename or '')
    result = await runner(replay)

    if _is_meaningful_success(result):
        registry.row_total = _row_total(result)
        registry.result_summary = _result_summary(result)
    elif not sa_inspect(registry).transient:
        # 服务层错误分支会 ``await db.rollback()``：登记行随事务一并丢弃，
        # 对象随之变为 transient，此时对它 delete 会抛 InvalidRequestError。
        # 仅在登记仍留在会话内（早退校验未回滚）时才需显式删除。
        await db.delete(registry)
    return result
