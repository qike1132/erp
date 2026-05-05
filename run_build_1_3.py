#!/usr/bin/env python3
"""
直接执行批处理文件构建 1.3 APK
"""
import subprocess
import sys
import os
from pathlib import Path

print("=" * 60)
print("  1.3 APK 构建")
print("=" * 60)

# 设置环境变量
os.environ['JAVA_HOME'] = r'C:\Program Files\Java\jdk-17'
os.environ['ANDROID_HOME'] = r'C:\Users\Administrator\AppData\Local\Android\Sdk'

# 批处理文件路径
bat_path = Path(__file__).parent / 'build_1_3_apk.bat'

print(f"\n批处理文件: {bat_path}")
print(f"工作目录: {Path(__file__).parent / 'android-app'}")
print("\n开始构建...\n")

# 直接使用 subprocess 调用 cmd.exe 执行批处理
try:
    result = subprocess.run(
        ['cmd.exe', '/c', str(bat_path)],
        cwd=str(Path(__file__).parent),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding='utf-8',
        errors='ignore'
    )
    
    print(result.stdout)
    
    if result.returncode == 0:
        print("\n✅ 构建命令执行完成")
    else:
        print(f"\n⚠️  构建命令返回码: {result.returncode}")
        
except Exception as e:
    print(f"\n❌ 执行异常: {e}")
    import traceback
    traceback.print_exc()

# 检查APK文件
print("\n检查构建结果...")
apk_build_path = Path(__file__).parent / 'android-app' / 'app' / 'build' / 'outputs' / 'apk' / 'debug' / 'app-debug.apk'
apk_release_path = Path(__file__).parent / 'static' / 'releases' / 'erp-v1.3.apk'

if apk_build_path.exists():
    size_mb = apk_build_path.stat().st_size / (1024 * 1024)
    print(f"\n✅ 找到APK: {apk_build_path}")
    print(f"   大小: {size_mb:.1f} MB")
    
    # 复制到发布目录
    print(f"\n复制到发布目录...")
    import shutil
    apk_release_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(apk_build_path, apk_release_path)
    print(f"✅ 已复制到: {apk_release_path}")
else:
    print(f"\n❌ 未找到APK: {apk_build_path}")
    
print("\n" + "=" * 60)
