import os
import subprocess
import sys

os.chdir(r'd:\erp_system')
result = subprocess.run([sys.executable, 'test_production_ready.py'], capture_output=True, text=True, timeout=120)
print("STDOUT:", result.stdout[-500:] if len(result.stdout) > 500 else result.stdout)
print("STDERR:", result.stderr[:200] if result.stderr else "")
print("EXIT_CODE:", result.returncode)
