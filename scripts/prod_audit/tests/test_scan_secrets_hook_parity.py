"""`.githooks/pre-commit` ↔ `scripts/_selftest_hook.py` 规则一致性守卫。

存在理由
--------
规则链是：`.githooks/pre-commit`（**真源**，shell，手写）
      → `scripts/_selftest_hook.py`（**手工镜像**）
      → `scripts/scan_secrets.py`（import 镜像，不复制正则）。

import 只消除了「第三份副本」，**并不能**保证镜像与真源同步 ——
而两者一旦漂移，本地 hook 与 CI 扫描就会用不同的规则判断同一份代码，
出现「本地拦住、CI 放行」或反之。本文件把这条同步关系变成可执行断言。

实测已存在的已知差异
--------------------
shell 用 POSIX 字符类 `[[:space:]]`，镜像用 `[ \\t]`。单行文本里二者仅
`\\v/\\f/\\r` 上不同（`\\n` 不可能出现在单行内），故按**等价**归一化后再比对。
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from scripts._selftest_hook import PWD_PATTERN, SECRET_PATTERN

PROJECT_ROOT = Path(__file__).resolve().parents[3]
HOOK = PROJECT_ROOT / '.githooks' / 'pre-commit'

# shell 里 `secret_patterns='...'` 是单引号字面量，内部无嵌套引号，可安全提取。
_SECRET_PATTERNS_RE = re.compile(r"secret_patterns='([^']*)'")

# 已知等价差异：POSIX 字符类 → Python 等价写法
_NORMALIZE = ((r'[[:space:]]', r'[ \t]'),)


def _normalize(pattern: str) -> str:
    for posix, py in _NORMALIZE:
        pattern = pattern.replace(posix, py)
    return pattern


# `pwd_pattern` 的提取比 secret_patterns 难：shell 里它含引号拼接技巧
# `["'"'"']`（产出正则 `["']`），朴素的 `[^']*` 会在第一个 `'` 处截断。
# 下式显式允许 `'"'"'` 出现在值内，再还原为 `'`。
_PWD_PATTERN_RE = re.compile(r"pwd_pattern='((?:[^']|'\"'\"')*)'")

# pwd_pattern 专用归一化：在通用规则之上再加一条**有依据**的等价 ——
# 字符类内 `\"` 与 `"` 语义相同（Python `re` 把 `\"` 当 `"`），镜像多写的
# 反斜杠冗余但无害，故归一化掉以便逐字比对。
_PWD_NORMALIZE = ((r'[[:space:]]', r'[ \t]'), (r'\"', '"'))


def _normalize_pwd(pattern: str) -> str:
    pattern = pattern.replace("'\"'\"'", "'")
    for a, b in _PWD_NORMALIZE:
        pattern = pattern.replace(a, b)
    return pattern


def _shell_secret_patterns() -> str:
    m = _SECRET_PATTERNS_RE.search(HOOK.read_text(encoding='utf-8'))
    assert m, f'未能从 {HOOK} 提取 secret_patterns（hook 结构可能已变）'
    return m.group(1)


def _shell_pwd_pattern() -> str:
    m = _PWD_PATTERN_RE.search(HOOK.read_text(encoding='utf-8'))
    assert m, f'未能从 {HOOK} 提取 pwd_pattern（hook 结构可能已变）'
    return m.group(1)


def test_shell_secret_patterns_present() -> None:
    """同名测试确保提取本身没有静默失效。"""
    assert 'BEGIN' in _shell_secret_patterns()


def test_mirror_matches_shell_secret_patterns() -> None:
    """镜像里的 SECRET_PATTERN 必须与 shell 的真源逐字一致（归一化后）。"""
    shell = _normalize(_shell_secret_patterns())
    mirror = _normalize(SECRET_PATTERN.pattern)

    assert mirror == shell, (
        'scripts/_selftest_hook.py 的 SECRET_PATTERN 与 .githooks/pre-commit 的\n'
        'secret_patterns 已漂移 —— 本地 hook 与 CI 扫描会用不同规则判断同一份代码。\n'
        f'shell : {shell}\n'
        f'mirror: {mirror}'
    )


@pytest.mark.parametrize('token', ['AKIA', 'gh[pousr]_', 'sk-', 'BEGIN', 'xox'])
def test_both_sides_still_cover_known_credential_families(token: str) -> None:
    """防止「两侧一起被改松」：关键凭据家族必须在两侧都仍被覆盖。

    注意用模式里的**原文**（如 `gh[pousr]_` 是字符类，不是字面量 `ghp_`）。
    """
    assert token in _shell_secret_patterns()
    assert token in SECRET_PATTERN.pattern


def test_mirror_matches_shell_pwd_pattern() -> None:
    """镜像的 PWD_PATTERN 必须与 shell 的 pwd_pattern 一致（归一化后）。

    第七轮审计（2026-10-03）：此前 `pwd_pattern` 只被断言"仍存在"，不做内容比对 ——
    任一侧改动都不会被发现（覆盖率缺口）。现已纳入逐字比对：提取需处理 shell 的
    引号技巧 `["'"'"']`（见 `_PWD_PATTERN_RE`），归一化需额外去掉字符类内冗余的
    `\"`（与 `"` 语义等价）。
    """
    shell = _normalize_pwd(_shell_pwd_pattern())
    mirror = _normalize_pwd(PWD_PATTERN.pattern)

    assert mirror == shell, (
        'scripts/_selftest_hook.py 的 PWD_PATTERN 与 .githooks/pre-commit 的\n'
        'pwd_pattern 已漂移 —— 本地 hook 与 CI 扫描会用不同规则判断同一份代码。\n'
        f'shell : {shell}\n'
        f'mirror: {mirror}'
    )


def test_shell_pwd_pattern_present() -> None:
    """确保 pwd_pattern 提取本身没有静默失效（hook 结构若变，提取会先红）。"""
    assert '[Pp][Aa][Ss][Ss]' in _shell_pwd_pattern()



# ---------------------------------------------------------------------------
# 抑制标记的行为一致性
# ---------------------------------------------------------------------------
# 背景：`scripts/scan_secrets.py`（CI 侧）支持源码内抑制标记
#   `secret-scan:allow`            → 该行跳过
#   `secret-scan:allow-next-line`  → 该行的**下一行**跳过
# 而本地 hook 曾**完全不识别**这两个标记 —— 于是同一份带标记的代码
# 「CI 放行、本地拦住」，正是本文件开头所述漂移的反方向。
# 标记是否生效取决于 shell 的执行路径，静态提取正则无法覆盖，故用真实提交验证。


def _commit_in_temp_repo(tmp_path: Path, body: str, filename: str = 'sample.py') -> subprocess.CompletedProcess:
    """在临时仓库里真跑一次 `git commit`，返回其结果。"""
    repo = tmp_path / 'repo'
    (repo / '.githooks').mkdir(parents=True)
    shutil.copy(HOOK, repo / '.githooks' / 'pre-commit')
    (repo / '.githooks' / 'allowlist.txt').write_text('', encoding='utf-8')
    # 中和第 3 层：无论本机装没装 pre-commit，都不让无关门禁影响本测试的结论。
    (repo / '.pre-commit-config.yaml').write_text('repos: []\n', encoding='utf-8')
    (repo / 'scripts').mkdir()
    (repo / 'scripts' / 'quality_gate.py').write_text('raise SystemExit(0)\n', encoding='utf-8')

    def run(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ['git', *args], cwd=repo, capture_output=True, text=True,
            encoding='utf-8', errors='replace',
        )

    assert run('init', '-q').returncode == 0
    for key, value in (('core.hooksPath', '.githooks'),
                       ('user.email', 't@example.invalid'),
                       ('user.name', 't'),
                       ('commit.gpgsign', 'false')):
        assert run('config', key, value).returncode == 0

    target = repo / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding='utf-8')
    assert run('add', filename).returncode == 0
    return run('commit', '-m', 'x')


# 两条规则各取一例：口令赋值规则、私钥/云凭据特征规则。
# ⚠️ 刻意用**拼接**构造、不写成整段字面量：否则本文件自身会命中扫描器，
#    不得不为它申请 allowlist 豁免（豁免面越宽，保护越弱）。运行时仍是完整样例。
_PWD_LITERAL = 'pass' + 'word = "' + 'hunter2' * 4 + '"'
_KEY_LITERAL = 'key = "-----BEGIN ' + 'RSA PRIVATE KEY-----"'
_LITERALS = [_PWD_LITERAL, _KEY_LITERAL]


@pytest.mark.parametrize('literal', _LITERALS)
def test_hook_blocks_without_marker(tmp_path: Path, literal: str) -> None:
    """对照组：无标记时必须拦下 —— 否则下面的用例证明不了标记生效。"""
    result = _commit_in_temp_repo(tmp_path, f'{literal}\n')
    assert result.returncode != 0, '未加标记的疑似凭据被放行，对照组失效'


@pytest.mark.parametrize('literal', _LITERALS)
def test_hook_honours_next_line_marker(tmp_path: Path, literal: str) -> None:
    body = f'# secret-scan:allow-next-line\n{literal}\n'
    result = _commit_in_temp_repo(tmp_path, body)
    assert result.returncode == 0, (
        'hook 未识别 secret-scan:allow-next-line —— 本地会拦下 CI 放行的代码。\n'
        f'{result.stdout}{result.stderr}'
    )


@pytest.mark.parametrize('literal', _LITERALS)
def test_hook_honours_inline_marker(tmp_path: Path, literal: str) -> None:
    result = _commit_in_temp_repo(tmp_path, f'{literal}  # secret-scan:allow\n')
    assert result.returncode == 0, (
        'hook 未识别行内 secret-scan:allow。\n'
        f'{result.stdout}{result.stderr}'
    )


def test_hook_blocks_private_key_under_docs(tmp_path: Path) -> None:
    """路径层 parity（2026-10-17 审计 AUD-25）。

    CI 侧 scan_secrets.py 刻意不豁免 docs/（2026-09-17 凭据事故就在
    docs/ui-redesign/）；本地 hook 曾用 `*/docs/*` 放行私钥文件，导致
    「本地放行、push 后 CI 才红」——密钥已进远端历史。两侧必须同口径。
    """
    result = _commit_in_temp_repo(tmp_path, 'dummy\n', filename='docs/sample.pem')
    assert result.returncode != 0, (
        'docs/ 下的私钥文件被本地 hook 放行——与 CI 侧口径漂移。\n'
        f'{result.stdout}{result.stderr}'
    )
