# 归档元信息（docs-archivist 于 2026-10-01 添加，以下 1 行注释 + 空行为归档者附加）
# 用途：复算 05 号报告 §1.3 的「52 条无权限点路由」与「11 条既无权限点也无认证依赖」（t9 修复 T8-1）
# 配套：先运行 routes3.py 与 routes4.py 生成 JSON；本脚本只读这两个 JSON，不写任何文件、不连库、不启动服务
# 关键口径：routes3.py 的 file 用反斜杠（os.path.relpath），routes4.py 的 endpoint_include.file 用正斜杠
#           （归档副本 routes4.py:98 的 rel 来自 :34 的 .replace(chr(92),"/")）——两者必须先归一化，
#           否则挂载层 deps 全部丢失，52 集内的「无认证依赖」会从 12 误算成 31
# 输入：C:\Users\Administrator\AppData\Local\Temp\erp_audit_v2\routes3.json / routes4.json
# 运行：python docs/audit-round2/scripts/normalize_deps.py   （建议 PYTHONDONTWRITEBYTECODE=1）
# 复算口径见 docs/audit-round2/05-ops-security-observability.md §1.3
# 归档日期：2026-10-01

import json, os, sys

ROOT = r"D:\erp_system"
TMP = r"C:\Users\Administrator\AppData\Local\Temp\erp_audit_v2"
BS = chr(92)
AUTH_DEP = "get_current_user_id"      # 挂载层注入的登录依赖
OPTIONAL_USER = "_get_optional_user"   # fastapi_app/core/health.py:82 的用户识别依赖（非认证依赖）


def norm(p):
    return p.replace(BS, "/")


def load(name):
    path = os.path.join(TMP, name)
    if not os.path.exists(path):
        sys.exit("缺少 %s —— 请先运行 routes3.py / routes4.py" % path)
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def mount_deps(entry, sep):
    """挂载层 include_router(..., dependencies=[...]) 的 deps；sep 决定 key 是否归一化"""
    if not entry or not entry.get("include"):
        return []
    return list(entry["include"].get("deps") or [])


def deps_of(row, lookup):
    d = list(row.get("param_deps") or []) + list(row.get("decorator_deps") or []) + list(row.get("router_deps") or [])
    d += mount_deps(lookup.get(norm(row["file"])), "/")
    return d


def main():
    rows = load("routes3.json")
    r4 = load("routes4.json")
    inc_norm = {norm(e["file"]): e for e in r4["endpoint_include"]}
    inc_raw = {e["file"]: e for e in r4["endpoint_include"]}
    hits_norm = sum(1 for r in rows if norm(r["file"]) in inc_norm)
    hits_raw = sum(1 for r in rows if r["file"] in inc_raw)

    live = [r for r in rows if "error" not in r]
    non_test = [r for r in live if "tests" not in norm(r["file"]).split("/")]
    no_perm = [r for r in non_test if not any(x.startswith("require_") for x in deps_of(r, inc_norm))]
    no_auth = [r for r in no_perm if not any(x.startswith(AUTH_DEP) for x in deps_of(r, inc_norm))]
    optional = [r for r in no_auth if any(OPTIONAL_USER in x for x in deps_of(r, inc_norm))]
    final = [r for r in no_auth if r not in optional]

    print("source: routes3.json / routes4.json @ %s" % TMP)
    print("ROOT  =", ROOT, "(只读；不连库)")
    print("routes3 rows: %d | parse errors: %d | non-test: %d" % (len(rows), len(rows) - len(live), len(non_test)))
    print("endpoint_include key separator: normalized(/) hits=%d ; raw hits=%d  <- 未归一化则挂载层全丢" % (hits_norm, hits_raw))
    print("52 -> no-permission routes:", len(no_perm))
    print("12 -> no-permission AND no %s (mount layer merged, keys normalized): %d" % (AUTH_DEP, len(no_auth)))
    for r in sorted(no_auth, key=lambda r: (norm(r["file"]), r["line"])):
        print("      %-52s :%-4d %-9s %s" % (norm(r["file"]), r["line"], r["method"], r["path"]))
    print("     exclude %d route(s) with %s ->" % (len(optional), OPTIONAL_USER))
    for r in optional:
        print("      %-52s :%-4d %-9s %s" % (norm(r["file"]), r["line"], r["method"], r["path"]))
    print("11 -> RESULT:", len(final))
    for r in sorted(final, key=lambda r: (norm(r["file"]), r["line"])):
        print("      %-52s :%-4d %-9s %s" % (norm(r["file"]), r["line"], r["method"], r["path"]))
    print("对照（错误口径，仅供说明 t8 回归）:")
    print("     unnormalized keys, no %s = %d" % (AUTH_DEP, sum(1 for r in no_perm if not any(x.startswith(AUTH_DEP) for x in list(r.get("param_deps") or []) + list(r.get("decorator_deps") or []) + list(r.get("router_deps") or []) + mount_deps(inc_raw.get(r["file"]), BS)))))
    print("     unnormalized keys, wider (user|permission) = %d" % sum(1 for r in no_perm if not any(("user" in x) or ("permission" in x) for x in list(r.get("param_deps") or []) + list(r.get("decorator_deps") or []) + list(r.get("router_deps") or []))))
    print("     param defaults only (no decorator/router/mount) = %d" % sum(1 for r in no_perm if not any(x.startswith(AUTH_DEP) for x in (r.get("param_deps") or []))))
    print("     no Depends at all in 52 set = %d" % sum(1 for r in no_perm if not deps_of(r, inc_norm)))


if __name__ == "__main__":
    main()
