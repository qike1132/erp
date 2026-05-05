import os
import subprocess

os.chdir(r'd:\erp_system\android-app')

cmd = [r'.\gradlew.bat', 'clean', 'assembleDebug', '--stacktrace']

print("Starting build...")
result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)

output = f"STDOUT:\n{result.stdout}\n\nSTDERR:\n{result.stderr}\n\nEXIT CODE: {result.returncode}\n"

with open(r'd:\erp_system\build_output.txt', 'w', encoding='utf-8') as f:
    f.write(output)

print(f"Build finished with exit code: {result.returncode}")
print(f"Output length: {len(output)} chars")

# Check APK
apk_path = r"d:\erp_system\android-app\app\build\outputs\apk\debug\app-debug.apk"
if os.path.exists(apk_path):
    size_mb = os.path.getsize(apk_path) / 1024 / 1024
    print(f"APK exists: {size_mb:.1f} MB")
else:
    print("APK NOT found")
