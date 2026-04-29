from app import create_app, db

app = create_app()
with app.app_context():
    # 查看采购相关的表
    result = db.session.execute(db.text("SHOW TABLES LIKE '%purchase%'"))
    print("Purchase tables:", [r[0] for r in result.fetchall()])

    # 查看备货相关的表
    result2 = db.session.execute(db.text("SHOW TABLES LIKE '%staging%'"))
    print("Staging tables:", [r[0] for r in result2.fetchall()])

    # 查看物料相关的表
    result3 = db.session.execute(db.text("SHOW TABLES LIKE '%material%'"))
    print("Material tables:", [r[0] for r in result3.fetchall()])

    # 查看craft相关
    result4 = db.session.execute(db.text("SHOW TABLES LIKE '%craft%'"))
    print("Craft tables:", [r[0] for r in result4.fetchall()])
