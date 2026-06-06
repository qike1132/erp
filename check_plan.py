import sys
sys.path.insert(0, '.')
from sqlalchemy import create_engine, text
from fastapi_app.core.config import settings
engine = create_engine(settings.DATABASE_URL)
from sqlalchemy.orm import Session

with Session(engine) as db:
    print('=== purchase_plans ===')
    rows = db.execute(text('SELECT * FROM purchase_plans')).fetchall()
    for r in rows:
        print(r)
    print()
    print('=== purchase_plan_details ===')
    rows = db.execute(text('SELECT * FROM purchase_plan_details')).fetchall()
    for r in rows:
        print(r)
