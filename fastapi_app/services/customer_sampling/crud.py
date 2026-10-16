"""打样 CRUD Facade（批次2-3 拆分，2026-08-22）

按职责拆分至 projects.py / parts.py（version_diff.py 承载版本域，内聚保持不拆）。
本模块保留全部原名称 re-export，包 __init__ 与既有引用零改动。
"""
# ruff: noqa: F401 - 兼容 Facade re-export
from fastapi_app.services.customer_sampling.parts import (
    batch_create_parts,
    copy_part_version,
    create_part,
    delete_part,
    get_part_field_candidates,
    list_parts,
    update_part,
)
from fastapi_app.services.customer_sampling.projects import (
    create_project,
    delete_project,
    get_project_detail,
    list_projects,
    update_project,
    update_project_status,
)
