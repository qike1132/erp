import ast
from pathlib import Path

path = Path("d:/erp_system/fastapi_app/api/v1/endpoints/auth.py")
source = path.read_text(encoding="utf-8")
tree = ast.parse(source, filename=str(path))

out = []
for node in ast.walk(tree):
    if isinstance(node, ast.AsyncFunctionDef):
        out.append(f"FUNC: {node.name}")
        for deco in node.decorator_list:
            out.append(f"  DECO type={type(deco).__name__}: {ast.dump(deco, include_attributes=False)[:200]}")
Path("d:/erp_system/scripts/debug_ast.out").write_text("\n".join(out), encoding="utf-8")
