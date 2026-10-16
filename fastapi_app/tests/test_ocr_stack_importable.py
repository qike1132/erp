"""OCR 栈传导依赖可导入 —— 回归测试

## 缺陷背景（2026-10-16 复现）

生产 venv 里 `rapidocr` / `rapid-table` / `rapidocr-pdf` 三个包**都已安装**
（连 500MB 的 onnx 模型文件都在），但 `import rapidocr` 仍然炸：

    ModuleNotFoundError: No module named 'antlr4'

链条是：rapidocr/rapid-table → `omegaconf` → `antlr4-python3-runtime`。
venv 里装的是 **omegaconf 2.3.1**，它的 METADATA 写着
`Requires-Dist: antlr4-python3-runtime==4.9.*`；而 venv 里没有 antlr4。
上游 **omegaconf 2.4.0 去掉了 antlr4 依赖**，`requirements/ocr.lock` 锁的
也正是 2.4.0 —— 所以 venv 里那份 2.3.1 是装漏了（不在锁内）。

于是 OCR 端点的表现是「可读的 503 + 修复指引」，而不是 500，但功能仍然坏了：
用户粘贴图片只看到一句「OCR 依赖未安装」，排查方向被引向「照 ocr.txt 重装」，
而重装并**不能**修好（见下一条）。

## 为什么 ocr.txt / lock 修不了它

实测 `uv pip compile requirements/ocr.txt` **同样不解析出 antlr4**：
它钉的 omegaconf==2.4.0，而 2.4.0 已经不再依赖 antlr4。所以无论跟着
`ocr.txt` 还是 `ocr.lock` 走，只要最后一步用的是 pip 且解析到 2.3.1，
这个坑就会重现。`test_ocr_dependency_guard.py` 只锁「缺依赖时报错格式」，
摸不到「到底能不能真的 import」。

## 本文件锁死什么

直接 import 三个 OCR 引擎包。它们在 venv 里装了就必须能 import ——
这条测试现在通过；把 omegaconf 退回 2.3.1 就会重新
`ModuleNotFoundError: No module named 'antlr4'`，即变红。

CI（base 层）**不装** OCR 栈，故三个包在 CI 上缺；缺时按设计 skip，
不当假红。只有装了却 import 失败（本事故的真形态）才算失败。
"""
import importlib
import importlib.util

import pytest

pytestmark = pytest.mark.unit

# OCR 引擎包：装了模型也白搭，import 不过就是全功能不可用。
_OCR_PACKAGES = ('rapidocr', 'rapidocr_pdf', 'rapid_table')

# omegaconf 是传导依赖：rapidocr/rapid-table 顶层 import 它
# （rapidocr/main.py: `from omegaconf import DictConfig`），
# 而 omegaconf 2.3.x 又 import antlr4 —— 这是本事故的断点。
_TRANSITIVE_DEPS = ('omegaconf', 'cv2', 'numpy')


def _installed(name: str) -> bool:
    """包是否已安装（不 import，避免触发副作用）"""
    return importlib.util.find_spec(name) is not None


@pytest.mark.skipif(
    not all(_installed(n) for n in _OCR_PACKAGES),
    reason='OCR 可选栈未安装（如 CI base 层）——按设计跳过，非失败',
)
@pytest.mark.parametrize('name', _OCR_PACKAGES)
def test_ocr_engine_package_imports(name: str):
    """包已安装就必须可 import —— 装了却 import 失败即本事故重演"""
    try:
        importlib.import_module(name)
    except ImportError as e:
        pytest.fail(
            f'{name} 已安装但 import 失败：{e}。'
            f'典型根因是传导依赖缺失（omegaconf→antlr4），'
            f'请核对 requirements/ocr.lock 中 omegaconf 的版本是否被 pip 解析成 2.3.x'
        )


@pytest.mark.skipif(
    not all(_installed(n) for n in _OCR_PACKAGES),
    reason='OCR 可选栈未安装（如 CI base 层）——按设计跳过，非失败',
)
@pytest.mark.parametrize('name', _TRANSITIVE_DEPS)
def test_ocr_transitive_dep_imports(name: str):
    """传导依赖同样必须可 import：本事故的断点恰在这一层（omegaconf→antlr4）"""
    try:
        importlib.import_module(name)
    except ImportError as e:
        pytest.fail(
            f'OCR 传导依赖 {name} import 失败：{e}。'
            f'omegaconf 2.3.x 依赖 antlr4-python3-runtime==4.9.*，'
            f'而 PyPI 上该版本无二进制 wheel，流水线重装极易漏掉它；'
            f'omegaconf 2.4.0 已去掉 antlr4 依赖，注意别被 pip 降级回 2.3.x'
        )
