"""部署对账：numbering_counter 水位 GREATEST(水位, 数据max)，只升不降。

关闭 spec §5 的同日键碰撞窗口：日期段从 UTC 切北京当天，两条路径共用同一
日期字符串而 seed 分支被忽略——若 data_max > last_seq，后续取号会连续撞
唯一索引。对账在 FastAPI lifespan 幂等执行；4 个 worker 并发触发由
advisory lock 串行化（GREATEST 语义本身安全，锁防交错报错）。

实现要点：每个实体一条**集合式** INSERT ... SELECT ... ON CONFLICT 语句完成
「扫描当日最大序号 + 补插缺行 + GREATEST 抬升」，不逐行 SELECT/UPDATE（无
循环内查询，非 N+1）。写入发生在**调用方会话**内（本函数不 commit），事务
边界归调用方；lifespan 侧调用后显式 commit 落库。
"""
import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.pg_locks import acquire_advisory_lock_async, number_lock_key

logger = logging.getLogger(__name__)

# (prefix, model 表名, 编号列名) —— 覆盖全部生成类编号实体（spec §4.5 前缀表）。
# 表名/列名均为本白名单常量，SQL 文本拼接无用户输入（值仍走绑定参数）。
NUMBERED_ENTITIES = [
    ('PO', 'order', 'order_no'),
    # 采购单 2026-10-10 起与客户订单共用 'PO' 前缀（迁移 pg_standalone_089）。
    # 两条同前缀、不同表：各自 upsert 到同一 (PO, date) 键，GREATEST 取两者最大值。
    ('PO', 'purchase_order', 'order_no'),
    ('BH', 'stock_in', 'stockin_no'),
    ('SO', 'stock_out', 'stockout_no'),
    ('CSO', 'case_movement', 'movement_no'),
    ('CSI', 'case_movement', 'movement_no'),
    ('CS', 'customer_sampling_project', 'sequence_no'),
    ('FH', 'outsource_shipment', 'shipment_no'),
    ('SR', 'stock_return', 'return_no'),
    ('PP', 'purchase_plans', 'plan_no'),
]

_RECONCILE_LOCK = number_lock_key('NUMBERING_RECONCILE', 'startup')

# 单实体对账语句：把该实体「按编号日期段分组的数值 max」作为候选水位 upsert 进
# numbering_counter。冲突且候选高于现有水位才更新（GREATEST，绝不降低）；
# RETURNING (xmax = 0) 区分本次是 INSERT（xmax=0）还是 UPDATE，供精确计数。
# 表名/列名来自 NUMBERED_ENTITIES 白名单常量，非用户输入（nosec B608）。
_ENTITY_UPSERT_SQL = (
    'INSERT INTO numbering_counter (prefix, number_date, last_seq, updated_at) '
    'SELECT :prefix, d.number_date, d.mx, now() '
    'FROM ('
    'SELECT split_part("{column}", \'-\', 2) AS number_date, '
    'CAST(MAX(CAST(split_part("{column}", \'-\', 3) AS BIGINT)) AS INTEGER) AS mx '
    'FROM "{table}" '
    'WHERE "{column}" ~ \'^[A-Z]+-[0-9]{{8}}-[0-9]+$\' '
    'GROUP BY 1'
    ') AS d '
    'WHERE d.mx IS NOT NULL '
    'ON CONFLICT (prefix, number_date) '
    'DO UPDATE SET last_seq = GREATEST(numbering_counter.last_seq, EXCLUDED.last_seq), '
    'updated_at = now() '
    'WHERE EXCLUDED.last_seq > numbering_counter.last_seq '
    'RETURNING (xmax = 0) AS was_inserted'
)


async def _reconcile_entity(db: AsyncSession, prefix: str, table: str, column: str) -> tuple[int, int]:
    """对单个实体对账一次，返回 (inserted, raised)。"""
    sql = text(_ENTITY_UPSERT_SQL.format(column=column, table=table))  # nosec B608 - 白名单常量
    returned = (await db.execute(sql, {'prefix': prefix})).fetchall()
    inserted = sum(1 for (was_inserted,) in returned if was_inserted)
    return inserted, len(returned) - inserted


async def reconcile_numbering_counters(db: AsyncSession) -> dict:
    """对账，返回 {'raised': n, 'inserted': n}。幂等：重复执行无变化。

    写入发生在**调用方会话/事务**内（本函数不 commit）——与 generate_number_async
    一致：事务边界归调用方所有。``raised`` 只计实际抬升的行：候选水位不高于现有
    水位时 ON CONFLICT 的 DO UPDATE 被 WHERE 拒绝，该行既不改也不返回，故第二次
    调用返回 {'raised': 0, 'inserted': 0}。
    """
    await acquire_advisory_lock_async(db, _RECONCILE_LOCK)
    raised = inserted = 0
    for prefix, table, column in NUMBERED_ENTITIES:
        ent_inserted, ent_raised = await _reconcile_entity(db, prefix, table, column)
        inserted += ent_inserted
        raised += ent_raised
    return {'raised': raised, 'inserted': inserted}
