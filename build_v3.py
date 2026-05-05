import os
import subprocess
import sys

# Clear JAVA_HOME and use correct JBR path
env = os.environ.copy()

# Remove old JAVA_HOME
if 'JAVA_HOME' in env:
    print(f"Removing old JAVA_HOME: {env['JAVA_HOME']}")
    del env['JAVA_HOME']

# Set correct JBR from Android SDK
jbr_path = r"C:\Users\Administrator\AppData\Local\Android\Sdk\jbr"
env['JAVA_HOME'] = jbr_path
print(f"Setting JAVA_HOME: {jbr_path}")

os.chdir(r'd:\erp_system\android-app')

# Step 1: Stop gradle daemon
print("\n=== Step 1: Stopping Gradle daemon ===")
try:
    result = subprocess.run([r'.\gradlew.bat', '--stop'], capture_output=True, text=True, timeout=60, env=env)
    print(f"Stop result: {result.returncode}")
except Exception as e:
    print(f"Stop error: {e}")

# Step 2: Clean build
print("\n=== Step 2: Cleaning ===")
try:
    result = subprocess.run([r'.\gradlew.bat', 'clean'], capture_output=True, text=True, timeout=120, env=env)
    print(f"Clean result: {result.returncode}")
except Exception as e:
    print(f"Clean error: {e}")

# Step 3: Build APK
print("\n=== Step 3: Building APK ===")
try:
    result = subprocess.run([r'.\gradlew.bat', 'assembleDebug', '--stacktrace'], capture_output=True, text=True, timeout=600, env=env)
    
    output = f"JAVA_HOME: {jbr_path}\n\n=== BUILD OUTPUT ===\n\nSTDOUT:\n{result.stdout}\n\nSTDERR:\n{result.stderr}\n\nEXIT CODE: {result.returncode}\n"
    
    with open(r'd:\erp_system\build_output.txt', 'w', encoding='utf-8') as f:
        f.write(output)
    
    print(f"\nBuild finished with exit code: {result.returncode}")
    print(f"Output saved to d:\\erp_system\\build_output.txt")
    
    # Check if APK was created
    apk_path = r"d:\erp_system\android-app\app\build\outputs\apk\debug\app-debug.apk"
    if os.path.exists(apk_path):
        size = os.path.getsize(apk_path)
        print(f"APK created: {apk_path} ({size / 1024 / 1024:.1f} MB)")
    else:
        print("APK NOT FOUND")
        
except Exception as e:
    print(f"Build error: {e}")
    with open(r'd:\erp_system\build_output.txt', 'w', encoding='utf-8') as f:
        f.write(f"Build error: {str(e)}")
