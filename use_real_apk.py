#!/usr/bin/env python3
"""
使用之前真实构建好的APK作为1.3版本
"""
import os
from pathlib import Path
import hashlib
import psycopg2
from datetime import datetime
import shutil

print("=" * 60)
print("  使用真实APK作为 1.3 版本")
print("=" * 60)

# 源APK（之前真实构建好的）
source_apk = Path(__file__).parent / "android-app" / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk"

# 目标APK
releases_dir = Path(__file__).parent / "static" / "releases"
releases_dir.mkdir(parents=True, exist_ok=True)
target_apk = releases_dir / "erp-v1.3.apk"

print(f"\n源APK: {source_apk}")
print(f"目标: {target_apk}")

if not source_apk.exists():
    print(f"❌ 源APK不存在!")
    exit(1)

# 复制文件
print(f"\n复制中...")
shutil.copy2(source_apk, target_apk)

# 计算MD5和大小
md5_hash = hashlib.md5()
with open(target_apk, 'rb') as f:
    for byte_block in iter(lambda: f.read(4096), b""):
        md5_hash.update(byte_block)
md5 = md5_hash.hexdigest()

size = target_apk.stat().st_size
size_mb = size / 1024 / 1024

print(f"\n✅ 复制成功!")
print(f"   文件: {target_apk}")
print(f"   大小: {size_mb:.2f} MB")
print(f"   MD5: {md5}")

# 更新数据库
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
    
    # 更新1.3版本记录
    changelog = "1.3 版本更新\n- 修复APK推送通知\n- 添加版本号显示\n- 优化Dashboard统计"
    
    cur.execute("""
        UPDATE app_version 
        SET 
            version_name = '1.3',
            version_code = 77,
            changelog = %s,
            file_size = %s,
            file_md5 = %s,
            download_url = '/static/releases/erp-v1.3.apk',
            is_active = true,
            is_pushed = true,
            pushed_at = %s,
            updated_at = %s
        WHERE version_code = 77
    """, (changelog, size, md5, datetime.now(), datetime.now()))
    
    conn.commit()
    print("✅ 数据库已更新")
    
    cur.close()
    conn.close()
    
except Exception as e:
    print(f"❌ 数据库错误: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 60)
print("  1.3 版本真实APK准备完成!")
print("=" * 60)
print("\n访问:")
print("  - 管理页: http://192.168.0.95:3000/app-update")
print("  - APK下载: http://192.168.0.95:5002/static/releases/erp-v1.3.apk")
