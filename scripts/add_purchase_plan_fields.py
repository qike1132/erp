"""添加 production_plan 新字段的迁移脚本"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from sqlalchemy import inspect, text

from fastapi_app.core.database import sync_engine


def main() -> None:
    from _prod_write_guard import require_prod_write_consent

    require_prod_write_consent('为 production_plan 增加字段（生产库 DDL）')

    insp = inspect(sync_engine)
    existing = [c['name'] for c in insp.get_columns('production_plan')]

    with sync_engine.connect() as conn:
        if 'shipped_qty' not in existing:
            conn.execute(text("ALTER TABLE production_plan ADD COLUMN shipped_qty INT DEFAULT 0 COMMENT '已出货数量'"))
            print("[OK] Added shipped_qty column")
        else:
            print("[SKIP] shipped_qty already exists")

        if 'upload_batch' not in existing:
            conn.execute(text("ALTER TABLE production_plan ADD COLUMN upload_batch VARCHAR(64) DEFAULT NULL COMMENT '上传批次ID'"))
            print("[OK] Added upload_batch column")
        else:
            print("[SKIP] upload_batch already exists")

        conn.commit()

    # Verify
    cols = [c['name'] for c in insp.get_columns('production_plan')]
    print(f"production_plan columns: {cols}")


if __name__ == '__main__':
    main()
