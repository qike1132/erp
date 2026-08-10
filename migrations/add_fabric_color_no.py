"""Add fabric_color_no column to customer_sampling_part table."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi_app.core.config import Settings
from sqlalchemy import create_engine, text

settings = Settings()
engine = create_engine(settings.DATABASE_URL)

with engine.connect() as conn:
    result = conn.execute(text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = 'customer_sampling_part' AND column_name = 'fabric_color_no'"
    ))
    if result.fetchone():
        print("Column fabric_color_no already exists. Skipping.")
    else:
        conn.execute(text(
            "ALTER TABLE customer_sampling_part ADD COLUMN fabric_color_no VARCHAR(50)"
        ))
        conn.commit()
        print("Added fabric_color_no column successfully.")

print("Done.")
