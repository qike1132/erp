# 归档元信息（docs-archivist 于 2026-10-01 添加，以下 1 行注释 + 空行为归档者附加）
# 来源：2026-10-01 第二轮审计 t5（安全/运维/可观测性）统计脚本，2026-10-01 15:08 前后取证时使用
# 原始路径：C:\Users\Administrator\AppData\Local\Temp\erp_audit_v2\routes4.py（99 行）
# 原始 SHA256：CB7BC413DF13E95AFAFF5AE5842907B43F669456B19DF6FD40BBDC433825E67E
# 依赖：Python 3（标准库 ast/json/os 即可）、硬编码 ROOT = r"D:\erp_system"、只做 AST 静态解析，不连库、不启动服务
# 遍历时跳过 .git / node_modules / __pycache__ / frontend-vite / backups / logs
# 输出：C:\Users\Administrator\AppData\Local\Temp\erp_audit_v2\routes4.json（endpoint_include 段给出每个端点文件在 v1/router.py 的 include_router 挂载项）
# 运行：python docs/audit-round2/scripts/routes4.py   （建议 PYTHONDONTWRITEBYTECODE=1 以免在仓库生成 __pycache__）
# 复算口径见 docs/audit-round2/05-ops-security-observability.md §1.3
# 归档日期：2026-10-01

import ast, json, os
ROOT = r"D:\erp_system"
OUT = os.path.join(r"C:\Users\Administrator\AppData\Local\Temp\erp_audit_v2","routes4.json")

def txt(n):
    try: return ast.unparse(n)
    except Exception: return "<?>"

def deps_from(node):
    out=[]
    for n in ast.walk(node):
        if isinstance(n,ast.Call):
            f=n.func; nm=f.id if isinstance(f,ast.Name) else (f.attr if isinstance(f,ast.Attribute) else "")
            if nm=="Depends":
                out.append(txt(n.args[0]) if n.args else "<no-arg>")
    return out

files={}
for dp,_,fs in os.walk(ROOT):
    if any(p in dp for p in (".git","node_modules","__pycache__","frontend-vite","backups","logs")): continue
    for fn in fs:
        if fn.endswith(".py"):
            p=os.path.join(dp,fn); files[os.path.relpath(p,ROOT).replace("\\","/")]=p

# global symbol table: module -> {alias: imported_module}
imports={}
router_of={}
includes={}
for rel,p in files.items():
    try: tree=ast.parse(open(p,encoding="utf-8").read())
    except Exception: continue
    im={}
    for n in ast.walk(tree):
        if isinstance(n,ast.ImportFrom) and n.module:
            for a in n.names: im[a.asname or a.name]=n.module
        if isinstance(n,ast.Assign):
            for t in n.targets:
                if isinstance(t,ast.Name) and isinstance(n.value,ast.Call):
                    f=n.value.func; nm=f.id if isinstance(f,ast.Name) else (f.attr if isinstance(f,ast.Attribute) else "")
                    if nm=="APIRouter":
                        d=[]
                        for kw in n.value.keywords:
                            if kw.arg=="dependencies": d+=deps_from(kw.value)
                        router_of[rel+ "::" + t.id]=d
    imports[rel]=im
    incs=[]
    for n in ast.walk(tree):
        if isinstance(n,ast.Call):
            f=n.func; nm=f.id if isinstance(f,ast.Name) else (f.attr if isinstance(f,ast.Attribute) else "")
            if nm=="include_router":
                tgt=txt(n.args[0]) if n.args else "?"
                pre=""; deps=[]
                for kw in n.keywords:
                    if kw.arg=="prefix": pre=ast.literal_eval(kw.value) if isinstance(kw.value,ast.Constant) else txt(kw.value)
                    if kw.arg=="dependencies": deps+=deps_from(kw.value)
                incs.append({"line":n.lineno,"target":tgt,"prefix":pre,"deps":deps})
    includes[rel]=incs

def resolve_deps(rel, alias, seen=None):
    """deps that apply to alias (a router object) when it is included into rel's parent chain"""
    seen=seen or set()
    key=(rel,alias)
    if key in seen: return []
    seen.add(key)
    mod=imports.get(rel,{}).get(alias)
    if not mod: return []
    cands=[k for k in files if k.endswith("/".join(mod.split(".")) + ".py") or k=="fastapi_app/"+ "/".join(mod.split(".")[1:])+".py"]
    # direct file
    fkey=mod.replace(".","/")+".py"
    if fkey not in files:
        fkey2=mod.replace(".","/")+"/__init__.py"
        fkey = fkey2 if fkey2 in files else None
    if not fkey: return []
    d=[]
    for inc in includes.get(fkey,[]):
        if inc["target"].split(".")[-1]==alias or inc["target"]==alias:
            d+=inc["deps"]+resolve_deps(fkey, inc["target"], seen)
    return d

# per endpoint file: which alias is registered in v1/router.py?
vr="fastapi_app/api/v1/router.py"
api_deps=[]
if vr in files:
    for inc in includes[vr]:
        api_deps.append(inc)
out=[]
for rel,p in files.items():
    if not rel.startswith("fastapi_app/api/v1/endpoints/") and rel!="fastapi_app/core/health.py" and rel!="fastapi_app/api/ws.py":
        continue
    d=None
    for inc in includes.get(vr,[]):
        tgt=inc["target"]
        mod=imports.get(vr,{}).get(tgt,'')
        if mod and rel.startswith(mod.replace(".","/")): d=inc; break
    out.append({"file":rel,"include":d})
json.dump({"routers":router_of,"includes":{k:v for k,v in includes.items() if v},"endpoint_include":out}, open(OUT,"w",encoding="utf-8"), ensure_ascii=False, indent=0)
print("routers:",len(router_of),"files with includes:",sum(1 for v in includes.values() if v))
for e in out[:5]: print(e)
