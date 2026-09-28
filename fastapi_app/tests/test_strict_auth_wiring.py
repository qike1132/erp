"""敏感路由的 fail-closed 鉴权：接线 + 行为。

背景（2026-09-28 上线前审计）
----------------------------
`core/deps.py` 定义了 `get_current_user_id_strict`（Redis 撤销存储不可用且本地
LRU 未命中时**拒绝**请求），但**全仓零调用点** —— 所有路由走 fail-open 版本，
于是 Redis 抖动期间「已登出/已吊销」的 token 仍被放行。

为什么只给 `/backup` 接线
-------------------------
`strict` 有个真实代价：**Redis 启动即不可用**时（`redis_cache.init_app` 失败后
不重试，只能重启进程回正），strict 路由会**永久 401**，连合法 token 也拒。
本仓库有过开机顺序事故史，因此取舍是：

* `/backup` —— 可覆盖整库，风险最高；且**还原路径本就对 Redis fail-closed**
  （`services/backup/restore.py` 的还原锁），所以不引入新的锁死。**接线**。
* `/users`、`/permissions` —— 收益是「Redis 抖动期间已吊销 token 不被复用」
  （窗口很窄），代价却是管理员被永久锁在用户/权限页之外。**刻意保持 fail-open**。

为什么路由内省写不了断言
------------------------
本版本 FastAPI 把 `include_router` 保留为 `_IncludedRouter` 包装对象：
`app.routes` 只暴露 8 条非 API 路由，`api_router.routes` 是 33 个包装对象。
因此接线用**源码级**断言（对本项目 router.py 结构稳定），
而行为用 **HTTP 级**断言（见文件末尾，不依赖任何 FastAPI 内部结构）。
"""
from __future__ import annotations

import contextlib
import re
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from fastapi_app.core.auth.token import create_access_token
from fastapi_app.core.deps import get_current_user_id, get_current_user_id_strict
from fastapi_app.main import app

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ROUTER = PROJECT_ROOT / 'fastapi_app' / 'api' / 'v1' / 'router.py'

# 接线 strict 的敏感前缀
STRICT_PREFIXES = ('/backup',)
# 刻意保持 fail-open 的前缀（原因见模块 docstring）
DELIBERATELY_FAIL_OPEN = ('/users', '/permissions')


def _dependency_for(prefix: str) -> str:
    src = ROUTER.read_text(encoding='utf-8')
    i = src.index(f'prefix="{prefix}",')
    m = re.search(r'dependencies=\[Depends\((\w+)\)\]', src[i:i + 700])
    assert m, f'router.py 中未找到 prefix="{prefix}" 的 dependencies（结构可能已变）'
    return m.group(1)


@pytest.mark.parametrize('prefix', STRICT_PREFIXES)
def test_sensitive_route_uses_fail_closed_dependency(prefix: str) -> None:
    assert _dependency_for(prefix) == 'get_current_user_id_strict', (
        f'{prefix} 应使用 fail-closed 的 get_current_user_id_strict'
    )


@pytest.mark.parametrize('prefix', DELIBERATELY_FAIL_OPEN)
def test_deferred_prefixes_stay_fail_open(prefix: str) -> None:
    """这两个前缀**刻意**保持 fail-open —— 若改成 strict，请同时更新模块 docstring。"""
    assert _dependency_for(prefix) == 'get_current_user_id'


@pytest.mark.parametrize('prefix', ['/stock', '/orders', '/products'])
def test_ordinary_routes_keep_fail_open_dependency(prefix: str) -> None:
    assert _dependency_for(prefix) == 'get_current_user_id'


def _bearer_token() -> str:
    return create_access_token({'sub': '1', 'username': 'admin'})


async def test_backup_returns_401_when_revocation_store_unavailable(client) -> None:
    """Redis 撤销存储不可用 + 本地缓存未命中 → /backup 必须 401（fail-closed）。

    这是审计发现的行为本身：仅靠源码接线断言无法证明 `fail_closed=True`
    真的被传到了 `is_token_revoked`（有人改坏 deps.py 也照样通过）。
    """
    # 让真实的 strict 依赖生效（conftest 默认把它 override 掉了）
    app.dependency_overrides.pop(get_current_user_id_strict, None)
    try:
        with patch('fastapi_app.core.redis_wrapper.get_client', return_value=None):
            resp = await client.get(
                '/api/v1/backup/ping',
                headers={'Authorization': f'Bearer {_bearer_token()}'},
            )
    finally:
        # 还原 override 供其余测试使用由 conftest 负责，这里只需保证不污染本用例
        pass

    assert resp.status_code == 401, f'期望 fail-closed 401，实际 {resp.status_code}'


async def test_users_uses_fail_open_blacklist_check(client) -> None:
    """同一故障条件下 /users 走的**必须是 fail-open 分支**（证明收窄生效）。

    不直接断言 HTTP 状态码：该端点在 mock DB 下会因查询不支持而报错，
    那与鉴权无关、会把断言变成噪声。这里直接探针 `is_token_revoked` 收到的
    `fail_closed` 实参 —— 这正是两个依赖的唯一行为差异。

    注意必须**同时摘掉 `get_current_user_id` 的 override**：conftest 默认把它
    替换成桩函数，真实鉴权路径（含撤销检查）根本不会执行，探针会一无所获。
    """
    seen: list[bool] = []

    async def spy(jti, *, fail_closed: bool = False):
        seen.append(fail_closed)
        return False  # 本地缓存未命中 + Redis 不可用时的真实语义

    app.dependency_overrides.pop(get_current_user_id, None)
    with patch('fastapi_app.core.deps.is_token_revoked', spy), \
         patch('fastapi_app.core.redis_wrapper.get_client', return_value=None), \
         contextlib.suppress(Exception):  # mock DB 下的报错与鉴权无关
        await client.get(
            '/api/v1/users/list',
            headers={'Authorization': f'Bearer {_bearer_token()}'},
        )

    assert seen, '未观察到撤销检查调用 —— override 可能没摘掉'
    assert all(value is False for value in seen), (
        f'/users 应保持 fail-open（fail_closed=False），实际收到 {seen}'
    )


async def test_backup_uses_fail_closed_blacklist_check(client) -> None:
    """与上一条对称：/backup 必须收到 fail_closed=True。"""
    seen: list[bool] = []

    async def spy(jti, *, fail_closed: bool = False):
        seen.append(fail_closed)
        if fail_closed:
            # 复刻真实语义：撤销状态不可判定时 fail-closed 直接拒绝
            raise HTTPException(status_code=401, detail='令牌状态校验不可用，请重新登录')
        return False

    app.dependency_overrides.pop(get_current_user_id_strict, None)
    resp = None
    # suppress：真正想断言的是「探针收到了什么实参」。若 deps.py 被改坏（不再
    # fail-closed），请求会继续往下走并在 mock DB 上抛错 —— 那会让失败信息变成
    # 无关的 AttributeError。先压制它，让下面的 seen 断言给出可读原因。
    with patch('fastapi_app.core.deps.is_token_revoked', spy), \
         patch('fastapi_app.core.redis_wrapper.get_client', return_value=None), \
         contextlib.suppress(Exception):
        resp = await client.get(
            '/api/v1/backup/ping',
            headers={'Authorization': f'Bearer {_bearer_token()}'},
        )

    assert seen == [True], f'/backup 必须走 fail-closed（fail_closed=True），实际收到 {seen}'
    assert resp is not None and resp.status_code == 401, (
        f'fail-closed 应直接拒绝，实际 {getattr(resp, "status_code", "请求抛错")}'
    )
