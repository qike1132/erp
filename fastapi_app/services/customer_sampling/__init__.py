"""customer_sampling 子包 - 按职责拆分的打样模块。

原 customer_sampling_service.py 已拆分为本子包下的子模块，
此处 re-export 全部公开函数保持导入兼容：
    from fastapi_app.services.customer_sampling_service import get_grouped_list
仍可正常工作。
"""
from .common import (
    _ensure_part_name_unique,
    _ensure_project_exists,
    _ensure_role_belongs_to_project,
    _get_default_role_id,
    _get_user_name,
    _resolve_pattern_maker_name,
    _resolve_supplier_name,
    _write_change_log,
)
from .crud import (
    batch_create_parts,
    copy_part_version,
    create_part,
    create_project,
    delete_part,
    delete_project,
    get_project_detail,
    list_parts,
    list_projects,
    update_part,
    update_project,
    update_project_status,
)
from .grouping import (
    _project_to_summary,
    get_completed_table,
    get_grouped_list,
)
from .roles import (
    create_role,
    delete_role,
    list_roles,
    update_role,
)
from .upload import (
    _batch_get_image_urls,
    _get_product_image_urls,
    upload_project_image,
)
from .version_diff import (
    _SNAPSHOT_FIELDS,
    _compute_diff,
    _next_version,
    _normalize_value,
    _version_num,
    create_version,
    get_parts_by_version,
    get_version_detail,
    list_change_logs,
    list_versions,
)

__all__ = [
    '_SNAPSHOT_FIELDS',
    '_batch_get_image_urls',
    '_compute_diff',
    '_ensure_part_name_unique',
    '_ensure_project_exists',
    '_ensure_role_belongs_to_project',
    '_get_default_role_id',
    '_get_product_image_urls',
    '_get_user_name',
    '_next_version',
    '_normalize_value',
    '_project_to_summary',
    '_resolve_pattern_maker_name',
    '_resolve_supplier_name',
    '_version_num',
    '_write_change_log',
    'batch_create_parts',
    'copy_part_version',
    'create_part',
    'create_project',
    'create_role',
    'create_version',
    'delete_part',
    'delete_project',
    'delete_role',
    'get_completed_table',
    'get_grouped_list',
    'get_parts_by_version',
    'get_project_detail',
    'get_version_detail',
    'list_change_logs',
    'list_parts',
    'list_projects',
    'list_roles',
    'list_versions',
    'update_part',
    'update_project',
    'update_project_status',
    'update_role',
    'upload_project_image',
]
