import os
import subprocess
import shutil

# Clear JAVA_HOME from environment
env = os.environ.copy()
if 'JAVA_HOME' in env:
    del env['JAVA_HOME']

# Use Android SDK's bundled JBR
jbr_path = r"C:\Users\Administrator\AppData\Local\Android\Sdk\jbr"
if os.path.exists(os.path.join(jbr_path, "bin", "java.exe")):
    env['JAVA_HOME'] = jbr_path
    print(f"Using JBR: {jbr_path}")
else:
    print("JBR not found at SDK location, searching...")
    for root, dirs, files in os.walk(r"C:\Users\Administrator\AppData\Local\Android"):
        if "java.exe" in files and "bin" in root:
            jbr_path = root.replace("\\bin", "")
            env['JAVA_HOME'] = jbr_path
            print(f"Found JBR: {jbr_path}")
            break

os.chdir(r'd:\erp_system\android-app')

cmd = [r'.\gradlew.bat', 'assembleDebug', '--stacktrace']

print(f"JAVA_HOME={env.get('JAVA_HOME', 'NOT SET')}")
print("Starting build...")

result = subprocess.run(cmd, capture_output=True, text=True, timeout=600, env=env)

output = f"JAVA_HOME: {env.get('JAVA_HOME', 'NOT SET')}\n\nSTDOUT:\n{result.stdout}\n\nSTDERR:\n{result.stderr}\n\nEXIT CODE: {result.returncode}\n"

with open(r'd:\erp_system\build_output.txt', 'w', encoding='utf-8') as f:
    f.write(output)

print(f"Build finished with exit code: {result.returncode}")
print(f"Output length: {len(output)} chars")
