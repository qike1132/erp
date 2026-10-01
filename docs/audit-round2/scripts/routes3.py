# 归档元信息（docs-archivist 于 2026-10-01 添加，以下 1 行注释 + 空行为归档者附加）
# 来源：2026-10-01 第二轮审计 t5（安全/运维/可观测性）统计脚本，2026-10-01 15:08 前后取证时使用
# 原始路径：C:\Users\Administrator\AppData\Local\Temp\erp_audit_v2\routes3.py（71 行）
# 原始 SHA256：22B4E595B00C57BC464A3CE3C259D940FDB729E77997467C5EFC2B1A8454A22D
# 依赖：Python 3（标准库 ast/json/os/io 即可）、硬编码 ROOT = r"D:\erp_system"、只做 AST 静态解析，不连库、不启动服务
# 输出：C:\Users\Administrator\AppData\Local\Temp\erp_audit_v2\routes3.json（随本目录归档者只复算一次，不落仓库）
# 运行：python docs/audit-round2/scripts/routes3.py   （建议 PYTHONDONTWRITEBYTECODE=1 以免在仓库生成 __pycache__）
# 复算口径见 docs/audit-round2/05-ops-security-observability.md §1.3
# 归档日期：2026-10-01

import ast, json, os, io

ROOT = r"D:\erp_system"
OUT = os.path.join(r"C:\Users\Administrator\AppData\Local\Temp\erp_audit_v2", "routes3.json")
HTTP = {"get","post","put","delete","patch","head","options","api_route","websocket"}

def txt(node):
    try: return ast.unparse(node)
    except Exception: return "<?>"

def deps_from(node):
    """collect Depends(X) descriptions inside arbitrary expression"""
    out=[]
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            f=n.func; name=f.id if isinstance(f,ast.Name) else (f.attr if isinstance(f,ast.Attribute) else "")
            if name=="Depends":
                if n.args:
                    out.append(txt(n.args[0]))
                else:
                    out.append("<Depends-no-arg>")
    return out

rows=[]
for dirpath,_,files in os.walk(os.path.join(ROOT,"fastapi_app")):
    for fn in files:
        if not fn.endswith(".py"): continue
        p=os.path.join(dirpath,fn)
        try:
            src=open(p,encoding="utf-8").read()
            tree=ast.parse(src)
        except Exception as e:
            rows.append({"file":os.path.relpath(p,ROOT),"error":str(e)}); continue
        rel=os.path.relpath(p,ROOT)
        router_deps=[]
        for n in ast.walk(tree):
            if isinstance(n,ast.Assign) and isinstance(n.value,ast.Call):
                f=n.value.func; nm=f.id if isinstance(f,ast.Name) else (f.attr if isinstance(f,ast.Attribute) else "")
                if nm=="APIRouter":
                    for kw in n.value.keywords:
                        if kw.arg=="dependencies":
                            router_deps += deps_from(kw.value)
        for n in ast.walk(tree):
            if not isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)): continue
            for dec in n.decorator_list:
                if not isinstance(dec,ast.Call): continue
                f=dec.func; nm=f.id if isinstance(f,ast.Name) else (f.attr if isinstance(f,ast.Attribute) else "")
                if nm not in HTTP: continue
                path= txt(dec.args[0]) if dec.args else ""
                ddeps=[]
                for kw in dec.keywords:
                    if kw.arg=="dependencies": ddeps += deps_from(kw.value)
                for a in dec.args[1:]:
                    ddeps += deps_from(a)
                a=n.args
                allargs=list(a.posonlyargs)+list(a.args)+list(a.kwonlyargs)
                adefs=list(a.defaults)+[d for d in a.kw_defaults if d is not None]
                pdeps=[]
                anns=[]
                for i,arg in enumerate(allargs):
                    if arg.arg in ("self","cls"): continue
                    if arg.annotation is not None: anns.append(arg.arg+":"+txt(arg.annotation))
                    else: anns.append(arg.arg+":?")
                for d in adefs:
                    pdeps += deps_from(d)
                rows.append({"file":rel,"line":dec.lineno,"func":n.name,"method":nm.upper(),"path":path,
                             "param_deps":pdeps,"decorator_deps":ddeps,"router_deps":router_deps,"annotations":anns})
json.dump(rows, open(OUT,"w",encoding="utf-8"), ensure_ascii=False, indent=0)
print("routes:",len(rows))
print("with param deps:",sum(1 for r in rows if r.get("param_deps")))
