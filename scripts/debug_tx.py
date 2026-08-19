from pathlib import Path

from audit_tx_patterns import detect_mode, iter_handlers

path = Path("d:/erp_system/fastapi_app/api/v1/endpoints/auth.py")
source = path.read_text(encoding="utf-8")
lines = [
    f"source len: {len(source)}",
    f"mode: {detect_mode(source)}",
]
count = 0
for name, method, route in iter_handlers(path):
    lines.append(f"  {name} {method} {route}")
    count += 1
lines.append(f"count: {count}")
Path("d:/erp_system/scripts/debug_tx.out").write_text("\n".join(lines), encoding="utf-8")
