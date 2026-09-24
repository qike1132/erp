"""皮套管理服务层(对外兼容入口)

从 case_service.py 按职责拆分为 services/case/ 子包:
- _common: 日期/分页/过滤工具与常量
- _serializers: 入库/出库序列化
- queries: 查询域(搜索/列表/汇总/流水/详情)
- commands: 命令域(入库/出库增删改查与批量)

本文件保留全部对外函数名的 re-export,历史调用方
`from fastapi_app.services.case_service import X` 保持不变。
"""
from fastapi_app.services.case._common import (  # noqa: F401
    _apply_date_filter,
    _apply_quantity_filter,
    _normalize_pagination,
    _parse_date,
)
from fastapi_app.services.case._serializers import (  # noqa: F401
    _serialize_stockin,
    _serialize_stockout,
)
from fastapi_app.services.case.commands import (  # noqa: F401
    _adjust_stockin_quantity,
    _adjust_stockout_quantity,
    _assert_no_case_references,
    _get_case_by_product_for_update,
    _get_case_for_update,
    _get_or_create_case_for_product,
    batch_create_case_stockins,
    batch_create_case_stockouts,
    create_case_product,
    create_case_stockin,
    create_case_stockout,
    delete_case_product,
    delete_case_stockin,
    delete_case_stockout,
    update_case_stockin,
    update_case_stockout,
)
from fastapi_app.services.case.queries import (  # noqa: F401
    _build_inventory_base_query,
    _build_inventory_items,
    _compute_inventory_stats,
    get_case_inventory_logs,
    get_case_inventory_summary,
    get_case_products,
    get_case_stockin_detail,
    get_case_stockins,
    get_case_stockout_detail,
    get_case_stockout_list,
    search_cases,
)
