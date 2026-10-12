"""产品导入预览端点（`POST /batch/batch-import/preview`）的路由与入参契约

只验证「路由真的挂上了」与「坏输入不写库、给出可读错误」。逐行分类语义在
``tests/test_product_import_preview.py``（真实测试库）里覆盖。

**为什么单独锁路由**：这个仓库此前在同一个 API 上踩过 404 —— 前端调
``/batch/import-products`` 而实际注册的是 ``/batch/batch-import``，产品导入稳定 404。
新增端点的第一道保险就是「路径写死在这儿，跑得过」。
"""
from io import BytesIO

import pytest

URL = '/api/v1/batch/batch-import/preview'


def upload(name: str, content: bytes) -> list:
    return [('file', (name, BytesIO(content), 'application/vnd.ms-excel'))]


class TestPreviewRoute:
    @pytest.mark.asyncio
    async def test_route_exists_and_rejects_non_xlsx(self, client, mock_db):
        """路径存在（非 404/405），且 .txt 在解析前就被拦下（不触碰数据库）。"""
        response = await client.post(URL, files=upload('x.txt', b'not excel'))

        assert response.status_code == 200, response.text
        body = response.json()
        assert body['success'] is False
        assert '.xlsx' in body['message'], body['message']

    @pytest.mark.asyncio
    async def test_route_is_not_shadowed_by_import_endpoint(self, client, mock_db):
        """预览路径不能被 ``/batch-import`` 抢先匹配（前缀相同、后缀不同）。"""
        response = await client.post(URL, files=upload('x.txt', b'x'))

        assert response.status_code != 405, '被 /batch-import 抢了路由（方法不允许）'
        assert 'rows' in response.json(), '未返回预览结构，可能命中了导入端点'
