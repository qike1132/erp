"""P0-4：审批域时钟统一为 naive UTC（同表两套时钟此前相差 8 小时）。"""
import ast
import inspect
from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from fastapi_app.shared_models import approval as approval_mod
from fastapi_app.shared_models.approval import ApprovalLog, ApprovalRequest, _utcnow


def test_updated_at_defaults_use_utc_clock():
    """updated_at 的 default 与 onupdate 必须与同表 request_time/action_time 同源。"""
    for table in (ApprovalRequest.__table__, ApprovalLog.__table__):
        column = table.c.updated_at
        # SQLAlchemy 会给零参可调用对象套一层 ctx 包装（functools.wraps），
        # 用 inspect.unwrap 还原到同一个 _utcnow 函数对象。
        assert inspect.unwrap(column.default.arg) is _utcnow, f"{table.name}.updated_at.default"
        assert inspect.unwrap(column.onupdate.arg) is _utcnow, f"{table.name}.updated_at.onupdate"


def test_no_bare_datetime_now_in_approval_module():
    """approval.py 内不得再出现无参 datetime.now()（本地 wall-clock）。"""
    tree = ast.parse(inspect.getsource(approval_mod))
    offenders = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "now"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "datetime"
            and not node.args
        ):
            offenders.append(node.lineno)
    assert offenders == [], f"approval.py 第 {offenders} 行仍在用本地 wall-clock datetime.now()"


def test_same_operation_timestamps_within_one_minute():
    """同一操作写出的两条记录（申请 + 日志）时间差 < 1 分钟。

    修复前 request_time/action_time 是 UTC、updated_at 是本地 wall-clock，
    同一条记录内部就差 8 小时（同一操作跨表更明显）。
    """
    engine = create_engine("sqlite://")
    ApprovalRequest.__table__.create(engine)
    ApprovalLog.__table__.create(engine)
    try:
        with Session(engine) as session:
            request = ApprovalRequest(order_id=1, requester_id=1, operation_type="edit")
            session.add(request)
            session.flush()
            log = ApprovalLog(approval_request_id=request.id, action="approve")
            session.add(log)
            session.flush()
            stamps = [request.request_time, request.updated_at, log.action_time, log.updated_at]
    finally:
        engine.dispose()

    assert all(s.tzinfo is None for s in stamps), "DB 列是 TIMESTAMP WITHOUT TIME ZONE，必须 naive"
    assert max(stamps) - min(stamps) < timedelta(minutes=1)
    assert abs((request.request_time - request.updated_at).total_seconds()) < 60
    assert abs((log.action_time - log.updated_at).total_seconds()) < 60
    # naive UTC：与 datetime.now(UTC) 同秒级（不是本地 wall-clock）
    assert abs(stamps[0] - datetime.now(UTC).replace(tzinfo=None)) < timedelta(minutes=5)
