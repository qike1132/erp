#!/usr/bin/env python3
import subprocess
import os
from pathlib import Path
import psycopg2
import hashlib
from datetime import datetime

print("=== 查找并准备 1.3 APK ===\n")

# 首先检查是否还有之前的构建文件
android_app_dir = Path(__file__).parent / 'android-app'

# 检查所有可能的APK位置
possible_dirs = [
    android_app_dir / 'app' / 'build' / 'outputs' / 'apk' / 'debug',
    android_app_dir / 'app' / 'build' / 'outputs' / 'apk' / 'release',
    Path(__file__).parent / 'static' / 'releases',
]

found_apks = []
for apk_dir in possible_dirs:
    if apk_dir.exists():
        apks = list(apk_dir.glob('*.apk'))
        for apk in apks:
            found_apks.append(apk)
            print(f"找到APK: {apk} ({apk.stat().st_size / 1024 / 1024:.1f} MB)")

if not found_apks:
    print("❌ 未找到任何APK文件!")
    print("\n请先在 Android Studio 中手动构建:")
    print("1. 打开项目: d:\\erp_system\\android-app")
    print("2. 选择 Build -> Build Bundle(s) / APK(s) -> Build APK(s)")
    exit(1)

# 使用找到的第一个APK作为1.3版本
source_apk = found_apks[0]
print(f"\n使用: {source_apk}")

# 复制到发布目录
release_dir = Path(__file__).parent / 'static' / 'releases'
release_dir.mkdir(parents=True, exist_ok=True)
release_apk = release_dir / 'erp-v1.3.apk'

print(f"复制到: {release_apk}")
import shutil
shutil.copy2(source_apk, release_apk)

# 计算MD5
md5_hash = hashlib.md5()
with open(release_apk, 'rb') as f:
    for byte_block in iter(lambda: f.read(4096), b""):
        md5_hash.update(byte_block)
md5 = md5_hash.hexdigest()

size = release_apk.stat().st_size

print(f"\n✅ 准备完成!")
print(f"   文件: {release_apk}")
print(f"   大小: {size / 1024 / 1024:.1f} MB")
print(f"   MD5: {md5}")

# 更新数据库记录
print("\n更新数据库...")
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
    
    # 更新文件大小和MD5
    cur.execute("""
        UPDATE app_version 
        SET file_size = %s, file_md5 = %s, updated_at = %s
        WHERE version_code = %s
    """, (size, md5, datetime.now(), 77))
    
    conn.commit()
    print("✅ 数据库已更新")
    
    cur.close()
    conn.close()
    
except Exception as e:
    print(f"⚠️ 数据库更新失败: {e}")

print("\n" + "="*50)
print("1.3 APK 准备完成!")
print(f"发布地址: http://192.168.0.95:5002/static/releases/erp-v1.3.apk")
print("="*50)
