import subprocess
import os
import sys

os.chdir(r'd:\erp_system\android-app')

# Remove JAVA_HOME if it's invalid
if 'JAVA_HOME' in os.environ:
    del os.environ['JAVA_HOME']

cmd = [r'.\gradlew.bat', 'assembleDebug', '--stacktrace']

print("Starting build...")
result = subprocess.run(cmd, capture_output=True, text=True, timeout=600, env=os.environ)

output = f"STDOUT:\n{result.stdout}\n\nSTDERR:\n{result.stderr}\n\nEXIT CODE: {result.returncode}\n"

with open(r'd:\erp_system\build_output.txt', 'w', encoding='utf-8') as f:
    f.write(output)

print(f"Build finished with exit code: {result.returncode}")
print("Output saved to d:\\erp_system\\build_output.txt")
print(f"Output length: {len(output)} chars")
