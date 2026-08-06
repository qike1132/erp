"""验证 uq_po_pending_dedup 索引是否已成功创建（COALESCE 版本）"""
import sys
from sqlalchemy import text
from fastapi_app.core.database import get_sync_engine

engine = get_sync_engine()
with engine.connect() as conn:
    result = conn.execute(text("""
        SELECT indexname, indexdef
        FROM pg_indexes
        WHERE tablename = 'purchase_order' AND indexname = 'uq_po_pending_dedup'
    """))
    row = result.fetchone()
    if row:
        print('=' * 60)
        print('OK  索引已创建:')
        print(f'  name: {row[0]}')
        print(f'  def:  {row[1]}')
    else:
        print('FAIL  未找到索引 uq_po_pending_dedup')
        sys.exit(1)

    result = conn.execute(text('SELECT version_num FROM alembic_version ORDER BY version_num'))
    versions = [r[0] for r in result]
    print()
    print(f'alembic_version: {versions}')

    result = conn.execute(text("SELECT COUNT(*) FROM purchase_order WHERE status = 'pending'"))
    cnt = result.fetchone()[0]
    print(f'pending 采购订单数: {cnt}')

    # 验证 COALESCE 约束是否生效：尝试 INSERT 重复记录应失败
    print()
    print('测试 COALESCE 约束是否拦截 NULL supplier_id 的重复 INSERT...')
    test_sql = text("""
        INSERT INTO purchase_order (order_no, customer_name, supplier_name, supplier_id, status, source_order_ids, product_name, product_quantity, total_amount, create_time, update_time)
        VALUES ('TEST-DUP-001', 'TEST', '1', NULL, 'pending', '[999999]', 'test', 1, 0, NOW(), NOW())
    """)
    try:
        conn.execute(test_sql)
        conn.execute(text("""
            INSERT INTO purchase_order (order_no, customer_name, supplier_name, supplier_id, status, source_order_ids, product_name, product_quantity, total_amount, create_time, update_time)
            VALUES ('TEST-DUP-002', 'TEST', '2', NULL, 'pending', '[999999]', 'test', 1, 0, NOW(), NOW())
        """))
        conn.commit()
        print('FAIL  约束未生效！两条 NULL supplier_id 的重复记录都插入成功了')
        # 清理
        conn.execute(text("DELETE FROM purchase_order WHERE order_no IN ('TEST-DUP-001', 'TEST-DUP-002')"))
        conn.commit()
        sys.exit(1)
    except Exception as e:
        conn.rollback()
        msg = str(e)
        if 'uq_po_pending_dedup' in msg:
            print('OK  约束已生效！第二条重复 INSERT 被正确拒绝')
        else:
            print(f'WARN  插入失败但不是由于 dedup 约束: {msg}')

    # 清理可能的测试数据
    conn.execute(text("DELETE FROM purchase_order WHERE order_no LIKE 'TEST-DUP-%'"))
    conn.commit()
    print('=' * 60)
