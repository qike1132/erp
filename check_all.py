import sys
sys.path.insert(0, '.')
from sqlalchemy import create_engine, text
from fastapi_app.core.config import settings
engine = create_engine(settings.DATABASE_URL)
from sqlalchemy.orm import Session

tables = [
    'purchase_plans', 'purchase_plan_details', 'staging_purchase_plan',
    'production_plan', 'production_plan_log', 'daily_production_record',
    '"order"', 'stock_out', 'stock_in', 'customer', 'product', 'supplier',
    'shipment_records', 'packaging_record', 'craft_work'
]

with Session(engine) as db:
    for t in tables:
        try:
            count = db.execute(text(f'SELECT COUNT(*) FROM {t}')).scalar()
            print(f'{t}: {count}')
        except Exception as e:
            print(f'{t}: ERROR - {e}')
