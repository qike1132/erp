"""采购订单查询 - 公共辅助函数(对外兼容入口)

从 purchase_order_query_helpers.py 按主题拆分为 services/purchase/ 子包:
- _common: 公共辅助  - _list: 列表查询  - _completed: 完成态查询
- _supplier: 供应商维度  - _factory: 工厂维度  - _unprocessed: 未处理记录

本文件保留全部符号的 re-export,历史调用方
`from fastapi_app.services.purchase_order_query_helpers import X` 保持不变。
"""
from fastapi_app.services.purchase._common import (  # noqa: F401
    _parse_source_order_ids,
    fetch_po_sku_lines_map,
    fetch_po_sku_pids_map,
)
from fastapi_app.services.purchase._list import (  # noqa: F401
    _fetch_bom_data,
    _is_filling_category,
    _apply_po_list_filters,
    _apply_po_sort,
    _fetch_po_items_by_order,
    _build_po_source_fill_and_no_maps,
    _build_po_source_no_map,
    _build_po_source_sku_map,
    _merge_duplicate_skus,
    _resolve_po_product_name_qty,
    _serialize_po_item,
    _serialize_po_list_item,
    _resolve_po_detail_product_name_qty,
    _PO_SORT_MAP,
)
from fastapi_app.services.purchase._completed import (  # noqa: F401
    _apply_completed_filters,
    _apply_completed_quick_filter,
    _fetch_completed_items_and_arrived,
    _serialize_completed_item,
    _serialize_completed_order,
    _COMPLETED_SORT_MAP,
    _QUICK_FILTER_DAYS,
)
from fastapi_app.services.purchase._supplier import (  # noqa: F401
    _build_po_items_map,
    _build_po_items_by_order,
    _fetch_po_items_map,
    _fetch_supplier_cust_order_map,
    _resolve_po_qty_and_pid,
    _build_supplier_mat_map,
)
from fastapi_app.services.purchase._factory import (  # noqa: F401
    _fetch_factory_cust_order_map,
    _fetch_prod_name_map,
    _resolve_factory_source_info,
    _resolve_factory_po_info,
    _accumulate_factory_bom,
    _accumulate_factory_po_items,
    _build_factory_group_map,
    _serialize_factory_groups,
)
from fastapi_app.services.purchase._unprocessed import (  # noqa: F401
    _build_not_processed_filter,
    _build_records_in_sql_order,
    _build_unprocessed_order_record,
    _build_unprocessed_response,
    _build_unprocessed_stockin_record,
    _build_unprocessed_union,
    _collect_record_product_ids,
    _count_unprocessed,
    _enrich_unprocessed_items,
    _fetch_bom_product_ids,
    _fetch_product_name_barcode,
    _fetch_unprocessed_page,
    _load_unprocessed_sources,
    _order_has_bom,
)
