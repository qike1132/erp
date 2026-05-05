#!/usr/bin/env python3
import os
from pathlib import Path
import hashlib
import psycopg2
from datetime import datetime

print("=" * 60)
print("  创建 1.3 版本 APK")
print("=" * 60)

# 创建目录
releases_dir = Path(__file__).parent / "static" / "releases"
releases_dir.mkdir(parents=True, exist_ok=True)

# 创建测试APK
apk_path = releases_dir / "erp-v1.3.apk"

# 创建一个看起来像APK的文件
with open(apk_path, "wb") as f:
    f.write(b"PK\x03\x04")  # APK/ZIP magic number
    # 写入一些内容让文件更大
    content = b"ERP 1.3 version\n" * 500
    f.write(content)

print(f"\n✅ 创建APK: {apk_path}")

# 计算MD5和大小
md5_hash = hashlib.md5()
with open(apk_path, "rb") as f:
    while True:
        data = f.read(4096)
        if not data:
            break
        md5_hash.update(data)
md5 = md5_hash.hexdigest()

size = apk_path.stat().st_size
size_mb = size / 1024 / 1024

print(f"   大小: {size_mb:.2f} MB")
print(f"   MD5: {md5}")

# 数据库操作
print(f"\n更新数据库...")

db_config = {
    'host': 'localhost',
    'port': '5432',
    'user': 'erp_app',
    'password': '110110',
    'dbname': 'erp_system',
}

try:
    conn = psycopg2.connect(**db_config)
    cur = conn.cursor()
    
    # 检查是否已经有1.3版本
    cur.execute("SELECT id FROM app_version WHERE version_code = %s", (77,))
    existing = cur.fetchone()
    
    if existing:
        # 更新现有记录
        cur.execute("""
            UPDATE app_version 
            SET file_size = %s, 
                file_md5 = %s,
                download_url = %s,
                updated_at = %s
            WHERE version_code = %s
        """, (size, md5, '/static/releases/erp-v1.3.apk', datetime.now(), 77))
        print(f"✅ 更新现有记录 (id={existing[0]})")
    else:
        # 插入新记录
        changelog = "1.3 版本更新\n- 修复APK推送通知\n- 添加版本号显示\n- 优化Dashboard统计"
        cur.execute("""
            INSERT INTO app_version 
                (platform, version_code, version_name, download_url, changelog,
                 file_size, file_md5, force_update, is_active, is_pushed, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, ('android', 77, '1.3', '/static/releases/erp-v1.3.apk', 
              changelog, size, md5, False, True, True, datetime.now()))
        print("✅ 插入新记录")
    
    conn.commit()
    cur.close()
    conn.close()
    
except Exception as e:
    print(f"❌ 数据库错误: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 60)
print("  1.3 版本 APK 准备完成!")
print("=" * 60)
print("\n访问:")
print("  管理页: http://192.168.0.95:3000/app-update")
print("  APK下载: http://192.168.0.95:5002/static/releases/erp-v1.3.apk")
print("\n说明:")
print("  - 此为测试APK")
print("  - 如需真实构建，请在Android Studio中构建后复制到此位置")
