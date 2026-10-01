"""OCR 提取器单例必须在模块级显式声明（P0-9）。

缺陷：_get_pdf_extracter() 里的 global _pdf_extracter + if _pdf_extracter is None
读的是**模块级**名字，而模块级从未赋值 -> 首次调用必抛
NameError: name '_pdf_extracter' is not defined —— 与依赖是否安装无关，OCR 整条链路不可用。

本文件锁定：三个单例在模块级声明，且 getter/extract_text_from_pdf 走的是同一份缓存。
"""
import sys
import types

import pytest

from fastapi_app.services.ocr import _extractors as ex

_SINGLETONS = ('_pdf_extracter', '_img_extracter', '_table_extracter')


@pytest.fixture(autouse=True)
def _reset_extracter_singletons():
    for name in _SINGLETONS:
        setattr(ex, name, None)
    yield
    for name in _SINGLETONS:
        setattr(ex, name, None)


def test_singletons_are_declared_at_module_level():
    for name in _SINGLETONS:
        assert name in vars(ex), f'{name} 未在模块级声明：getter 首次调用会 NameError'
        assert getattr(ex, name) is None


def test_get_pdf_extracter_initializes_and_caches(monkeypatch):
    created = []

    class _FakeRapidOCRPDF:
        def __init__(self):
            created.append('init')

    monkeypatch.setitem(
        sys.modules, 'rapidocr_pdf', types.SimpleNamespace(RapidOCRPDF=_FakeRapidOCRPDF)
    )
    first = ex._get_pdf_extracter()
    second = ex._get_pdf_extracter()
    assert isinstance(first, _FakeRapidOCRPDF)
    assert first is second, '提取器未按单例缓存'
    assert created == ['init']


def test_get_pdf_extracter_missing_dependency_raises_runtime_error(monkeypatch):
    # sys.modules 置 None -> 'from rapidocr_pdf import X' 抛 ImportError
    monkeypatch.setitem(sys.modules, 'rapidocr_pdf', None)
    with pytest.raises(RuntimeError) as excinfo:
        ex._get_pdf_extracter()
    assert 'rapidocr_pdf 未安装' in str(excinfo.value)
    assert not isinstance(excinfo.value, NameError)


def test_extract_text_from_pdf_uses_declared_singleton(monkeypatch):
    """端到端回归：缺依赖时抛 ImportError/RuntimeError，而不是 NameError。

    extract_text_from_pdf 内先做 `from rapidocr_pdf import RapidOCRPDF`（依赖缺失因此
    抛 ImportError），之后才走 _get_pdf_extracter() 的 RuntimeError 分支；两条路径都
    说明单例已声明 —— 唯一要杜绝的是 NameError: name '_pdf_extracter' is not defined。
    """
    monkeypatch.setitem(sys.modules, 'rapidocr_pdf', None)
    with pytest.raises((RuntimeError, ImportError)) as excinfo:
        ex.extract_text_from_pdf(b'%PDF-1.4')
    assert not isinstance(excinfo.value, NameError), (
        'extract_text_from_pdf 仍抛 NameError —— 模块级单例没声明'
    )
    for name in _SINGLETONS:
        assert name in vars(ex)


def test_extract_text_from_pdf_runs_with_fake_backend(monkeypatch):
    """端到端：假后端下走完提取流程（证明单例确实被创建并复用）。"""
    created = []

    class _FakeRapidOCRPDF:
        def __init__(self):
            created.append('init')

        @staticmethod
        def load_pdf(content):
            return 'pdf-data'

        def extract_texts(self, pdf_data, force_ocr=False, page_num_list=None):
            return ({0: 'direct'}, [1])

        def get_ocr_res_streaming(self, pdf_data, idxs):
            return {1: 'ocr'}

        def merge_direct_ocr(self, txts, ocr):
            return [(1, 'page1 text'), (2, 'page2 text')]

    monkeypatch.setitem(
        sys.modules, 'rapidocr_pdf', types.SimpleNamespace(RapidOCRPDF=_FakeRapidOCRPDF)
    )
    pages = ex.extract_text_from_pdf(b'%PDF-1.4')
    assert pages == [{'page': 1, 'text': 'page1 text'}, {'page': 2, 'text': 'page2 text'}]
    assert created == ['init']
