"""API v2 版本化策略公共工具

P2-15: 集中管理版本响应头，避免 v2 router 与业务端点之间的循环导入。
"""


def _version_headers() -> dict[str, str]:
    """v2 通用响应头：声明 API 版本与弃用政策"""
    return {
        "API-Version": "2.0.0",
        "Sunset": "Sun, 31 Dec 2026 23:59:59 GMT",
        "Deprecation": "false",
    }
