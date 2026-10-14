"""一次性数据修正：把批量出货写错的 stockout_date 回退 8 小时。

背景（2026-10-14 事故）：`stock_out.stockout_date` 是 timestamptz，报表用
``to_char(..., 'YYYY-MM-DD HH24:MI')`` 在会话时区 Asia/Shanghai 下渲染。
`stock_out_service._create_stockout_records` 旧实现把
``_parse_date_preserve_time`` 返回的**北京墙钟** naive 值 ``.replace(tzinfo=UTC)``，
等于把它当 UTC，再按 +8 渲染 → 出货时间晚 8 小时（SO-20261014-0001：实际 11:20，
报表 19:20）。代码侧已在 2b928da1 修复；本脚本只修历史数据。

判定口径（精确，不靠「差 8 小时」猜）：
  出错行把「所选日期 + 创建时的北京时分」当 UTC 存，故
  ``to_char(stockout_date AT TIME ZONE 'UTC', 'HH24:MI')`` 恒等于
  ``to_char(updated_at AT TIME ZONE 'Asia/Shanghai', 'HH24:MI')``。
  正确行两者的时分恒差 8 小时（= 480 分钟，永不为 0），不会命中；
  时分相等只可能是「整日偏移」，即本 bug 的签名。
  注意判据只看时分、不看日期：用户若选了非当天日期，整时间戳会差整数天，
  但时分签名仍然成立（2026-10-10 SO-20261010-0004 就是这样一条）。
  `updated_at IS NULL` 的行无法判定，只报告、不修改。

修正动作：``stockout_date = stockout_date - interval '8 hours'``（单事务）。

用法（必须从仓库根目录运行）：
  python scripts/fix_stockout_date_timezone_20261014.py            # dry-run，只报告
  python scripts/fix_stockout_date_timezone_20261014.py --execute  # 备份后执行
  # --execute 需显式授权写生产库：ERP_ALLOW_PROD_WRITE=1 或 --allow-prod-write
"""
import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

_HERE = Path(__file__).resolve()
sys.path.insert(0, str(_HERE.parent))       # scripts/：_prod_write_guard
sys.path.insert(0, str(_HERE.parents[1]))   # 仓库根：fastapi_app

from sqlalchemy import text

_CANDIDATE_SQL = """
SELECT id, stockout_no, stockout_date, updated_at, customer, quantity,
       (stockout_date AT TIME ZONE 'UTC') AS utc_wall,
       (updated_at AT TIME ZONE 'Asia/Shanghai') AS bj_wall
FROM stock_out
WHERE updated_at IS NOT NULL
  AND to_char(stockout_date AT TIME ZONE 'UTC', 'HH24:MI')
      = to_char(updated_at AT TIME ZONE 'Asia/Shanghai', 'HH24:MI')
ORDER BY id
"""

_NULL_UPDATED_SQL = "SELECT count(*) FROM stock_out WHERE updated_at IS NULL"
_TOTAL_SQL = "SELECT count(*) FROM stock_out"


async def main(execute: bool) -> int:
    if execute:
        from _prod_write_guard import require_prod_write_consent
        require_prod_write_consent(
            "把批量出货写错的 stockout_date 回退 8 小时",
            hint='误操作可依据 backups/ 下的 JSON 备份手工恢复',
        )

    from fastapi_app.core.database import (
        ensure_engine_for_current_loop,
        require_async_session_local,
    )

    await ensure_engine_for_current_loop()
    session_factory = require_async_session_local()

    async with session_factory() as db:
        total = int((await db.execute(text(_TOTAL_SQL))).scalar() or 0)
        null_updated = int((await db.execute(text(_NULL_UPDATED_SQL))).scalar() or 0)
        rows = list((await db.execute(text(_CANDIDATE_SQL))).all())

        print(f'stock_out 总行数：{total}')
        print(f'updated_at 为空（无法判定，跳过）：{null_updated}')
        print(f'命中「UTC 墙钟 == 创建北京墙钟」的待修正行：{len(rows)}')
        for r in rows:
            print(
                f'  - #{r.id} {r.stockout_no} 客户={r.customer} 数量={r.quantity} '
                f'现值={r.stockout_date} → 修正后={r.stockout_date} - 8h'
                f'（UTC墙钟={r.utc_wall} / 创建北京墙钟={r.bj_wall}）'
            )
        if not rows:
            print('无待修正行，无需处理')
            return 0
        if not execute:
            print('\n[dry-run] 未做任何修改。确认无误后加 --execute 执行。')
            return 0

        backup_dir = _HERE.parents[1] / 'backups'
        backup_dir.mkdir(exist_ok=True)
        backup_path = backup_dir / (
            f'stockout_date_tz_backup_{datetime.now().strftime("%Y%m%d-%H%M%S")}.json'
        )
        backup_path.write_text(json.dumps({
            'schema_version': 1,
            'cleaned_at': datetime.now().isoformat(),
            'reason': 'batch stockout stored Beijing wall-clock as UTC (+8h shift)',
            'rows': [
                {
                    'id': r.id,
                    'stockout_no': r.stockout_no,
                    'stockout_date_before': str(r.stockout_date),
                    'updated_at': str(r.updated_at),
                    'customer': r.customer,
                    'quantity': r.quantity,
                }
                for r in rows
            ],
        }, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'备份已写入：{backup_path}')

        ids = [r.id for r in rows]
        result = await db.execute(
            text(
                "UPDATE stock_out SET stockout_date = stockout_date - interval '8 hours' "
                "WHERE id = ANY(:ids)"
            ),
            {'ids': ids},
        )
        await db.commit()
        print(f'已修正 {result.rowcount or 0} 行（事务已提交）')

    try:
        from fastapi_app.core.redis_wrapper import safe_delete_pattern
        deleted = await safe_delete_pattern('*stockout_logs*', context='出货时间修正后清缓存')
        print(f'出货流水缓存已清：{deleted} 个键')
    except Exception as cache_err:  # noqa: BLE001 - 缓存清理失败不影响已提交数据
        print(f'警告：缓存清理失败（{cache_err}）；报表缓存 TTL 30s 会兜底。')
    return 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='修正批量出货 stockout_date 的 +8 小时时区偏移')
    parser.add_argument('--execute', action='store_true', help='真正执行修正（默认 dry-run）')
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.execute)))
