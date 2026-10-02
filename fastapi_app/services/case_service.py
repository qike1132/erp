"""皮套管理服务层(对外兼容入口)

按职责拆分为 services/case/ 子包:
- _common: 日期/分页/过滤工具与常量
- _serializers: SKU / 流水序列化
- queries: 查询域(SKU 搜索/列表 / 流水 / 库存分组汇总)
- commands: 命令域(SKU 增删改 / 流水增删改 / 批量)

本文件保留对外函数名的 re-export。
"""
from fastapi_app.services.case._common import (  # noqa: F401
    _apply_date_filter,
    _apply_quantity_filter,
    _normalize_pagination,
    _parse_date,
)
from fastapi_app.services.case._serializers import (  # noqa: F401
    _serialize_item,
    _serialize_movement,
)
from fastapi_app.services.case.commands import (  # noqa: F401
    _get_case_for_update,
    batch_create_movements,
    create_case_item,
    create_movement,
    delete_case_item,
    delete_movement,
    update_case_item,
    update_movement,
)
from fastapi_app.services.case.queries import (  # noqa: F401
    get_case_inventory,
    get_case_items,
    get_case_movement_detail,
    get_case_movements,
    search_cases,
)
