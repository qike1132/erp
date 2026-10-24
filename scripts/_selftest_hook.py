"""`.githooks/pre-commit` 第 2 层（密钥内容扫描）自测。

存在理由：改这个 hook 没有任何自动化验证 → 极易出「静默假绿」
（把规则改松了却没人发现）或「静默假红」（误报拦住正常提交）。

本文件用 Python 忠实镜像 shell 里的规则链，对一组边界用例断言分类，
并把**既有的、刻意保留的能力缺口**单列为 KNOWN_GAPS（显式告警，不伪装成覆盖）。

用法：
    python scripts/_selftest_hook.py          # 规则级用例（快）
    python scripts/_selftest_hook.py --e2e    # 额外跑真实 hook（慢，约数分钟）
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# --- 镜像 .githooks/pre-commit 的模式 -------------------------------------
# 注：`[A-Za-z]{0,3}` 对应 2026-09-24 起允许的 Python 字符串前缀（r""/b""/rb""）。
PWD_PATTERN = re.compile(
    r"([Pp][Aa][Ss][Ss][Ww][Oo][Rr][Dd]|[Pp][Aa][Ss][Ss][Ww][Dd]|[Ss][Ee][Cc][Rr][Ee][Tt]"
    r"|[Tt][Oo][Kk][Ee][Nn]|[Aa][Pp][Ii][_]?[Kk][Ee][Yy]|[Rr][Ee][Qq][Uu][Ii][Rr][Ee][Pp][Aa][Ss][Ss])"
    # 2026-10-24（P1）：关键词允许后缀（SECRET_KEY / API_KEY_ID 等），
    # 右值改为「非空白非引号」字符类 —— 原先写死 [A-Za-z0-9+/=_.:@!#%^&*-]，
    # 含 $ ? ~ ( ) { } | \ 的真口令（如 "Abc$123456789xyz"）整条漏判。
    r"[A-Za-z0-9_]*[ \t]*[:=][ \t]*[A-Za-z]{0,3}[\"']?[^ \t\"']{12,}"
)
SECRET_PATTERN = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----|-----BEGIN OPENSSH PRIVATE KEY-----"
    r"|AKIA[0-9A-Z]{16}|ASIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{36,}"
    r"|xox[baprs]-[A-Za-z0-9-]{10,}|sk-[A-Za-z0-9]{32,}|AIza[0-9A-Za-z_-]{35}"
    r"|-----BEGIN (RSA|EC|DSA|PGP) "
)
PLACEHOLDER = re.compile(
    r"(<[^>]+>|YOUR_|CHANGE_?ME|changeme|placeholder|example|xxxx|dummy|fake|testkey|your[-_])",
    re.IGNORECASE,
)
EXPRESSION = re.compile(
    r"[:=][ \t]*[A-Za-z0-9_.]*([\(\[]|[ \t]+(or|and)[ \t]+[A-Za-z0-9_.]*[\(\[]?)"
)
# ④ 2026-09-24 新增：.py 专属收窄 —— 匹配片段的右值必须带引号
PY_QUOTED_RHS = re.compile(r"[:=][ \t]*[A-Za-z]{0,3}[\"']")
# ⑤ 2026-10-24：右值是变量/插值/命令替换，而不是字面量。
#    $VAR / ${VAR} / $($cmd) / %VAR% / {{ expr }} / <占位> 都不是硬编码凭据。
#    实测误报：`PASSWORD="${POSTGRES_PASSWORD}"`、`PASSWORD = $PgSuperPassword`、
#    `Password = (Read-EnvFile ...)`、`PASSWORD="${REPL_PASSWORD:-$(openssl ...)}"`。
#    注意不能用「右值含 $ 就跳过」——`"Abc$123456789xyz"` 是真口令，只判首字符。
_VARIABLE_RHS = re.compile(r"[:=][ \t]*[A-Za-z]{0,3}[\"']?[\$%{<]")
# ⑥ 2026-10-24：关键词本身是**配置项名**而非凭据值。
#    实测误报：`PASSWORD_PREFIX = "erp:backup_task_pwd:`（Redis key 前缀）。
_CONFIG_NAME_KEYWORD = re.compile(
    r"^[A-Za-z0-9_]*(?:_PREFIX|_SUFFIX|_LEN|_MIN|_MAX|_FIELD|_HEADER|_POLICY"
    r"|_PATTERN|_REGEX|_HINT|_LABEL|_TITLE|_TYPE|_NAME)[ \t]*[:=]",
    re.IGNORECASE,
)
# ⑦ 2026-10-24：右值以非 ASCII 开头 = 中文说明文字，不是字面量凭据。
#    实测误报：`password_string: 测试/配置默认值，真实密码走环境变量`、
#    `password: 加密密码（请求头，H3：已移除`。只判首字符，`"密码Abc123456"`
#    这类以中文开头的真口令仍会被漏掉——属可接受取舍（本仓无此形态）。
_NON_ASCII_RHS = re.compile(r"[:=][ \t]*[A-Za-z]{0,3}[\"']?[^\x00-\x7f]")
# ⑧ 2026-10-24：shell 参数展开 `${VAR:?msg}` / `:-` / `:=` / `:+` 不是字面量。
#    实测误报：`init-replica.sh` 的
#    `: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD must be provided via environment}"`
#    被切成 `PASSWORD:?POSTGRES_PASSWORD` 而命中。
_SHELL_EXPANSION_RHS = re.compile(r"[:=][?:+\-]")
# ⑨ 2026-10-24：右值不含任何字母数字 = 装饰性分隔线/注释横幅，不是凭据。
#    实测误报：HTML 里的 `/* ===== 1. 设计令牌 Design Tokens ===== */`
#    被切成 `Tokens =====================` 而命中。
_ALNUM = re.compile(r"[A-Za-z0-9]")
_SEP_RE = re.compile(r"[:=]")


def password_rule_hits(line: str, is_py: bool) -> bool:
    """镜像 hook 第 2 层的口令赋值判定。

    关键：hook 用 `grep -o` 提取**匹配片段**后逐片段判定（不是整行）——
    否则 `access_token=access_token, token_type="bearer"` 这类行会因右侧另有
    带引号字面量而整行放行。此处同样按 finditer 逐匹配判定。
    """
    for m in PWD_PATTERN.finditer(line):
        seg = m.group(0)
        if PLACEHOLDER.search(seg):                 # ① 占位符
            continue
        if EXPRESSION.search(seg):                  # ② / ③ 表达式
            continue
        if _VARIABLE_RHS.search(seg):                # ⑤ 变量/插值
            continue
        if _CONFIG_NAME_KEYWORD.search(seg):         # ⑥ 配置项名（PASSWORD_PREFIX 等）
            continue
        if _NON_ASCII_RHS.search(seg):               # ⑦ 中文说明文字
            continue
        if _SHELL_EXPANSION_RHS.search(seg):         # ⑧ shell 参数展开
            continue
        _sep = _SEP_RE.search(seg)
        if _sep and not _ALNUM.search(seg[_sep.end():]):  # ⑨ 纯分隔线/横幅
            continue
        if is_py and not PY_QUOTED_RHS.search(seg):  # ④ .py 右值必须带引号
            continue
        return True
    return False


def secret_rule_hits(line: str) -> bool:
    return bool(SECRET_PATTERN.search(line))


# --- 必须正确分类的用例：(说明, 行内容, 是否 .py, 期望口令规则命中) ---------
CASES: list[tuple[str, str, bool, bool]] = [
    # ④ 的核心目标：纯引用不得命中（这三条正是 2026-09-24 拦提交的实测行）
    ("属性读取（auth.py 实测）", "    password = data.password", True, False),
    ("属性读取（auth.py 实测）", "    refresh_token = data.refresh_token", True, False),
    ("变量传参与带引号字面量同行（auth.py 实测）",
     'return success_response(access_token=access_token, token_type="bearer")  # noqa: S106', True, False),
    ("变量传参（restore.py 实测）", "        decrypt_password=decrypt_password,", True, False),
    ("函数调用右值", "    secret = load_secret()", True, False),
    ("or 合并表达式", "    token = a or b", True, False),
    # 真字面量必须命中（防「改松了」的静默假绿）
    ("真字面量（双引号）", '    password = "hunter2secret123"', True, True),
    ("真字面量（单引号）", "    api_key = 'abcdef1234567890'", True, True),
    ("r-string 字面量（前缀支持）", '    token = r"abcdef1234567890"', True, True),
    ("b-string 字面量（前缀支持）", '    secret = b"abcdef1234567890"', True, True),
    # 非 .py 不受 ④ 影响（.yml/.conf 里不带引号就是字面量）
    ("YAML 真值（不带引号）", "  POSTGRES_PASSWORD: erp_test_pass", False, True),
    ("YAML 带引号真值", '  DB_PASSWORD: "abcdef1234567890"', False, True),
    ("YAML 占位符", "  DB_PASSWORD: YOUR_PASSWORD_HERE", False, False),
    ("py 占位符", '    password = "<your-password>"', True, False),
    ("无凭据关键词的普通行", "    result = compute_total(rows)", True, False),
]

SECRET_CASES: list[tuple[str, str, bool]] = [
    ("PEM 私钥头", "-----BEGIN RSA PRIVATE KEY-----", True),
    ("AWS AKIA", "aws_key = AKIAIOSFODNN7EXAMPLE", True),
    ("GitHub token", "token = ghp_" + "a" * 36, True),
    ("OpenAI key", "k = sk-" + "a" * 32, True),
    ("普通注释", "# 这里只是说明，不含凭据", False),
]

# --- 既有能力缺口：**刻意保留**（hook 自述「高精度，宁可漏报」），此处显式记录 ---
KNOWN_GAPS: list[tuple[str, str, bool]] = [
    ("f-string 且字面量片段 <12 字符",
     '    password = f"prefix{var}suffix"', True),
    ("空格分隔的 conf（非 :/= 形式）",
     "requirepass abc123def456ghi", False),
]


def run_rule_cases() -> int:
    failures: list[str] = []
    for desc, line, is_py, expected in CASES:
        got = password_rule_hits(line, is_py)
        flag = "OK  " if got == expected else "FAIL"
        if got != expected:
            failures.append(f"口令规则: {desc} 期望={expected} 实际={got}  行={line!r}")
        print(f"  [{flag}] 口令规则 {desc:34s} 期望={expected!s:5s} 实际={got!s:5s}")
    for desc, line, expected in SECRET_CASES:
        got = secret_rule_hits(line)
        flag = "OK  " if got == expected else "FAIL"
        if got != expected:
            failures.append(f"密钥特征: {desc} 期望={expected} 实际={got}")
        print(f"  [{flag}] 密钥特征 {desc:34s} 期望={expected!s:5s} 实际={got!s:5s}")

    print("\n  --- 既有能力缺口（非本次引入，仅记录，不计失败）---")
    for desc, line, is_py in KNOWN_GAPS:
        got = password_rule_hits(line, is_py)
        print(f"  [gap ] {desc:34s} 实际命中={got!s:5s}  行={line!r}")

    if failures:
        print(f"\n[FAIL] {len(failures)} 个用例未通过：")
        for f in failures:
            print("   -", f)
        return 1
    print(f"\n[PASS] 全部 {len(CASES) + len(SECRET_CASES)} 个规则用例通过")
    return 0


def run_e2e() -> int:
    """直接跑真实 hook，断言它对**当前暂存集**放行。"""
    print("\n--- E2E：执行 .githooks/pre-commit（可能需数分钟）---")
    proc = subprocess.run(
        ["git", "hook", "run", "pre-commit"],
        cwd=str(PROJECT_ROOT), capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    print("\n".join(out.splitlines()[-15:]))
    if proc.returncode == 0:
        print("[PASS] hook 对当前暂存集放行（exit 0）")
        return 0
    print(f"[FAIL] hook 拒绝提交（exit {proc.returncode}）")
    return 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--e2e", action="store_true", help="额外执行真实 hook")
    args = ap.parse_args()
    rc = run_rule_cases()
    if args.e2e:
        rc = max(rc, run_e2e())
    return rc


if __name__ == "__main__":
    sys.exit(main())
