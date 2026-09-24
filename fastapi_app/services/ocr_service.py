"""ocr_service(对外兼容入口)

从 ocr_service.py 按职责拆分为 services/ocr/ 子包。
- _progress: 进度管理  - _extractors: 提取器
- _html_tables: HTML 表格解析  - _text_parsers: 文本格式解析  - _import: 出货单导入

本文件保留全部对外函数名的 re-export,历史调用方
`from fastapi_app.services.ocr_service import X` 保持不变。
"""
from fastapi_app.services.ocr._extractors import (  # noqa: F401
    IMAGE_EXTENSIONS,
    _get_img_extracter,
    _get_pdf_extracter,
    _get_table_extracter,
    _pdf_to_images,
    extract_table_structure,
    extract_text,
    extract_text_from_image,
    extract_text_from_pdf,
)
from fastapi_app.services.ocr._html_tables import (  # noqa: F401
    _detect_column_mapping,
    _extract_customer_from_header_text,
    _extract_item_from_row,
    _html_table_to_rows,
    parse_html_shipping_tables,
    parse_shipping_document,
)
from fastapi_app.services.ocr._import import (  # noqa: F401
    import_staging_stockouts_from_file,
)
from fastapi_app.services.ocr._progress import (  # noqa: F401
    _cleanup_progress_store,
    _progress_lock,
    _progress_store,
    _update_progress,
    create_progress,
    get_progress,
)
from fastapi_app.services.ocr._text_parsers import (  # noqa: F401
    _detect_column_positions,
    _extract_customer_from_header,
    _extract_row_by_positions,
    _parse_key_value_format,
    _parse_line_by_line,
    _parse_ocr_sliding_window,
    _parse_ocr_table_format,
    _parse_quantity,
    _parse_table_format,
)
