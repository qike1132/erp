from app import create_app, db

app = create_app()
with app.app_context():
    result = db.session.execute(db.text("SHOW TABLES LIKE '%production%'"))
    print("Production tables:", [r[0] for r in result.fetchall()])

    result2 = db.session.execute(db.text("SHOW TABLES LIKE '%plan%'"))
    print("Plan tables:", [r[0] for r in result2.fetchall()])

    result3 = db.session.execute(db.text("SHOW TABLES LIKE '%order_group%'"))
    print("Order group tables:", [r[0] for r in result3.fetchall()])
