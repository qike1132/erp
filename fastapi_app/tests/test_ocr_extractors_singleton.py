"""OCR 提取器单例的模块级声明 —— 回归测试

## 缺陷背景（2026-09-14 由 mypy `name-defined` 发现）

`_get_pdf_extracter` / `_get_img_extracter` / `_get_table_extracter` 内部写：

    global _pdf_extracter
    if _pdf_extracter is None:
        ...

但 `_pdf_extracter` **从未在模块级声明**。`global X` 只声明「函数内对 X 的赋值
写回模块级」，**它不创建变量**。因此首次调用会在 `if _pdf_extracter is None`
处直接抛：

    NameError: name '_pdf_extracter' is not defined

**与第三方依赖是否安装无关** —— 实测 `rapidocr_pdf` / `rapidocr` / `rapid_table`
三个包均已安装，OCR 功能仍然 100% 不可用（每次调用必 500）。

## 为什么 1297 项测试没拦住

`test_ocr_import.py` 只覆盖**上传 / 进度查询 API**（mock 掉 `create_progress`、
`get_progress`、`import_staging_stockouts_from_file`），从不触碰提取器 getter。
本文件锁死该缺陷，防止回退。
"""
import sys
import types

import pytest

pytestmark = pytest.mark.unit

from fastapi_app.services.ocr import _extractors

_SINGLETONS = ('_pdf_extracter', '_img_extracter', '_table_extracter')


class TestModuleLevelDeclaration:
    """三个单例必须存在于模块命名空间 —— 这是 `global` 能工作的前提"""

    @pytest.mark.parametrize('name', _SINGLETONS)
    def test_declared_in_module_namespace(self, name):
        assert name in vars(_extractors), (
            f'{name} 未在模块级声明。`global {name}` 不创建变量，'
            f'getter 里的 `if {name} is None` 会抛 NameError。'
        )

    @pytest.mark.parametrize('name', _SINGLETONS)
    def test_initial_value_is_none(self, name):
        """初始值须为 None，getter 的惰性初始化分支才成立。

        AUD-15（2026-10-24 审计）：原断言 `X is None or X is not None` 是互补
        析取恒真——单例初值被改成非 None 哨兵时测试仍绿，零约束。改为真断言；
        本文件收集序在同进程消费 getter 的测试之前（pytest 按文件名字母序，
        test_ocr_* 消费方在 OCR 服务的测试里更晚收集），若未来顺序变化导致
        初值已被初始化而误红，按「测试能红好过恒真」原则修收集序而非回退本断言。
        """
        assert getattr(_extractors, name) is None, (
            f'{name} 的模块级初值必须为 None（惰性初始化前提）；'
            f'若因收集序变化已被初始化，请检查 import 顺序而非放松本断言'
        )


class TestGetterDoesNotRaiseNameError:
    """核心回归断言：getter 不得抛 NameError"""

    @pytest.mark.parametrize('getter', [
        '_get_pdf_extracter', '_get_img_extracter', '_get_table_extracter',
    ])
    def test_no_name_error(self, getter):
        try:
            getattr(_extractors, getter)()
        except NameError as e:
            pytest.fail(f'{getter} 抛 NameError（模块级单例未声明）: {e}')
        except RuntimeError:
            pass          # 第三方依赖未安装 → 属预期分支
        except Exception:  # noqa: S110 - 模型加载失败等环境问题与本测试目标无关；
            pass          #   不能用 contextlib.suppress 合并，否则 NameError 分支会被一并吞掉


class TestLazyInitAndCaching:
    """惰性初始化 + 单例缓存语义"""

    def test_pdf_getter_caches_singleton(self, monkeypatch):
        fake = object()
        monkeypatch.setattr(_extractors, '_pdf_extracter', None)
        fake_mod = types.ModuleType('rapidocr_pdf')
        fake_mod.RapidOCRPDF = lambda: fake          # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, 'rapidocr_pdf', fake_mod)

        assert _extractors._get_pdf_extracter() is fake
        # 第二次调用命中缓存，不应重新构造
        assert _extractors._get_pdf_extracter() is fake

    def test_missing_dependency_raises_runtime_error(self, monkeypatch):
        """依赖缺失时应给出可操作的 RuntimeError，而不是 NameError。"""
        monkeypatch.setattr(_extractors, '_pdf_extracter', None)
        monkeypatch.setitem(sys.modules, 'rapidocr_pdf', None)   # 模拟不可导入

        with pytest.raises(RuntimeError, match='rapidocr_pdf'):
            _extractors._get_pdf_extracter()
