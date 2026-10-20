"""Add fabric_color_no column to customer_sampling_part table（已归档，勿再使用）。

2026-10-17 审计 Z08-R1：该列已由 Alembic 迁移
``pg_standalone_021_remove_part_name_unique.py`` 正式添加；本脚本是绕过迁移链的
第二真相源，移至 archive/ 仅作历史参考。确需运行须显式加
``--allow-deprecated-script``。
"""
import os
import sys

if '--allow-deprecated-script' not in sys.argv:
    print('已归档：请使用迁移 pg_standalone_021（该列已由 Alembic 管理）。')
    print('确需运行请显式加 --allow-deprecated-script。')
    sys.exit(2)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sqlalchemy import create_engine, text

from fastapi_app.core.config import Settings

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
