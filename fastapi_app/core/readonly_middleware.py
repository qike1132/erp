"""
迁移期间只读模式中间件
整改: PostgreSQL 切换窗口期间使用
"""
from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
import logging

logger = logging.getLogger(__name__)


class ReadOnlyMiddleware(BaseHTTPMiddleware):
    """
    迁移期间只读模式中间件
    - GET/HEAD 请求正常通过
    - POST/PUT/DELETE 请求返回 503 Service Unavailable
    """
    
    def __init__(self, app, enabled: bool = False, whitelist_paths: list = None):
        super().__init__(app)
        self.enabled = enabled
        self.whitelist_paths = whitelist_paths or ['/api/health', '/api/readiness']
    
    async def dispatch(self, request: Request, call_next):
        if not self.enabled:
            return await call_next(request)
        
        # 白名单路径跳过检查
        if any(request.url.path.startswith(path) for path in self.whitelist_paths):
            return await call_next(request)
        
        # 只读模式：只允许读操作
        if request.method in ['POST', 'PUT', 'DELETE', 'PATCH']:
            logger.warning(f"只读模式拦截: {request.method} {request.url.path}")
            raise HTTPException(
                status_code=503,
                detail={
                    "message": "系统正在维护中，暂不接受写入操作",
                    "retry_after": 900,  # 15 分钟后重试
                    "maintenance_window": "2026-XX-XX 02:00-02:15"
                }
            )
        
        return await call_next(request)
