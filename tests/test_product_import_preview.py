"""产品批量导入的「预览」链路（``POST /batch/batch-import/preview`` 的服务层）

预览的意义：用户在**确认之前**看到的就是「将要发生什么」。因此它必须只分类、
绝不写库。本文件锁住三件事：

1. **预览跑完，产品表与上传目录都没有变化**（核心回归——预览偷偷写库是这套设计
   最容易犯的错，而且肉眼看不出来）；
2. 行分类正确（新增 / 补全 / 跳过 / 错误），且「补全」给出改前改后，客户未匹配
   要能一眼看出来（这正是用户反馈「导入后没有客户和价格」的那个点）；
3. 预览的汇总与**随后真实导入**的结果对得上——防止预览与导入两套口径各自漂移。

走真实测试库（conftest 的 test_engine 由 ``Base.metadata.create_all`` 建表）；
对象存储换成 tmp_path，避免往生产的 static/uploads 写测试文件。
"""
import io
from pathlib import Path

import openpyxl
import pytest
from sqlalchemy import select

from fastapi_app.services import batch_import_service, storage_service
from fastapi_app.shared_models import Customer, Product, ProductCustomer

HEADERS = ['客户', '产品名称', '工厂', '69码', '产品价格', '图片']


class _Upload:
    """满足 ``schemas.batch.ExcelUpload`` 协议的最小上传对象。"""

    def __init__(self, filename: str, content: bytes):
        self.filename = filename
        self._buf = io.BytesIO(content)

    async def read(self, size: int = -1) -> bytes:
        return self._buf.read(size)


def _make_workbook(sheet_name: str, rows: list[list]) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet_name
    ws.append(HEADERS)
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@pytest.fixture
def local_storage(tmp_path, monkeypatch):
    """把对象存储换到 tmp_path，避免往生产的 static/uploads 写测试图片。"""
    monkeypatch.setattr(
        storage_service, '_backend', storage_service.LocalStorageBackend(base_dir=tmp_path),
    )


async def _add_customer(db, name: str) -> Customer:
    existing = (await db.execute(select(Customer).where(Customer.name == name))).scalars().first()
    if existing is not None:
        return existing
    customer = Customer(name=name)
    db.add(customer)
    await db.flush()
    return customer


async def _add_product(db, name: str, *, price=0, factory='') -> Product:
    product = Product(name=name, barcode='', price=price, factory=factory,
                      initial_stock=0, current_stock=0)
    db.add(product)
    await db.flush()
    return product


async def _product_by_name(db, name: str) -> Product | None:
    return (await db.execute(select(Product).where(Product.name == name))).scalars().first()


# ==================== 1. 预览不写库（核心回归） ====================


async def test_preview_writes_nothing_to_db_or_disk(async_db_session, local_storage, tmp_path):
    """预览跑完：产品没落库、上传目录一个文件都没多。

    这是整套设计的地基——预览若偷偷写库，用户会在「取消」之后发现数据已经变了。
    """
    content = _make_workbook('新品录入', [['顺发玩具', '预览不写库-A', '东莞', None, 12.5, None]])

    result = await batch_import_service.preview_products_service(
        async_db_session, _Upload('x.xlsx', content))

    assert result.success, result.message
    assert result.summary.create == 1, result.summary
    # flush 把「预览若偷偷 db.add 的对象」推到库里 —— 会话是 autoflush=False，
    # 不 flush 的话挂起的 INSERT 会被查询忽略，这条断言就成了摆设。
    await async_db_session.flush()
    assert await _product_by_name(async_db_session, '预览不写库-A') is None, '预览把产品写进了数据库'
    files = [p for p in tmp_path.rglob('*') if p.is_file()]
    assert files == [], f'预览产生了文件: {files}'


async def test_preview_does_not_mutate_existing_product(async_db_session, local_storage):
    """已存在的空价格产品，预览只报告「将补全」，绝不真的改它。"""
    product = await _add_product(async_db_session, '预览不改库-零价', price=0)
    content = _make_workbook('新品录入', [['顺发玩具', '预览不改库-零价', '东莞', None, 15, None]])

    result = await batch_import_service.preview_products_service(
        async_db_session, _Upload('x.xlsx', content))

    assert result.rows[0].action == 'backfill', result.rows[0]
    # 同上：flush 后才能看见「改在内存里没落库」之外的真写入
    await async_db_session.flush()
    await async_db_session.refresh(product)
    assert float(product.price) == 0, f'预览把价格改了: {product.price!r}'
    assert (product.factory or '') == '', f'预览把工厂改了: {product.factory!r}'


# ==================== 2. 行分类 ====================


