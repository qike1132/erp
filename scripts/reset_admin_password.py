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
import sys
from pathlib import Path

# 将项目根目录加入路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from fastapi_app.core.config import settings
from fastapi_app.core.security import hash_password
from utils.password_validator import PasswordValidator


def _validate_password_strength(password: str) -> None:
    """校验密码：复用 PasswordValidator，与建号/改密保持同一套策略"""
    is_valid, error_msg = PasswordValidator.validate(password)
    if not is_valid:
        raise ValueError(error_msg)


# 重置语句抽成模块常量：「重置口令必须同时 bump token_version」是本脚本的契约，
# 抽出来才能被纯文本断言而不必真连库（数据库只在生产/测试库上，脚本不允许被测试跑）。
#
# 为什么必须带上 token_version：HTTP 侧 `deps._verify_user_active` 与 WebSocket 60s
# 复核都比对用户表的 token_version。只改 password 时，重置前签发的 access/refresh
# token 仍能用满剩余有效期（默认 2 小时 / 7 天），等于「重置」没把旧会话踢下线
# ——忘了密码的场景往往正怀疑凭据已外泄（2026-11-16 审计 Low）。
# COALESCE 兜住历史行的 NULL，避免 NULL + 1 = NULL 让版本永远不变。
_RESET_ADMIN_PASSWORD_SQL = (
    'UPDATE "user" '
    'SET password = :password, token_version = COALESCE(token_version, 0) + 1 '
    'WHERE username = :username'
)


def reset_admin_password(new_password: str) -> bool:
    """重置 admin 用户密码（同时让既有会话失效）"""
    _validate_password_strength(new_password)

    engine = create_engine(settings.DATABASE_URL)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    with SessionLocal() as session:
        # 生成新的密码哈希
        new_hash = hash_password(new_password)

        # 更新 admin 用户的密码，并 bump token_version（见 _RESET_ADMIN_PASSWORD_SQL）
        result = session.execute(
            text(_RESET_ADMIN_PASSWORD_SQL),
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
    parser.add_argument('--password', '-p', help='新密码（至少6位，策略与系统建号一致）')
    args = parser.parse_args()

    password = args.password or os.environ.get('NEW_ADMIN_PASSWORD')
    if not password:
        print("错误: 请通过 --password 参数或 NEW_ADMIN_PASSWORD 环境变量提供新密码")
        print("示例: python scripts/reset_admin_password.py --password YourStrongPwd123")
        sys.exit(1)

    # 危险写护栏（审查 H13）：UPDATE "user" 直写生产库，与 init_permissions/
    # db_manager 同一授权口（ERP_ALLOW_PROD_WRITE=1 或 --allow-prod-write）。
    from _prod_write_guard import require_prod_write_consent
    require_prod_write_consent(
        '重置 admin 用户密码（UPDATE "user"）',
        hint='不可逆：原密码哈希将被覆盖。仅限初始化/忘记密码场景。',
    )

    print("开始重置 admin 用户密码...")
    success = reset_admin_password(password)
    sys.exit(0 if success else 1)
