"""门禁自检：验证 quality_gate 与各 check_* 脚本的关键防御确实生效。

覆盖三类"假绿"（比报红更危险）：
  1. 新增违规必须被棘轮拦下（exit 1 + REGRESS）
  2. 显式传入单文件路径时必须真的扫描（不能静默 PASS）
  3. 语法错误的文件必须 WARN，不能被当作"无违规"

用法：python scripts/_selftest_gate.py
全部通过 exit 0，任一失败 exit 1。
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
PROBE = ROOT / "fastapi_app" / "_zz_gate_probe.py"
BAD = ROOT / "fastapi_app" / "_zz_broken_probe.py"
N1_PROBE = ROOT / "fastapi_app" / "_zz_n1_probe.py"

# N+1 检查器的语义探针：每段对应一条断言，见 _check_n_plus_one_semantics
N1_PROBE_SOURCE = (
    "async def real_n_plus_one(db, rows):\n"
    "    for r in rows:\n"
    "        await db.execute(1)\n"
    "\n"
    "async def query_in_iterable(db, rows):\n"
    "    for x in (await db.execute(1)).all():\n"
    "        pass\n"
    "\n"
    "async def justified_with_reason(db, rows):\n"
    "    for r in rows:\n"
    "        await db.execute(1)  # batch-loop: 有意逐行处理,非 N+1\n"
    "\n"
    "async def marker_without_reason(db, rows):\n"
    "    for r in rows:\n"
    "        await db.execute(1)  # batch-loop:\n"
    "\n"
    "async def after_loop(db, rows):\n"
    "    for r in rows:\n"
    "        pass\n"
    "    await db.execute(1)\n"
    "\n"
    "async def nested_loops(db, rows):\n"
    "    for a in rows:\n"
    "        for b in a:\n"
    "            await db.execute(1)\n"
)

# 90 行函数 + 无标注的裸 except → 应被 function_length 与 bare_except 同时命中
PROBE_SOURCE = (
    "async def probe_too_long():\n"
    + "".join(f"    x{i} = {i}\n" for i in range(90))
    + "    try:\n"
    + "        return x0\n"
    + "    except Exception:\n"
    + "        return None\n"
)
# 故意语法错误
BAD_SOURCE = "def broken(:\n    pass\n"


def run(*args: str) -> tuple[int, str, str]:
    proc = subprocess.run(
        [sys.executable, *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return proc.returncode, proc.stdout or "", proc.stderr or ""


def cleanup() -> None:
    PROBE.unlink(missing_ok=True)
    BAD.unlink(missing_ok=True)
    N1_PROBE.unlink(missing_ok=True)


def _check_n_plus_one_semantics() -> list[tuple[str, bool, str]]:
    """证明 N+1 检查器既有区分度、又不过度报。

    背景：2026-09-14 修了 `_visit_loop`（此前把循环的 iterable 表达式也当循环体），
    又新增了就地标注与函数级白名单。这三处改动都可能把检查器改废，必须逐条断言。
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location("n1_probe", ROOT / "scripts" / "check_n_plus_one.py")
    mod = importlib.util.module_from_spec(spec)
    # 必须先注册进 sys.modules：@dataclass 处理 cls.__module__ 时会回查 sys.modules
    sys.modules["n1_probe"] = mod
    spec.loader.exec_module(mod)

    N1_PROBE.write_text(N1_PROBE_SOURCE, encoding="utf-8")
    violations, err = mod.scan_file(N1_PROBE)
    if err is not None:
        return [("N+1 探针可解析", False, f"解析失败：{err}")]

    flagged = {v.function for v in violations}
    cases = [
        ("真 N+1 必须报", "real_n_plus_one" in flagged, f"flagged={sorted(flagged)}"),
        ("for...in iterable 的查询不得报", "query_in_iterable" not in flagged, ""),
        ("就地标注(带理由)不得报", "justified_with_reason" not in flagged, ""),
        ("空理由标注必须报", "marker_without_reason" in flagged, ""),
        ("循环外查询不得报", "after_loop" not in flagged, ""),
        ("嵌套循环必须报", "nested_loops" in flagged, ""),
    ]
    # 函数级白名单：只注销 real_n_plus_one，其余保持
    rel = str(N1_PROBE.relative_to(ROOT)).replace("\\", "/")
    wl = {f"{rel}::real_n_plus_one"}
    rest = [v for v in violations if not mod.is_whitelisted(v, wl)]
    cases.append(
        ("函数级白名单 file::func 生效",
         all(v.function != "real_n_plus_one" for v in rest) and any(v.function == "marker_without_reason" for v in rest),
         f"过滤后={sorted(v.function for v in rest)}")
    )
    # 僵尸键：豁免名单指向已删文件/已改名函数/越界行号时必须报错，而不是静默失效
    good_key = f"{rel}::real_n_plus_one"
    zombie_set = {
        good_key,
        f"{rel}::renamed_away",
        f"{rel}:99999",
        "fastapi_app/_zz_does_not_exist.py",
    }
    found = set(mod.find_zombie_keys(zombie_set, ROOT))
    cases.append(
        ("僵尸键必须报（改名函数/越界行号/已删文件）",
         found == {f"{rel}::renamed_away", f"{rel}:99999", "fastapi_app/_zz_does_not_exist.py"},
         f"实测={sorted(found)}")
    )
    cases.append(
        ("有效键不得误判为僵尸（含整文件豁免）",
         good_key not in found and f"{rel}::nested_loops" not in mod.find_zombie_keys({f"{rel}::nested_loops"}, ROOT),
         "")
    )
    return cases


