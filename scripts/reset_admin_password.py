"""
重置 admin 用户密码脚本

从环境变量 NEW_ADMIN_PASSWORD 或命令行参数读取新密码，禁止硬编码。
用法:
    # 方式1: 环境变量
    $env:NEW_ADMIN_PASSWORD='<your-strong-password>'; python scripts/reset_admin_password.py
    # 方式2: 命令行参数
    python scripts/reset_admin_password.py --password <your-strong-password>
"""

import argparse
import os
import re
import sys
from pathlib import Path

# 将项目根目录加入路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from fastapi_app.core.config import settings
from fastapi_app.core.security import hash_password


def _validate_password_strength(password: str) -> None:
    """校验密码复杂度：至少8位，含字母和数字"""
    if len(password) < 8:
        raise ValueError('密码长度至少 8 位')
    if not re.search(r'[A-Za-z]', password):
        raise ValueError('密码必须包含字母')
    if not re.search(r'\d', password):
        raise ValueError('密码必须包含数字')


def reset_admin_password(new_password: str) -> bool:
    """重置 admin 用户密码"""
    _validate_password_strength(new_password)

    engine = create_engine(settings.DATABASE_URL)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    with SessionLocal() as session:
        # 生成新的密码哈希
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
        print(f"   新密码: {'*' * len(new_password)}（已隐藏）")
        return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='重置 admin 用户密码')
    parser.add_argument('--password', '-p', help='新密码（至少8位，含字母和数字）')
    args = parser.parse_args()

    password = args.password or os.environ.get('NEW_ADMIN_PASSWORD')
    if not password:
        print("错误: 请通过 --password 参数或 NEW_ADMIN_PASSWORD 环境变量提供新密码")
        print("示例: python scripts/reset_admin_password.py --password YourStrongPwd123")
        sys.exit(1)

    print("开始重置 admin 用户密码...")
    success = reset_admin_password(password)
    sys.exit(0 if success else 1)
