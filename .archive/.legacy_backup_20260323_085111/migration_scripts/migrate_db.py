from app import app, db

with app.app_context():
    # 检查stock_in表是否存在customer列
    from sqlalchemy import inspect
    inspector = inspect(db.engine)
    columns = [c['name'] for c in inspector.get_columns('stock_in')]

    if 'customer' not in columns:
        # 添加customer列
        from sqlalchemy import text
        db.session.execute(text('ALTER TABLE stock_in ADD COLUMN customer VARCHAR(100) NOT NULL DEFAULT "MINISO 国内"'))
        db.session.commit()
        print('Added customer column to stock_in table')
    else:
        print('customer column already exists in stock_in table')

    # 验证修改
    columns = [c['name'] for c in inspector.get_columns('stock_in')]
    print('Current columns in stock_in table:', columns)
