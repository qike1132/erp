"""数据库性能基线探针（只读）

用途
----
为性能类优化决策提供**实测基线**，替代"经验区间"式猜测。本项目此前所有
性能方案都卡在"无基线无法验收"，本脚本补齐这一环。

测量内容
--------
1. 表规模：行数 / 表大小 / 索引大小（全库）
2. 精确 COUNT(*)：对关键表复核 reltuples 估计是否失真
3. 深分页实测：取各表**最深的真实页**，测量 OFFSET 分页耗时
4. COUNT(*) 成本：optimized_count 想优化的对象
5. Redis 往返延迟：用于判定"加缓存是否真的比查库更快"
6. 服务端关键参数：shared_buffers 等（判断数据能否常驻内存）

判定逻辑
--------
- 若「库总大小 << shared_buffers」→ 全库常驻内存，I/O 不是瓶颈
- 若「最深真实页耗时 < 1 ms」→ 深分页优化无对象
- 若「Redis 往返 >= 小表查询耗时」→ 对小表加缓存是负收益

用法
----
    python scripts/db_baseline_probe.py            # 全部测量
    python scripts/db_baseline_probe.py --sizes    # 仅表规模
    python scripts/db_baseline_probe.py --latency  # 仅延迟

只读，不执行任何写操作（Redis 部分会临时 set/delete 一个探针键）。
凭据从项目根目录 .env 读取，不硬编码。
"""
from __future__ import annotations

import argparse
import asyncio
import re
import statistics
import sys
import time
from pathlib import Path

try:
    import asyncpg
except ImportError:
    print('需要 asyncpg：pip install asyncpg', file=sys.stderr)
    sys.exit(2)

ENV_PATH = Path(__file__).resolve().parent.parent / '.env'
REPEAT = 20


def load_env() -> dict[str, str]:
    """从 .env 读取配置（忽略注释与空行）。"""
    cfg: dict[str, str] = {}
    if not ENV_PATH.exists():
        print(f'未找到 {ENV_PATH}', file=sys.stderr)
        sys.exit(2)
    for line in ENV_PATH.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        k, _, v = line.partition('=')
        cfg[k.strip()] = v.strip()
    return cfg


def build_dsn(cfg: dict[str, str]) -> str:
    return (
        f"postgresql+psycopg://{cfg['DB_USER']}:{cfg['DB_PASSWORD']}"
        f"@{cfg['DB_HOST']}:{cfg['DB_PORT']}/{cfg['DB_NAME']}"
    )


async def timed(conn, sql: str, args=None, repeat: int = REPEAT) -> tuple[float, float]:
    """返回 (中位数 ms, 最大 ms)。重复取样以避开首次执行的计划缓存冷启动。"""
    samples = []
    for _ in range(repeat):
        t0 = time.perf_counter()
        await conn.fetch(sql, *(args or ()))
        samples.append((time.perf_counter() - t0) * 1000)
    return statistics.median(samples), max(samples)


async def report_sizes(conn) -> None:
    print('=' * 78)
    print('【1】表规模 Top 25')
    print('=' * 78)
    rows = await conn.fetch("""
        SELECT c.relname AS t, c.reltuples::bigint AS est,
               pg_total_relation_size(c.oid) AS total,
               pg_indexes_size(c.oid) AS idx
        FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE c.relkind = 'r' AND n.nspname = 'public'
        ORDER BY c.reltuples DESC LIMIT 25
    """)
    print(f"{'table':<38}{'est_rows':>12}{'total_MB':>12}{'idx_MB':>10}")
    for r in rows:
        print(f"{r['t']:<38}{r['est']:>12}"
              f"{r['total'] / 1048576:>12.1f}{r['idx'] / 1048576:>10.1f}")

    r = await conn.fetchrow("""
        SELECT count(*) AS n, pg_database_size(current_database()) AS sz
        FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE c.relkind = 'r' AND n.nspname = 'public'
    """)
    print(f"\n表数量 {r['n']}    库总大小 {r['sz'] / 1048576:.1f} MB")

    print()
    print('【2】服务端关键参数（判断数据能否常驻内存）')
    print('=' * 78)
    for p in ('server_version', 'shared_buffers', 'effective_cache_size',
              'work_mem', 'max_connections'):
        print(f'  {p:<24}{await conn.fetchval(f"SHOW {p}")}')
    db_mb = r['sz'] / 1048576
    sb = await conn.fetchval('SHOW shared_buffers')
    m = re.match(r'(\d+)', str(sb))
    if m:
        sb_mb = int(m.group(1)) / 1048576 if 'MB' in str(sb) else int(m.group(1))
        print(f'\n  → 全库 {db_mb:.1f} MB 占 shared_buffers {sb_mb:.0f} MB 的 '
              f'{db_mb / sb_mb * 100:.2f}%')


