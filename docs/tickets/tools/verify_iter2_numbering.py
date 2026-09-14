"""ITER-2 T1/T2 验证：批量取号的原子性与不重号。

三层验证，越往后越强：

1. **SQL 语法** —— 用 pglast（PostgreSQL 自身的解析器）解析两条常量 SQL，
   确保 `ON CONFLICT ... DO UPDATE ... RETURNING` 在目标方言下合法。
   静态检查抓不到 SQL 方言错误，这一层补上。
2. **取号逻辑** —— 用桩替掉 `allocate_sequence_range`，验证编号格式、连续性、
   数量、以及 count<=0 的边界（不打库）。
3. **真实库并发** —— 4 个协程各预留 1000 个号，断言四段号**两两不相交**；
   并验证单号版与批量版混用也不重号。

第 3 层是真的写库，使用测试专用前缀 ``ITERTEST``（与 PO/BH/SO/CG/CS/CSO/CSI
均不冲突），跑完即清理该前缀的计数行，不留痕迹。

用法::

    python docs/tickets/tools/verify_iter2_numbering.py
"""
from __future__ import annotations

import asyncio
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

TEST_PREFIX = 'ITERTEST'
CONCURRENCY = 4
PER_BATCH = 1000

#: SQLAlchemy 绑定参数占位符 :name（pglast 只认 PG 语法，需先替换）
_BIND_RE = re.compile(r':\w+')

_failures: list[str] = []


def check(label: str, ok: bool, detail: str = '') -> None:
    print(f'  [{"PASS" if ok else "FAIL"}] {label}{" — " + detail if detail else ""}')
    if not ok:
        _failures.append(label)


# ---------------------------------------------------------------------------
# 1. SQL 语法（pglast = PostgreSQL 自身的前端）
# ---------------------------------------------------------------------------

def verify_sql_syntax() -> None:
    print('\n[1] SQL 语法（pglast / PostgreSQL 解析器）')
    try:
        from pglast import parse_sql
    except ImportError:
        check('pglast 可用', False, '未安装，跳过该层')
        return

    from fastapi_app.services.numbering_sequence import _ALLOCATE_RANGE_SQL, _ALLOCATE_SQL

    for name, stmt in (('_ALLOCATE_SQL', _ALLOCATE_SQL), ('_ALLOCATE_RANGE_SQL', _ALLOCATE_RANGE_SQL)):
        sql = stmt.text
        # SQLAlchemy 的 :name 是绑定参数占位符，不是 PostgreSQL 语法。
        # pglast 是 PG 自身的解析器，必须先替换成字面量才能验证方言合法性。
        pg_sql = _BIND_RE.sub("'BIND'", sql)
        try:
            parse_sql(pg_sql)
        except Exception as exc:  # noqa: BLE001 - 验证脚本需要把任何解析错误都暴露出来
            check(f'{name} 可被 PG 解析', False, str(exc)[:200])
            continue
        check(f'{name} 可被 PG 解析（方言合法）', True)
        has_returning = 'RETURNING' in sql.upper()
        has_conflict = 'ON CONFLICT' in sql.upper()
        check(f'{name} 含 RETURNING', has_returning)
        check(f'{name} 含 ON CONFLICT', has_conflict)

    range_sql = _ALLOCATE_RANGE_SQL.text
    check(
        '_ALLOCATE_RANGE_SQL 用 :count 参数化递增（非字面量拼接）',
        'last_seq + :count' in range_sql,
    )
    single_sql = _ALLOCATE_SQL.text
    check('_ALLOCATE_SQL 递增固定 +1', 'last_seq + 1' in single_sql)


# ---------------------------------------------------------------------------
# 2. 取号逻辑（桩替 allocate_sequence_range，不打库）
# ---------------------------------------------------------------------------

