from fastapi_app.core.database import get_sync_engine
from sqlalchemy import text
eng = get_sync_engine()
conn = eng.connect()
print("=== inventory_log columns ===")
for r in conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name='inventory_log' ORDER BY ordinal_position")):
    print(" -", r[0])
print("=== inventory_log indexes ===")
for r in conn.execute(text("SELECT indexname FROM pg_indexes WHERE schemaname='public' AND tablename='inventory_log'")):
    print(" -", r[0])
conn.close()
