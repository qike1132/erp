import subprocess, os, sys
from pathlib import Path

os.environ["JAVA_HOME"] = r"D:\JDK\jdk-17.0.13+11"
os.environ["GRADLE_OPTS"] = "-Dorg.gradle.daemon=false"

result = subprocess.run(
    [r"d:\erp_system\android-app\gradlew.bat", "clean", ":app:assembleDebug"],
    cwd=r"d:\erp_system\android-app",
    capture_output=True, text=True, timeout=600
)

with open("d:/erp_system/gradle_out.txt", "w", encoding="utf-8") as f:
    f.write("STDOUT:\n" + result.stdout + "\n\nSTDERR:\n" + result.stderr + f"\n\nEXIT: {result.returncode}")

print(f"Exit code: {result.returncode}")
if result.returncode != 0:
    print("ERRORS:")
    for line in (result.stderr + "\n" + result.stdout).splitlines():
        if any(k in line.lower() for k in ["error:", "unresolved", "cannot", "nonexistent", "exception"]):
            print(line)
