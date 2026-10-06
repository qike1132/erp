"""订单图片 OCR 预览端点测试（`POST /ocr-import/order/preview`）

该端点**不写库**：识别结果只回给前端人工确认。
OCR 引擎与数据库查询都在此 mock 掉，测试只验证契约与匹配语义。
"""
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

CHAT_PAGES = [{'page': 0, 'text': '客户：华东商贸\n儿童保温杯500ml50箱\n卡通雨伞8骨30把'}]
EMPTY_PAGES = [{'page': 0, 'text': '王姐，这周要补一批货\n收到，安排'}]

URL = '/api/v1/ocr-import/order/preview'


def make_rows(rows: list) -> MagicMock:
    """构造 db.execute(...) 的返回。

    只取部分列时（`select(Product.id, Product.name, ...)`）结果直接由 `all()` 给出
    Row；仍保留 `scalars().all()` 以兼容按整表实体查询的写法。
    """
    result = MagicMock()
    result.all.return_value = rows
    result.scalars.return_value.all.return_value = rows
    return result


def make_product(pid: int, name: str, barcode: str = '') -> MagicMock:
    p = MagicMock()
    p.id = pid
    p.name = name
    p.barcode = barcode
    return p


def make_customer(cid: int, name: str) -> MagicMock:
    c = MagicMock()
    c.id = cid
    c.name = name
    return c


# P0-12：上传魔数校验接入后，PNG 内容必须带真实 PNG 签名（\x89PNG\r\n\x1a\n），
# 否则会在进入本端点逻辑前被 400 拦下（本文件测的是订单预览语义，不是上传校验）。
def upload(name: str = 'order.png', content: bytes = b'\x89PNG\r\n\x1a\n' + b'fake-image-body') -> list:
    return [('file', (name, BytesIO(content), 'image/png'))]


class TestOrderPreviewValidation:
    @pytest.mark.asyncio
    async def test_unsupported_format(self, client, mock_db):
        response = await client.post(URL, files=upload('order.doc'))
        assert response.status_code == 400
        assert '不支持的文件格式' in response.json()['detail']

    @pytest.mark.asyncio
    async def test_empty_file(self, client, mock_db):
        response = await client.post(URL, files=upload(content=b''))
        assert response.status_code == 400
        assert '文件为空' in response.json()['detail']

    @pytest.mark.asyncio
    async def test_oversized_rejected_by_middleware(self, client, mock_db):
        """超 10MB 由全局 body-size 中间件先拒（413），走不到端点的 400。

        端点内那条 10MB 检查与中间件的 MAX_REQUEST_BODY_SIZE 一致，
        是防御性重复（与既有 /ocr-import/upload 保持一致），此处不单独断言。
        """
        response = await client.post(URL, files=upload(content=b'x' * (10 * 1024 * 1024 + 1)))
        assert response.status_code == 413


