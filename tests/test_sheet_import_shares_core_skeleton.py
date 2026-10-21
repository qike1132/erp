"""两条导入路径共用一份行循环骨架（2026-10-17 审计 Z04-R3②）。

单 Sheet 端点的 ``_run_sheet_rows`` 与综合导入/ARQ 的 ``_import_data_generic`` 曾是
两份同构行循环（savepoint 包行 → 成功后计数 → 异常兜底 → post-commit 钩子）。
2026-08-10 的 19 张孤儿订单事故就是「core 改了、单 Sheet 漏改」的产物，所以
2026-10-15 先把 5 份端点副本收成 1 份，本轮（Z04-R3②）再把那 1 份并入 core 骨架。

本文件锁住合并后必须成立的四条：

1. **结构**：``_run_sheet_rows`` 不再自带行循环，只剩签名/返回结构的适配；
2. **提交后钩子的既有不对称**：单 Sheet 路径**不**登记采购单自动生成（合并骨架
   不能顺手让 5 个端点当场生成真实采购单），综合导入/ARQ 路径照旧登记；
3. **适配语义**：``(True/False, message)`` 三态 → imported/skipped 计数与行级消息，
   单行异常只回滚本行且不中断整批；
4. **全跳过时不挂任何钩子**（重复文件/空文件不该清缓存、更不该触发采购扫描）。
"""
import inspect

from sqlalchemy import select

from fastapi_app.services import batch_import_core as bic
from fastapi_app.services import batch_import_service as bis
from fastapi_app.services.batch_import_cache import invalidate_batch_import_caches
from fastapi_app.services.purchase._auto_generate import _run_auto_generate
from fastapi_app.shared_models import Customer


def _callbacks(session) -> list:
    """本次事务登记的提交后回调（只验「登记了什么」，绝不执行 —— 执行会真下单）。"""
    return list(session.info.get('post_commit_callbacks') or [])


class TestStructure:
    def test_sheet_rows_delegates_to_core_skeleton(self):
        src = inspect.getsource(bis._run_sheet_rows)

        assert '_import_data_generic' in src, '单 Sheet 骨架未并入 core，行循环仍是两份'
        for forbidden in ('begin_nested', 'schedule_post_commit_invalidation', 'for row_data in'):
            assert forbidden not in src, f'_run_sheet_rows 里残留第二份循环片段: {forbidden}'

    def test_purchase_auto_generate_is_parameterized(self):
        src = inspect.getsource(bic._import_data_generic)

        assert 'auto_generate_purchase' in src, (
            '采购自动生成不再是可配置项：单 Sheet 端点会跟着综合路径一起生成采购单'
        )

    def test_endpoints_keep_own_row_writers(self):
        """5 个单 Sheet 端点仍只负责写行，循环归骨架：出现第二份循环即回归。"""
        for name in ('import_orders_service', 'import_stockins_service', 'import_stockouts_service',
                     'import_case_stockins_service', 'import_case_stockouts_service'):
            assert '_run_sheet_rows' in inspect.getsource(getattr(bis, name)), f'{name} 不再走共享骨架'


class TestPostCommitHooks:
    """合并最容易改错的地方：钩子。用真实会话验「登记了哪几个回调」。"""

    async def test_sheet_path_registers_cache_invalidation_only(self, async_db_session):
        async def _writer(_db, _row):
            return True, None

        result = await bis._run_sheet_rows(
            async_db_session, [{'数量': 1}], _writer,
            '成功导入', '没有成功导入', log_label='骨架测试',
        )

        assert result.imported == 1, result.message
        assert _callbacks(async_db_session) == [invalidate_batch_import_caches], (
            f'单 Sheet 路径的提交后钩子不符: {_callbacks(async_db_session)}'
        )

    async def test_core_path_still_auto_generates_purchase_orders(self, async_db_session):
        """默认参数守住综合导入/ARQ 的既有行为：失效缓存 + 采购单自动生成都在。"""
        async def _handler(_db, _row, _idx, _ctx, _msgs):
            return True

        count, _msgs = await bic._import_data_generic(
            async_db_session, [{'数量': 1}], _handler, label='骨架测试',
        )

        assert count == 1
        callbacks = _callbacks(async_db_session)
        assert invalidate_batch_import_caches in callbacks
        assert _run_auto_generate in callbacks, (
            f'综合导入路径丢了采购单自动生成钩子: {callbacks}'
        )

    async def test_nothing_imported_registers_no_hooks(self, async_db_session):
        """全部跳过（重复文件/空文件）既不清缓存也不触发采购扫描。"""
        async def _writer(_db, _row):
            return False, '数量必须大于0'

        result = await bis._run_sheet_rows(
            async_db_session, [{'数量': 0}], _writer,
            '成功导入', '没有成功导入', log_label='骨架测试',
        )

        assert result.imported == 0, result.message
        # 失败分支不回填 skipped（_build_batch_result 既有契约），只回显行级消息
        assert '数量必须大于0' in result.message, result.message
        assert _callbacks(async_db_session) == []


class TestAdapterSemantics:
    """三态 ``(ok, message)`` 经适配层进 core 骨架后的用户可见行为（与合并前一致）。"""

    async def test_three_row_states_and_row_numbering(self, async_db_session):
        async def _writer(_db, row):
            state = row['state']
            if state == 'ok':
                return True, None
            if state == 'msg':
                return False, '客户"甲"不存在于客户主数据，请先在客户管理中创建'
            if state == 'silent':
                return False, None
            raise ValueError('数量解析失败')

        rows = [{'state': s} for s in ('msg', 'ok', 'silent', 'boom')]
        result = await bis._run_sheet_rows(
            async_db_session, rows, _writer,
            '成功导入', '没有成功导入', log_label='骨架测试',
        )

        assert result.imported == 1, result.message
        assert result.skipped == 3, result.message
        # 异常行不中断整批：它排在最后，前面的 msg/silent 行照常计数
        assert '客户"甲"不存在' in result.message, result.message
        # 行号自表头下第一行（第 2 行）起算：第 4 条数据 = Excel 第 5 行
        assert '行5: 异常 - 数量解析失败' in result.message, result.message

    async def test_bad_row_rolls_back_only_itself(self, async_db_session):
        """行内 SQL 错误只回滚本行，前后行仍落库（savepoint 隔离，端点级语义不变）。"""
        async def _writer(db, row):
            # customer.name 是 varchar(100)：超长名在 savepoint 退出的 flush 里必炸
            db.add(Customer(name=row['name'], phone='10000'))
            return True, None

        rows = [{'name': n} for n in ('骨架测试-存活前', 'X' * 300, '骨架测试-存活后')]
        result = await bis._run_sheet_rows(
            async_db_session, rows, _writer,
            '成功导入', '没有成功导入', log_label='骨架测试',
        )

        assert result.imported == 2, result.message
        assert result.skipped == 1, result.message
        names = set((await async_db_session.execute(
            select(Customer.name).where(Customer.name.like('骨架测试-存活%')))).scalars().all())
        assert names == {'骨架测试-存活前', '骨架测试-存活后'}, names
