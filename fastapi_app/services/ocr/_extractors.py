"""OCR 文本/表格提取器

从 ocr_service.py 按职责拆出,行为与原实现完全一致。
"""
import importlib
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.bmp', '.tiff', '.tif', '.webp'}

# OCR 可选依赖的安装指引（requirements/ocr.txt 同样是这一串）
_OCR_INSTALL_HINT = 'pip install -r requirements/ocr.txt（约 500MB，可选装）'


class OcrDependencyError(RuntimeError):
    """OCR 可选依赖缺失。

    刻意继承 RuntimeError：`_import.py` 里既有的 `except RuntimeError`（出货单表格
    识别失败即回退文本模式）继续生效；同时端点可以单独捕获它，把可执行的修复指引
    回给调用方，而不是只回一句「服务器内部错误」。

    背景（2026-10-08 生产事故）：新部署的 venv 漏装 OCR 可选栈，用户粘贴图片只看到
    「服务器内部错误」，真正的 `ModuleNotFoundError: No module named 'numpy'` 只躺在
    日志里。缺依赖属于**可预期的部署状态**，应当自报家门。
    """


def _missing_modules(names: tuple[str, ...]) -> list[str]:
    """返回其中缺失的模块名（不抛异常，便于一次性报全）"""
    missing = []
    for name in names:
        try:
            importlib.import_module(name)
        except ImportError:
            missing.append(name)
    return missing


def _require_modules(*names: str) -> None:
    """惰性导入 OCR 依赖；缺任何一个都抛出带修复命令的 OcrDependencyError。

    一次报全缺失项：逐个导入报错会让运维修一个再撞下一个。
    """
    missing = _missing_modules(names)
    if missing:
        raise OcrDependencyError(
            f'OCR 依赖未安装：{"、".join(missing)}；请执行 {_OCR_INSTALL_HINT}'
        )


# 延迟初始化的提取器单例。
#
# ⚠️ 必须在此处**显式声明**：`global X` 只声明「函数内对 X 的赋值要写回模块级」，
#    它**不会创建变量**。若模块级没有 X，`if X is None` 会先抛
#    `NameError: name 'X' is not defined` —— 与依赖是否安装**无关**。
#    2026-09-14 由 mypy 的 `name-defined` 发现：这三个名字只在 getter 里出现过，
#    模块级从未赋值，导致 OCR 功能整体不可用（首次调用必抛 NameError）。
#    类型用 Any：提取器类来自可选的第三方包（rapidocr_pdf / rapidocr / rapid_table），
#    惰性导入，静态类型不可得。
_pdf_extracter: Any = None
_img_extracter: Any = None
_table_extracter: Any = None


def _get_pdf_extracter():
    """延迟初始化 RapidOCRPDF 提取器（避免模块导入时加载模型）"""
    global _pdf_extracter
    if _pdf_extracter is None:
        try:
            from rapidocr_pdf import RapidOCRPDF
            _pdf_extracter = RapidOCRPDF()
            logger.info('RapidOCRPDF 提取器初始化成功')
        except ImportError:
            raise OcrDependencyError(f'OCR 依赖未安装：rapidocr_pdf；请执行 {_OCR_INSTALL_HINT}') from None
    return _pdf_extracter

def _get_img_extracter():
    """延迟初始化 RapidOCR 图片识别器（避免模块导入时加载模型）"""
    global _img_extracter
    if _img_extracter is None:
        try:
            from rapidocr import RapidOCR
            _img_extracter = RapidOCR()
            logger.info('RapidOCR 图片识别器初始化成功')
        except ImportError:
            raise OcrDependencyError(f'OCR 依赖未安装：rapidocr；请执行 {_OCR_INSTALL_HINT}') from None
    return _img_extracter

def _get_table_extracter():
    """延迟初始化 RapidTable 表格结构识别器"""
    global _table_extracter
    if _table_extracter is None:
        try:
            from rapid_table import ModelType, RapidTable, RapidTableInput
            input_args = RapidTableInput(model_type=ModelType.SLANETPLUS)
            _table_extracter = RapidTable(input_args)
            logger.info('RapidTable (SLANet-plus) 表格识别器初始化成功')
        except ImportError:
            raise OcrDependencyError(f'OCR 依赖未安装：rapid_table；请执行 {_OCR_INSTALL_HINT}') from None
    return _table_extracter

