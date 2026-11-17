"""测试库隔离的两半护栏（2026-11-17 上线前审计 P0-2 的回归锁）。

## 这条测试拦哪种出错

P0-2 的成因是**两件事同时缺**：

1. `fastapi_app/tests/` 这棵树没有把 `settings.DATABASE_URL` 重定向到测试库
   （只有根树 `tests/conftest.py::app_on_test_db` 干了这事，且只对 `tests/` 生效）；
2. 因此本树里任何走应用自身引擎的代码，连的都是 `.env` 里那个库（生产机上即生产库）。

修复也是两半，本文件各锁一半：

- `test_settings_point_at_test_db`：**跑测试时 `settings` 的三个库 URL 必须都指向 `*_test`**
  ——夹具被删/被改坏、或有人把 autouse 去掉，这条立刻红。
- `test_gate_flags_app_engine_usage` / `test_gate_passes_clean_tree`：**门禁对
  `get_sync_engine` 这类用法必须变红、对干净文件必须放行** —— 用真实子进程跑
  `scripts/check_test_db_isolation.py`（含 `--json` 契约），不是断言"函数存在"。
  变异检查：把 CONTEXT.md 里 `FORBIDDEN_NAMES` 中的 `get_sync_engine` 删掉，
  本文件第一条用例会红（旧实现 `_real_pg_engine` 用的正是它）。
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import sys
from pathlib import Path

from fastapi_app.core.config import settings

_REPO_ROOT = Path(__file__).resolve().parents[2]
_GATE = _REPO_ROOT / "scripts" / "check_test_db_isolation.py"

# 合成夹具：故意使用应用自身引擎（P0-2 的原形态）
_PROBE_BAD = (
    "from fastapi_app.core.database import get_sync_engine\n"
    "engine = get_sync_engine()\n"
)
# 合成夹具：走硬闸 + 自建引擎（修复后的正确形态）
_PROBE_CLEAN = (
    "from fastapi_app.tests._test_db_guard import resolve_test_db_url\n"
    "url = resolve_test_db_url()\n"
)


def _load_gate_module():
    """把 `scripts/check_test_db_isolation.py` 作为模块加载（不起子进程）。"""
    name = "_check_test_db_isolation_under_test"
    spec = importlib.util.spec_from_file_location(name, _GATE)
    assert spec is not None and spec.loader is not None, f"无法加载门禁脚本：{_GATE}"
    module = importlib.util.module_from_spec(spec)
    # dataclasses 会回查 sys.modules[cls.__module__]，不登记就 AttributeError
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _run_gate(scan_dir: Path) -> tuple[int, dict]:
    """进程内跑门禁 `main()`，返回 (退出码, JSON 载荷)。"""
    module = _load_gate_module()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = module.main([str(scan_dir), "--json"])
    text = buf.getvalue().strip()
    if not text:
        return rc, {"total": -1, "violations": [], "scanned_files": 0}
    return rc, json.loads(text.splitlines()[-1])


def test_settings_point_at_test_db():
    """夹具生效：三个库 URL 都必须落在 `*_test` 库上（否则测试会连生产库）。"""
    for name in ("ASYNC_DATABASE_URL", "DATABASE_URL", "ASYNC_DATABASE_REPLICA_URL"):
        url = str(getattr(settings, name, "") or "")
        assert url, f"settings.{name} 为空，夹具未生效"
        db_name = url.split("?")[0].rstrip("/").rsplit("/", 1)[-1]
        assert db_name.endswith("_test"), (
            f"settings.{name} 指向非测试库（db={db_name!r}）："
            "fastapi_app/tests/conftest.py::app_on_test_db 未生效或被人改坏"
        )


def test_gate_flags_app_engine_usage(tmp_path):
    """门禁必须对 `get_sync_engine` 变红（退出码非 0 + total >= 1）。"""
    (tmp_path / "test_bad.py").write_text(_PROBE_BAD, encoding="utf-8")
    rc, payload = _run_gate(tmp_path)
    assert rc != 0, f"门禁放行了应用自身引擎用法：{payload}"
    assert payload["total"] >= 1, payload
    hit_names = {v["name"] for v in payload["violations"]}
    assert "get_sync_engine" in hit_names, hit_names


def test_gate_passes_clean_tree(tmp_path):
    """门禁必须放行走测试库硬闸的写法（否则会把正确写法也拦掉）。"""
    (tmp_path / "test_clean.py").write_text(_PROBE_CLEAN, encoding="utf-8")
    rc, payload = _run_gate(tmp_path)
    assert rc == 0, f"门禁误报正确写法：{payload}"
    assert payload["total"] == 0, payload


def test_real_tree_is_clean():
    """现网测试树必须零违规（这条是 P0-2 修复本身的守卫）。"""
    rc, payload = _run_gate(_REPO_ROOT / "fastapi_app" / "tests")
    assert rc == 0, f"fastapi_app/tests 出现应用自身引擎用法：{payload['violations']}"
    assert payload["scanned_files"] > 100, payload
