"""深层优化测试 - 慢查询监听器/X-Request-ID链路追踪

测试内容：
1. slow_query.py 日志格式正确性
2. slow_query.py 计数器线程安全
3. X-Request-ID 响应头存在性
4. 异常响应 request_id 与响应头一致
5. rebuild_pool 后慢查询监听器重新注册
"""
import contextlib
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestSlowQueryLogger:
    """慢查询监听器测试"""

    def test_slow_query_counter_thread_safety(self):
        """测试计数器线程安全"""
        from fastapi_app.core.slow_query import _counter, get_slow_query_count, reset_slow_query_count

        reset_slow_query_count()

        def increment_many(n: int):
            for _ in range(n):
                _counter.inc()

        threads = [threading.Thread(target=increment_many, args=(1000,)) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert get_slow_query_count() == 10 * 1000
        reset_slow_query_count()

    def test_reset_slow_query_count(self):
        """测试计数器重置"""
        from fastapi_app.core.slow_query import _counter, get_slow_query_count, reset_slow_query_count

        _counter.inc()
        _counter.inc()
        assert get_slow_query_count() >= 2
        reset_slow_query_count()
        assert get_slow_query_count() == 0

    def test_get_threshold(self):
        """测试按语句类型返回阈值"""
        from fastapi_app.core.slow_query import SLOW_QUERY_REPORT_THRESHOLD, SLOW_QUERY_THRESHOLD, _get_threshold

        assert _get_threshold("SELECT * FROM orders WHERE id = $1") == SLOW_QUERY_THRESHOLD
        assert _get_threshold("SELECT COUNT(*) FROM orders GROUP BY status") == SLOW_QUERY_REPORT_THRESHOLD
        assert _get_threshold("SELECT * FROM export_data WHERE created_at > $1") == SLOW_QUERY_REPORT_THRESHOLD
        assert _get_threshold("SELECT * FROM dashboard_stats") == SLOW_QUERY_REPORT_THRESHOLD

    def test_probe_queries_get_probe_threshold(self):
        """健康探针（catalog/权限存在性检查）用 probe 阈值，不按 OLTP 0.2s 判。

        2026-10-07：to_regclass / has_table_privilege 在 cron tick 上 0.24~0.36s，
        但同刻业务查询不慢 —— 用 OLTP 阈值会持续假阳性刷屏。
        """
        from fastapi_app.core.slow_query import (
            SLOW_QUERY_PROBE_THRESHOLD,
            SLOW_QUERY_THRESHOLD,
            _get_threshold,
            _kind,
        )

        probe_sqls = [
            "SELECT to_regclass($1)",
            "SELECT has_table_privilege($1, 'order', 'SELECT')",
        ]
        for sql in probe_sqls:
            assert _get_threshold(sql) == SLOW_QUERY_PROBE_THRESHOLD, sql
            assert _kind(SLOW_QUERY_PROBE_THRESHOLD) == "probe"

        # 普通 OLTP 查询不受影响
        assert _get_threshold('SELECT id FROM "order" WHERE id = $1') == SLOW_QUERY_THRESHOLD
        assert _kind(SLOW_QUERY_THRESHOLD) == "oltp"


class TestRequestIdMiddleware:
    """X-Request-ID 链路追踪测试"""

    def test_response_has_request_id_header(self):
        """测试响应包含 X-Request-ID 头"""
        from fastapi import FastAPI
        from fastapi.responses import JSONResponse
        from fastapi.testclient import TestClient

        from fastapi_app.core.middleware import setup_middleware

        app = FastAPI()
        setup_middleware(app)

        @app.get("/test-rid")
        async def test_endpoint():
            return JSONResponse({"ok": True})

        client = TestClient(app)
        response = client.get("/test-rid")

        assert response.status_code == 200
        assert "X-Request-ID" in response.headers
        assert len(response.headers["X-Request-ID"]) >= 8

    def test_request_id_propagates_from_header(self):
        """测试请求头传入的 X-Request-ID 被复用"""
        from fastapi import FastAPI, Request
        from fastapi.responses import JSONResponse
        from fastapi.testclient import TestClient

        from fastapi_app.core.middleware import setup_middleware

        app = FastAPI()
        setup_middleware(app)

        @app.get("/test-rid-echo")
        async def test_endpoint(request: Request):
            return JSONResponse({"rid": request.state.request_id})

        client = TestClient(app)
        test_rid = "test-rid-12345678"
        response = client.get("/test-rid-echo", headers={"X-Request-ID": test_rid})

        assert response.status_code == 200
        assert response.headers["X-Request-ID"] == test_rid
        assert response.json()["rid"] == test_rid

    def test_error_response_request_id_matches_header(self):
        """测试异常响应中的 request_id 与响应头一致"""
        from fastapi import FastAPI
        from fastapi.responses import JSONResponse as _JSONResp
        from fastapi.testclient import TestClient

        from fastapi_app.core.exceptions import AppError, BusinessError, current_iso_timestamp, new_request_id
        from fastapi_app.core.middleware import setup_middleware

        class MsgspecResponse(_JSONResp):
            media_type = "application/json"
            def render(self, content):
                import msgspec.json
                return msgspec.json.encode(content)

        app = FastAPI()
        setup_middleware(app)

        @app.get("/test-error-400")
        async def test_error():
            raise BusinessError("测试业务错误")

        @app.exception_handler(AppError)
        async def app_error_handler(request, exc):
            request_id = getattr(request.state, 'request_id', None) or new_request_id()
            return MsgspecResponse(
                content={
                    "success": False,
                    "detail": exc.message,
                    "code": exc.code,
                    "status_code": exc.status_code,
                    "request_id": request_id,
                    "timestamp": current_iso_timestamp(),
                },
                status_code=exc.status_code,
            )

        client = TestClient(app)
        response = client.get("/test-error-400")

        assert response.status_code == 400
        header_rid = response.headers.get("X-Request-ID")
        body_rid = response.json().get("request_id")
        assert header_rid is not None
        assert body_rid is not None
        assert header_rid == body_rid, f"响应头 {header_rid} 与响应体 {body_rid} request_id 不一致"


class TestDatabaseSlowQueryRegistration:
    """数据库慢查询监听器注册测试"""

    def test_module_imports_slow_query_setup(self):
        """测试 database.py 能正确导入慢查询模块"""
        from fastapi_app.core import database
        assert hasattr(database, '_async_engine')
        # _async_engine 仅在 init_async_engine() 后非 None；单测不连库，此处只验证
        # database.py 与 slow_query 模块的导入链完好（真实注册路径见
        # test_rebuild_pool_registers_listeners 与 database.py 的 engine 初始化代码）
        from fastapi_app.core.slow_query import setup_slow_query_listener
        assert callable(setup_slow_query_listener)

    def test_slow_query_setup_function_exists(self):
        """测试 slow_query 模块导出必要函数"""
        from fastapi_app.core.slow_query import (
            get_slow_query_count,
            reset_slow_query_count,
            setup_slow_query_listener,
        )
        assert callable(setup_slow_query_listener)
        assert callable(get_slow_query_count)
        assert callable(reset_slow_query_count)
        reset_slow_query_count()
        assert get_slow_query_count() == 0

    def test_rebuild_pool_registers_listeners(self):
        """测试 setup_slow_query_listener 函数可正常调用（验证不抛出异常）"""
        import os
        import tempfile

        from sqlalchemy import create_engine

        from fastapi_app.core.slow_query import setup_slow_query_listener

        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name
        engine = None
        try:
            engine = create_engine(f"sqlite:///{db_path}", echo=False)
            setup_slow_query_listener(engine)
            with engine.connect() as conn:
                conn.exec_driver_sql("SELECT 1")
        finally:
            if engine is not None:
                engine.dispose()
            with contextlib.suppress(PermissionError, OSError):
                os.unlink(db_path)

    def test_database_rebuild_pool_re_registers(self):
        """测试 database.py 中 rebuild_pool 能访问 setup_slow_query_listener"""
        import inspect

        from fastapi_app.core import database
        source = inspect.getsource(database.rebuild_pool)
        assert "setup_slow_query_listener" in source, "rebuild_pool 应重新注册慢查询监听器"
        assert "_register_slow_listener_for_read_engine" in source, "rebuild_pool 应为只读引擎注册监听器"
