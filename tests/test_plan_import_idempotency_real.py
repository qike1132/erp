"""A2 真库重放测试：同一 job 重试后 staging 行数不变。"""
import openpyxl
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from fastapi_app.tasks import plan_tasks


def _make_xlsx(path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["客户", "产品", "条码", "数量", "日期", "备注"])
    ws.append(["C1", "P1", "B1", 10, "2026-10-22", ""])
    wb.save(path)
    wb.close()


@pytest.mark.asyncio
async def test_real_replay_does_not_duplicate_rows(test_engine, tmp_path, monkeypatch):
    sync_url = test_engine.url.render_as_string(hide_password=False).replace(
        "+asyncpg", "+psycopg"
    )
    sync_engine = create_engine(sync_url)
    Session = sessionmaker(bind=sync_engine)
    monkeypatch.setattr(
        "fastapi_app.tasks.batch_tasks._is_allowed_upload_path", lambda p: True
    )

    path = tmp_path / "plans.xlsx"
    _make_xlsx(path)
    r1 = plan_tasks._run_import_plans_impl(
        str(path), 1, "job-real-1", session_factory=Session
    )
    _make_xlsx(path)  # 首次成功后临时文件被删，重放前重建
    r2 = plan_tasks._run_import_plans_impl(
        str(path), 1, "job-real-1", session_factory=Session
    )

    with Session() as s:
        n = s.execute(
            text("SELECT COUNT(*) FROM staging_purchase_plan WHERE upload_batch_id = :b"),
            {"b": r1["batch_id"]},
        ).scalar()
    sync_engine.dispose()

    assert r1["batch_id"] == r2["batch_id"]
    assert n == 1
