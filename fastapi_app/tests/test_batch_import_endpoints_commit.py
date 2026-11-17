"""批量导入端点的提交边界（2026-11-17 上线前审计 V-A）。

## 拦哪种出错

`batch.py` 的 7 个导入端点此前把提交责任交给 `get_async_db` 依赖收尾。FastAPI 的
依赖收尾在**响应发出之后**才执行，于是 commit 失败时客户端已经拿到 200、数据却没落库
—— 生产 logs 实测 15 条「事务提交失败：响应已发送但数据未落库」（其中 10 条
`db_name=erp_system`，5 条带 `path=/api/v1/orders`）。

导入端点是最伤的一档：用户看到「成功导入 N 行」，库里一行都没有；再传同一文件又被
文件指纹判 409（`ImportFileRegistry` 登记行随事务一起没了，用户既没数据也没法重试）。

## 本文件各锁一件事

1. `test_commit_failure_surfaces_as_5xx`：commit 抛 `SQLAlchemyError` → 端点必须抛
   HTTP 500（而不是安静返回「导入成功」）；
2. `test_happy_path_commits_inside_handler`：正常路径在 handler 内提交，依赖收尾时
   已无待提交变更（= 收尾阶段不可能再失败）；
3. `test_endpoint_commits_in_handler`：源码守卫，7 个端点逐个断言包了
   `async with db_transaction(db):` —— 漏一个就等于留一条静默丢数路径。

修复前：1 红（不抛，直接返回结果对象）、3 红（没有 `db_transaction`）。
"""
import inspect
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import OperationalError

from fastapi_app.api.v1.endpoints import batch as batch_mod

#: 7 个走 ``run_guarded_import`` 的导入端点（预览端点只读，不在此列）
_ENDPOINTS = [
    'batch_import_orders',
    'batch_import_case_stockouts',
    'batch_import_case_stockins',
    'batch_import_stockins',
    'batch_import_stockouts',
    'batch_import_products',
    'batch_import_comprehensive',
]


class _CommitFailingDB:
    """提交即失败的会话替身（只实现 db_transaction 用到的两个方法）。"""

    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    async def commit(self) -> None:
        self.commits += 1
        raise OperationalError('COMMIT', {}, Exception('connection reset by peer'))

    async def rollback(self) -> None:
        self.rollbacks += 1


class _CommitOkDB(_CommitFailingDB):
    async def commit(self) -> None:
        self.commits += 1


def _user() -> SimpleNamespace:
    return SimpleNamespace(id=1, factory=None, is_super=True)


@pytest.mark.parametrize('name', _ENDPOINTS)
async def test_commit_failure_surfaces_as_5xx(name, monkeypatch):
    """提交失败必须是 5xx：客户端不能拿到「导入成功」。"""
    calls: list = []

    async def _runner(*args, **_kwargs):
        calls.append(args)
        return SimpleNamespace(success=True, imported=1, skipped=0)

    monkeypatch.setattr(batch_mod, 'run_guarded_import', _runner)
    db = _CommitFailingDB()

    with pytest.raises(HTTPException) as excinfo:
        await getattr(batch_mod, name)(file=object(), db=db, current_user=_user())

    assert excinfo.value.status_code == 500, excinfo.value
    assert db.commits == 1, '提交必须发生在 handler 内（失败即 5xx，不再 200 + 静默丢数）'
    assert calls, '守卫/导入没被调用，用例本身失效'


async def test_happy_path_commits_inside_handler(monkeypatch):
    """正常路径：handler 内提交后，依赖收尾阶段已无待提交变更。"""
    async def _runner(*_args, **_kwargs):
        return SimpleNamespace(success=True, imported=3, skipped=0)

    monkeypatch.setattr(batch_mod, 'run_guarded_import', _runner)
    db = _CommitOkDB()

    result = await batch_mod.batch_import_orders(
        file=object(), db=db, current_user=_user(),
    )

    assert result.imported == 3
    assert db.commits == 1, f'应恰好提交一次，实际 {db.commits}'
    assert db.rollbacks == 0


@pytest.mark.parametrize('name', _ENDPOINTS)
def test_endpoint_commits_in_handler(name):
    """源码守卫：每个导入端点都必须在 handler 内显式提交。"""
    src = inspect.getsource(getattr(batch_mod, name))
    assert 'run_guarded_import(' in src, f'{name} 不再是受守卫的导入端点，用例需同步'
    assert 'async with db_transaction(db):' in src, (
        f'{name} 把提交责任交回了 get_async_db 收尾 —— 响应已发出后提交失败 = 静默丢数（V-A）'
    )
