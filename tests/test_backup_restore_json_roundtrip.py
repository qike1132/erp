"""G4（2026-10-17 审计 TEST 区）：本仓缺「真实备份 → 还原 → 数据一致」的往返验证。

现状：`fastapi_app/tests/test_restore_real_roundtrip.py` 是唯一走真库的还原用例，
但它依赖 `pg_dump`/`psql` 在 PATH（本机生产机与 CI 都不满足）→ 常态 skip；而还原
是**唯一不可逆**链路，一旦 skip 就没有任何证据说明「备份能不能恢复」，恢复失败
只在真灾难时暴露。

本用例用真 PostgreSQL（测试库）+ 真 `restore_legacy_json` 跑一次最小往返，
**不需要 pg_dump、不需要超管**：
    真实行 → 备份载荷 → 清空表（模拟数据丢失）→ 还原 → 行数与主键集合一致。

隔离：三张核心表建在专用 schema `g4_roundtrip` 里（search_path 指过去），整个
过程在**一个事务**内完成并整体回滚 —— 既不碰 public 里的其它用例数据，也不留痕。

导出侧说明（诚实标注边界）：生产导出函数 `execute_legacy_backup_to_bytes` 先用
`information_schema.tables WHERE table_schema = 'public'` 过滤表名，专用 schema 下
会被判为「表不存在」而拒绝导出（那是它 fail-closed 的正确行为）。故载荷按该函数
逐字相同的循环体构造（`serialize_value` + columns/rows/count 同结构）。还原侧
——也就是真正不可逆的那一半——走的是生产函数本体。

**已知缺口（明确登记，不假装覆盖）**：导出函数本体（`information_schema` 表存在性过滤、
导出行序列化失败时的 ``{'error': ...}`` 载荷形状、`tables/exclude_tables` 过滤语义）本用例
**零覆盖** —— 载荷是照抄它的循环体拼的。要覆盖导出侧需另开一条用例（临时目录 + tmp 库或
对 `_validate_json_backup_payload` 的 fail-closed 分支单独断言）。
"""
import json

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fastapi_app.shared_models import Base

SCHEMA = 'g4_roundtrip'
CORE_TABLES = ('customer', 'product', 'supplier')


def _quote(name: str) -> str:
    return f'"{name}"'


async def _snapshot(db: AsyncSession) -> dict[str, list[int]]:
    """三张核心表的 (id 升序) 主键快照 —— 行数与身份一起比。"""
    out: dict[str, list[int]] = {}
    for table in CORE_TABLES:
        rows = (await db.execute(
            text(f'SELECT id FROM {_quote(table)} ORDER BY id')  # nosec B608 - 表名来自本文件常量
        )).scalars().all()
        out[table] = list(rows)
    return out


def _build_payload(db, rows_by_table: dict) -> dict:
    """按 `execute_legacy_backup_to_bytes` 的循环体结构组装载荷（同字段/同序列化）。"""
    from fastapi_app.services.backup.json_backup import serialize_value

    tables: dict[str, dict] = {}
    for table, (columns, rows) in rows_by_table.items():
        tables[table] = {
            'columns': columns,
            'rows': [{c: serialize_value(r[c]) for c in columns} for r in rows],
            'count': len(rows),
        }
    return {
        'version': '1.0',
        'exported_at': '2026-11-18 00:00:00',
        'exported_by': 'g4-roundtrip',
        'remark': 'G4 最小往返',
        'tables': tables,
    }


@pytest_asyncio.fixture
async def isolated_schema(test_engine):
    """建专用 schema + 三张核心表，测试结束后随外事务回滚消失。

    `checkfirst=False` 是必须的：默认 True 时 create_all 先做存在性探测，而探测
    走的是**默认 search_path**（public），public 里已有同名表就会被判为「已存在」
    并跳过 DDL —— 专用 schema 里于是没有表，后续非限定语句全部落回 public，
    隔离静默失效（全量跑时本用例正是这样红的：快照里混进了别的用例的 product）。
    """
    tables = [Base.metadata.tables[name] for name in CORE_TABLES]
    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

    async with factory() as db:
        # 幂等：上一次若真留下残骸（例如某次 restore 加了 commit），这里先清干净，
        # 否则 CREATE SCHEMA 直接报错，且残留表会让隔离自检以难懂的方式失败。
        await db.execute(text(f'DROP SCHEMA IF EXISTS {_quote(SCHEMA)} CASCADE'))
        await db.execute(text(f'CREATE SCHEMA {_quote(SCHEMA)}'))
        # public 必须留在 search_path 里：pg_trgm 的 gin_trgm_ops 操作符类装在 public，
        # 而 customer 带 trgm GIN 索引；专用 schema 排在最前，非限定表名仍落在它里面。
        await db.execute(text(f'SET LOCAL search_path TO {_quote(SCHEMA)}, public'))
        conn = await db.connection()
        await conn.run_sync(
            lambda sync_conn: Base.metadata.create_all(sync_conn, tables=tables, checkfirst=False)
        )
        try:
            yield db
        finally:
            await db.rollback()


