"""OCR PDF 预览的页数/总像素预算（2026-11-16 审计 Medium）。

拦哪种错：`_pdf_to_images` 把每页 `get_pixmap(dpi=200)` 的位图**全部**累积进 list，
且没有任何页数/像素上限 —— 200dpi 的 A4 单页约 3.9M 像素（RGB 约 11MB），一本 200 页
的 PDF 就是 2GB+，一个预览请求即可把进程打挂。

自包含：fitz/cv2/numpy 一律换成假模块（CI 只装 base 依赖，可选 OCR 栈可能不存在），
不解析真 PDF、不加载任何模型。
"""
import sys
import types
from io import BytesIO

import pytest

from fastapi_app.services.ocr import _extractors as ex

PREVIEW_URL = '/api/v1/ocr-import/preview'


class _FakePixmap:
    def __init__(self, width: int, height: int) -> None:
        self.width = width
        self.height = height

    def tobytes(self, _fmt: str) -> bytes:
        return b'fake-png-bytes'


class _FakePage:
    def __init__(self, width: int, height: int, rendered: list[int]) -> None:
        self._width = width
        self._height = height
        self._rendered = rendered

    def get_pixmap(self, dpi: int = 200):
        # dpi 必须是常量而不是调用方随手传的值：预算按它折算，改大就没意义了
        assert dpi == ex._PDF_RENDER_DPI, f'渲染 dpi 断言失败: {dpi}'
        self._rendered.append(dpi)
        return _FakePixmap(self._width, self._height)


class _FakeDoc:
    def __init__(self, pages: list[_FakePage]) -> None:
        self._pages = pages
        self.page_count = len(pages)
        self.closed = False

    def __iter__(self):
        return iter(self._pages)

    def close(self) -> None:
        self.closed = True


def _install_fake_pdf(monkeypatch, specs: list[tuple[int, int]]):
    """装上假 fitz/cv2/numpy 与给定页尺寸序列，返回 (doc, rendered 次数列表)。"""
    rendered: list[int] = []
    doc = _FakeDoc([_FakePage(w, h, rendered) for w, h in specs])
    monkeypatch.setitem(sys.modules, 'fitz', types.SimpleNamespace(open=lambda **_kw: doc))
    monkeypatch.setitem(
        sys.modules, 'cv2',
        types.SimpleNamespace(IMREAD_COLOR=1, imdecode=lambda *_args: object()),
    )
    monkeypatch.setitem(
        sys.modules, 'numpy',
        types.SimpleNamespace(uint8='uint8', frombuffer=lambda data, dtype=None: data),
    )
    # 依赖安装检查一并跳过：CI 只装 base，numpy/cv2/fitz 可能真的不存在
    monkeypatch.setattr(ex, '_require_modules', lambda *_names: None)
    return doc, rendered


# ============================================================================
# 预算判定
# ============================================================================
def test_pdf_over_page_limit_rejected_before_rendering(monkeypatch):
    """超页数上限直接拒绝，且**一页都不渲染**（渲染才是吃内存的那一步）。"""
    over_limit = ex._MAX_PDF_PAGES + 10
    doc, rendered = _install_fake_pdf(monkeypatch, [(200, 200)] * over_limit)

    with pytest.raises(ex.OcrPageBudgetExceededError) as excinfo:
        list(ex._pdf_to_images(b'%PDF-fake'))

    assert str(ex._MAX_PDF_PAGES) in str(excinfo.value)
    assert rendered == [], '超页数的文档不得先渲染一遍再报错'
    assert doc.closed is True, '拒绝路径也必须关闭文档句柄'


def test_pdf_total_pixels_over_budget_rejected(monkeypatch):
    """单页就超总像素上限（20000×20000 = 4 亿）同样拦得住。"""
    _install_fake_pdf(monkeypatch, [(20000, 20000)])

    with pytest.raises(ex.OcrPageBudgetExceededError):
        list(ex._pdf_to_images(b'%PDF-fake'))


def test_budget_error_is_business_error_not_a_swallowed_type():
    """必须是业务异常，且**不能**是 RuntimeError/ValueError/OSError。

    那三个类型在 `_import.py` 里会被当成「识别失败，回退文本模式」吞掉 —— 预算是安全
    边界，被吞掉等于绕开（文本模式同样渲染整本 PDF）。
    """
    from fastapi_app.core.exceptions import BusinessError

    assert issubclass(ex.OcrPageBudgetExceededError, BusinessError)
    assert not issubclass(ex.OcrPageBudgetExceededError, (RuntimeError, ValueError, OSError))


# ============================================================================
# 正常页数照旧通过 / 逐页产出
# ============================================================================
def test_pdf_within_page_limit_yields_every_page(monkeypatch):
    """正常页数行为不变：每页一张图，消费完关闭文档。"""
    doc, rendered = _install_fake_pdf(monkeypatch, [(300, 300)] * 3)

    images = list(ex._pdf_to_images(b'%PDF-fake'))

    assert len(images) == 3
    assert len(rendered) == 3
    assert doc.closed is True


def test_pdf_pages_are_yielded_lazily(monkeypatch):
    """逐页产出：取第一页时不得把整本 5 页都渲染进内存（原实现就是整本缓存）。"""
    _doc, rendered = _install_fake_pdf(monkeypatch, [(300, 300)] * 5)

    generator = ex._pdf_to_images(b'%PDF-fake')
    first = next(generator)
    try:
        assert first is not None
        assert len(rendered) == 1, f'取一页却渲染了 {len(rendered)} 页，说明仍是整本缓存'
    finally:
        generator.close()


def test_extract_table_structure_propagates_page_budget(monkeypatch):
    """消费方（表格识别）必须把预算异常抛出去，而不是静默返回 []。"""
    _install_fake_pdf(monkeypatch, [(200, 200)] * (ex._MAX_PDF_PAGES + 1))
    monkeypatch.setattr(ex, '_get_table_extracter', lambda: (lambda *_a: None))
    monkeypatch.setattr(ex, '_get_img_extracter', lambda: (lambda *_a: None))

    with pytest.raises(ex.OcrPageBudgetExceededError):
        ex.extract_table_structure(b'%PDF-fake', 'shipping.pdf')


# ============================================================================
# 端点映射：4xx 而不是 500
# ============================================================================
def _png_bytes() -> bytes:
    """真 PNG：端点有文件头（魔数）校验，伪造字节会先被 400 拦掉，测不到预算分支"""
    from PIL import Image

    buf = BytesIO()
    Image.new('RGB', (8, 8), 'white').save(buf, 'PNG')
    return buf.getvalue()


@pytest.mark.asyncio
async def test_preview_returns_400_when_page_budget_exceeded(client, monkeypatch):
    """超预算 → 400 且带上限说明（映射成 500 的话前端只会看到「服务器内部错误」）。"""
    message = f'PDF 共 {ex._MAX_PDF_PAGES + 10} 页，超过识别上限 {ex._MAX_PDF_PAGES} 页'
    monkeypatch.setattr(
        'fastapi_app.services.ocr_service.extract_table_structure',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            ex.OcrPageBudgetExceededError(message)
        ),
    )

    response = await client.post(
        PREVIEW_URL, files=[('file', ('doc.png', BytesIO(_png_bytes()), 'image/png'))]
    )

    assert response.status_code == 400
    assert str(ex._MAX_PDF_PAGES) in response.json()['detail']
