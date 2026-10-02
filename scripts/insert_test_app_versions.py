"""
插入测试App版本数据
"""
import asyncio
import hashlib
import os
import sys
from datetime import datetime

# 导入模型（需要确保路径正确）
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

# 项目根（不是 scripts/ —— 原写 .parent 会让 fastapi_app 导入失败）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# 护栏**先于 app 导入**：本脚本引用的 fastapi_app.shared_models.app_version 已不存在
# （另有 settings.database_url 亦不存在），app 导入必然失败 —— 但"要写生产库"这件事
# 必须在任何导入失败之前就拦下来。
from _prod_write_guard import require_prod_write_consent

require_prod_write_consent('向生产库插入测试 app 版本')

from fastapi_app.shared_models.app_version import AppVersion

from fastapi_app.core.config import Settings

settings = Settings()

# 创建异步引擎
async_engine = create_async_engine(settings.database_url, echo=True)


async def insert_test_data():
    """插入测试版本数据"""
    print("=" * 50)
    print("插入 App版本 测试数据")
    print("=" * 50)
    print()

    # 创建 static/releases 目录
    upload_dir = Path(__file__).parent / "static" / "releases"
    upload_dir.mkdir(parents=True, exist_ok=True)

    # 创建一个测试文件
    test_apk_path = upload_dir / "test_v11.apk"
    with open(test_apk_path, "wb") as f:
        f.write(b"test content 1.1")

    # 计算 MD5
    md5_hash = hashlib.md5(b"test content 1.1").hexdigest()

    # 插入测试数据
    async with AsyncSession(async_engine) as session:
        # 检查是否已有数据
        existing = await session.execute(
            select(AppVersion).where(AppVersion.version_code == 1)
        )
        if existing.scalars().first():
            print("测试数据已存在，跳过")
            await session.close()
            return

        # 插入2个版本
        # 版本 1: 待发布
        v1 = AppVersion(
            platform="android",
            version_code=1,
            version_name="1.0",
            download_url="/static/releases/test_v11.apk",
            changelog="初始版本，测试功能",
            file_size=os.path.getsize(test_apk_path),
            md5_hash=md5_hash,
            force_update=False,
            is_active=False,
            pushed=False,
            created_at=datetime.now(),
        )
        session.add(v1)

        # 版本 2: 已发布
        test_apk2 = upload_dir / "test_v12.apk"
        with open(test_apk2, "wb") as f:
            f.write(b"test content 1.2")

        md5_hash2 = hashlib.md5(b"test content 1.2").hexdigest()
        v2 = AppVersion(
            platform="android",
            version_code=2,
            version_name="1.1",
            download_url="/static/releases/test_v12.apk",
            changelog="新版本，测试推送功能",
            file_size=os.path.getsize(test_apk2),
            md5_hash=md5_hash2,
            force_update=True,
            is_active=True,
            pushed=True,
            created_at=datetime.now(),
        )
        session.add(v2)

        await session.commit()
        await session.refresh(v1)
        await session.refresh(v2)

        print(f"✅ 插入版本 1: v{v1.version_name} (code={v1.version_code}), 状态=待发布")
        print(f"✅ 插入版本 2: v{v2.version_name} (code={v2.version_code}), 状态=已发布")
        print()
        print("测试数据插入成功！")
        print("请访问 http://192.168.0.95:3000/app-update 查看")


if __name__ == "__main__":
    asyncio.run(insert_test_data())
