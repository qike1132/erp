
import os
import subprocess
import shutil
from pathlib import Path

print("=" * 60)
print("  查找 Java 并构建 APK")
print("=" * 60)

# 查找 Java 的常见位置
java_paths = [
    r"C:\Program Files\Android\Android Studio\jbr",
    r"C:\Program Files\Android\Android Studio\jre",
    r"C:\Program Files\Eclipse Adoptium\jdk-17.0.10-hotspot",
    r"C:\Program Files\Java\jdk-17",
    r"C:\Program Files\Java\jdk-11",
]

java_found = None
for jp in java_paths:
    java_exe = os.path.join(jp, "bin", "java.exe")
    if os.path.exists(java_exe):
        java_found = jp
        print(f"\n✓ 找到 Java: {jp}")
        break

if not java_found:
    print("\n未找到标准位置的 Java，尝试搜索...")
    # 搜索常见位置
    search_roots = [
        r"C:\Program Files",
        r"C:\Program Files (x86)",
        r"C:\Users\Administrator\AppData\Local",
    ]
    
    for root in search_roots:
        try:
            for dirpath, dirnames, filenames in os.walk(root, topdown=True):
                if "java.exe" in filenames and "bin" in dirpath:
                    java_home = os.path.dirname(dirpath)
                    if os.path.exists(os.path.join(java_home, "bin", "java.exe")):
                        java_found = java_home
                        print(f"\n✓ 找到 Java: {java_home}")
                        break
            if java_found:
                break
        except (PermissionError, OSError):
            continue

if not java_found:
    print("\n❌ 未找到 Java!")
    print("\n请安装:")
    print("  - Android Studio (包含 JBR)")
    print("  - 或 JDK 17+")
    exit(1)

# 设置环境变量
env = os.environ.copy()
env['JAVA_HOME'] = java_found
env['PATH'] = f"{os.path.join(java_found, 'bin')};{env['PATH']}"

# 检查现有 APK
android_app_dir = Path(__file__).parent / "android-app"
debug_apk = android_app_dir / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk"

if debug_apk.exists():
    size_mb = debug_apk.stat().st_size / 1024 / 1024
    print(f"\n✓ 找到已构建的 APK: {debug_apk}")
    print(f"  大小: {size_mb:.2f} MB")
    
    # 复制到 releases 目录
    releases_dir = Path(__file__).parent / "static" / "releases"
    releases_dir.mkdir(exist_ok=True)
    target_apk = releases_dir / "erp-v1.3.apk"
    
    print(f"\n复制到: {target_apk}")
    shutil.copy2(debug_apk, target_apk)
    
    print(f"\n✓ 完成!")
    print(f"\nAPK 位置: {target_apk}")
    print(f"下载地址: http://192.168.0.95:5000/static/releases/erp-v1.3.apk")
else:
    print(f"\n未找到已构建的 APK，尝试构建...")
    print(f"位置: {debug_apk}")
    
    # 尝试构建
    os.chdir(android_app_dir)
    
    print(f"\nJAVA_HOME: {env['JAVA_HOME']}")
    
    try:
        # 先尝试 clean
        print("\n步骤 1/2: 清理...")
        result = subprocess.run(
            [r'.\gradlew.bat', 'clean'],
            env=env,
            capture_output=True,
            text=True,
            timeout=300
        )
        print(f"  退出码: {result.returncode}")
        
        # 再构建
        print("\n步骤 2/2: 构建 Debug APK...")
        result = subprocess.run(
            [r'.\gradlew.bat', 'assembleDebug'],
            env=env,
            capture_output=True,
            text=True,
            timeout=600
        )
        
        print(f"  退出码: {result.returncode}")
        
        if result.returncode == 0 and debug_apk.exists():
            size_mb = debug_apk.stat().st_size / 1024 / 1024
            print(f"\n✓ 构建成功!")
            print(f"  APK: {debug_apk}")
            print(f"  大小: {size_mb:.2f} MB")
            
            # 复制到 releases 目录
            releases_dir = Path(__file__).parent / "static" / "releases"
            releases_dir.mkdir(exist_ok=True)
            target_apk = releases_dir / "erp-v1.3.apk"
            
            print(f"\n复制到: {target_apk}")
            shutil.copy2(debug_apk, target_apk)
            
            print(f"\n✓ 完成!")
            print(f"\nAPK 位置: {target_apk}")
            print(f"下载地址: http://192.168.0.95:5000/static/releases/erp-v1.3.apk")
        else:
            print(f"\n❌ 构建失败!")
            print(f"STDOUT: {result.stdout[:500]}...")
            print(f"STDERR: {result.stderr[:500]}...")
            
    except Exception as e:
        print(f"\n❌ 构建异常: {e}")
        import traceback
        traceback.print_exc()

print("\n" + "=" * 60)

