"""产品导入只有一份行逻辑（2026-10-17 审计 Z04-R3）

端点用的 ``import_products_service`` 此前内嵌第二套逐行写入（字段别名 / 批内同名 /
只补空值 / 图片落库），与综合导入·ARQ 用的 ``import_products_from_data`` 各持一份，
改一处漏一处。现在端点委托 core，本文件锁住两件事：

1. **结构**：端点函数里不得再出现产品行写入 —— 防止第二份实现长回来；
2. **收敛后的语义**：批内同名带图行的图片要落地（core 口径），单行 DB 异常只回滚
   本行（savepoint 隔离，端点级用户可见行为不变）。
"""
import inspect

from sqlalchemy import select

from fastapi_app.services import batch_import_core, batch_import_service
from fastapi_app.shared_models import Product

_FAKE_IMAGE_KEY = 'uploads/fake.webp'
_FAKE_PNG = b'\x89PNG\r\n\x1a\n' + b'\x00' * 8


class _Upload:
    """满足 ``schemas.batch.ExcelUpload`` 协议的最小上传对象。"""

    filename = 'x.xlsx'


def _patch_sheet(monkeypatch, rows: list[dict], cell_images: dict[str, bytes] | None = None) -> None:
    """把「读文件」这步换成给定行 —— 本文件测行逻辑，不重复测 xlsx 解析。"""
    images = cell_images or {}

    async def _read(_file):
        return rows, images, None

    monkeypatch.setattr(batch_import_service, '_validate_xlsx_file', lambda _f: None)
    monkeypatch.setattr(batch_import_service, '_read_product_sheet', _read)


def _row(name: str, price=3, image: str | None = None) -> dict:
    return {'客户': None, '产品名称': name, '工厂': None, '69码': None,
            '产品价格': price, '图片': image}


async def test_endpoint_delegates_row_logic_to_core() -> None:
    """端点函数里不得再有产品行写入：出现即说明第二份实现长回来了。"""
    src = inspect.getsource(batch_import_service.import_products_service)

    assert 'import_products_from_data' in src, '端点未委托 core，行逻辑又分成两份'
    for forbidden in ('Product(', 'ProductCustomer(', '_save_imported_image('):
        assert forbidden not in src, f'端点里残留行写入 {forbidden}，与 core 重复维护'


async def test_intra_file_duplicate_with_image_lands_image(async_db_session, monkeypatch):
    """同名第二行带图：图片要补进先建的那条，而不是整行连同图片一起丢掉。"""
    _patch_sheet(monkeypatch, [
        _row('收敛测试-同名带图', price=3),
        _row('收敛测试-同名带图', price=9, image='=DISPIMG("ID_A",1)'),
    ], {'ID_A': _FAKE_PNG})

    async def _fake_save(_db, _bytes, _name, _uploader_id):
        return _FAKE_IMAGE_KEY

    monkeypatch.setattr(batch_import_core, '_save_imported_image', _fake_save)

    result = await batch_import_service.import_products_service(async_db_session, _Upload())

    rows = (await async_db_session.execute(
        select(Product).where(Product.name == '收敛测试-同名带图'))).scalars().all()
    assert len(rows) == 1, [p.name for p in rows]
    assert rows[0].image == _FAKE_IMAGE_KEY, f'同名重复行的图片未落地: {rows[0].image!r}'
    assert result.imported == 1 and result.skipped == 1, result.message
    assert '图片已补入' in result.message, result.message


async def test_bad_row_rolls_back_only_itself(async_db_session, monkeypatch):
    """中间一行撞 DB 约束：本行跳过，前后两行照常落库（端点级 savepoint 隔离）。"""
    _patch_sheet(monkeypatch, [
        _row('收敛测试-存活前'),
        _row('X' * 300),  # product.name 是 varchar(100)，flush 时必炸
        _row('收敛测试-存活后'),
    ])

    result = await batch_import_service.import_products_service(async_db_session, _Upload())

    assert result.success, result.message
    assert result.imported == 2, result.message
    assert result.skipped == 1, result.message
    names = set((await async_db_session.execute(
        select(Product.name).where(Product.name.like('收敛测试-存活%')))).scalars().all())
    assert names == {'收敛测试-存活前', '收敛测试-存活后'}, names


async def test_endpoint_import_does_not_auto_generate_purchase_orders(
    async_db_session, monkeypatch,
):
    """产品导入**端点**不得触发采购单自动生成；综合导入 / ARQ 仍要触发。

    骨架合并（Z04-R3②）前，端点级导入只清缓存、不生成采购单；合并后端点改走
    core，若沿用 core 的默认 True，用户导入一次产品就会凭空多出采购单。
    """
    from fastapi_app.services.purchase import _auto_generate

    calls: list = []
    monkeypatch.setattr(
        _auto_generate, 'schedule_auto_generate_purchase_orders', lambda db: calls.append(db),
    )

    _patch_sheet(monkeypatch, [_row('端点不生成采购单', price=3)])
    await batch_import_service.import_products_service(async_db_session, _Upload())
    assert calls == [], '产品导入端点触发了采购单自动生成'

    # 综合导入 / ARQ 走 core 的默认行为：仍要登记采购单自动生成
    await batch_import_service.import_products_from_data(
        async_db_session, [_row('综合导入才生成采购单', price=3)],
    )
    assert len(calls) == 1, '综合导入路径丢失了采购单自动生成'
