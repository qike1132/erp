"""FastAPI 服务层共享工具函数"""


def escape_like(value: str) -> str:
    """转义 SQL LIKE 通配符，防止 LIKE 注入"""
    return value.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
