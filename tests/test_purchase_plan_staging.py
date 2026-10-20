"""采购计划暂存确认（confirm_staging）的产品落空守卫 —— 审计 #2。

背景：`validate_staging` 校验通过后到 `confirm_staging` 确认之间，产品可能被改名
或删除。此时确认阶段按产品名匹配会落空，原实现写 `product_id=0` 占位行：

    product_id 0 → 外键 purchase_plan_details_product_id_fkey（REFERENCES product(id)）
    库里不存在 id=0 → 提交时 FK 违约 → 整批确认失败，且该 IntegrityError 在确认端点
    被 error_map 映射成 409「单号已存在，请勿重复提交」——与真实原因毫无关系。

本文件钉住两条：
    1. 产品落空 → confirm_staging 抛业务错误（400），不落任何明细；
    2. 产品可解析 → 写入的明细 product_id 是真实 product.id，绝不是 0。

mock 的 db.execute 按语句内容分派（暂存行 / 产品 / 删除），不依赖查询顺序。
"""
from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest

from fastapi_app.services import purchase_plan_staging as staging


def _make_record(record_id=1, product_name='皮套A', customer_name='客户A', plan_month='2026-10'):
    """构造一条校验通过的暂存行"""
    record = MagicMock()
    record.id = record_id
    record.is_validated = True
    record.validation_error = None
    record.product_name = product_name
    record.customer_name = customer_name
    record.plan_month = plan_month
    record.plan_date = date(2026, 10, 1)
    record.quantity = 10
    record.remark = ''
    return record


def _result(rows):
    """模拟 select(...).scalars().all() 的返回值"""
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    result.all.return_value = []
    return result


@pytest.fixture
def _stub_dependencies(monkeypatch):
    """隔离与本用例无关的外部依赖：订单余量校验、活跃客户查询。"""
    async def _no_order_block(db, items):
        return []

    async def _customers(db):
        return [{'name': '客户A', 'id': 7}]

    monkeypatch.setattr(staging, 'check_order_remaining', _no_order_block)
    monkeypatch.setattr(staging.customer_service, 'get_active_customer_names', _customers)


def _make_db(records, products):
    """构造按语句内容分派的 db mock"""
    db = AsyncMock()
    db.info = {}

    async def _execute(stmt):
        text = str(stmt)
        if 'staging_purchase_plan' in text:
            return _result(records)
        if 'FROM product' in text:
            return _result(products)
        return _result([])

    db.execute = AsyncMock(side_effect=_execute)
    db.add = MagicMock()
    return db


@pytest.mark.asyncio
async def test_missing_product_fails_fast_without_writing_details(_stub_dependencies):
    """产品已不存在 → 抛业务错误，绝不写 product_id=0 占位行"""
    db = _make_db([_make_record(product_name='已删除产品')], [])

    with pytest.raises(ValueError, match='已删除产品'):
        await staging.confirm_staging(db, 'sess-1')

    assert db.add.call_count == 0, '产品落空时不得写入任何计划明细'


@pytest.mark.asyncio
async def test_missing_product_lists_all_missing_names(_stub_dependencies):
    """多个产品落空时，错误信息一次列出全部，便于用户重新校验"""
    records = [
        _make_record(record_id=1, product_name='已删除A'),
        _make_record(record_id=2, product_name='已删除B'),
    ]
    db = _make_db(records, [])

    with pytest.raises(ValueError) as exc:
        await staging.confirm_staging(db, 'sess-1')

    message = str(exc.value)
    assert '已删除A' in message and '已删除B' in message, message


@pytest.mark.asyncio
async def test_resolved_product_writes_real_product_id(_stub_dependencies, monkeypatch):
    """产品可解析 → 明细写真实 product_id（不是 0）"""
    product = MagicMock()
    product.id = 42
    product.name = '皮套A'
    db = _make_db([_make_record(product_name='皮套A')], [product])

    plan = MagicMock()
    plan.id = 100
    plan.plan_no = 'PP-0001'

    async def _fake_plan(db_, customer_id, customer_name, plan_month, batch_id='', created_by=''):
        return plan

    monkeypatch.setattr(staging, '_get_or_create_plan_for_group', _fake_plan)

    result = await staging.confirm_staging(db, 'sess-1')

    assert result['created_count'] == 1
    added = [c.args[0] for c in db.add.call_args_list]
    assert len(added) == 1
    assert added[0].product_id == 42, 'product_id 必须是真实产品ID，不能是占位 0'


def test_create_details_rejects_missing_product():
    """写入点自身也必须拒绝落空产品——绝不产出 product_id=0 的明细"""
    db = AsyncMock()
    plan = MagicMock()
    plan.id = 100

    with pytest.raises(ValueError, match='不存在'):
        staging._create_details_for_group(
            db, plan, [_make_record(product_name='幽灵产品')], {},
        )

    assert db.add.call_count == 0, '落空产品时不得写入明细'
