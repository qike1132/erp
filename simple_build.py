#!/usr/bin/env python3
import subprocess
import sys
import os
from pathlib import Path

print("=== 1.3 APK 构建 ===")

# 设置必要的环境
os.environ['JAVA_HOME'] = r'C:\Program Files\Java\jdk-17'
os.environ['ANDROID_HOME'] = r'C:\Users\Administrator\AppData\Local\Android\Sdk'

# Gradle 路径
gradle_path = Path(__file__).parent / 'android-app' / 'gradlew.bat'

# 构建输出目录
output_dir = Path(__file__).parent / 'android-app' / 'app' / 'build' / 'outputs' / 'apk' / 'debug'

# 清理旧构建
print("\n1. 清理...")
subprocess.run(
    [str(gradle_path), 'clean', '--no-daemon'],
    cwd=str(Path(__file__).parent / 'android-app'),
    capture_output=True
)

# 构建
print("\n2. 开始构建 (这可能需要几分钟)...")
result = subprocess.run(
    [str(gradle_path), 'assembleDebug', '--no-daemon', '--console=plain'],
    cwd=str(Path(__file__).parent / 'android-app'),
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True,
    encoding='utf-8',
    errors='ignore'
)

# 输出构建日志
print("\n构建输出 (最后部分):")
print(result.stdout[-2000:] if len(result.stdout) > 2000 else result.stdout)

if result.returncode != 0:
    print(f"\n❌ 构建失败 (退出码: {result.returncode})")
    sys.exit(1)

# 检查结果
print("\n3. 检查APK...")
apk_files = list(output_dir.glob("*.apk"))

if apk_files:
    apk_file = apk_files[0]
    size_mb = apk_file.stat().st_size / (1024 * 1024)
    
    print(f"✅ 构建成功!")
    print(f"   文件: {apk_file}")
    print(f"   大小: {size_mb:.1f} MB")
    
    # 复制到发布目录
    release_dir = Path(__file__).parent / 'static' / 'releases'
    release_dir.mkdir(parents=True, exist_ok=True)
    
    release_apk = release_dir / 'erp-v1.3.apk'
    
    print(f"\n4. 复制到发布目录...")
    import shutil
    shutil.copy2(apk_file, release_apk)
    print(f"✅ 已复制到: {release_apk}")
    
    print("\n" + "="*50)
    print("完成!")
    print(f"构建目录: {apk_file}")
    print(f"发布目录: {release_apk}")
    print("="*50)
else:
    print(f"❌ 未找到APK文件!")
    print(f"   检查的目录: {output_dir}")
    sys.exit(1)