async def verify_numbering_logic() -> None:
    print('\n[2] 取号逻辑（桩替 allocate_sequence_range）')
    from fastapi_app.services import numbering as nb

    calls: list[tuple] = []

    async def fake_range(prefix, date_str, count, seed=0):
        calls.append((prefix, date_str, count, seed))
        return 900 + 1                       # 起始序号固定为 901

    async def fake_daily_max(db, model, date_field, number_field):
        return 900                           # 种子；此处不依赖真实会话

    original = nb.allocate_sequence_range
    original_max = nb.read_daily_max
    nb.allocate_sequence_range = fake_range
    nb.read_daily_max = fake_daily_max
    try:
        numbers = await nb.generate_number_batch('PO', None, 'order_date', 'order_no', None, 4)
        check('返回 4 个编号', len(numbers) == 4, str(numbers))
        check('起始序号来自 allocate_sequence_range', numbers[0].endswith('-0901'), numbers[0])
        check('批内连续', [n[-4:] for n in numbers] == ['0901', '0902', '0903', '0904'])
        check('格式为 PREFIX-YYYYMMDD-XXXX', numbers[0].split('-')[0] == 'PO' and len(numbers[0].split('-')) == 3)
        check('透传 count 给取号层', calls and calls[0][2] == 4, str(calls))
        check('透传 prefix 给取号层', calls and calls[0][0] == 'PO')

        calls.clear()
        empty = await nb.generate_number_batch('PO', None, 'order_date', 'order_no', None, 0)
        check('count=0 返回空列表且不打库', empty == [] and not calls, f'calls={calls}')

        negative = await nb.generate_number_batch('PO', None, 'order_date', 'order_no', None, -3)
        check('count<0 返回空列表且不打库', negative == [] and not calls)

        # 超过 9999 时不截断（zfill 只补齐）
        nb.allocate_sequence_range = lambda *a, **k: _raise_return(9997)
        big = await nb.generate_number_batch('PO', None, 'order_date', 'order_no', None, 4)
        check('序号超 9999 不截断（仍唯一）', big == [
            f'PO-{big[0].split("-")[1]}-9997', f'PO-{big[0].split("-")[1]}-9998',
            f'PO-{big[0].split("-")[1]}-9999', f'PO-{big[0].split("-")[1]}-10000',
        ], str(big))
    finally:
        nb.allocate_sequence_range = original
        nb.read_daily_max = original_max

    # count 边界由 allocate_sequence_range 自己守
    from fastapi_app.services.numbering_sequence import allocate_sequence_range
    for bad in (0, -1):
        try:
            await allocate_sequence_range(TEST_PREFIX, '19700101', bad)
            check(f'allocate_sequence_range(count={bad}) 应抛 ValueError', False)
        except ValueError:
            check(f'allocate_sequence_range(count={bad}) 抛 ValueError', True)


async def _raise_return(value: int) -> int:
    return value


# ---------------------------------------------------------------------------
# 3. 真实库并发
# ---------------------------------------------------------------------------

async def _cleanup(prefix: str, date_str: str) -> None:
    from sqlalchemy import delete

    from fastapi_app.core.database import get_async_db_context
    from fastapi_app.shared_models.numbering_counter import NumberingCounter

    async with get_async_db_context() as db:
        await db.execute(
            delete(NumberingCounter).where(
                NumberingCounter.prefix == prefix,
                NumberingCounter.number_date == date_str,
            )
        )
        await db.commit()


async def verify_real_db_concurrency() -> None:
    print('\n[3] 真实库并发（4 协程 × 1000 号，断言两两不相交）')
    from fastapi_app.services.numbering_sequence import allocate_sequence, allocate_sequence_range

    date_str = datetime.now(UTC).strftime('%Y%m%d')
    await _cleanup(TEST_PREFIX, date_str)

    try:
        starts = await asyncio.gather(*[
            allocate_sequence_range(TEST_PREFIX, date_str, PER_BATCH) for _ in range(CONCURRENCY)
        ])
        check(f'{CONCURRENCY} 个协程都拿到起始序号', all(isinstance(s, int) for s in starts), str(starts))
        check('起始序号互不相同', len(set(starts)) == CONCURRENCY, str(sorted(starts)))

        ranges = [set(range(s, s + PER_BATCH)) for s in starts]
        pairwise_disjoint = True
        for i in range(len(ranges)):
            for j in range(i + 1, len(ranges)):
                if ranges[i] & ranges[j]:
                    pairwise_disjoint = False
        total = set().union(*ranges)
        check('号段两两不相交（无重号）', pairwise_disjoint)
        check(f'合计 {CONCURRENCY * PER_BATCH} 个号全部唯一', len(total) == CONCURRENCY * PER_BATCH,
              f'实际 {len(total)}')

        # 单号版与批量版混用：接着取 50 个单号 + 一段 50 个号，不得与已有段重叠
        singles = [await allocate_sequence(TEST_PREFIX, date_str) for _ in range(50)]
        batch_start = await allocate_sequence_range(TEST_PREFIX, date_str, 50)
        mixed = set(singles) | set(range(batch_start, batch_start + 50))
        check('单号版与批量版混用无重号', len(mixed) == 100, f'实际 {len(mixed)}')
        check('混用结果与并发段无交集', not (mixed & total))

        # 连续性：并发取号之后，序号水位应恰好被推进到起点之外
        first_start = min(starts)
        check('并发段整体位于计数起点之上', first_start >= 1, f'min(start)={first_start}')
    finally:
        await _cleanup(TEST_PREFIX, date_str)
        print(f'  [done] 已清理测试前缀 {TEST_PREFIX} 的计数行')


async def main() -> int:
    print('=' * 78)
    print('ITER-2 T1/T2 验证：批量取号原子性与不重号')
    print('=' * 78)

    verify_sql_syntax()
    await verify_numbering_logic()
    try:
        await verify_real_db_concurrency()
    except Exception as exc:  # noqa: BLE001 - 验证脚本需要暴露连接失败等环境问题
        check('真实库并发验证可执行', False, f'{type(exc).__name__}: {exc}')

    print('\n' + '=' * 78)
    if _failures:
        print(f'结论：{len(_failures)} 项失败')
        for f in _failures:
            print(f'  - {f}')
        return 1
    print('结论：全部通过 ✅')
    return 0


if __name__ == '__main__':
    raise SystemExit(asyncio.run(main()))