@pytest.mark.asyncio
async def test_json_restore_roundtrip_keeps_rows_and_primary_keys(isolated_schema):
    from fastapi_app.services.backup.json_backup import restore_legacy_json

    db = isolated_schema

    async def _public_counts() -> dict[str, int]:
        """public 同名表的行数——用来证明本次往返没有碰到 public 里的数据。"""
        counts: dict[str, int] = {}
        for table in CORE_TABLES:
            counts[table] = (await db.execute(
                text(f'SELECT COUNT(*) FROM public.{_quote(table)}')  # nosec B608 - 表名来自本文件常量
            )).scalar() or 0
        return counts

    # 1) 真实写入三张核心表（显式主键，便于事后逐个比对）
    await db.execute(text(
        'INSERT INTO customer (id, name, status) '
        "VALUES (101, 'G4客户甲', TRUE), (102, 'G4客户乙', TRUE)"
    ))
    await db.execute(text(
        "INSERT INTO supplier (id, name) VALUES (201, 'G4供应商甲')"
    ))
    await db.execute(text(
        'INSERT INTO product (id, name, initial_stock, current_stock) '
        "VALUES (301, 'G4产品甲', 0, 7), (302, 'G4产品乙', 0, 0)"
    ))
    await db.flush()

    before = await _snapshot(db)
    # 隔离自检：专用 schema 里三张表必须是空的（只有本用例刚插入的行）。
    # 若这里混进了别的用例的数据，说明隔离失效 —— 后续"往返后一致"会变成
    # 在与别人数据混跑的表上比对，断言含义不成立，故直接失败并点明原因。
    assert before == {
        'customer': [101, 102],
        'product': [301, 302],
        'supplier': [201],
    }, f'专用 schema 隔离失效（表落到了 public）：{before}'

    # 隔离后置守卫：本次往返只允许在专用 schema 里发生。restore 若将来加一次真
    # commit，`SET LOCAL search_path` 就会失效、语句落回 public（其中 setval 不受事务
    # 保护、回滚不掉），所以把 public 的行数快照也一起比。
    public_before = await _public_counts()

    # 2) 备份载荷（同生产导出结构）
    rows_by_table: dict[str, tuple[list[str], list]] = {}
    for table in CORE_TABLES:
        result = await db.execute(text(f'SELECT * FROM {_quote(table)} ORDER BY id'))  # nosec B608
        columns = list(result.keys())
        rows_by_table[table] = (columns, list(result.mappings().all()))
    payload = _build_payload(db, rows_by_table)
    # 载荷必须能被 JSON 往返（真实备份是落盘字节，不是内存 dict）
    payload = json.loads(json.dumps(payload, ensure_ascii=False))
    for table in CORE_TABLES:
        assert payload['tables'][table]['count'] == len(before[table])

    # 3) 模拟数据丢失：三张表清空
    for table in CORE_TABLES:
        await db.execute(text(f'DELETE FROM {_quote(table)}'))  # nosec B608
    await db.flush()
    assert await _snapshot(db) == {'customer': [], 'product': [], 'supplier': []}

    # 4) 真还原（生产函数本体）
    result = await restore_legacy_json(payload, db)

    assert result['errors'] == [], f'还原不得有错误：{result["errors"]}'
    assert result['database']['status'] == 'ok'
    assert result['total_inserted'] == sum(len(v) for v in before.values())

    # 生产自己的「还原后校验」也必须过：_verify_restored_json 失败时只写
    # verification.overall_pass=False + _verification_failed，**不进 errors**、status 仍是
    # ok —— 只断 errors/status 的话，这条校验链路整段失效本用例照绿（2026-11-18 评审）。
    assert result['verification']['overall_pass'] is True, (
        f"生产还原校验未通过：{result['verification']}"
    )

    # 5) 行数与主键集合必须与备份点完全一致
    after = await _snapshot(db)
    assert after == before, f'还原后主键集合不一致：{before} vs {after}'

    # 隔离后置守卫（2026-11-18 评审）：public 的行数一秒没动，且连接仍在专用 schema 上。
    public_after = await _public_counts()
    assert public_after == public_before, (
        f'本次往返改动了 public 里的表（隔离失效）：{public_before} → {public_after}'
    )
    search_path = (await db.execute(text("SELECT current_setting('search_path')"))).scalar() or ''
    assert SCHEMA in search_path, f'连接已不在专用 schema 上（search_path={search_path}）'

    # 值也要回来（不止主键）：抽查被清空前记录的业务字段
    qty = (await db.execute(text('SELECT current_stock FROM product WHERE id = 301'))).scalar()
    assert qty == 7, '还原必须带回业务列，而不是只补主键行'
    name = (await db.execute(text('SELECT name FROM customer WHERE id = 102'))).scalar()
    assert name == 'G4客户乙'
