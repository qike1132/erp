"""AUD-06（2026-10-24 审计）回归锁：凡可被按名入队的 ARQ 函数必须在 functions 表。

背景：maintain_logs_task / replica_lag_task / catch_up_daily_crons 曾只在
cron_schedules 里（cron 由 worker 内部直调、不经按名派发），但两个消费方按
``__name__`` 入队——catch_up_daily_crons 对漏跑的日级 cron 补跑（arq_app.py
_DAILY_CRON_NAMES）与 /backup/schedule/trigger 端点（backup/records.py）。
缺注册时 worker 侧 ``self.functions[function_name]`` KeyError →
JobExecutionFailed("function ... not found")：任务永失败、不重试、不经
on_job_end（无终态回写、无死信）——补跑机制静默失效、触发端点假成功。

本锁断言两条不变式：
1. cron_schedules 每个条目的 func 必须已在 WorkerSettings.functions（cron 本身
   不需要，但按名入队消费方只认 functions 表；且 _tracked_job@wraps 保留了
   __name__，注册无副作用）。
2. catch_up_daily_crons 可按名入队的 _DAILY_CRON_NAMES 目标也必须在表里。
"""
from fastapi_app.core import arq_app


def _registered_names() -> set[str]:
    # functions 表的项被 _tracked_job(@wraps) 包装，__name__ 保留原函数名。
    return {f.__name__ for f in arq_app.WorkerSettings.functions}


def test_every_cron_schedule_function_is_registered():
    registered = _registered_names()
    missing = [
        s['name'] for s in arq_app.cron_schedules if s['func'].__name__ not in registered
    ]
    assert not missing, (
        f'cron_schedules 里这些任务未注册进 WorkerSettings.functions：{missing}；'
        f'凡可被 /backup/schedule/trigger 或补跑逻辑按名入队的函数，缺注册会在 '
        f'worker 侧永久失败且无终态回写（AUD-06）'
    )


def test_daily_cron_catchup_targets_are_registered():
    registered = _registered_names()
    # catch_up_daily_crons 对 _DAILY_CRON_NAMES 里记录的 cron 名按名入队对应函数。
    cron_name_to_func = {s['name']: s['func'] for s in arq_app.cron_schedules}
    missing = [
        name for name in sorted(arq_app._DAILY_CRON_NAMES)
        if name in cron_name_to_func and cron_name_to_func[name].__name__ not in registered
    ]
    assert not missing, (
        f'日级 cron 补跑目标未注册：{missing}——worker 停机跨过窗口后补跑会 '
        f'"function not found" 永久失败（AUD-06）'
    )


def test_trigger_endpoint_backed_functions_are_registered():
    """/backup/schedule/trigger 端点按 cron_schedules 条目 func.__name__ 入队，
    全部条目已由 test_every_cron_schedule_function_is_registered 覆盖；这里补一条
    直白断言锁住三个曾经的漏网函数，防有人以「cron 不需要」为由移除注册。"""
    registered = _registered_names()
    for fn_name in ('maintain_logs_task', 'replica_lag_task', 'catch_up_daily_crons'):
        assert fn_name in registered, (
            f'{fn_name} 不在 WorkerSettings.functions：按名入队必永久失败（AUD-06）'
        )
