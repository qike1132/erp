#!/usr/bin/env python3
"""
测试 OTA 1.3 版本流程
"""
import json
import random
import sys
import time
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPTS_DIR.parent

sys.path.insert(0, str(PROJECT_ROOT / "fastapi_app"))

import asyncio
from datetime import datetime

# 导入数据库配置
from shared_models.app_version import AppVersion
from sqlalchemy.ext.asyncio import AsyncSession
from shared.core.database import engine, Base, get_session

async def create_test_1_3():
    async with get_session() as session:
        print("=" * 60)
        print(f"  OTA 1.3 版本测试  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 60)

        # 1.3 版本信息
        version_name = "1.3"
        version_code = 77
        
        print("\n[1/4] 创建测试 APK...")

        # 创建测试 APK 文件
        releases_dir = PROJECT_ROOT / "static" / "releases"
        releases_dir.mkdir(parents=True, exist_ok=True)
        test_apk = releases_dir / f"erp-v1.3.apk"
        
        # 如果已有APK，先检查
        if not test_apk.exists():
            test_apk.touch()
            # 写入 PK 魔数，让文件看起来像 APK
            with open(test_apk, "wb") as f:
                f.write(b"PK\x03\x04")  # ZIP/APK 魔数
                f.write(b"test content")
        print(f"  [OK] 测试 APK: {test_apk}")

        print("\n[2/4] 插入数据库...")
        
        changelog = "1.3 版本更新:\n- 修复 APK 推送通知\n- 添加版本号显示\n- 优化 Dashboard 统计"
        
        new_version = AppVersion(
            version_name=version_name,
            version_code=version_code,
            changelog=changelog,
            file_path=str(test_apk),
            file_md5=hashlib.md5(str(test_apk).encode()).hexdigest(),
            file_size=test_apk.stat().st_size,
            platform="android",
            is_active=False,
            is_force_update=False,
        )
        session.add(new_version)
        await session.commit()
        await session.refresh(new_version)
        
        print(f"  [OK] ID: {new_version.id}, 状态: 待发布")
        
        print("\n[3/4] 激活版本...")
        
        # 激活版本
        new_version.is_active = True
        await session.commit()
        print(f"  [OK] 版本已激活")
        
        print("\n[4/4] 标记为已推送...")
        
        new_version.is_pushed = True
        new_version.pushed_at = datetime.now()
        await session.commit()
        print(f"  [OK] 已标记推送")
        
        print("\n" + "=" * 60)
        print(f"  1.3 版本测试完成!")
        print(f"  版本: v{version_name} (code={version_code})")
        print(f"  状态: 已发布")
        print("=" * 60)
        
        print("\n访问:")
        print("  管理页: http://192.168.0.95:3000/app-update")
        print("  APK: http://192.168.0.95:5002/static/releases/erp-v1.3.apk")
        
        return new_version

if __name__ == "__main__":
    import hashlib
    try:
        asyncio.run(create_test_1_3())
    except Exception as e:
        print(f"  [ERROR] {e}")
        import traceback
        traceback.print_exc()
