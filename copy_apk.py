#!/usr/bin/env python3
"""Copy real APK to 1.3 version"""
import shutil
import hashlib
import psycopg2
from datetime import datetime
from pathlib import Path

def main():
    # File paths
    src_apk = Path(r"d:\erp_system\android-app\app\build\outputs\apk\debug\app-debug.apk")
    dst_dir = Path(r"d:\erp_system\static\releases")
    dst_apk = dst_dir / "erp-v1.3.apk"
    
    # Ensure directory exists
    dst_dir.mkdir(parents=True, exist_ok=True)
    
    # Copy file
    print(f"Copying: {src_apk} -> {dst_apk}")
    shutil.copy2(src_apk, dst_apk)
    
    # Calculate MD5
    md5 = hashlib.md5()
    with open(dst_apk, "rb") as f:
        while chunk := f.read(8192):
            md5.update(chunk)
    md5_hex = md5.hexdigest()
    
    # Get size
    size = dst_apk.stat().st_size
    size_mb = size / (1024 * 1024)
    
    print(f"\nAPK ready: {dst_apk}")
    print(f"Size: {size_mb:.2f} MB")
    print(f"MD5: {md5_hex}")
    
    # Update database
    print("\nUpdating database...")
    try:
        conn = psycopg2.connect(
            host="localhost",
            port="5432",
            user="erp_app",
            password="110110",
            dbname="erp_system"
        )
        cur = conn.cursor()
        
        changelog = """1.3版本更新:
- 修复APK推送通知功能
- 在应用中添加版本号显示
- 优化Dashboard统计功能
- 解决PowerShell集成问题"""
        
        # Check if 1.3 exists, update or insert
        cur.execute("SELECT id FROM app_version WHERE version_code = 77")
        existing = cur.fetchone()
        
        if existing:
            version_id = existing[0]
            cur.execute("""
                UPDATE app_version
                SET 
                    version_name = '1.3',
                    changelog = %s,
                    file_path = %s,
                    download_url = '/static/releases/erp-v1.3.apk',
                    file_md5 = %s,
                    file_size = %s,
                    is_active = True,
                    is_pushed = True,
                    pushed_at = %s,
                    updated_at = %s
                WHERE id = %s
            """, (changelog, str(dst_apk), md5_hex, size, datetime.now(), datetime.now(), version_id))
            print(f"Updated existing version, id={version_id}")
        else:
            cur.execute("""
                INSERT INTO app_version (
                    platform, version_code, version_name, changelog, file_path,
                    download_url, file_md5, file_size,
                    force_update, is_active, is_pushed, created_at, updated_at, pushed_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (
                'android', 77, '1.3', changelog, str(dst_apk),
                '/static/releases/erp-v1.3.apk', md5_hex, size,
                False, True, True, datetime.now(), datetime.now(), datetime.now()
            ))
            version_id = cur.fetchone()[0]
            print(f"Inserted new version, id={version_id}")
        
        conn.commit()
        cur.close()
        conn.close()
        print("\n✅ Database updated successfully")
        
    except Exception as e:
        print(f"\n❌ Database error: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "="*60)
    print("✅ 1.3版本准备完成!")
    print("="*60)
    print("\n访问:")
    print("- 管理后台: http://192.168.0.95:3000/app-update")
    print("- APK下载: http://192.168.0.95:5002/static/releases/erp-v1.3.apk")

if __name__ == "__main__":
    main()
