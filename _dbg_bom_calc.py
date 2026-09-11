# -*- coding: utf-8 -*-
"""诊断：物料计算器 BOM 与产品录入页 BOM 不一致（只读查询）"""
import psycopg2, psycopg2.extras, sys

sys.stdout.reconfigure(encoding='utf-8')

CONN = dict(host='localhost', port=5432, user='erp_app', password='110110', dbname='erp_system')
conn = psycopg2.connect(**CONN)
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

print('=== 1. 名称匹配的产品 ===')
cur.execute("""
    SELECT id, name, barcode, create_time
    FROM product
    WHERE name LIKE %s OR name LIKE %s OR name LIKE %s
    ORDER BY id
""", ('%团子木鱼%', '%蛋仔派对%', '%木鱼%'))
rows = cur.fetchall()
for r in rows:
    print(f"  id={r['id']:<6} name={r['name']!r:<45} barcode={r['barcode']}")

if not rows:
    print('  未找到匹配产品')
    sys.exit(0)

print('\n=== 2. 各匹配产品的 BOM 明细 ===')
for p in rows:
    pid, pname = p['id'], p['name']
    print(f"\n--- [{pid}] {pname} ---")

    cur.execute("SELECT id, role_id, material_code, cotton_usage, specification, supplier_name, unit, remark FROM product_material WHERE product_id=%s ORDER BY id", (pid,))
    mats = cur.fetchall()
    print(f"  product_material ({len(mats)} 行):")
    for m in mats:
        print(f"    #{m['id']} role_id={m['role_id']} code={m['material_code']!r} cotton_usage={m['cotton_usage']} spec={m['specification']!r} sup={m['supplier_name']!r} unit={m['unit']!r}")

    cur.execute("SELECT id, role_id, material_code, fabric_name, specification, quantity, supplier_name, unit FROM product_fabric WHERE product_id=%s ORDER BY id", (pid,))
    fbs = cur.fetchall()
    print(f"  product_fabric ({len(fbs)} 行):")
    for f in fbs:
        print(f"    #{f['id']} role_id={f['role_id']} code={f['material_code']!r} name={f['fabric_name']!r} spec={f['specification']!r} qty={f['quantity']} sup={f['supplier_name']!r} unit={f['unit']!r}")

    cur.execute("SELECT id, role_id, material_code, accessory_name, specification, quantity, supplier_name, unit, material_category FROM product_accessory WHERE product_id=%s ORDER BY id", (pid,))
    accs = cur.fetchall()
    print(f"  product_accessory ({len(accs)} 行):")
    for a in accs:
        print(f"    #{a['id']} role_id={a['role_id']} cat={a['material_category']!r} code={a['material_code']!r} name={a['accessory_name']!r} spec={a['specification']!r} qty={a['quantity']} sup={a['supplier_name']!r} unit={a['unit']!r}")

    cur.execute("SELECT id, role_name FROM product_role WHERE product_id=%s ORDER BY id", (pid,))
    rls = cur.fetchall()
    print(f"  product_role ({len(rls)} 行): {[(r['id'], r['role_name']) for r in rls]}")

    # has_bom 判定（模拟 shared_models.Product.has_bom）
    has_filling = any((m['cotton_usage'] or 0) > 0 for m in mats)
    has_bom = has_filling or len(fbs) > 0 or len(accs) > 0
    print(f"  >> has_bom={has_bom} (filling={has_filling}, fabric={len(fbs)}, accessory={len(accs)})")

    # 模拟 aggregate_materials(quantity=1)
    agg = {}
    for m in mats:
        if (m['cotton_usage'] or 0) > 0:
            k = ('filling', '棉花/填充物', m['supplier_name'] or '', m['specification'] or '')
            agg[k] = agg.get(k, 0) + float(m['cotton_usage'] or 0)
    for f in fbs:
        k = ('fabric', f['fabric_name'], f['supplier_name'] or '', f['specification'] or '')
        agg[k] = agg.get(k, 0) + float(f['quantity'] or 0)
    for a in accs:
        k = (a['material_category'] or 'accessory', a['accessory_name'], a['supplier_name'] or '', a['specification'] or '')
        agg[k] = agg.get(k, 0) + float(a['quantity'] or 0)
    print(f"  >> 计算器(数量=1)聚合出 {len(agg)} 条物料:")
    for k, v in agg.items():
        print(f"     {k[0]:<10} {k[1]!r:<30} sup={k[2]!r:<20} spec={k[3]!r:<15} 用量={v}")

conn.close()
