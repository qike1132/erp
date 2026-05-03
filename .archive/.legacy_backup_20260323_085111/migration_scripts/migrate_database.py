"""
数据库迁移脚本：扩展inventory_log表的related_id字段长度和stock_out表的stockout_no字段长度
"""
import sys

sys.path.insert(0, r'c:\Users\Administrator\Desktop\erp_system')

from app import app, db
from sqlalchemy import text


def migrate_database():
    """执行数据库迁移"""
    with app.app_context():
        try:
            # 执行ALTER TABLE语句
            sql1 = text("ALTER TABLE inventory_log MODIFY COLUMN related_id VARCHAR(50)")
            db.session.execute(sql1)

            sql2 = text("ALTER TABLE stock_out MODIFY COLUMN stockout_no VARCHAR(50)")
            db.session.execute(sql2)

            db.session.commit()
            print('[OK] 数据库迁移成功：')
            print('  - related_id字段已扩展到VARCHAR(50)')
            print('  - stockout_no字段已扩展到VARCHAR(50)')
        except Exception as e:
            print(f'[ERROR] 数据库迁移失败: {e}')
            db.session.rollback()

if __name__ == '__main__':
    migrate_database()
