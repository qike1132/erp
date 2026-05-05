import psycopg2
import os
from datetime import datetime

# 数据库配置
db_config = {
    'host': 'localhost',
    'port': '5432',
    'user': 'erp_app',
    'password': '110110',
    'dbname': 'erp_system',
}

print("=" * 50)
print("插入 App版本 测试数据")
print("=" * 50)
print()

# 创建 static/releases 目录
upload_dir = os.path.join(os.path.dirname(__file__), '..', 'static', 'releases')
os.makedirs(upload_dir, exist_ok=True)

# 创建测试文件
test_apk1 = os.path.join(upload_dir, "test_v10.apk")
with open(test_apk1, "wb") as f:
    f.write(b"test content 1.0")

test_apk2 = os.path.join(upload_dir, "test_v11.apk")
with open(test_apk2, "wb") as f:
    f.write(b"test content 1.1")

conn = None
try:
    conn = psycopg2.connect(**db_config)
    cur = conn.cursor()

    # 检查表是否存在
    cur.execute("SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_name='app_version')")
    exists = cur.fetchone()[0]

    if not exists:
        print("错误: app_version 表不存在，请先运行迁移")
        conn.close()
        exit(1)

    # 检查是否已有数据
    cur.execute("SELECT COUNT(*) FROM app_version")
    count = cur.fetchone()[0]
    if count > 0:
        print(f"数据库中已有 {count} 条数据，跳过插入")
        conn.commit()
        conn.close()
        print()
        print("请访问 http://192.168.0.95:3000/app-update 查看")
        exit(0)

    # 插入测试数据
    print("正在插入测试数据...")

    now = datetime.now().isoformat()
    size1 = os.path.getsize(test_apk1)
    size2 = os.path.getsize(test_apk2)

    # 版本 1: 待发布
    cur.execute("""
        INSERT INTO app_version (platform, version_code, version_name, download_url, changelog, file_size, force_update, is_active, pushed, created_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, ('android', 75, '1.0', '/static/releases/test_v10.apk', '初始版本，测试功能', size1, False, False, False, now))

    # 版本 2: 已发布
    cur.execute("""
        INSERT INTO app_version (platform, version_code, version_name, download_url, changelog, file_size, force_update, is_active, pushed, created_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, ('android', 76, '1.1', '/static/releases/test_v11.apk', '新版本，测试推送功能', size2, True, True, True, now))

    conn.commit()
    print("✅ 插入 2 条测试数据成功！")
    print()
    print("   - v1.0 (待发布，黄色标记)")
    print("   - v1.1 (已发布，绿色标记)")
    print()
    print("请访问 http://192.168.0.95:3000/app-update 查看")
    print()

    cur.close()
    conn.close()

except Exception as e:
    print(f"错误: {e}")
    if conn:
        conn.close()
    exit(1)
