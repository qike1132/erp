"""Unit tests for pg_standalone_013 timezone migration.

The migration converts TIMESTAMP WITHOUT TIME ZONE columns (which stored
naive UTC values via ``datetime.now(UTC).replace(tzinfo=None)``) to
TIMESTAMP WITH TIME ZONE.

This test ensures the generated DDL contains ``AT TIME ZONE 'UTC'``,
which is the only thing preventing silent data corruption of all
historical timestamps (PostgreSQL would otherwise assume naive values
are in the *session local timezone*).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

MIGRATION_PATH = (
    Path(__file__).resolve().parent.parent
    / "migrations"
    / "versions"
    / "pg_standalone_013_convert_datetime_to_timezone_aware.py"
)


def _load_migration_module():
    """Dynamically load the migration module (not on the default PYTHONPATH)."""
    spec = importlib.util.spec_from_file_location(
        "pg_standalone_013_convert_datetime_to_timezone_aware",
        MIGRATION_PATH,
    )
    assert spec is not None and spec.loader is not None, f"Cannot locate migration at {MIGRATION_PATH}"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _CaptureOps:
    """Stub for alembic ``op`` that records every DDL string passed to ``op.execute``."""

    def __init__(self):
        self.executed: list[str] = []

    def execute(self, sql: str) -> None:
        self.executed.append(sql)

    # --- quote helpers are unused by the fixed migration but kept defensively ---
    @staticmethod
    def quote(value: str) -> str:  # pragma: no cover - alembic op doesn't actually have this
        return '"' + value.replace('"', '""') + '"'


class TestMigrationTimezoneSanity:
    def test_migration_module_loads_and_has_columns_list(self):
        mod = _load_migration_module()
        assert hasattr(mod, "_COLUMNS"), "_COLUMNS list missing"
        assert len(mod._COLUMNS) > 50, "Expected many datetime columns to be converted"
        # A couple of representative tables should be present:
        tables = {t for t, _ in mod._COLUMNS}
        assert "order" in tables, "order table should be migrated"
        assert "purchase_order" in tables, "purchase_order table should be migrated"
        assert "modification_log" in tables, "audit/modification_log table should be migrated"

    def test_upgrade_generates_at_time_zone_utc_for_every_column(self):
        mod = _load_migration_module()
        capture = _CaptureOps()
        # Temporarily swap the alembic op with our capture:
        original_op = getattr(mod, "op", None)
        mod.op = capture
        try:
            mod.upgrade()
        finally:
            if original_op is not None:
                mod.op = original_op

        assert len(capture.executed) == len(mod._COLUMNS), (
            f"Expected 1 ALTER per column ({len(mod._COLUMNS)}), got {len(capture.executed)}"
        )
        for (table, column), sql in zip(mod._COLUMNS, capture.executed, strict=False):
            assert sql.count("ALTER TABLE") == 1, f"Bad DDL shape for {table}.{column}: {sql}"
            assert "ALTER COLUMN" in sql, f"Missing ALTER COLUMN for {table}.{column}: {sql}"
            assert "TIMESTAMP WITH TIME ZONE" in sql, f"Wrong target type for {table}.{column}: {sql}"
            # THE CRITICAL ASSERTION: without AT TIME ZONE 'UTC' all history is shifted.
            assert "AT TIME ZONE 'UTC'" in sql, (
                f"Migration DDL for {table}.{column} is missing AT TIME ZONE 'UTC'.\n"
                f"Generated DDL: {sql}\n"
                f"Without this clause, Postgres interprets naive stored values in the "
                f"session local timezone (e.g. Asia/Shanghai = UTC+8), silently "
                f"shifting every historical timestamp."
            )
            # Identifier quoting should be present (double quotes on Postgres identifiers):
            assert f'"{table}"' in sql, f"Table identifier not quoted in: {sql}"
            assert f'"{column}"' in sql, f"Column identifier not quoted in: {sql}"

    def test_downgrade_also_uses_at_time_zone_utc(self):
        """Going back down must also preserve value semantics (UTC → naive UTC)."""
        mod = _load_migration_module()
        capture = _CaptureOps()
        original_op = getattr(mod, "op", None)
        mod.op = capture
        try:
            mod.downgrade()
        finally:
            if original_op is not None:
                mod.op = original_op

        assert len(capture.executed) == len(mod._COLUMNS)
        for sql in capture.executed:
            assert "TIMESTAMP WITHOUT TIME ZONE" in sql, f"Wrong downgrade target type: {sql}"
            assert "AT TIME ZONE 'UTC'" in sql, (
                f"Downgrade DDL missing AT TIME ZONE 'UTC' — values would shift on rollback.\n"
                f"Generated DDL: {sql}"
            )

    def test_helper_q_properly_escapes_double_quotes(self):
        mod = _load_migration_module()
        # Sanity check the identifier quoting helper (if future identifiers ever
        # contain quotes; today none do, but defensive coverage is cheap).
        assert hasattr(mod, "_q"), "_q helper should exist for identifier quoting"
        assert mod._q("simple") == '"simple"'
        assert mod._q('weird"name') == '"weird""name"', "Embedded quote should be doubled per SQL standard"

    def test_sample_order_columns_upgrade_sql_matches_expected_pattern(self):
        """Exact-content check for a representative known-good ALTER."""
        mod = _load_migration_module()
        capture = _CaptureOps()
        original_op = getattr(mod, "op", None)
        mod.op = capture
        try:
            mod.upgrade()
        finally:
            if original_op is not None:
                mod.op = original_op

        order_idx = next(i for i, (t, _) in enumerate(mod._COLUMNS) if t == "order")
        order_sql = capture.executed[order_idx]
        # Representative DDL for "order"."order_date" (or whichever order-column comes first):
        assert order_sql.startswith('ALTER TABLE "order" ALTER COLUMN '), order_sql
        assert order_sql.endswith("USING \"order_date\" AT TIME ZONE 'UTC'") or "AT TIME ZONE 'UTC'" in order_sql
