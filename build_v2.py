import os
import subprocess
import sys

# Clear JAVA_HOME from environment
env = os.environ.copy()
old_java = env.get('JAVA_HOME', 'NOT SET')
if 'JAVA_HOME' in env:
    del env['JAVA_HOME']
    print(f"Removed JAVA_HOME: {old_java}")

# Use Android SDK's bundled JBR
jbr_path = r"C:\Users\Administrator\AppData\Local\Android\Sdk\jbr"
if os.path.exists(os.path.join(jbr_path, "bin", "java.exe")):
    env['JAVA_HOME'] = jbr_path
    print(f"Using JBR: {jbr_path}")
else:
    print("JBR not found at SDK location")
    # Try to find it
    import glob
    candidates = glob.glob(r"C:\Users\Administrator\AppData\Local\Android\Sdk\*\bin\java.exe")
    if candidates:
        jbr_path = os.path.dirname(os.path.dirname(candidates[0]))
        env['JAVA_HOME'] = jbr_path
        print(f"Found JBR at: {jbr_path}")
    else:
        print("No JBR found!")
        sys.exit(1)

os.chdir(r'd:\erp_system\android-app')

cmd = [r'.\gradlew.bat', 'assembleDebug']

print(f"JAVA_HOME={env.get('JAVA_HOME', 'NOT SET')}")
print("Starting build...")

try:
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600, env=env)
    output = f"JAVA_HOME: {env.get('JAVA_HOME', 'NOT SET')}\n\nSTDOUT:\n{result.stdout}\n\nSTDERR:\n{result.stderr}\n\nEXIT CODE: {result.returncode}\n"
    with open(r'd:\erp_system\build_output.txt', 'w', encoding='utf-8') as f:
        f.write(output)
    print(f"Build finished with exit code: {result.returncode}")
    print(f"Output length: {len(output)} chars")
except Exception as e:
    print(f"Error: {e}")
    with open(r'd:\erp_system\build_output.txt', 'w', encoding='utf-8') as f:
        f.write(f"Error: {e}")
