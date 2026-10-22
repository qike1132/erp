"""出货同步历史回填（默认 dry-run）。

只写 shipment_records（幂等 upsert，按 shipment_no），不碰业务表。
用法：
    python scripts/backfill_shipment_records.py --from 2026-10-08 --to 2026-10-21
    python scripts/backfill_shipment_records.py --from 2026-10-08 --to 2026-10-21 --apply
"""
from __future__ import annotations

import argparse
from datetime import date, timedelta


def parse_args(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description="回填 shipment_records（默认 dry-run）")
    parser.add_argument("--from", dest="start", required=True, type=date.fromisoformat)
    parser.add_argument("--to", dest="end", required=True, type=date.fromisoformat)
    parser.add_argument(
        "--apply", dest="dry_run", action="store_false", default=True,
        help="实际写库；不加此参数只做只读统计",
    )
    return parser.parse_args(argv)


def _dates(start: date, end: date):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def run(start: date, end: date, *, dry_run: bool = True, session_factory=None) -> int:
    from sqlalchemy import text

    from fastapi_app.tasks.plan_tasks import _sync_one_date, _SyncSession

    session = (session_factory or _SyncSession)()
    try:
        customers = session.execute(text("SELECT id, name FROM customer")).fetchall()
        customer_id_map = {c.name: c.id for c in customers}
        total = 0
        for day in _dates(start, end):
            stockout_rows = session.execute(
                text(
                    "SELECT COUNT(*) FROM stock_out WHERE DATE(stockout_date) = :d "
                    "AND customer IS NOT NULL AND customer != ''"
                ),
                {"d": day},
            ).scalar() or 0
            shipment_rows = session.execute(
                text("SELECT COUNT(*) FROM shipment_records WHERE shipment_date = :d"),
                {"d": day},
            ).scalar() or 0
            if dry_run:
                print(f"{day}: stock_out={stockout_rows} shipment_records={shipment_rows} (dry-run)")
                continue
            synced = _sync_one_date(session, day, customer_id_map)
            session.commit()
            total += synced
            print(f"{day}: synced={synced}")
        if dry_run:
            print("dry-run：未写入。确认无误后加 --apply 执行。")
        else:
            print(f"完成，写入/更新 {total} 条。")
        return total
    finally:
        session.close()


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    run(args.start, args.end, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
