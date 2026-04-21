"""
健康检查端点
整改: 添加完整的健康检查，支持负载均衡器和服务发现
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
import redis.asyncio as redis
import os

from fastapi_app.core.database import get_async_db

router = APIRouter(prefix="/health", tags=["健康检查"])

# Redis 连接
redis_client = redis.from_url(
    os.getenv("REDIS_URL", "redis://localhost:6379/0"),
    decode_responses=True
)


@router.get("/")
async def health_check():
    """
    基础健康检查
    返回: 200 OK（服务存活）
    """
    return {
        "status": "healthy",
        "service": "erp-system",
        "version": "1.4.1",
        "timestamp": datetime.now().isoformat()
    }


@router.get("/ready")
async def readiness_check(db: AsyncSession = Depends(get_async_db)):
    """
    就绪检查
    验证: 数据库连接、Redis 连接
    返回: 200 OK（可接收流量）或 503 Service Unavailable
    """
    checks = {}
    
    # 检查数据库
    try:
        await db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {str(e)}"
        raise HTTPException(
            status_code=503,
            detail={
                "status": "not_ready",
                "checks": checks,
                "message": "数据库连接异常"
            }
        )
    
    # 检查 Redis
    try:
        await redis_client.ping()
        checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"error: {str(e)}"
        raise HTTPException(
            status_code=503,
            detail={
                "status": "not_ready",
                "checks": checks,
                "message": "Redis 连接异常"
            }
        )
    
    return {
        "status": "ready",
        "checks": checks,
        "timestamp": datetime.now().isoformat()
    }


@router.get("/live")
async def liveness_check():
    """
    存活检查
    返回: 200 OK（进程存活）
    用途: Kubernetes/Docker 自动重启判断
    """
    return {
        "status": "alive",
        "timestamp": datetime.now().isoformat()
    }


from datetime import datetime
