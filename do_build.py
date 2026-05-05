import os
import subprocess
import sys
import glob

# Find java.exe
java_paths = [
    r"C:\Program Files\Android\Android Studio\jbr\bin\java.exe",
    r"C:\Program Files\Android\Android Studio\jre\bin\java.exe",
    r"C:\Users\Administrator\AppData\Local\Android\Sdk\jbr\bin\java.exe",
    r"C:\Users\Administrator\AppData\Local\Android\Sdk\jre\bin\java.exe",
]

java_exe = None
for p in java_paths:
    if os.path.exists(p):
        java_exe = p
        jbr = os.path.dirname(p)
        print(f"Found java.exe at: {jbr}")
        break

if not java_exe:
    # Search more broadly
    for base in [r"C:\Program Files\Android", r"C:\Users\Administrator\AppData\Local\Android"]:
        if os.path.exists(base):
            for root, dirs, files in os.walk(base):
                if "java.exe" in files:
                    java_exe = os.path.join(root, "java.exe")
                    jbr = os.path.dirname(root) if os.path.basename(root) == "bin" else root
                    print(f"Found java.exe at: {java_exe}")
                    break
            if java_exe:
                break

if not java_exe:
    print("ERROR: No java.exe found!")
    sys.exit(1)

jbr_path = os.path.dirname(java_exe)
os.environ['JAVA_HOME'] = jbr_path
os.environ['PATH'] = jbr_path + os.pathsep + os.environ['PATH']

print(f"JAVA_HOME set to: {jbr_path}")

os.chdir(r'd:\erp_system\android-app')

# Build
cmd = [r'.\gradlew.bat', 'assembleDebug']
print(f"Running: {' '.join(cmd)}")

result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)

output_file = r'd:\erp_system\build_result.txt'
with open(output_file, 'w', encoding='utf-8') as f:
    f.write(f"JAVA_HOME: {jbr_path}\n")
    f.write(f"EXIT CODE: {result.returncode}\n\n")
    f.write("STDOUT:\n")
    f.write(result.stdout)
    f.write("\n\nSTDERR:\n")
    f.write(result.stderr)

print(f"Build exit code: {result.returncode}")
print(f"Output saved to: {output_file}")

# Check for APK
apk_pattern = r'd:\erp_system\android-app\app\build\outputs\apk\debug\*.apk'
apks = glob.glob(apk_pattern)
if apks:
    for apk in apks:
        size = os.path.getsize(apk) / 1024 / 1024
        print(f"APK found: {apk} ({size:.1f} MB)")
else:
    print("No APK found")
