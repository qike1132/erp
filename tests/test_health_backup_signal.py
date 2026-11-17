"""备份可观测性:/api/health 的 backup 信号 + backup_freshness 助手。

打桩遵循 test_backup_validation_helpers 的历史教训:用真实临时目录 + 真实 .zip
产物(生产者 records.list_backup_files 只认 filename/size,伪造返回形状会漏检)。
"""
from __future__ import annotations

import os
import time
import zipfile
from pathlib import Path

import pytest

from fastapi_app.services.backup import freshness, records


@pytest.fixture()
def backup_dir(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setattr(records, "BACKUP_DIR", tmp_path)
    return tmp_path


def _make_backup(d: Path, name: str, age_hours: float) -> Path:
    p = d / name
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("manifest.json", "{}")
    ts = time.time() - age_hours * 3600
    os.utime(p, (ts, ts))
    return p


class TestBackupFreshness:
    def test_recent_backup_is_ok(self, backup_dir: Path) -> None:
        _make_backup(backup_dir, "erp_auto_daily_20260928_1000.zip", age_hours=3)
        r = freshness.backup_freshness()
        assert r["ok"] is True
        assert 2.5 < r["age_hours"] < 3.5
        assert r["last_at"] is not None

    def test_stale_beyond_threshold_is_not_ok(self, backup_dir: Path) -> None:
        _make_backup(backup_dir, "erp_auto_daily_20260926_0200.zip", age_hours=30)
        r = freshness.backup_freshness()
        assert r["ok"] is False
        assert r["age_hours"] > 25

    def test_within_threshold_boundary_ok(self, backup_dir: Path) -> None:
        _make_backup(backup_dir, "erp_auto_daily_20260927_0200.zip", age_hours=24)
        assert freshness.backup_freshness()["ok"] is True

    def test_custom_threshold(self, backup_dir: Path) -> None:
        _make_backup(backup_dir, "erp_auto_daily_20260927_0200.zip", age_hours=10)
        assert freshness.backup_freshness(threshold_hours=5)["ok"] is False
        assert freshness.backup_freshness(threshold_hours=20)["ok"] is True

    def test_newest_file_wins(self, backup_dir: Path) -> None:
        _make_backup(backup_dir, "erp_auto_daily_20260920_0200.zip", age_hours=100)
        _make_backup(backup_dir, "erp_auto_daily_20260928_1600.zip", age_hours=1)
        r = freshness.backup_freshness()
        assert r["ok"] is True
        assert r["age_hours"] < 2

    def test_non_backup_named_files_are_ignored(self, backup_dir: Path) -> None:
        """命名约定之外的文件(演练/临时件)不计入新鲜度——用真实生产者判定。"""
        _make_backup(backup_dir, "scratch.zip", age_hours=0)
        r = freshness.backup_freshness()
        assert r["ok"] is False
        assert r["age_hours"] is None

    def test_no_files_is_not_ok(self, backup_dir: Path) -> None:
        r = freshness.backup_freshness()
        assert r["ok"] is False
        assert r["age_hours"] is None
        assert r["last_at"] is None

    def test_scan_error_is_not_ok_and_never_raises(self, backup_dir: Path, monkeypatch) -> None:
        def _boom() -> list:
            raise OSError("disk error")

        monkeypatch.setattr(records, "list_backup_files", _boom)
        r = freshness.backup_freshness()
        assert r["ok"] is False
        assert r["age_hours"] is None


class TestBackupSignalComposition:
    """/api/health 的 backup 块组合逻辑(不打真 app)。

    不在此处做 HTTP 级集成断言:本仓库 app 的 DB/Redis 客户端绑定在首个 event loop 上,
    整套混跑后再新起 loop 打真 app 必现 "Event loop is closed" —— 是该测试基建的既有
    限制,与本改动无关。端点真实取值已在实机上由 backup_signal 直接验证
    ({'ok': True, 'age_hours': 7.86, 'arq_ok': True});此处锁定组合语义与接线。
    """

    @staticmethod
    def _patch(monkeypatch, fresh: dict, arq_ok: bool | Exception):
        from fastapi_app.core import arq_app
        from fastapi_app.services.backup import freshness as _fresh

        monkeypatch.setattr(_fresh, "backup_freshness", lambda *a, **k: fresh)

        async def _probe(timeout: float = 1.0) -> bool:
            if isinstance(arq_ok, Exception):
                raise arq_ok
            return arq_ok

        monkeypatch.setattr(arq_app, "probe_worker_health_isolated", _probe)

    def _signal(self):
        import asyncio

        from fastapi_app.core.health import _backup_signal

        return asyncio.run(_backup_signal())

    def test_fresh_and_arq_online_is_ok(self, monkeypatch) -> None:
        self._patch(monkeypatch, {"ok": True, "age_hours": 3.0, "last_at": "x"}, True)
        r = self._signal()
        assert r == {"ok": True, "age_hours": 3.0, "arq_ok": True}

    def test_arq_offline_makes_overall_not_ok(self, monkeypatch) -> None:
        """ARQ 掉线即使产物还新鲜也判异常 —— 备份即将停摆。"""
        self._patch(monkeypatch, {"ok": True, "age_hours": 3.0, "last_at": "x"}, False)
        r = self._signal()
        assert r["ok"] is False
        assert r["arq_ok"] is False
        assert r["age_hours"] == 3.0

    def test_stale_backup_makes_overall_not_ok(self, monkeypatch) -> None:
        self._patch(monkeypatch, {"ok": False, "age_hours": 40.0, "last_at": "x"}, True)
        r = self._signal()
        assert r["ok"] is False
        assert r["arq_ok"] is True

    def test_probe_exception_degrades_to_not_ok(self, monkeypatch) -> None:
        """探测自身抛异常不得让健康端点炸掉。"""
        self._patch(monkeypatch, {"ok": True, "age_hours": 1.0, "last_at": "x"}, RuntimeError("boom"))
        r = self._signal()
        assert r["ok"] is False
        assert r["arq_ok"] is False

    def test_keys_contract(self, monkeypatch) -> None:
        self._patch(monkeypatch, {"ok": True, "age_hours": None, "last_at": None}, True)
        assert set(self._signal()) == {"ok", "age_hours", "arq_ok"}


async def test_health_route_wires_backup_block(monkeypatch) -> None:
    """backup 块必须在建缓存之前算好并进入缓存的 internal_data。

    P1-14 起走带预算的包装（``_backup_signal_bounded``），故此前的源码文本断言
    改为行为断言：只要 backup 块真的进了响应与缓存，中间经过哪个函数都成立。
    """
    from fastapi_app.core import health

    async def _backup():
        return {"ok": True, "age_hours": 0.5, "arq_ok": True}

    async def _db() -> bool:
        return True

    async def _redis() -> bool:
        return True

    monkeypatch.setattr(health, "_db_healthy", _db)
    monkeypatch.setattr(health, "_redis_healthy", _redis)
    monkeypatch.setattr(health, "_backup_signal", _backup)
    monkeypatch.setattr(health, "_audit_retention_signal", lambda: {"ok": True})
    monkeypatch.setattr(
        health, "_numbering_audit_retention_signal", lambda: {"ok": True})

    saved = dict(health._health_cache)
    try:
        payload = await health._build_fresh_health(None, [], include_internal=True)
        cached = dict(health._health_cache["internal_data"] or {})
    finally:
        health._health_cache.clear()
        health._health_cache.update(saved)

    assert payload["backup"]["ok"] is True
    assert cached["backup"]["ok"] is True, "backup 块没进缓存 → 后续请求看不到备份链状态"
    # P1-14：各段耗时随缓存一起暴露，慢在哪一段可直接读
    assert {"db", "redis", "backup"} <= set(payload["checks"]["probe_ms"])
