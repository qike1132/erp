import os
import subprocess
import shutil

# Remove JAVA_HOME completely
env = {k: v for k, v in os.environ.items() if k != 'JAVA_HOME'}
env['JAVA_HOME'] = r'C:\Users\Administrator\AppData\Local\Android\Sdk\jbr'
env['PATH'] = env['JAVA_HOME'] + r'\bin' + os.pathsep + env.get('PATH', '')

os.chdir(r'd:\erp_system\android-app')

# Delete build output first
if os.path.exists(r'd:\erp_system\build_output.txt'):
    os.remove(r'd:\erp_system\build_output.txt')

# Build
print(f"JAVA_HOME={env['JAVA_HOME']}")
print("Running gradle...")

result = subprocess.run(
    [r'.\gradlew.bat', 'clean', 'assembleDebug'],
    capture_output=True, 
    text=True, 
    timeout=600,
    env=env,
    cwd=r'd:\erp_system\android-app'
)

output = f"JAVA_HOME: {env['JAVA_HOME']}\n\nSTDOUT:\n{result.stdout}\n\nSTDERR:\n{result.stderr}\n\nEXIT CODE: {result.returncode}\n"

with open(r'd:\erp_system\build_output.txt', 'w', encoding='utf-8') as f:
    f.write(output)

print(f"Exit code: {result.returncode}")
print(f"Output length: {len(output)}")

# Check APK
apk = r"d:\erp_system\android-app\app\build\outputs\apk\debug\app-debug.apk"
if os.path.exists(apk):
    print(f"APK exists: {os.path.getsize(apk)/1024/1024:.1f} MB")
else:
    print("APK not found")
