"""
数据库迁移脚本
添加 MaterialRegistration.status 列（如果表已存在但缺少该列）
"""
from app import db, app
from sqlalchemy import inspect

with app.app_context():
    try:
        # 1. 创建不存在的表
        db.create_all()
        print("数据库表检查/创建完成!")

        # 2. 检查 material_registration 表是否缺少 status 列
        inspector = inspect(db.engine)
        if 'material_registration' in inspector.get_table_names():
            columns = [col['name'] for col in inspector.get_columns('material_registration')]
            if 'status' not in columns:
                db.session.execute(
                    db.text("ALTER TABLE material_registration ADD COLUMN status VARCHAR(20) DEFAULT 'pending'")
                )
                db.session.commit()
                print("material_registration 表已添加 status 列")

                # 为已有记录回填 status（根据 items 计算实际状态）
                from app.models.material_registration import MaterialRegistration
                registrations = MaterialRegistration.query.all()
                for reg in registrations:
                    reg.update_status()
                db.session.commit()
                print(f"已更新 {len(registrations)} 条记录的 status 字段")
            else:
                print("material_registration.status 列已存在，无需迁移")
        else:
            print("material_registration 表不存在，将由 db.create_all() 创建")

    except Exception as e:
        print(f"迁移出错: {e}")
        db.session.rollback()
