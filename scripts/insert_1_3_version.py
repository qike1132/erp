import hashlib
import os
from datetime import datetime
from pathlib import Path

import psycopg2
from _prod_write_guard import require_prod_write_consent

require_prod_write_consent('向生产库插入/推送 app 版本（会触发全设备 OTA）')

# 数据库配置
db_config = {
    'host': 'localhost',
    'port': '5432',
    'user': 'erp_app',
    'password': os.environ.get('DB_PASSWORD', ''),
    'dbname': 'erp_system',
}

print("=" * 60)
print("  1.3 版本 OTA 测试")
print("=" * 60)
print()

# 创建 static/releases 目录
PROJECT_ROOT = Path(__file__).resolve().parent.parent
upload_dir = PROJECT_ROOT / "static" / "releases"
os.makedirs(upload_dir, exist_ok=True)

# 创建测试 APK 文件
test_apk = upload_dir / "erp-v1.3.apk"
if test_apk.exists():
    os.remove(test_apk)
with open(test_apk, "wb") as f:
    f.write(b"PK\x03\x04")  # ZIP/APK 魔数
    f.write(b"1.3 version test")

print(f"[1/4] 创建测试 APK: {test_apk}")

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

    # 检查是否已有 1.3 版本
    cur.execute("SELECT id FROM app_version WHERE version_code = %s", (77,))
    existing = cur.fetchone()
    if existing:
        print(f"版本 77 (1.3) 已存在，ID={existing[0]}")
        print("删除旧版本...")
        cur.execute("DELETE FROM app_version WHERE version_code = %s", (77,))
        conn.commit()

    print("[2/4] 插入数据库...")

    now = datetime.now()
    size = os.path.getsize(test_apk)

    # 计算简单的 MD5
    md5_hash = hashlib.md5()
    with open(test_apk, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            md5_hash.update(byte_block)
    md5 = md5_hash.hexdigest()

    changelog = "1.3 版本更新:\n- 修复 APK 推送通知\n- 添加版本号显示\n- 优化 Dashboard 统计"

    # 插入版本 1.3 (待发布状态)
    cur.execute("""
        INSERT INTO app_version (platform, version_code, version_name, download_url, changelog, file_size, file_md5, force_update, is_active, is_pushed, created_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
    """, ('android', 77, '1.3', '/static/releases/erp-v1.3.apk', changelog, size, md5, False, False, False, now))

    version_id = cur.fetchone()[0]
    conn.commit()

    print(f"  [OK] 插入成功, ID={version_id}")

    print("[3/4] 激活版本...")
    cur.execute("""
        UPDATE app_version
        SET is_active = %s, updated_at = %s
        WHERE id = %s
    """, (True, datetime.now(), version_id))
    conn.commit()
    print("  [OK] 版本已激活")

    print("[4/4] 标记为已推送...")
    cur.execute("""
        UPDATE app_version
        SET is_pushed = %s, pushed_at = %s, updated_at = %s
        WHERE id = %s
    """, (True, datetime.now(), datetime.now(), version_id))
    conn.commit()
    print("  [OK] 已标记推送")

    print()
    print("=" * 60)
    print("  1.3 版本测试完成!")
    print("=" * 60)
    print()
    print("  版本: v1.3 (code=77)")
    print(f"  ID: {version_id}")
    print(f"  APK: {test_apk} ({size} bytes)")
    print(f"  MD5: {md5}")
    print("  状态: 已发布")
    print()
    print("  访问:")
    print("  - 管理页: http://192.168.0.95:3000/app-update")
    print("  - APK下载: http://192.168.0.95:5002/static/releases/erp-v1.3.apk")
    print()

    cur.close()
    conn.close()

except Exception as e:
    print(f"错误: {e}")
    import traceback
    traceback.print_exc()
    if conn:
        conn.rollback()
        conn.close()
    exit(1)
