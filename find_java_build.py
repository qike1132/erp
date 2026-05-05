import os
import subprocess

# Find Java installation
java_paths = [
    r"C:\Program Files\Android\Android Studio\jbr",
    r"C:\Program Files\Android\Android Studio\jre",
    r"C:\Program Files\Java\jdk-17",
    r"C:\Program Files\Java\jdk-11",
    r"C:\Program Files\Java\jdk1.8.0_291",
    r"C:\Users\Administrator\AppData\Local\Android\Sdk\jbr",
]

java_home = None
for path in java_paths:
    if os.path.exists(os.path.join(path, "bin", "java.exe")):
        java_home = path
        print(f"Found Java at: {path}")
        break

if not java_home:
    print("Java not found in expected locations")
    # List what exists
    for path in java_paths:
        exists = os.path.exists(path)
        print(f"  {path}: {'EXISTS' if exists else 'not found'}")
    exit(1)

os.environ['JAVA_HOME'] = java_home
os.chdir(r'd:\erp_system\android-app')

cmd = [r'.\gradlew.bat', 'assembleDebug', '--stacktrace']

print(f"Using JAVA_HOME={java_home}")
print("Starting build...")

result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)

output = f"STDOUT:\n{result.stdout}\n\nSTDERR:\n{result.stderr}\n\nEXIT CODE: {result.returncode}\n"

with open(r'd:\erp_system\build_output.txt', 'w', encoding='utf-8') as f:
    f.write(output)

print(f"Build finished with exit code: {result.returncode}")
print(f"Output length: {len(output)} chars")
