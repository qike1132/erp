import sys
sys.path.insert(0, '.')
from sqlalchemy import create_engine, text, inspect
from fastapi_app.core.config import settings
engine = create_engine(settings.DATABASE_URL)
from sqlalchemy.orm import Session

with Session(engine) as db:
    print('=== production_plan ===')
    print('count:', db.execute(text('SELECT COUNT(*) FROM production_plan')).scalar())
    inspector = inspect(engine)
    columns = inspector.get_columns('production_plan')
    col_names = [c['name'] for c in columns]
    print('columns:', col_names)
    rows = db.execute(text(f'SELECT * FROM production_plan LIMIT 5')).fetchall()
    for r in rows:
        print(r)
