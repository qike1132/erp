"""M6 运维件：回填脚本默认 dry-run，必须显式 --apply 才写库。"""


def test_backfill_defaults_to_dry_run():
    from scripts.backfill_shipment_records import parse_args

    args = parse_args(["--from", "2026-10-08", "--to", "2026-10-21"])
    assert args.dry_run is True
    assert args.start.isoformat() == "2026-10-08"
    assert args.end.isoformat() == "2026-10-21"


def test_backfill_apply_flag_disables_dry_run():
    from scripts.backfill_shipment_records import parse_args

    args = parse_args(["--from", "2026-10-08", "--to", "2026-10-21", "--apply"])
    assert args.dry_run is False


def test_dry_run_does_not_write(monkeypatch):
    from datetime import date

    from scripts import backfill_shipment_records as bf

    calls = []
    monkeypatch.setattr(
        "fastapi_app.tasks.plan_tasks._sync_one_date", lambda *a: calls.append(1)
    )

    class _Result:
        def fetchall(self):
            return []

        def scalar(self):
            return 0

    class _Session:
        def execute(self, stmt, params=None):
            return _Result()

        def close(self):
            pass

    bf.run(date(2026, 10, 8), date(2026, 10, 9), dry_run=True,
           session_factory=lambda: _Session())
    assert calls == []
