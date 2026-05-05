import subprocess

result = subprocess.run(
    ['cmd', '/c', 'dir /s /b "C:\\Users\\*\\java.exe" 2>nul | findstr /i "bin\\\\java.exe" | findstr /v "jre\\\\bin\\\\client"'],
    capture_output=True,
    text=True,
    timeout=30
)

print("STDOUT:", result.stdout)
print("STDERR:", result.stderr)
print("EXIT:", result.returncode)

# Save to file
with open(r'd:\erp_system\java_locations.txt', 'w') as f:
    f.write(result.stdout)
