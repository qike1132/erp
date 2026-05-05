import os
import subprocess
import glob
import shutil

# Find Java
java_candidates = [
    r"C:\Program Files\Android\Android Studio\jbr\bin\java.exe",
    r"C:\Program Files\Android\Android Studio\jre\bin\java.exe",
]

java_exe = None
for p in java_candidates:
    if os.path.exists(p):
        java_exe = p
        break

if not java_exe:
    print("ERROR: Java not found!")
    exit(1)

jbr = os.path.dirname(java_exe)
print(f"JAVA: {jbr}")

env = os.environ.copy()
env['JAVA_HOME'] = jbr
env['ANDROID_HOME'] = r"C:\Users\Administrator\AppData\Local\Android\Sdk"

os.chdir(r"d:\erp_system\android-app")

print("=== BUILDING APK ===")
result = subprocess.run(
    [r".\gradlew.bat", "clean", "assembleDebug", "--no-daemon", "--stacktrace"],
    capture_output=True, text=True, timeout=600, env=env
)

print(f"EXIT: {result.returncode}")

with open(r"d:\erp_system\apk_build_log.txt", "w", encoding="utf-8") as f:
    f.write(f"EXIT: {result.returncode}\n\nSTDOUT:\n{result.stdout}\n\nSTDERR:\n{result.stderr}")

apk = r"d:\erp_system\android-app\app\build\outputs\apk\debug\app-debug.apk"
if os.path.exists(apk):
    mb = os.path.getsize(apk) / 1024 / 1024
    print(f"SUCCESS: APK at {apk} ({mb:.1f} MB)")
    # Copy to releases
    shutil.copy2(apk, r"d:\erp_system\static\releases\erp-v1.2.apk")
    print("Copied to releases")
else:
    print("FAILED: No APK")
