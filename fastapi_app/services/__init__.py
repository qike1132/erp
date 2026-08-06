"""FastAPI 服务层共享工具函数

注意：escape_like 已下沉到 fastapi_app.core.sanitizer，此处保留 re-export 以保持向后兼容。
"""
from fastapi_app.core.sanitizer import escape_like

__all__ = ['escape_like']
