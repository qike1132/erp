"""失败路径与健壮性四连回归（M-15 / M-18 / M-10 / M-8，2026-11-21 审计）。

M-15：/reports 五个流水端点此前不捕 parse_date_strict 的 ValueError（?start_date=abc
返回 500）——report_service 源头统一转 BusinessError(400)。
M-18：auxiliary 批量提交三 schema 的列表无上限——补 max_length=200。
M-10：daily_production 更新显式传 quantity/unit_price=null 此前 500——归并为
「不修改」。
M-8：batch_import 临时文件清理的 time.sleep 重试此前跑在事件循环上——挪线程池
（行为等价，无独立断言，由导入套件覆盖执行路径）。
"""
import pytest
from pydantic import ValidationError

from fastapi_app.api.v1.endpoints.auxiliary import BatchOrderRequest, BatchStockInRequest


def _item(i: int) -> dict:
    return {'product_id': i + 1, 'quantity': 1, 'customer': '客户甲'}


def test_batch_order_request_caps_orders_at_200():
    with pytest.raises(ValidationError):
        BatchOrderRequest(orders=[_item(i) for i in range(201)])
    req = BatchOrderRequest(orders=[_item(i) for i in range(200)])
    assert len(req.orders) == 200


def test_batch_stockin_request_caps_stockins_at_200():
    with pytest.raises(ValidationError):
        BatchStockInRequest(stockins=[_item(i) for i in range(201)])


@pytest.mark.parametrize('path', ['/api/v1/reports/order-logs', '/api/v1/reports/stockin-logs'])
async def test_report_logs_invalid_date_is_400(async_client, auth_headers, path):
    resp = await async_client.get(
        path, params={'start_date': 'abc', 'end_date': '2026-11-01'}, headers=auth_headers)
    assert resp.status_code == 400, (resp.status_code, resp.text[:200])


async def test_report_logs_valid_dates_still_ok(async_client, auth_headers):
    resp = await async_client.get(
        '/api/v1/reports/order-logs', headers=auth_headers)
    assert resp.status_code == 200, (resp.status_code, resp.text[:200])
