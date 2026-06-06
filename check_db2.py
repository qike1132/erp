import sys
sys.path.insert(0, '.')
from sqlalchemy import create_engine, text
from fastapi_app.core.config import settings
engine = create_engine(settings.DATABASE_URL)
from sqlalchemy.orm import Session

with Session(engine) as db:
    print('=== Check all tables related to plans ===')
    print('purchase_plans:', db.execute(text('SELECT COUNT(*) FROM purchase_plans')).scalar())
    print('purchase_plan_details:', db.execute(text('SELECT COUNT(*) FROM purchase_plan_details')).scalar())
    print('staging_purchase_plan:', db.execute(text('SELECT COUNT(*) FROM staging_purchase_plan')).scalar())
    print()
    print('=== Check orders (might be source of data) ===')
    print('order count:', db.execute(text('SELECT COUNT(*) FROM "order"')).scalar())
    rows = db.execute(text('SELECT id, order_no, customer_name, delivery_date, status FROM "order" LIMIT 5')).fetchall()
    for r in rows:
        print(r)
    print()
    print('=== Check stock_out ===')
    print('stock_out count:', db.execute(text('SELECT COUNT(*) FROM stock_out')).scalar())
    rows = db.execute(text('SELECT id, product_name, customer_name, quantity, out_date FROM stock_out LIMIT 5')).fetchall()
    for r in rows:
        print(r)
