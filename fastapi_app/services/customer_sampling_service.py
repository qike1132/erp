"""按客户分类打样信息模块服务层（已拆分为 customer_sampling 子包）。

本文件保留为 re-export 入口，保持向后兼容：
    from fastapi_app.services.customer_sampling_service import get_grouped_list

实际实现位于 fastapi_app/services/customer_sampling/ 子包。
拆分来源：.codeartsdoer/specs/code_quality_opt/tasks.md P0-2
"""
from fastapi_app.services.customer_sampling import *  # noqa: F403
from fastapi_app.services.customer_sampling import __all__  # noqa: F401
