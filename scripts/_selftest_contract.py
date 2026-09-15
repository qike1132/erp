"""契约快照自检：验证 --check 能真的抓出契约漂移。

在快照目录的**临时副本**上做篡改，绝不触碰真基线。
需要目标后端可达（默认 127.0.0.1:5002）；不可达时退出码 2 并说明。

语义说明（诊断时最容易搞反）：
  diff 的方向是 expected(快照) vs actual(服务端)。
  · 快照里有、服务端没有 → "字段消失" = **危险方向**（后端删了字段，前端会静默空白）
  · 快照里没有、服务端有 → "新增字段" = 通常是加字段（也报，提醒确认）
  所以"模拟后端删字段"的办法是：往快照里**加**一个键。

用法：python scripts/_selftest_contract.py [--base-url URL]
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONTRACT_DIR = ROOT / "tests" / "contract"
SNAPSHOT_DIR = CONTRACT_DIR / "snapshots"
TARGET = "products_list"  # 结构最稳定的一个，用来做篡改样本
PRICE_KEY = "items[].price:float"


def run_check(snapshot_dir: Path, base_url: str) -> tuple[int, dict]:
    proc = subprocess.run(
        [
            sys.executable, "scripts/contract_snapshot.py", "--check", "--json",
            "--base-url", base_url, "--snapshot-dir", str(snapshot_dir),
        ],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    try:
        return proc.returncode, json.loads(proc.stdout)
    except ValueError:
        return proc.returncode, {"results": [], "_raw": (proc.stdout or proc.stderr)[:400]}


def result_of(report: dict, name: str = TARGET) -> tuple[str, list[str]]:
    for item in report.get("results", []):
        if item.get("name") == name:
            return item.get("status", "?"), item.get("diffs", [])
    return "absent", []


class Harness:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url
        # 放系统临时目录，不要放进仓库 —— 否则一旦清理失败就会残留在 tests/contract/ 里
        # 被 git 当成未跟踪文件（已踩过：留下 3 个 contract_selftest_* 目录）
        self.tmp = Path(tempfile.mkdtemp(prefix="erp_contract_selftest_"))

    def reset(self) -> Path:
        """每个用例前把副本恢复成基线原样，避免篡改在用例间累积。"""
        shutil.rmtree(self.tmp, ignore_errors=True)
        shutil.copytree(SNAPSHOT_DIR, self.tmp, dirs_exist_ok=True)
        return self.tmp

    def tamper(self, mutate: Callable[[dict], None]) -> None:
        path = self.tmp / f"{TARGET}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        mutate(data)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def close(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:5002")
    args = parser.parse_args()

    if not SNAPSHOT_DIR.exists() or not any(SNAPSHOT_DIR.glob("*.json")):
        print(f"[SKIP] 尚无快照，请先执行 --record（{SNAPSHOT_DIR}）")
        return 2

    h = Harness(args.base_url)
    results: list[tuple[str, bool, str]] = []
    try:
        # 0) 基线自洽：未篡改必须完全一致
        rc, report = run_check(h.reset(), args.base_url)
        status, _ = result_of(report)
        if rc == 2:
            print(f"[ERROR] 后端不可达或鉴权失败，自检无法进行：{report.get('_raw', '')}")
            return 2
        results.append(("未篡改 → 一致", rc == 0 and status == "match", f"exit={rc} status={status}"))

        # 1) 服务端删字段（危险方向）：快照里加键 → 期望"字段消失"
        h.reset()
        h.tamper(lambda d: d.__setitem__("shape", sorted(d["shape"] + ["items[].ghost_field:str"])))
        rc, report = run_check(h.tmp, args.base_url)
        _, diffs = result_of(report)
        hit = rc == 1 and any("字段消失" in x and "ghost_field" in x for x in diffs)
        results.append(("服务端删字段 → drift", hit, f"exit={rc} {diffs[:1]}"))

        # 2) 服务端新增字段：快照里删键 → 期望"新增字段"
        h.reset()
        h.tamper(lambda d: d.__setitem__("shape", [s for s in d["shape"] if s != PRICE_KEY]))
        rc, report = run_check(h.tmp, args.base_url)
        _, diffs = result_of(report)
        hit = rc == 1 and any("新增字段" in x and "price" in x for x in diffs)
        results.append(("服务端新增字段 → drift", hit, f"exit={rc} {diffs[:1]}"))

        # 3) 类型变化
        h.reset()
        h.tamper(lambda d: d.__setitem__("shape", [s.replace(PRICE_KEY, "items[].price:str") for s in d["shape"]]))
        rc, report = run_check(h.tmp, args.base_url)
        _, diffs = result_of(report)
        hit = rc == 1 and any("类型变化" in x and "price" in x for x in diffs)
        results.append(("类型变化 → drift", hit, f"exit={rc} {diffs[:1]}"))

        # 4) 状态码变化
        h.reset()
        h.tamper(lambda d: d.__setitem__("http_status", 500))
        rc, report = run_check(h.tmp, args.base_url)
        _, diffs = result_of(report)
        hit = rc == 1 and any("状态码" in x for x in diffs)
        results.append(("状态码变化 → drift", hit, f"exit={rc} {diffs[:1]}"))

        # 5) 空数组容差：把 items 整体压成空数组形态，不得因数据波动误报
        h.reset()
        h.tamper(lambda d: d.__setitem__(
            "shape", ["items:array[0]" if s.startswith("items[]") else s for s in d["shape"]]))
        rc, report = run_check(h.tmp, args.base_url)
        _, diffs = result_of(report)
        tolerated = rc == 0 and all("items[]." not in x for x in diffs)
        results.append(("空数组容差 → 不误报", tolerated, f"exit={rc}"))
    finally:
        h.close()

    print("契约快照自检结果")
    print("-" * 74)
    ok = True
    for name, passed, detail in results:
        print(f"  {'PASS' if passed else 'FAIL'}  {name:<24} {detail}")
        ok = ok and passed
    print("-" * 74)
    print("[PASS] 全部通过" if ok else "[FAIL] 存在未通过项")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
