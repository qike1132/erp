"""业务时区（北京时间）展示口径 —— re-export 自 :mod:`fastapi_app.core.business_time`。

时区源的**唯一定义点**已下沉到 core（stdlib-only 叶子，供 ``shared_models`` 引用
而不反向依赖 services）。本模块保留以维持 services 层既有 import 路径。
"""
from fastapi_app.core.business_time import _BUSINESS_TZ, fmt_business

__all__ = ['_BUSINESS_TZ', 'fmt_business']
