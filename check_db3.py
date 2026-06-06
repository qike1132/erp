import sys
sys.path.insert(0, '.')
from sqlalchemy import create_engine, text, inspect
from fastapi_app.core.config import settings
engine = create_engine(settings.DATABASE_URL)
from sqlalchemy.orm import Session

with Session(engine) as db:
    print('=== Check all tables related to plans ===')
    print('purchase_plans:', db.execute(text('SELECT COUNT(*) FROM purchase_plans')).scalar())
    print('purchase_plan_details:', db.execute(text('SELECT COUNT(*) FROM purchase_plan_details')).scalar())
    print('staging_purchase_plan:', db.execute(text('SELECT COUNT(*) FROM staging_purchase_plan')).scalar())
    print()
    print('=== Check orders ===')
    print('order count:', db.execute(text('SELECT COUNT(*) FROM "order"')).scalar())
    # Get column names first
    inspector = inspect(engine)
    columns = inspector.get_columns('order')
    col_names = [c['name'] for c in columns]
    print('order columns:', col_names[:10])
    rows = db.execute(text(f'SELECT {", ".join(col_names[:5])} FROM "order" LIMIT 3')).fetchall()
    for r in rows:
        print(r)
    print()
    print('=== Check stock_out ===')
    print('stock_out count:', db.execute(text('SELECT COUNT(*) FROM stock_out')).scalar())
    columns = inspector.get_columns('stock_out')
    col_names = [c['name'] for c in columns]
    print('stock_out columns:', col_names[:10])
    rows = db.execute(text(f'SELECT {", ".join(col_names[:5])} FROM stock_out LIMIT 3')).fetchall()
    for r in rows:
        print(r)
    print()
    print('=== Check production_plan ===')
    print('production_plan count:', db.execute(text('SELECT COUNT(*) FROM production_plan')).scalar())
    columns = inspector.get_columns('production_plan')
    col_names = [c['name'] for c in columns]
    print('production_plan columns:', col_names[:10])
