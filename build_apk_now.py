#!/usr/bin/env python3
"""
一键构建 APK 脚本
由于终端环境问题，这个脚本提供手动构建步骤
"""
import os
import sys
import shutil
import hashlib
from pathlib import Path

PROJECT_ROOT = Path("d:/erp_system")
ANDROID_DIR = PROJECT_ROOT / "android-app"
RELEASE_DIR = PROJECT_ROOT / "static" / "releases"

def compute_md5(file_path: str) -> str:
    hash_md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()

def main():
    print("=" * 60)
    print("  ERP APK 构建发布")
    print("=" * 60)
    
    # 读取版本信息
    version_props = {}
    with open(ANDROID_DIR / "version.properties", "r") as f:
        for line in f:
            if "=" in line:
                k, v = line.strip().split("=", 1)
                version_props[k] = v
    
    version_code = version_props.get("VERSION_CODE", "76")
    version_name = version_props.get("VERSION_NAME", "1.2")
    
    print(f"\n当前版本: v{version_name} (code={version_code})")
    print(f"项目路径: {ANDROID_DIR}")
    
    # 检查现有APK
    existing_apk = RELEASE_DIR / f"test_v{version_name.replace('.', '')}.apk"
    if existing_apk.exists():
        print(f"\n✅ 已存在APK: {existing_apk}")
        print(f"   大小: {existing_apk.stat().st_size / 1024:.1f} KB")
        
        # 计算MD5
        md5 = compute_md5(str(existing_apk))
        print(f"   MD5: {md5}")
        
        # 复制为正式版本
        formal_apk = RELEASE_DIR / f"erp-v{version_name}.apk"
        shutil.copy2(existing_apk, formal_apk)
        print(f"\n✅ 已复制为正式版本: {formal_apk}")
        
        print("\n" + "=" * 60)
        print("  APK 准备完成!")
        print("=" * 60)
        print(f"\n下载地址: http://192.168.0.95:5002/static/releases/erp-v{version_name}.apk")
        print(f"管理页面: http://192.168.0.95:3000/app-update")
        
        return 0
    else:
        print(f"\n❌ 找不到现有APK: {existing_apk}")
        print("\n请手动执行Gradle构建:")
        print(f"  cd {ANDROID_DIR}")
        print("  .\\gradlew.bat assembleRelease")
        return 1

if __name__ == "__main__":
    sys.exit(main())
