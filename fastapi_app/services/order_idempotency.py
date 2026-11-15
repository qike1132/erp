"""订单创建的请求级幂等（``POST /orders/create``）。

与采购单人工生成（``services/purchase_order_idempotency.py``）同一套机制，不另造轮子：

1. ``(actor_id, idempotency_key)`` 唯一登记 —— 同一个人同一把键只有一条记录；
2. ``request_hash`` 指纹 —— 同键不同内容判 409，避免重试把 A 订单的内容套到 B 上；
3. 成功后把响应体落 ``response_body``，同键同指纹的后续请求直接重放；
4. 事务级 advisory lock 把同键并发请求串行化（锁随外层事务提交/回滚释放）。

为什么不能「按订单号去重」：下单每次都会 ``generate_order_number()``，重试必然
拿到**新**单号，只有客户端带来的请求键能识别「这是同一次下单的重试」。
"""
from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.exceptions import BusinessError, ConflictError
from fastapi_app.core.pg_locks import acquire_advisory_lock_async, number_lock_key
from fastapi_app.shared_models import OrderCreateAttempt

#: 幂等键长度区间。上限 64 与列宽（String(64)）一致，下限 8 让「随手一个 1」也能被拦下。
KEY_MIN_LENGTH = 8
KEY_MAX_LENGTH = 64
#: 允许的字符集：只收 URL/HTTP 头里无需转义的字符，排除空格、引号、换行等
#: （它们会被网关或日志系统改写，导致「同一个键」在服务端变成两个）。
_KEY_PATTERN = re.compile(r'^[A-Za-z0-9._:-]+$')

#: 重放时替换进响应体的提示语：让调用方一眼看出「这次没有新建订单」。
REPLAY_MESSAGE = '重复请求，已返回首次结果（未重复建单）'

_CONFLICT_MESSAGE = '同一幂等键已用于不同的下单内容，请更换 Idempotency-Key 或核对请求体'


def validate_key(key: str | None) -> str | None:
    """校验 Idempotency-Key 并原样返回；未提供时返回 None（不强制客户端改造）。

    非法键在**开事务之前**就失败（BusinessError → 400），免得为一个注定失败的
    请求去抢 advisory lock、等行锁。
    """
    # 直接调用端点函数（单测/内部）时，FastAPI 的 Header 默认值会原样传进来，
    # 它不是 str；生产请求里 FastAPI 只会给 str 或 None。按「未提供」处理，
    # 避免 len(Header) 抛 TypeError。
    if key is None or not isinstance(key, str):
        return None
    if not (KEY_MIN_LENGTH <= len(key) <= KEY_MAX_LENGTH):
        raise BusinessError(
            f'Idempotency-Key 长度必须为 {KEY_MIN_LENGTH}-{KEY_MAX_LENGTH} 个字符'
        )
    if not _KEY_PATTERN.match(key):
        raise BusinessError('Idempotency-Key 只允许字母、数字与 . _ : - 字符')
    return key


def request_hash(
    product_id: int,
    quantity: int,
    customer: str | None,
    note: str | None,
) -> str:
    """下单内容指纹：规范化后用**定长列表**序列化再 sha256。

    刻意不用 dict 做规范化载体：dict 的序列化结果依赖键的插入顺序，两处构造
    顺序一旦不同，同一次重试就会被判成「内容变了」而误报 409。列表顺序固定，
    序列化结果只取决于取值本身。``note`` 的 None 归一到 ''（前端不传与传空串
    是同一个意思，不该判成两份内容）。
    """
    canonical = [
        int(product_id),
        int(quantity),
        (customer or '').strip(),
        (note or '').strip(),
    ]
    payload = json.dumps(canonical, ensure_ascii=False, separators=(',', ':')).encode()
    return hashlib.sha256(payload).hexdigest()


async def acquire_key_lock(db: AsyncSession, actor_id: int, key: str) -> None:
    """同一用户的同一请求键串行化：后到的并发重试在锁上排队，醒来即可读到首次结果。

    事务级 advisory lock（``pg_advisory_xact_lock``）随外层 ``db_transaction``
    的 commit/rollback 自动释放，不需要显式解锁；因此本函数**必须**在事务内调用。
    """
    lock_key = number_lock_key('ORDER_CREATE_KEY', f'{actor_id}:{key}')
    await acquire_advisory_lock_async(db, lock_key)


async def load_replay(
    db: AsyncSession, actor_id: int, key: str, fingerprint: str,
) -> dict | None:
    """读取可重放的响应体：无登记 / 首次未成功 → None（允许用同键重试）。

    - 无登记：正常首次请求；
    - 指纹不一致：同键换了内容，409（不能把首次结果张冠李戴地返回）；
    - ``response_body`` 为空或 ``success`` 不为真：上次没成，放行重做；
    - 其余：深拷贝后改 ``message`` 为重放提示，避免把「订单添加成功」当成
      「这次又建了一张」。
    """
    attempt = await db.scalar(
        select(OrderCreateAttempt).where(
            OrderCreateAttempt.actor_id == actor_id,
            OrderCreateAttempt.idempotency_key == key,
        )
    )
    if attempt is None:
        return None
    if attempt.request_hash != fingerprint:
        raise ConflictError(_CONFLICT_MESSAGE)
    body = attempt.response_body
    if not body or not body.get('success'):
        return None
    replay = deepcopy(body)
    replay['success'] = True
    replay['message'] = REPLAY_MESSAGE
    return replay


async def save_result(
    db: AsyncSession,
    actor_id: int,
    key: str,
    fingerprint: str,
    result: dict,
) -> None:
    """在同一数据库事务内登记本次结果（无则插入，有则更新响应体）。

    与订单写入同事务：订单回滚了登记也不会留下，不会出现「登记说建成、
    库里没有单」的假成功。
    """
    attempt = await db.scalar(
        select(OrderCreateAttempt).where(
            OrderCreateAttempt.actor_id == actor_id,
            OrderCreateAttempt.idempotency_key == key,
        )
    )
    if attempt is None:
        attempt = OrderCreateAttempt(
            actor_id=actor_id,
            idempotency_key=key,
            request_hash=fingerprint,
        )
        db.add(attempt)
    elif attempt.request_hash != fingerprint:
        raise ConflictError(_CONFLICT_MESSAGE)
    attempt.response_body = deepcopy(result)
    await db.flush()
