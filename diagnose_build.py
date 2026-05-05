#!/usr/bin/env python3
"""
Gradle 构建诊断脚本
"""
import os
import subprocess
import sys
from pathlib import Path

ANDROID_DIR = Path("d:/erp_system/android-app")

def check_environment():
    print("=" * 60)
    print("环境检查")
    print("=" * 60)
    
    # 检查 Java
    java_home = os.environ.get("JAVA_HOME", "")
    print(f"JAVA_HOME: {java_home}")
    if java_home:
        java_exe = Path(java_home) / "bin" / "java.exe"
        if java_exe.exists():
            print(f"✅ Java 可执行文件存在: {java_exe}")
        else:
            print(f"❌ Java 可执行文件不存在")
    else:
        print("❌ JAVA_HOME 未设置")
    
    # 检查 Android SDK
    android_home = os.environ.get("ANDROID_HOME", "")
    print(f"ANDROID_HOME: {android_home}")
    if android_home:
        sdk_dir = Path(android_home)
        if sdk_dir.exists():
            print(f"✅ Android SDK 目录存在: {sdk_dir}")
            # 检查 build-tools
            build_tools = sdk_dir / "build-tools"
            if build_tools.exists():
                versions = list(build_tools.iterdir())
                print(f"✅ Build Tools 版本: {[v.name for v in versions]}")
            else:
                print("❌ Build Tools 不存在")
            # 检查 platform-tools
            platform_tools = sdk_dir / "platform-tools"
            if platform_tools.exists():
                print(f"✅ Platform Tools 存在")
            else:
                print("❌ Platform Tools 不存在")
        else:
            print(f"❌ Android SDK 目录不存在")
    else:
        print("❌ ANDROID_HOME 未设置")
    
    # 检查 Gradle Wrapper
    gradlew = ANDROID_DIR / "gradlew.bat"
    if gradlew.exists():
        print(f"✅ Gradle Wrapper 存在: {gradlew}")
    else:
        print(f"❌ Gradle Wrapper 不存在")
    
    # 检查 local.properties
    local_props = ANDROID_DIR / "local.properties"
    if local_props.exists():
        print(f"✅ local.properties 存在")
        with open(local_props) as f:
            content = f.read()
            if "sdk.dir" in content:
                print("✅ SDK 路径已配置")
            else:
                print("❌ SDK 路径未配置")
    else:
        print(f"❌ local.properties 不存在")
    
    # 检查版本属性
    version_props = ANDROID_DIR / "version.properties"
    if version_props.exists():
        print(f"✅ version.properties 存在")
        with open(version_props) as f:
            print(f"   内容: {f.read().strip()}")
    else:
        print(f"❌ version.properties 不存在")

def check_build_outputs():
    print("\n" + "=" * 60)
    print("构建输出检查")
    print("=" * 60)
    
    build_dir = ANDROID_DIR / "app" / "build"
    
    # 检查关键目录
    checks = [
        ("DEX 文件", build_dir / "intermediates" / "dex" / "debug" / "mergeExtDexDebug"),
        ("资源文件", build_dir / "intermediates" / "packaged_res" / "debug" / "packageDebugResources"),
        ("Manifest", build_dir / "intermediates" / "merged_manifest" / "debug" / "processDebugMainManifest"),
        ("Kotlin 编译输出", build_dir / "tmp" / "kotlin-classes" / "debug"),
        ("APK 输出", build_dir / "outputs" / "apk" / "debug"),
    ]
    
    for name, path in checks:
        if path.exists():
            files = list(path.iterdir()) if path.is_dir() else [path]
            print(f"✅ {name}: {path}")
            print(f"   文件数: {len(files)}")
        else:
            print(f"❌ {name}: 不存在")

def run_gradle_tasks():
    print("\n" + "=" * 60)
    print("Gradle 任务检查")
    print("=" * 60)
    
    env = os.environ.copy()
    env["JAVA_HOME"] = r"C:\Program Files\Java\jdk-17"
    env["ANDROID_HOME"] = r"C:\Users\Administrator\AppData\Local\Android\Sdk"
    env["GRADLE_OPTS"] = "-Dorg.gradle.daemon=false -Dorg.gradle.console=plain"
    
    # 检查可用任务
    result = subprocess.run(
        [str(ANDROID_DIR / "gradlew.bat"), "tasks", "--all", "--no-daemon", "--console=plain"],
        cwd=str(ANDROID_DIR),
        env=env,
        capture_output=True,
        text=True,
        timeout=120
    )
    
    if "assembleDebug" in result.stdout:
        print("✅ assembleDebug 任务可用")
    else:
        print("❌ assembleDebug 任务不可用")
    
    if "packageDebug" in result.stdout:
        print("✅ packageDebug 任务可用")
    else:
        print("❌ packageDebug 任务不可用")
    
    # 显示相关任务
    lines = result.stdout.split('\n')
    for line in lines:
        if 'Debug' in line or 'apk' in line.lower():
            print(f"   {line}")

def main():
    check_environment()
    check_build_outputs()
    run_gradle_tasks()
    
    print("\n" + "=" * 60)
    print("诊断完成")
    print("=" * 60)

if __name__ == "__main__":
    main()
