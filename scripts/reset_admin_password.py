"""
重置 admin 用户密码脚本

将 admin 用户的密码重置为 admin123
"""

import sys
from pathlib import Path

# 将项目根目录加入路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from fastapi_app.core.config import settings
from fastapi_app.core.security import hash_password


def reset_admin_password():
    """重置 admin 用户密码为 admin123"""
    engine = create_engine(settings.DATABASE_URL)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    with SessionLocal() as session:
        # 生成新的密码哈希
        new_password = "admin123"
        new_hash = hash_password(new_password)

        # 更新 admin 用户的密码
        result = session.execute(
            text('UPDATE "user" SET password = :password WHERE username = :username'),
            {"password": new_hash, "username": "admin"}
        )

        if result.rowcount == 0:
            print("错误: 未找到 admin 用户")
            session.rollback()
            return False

        session.commit()
        print("✅ 成功重置 admin 用户密码")
        print("   用户名: admin")
        print(f"   新密码: {new_password}")
        return True


if __name__ == "__main__":
    print("开始重置 admin 用户密码...")
    reset_admin_password()
