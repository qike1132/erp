"""P0-3：commit 失败必须留下 Prometheus 计数 + 结构化日志，且异常仍向上抛。

背景：FastAPI 0.106+ 的依赖收尾发生在响应发送之后，commit 失败时客户端已经拿到
成功响应 —— 没有指标就只能靠日志人肉发现「静默丢数据」。
"""
import logging
from types import SimpleNamespace

import pytest
from prometheus_client import REGISTRY
from sqlalchemy.exc import SQLAlchemyError

from fastapi_app.core import database

_METRIC = "db_commit_failures_total"


class _Session:
    """commit 抛 SQLAlchemyError、rollback 正常的假会话。"""

    def __init__(self, fail_commit: bool = True):
        self.fail_commit = fail_commit
        self.commits = 0
        self.rollbacks = 0

    async def commit(self):
        self.commits += 1
        if self.fail_commit:
            raise SQLAlchemyError("模拟提交失败")

    async def rollback(self):
        self.rollbacks += 1


class _Factory:
    """database._AsyncSessionLocal 的替身（async_sessionmaker 只需支持 async with）。"""

    def __init__(self, session):
        self._session = session

    def __call__(self):
        return self

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *exc_info):
        return False


def _install(monkeypatch, session):
    async def _noop():
        return None

    monkeypatch.setattr(database, "ensure_engine_for_current_loop", _noop)
    monkeypatch.setattr(database, "_AsyncSessionLocal", _Factory(session))


def _sample() -> float:
    value = REGISTRY.get_sample_value(_METRIC)
    return 0.0 if value is None else value


async def test_commit_failure_counts_and_reraises(monkeypatch, caplog):
    session = _Session()
    _install(monkeypatch, session)
    request = SimpleNamespace(
        state=SimpleNamespace(request_id="req-p0-3-fixed"),
        url=SimpleNamespace(path="/api/v1/orders"),
    )
    before = _sample()

    agen = database.get_async_db(request)
    assert await agen.__anext__() is session
    with caplog.at_level(logging.ERROR, logger="fastapi_app.core.database"):
        with pytest.raises(SQLAlchemyError):
            await agen.__anext__()

    # 指标 +1
    assert _sample() == before + 1
    # 回滚后异常仍向上抛（调用方必须能看到失败）
    assert session.commits == 1
    assert session.rollbacks == 1

    record = caplog.records[-1]
    assert record.levelno == logging.ERROR
    message = record.getMessage()
    assert "req-p0-3-fixed" in message
    assert "/api/v1/orders" in message
    # 结构化字段（extra=）：request_id / db_name / path
    assert record.request_id == "req-p0-3-fixed"
    assert record.db_name == "erp_system"
    assert record.path == "/api/v1/orders"


async def test_commit_failure_without_request_still_logs(monkeypatch, caplog):
    """无参直调（main.py:345/:359 等 `async for` 调用方）不能因 request=None 而炸。"""
    session = _Session()
    _install(monkeypatch, session)
    agen = database.get_async_db()
    assert await agen.__anext__() is session
    with caplog.at_level(logging.ERROR, logger="fastapi_app.core.database"):
        with pytest.raises(SQLAlchemyError):
            await agen.__anext__()
    assert "request_id=None" in caplog.records[-1].getMessage()


def test_request_param_is_recognized_by_fastapi():
    """request 形参必须被 FastAPI 认作 Request 注入点。

    一旦退化成 Body/查询参数，所有 `Depends(get_async_db)` 的端点都会 422 ——
    这是给共享依赖加参数时最容易踩的坑，固化为回归测试。
    """
    from fastapi.dependencies.utils import get_dependant

    dependant = get_dependant(path="/probe", call=database.get_async_db)
    assert dependant.request_param_name == "request"
    assert dependant.body_params == []
    assert dependant.query_params == []


def test_dependency_end_to_end_returns_200(monkeypatch):
    """真实 app 内 `Depends(get_async_db)` 仍是 200（不是 422/500）。"""
    from fastapi import Depends, FastAPI, Request
    from fastapi.testclient import TestClient

    session = _Session(fail_commit=False)
    _install(monkeypatch, session)
    app = FastAPI()

    @app.get("/probe")
    async def probe(request: Request, db=Depends(database.get_async_db)):
        return {"injected": isinstance(request, Request)}

    response = TestClient(app).get("/probe")
    assert response.status_code == 200, response.text
    assert response.json() == {"injected": True}


def test_pool_config_includes_pool_recycle(monkeypatch):
    """P0-10：pool_recycle 必须真的进 _get_pool_config()（此前全仓 0 命中）。"""
    monkeypatch.delenv("DB_POOL_RECYCLE", raising=False)
    assert database._get_pool_config()["pool_recycle"] == 1800
    monkeypatch.setenv("DB_POOL_RECYCLE", "600")
    assert database._get_pool_config()["pool_recycle"] == 600
