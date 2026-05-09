import sys
from pathlib import Path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
from sqlalchemy import create_engine, text
from fastapi_app.core.config import settings

engine = create_engine(settings.DATABASE_URL)
RESERVED = {"order", "case", "user"}

with engine.connect() as conn:
    result = conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"))
    tables = [row[0] for row in result]
    print("=== 全表数据验证 ===")
    has_data = False
    for t in tables:
        tbl_ref = f'"{t}"' if t in RESERVED else t
        count = conn.execute(text(f'SELECT COUNT(*) FROM {tbl_ref}')).scalar()
        if count > 0:
            has_data = True
            print(f"  {t}: {count} 条")
    if not has_data:
        print("  所有业务表数据均为 0")
    print()

    admin_count = conn.execute(text("SELECT COUNT(*) FROM \"user\" WHERE username='admin'")).scalar()
    perm_count = conn.execute(text("SELECT COUNT(*) FROM permission")).scalar()
    up_count = conn.execute(text("SELECT COUNT(*) FROM user_permission")).scalar()
    alembic_count = conn.execute(text("SELECT COUNT(*) FROM alembic_version")).scalar()
    print("=== 系统基础数据保留情况 ===")
    print(f"  admin 用户: {admin_count} 条 {'✓' if admin_count == 1 else '✗'}")
    print(f"  权限定义: {perm_count} 条 {'✓' if perm_count > 0 else '✗'}")
    print(f"  admin 权限: {up_count} 条 {'✓' if up_count > 0 else '✗'}")
    print(f"  迁移版本: {alembic_count} 条 {'✓' if alembic_count > 0 else '✗'}")
