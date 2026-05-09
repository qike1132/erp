"""检查数据库中的表"""
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import create_engine, text

from fastapi_app.core.config import settings


def main():
    engine = create_engine(settings.DATABASE_URL)
    
    with engine.connect() as conn:
        # 获取所有表名
        result = conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename"))
        tables = [row[0] for row in result]
        
        print("数据库中的表:")
        for table in tables:
            # 获取表的行数
            try:
                count_result = conn.execute(text(f"SELECT COUNT(*) FROM \"{table}\""))
                count = count_result.scalar()
                print(f"  - {table}: {count} 条")
            except Exception as e:
                print(f"  - {table}: 无法统计行数 - {e}")


if __name__ == '__main__':
    main()