def extract_text_from_pdf(pdf_content: bytes) -> list[dict]:
    """
    从 PDF 文件提取文本内容

    使用 RapidOCRPDF 的完整流程:
    1. 提取文本型页面的直接文本
    2. 对图片型页面进行 OCR 识别
    3. 合并结果

    Args:
        pdf_content: PDF 文件字节内容

    Returns:
        列表，每项包含 {"page": 页码, "text": 文本内容}
    """
    from rapidocr_pdf import RapidOCRPDF
    extracter = _get_pdf_extracter()
    pdf_data = RapidOCRPDF.load_pdf(pdf_content)
    txts_dict, need_ocr_idxs = extracter.extract_texts(pdf_data, force_ocr=False, page_num_list=None)
    ocr_res_dict = {}
    if need_ocr_idxs:
        ocr_res_dict = extracter.get_ocr_res_streaming(pdf_data, need_ocr_idxs)
    merged = extracter.merge_direct_ocr(txts_dict, ocr_res_dict)
    pages = []
    for item in merged:
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            page_num = item[0]
            text = item[1] if isinstance(item[1], str) else str(item[1])
            pages.append({'page': page_num, 'text': text})
    return pages

def extract_text_from_image(image_content: bytes) -> list[dict]:
    """
    从图片文件提取文本内容

    使用 RapidOCR 对图片进行直接 OCR 识别。

    Args:
        image_content: 图片文件字节内容

    Returns:
        列表，每项包含 {"page": 页码(固定0), "text": 文本内容}
    """
    _require_modules('numpy', 'cv2')
    import numpy as np
    extracter = _get_img_extracter()
    img_array = np.frombuffer(image_content, dtype=np.uint8)
    import cv2
    img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
    if img is None:
        return []
    result = extracter(img)
    if result.txts is None:
        return []
    text = '\n'.join(result.txts)
    return [{'page': 0, 'text': text}]

def extract_text(file_content: bytes, filename: str='') -> list[dict]:
    """
    统一入口：根据文件类型自动选择 PDF 或图片 OCR 提取

    Args:
        file_content: 文件字节内容
        filename: 文件名（用于判断类型）

    Returns:
        列表，每项包含 {"page": 页码, "text": 文本内容}
    """
    ext = os.path.splitext(filename or '')[1].lower()
    if ext == '.pdf':
        return extract_text_from_pdf(file_content)
    elif ext in IMAGE_EXTENSIONS:
        return extract_text_from_image(file_content)
    else:
        try:
            return extract_text_from_pdf(file_content)
        except (ValueError, OSError):
            return extract_text_from_image(file_content)

def extract_table_structure(file_content: bytes, filename: str='') -> list[dict]:
    """
    使用 RapidTable 提取文档中的表格结构

    与 extract_text 不同，本函数直接输出 HTML 表格结构，
    保留了行列对应关系，无需后置正则猜测。
    """
    _require_modules('cv2', 'numpy')
    import cv2
    import numpy as np
    ext = os.path.splitext(filename or '')[1].lower()
    is_pdf = ext == '.pdf'
    page_images = []
    if is_pdf:
        page_images = _pdf_to_images(file_content)
    else:
        img_array = np.frombuffer(file_content, dtype=np.uint8)
        img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
        if img is not None:
            page_images = [img]
    if not page_images:
        return []
    table_engine = _get_table_extracter()
    ocr_engine = _get_img_extracter()
    results = []
    for page_idx, img in enumerate(page_images):
        try:
            ocr_res = ocr_engine(img)
            ocr_results = [ocr_res.boxes, ocr_res.txts, ocr_res.scores]
            table_res = table_engine(img, ocr_results)
            html_table = table_res.pred_html or ''
            text = '\n'.join(ocr_res.txts) if ocr_res.txts else ''
            results.append({'page': page_idx, 'html': html_table, 'text': text})
        except (ValueError, TypeError, OSError) as e:
            logger.warning(f'RapidTable 第{page_idx}页识别失败: {e}')
            continue
    return results

def _pdf_to_images(pdf_content: bytes) -> list:
    """将 PDF 每一页转为 numpy 图片数组"""
    _require_modules('cv2', 'fitz', 'numpy')
    import cv2
    import fitz
    import numpy as np
    doc = fitz.open(stream=pdf_content, filetype='pdf')
    images = []
    try:
        for page in doc:
            pix = page.get_pixmap(dpi=200)
            img_data = pix.tobytes('png')
            img_array = np.frombuffer(img_data, dtype=np.uint8)
            img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
            if img is not None:
                images.append(img)
    finally:
        doc.close()
    return images
