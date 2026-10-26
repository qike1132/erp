"""H4 回归锁：/api/health 必须能证明「实际响应请求的 worker 是哪一代代码」。

背景（2026-10-26 上线前检查 H4）：发布脚本原先只看 `/api/health` 是否 200。
旧进程一直健康时，脚本会把「新代码根本没加载」判成发布成功。修复是双端配合：

* 本模块在**导入时**固化 worker 指纹（pid / boot_id / started_at / 加载时的 HEAD）；
* 仅对**回环**请求把指纹放进响应的 ``runtime`` 字段 —— 公网请求不扩大指纹面。

restart_backend.py 的发布验收据此校验 commit == 目标 HEAD、启动时刻晚于本次操作，
任一不满足即失败关闭（见 fastapi_app/tests/test_write_guard_wiring.py）。
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from fastapi_app.core import health


def _req(host: str):
    return SimpleNamespace(client=SimpleNamespace(host=host))


def test_runtime_fingerprint_is_stable_within_process():
    """boot_id 必须每进程固定：每次请求重新生成会让「启动代次」失去意义。"""
    first = health._runtime_fingerprint()
    second = health._runtime_fingerprint()

    assert first["boot_id"] == second["boot_id"] != ""
    assert first["pid"] == second["pid"] == health._PROCESS_PID
    assert first["started_at"] == second["started_at"] == health._PROCESS_STARTED_AT
    assert set(first) == {"pid", "boot_id", "started_at", "commit", "version"}


def test_runtime_attached_only_for_loopback_clients():
    """公网/反代来源不得拿到 pid/boot_id（指纹面只对回环开放）。"""
    for host in ("127.0.0.1", "::1", "localhost", "::ffff:127.0.0.1"):
        payload = health._attach_runtime({"status": "healthy"}, _req(host))
        assert payload.get("runtime", {}).get("pid") == health._PROCESS_PID, host
    for host in ("10.0.0.8", "203.0.113.9", ""):
        payload = health._attach_runtime({"status": "healthy"}, _req(host))
        assert "runtime" not in payload, f"非回环来源 {host!r} 不得暴露 runtime"


def test_runtime_not_attached_to_response_objects():
    """503 分支返回的是 Response 对象，不得被当成 dict 注入。"""
    resp = SimpleNamespace(status_code=503)
    assert health._attach_runtime(resp, _req("127.0.0.1")) is resp
    assert not hasattr(resp, "runtime")


def test_loaded_commit_is_sha_or_none():
    """打包环境没有 .git 时允许 None（发布脚本会失败关闭），但不许是半截字符串。"""
    commit = health._LOADED_COMMIT
    assert commit is None or (len(commit) == 40 and all(c in "0123456789abcdef" for c in commit))


def test_read_loaded_commit_does_not_spawn_git():
    """导入期读 HEAD 必须是纯文件 I/O（不起子进程、不依赖 git 在 PATH 上）。"""
    import ast

    tree = ast.parse(Path(health.__file__).read_text(encoding='utf-8'))
    imported = {
        alias.name.split('.')[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        (node.module or '').split('.')[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    assert 'subprocess' not in imported, '健康模块不得为读 HEAD 引入子进程'

    calls = [
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    ]
    assert 'run' not in calls and 'Popen' not in calls, '导入期不得拉起外部命令'
    assert health._read_loaded_commit() == health._LOADED_COMMIT


def _write_git(root, head_text: str):
    git = root / '.git'
    git.mkdir()
    (git / 'HEAD').write_text(head_text, encoding='utf-8')
    return git


def test_read_loaded_commit_from_ref_file(tmp_path):
    git = _write_git(tmp_path, 'ref: refs/heads/main\n')
    ref = git / 'refs' / 'heads'
    ref.mkdir(parents=True)
    (ref / 'main').write_text('A' * 40 + '\n', encoding='utf-8')

    assert health._read_loaded_commit(tmp_path) == 'a' * 40


def test_read_loaded_commit_from_packed_refs(tmp_path):
    """refs 被打包后 refs/heads/main 不存在，必须回落到 packed-refs。"""
    git = _write_git(tmp_path, 'ref: refs/heads/main\n')
    (git / 'packed-refs').write_text(
        '# pack-refs with: peeled fully-peeled\n'
        f'{"b" * 40} refs/heads/other\n'
        f'{"c" * 40} refs/heads/main\n',
        encoding='utf-8',
    )

    assert health._read_loaded_commit(tmp_path) == 'c' * 40


def test_read_loaded_commit_detached_head(tmp_path):
    _write_git(tmp_path, 'd' * 40 + '\n')

    assert health._read_loaded_commit(tmp_path) == 'd' * 40


def test_read_loaded_commit_from_linked_worktree(tmp_path):
    """linked worktree：.git 是 "gitdir: <path>" 文本文件。"""
    real_git = tmp_path / 'real-git'
    real_git.mkdir()
    (real_git / 'HEAD').write_text('ref: refs/heads/main\n', encoding='utf-8')
    (real_git / 'refs' / 'heads').mkdir(parents=True)
    (real_git / 'refs' / 'heads' / 'main').write_text('e' * 40, encoding='utf-8')

    work = tmp_path / 'work'
    work.mkdir()
    (work / '.git').write_text(f'gitdir: {real_git}\n', encoding='utf-8')

    assert health._read_loaded_commit(work) == 'e' * 40


def test_read_loaded_commit_missing_or_broken(tmp_path):
    assert health._read_loaded_commit(tmp_path) is None  # 无 .git（打包运行）
    _write_git(tmp_path, 'not-a-ref-and-not-a-sha\n')
    assert health._read_loaded_commit(tmp_path) is None


@pytest.mark.asyncio
async def test_health_check_attaches_runtime_without_polluting_cache(monkeypatch):
    """缓存快照里不得混入 runtime：否则公网缓存会带上回环指纹。"""
    cached = {"status": "healthy", "app": "erp", "backup": {"ok": True}}
    health._health_cache["public_data"] = dict(cached)
    health._health_cache["cached_at"] = __import__("time").time()

    async def _no_degraded():
        return []

    monkeypatch.setattr(health, "degraded_reasons_all", _no_degraded)

    payload = await health.health_check(_req("127.0.0.1"), user_id=None)

    assert payload["runtime"]["pid"] == health._PROCESS_PID
    assert payload["status"] == "healthy"
    assert "runtime" not in health._health_cache["public_data"], \
        "runtime 不得写回缓存（缓存会被公网请求复用）"
