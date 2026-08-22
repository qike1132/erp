"""get_async_read_db 只读副本降级逻辑 - 单元测试

覆盖 P 性能迭代中为"页面加载中"故障修复加入的快速失败/降级：
- 副本连接检出超时（不可达/池耗尽/断连）→ 立即回退主库并归还副本会话
- 副本可用 → 正常产出副本会话，结束后关闭

全部通过 mock 注入，不触发真实数据库/事件循环连接。
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from fastapi_app.core import database


async def _collect_(gen):
    """收集 async generator 产出的全部会话"""
    out = []
    async for s in gen:
        out.append(s)
    return out


class TestGetAsyncReadDbFallback:
    @pytest.mark.asyncio
    async def test_replica_checkout_timeout_falls_back_to_primary(self, monkeypatch, caplog):
        """副本连接检出超时 → 降级主库，并关闭副本会话"""
        fake_replica = AsyncMock()
        fake_replica.execute = AsyncMock(side_effect=TimeoutError())
        fake_replica.close = AsyncMock()

        async def fake_get_async_db():
            yield "primary-session"

        monkeypatch.setattr(database, "_init_read_engine", lambda: None)
        monkeypatch.setattr(database, "_ReadSessionLocal", lambda: fake_replica)
        monkeypatch.setattr(database, "get_async_db", fake_get_async_db)

        with caplog.at_level("WARNING"):
            sessions = await _collect_(database.get_async_read_db())

        # 回退到主库会话
        assert sessions == ["primary-session"]
        # 副本会话已被归还（close）
        fake_replica.close.assert_called_once()
        # 记录降级告警日志
        assert any("只读副本连接不可用" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_empty_primary_fallback_has_no_leak(self, monkeypatch):
        """副本降级后主库无可用会话产出时，不产出会话且副本已归还（无泄漏）"""
        fake_replica = AsyncMock()
        fake_replica.execute = AsyncMock(side_effect=TimeoutError())

        async def fake_get_async_db_empty():
            return
            yield  # 空 field-generator（无主库回退源）

        monkeypatch.setattr(database, "_init_read_engine", lambda: None)
        monkeypatch.setattr(database, "_ReadSessionLocal", lambda: fake_replica)
        monkeypatch.setattr(database, "get_async_db", fake_get_async_db_empty)

        sessions = await _collect_(database.get_async_read_db())
        # 空主库 → 无产量，且副本会话已尝试关闭（无泄漏）
        assert sessions == []
        fake_replica.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_replica_healthy_yields_replica_and_closes(self, monkeypatch):
        """副本健康 → 产出副本会话，结束关闭"""
        fake_replica = AsyncMock()
        fake_replica.execute = AsyncMock(return_value=MagicMock())
        fake_replica.close = AsyncMock()

        monkeypatch.setattr(database, "_init_read_engine", lambda: None)
        monkeypatch.setattr(database, "_ReadSessionLocal", lambda: fake_replica)

        sessions = await _collect_(database.get_async_read_db())

        assert sessions == [fake_replica]
        fake_replica.close.assert_called_once()
