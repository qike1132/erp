"""
数据库迁移脚本 - 添加暂存订单表
运行方式：在项目根目录执行 python migrations\add_staging_order.py
"""
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db, create_app
from app.models.staging_order import StagingOrder


def upgrade():
    """创建暂存订单表"""
    try:
        app = create_app()
        with app.app_context():
            db.create_all()
            print("[OK] staging_order 表创建成功")
        return True
    except Exception as e:
        print(f"[ERROR] staging_order 表创建失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def downgrade():
    """删除暂存订单表"""
    try:
        app = create_app()
        with app.app_context():
            StagingOrder.__table__.drop(db.engine)
            print("[OK] staging_order 表删除成功")
        return True
    except Exception as e:
        print(f"[ERROR] staging_order 表删除失败: {e}")
        return False


if __name__ == '__main__':
    upgrade()
