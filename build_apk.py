import subprocess
import os
import sys

os.environ['JAVA_HOME'] = r'C:\Program Files\Android\Android Studio\jbr'
os.chdir(r'd:\erp_system\android-app')

cmd = [r'.\gradlew.bat', 'assembleDebug', '--stacktrace']

print("Starting build...")
result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)

output = f"STDOUT:\n{result.stdout}\n\nSTDERR:\n{result.stderr}\n\nEXIT CODE: {result.returncode}\n"

with open(r'd:\erp_system\build_output.txt', 'w', encoding='utf-8') as f:
    f.write(output)

print(f"Build finished with exit code: {result.returncode}")
print("Output saved to d:\\erp_system\\build_output.txt")
print(f"Output length: {len(output)} chars")
