"""asyncpg 连接测试脚本

从应用配置读取数据库连接参数，避免硬编码凭据。
"""
import asyncio
import os
import sys
from pathlib import Path

import asyncpg

# 将项目根目录加入路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


async def main():
    lines = []
    try:
        # 优先从环境变量读取（兼容独立运行），否则从应用配置读取
        db_url = os.environ.get('DATABASE_URL') or os.environ.get('TEST_DATABASE_URL')
        if db_url:
            conn = await asyncpg.connect(dsn=db_url)
        else:
            from fastapi_app.core.config import settings
            # settings.DATABASE_URL 是 SQLAlchemy 格式 (postgresql+asyncpg://...)
            # asyncpg 需要标准 postgresql://... 格式
            dsn = settings.DATABASE_URL.replace('postgresql+asyncpg://', 'postgresql://')
            conn = await asyncpg.connect(dsn=dsn)
        row = await conn.fetchval("SELECT 1")
        await conn.close()
        lines.append(f"connected, select 1 = {row}")
    except Exception as e:
        lines.append(f"error: {type(e).__name__} {e}")
    Path("d:/erp_system/scripts/test_asyncpg.out").write_text("\n".join(lines), encoding="utf-8")


asyncio.run(main())
