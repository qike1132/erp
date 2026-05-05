import os
import subprocess
import sys

# Find the correct JBR
jbr_candidates = [
    r"C:\Users\Administrator\AppData\Local\Android\Sdk\jbr",
    r"C:\Users\Administrator\AppData\Local\Android\Sdk\jre",
    r"C:\Program Files\Android\Android Studio\jbr",
    r"C:\Program Files\Android\Android Studio\jre",
]

jbr_path = None
for candidate in jbr_candidates:
    java_exe = os.path.join(candidate, "bin", "java.exe")
    if os.path.exists(java_exe):
        jbr_path = candidate
        print(f"Found Java at: {jbr_path}")
        break

if not jbr_path:
    print("No Java found!")
    # Try to find java.exe in Android SDK
    import glob
    for pattern in [
        r"C:\Users\Administrator\AppData\Local\Android\Sdk\**\bin\java.exe",
        r"C:\Program Files\Android\Android Studio\**\bin\java.exe",
    ]:
        matches = glob.glob(pattern, recursive=True)
        if matches:
            jbr_path = os.path.dirname(os.path.dirname(matches[0]))
            print(f"Found Java at: {jbr_path}")
            break

if not jbr_path:
    print("FATAL: Cannot find Java installation")
    sys.exit(1)

# Set environment
env = os.environ.copy()
env['JAVA_HOME'] = jbr_path
env['PATH'] = os.path.join(jbr_path, 'bin') + os.pathsep + env['PATH']

print(f"Using JAVA_HOME: {env['JAVA_HOME']}")

os.chdir(r'd:\erp_system\android-app')

# Stop daemon first
print("\n=== Stopping Gradle daemon ===")
result = subprocess.run([r'.\gradlew.bat', '--stop'], capture_output=True, text=True, timeout=60, env=env)
print(f"Stop output: {result.stdout[:200]}")

# Build
print("\n=== Building APK ===")
result = subprocess.run([r'.\gradlew.bat', 'clean', 'assembleDebug'], capture_output=True, text=True, timeout=600, env=env)

output = f"JAVA_HOME: {jbr_path}\n\nSTDOUT:\n{result.stdout}\n\nSTDERR:\n{result.stderr}\n\nEXIT CODE: {result.returncode}\n"

with open(r'd:\erp_system\build_output.txt', 'w', encoding='utf-8') as f:
    f.write(output)

print(f"\nBuild finished: exit code {result.returncode}")
print(f"Output length: {len(output)} chars")
print(f"Saved to: d:\\erp_system\\build_output.txt")

# Check APK
apk_path = r"d:\erp_system\android-app\app\build\outputs\apk\debug\app-debug.apk"
if os.path.exists(apk_path):
    size_mb = os.path.getsize(apk_path) / 1024 / 1024
    print(f"✓ APK exists: {apk_path} ({size_mb:.1f} MB)")
else:
    print(f"✗ APK NOT found at {apk_path}")
