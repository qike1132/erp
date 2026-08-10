import psycopg2

conn = psycopg2.connect(
    host='localhost', port=5432,
    dbname='erp_system', user='erp_app', password='110110',
)
cur = conn.cursor()

# 检查所有索引（包括唯一索引）
cur.execute("SELECT indexname, indexdef FROM pg_indexes WHERE tablename='customer_sampling_part'")
print('=== Indexes ===')
for row in cur.fetchall():
    print(row[1])

# 检查所有列
cur.execute("SELECT column_name, data_type, is_nullable FROM information_schema.columns WHERE table_name='customer_sampling_part' ORDER BY ordinal_position")
print('\n=== Columns ===')
for row in cur.fetchall():
    print(f'  {row[0]}: {row[1]} (nullable={row[2]})')

# 检查现有数据
cur.execute("SELECT id, project_id, part_name, sort_order, fabric_name, fabric_color_no, supplier_name, version FROM customer_sampling_part ORDER BY id DESC LIMIT 5")
print('\n=== Recent parts ===')
for row in cur.fetchall():
    print(f'  id={row[0]}, project={row[1]}, name={row[2]}, sort={row[3]}, fabric={row[4]}, color={row[5]}, supplier={row[6]}, ver={row[7]}')

cur.close()
conn.close()
