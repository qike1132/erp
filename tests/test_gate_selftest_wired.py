"""门禁自检「必须真有人跑」的棘轮（2026-10-17 审计 TEST 区 / 批次 8）。

`scripts/_selftest_gate.py` 是跨门禁的语义自检：N+1 判定不退化（真 N+1 必报、
`for ... in iterable` 的查询不得报、就地标注必须带理由、白名单 `file::func` 生效、
僵尸键必报）、子进程中文 stderr 必须按 UTF-8 读回、语法错误文件与无效路径必须发
WARN 而不是静默 PASS。

问题在于它长期**没有任何调用方**：CI 不跑它，`quality_gate.py` 也不能递归自调
（自检里要跑 quality_gate，自调即死循环），此前只有一个测 stderr 编码的用例 import
了它的两个函数。于是 18 项自检里绝大部分从未被任何流水线执行过 —— 「防线没人跑」
和「没有防线」是同一个结果。

本用例把「CI 必须有一条 `run:` 真的执行它」写成机器判定。2026-11-18 评审收紧了三处
（原来的写法都能被绕过）：
* 只在注释里提到脚本名不算调用方 → 先去掉整行 YAML 注释；
* 写在 `name:` 里、或被 `if: false` / `continue-on-error` 包裹也不算 → 只认
  `run: python scripts/_selftest_gate.py` 这一行，并检查该 step 没有被静默放行；
* `quality_gate.py` 的「不得自调」原来做整文件子串搜索，写一句「不要调用
  `_selftest_gate.py`」的注释反而会判违规 → 改成只看调用面（import/subprocess/run 同句）。
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SELFTEST = REPO / "scripts" / "_selftest_gate.py"
GATE = REPO / "scripts" / "quality_gate.py"
CI = REPO / ".github" / "workflows" / "ci-cd.yml"

#: 真的执行自检的那一行（允许 `python` 前有 `&`/引号之类的空白差异）。
RUN_LINE = re.compile(r"^\s*run:\s*(?:&\s*)?['\"]?python['\"]?\s+scripts/_selftest_gate\.py\s*$", re.MULTILINE)

#: 自检里不可静默丢失的语义面（每条都对应一次真实事故/评审结论）。
REQUIRED_DEFS = ("def _check_n_plus_one_semantics(",)
REQUIRED_CALLS = (
    "find_zombie_keys(",   # 改名函数 / 越界行号 / 已删文件必须报
    "PYTHONIOENCODING",    # 子进程 stderr 按 utf-8 读回（否则中文断言恒红）
)
#: `_check_n_plus_one_semantics` 里逐条断言标签（真 N+1/iterable/带理由/空理由/循环外/
#: 嵌套 + 白名单 + 僵尸键 + 有效键）。删掉任一条分支都会带走对应标签。
REQUIRED_CASES = (
    'N+1 探针可解析',
    '真 N+1 必须报',
    'for...in iterable 的查询不得报',
    '就地标注(带理由)不得报',
    '空理由标注必须报',
    '循环外查询不得报',
    '嵌套循环必须报',
    '函数级白名单 file::func 生效',
    '僵尸键必须报（改名函数/越界行号/已删文件）',
    '有效键不得误判为僵尸（含整文件豁免）',
)


def _non_comment_lines(text: str) -> str:
    """去掉整行 YAML 注释：只在注释里提到脚本名不算「有调用方」。"""
    return "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    )


def test_selftest_gate_script_exists() -> None:
    assert SELFTEST.is_file(), f"跨门禁自检脚本不见了：{SELFTEST}"


def test_selftest_gate_is_executed_by_a_ci_run_step() -> None:
    ci = _non_comment_lines(CI.read_text(encoding="utf-8"))
    match = RUN_LINE.search(ci)
    assert match is not None, (
        "CI 里没有任何 `run:` 真的执行 scripts/_selftest_gate.py —— 它的 18 项自检"
        "就等于不存在（写在注释或 name: 里都不算）"
    )

    # 该 step 不得被静默放行：紧邻的几行里出现 if:/continue-on-error 视为未执行。
    tail = ci[match.end():].splitlines()[:3]
    banned = [line.strip() for line in tail if re.search(r"^(if:|continue-on-error:)", line.strip())]
    assert banned == [], f"执行自检的 CI step 被条件/放行包裹，等于没跑：{banned}"


def test_selftest_gate_is_not_called_by_quality_gate() -> None:
    """quality_gate 不得调用自检：自检内部要跑 quality_gate，自调即死循环。"""
    gate = GATE.read_text(encoding="utf-8")
    # 只看调用面：注释里写「不要调用 _selftest_gate.py」不该判违规
    offenders = [
        line for line in gate.splitlines()
        if "_selftest_gate" in line
        and re.search(r"\b(import|from|run|subprocess|check_output|Popen)\b", line)
    ]
    assert offenders == [], (
        f"quality_gate.py 不得调用 _selftest_gate.py（自检内部会跑 quality_gate，会死循环）：{offenders}"
    )


def test_selftest_gate_still_covers_critical_semantics() -> None:
    src = SELFTEST.read_text(encoding="utf-8")
    missing = [name for name in (*REQUIRED_DEFS, *REQUIRED_CALLS) if name not in src]
    assert missing == [], (
        f"自检丢失了这些语义面（别当清理死代码删掉，它们是防线本身）：{missing}"
    )
    # 逐条断言「判定分支还在」。不能只数字符串出现次数：N+1 的 6 条在 cases 列表字面量里、
    # 3 条在 cases.append 里，`cases.append(` 只数到后 3 条（2026-11-18 评审实测踩到）。
    # 删掉任何一条分支都会带走它的断言标签 → 当场红。
    lost = [label for label in REQUIRED_CASES if f'"{label}"' not in src]
    assert lost == [], (
        f"N+1 判定自检丢了这些分支（判定退化 = 防线失效，不是可清理的死代码）：{lost}"
    )
