# tests/test_openapi_snapshot_freshness.py
"""回归锁: openapi.json 快照过期时，契约门禁必须判红。

背景: 生成器只读 frontend-vite/openapi.json。若后端改了 schema 而没人重导快照，
前端类型会无声地停留在旧契约上（假绿）。本测试钉住 --snapshot 能检出这种过期。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "check_openapi_frontend_alignment.py"


def _run(args: list[str]) -> subprocess.CompletedProcess:
    # 强制子进程按 UTF-8 写管道：Windows 本地码页（GBK）下 encoding="utf-8" 严格解码会炸，
    # 中文断言串 '一致' 一并失效。CI(Linux) 本就 UTF-8，此设置无害。
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, encoding="utf-8", env=env, cwd=str(ROOT),
    )


def test_snapshot_fresh_passes(tmp_path: Path) -> None:
    # 走 CI 的真实路径：现算 app.openapi() 与已导出的快照文件比对（不传 --openapi）
    snap = tmp_path / "snap.json"
    live = _run(["--export", str(snap)])
    assert live.returncode == 0, live.stderr
    r = _run(["--snapshot", str(snap)])
    assert r.returncode == 0, r.stdout + r.stderr
    assert "一致" in r.stdout


def test_snapshot_stale_fails(tmp_path: Path) -> None:
    snap = tmp_path / "snap.json"
    live = _run(["--export", str(snap)])
    assert live.returncode == 0, live.stderr
    stale = json.loads(snap.read_text(encoding="utf-8"))
    stale["paths"]["/__drift_probe__"] = {"get": {"responses": {"200": {"description": "x"}}}}
    (tmp_path / "stale.json").write_text(json.dumps(stale, ensure_ascii=False), encoding="utf-8")
    r = _run(["--snapshot", str(tmp_path / "stale.json")])
    assert r.returncode == 1, r.stdout + r.stderr
    assert "过期" in r.stdout or "不一致" in r.stdout
