#!/usr/bin/env python3
"""简单的重新打包发布流程：使用现有APK文件"""
import os
import sys
import shutil
import json
import hashlib
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR
ANDROID_DIR = PROJECT_ROOT / "android-app"
RELEASE_DIR = PROJECT_ROOT / "static" / "releases"

VERSION_CODE = 76
VERSION_NAME = "1.2"

def compute_md5(file_path: str) -> str:
    """计算文件的 MD5 hash"""
    hash_md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()

def main():
    print("=" * 60)
    print(f"  ERP APK 重新发布  (v{VERSION_NAME}, code={VERSION_CODE})")
    print("=" * 60)

    # 查找现有 APK
    source_apk = RELEASE_DIR / "test_v12.apk"
    if not source_apk.exists():
        print(f"[ERROR] 找不到APK: {source_apk}")
        return 1

    print(f"[OK] 使用现有APK: {source_apk} ({source_apk.stat().st_size / 1024 / 1024:.1f} MB)")

    # 计算 MD5
    md5 = compute_md5(str(source_apk))
    print(f"[OK] MD5: {md5}")

    # 复制到发布目录（如果还不在那里）
    target_apk = RELEASE_DIR / f"erp-v{VERSION_NAME}.apk"
    if source_apk != target_apk:
        shutil.copy2(source_apk, target_apk)
        print(f"[OK] 已复制到: {target_apk}")
    else:
        print(f"[OK] APK已在发布目录: {target_apk}")

    print("\n" + "=" * 60)
    print(f"  重新发布完成!")
    print(f"  版本: v{VERSION_NAME} (code={VERSION_CODE})")
    print(f"  MD5:  {md5}")
    print(f"  APK:  {target_apk}")
    print("=" * 60)
    return 0

if __name__ == "__main__":
    sys.exit(main())