def main() -> int:
    cleanup()
    results: list[tuple[str, bool, str]] = []

    # ---- 1. 棘轮能拦新增违规 ----
    try:
        compile(PROBE_SOURCE, str(PROBE), "exec")  # 先确保探针自身合法
    except SyntaxError as exc:
        print(f"[FAIL] 探针文件自身语法错误，自检无效：{exc}")
        cleanup()
        return 2
    PROBE.write_text(PROBE_SOURCE, encoding="utf-8")

    rc, out, _ = run("scripts/check_bare_except.py", str(PROBE.relative_to(ROOT)))
    results.append(("单文件扫描能看见违规", "[FAIL]" in out, f"exit={rc}"))

    rc, out, _ = run("scripts/quality_gate.py")
    results.append(("新增违规 → exit 1 且报 REGRESS", rc == 1 and "REGRESS" in out, f"exit={rc}"))

    PROBE.unlink(missing_ok=True)
    rc, out, _ = run("scripts/quality_gate.py")
    results.append(("清理后 → exit 0 且 PASS", rc == 0 and "[PASS]" in out, f"exit={rc}"))

    # ---- 2. 语法错误文件不能静默 PASS ----
    BAD.write_text(BAD_SOURCE, encoding="utf-8")
    for gate in ("check_bare_except.py", "check_function_length.py"):
        rc, out, err = run(f"scripts/{gate}", str(BAD.relative_to(ROOT)))
        warned = "解析失败" in err
        results.append((f"{gate} 对语法错误文件发出 WARN", warned, f"stderr 含 WARN={warned}"))

    # ---- 3. 路径写错不能静默 PASS ----
    for gate in ("check_bare_except.py", "check_function_length.py", "check_n_plus_one.py"):
        rc, out, err = run(f"scripts/{gate}", "definitely_missing_dir")
        results.append((f"{gate} 对无效路径发出 WARN", "WARN" in err, f"stderr 含 WARN={'WARN' in err}"))

    # ---- 4. N+1 检查器的语义（2026-09-14 改过 _visit_loop，必须证明没改废）----
    results.extend(_check_n_plus_one_semantics())

    cleanup()

    print("门禁自检结果")
    print("-" * 62)
    ok = True
    for name, passed, detail in results:
        print(f"  {'PASS' if passed else 'FAIL'}  {name:<40} {detail}")
        ok = ok and passed
    print("-" * 62)
    print("[PASS] 全部通过" if ok else "[FAIL] 存在未通过项")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
