"""备份还原 confirm 二次确认闸门：端点级回归锁（2026-11-03 审查 S16）。

历史 High ④「备份上传还原零确认」已于 2026-10-30 整改：后端 4 个还原端点全部在
函数体**首行**拦 ``if not confirm`` → 400「恢复操作需要二次确认」，前端也补了确认
对话框与双勾选（``BackupView.vue`` / ``RestoreConfirmDialog.vue``）。

问题在于：**没有任何用例断言这个闸门本身**。删掉任一处 ``if not confirm`` 不会有
任何测试变红——闸门等于零回归保护。更现实的场景是「将来新增一个还原入口时复制
粘贴漏掉闸门」，本文件就是拦这种情况。

设计取舍：为什么直接调端点协程，而不走 ASGI 客户端
--------------------------------------------------
1. 4 个端点在 ``if not confirm`` **之后**才触碰 file/filename/DB/Redis，所以传
   ``None`` / 假文件名是安全的，不会产生任何真实副作用；
2. 不依赖 auth fixture、不依赖测试库、不依赖 Redis —— 这条安全用例在任何环境都能跑。
   **会被 skip 掉的安全闸门等于没有闸门**（本仓 2026-10-27 已因「静默 skip 把写路径
   回归隐藏成绿」踩过一次），所以刻意不引入任何可 skip 的依赖；
3. 若闸门被删/被改成默认 True，函数会继续往下执行并在 file/filename 上抛别的异常，
   用例同样变红——检测力不依赖错误类型恰好命中。

副作用断言：把「只有确认之后才会走到」的三处入口都替换成会炸的替身，断言一次都没被
调用。这样即使有人把闸门挪到某个副作用之后，用例也会红。
"""
from __future__ import annotations

import inspect

import pytest
from fastapi import HTTPException

from fastapi_app.api.v1.endpoints.backup import _mutex
from fastapi_app.api.v1.endpoints.backup import restore as restore_mod

# (函数名, 除 confirm 外的必填/位置参数, 展示名)
RESTORE_ENDPOINTS = [
    ("import_backup", {"file": None}, "POST /import"),
    ("restore_server_backup", {"filename": "any.zip"}, "POST /restore-by-name/{filename}"),
    ("async_import_backup", {"file": None}, "POST /async-import"),
    (
        "async_restore_server_backup",
        {"filename": "any.zip"},
        "POST /async-restore-by-name/{filename}",
    ),
]
_IDS = [case[2] for case in RESTORE_ENDPOINTS]


@pytest.fixture
def side_effect_traps(monkeypatch) -> list[str]:
    """把确认之后才会走到的副作用入口换成「记录并炸掉」的替身。"""
    calls: list[str] = []

    async def _lock_trap(*args, **kwargs):
        calls.append("_acquire_sync_restore_lock")
        raise AssertionError(
            "确认闸门未拦截：端点已开始获取还原锁。"
            "说明 `if not confirm` 已被删除或挪到副作用之后。"
        )

    async def _mutex_trap(*args, **kwargs):
        calls.append("ensure_restore_slot_free")
        raise AssertionError("确认闸门未拦截：端点已进入并发互斥检查。")

    async def _acquire_trap(*args, **kwargs):
        calls.append("backup_service.acquire_restore_lock")
        raise AssertionError("确认闸门未拦截：异步端点已开始抢还原锁。")

    monkeypatch.setattr(restore_mod, "_acquire_sync_restore_lock", _lock_trap)
    # ensure_restore_slot_free 是函数体内的局部 import，补丁打在源模块上才生效
    monkeypatch.setattr(_mutex, "ensure_restore_slot_free", _mutex_trap)
    monkeypatch.setattr(restore_mod.backup_service, "acquire_restore_lock", _acquire_trap)
    return calls


@pytest.mark.parametrize(("func_name", "kwargs", "label"), RESTORE_ENDPOINTS, ids=_IDS)
async def test_restore_endpoint_rejects_without_confirm(
    func_name: str, kwargs: dict, label: str, side_effect_traps: list[str],
) -> None:
    """显式 confirm=False：必须 400，且不得触发任何副作用。"""
    endpoint = getattr(restore_mod, func_name)

    with pytest.raises(HTTPException) as exc_info:
        await endpoint(confirm=False, **kwargs)

    assert exc_info.value.status_code == 400, f"{label} 未返回 400"
    assert "二次确认" in str(exc_info.value.detail), (
        f"{label} 的 400 缺少「二次确认」提示，前端无法据此提示用户：{exc_info.value.detail!r}"
    )
    assert not side_effect_traps, (
        f"{label} 在确认前就触发了副作用：{side_effect_traps}"
    )


@pytest.mark.parametrize(("func_name", "kwargs", "label"), RESTORE_ENDPOINTS, ids=_IDS)
def test_restore_endpoint_confirm_defaults_to_false(
    func_name: str, kwargs: dict, label: str,
) -> None:
    """声明级断言：``confirm`` 的默认值必须是 False（默认放行等于闸门不存在）。

    为什么不直接「省略 confirm 调用一次」：4 个端点的写法并不统一——
    ``import_backup`` / ``async_import_backup`` 是 ``confirm: bool = False``，
    ``restore_server_backup`` / ``async_restore_server_backup`` 是
    ``confirm: bool = Query(False)``。后者在**直接调用**（不走 FastAPI 依赖解析）时，
    形参拿到的是 ``Query`` 对象本身，而它是**真值**——``if not confirm`` 不成立。
    这不是线上缺陷（真实 HTTP 请求下 FastAPI 会解析成 False），但会让「省略参数」
    风格的用例产生假报警。因此这里统一读声明默认值：FastAPI Param 对象取其 ``.default``。
    """
    declared = inspect.signature(getattr(restore_mod, func_name)).parameters["confirm"].default
    # FastAPI 的 Query(...)/Body(...) 等 Param 对象，真实默认值挂在 .default 上
    resolved = getattr(declared, "default", declared)

    assert resolved is False, (
        f"{label} 的 confirm 默认值是 {resolved!r}，不是 False——"
        "旧调用方不传 confirm 就会跳过二次确认"
    )
