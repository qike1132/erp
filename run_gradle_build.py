#!/usr/bin/env python3
"""
Gradle 构建脚本 - 绕过终端分页器问题
"""
import subprocess
import os
import sys
from pathlib import Path

ANDROID_DIR = Path("d:/erp_system/android-app")

def run_build():
    # 设置环境变量
    env = os.environ.copy()
    env["JAVA_HOME"] = r"C:\Program Files\Java\jdk-17"
    env["ANDROID_HOME"] = r"C:\Users\Administrator\AppData\Local\Android\Sdk"
    env["GRADLE_OPTS"] = "-Dorg.gradle.daemon=false -Dorg.gradle.console=plain"
    env["PAGER"] = ""  # 禁用分页器
    env["GIT_PAGER"] = ""  # 禁用 git 分页器
    
    # 构建命令
    cmd = [str(ANDROID_DIR / "gradlew.bat"), "assembleDebug", "--no-daemon", "--console=plain", "--info"]
    
    print("=" * 60)
    print("开始 Gradle 构建...")
    print(f"工作目录: {ANDROID_DIR}")
    print(f"命令: {' '.join(cmd)}")
    print("=" * 60)
    
    try:
        result = subprocess.run(
            cmd,
            cwd=str(ANDROID_DIR),
            env=env,
            capture_output=True,
            text=True,
            timeout=300  # 5分钟超时
        )
        
        print("\n--- STDOUT ---")
        print(result.stdout[-5000:] if len(result.stdout) > 5000 else result.stdout)  # 只显示最后5000字符
        
        if result.stderr:
            print("\n--- STDERR ---")
            print(result.stderr[-2000:] if len(result.stderr) > 2000 else result.stderr)
        
        print(f"\n返回码: {result.returncode}")
        
        if result.returncode == 0:
            print("\n✅ 构建成功!")
            # 检查 APK 是否存在
            apk_path = ANDROID_DIR / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk"
            if apk_path.exists():
                size_mb = apk_path.stat().st_size / (1024 * 1024)
                print(f"✅ APK 已生成: {apk_path} ({size_mb:.1f} MB)")
                return 0
            else:
                print("❌ APK 文件未找到")
                return 1
        else:
            print("\n❌ 构建失败")
            return 1
            
    except subprocess.TimeoutExpired:
        print("❌ 构建超时 (5分钟)")
        return 1
    except Exception as e:
        print(f"❌ 构建异常: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(run_build())
