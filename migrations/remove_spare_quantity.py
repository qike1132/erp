"""
移除 purchase_order_item 表的 spare_quantity 字段
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from sqlalchemy import text

def upgrade():
    """移除 spare_quantity 列"""
    app = create_app()
    with app.app_context():
        connection = db.engine.connect()

        result = connection.execute(text("SHOW COLUMNS FROM purchase_order_item LIKE 'spare_quantity'"))
        if result.fetchone():
            print("发现 spare_quantity 列，开始移除...")
            connection.execute(text("ALTER TABLE purchase_order_item DROP COLUMN spare_quantity"))
            connection.commit()
            print("spare_quantity 列已成功移除！")
        else:
            print("spare_quantity 列不存在，跳过移除操作。")

        connection.close()

def downgrade():
    """恢复 spare_quantity 列"""
    app = create_app()
    with app.app_context():
        connection = db.engine.connect()

        result = connection.execute(text("SHOW COLUMNS FROM purchase_order_item LIKE 'spare_quantity'"))
        if not result.fetchone():
            print("恢复 spare_quantity 列...")
            connection.execute(text("ALTER TABLE purchase_order_item ADD COLUMN spare_quantity DECIMAL(12,2) DEFAULT 0 COMMENT '备品订单用量'"))
            connection.commit()
            print("spare_quantity 列已成功恢复！")
        else:
            print("spare_quantity 列已存在，跳过恢复操作。")

        connection.close()

if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'downgrade':
        downgrade()
    else:
        upgrade()