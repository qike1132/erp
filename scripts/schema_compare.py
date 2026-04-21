"""
Phase 6.0: 自动化 Schema 对比脚本

两方对比：数据库实际结构 vs FastAPI 模型定义
输出差异报告，0 差异或差异已有合理解释才能继续 Phase 6.1。
"""

import sys
import os

# 确保项目根目录在 sys.path 中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main():
    from sqlalchemy import inspect as sa_inspect
    from fastapi_app.core.database import sync_engine

    # 1. 获取数据库实际结构
    print("=" * 60)
    print("Step 1: 获取数据库实际结构...")
    print("=" * 60)
    db_inspector = sa_inspect(sync_engine)
    db_tables = {}
    for table_name in sorted(db_inspector.get_table_names()):
        columns = {}
        for col in db_inspector.get_columns(table_name):
            columns[col['name']] = {
                'type': str(col['type']),
                'nullable': col.get('nullable', True),
                'default': str(col.get('default', '')),
            }
        db_tables[table_name] = columns
    print(f"  数据库共 {len(db_tables)} 张表")

    # 2. 获取 FastAPI 模型定义
    print("\n" + "=" * 60)
    print("Step 2: 获取 FastAPI 模型定义...")
    print("=" * 60)
    fastapi_tables = {}
    try:
        from fastapi_app.shared_models import Base
        # 触发所有模型注册
        import importlib
        models_pkg = os.path.join(os.path.dirname(__file__), 'fastapi_app', 'shared_models')
        if os.path.isdir(models_pkg):
            for fname in os.listdir(models_pkg):
                if fname.endswith('.py') and not fname.startswith('_'):
                    try:
                        importlib.import_module(f"fastapi_app.shared_models.{fname[:-3]}")
                    except Exception:
                        pass

        for mapper in Base.registry.mappers:
            table = mapper.local_table
            columns = {}
            for c in table.columns:
                columns[c.name] = {
                    'type': str(c.type),
                    'nullable': c.nullable,
                    'default': str(c.default) if c.default else '',
                }
            fastapi_tables[table.name] = columns
        print(f"  FastAPI 模型共 {len(fastapi_tables)} 张表")
    except Exception as e:
        print(f"  FastAPI 模型加载失败: {e}")

    # 3. 两方对比
    print("\n" + "=" * 60)
    print("Step 3: 对比结果")
    print("=" * 60)

    all_tables = set(db_tables.keys()) | set(fastapi_tables.keys())
    differences = []

    for table in sorted(all_tables):
        in_db = table in db_tables
        in_fastapi = table in fastapi_tables

        if not in_db:
            differences.append(f"  表 '{table}': 仅存在于模型定义中，数据库中不存在")
            continue
        if not in_fastapi:
            differences.append(f"  表 '{table}': 仅存在于数据库中，无模型定义")
            continue

        db_cols = db_tables.get(table, {})
        fastapi_cols = fastapi_tables.get(table, {})

        all_cols = set(db_cols.keys()) | set(fastapi_cols.keys())

        for col in sorted(all_cols):
            in_db_col = col in db_cols
            in_fastapi_col = col in fastapi_cols

            if not in_db_col:
                differences.append(f"  表 '{table}'.列 '{col}': 仅存在于 FastAPI 模型中，数据库中不存在")
                continue

            if in_fastapi_col and db_cols[col]['type'] != fastapi_cols[col]['type']:
                differences.append(f"  表 '{table}'.列 '{col}': DB类型={db_cols[col]['type']} vs FastAPI类型={fastapi_cols[col]['type']}")

    if differences:
        print(f"\n发现 {len(differences)} 处差异:")
        for diff in differences:
            print(diff)
    else:
        print("\n三方对比无差异！所有模型定义与数据库结构一致。")

    # 4. 统计摘要
    print("\n" + "=" * 60)
    print("摘要")
    print("=" * 60)
    print(f"  数据库表数: {len(db_tables)}")
    print(f"  FastAPI 模型表数: {len(fastapi_tables)}")
    print(f"  差异数: {len(differences)}")

    return len(differences)


if __name__ == "__main__":
    diff_count = main()
    sys.exit(diff_count)
