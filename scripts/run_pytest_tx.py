import subprocess
import sys

cmd = [
    sys.executable, "-m", "pytest",
    "fastapi_app/tests/test_auth.py",
    "fastapi_app/tests/test_customer.py",
    "-v",
]
result = subprocess.run(cmd, capture_output=True, text=True, cwd="d:/erp_system")
out_path = "d:/erp_system/scripts/pytest_tx.out"
with open(out_path, "w", encoding="utf-8") as f:
    f.write("STDOUT:\n")
    f.write(result.stdout)
    f.write("\n\nSTDERR:\n")
    f.write(result.stderr)
    f.write(f"\n\nRETURN CODE: {result.returncode}\n")
print(f"output written to {out_path}, rc={result.returncode}")
