"""还原锁的持有者归属：不得无条件删除他人的锁。

背景（/backup 审计，high）
-------------------------
`release_restore_lock(task_id=None)` 在 None 时**无条件 DELETE** 锁键（旧语义兜底）。
同步还原路径（/import、/restore-by-name 的 zip 与 json 分支、/restore-incremental）
此前全部以 `release_restore_lock()` 无参释放，等于把「谁持锁」这一保护整个跳过：

    请求 A 取锁 → 还原超过 TTL(3600s) 锁自然过期 → 请求 B 取到同一把锁
    → A 的 finally 执行，删掉**B 的**锁 → 请求 C 又能进来 ⇒ 两个破坏性还原并发。

修法：`_acquire_sync_restore_lock` 返回**每次请求唯一**的 owner token，释放时经 Lua
比对 value 才删除。token 必须唯一 —— 若沿用固定的 'sync_import'，锁过期后新请求
取到的 value 与旧请求相同，误删依旧会发生。
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from fastapi_app.api.v1.endpoints.backup import restore as restore_mod
from fastapi_app.services import backup as backup_service
from fastapi_app.services.backup import restore as restore_svc

_RESTORE_PY = Path(restore_mod.__file__)


class _FakeRedis:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def delete(self, key: str):
        self.calls.append(('delete', key))
        return 1

    async def eval(self, script: str, numkeys: int, *args):
        self.calls.append(('eval', numkeys, *args))
        return 0


def _patch_redis(monkeypatch: pytest.MonkeyPatch) -> _FakeRedis:
    fake = _FakeRedis()

    async def _get_redis():
        return fake

    import fastapi_app.core.backup_progress as bp

    monkeypatch.setattr(bp, '_get_redis', _get_redis)
    return fake


# ---------------------------------------------------------------------------
# token 唯一性 —— 修法的核心
# ---------------------------------------------------------------------------

async def test_sync_lock_token_is_unique_per_call(monkeypatch: pytest.MonkeyPatch) -> None:
    acquired: list[str] = []

    async def fake_acquire(owner: str) -> bool:
        acquired.append(owner)
        return True

    monkeypatch.setattr(backup_service, 'acquire_restore_lock', fake_acquire)

    first = await restore_mod._acquire_sync_restore_lock('sync_import')
    second = await restore_mod._acquire_sync_restore_lock('sync_import')

    assert first != second, '两次请求拿到同一个 token ⇒ 迟到释放仍会误删新锁'
    assert acquired == [first, second], '落进锁里的 value 必须是返回给调用方的 token'
    assert first.startswith('sync_import:'), '仍应保留可读前缀，便于 409 报文定位'


# ---------------------------------------------------------------------------
# release 语义：有 owner 走 Lua 比对，无 owner 才是无条件删除（旧语义）
# ---------------------------------------------------------------------------

async def test_release_with_owner_uses_compare_and_delete(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _patch_redis(monkeypatch)

    await restore_svc.release_restore_lock('sync_import:deadbeef')

    assert fake.calls == [('eval', 1, 'erp:restore_lock', 'sync_import:deadbeef')], (
        '带 owner 释放必须走 Lua 比对，绝不能退化成无条件 delete'
    )


async def test_release_without_owner_still_deletes_unconditionally(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """旧语义只保留给显式传 None 的调用方（本次改动的兼容面）。"""
    fake = _patch_redis(monkeypatch)

    await restore_svc.release_restore_lock()

    assert fake.calls == [('delete', 'erp:restore_lock')]


# ---------------------------------------------------------------------------
# 静态守卫：端点里不再出现无参释放，且每个 acquire 的返回值都被用于释放
# ---------------------------------------------------------------------------

def _tree() -> ast.Module:
    return ast.parse(_RESTORE_PY.read_text(encoding='utf-8'))


def _await_call(node: ast.AST, name: str) -> bool:
    return (
        isinstance(node, ast.Await)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, (ast.Name, ast.Attribute))
        and (node.value.func.id if isinstance(node.value.func, ast.Name) else node.value.func.attr) == name
    )


def test_no_bare_release_restore_lock_call_in_endpoints() -> None:
    """`release_restore_lock()` 无参调用 = 无条件删锁，端点里一个都不许有。"""
    bare = []
    for node in ast.walk(_tree()):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != 'release_restore_lock':
            continue
        if not node.args and not node.keywords:
            bare.append(node.lineno)

    assert bare == [], f'第 {bare} 行仍以无参方式释放还原锁（会误删他人锁）'


def test_every_sync_acquire_result_is_released() -> None:
    """每个 `_acquire_sync_restore_lock` 的返回值都要被赋名并交给 release。

    acquire 会占锁，漏掉释放就会把锁留到 TTL 过期；返回的 token 没有用于释放
    则说明调用方又回到了无参释放的老路。
    """
    tree = _tree()
    assigned: set[str] = set()
    acquire_lines: list[int] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and _await_call(node.value, '_acquire_sync_restore_lock'):
            assert len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
            assigned.add(node.targets[0].id)
        if isinstance(node, ast.Expr) and _await_call(node.value, '_acquire_sync_restore_lock'):
            acquire_lines.append(node.lineno)

    assert acquire_lines == [], (
        f'第 {acquire_lines} 行的 `_acquire_sync_restore_lock(...)` 丢弃了返回的 owner token'
    )
    assert assigned, '端点里应当存在被赋名的 acquire 调用'

    released: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != 'release_restore_lock':
            continue
        for arg in node.args:
            if isinstance(arg, ast.Name):
                released.add(arg.id)

    missing = assigned - released
    assert not missing, f'这些 token 拿了锁却没用于释放：{sorted(missing)}'