async def test_preview_classifies_new_backfill_skip_and_error(async_db_session, local_storage):
    """四种动作各来一行，逐行核对分类与「改前改后」。"""
    customer = await _add_customer(async_db_session, '顺发玩具')
    await _add_product(async_db_session, '预览分类-零价', price=0)
    done = await _add_product(async_db_session, '预览分类-已完整', price=9, factory='东莞')
    async_db_session.add(ProductCustomer(product_id=done.id, customer_id=customer.id))
    await async_db_session.flush()

    content = _make_workbook('新品录入', [
        ['顺发玩具', '预览分类-新品', '东莞', None, 12.5, None],   # 行2 新增
        ['顺发玩具', '预览分类-零价', '东莞', None, 15, None],     # 行3 补全（价格 0 → 15）
        ['顺发玩具', '预览分类-已完整', '东莞', None, 9, None],    # 行4 跳过（无可补）
        ['顺发玩具', None, '东莞', None, 5, None],                  # 行5 错误（缺产品名称）
    ])

    result = await batch_import_service.preview_products_service(
        async_db_session, _Upload('x.xlsx', content))

    by_row = {r.row_no: r for r in result.rows}
    assert by_row[2].action == 'create', by_row[2]
    assert by_row[2].name == '预览分类-新品' and by_row[2].price == '12.50'
    assert by_row[3].action == 'backfill', by_row[3]
    assert any('15' in c for c in by_row[3].changes), f'未给出改前改后: {by_row[3].changes}'
    assert by_row[4].action == 'skip', by_row[4]
    assert by_row[5].action == 'error', by_row[5]

    assert (result.summary.create, result.summary.backfill,
            result.summary.skip, result.summary.error) == (1, 1, 1, 1), result.summary


async def test_preview_flags_duplicate_rows_in_file(async_db_session, local_storage):
    """同一文件内产品名重复：只保留第一次，重复行标「跳过」。"""
    content = _make_workbook('新品录入', [
        ['顺发玩具', '预览重复-X', '东莞', None, 5, None],
        ['顺发玩具', '预览重复-X', '东莞', None, 5, None],
    ])

    result = await batch_import_service.preview_products_service(
        async_db_session, _Upload('x.xlsx', content))

    assert [r.action for r in result.rows] == ['create', 'skip'], result.rows
    assert result.summary.create == 1 and result.summary.skip == 1


async def test_preview_flags_unknown_customer(async_db_session, local_storage):
    """客户名不在主数据：行仍会新增，但 customer_matched=False 且给出可见提示。"""
    content = _make_workbook('新品录入', [['查无此客户', '预览-孤儿客户', '东莞', None, 5, None]])

    result = await batch_import_service.preview_products_service(
        async_db_session, _Upload('x.xlsx', content))

    row = result.rows[0]
    assert row.action == 'create'
    assert row.customer_name == '查无此客户'
    assert row.customer_matched is False
    assert any('不存在于客户主数据' in m for m in row.messages), row.messages


async def test_preview_treats_unstorable_image_row_as_skip(async_db_session, local_storage):
    """已存在产品 + 图片格式无法识别：预览必须判「跳过」，与导入同口径。

    回归（2026-10-13）：预览原先无条件把「带图」算作改动（backfill / 更新图片），
    而导入侧 ``_save_imported_image`` 认不出魔数（EMF/BMP/TIFF 等 WPS 单元格图片）
    就跳过该图、该行不算改动 —— 预览高估写入数，与
    ``test_preview_summary_matches_real_import`` 锁定的口径相悖。
    """
    await _add_product(async_db_session, '预览坏图-已存在', price=0)
    await async_db_session.flush()

    row = {'客户': '', '产品名称': '预览坏图-已存在', '工厂': '', '69码': '',
           '产品价格': '', '图片': '=DISPIMG("ID_bad",1)'}
    context = {'cell_images': {'ID_bad': b'EMF-not-an-image'},
               'customer_cache': {}, 'seen_names': set()}

    preview_row = await batch_import_service._classify_product_row(
        async_db_session, row, 2, context)

    # 该行确实带着图片字节（否则这条测试测的不是图片那条分支）
    assert preview_row.has_image is True
    assert preview_row.action == 'skip', preview_row
    assert '更新图片' not in preview_row.changes, preview_row.changes
    assert any('图片' in m for m in preview_row.messages), preview_row.messages


# ==================== 3. 预览与真实导入口径一致 ====================

async def test_preview_summary_matches_real_import(async_db_session, local_storage):
    """同一文件：预览的汇总必须能预测真实导入的 imported / skipped。

    这条是防「两套口径漂移」的哨兵——预览说 2 条会写入，导入就必须写入 2 条。
    """
    await _add_customer(async_db_session, '顺发玩具')
    await _add_product(async_db_session, '预览一致-零价', price=0)
    content = _make_workbook('新品录入', [
        ['顺发玩具', '预览一致-新品', '东莞', None, 12.5, None],   # 新增
        ['顺发玩具', '预览一致-零价', '东莞', None, 15, None],     # 补全
        [None, None, None, None, None, None],                       # 无法导入
    ])

    preview = await batch_import_service.preview_products_service(
        async_db_session, _Upload('x.xlsx', content))
    result = await batch_import_service.import_products_service(
        async_db_session, _Upload('x.xlsx', content))

    assert result.imported == preview.summary.create + preview.summary.backfill, (
        f'预览说写入 {preview.summary.create + preview.summary.backfill} 条，'
        f'实际写入 {result.imported} 条')
    assert result.skipped == preview.summary.skip + preview.summary.error, (
        f'预览说跳过 {preview.summary.skip + preview.summary.error} 条，'
        f'实际跳过 {result.skipped} 条')


