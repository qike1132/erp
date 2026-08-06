"""审计 v1 endpoints 事务控制模式，输出 CSV 清单。"""
import ast
import csv
import sys
from pathlib import Path

ENDPOINTS_DIR = Path("d:/erp_system/fastapi_app/api/v1/endpoints")


HTTP_METHODS = {"get", "post", "put", "delete", "patch", "head", "options", "api_route"}


def _extract_path_and_method(call: ast.Call):
    func_name = ""
    if isinstance(call.func, ast.Attribute):
        if call.func.attr in HTTP_METHODS:
            func_name = call.func.attr
    elif isinstance(call.func, ast.Name):
        if call.func.id in HTTP_METHODS:
            func_name = call.func.id
    if not func_name:
        return None, None

    methods_kw = None
    path_arg = None
    for kw in call.keywords:
        if kw.arg == "methods" and isinstance(kw.value, (ast.List, ast.Tuple)):
            methods_kw = kw.value
        elif kw.arg == "path":
            if isinstance(kw.value, ast.Constant):
                path_arg = kw.value.value
    if func_name == "api_route":
        method = ",".join(
            elt.value for elt in getattr(methods_kw, "elts", []) if isinstance(elt, ast.Constant)
        ).upper() or "ANY"
    else:
        method = func_name.upper()
    if path_arg is None and call.args:
        first = call.args[0]
        if isinstance(first, ast.Constant):
            path_arg = first.value
    return method, path_arg or ""


def iter_handlers(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if not isinstance(node, ast.AsyncFunctionDef):
            continue
        name = node.name
        method = path_method = ""
        # 查找 router.*(path=..., methods=...) 装饰器（支持嵌套装饰器如 @cache 包裹 router.get）
        for deco in node.decorator_list:
            call = None
            if isinstance(deco, ast.Call):
                call = deco
            elif isinstance(deco, ast.Attribute) and isinstance(deco.value, ast.Call):
                call = deco.value
            if not call or not isinstance(call.func, (ast.Attribute, ast.Name)):
                continue
            m, p = _extract_path_and_method(call)
            if m:
                method = m
                path_method = p
                break
        if method:
            yield name, method, path_method


def detect_mode(source: str) -> str:
    has_db_tx = "db_transaction" in source
    has_manual_commit = "await db.commit()" in source or "await db.rollback()" in source
    if has_db_tx and has_manual_commit:
        return "mixed"
    if has_db_tx:
        return "db_transaction"
    if has_manual_commit:
        return "manual_commit"
    return "read_only"


def main():
    out_path = Path("d:/erp_system/scripts/endpoint_tx_audit.csv")
    rows = []
    for path in sorted(ENDPOINTS_DIR.rglob("*.py")):
        rel = path.relative_to(ENDPOINTS_DIR).as_posix()
        source = path.read_text(encoding="utf-8")
        needs_integrity = "IntegrityError" in source
        for name, method, route_path in iter_handlers(path):
            mode = detect_mode(source)
            rows.append({
                "file": rel,
                "function": name,
                "method": method,
                "path": route_path,
                "tx_mode": mode,
                "needs_integrity_check": "yes" if needs_integrity else "no",
            })

    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["file", "function", "method", "path", "tx_mode", "needs_integrity_check"],
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)
    print(f"审计清单已写入 {out_path}，共 {len(rows)} 个端点")


if __name__ == "__main__":
    main()
