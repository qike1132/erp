"""M8：批量计划导入重放不得重复插入（原 batch_id 每次重试重新生成）。"""
import pytest

from fastapi_app.tasks import plan_tasks


def test_batch_id_is_stable_for_same_job():
    assert plan_tasks._batch_id_for_job("job-abc-123") == plan_tasks._batch_id_for_job("job-abc-123")
    assert plan_tasks._batch_id_for_job("job-abc-123") != plan_tasks._batch_id_for_job("job-def-456")


@pytest.mark.asyncio
async def test_replay_passes_same_job_id(monkeypatch, tmp_path):
    seen = []

    def _fake_impl(file_path, user_id, job_id):
        seen.append(job_id)
        return {"success": True, "batch_id": plan_tasks._batch_id_for_job(job_id)}

    monkeypatch.setattr(plan_tasks, "_run_import_plans_impl", _fake_impl)
    ctx = {"job_id": "job-abc-123"}
    r1 = await plan_tasks.batch_import_plans_task(ctx, str(tmp_path / "a.xlsx"), "a.xlsx", 1)
    r2 = await plan_tasks.batch_import_plans_task(ctx, str(tmp_path / "a.xlsx"), "a.xlsx", 1)
    assert r1["batch_id"] == r2["batch_id"]
    assert seen == ["job-abc-123", "job-abc-123"]


def test_clear_batch_rows_deletes_then_commits():
    calls = []

    class _FakeSession:
        def execute(self, stmt):
            calls.append(("execute", str(stmt)))

        def commit(self):
            calls.append(("commit", None))

    plan_tasks._clear_batch_rows(_FakeSession(), "job-abc123")
    assert calls[0][0] == "execute"
    assert "DELETE FROM staging_purchase_plan" in calls[0][1]
    assert calls[1] == ("commit", None)