async def test_preview_summary_matches_real_import_on_in_file_duplicate(
    async_db_session, local_storage,
):
    """同一文件内两行同名：预览说「跳过」，导入就必须只写 1 条。

    2026-10-12 独立评审发现的口径漂移：第二行若落进「已存在」分支，会把第一行刚建的
    同名产品补全并计数 —— 预览说写入 1 条、导入写 2 条。重复行只按「跳过 + 回显」处置，
    它的字段不得并进上一行建的产品。
    """
    await _add_customer(async_db_session, '顺发玩具')
    content = _make_workbook('新品录入', [
        ['顺发玩具', '预览一致-同名重复', None, None, None, None],   # 新建（价格/工厂都空）
        ['顺发玩具', '预览一致-同名重复', '东莞', None, 15, None],   # 文件内同名 → 跳过
    ])

    preview = await batch_import_service.preview_products_service(
        async_db_session, _Upload('x.xlsx', content))
    result = await batch_import_service.import_products_service(
        async_db_session, _Upload('x.xlsx', content))

    assert preview.summary.create + preview.summary.backfill == 1, preview.summary
    assert preview.summary.skip == 1, preview.summary
    assert result.imported == preview.summary.create + preview.summary.backfill, (
        f'预览说写入 {preview.summary.create + preview.summary.backfill} 条，'
        f'实际写入 {result.imported} 条')
    assert result.skipped == preview.summary.skip + preview.summary.error, (
        f'预览说跳过 {preview.summary.skip + preview.summary.error} 条，'
        f'实际跳过 {result.skipped} 条')
    product = (await async_db_session.execute(
        select(Product).where(Product.name == '预览一致-同名重复'))).scalars().one()
    assert float(product.price or 0) == 0, f'重复行的价格不该并进上一行建的产品: {product.price!r}'
    assert not (product.factory or ''), f'重复行的工厂不该并进上一行建的产品: {product.factory!r}'


async def test_core_import_skips_in_file_duplicate_rows(async_db_session):
    """core 路径（综合导入 / ARQ）对文件内同名重复行同样只跳过、不合并计数。"""
    await _add_customer(async_db_session, '顺发玩具')
    rows = [
        {'客户': '顺发玩具', '产品名称': '预览一致-core同名', '工厂': None, '产品价格': None},
        {'客户': '顺发玩具', '产品名称': '预览一致-core同名', '工厂': '东莞', '产品价格': 15},
    ]

    count, messages = await batch_import_service.import_products_from_data(async_db_session, rows)

    assert count == 1, messages
    product = (await async_db_session.execute(
        select(Product).where(Product.name == '预览一致-core同名'))).scalars().one()
    assert float(product.price or 0) == 0, f'重复行的价格不该并进来: {product.price!r}'


# ==================== 4. 文件级校验 ====================


async def test_preview_rejects_non_excel(async_db_session):
    result = await batch_import_service.preview_products_service(
        async_db_session, _Upload('x.txt', b'not an excel file'))

    assert result.success is False
    assert result.message


async def test_preview_rejects_corrupt_xlsx(async_db_session):
    """扩展名对但内容不是 Excel → 明确报错（解析层拦下），不静默空跑。"""
    result = await batch_import_service.preview_products_service(
        async_db_session, _Upload('x.xlsx', b'PK\x03\x04 not really a workbook'))

    assert result.success is False
    assert result.message, '损坏文件必须给出可见错误'


async def test_preview_falls_back_to_first_sheet_like_import(async_db_session, local_storage):
    """没有「新品录入」/「产品管理」Sheet 时回退首个 Sheet —— 与导入同口径。

    解析层 `_find_target_sheet` 的既定行为是「匹配不到就用首个 Sheet」，预览不能比
    导入更严格，否则会出现「预览报错、导入却成功」的错位。
    """
    content = _make_workbook('无关Sheet', [['顺发玩具', '预览回退-首个Sheet', '东莞', None, 6, None]])

    result = await batch_import_service.preview_products_service(
        async_db_session, _Upload('x.xlsx', content))

    assert result.success, result.message
    assert result.rows[0].name == '预览回退-首个Sheet', result.rows[0]


def test_template_path_constant_is_shared():
    """守卫：模板资产仍在本文件假定的位置（导入/预览共用同一模板）。"""
    assert (Path(__file__).resolve().parent.parent / 'static' / 'files'
            / '统一导入模板.xlsx').is_file()