class TestOrderPreviewResult:
    @pytest.mark.asyncio
    async def test_success_returns_items_with_matches(self, client, mock_db):
        mock_db.execute = AsyncMock(side_effect=[
            make_rows([make_product(7, '儿童保温杯 500ml')]),
            make_rows([make_customer(3, '华东商贸')]),
        ])
        with patch('fastapi_app.services.ocr._order_preview.extract_text',
                   return_value=CHAT_PAGES):
            response = await client.post(URL, files=upload())
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert data['item_count'] == 2
        first = data['items'][0]
        assert first['raw_product_name'] == '儿童保温杯500ml'
        assert first['product_name'] == '儿童保温杯 500ml'
        assert first['product_id'] == 7
        assert first['quantity'] == 50
        assert first['unit'] == '箱'
        assert first['customer'] == '华东商贸'
        assert first['customer_id'] == 3
        assert first['note'] == ''

    @pytest.mark.asyncio
    async def test_unmatched_product_keeps_raw_name(self, client, mock_db):
        mock_db.execute = AsyncMock(side_effect=[
            make_rows([]),                     # 库内没有任何产品
            make_rows([make_customer(3, '华东商贸')]),
        ])
        with patch('fastapi_app.services.ocr._order_preview.extract_text',
                   return_value=CHAT_PAGES):
            response = await client.post(URL, files=upload())
        data = response.json()
        assert data['items'][0]['product_id'] is None
        assert data['items'][0]['product_name'] == '儿童保温杯500ml'
        assert any('没有匹配' in w for w in data['warnings'])

    @pytest.mark.asyncio
    async def test_missing_customer_falls_back_to_form(self, client, mock_db):
        pages = [{'page': 0, 'text': '儿童保温杯500ml50箱'}]
        mock_db.execute = AsyncMock(side_effect=[
            make_rows([make_product(7, '儿童保温杯500ml')]),
            make_rows([make_customer(3, '华东商贸有限公司')]),
        ])
        with patch('fastapi_app.services.ocr._order_preview.extract_text',
                   return_value=pages):
            response = await client.post(URL + '?customer=华东商贸有限公司', files=upload())
        data = response.json()
        assert data['items'][0]['customer'] == '华东商贸有限公司'
        assert any('已按当前选择的客户填入' in w for w in data['warnings'])

    @pytest.mark.asyncio
    async def test_no_items_returns_failure_with_raw_text(self, client, mock_db):
        with patch('fastapi_app.services.ocr._order_preview.extract_text',
                   return_value=EMPTY_PAGES):
            response = await client.post(URL, files=upload())
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is False
        assert data['item_count'] == 0
        assert data['items'] == []
        assert '王姐' in data['raw_text']

    @pytest.mark.asyncio
    async def test_preview_does_not_write(self, client, mock_db):
        """预览语义：只读匹配，不得产生任何写入"""
        mock_db.execute = AsyncMock(side_effect=[
            make_rows([make_product(7, '儿童保温杯500ml')]),
            make_rows([]),
        ])
        with patch('fastapi_app.services.ocr._order_preview.extract_text',
                   return_value=CHAT_PAGES):
            await client.post(URL, files=upload())
        mock_db.add.assert_not_called()
        mock_db.flush.assert_not_called()
        mock_db.commit.assert_not_called()


def _override_user(allowed: set[str]):
    """把 _get_user_with_permissions 覆盖为仅拥有 allowed 权限码的用户。

    返回 (app, 依赖) 供用例在 finally 里恢复，避免泄漏到后续用例。
    """
    from fastapi_app.core.deps import _get_user_with_permissions
    from fastapi_app.main import app

    user = MagicMock()
    user.id = 1
    user.username = 'perm-probe'
    user.is_super = False
    user.has_permission = MagicMock(side_effect=lambda code: code in allowed)
    app.dependency_overrides[_get_user_with_permissions] = lambda: user
    return app, _get_user_with_permissions


class TestOrderPreviewPermissions:
    """权限契约守卫：订单页（order_manage）与出货页（stockout_manage）都能用这条识别预览。

    2026-10-06 共享 components/ocr 后，出货页也走本端点；若有人收缩权限码，
    这里会先红。
    """

    @pytest.mark.asyncio
    async def test_stockout_manage_allowed(self, client, mock_db):
        mock_db.execute = AsyncMock(side_effect=[
            make_rows([make_product(7, '儿童保温杯500ml')]),
            make_rows([make_customer(3, '华东商贸')]),
        ])
        app, dep = _override_user({'stockout_manage'})
        try:
            with patch('fastapi_app.services.ocr._order_preview.extract_text',
                       return_value=CHAT_PAGES):
                response = await client.post(URL, files=upload())
        finally:
            del app.dependency_overrides[dep]
        assert response.status_code == 200
        assert response.json()['success'] is True

    @pytest.mark.asyncio
    async def test_order_manage_still_allowed(self, client, mock_db):
        mock_db.execute = AsyncMock(side_effect=[
            make_rows([make_product(7, '儿童保温杯500ml')]),
            make_rows([make_customer(3, '华东商贸')]),
        ])
        app, dep = _override_user({'order_manage'})
        try:
            with patch('fastapi_app.services.ocr._order_preview.extract_text',
                       return_value=CHAT_PAGES):
                response = await client.post(URL, files=upload())
        finally:
            del app.dependency_overrides[dep]
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_user_without_any_required_permission_403(self, client, mock_db):
        app, dep = _override_user(set())
        try:
            response = await client.post(URL, files=upload())
        finally:
            del app.dependency_overrides[dep]
        assert response.status_code == 403
        assert '权限不足' in response.json()['detail']
