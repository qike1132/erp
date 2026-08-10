import psycopg2

conn = psycopg2.connect(
    host='localhost', port=5432,
    dbname='erp_system', user='erp_app', password='110110',
)
cur = conn.cursor()

# 删除唯一索引
cur.execute("DROP INDEX IF EXISTS uq_csp_part_name")
conn.commit()
print('Dropped unique index uq_csp_part_name')

# 创建普通索引替代
cur.execute("CREATE INDEX IF NOT EXISTS idx_csp_part_name ON customer_sampling_part (project_id, part_name)")
conn.commit()
print('Created normal index idx_csp_part_name')

# 验证
cur.execute("SELECT indexname, indexdef FROM pg_indexes WHERE tablename='customer_sampling_part'")
print('\n=== Indexes after fix ===')
for row in cur.fetchall():
    print(row[1])

cur.close()
conn.close()