async def report_latency(conn) -> None:
    print()
    print('=' * 78)
    print('【3】深分页实测：各表「最深的真实页」')
    print('=' * 78)
    print(f"{'表':<30}{'行数':>8}{'OFFSET':>9}{'中位 ms':>11}{'最大 ms':>10}")
    for table, col in (
        ('order', 'order_date'),
        ('customer_sampling_project', 'updated_at'),
        ('customer_sampling_part', 'id'),
        ('inventory_log', 'id'),
        ('audit_log', 'id'),
    ):
        total = await conn.fetchval(f'SELECT count(*) FROM "{table}"')
        off = max(0, total - 20)
        med, mx = await timed(
            conn,
            f'SELECT * FROM "{table}" ORDER BY {col} DESC OFFSET $1 LIMIT 20',
            (off,),
        )
        print(f'{table:<30}{total:>8}{off:>9}{med:>11.3f}{mx:>10.3f}')

    print()
    print('=' * 78)
    print('【4】COUNT(*) 全表计数成本')
    print('=' * 78)
    print(f"{'表':<30}{'中位 ms':>11}{'最大 ms':>10}")
    for t in ('order', 'audit_log', 'inventory_log',
              'customer_sampling_part', 'product'):
        med, mx = await timed(conn, f'SELECT count(*) FROM "{t}"')
        print(f'{t:<30}{med:>11.3f}{mx:>10.3f}')


async def report_redis() -> None:
    print()
    print('=' * 78)
    print('【5】Redis 往返延迟（对照：加缓存是否真能降延迟）')
    print('=' * 78)
    cfg = load_env()
    url = cfg.get('REDIS_CACHE_URL')
    if not url:
        print('  未配置 REDIS_CACHE_URL，跳过')
        return
    try:
        import redis.asyncio as aioredis
    except ImportError:
        print('  未安装 redis 客户端，跳过')
        return
    r = aioredis.from_url(url)
    try:
        await r.ping()
    except Exception as e:
        print(f'  Redis 连接失败: {type(e).__name__}: {e}')
        return
    try:
        for _ in range(5):
            await r.get('__baseline_probe__')
        s = []
        for _ in range(50):
            t0 = time.perf_counter()
            await r.get('__baseline_probe__')
            s.append((time.perf_counter() - t0) * 1000)
        print(f"  {'GET miss':<24}{statistics.median(s):>11.3f}{max(s):>10.3f}")
        await r.set('__baseline_probe__', 'x' * 512)
        s = []
        for _ in range(50):
            t0 = time.perf_counter()
            await r.get('__baseline_probe__')
            s.append((time.perf_counter() - t0) * 1000)
        await r.delete('__baseline_probe__')
        print(f"  {'GET hit (512B)':<24}{statistics.median(s):>11.3f}{max(s):>10.3f}")
    finally:
        await r.aclose()


async def main() -> None:
    ap = argparse.ArgumentParser(description='数据库性能基线探针（只读）')
    ap.add_argument('--sizes', action='store_true', help='仅表规模')
    ap.add_argument('--latency', action='store_true', help='仅延迟测量')
    args = ap.parse_args()
    only = args.sizes or args.latency

    conn = await asyncpg.connect(build_dsn(load_env()))
    try:
        if not only or args.sizes:
            await report_sizes(conn)
        if not only or args.latency:
            await report_latency(conn)
        if not only:
            await report_redis()
    finally:
        await conn.close()


if __name__ == '__main__':
    asyncio.run(main())
