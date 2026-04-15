import pymysql

conn = pymysql.connect(host='localhost', user='root', password='110110')
cursor = conn.cursor()
cursor.execute('SHOW VARIABLES LIKE "datadir"')
result = cursor.fetchone()
print('MySQL数据目录:', result[1])

cursor.execute('USE erp_system')
cursor.execute('SHOW TABLES')
tables = cursor.fetchall()
print('\n数据库 erp_system 中的表:')
for table in tables:
    print(' -', table[0])

conn.close()
