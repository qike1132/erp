"""DSN / pgbouncer userlist 两条凭据规则的镜像一致性 + 行为守卫（2026-10-17 审计 P1-22）。

为什么单独成文件
----------------
原规则链只认「关键词 = 值」（`password/secret/token` 与值同现），而本仓真实凭据形态是
`scheme://user:pw@host`（`.env`、部署脚本、CI 变量）与 pgbouncer `userlist.txt` 的
`"user" "pw"` 两列 —— 关键词根本不出现，于是**本地钩子与 CI 全树扫描同时放行**，
AGENTS §5-2「凭据永不入库」此前纯靠人。

本文件锁三件事：
1. 真源（`.githooks/pre-commit` 的 `dsn_pattern` / `userlist_pattern`）与镜像
   （`scripts/_selftest_hook.py` 的 `DSN_PATTERN` / `USERLIST_PATTERN`）逐字一致；
2. 真实 `git commit` 下，DSN 内嵌口令与 userlist 内容**被拦**；
3. 占位值、插值表达式（本仓 `_build_database_uri` 的写法）**不被误拦**。
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from scripts._selftest_hook import (
    DSN_PATTERN,
    PGPASS_PATTERN,
    USERLIST_PATTERN,
    dsn_rule_hits,
    pgpass_rule_hits,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
HOOK = PROJECT_ROOT / '.githooks' / 'pre-commit'

_DSN_PATTERN_RE = re.compile(r"dsn_pattern='([^']*)'")
_USERLIST_PATTERN_RE = re.compile(r"userlist_pattern='([^']*)'")
_PGPASS_PATTERN_RE = re.compile(r"pgpass_pattern='([^']*)'")


def _normalize_cred(pattern: str) -> str:
    """POSIX 字符类归一：`[:space:]` → ` \\t`（单行文本内二者等价）。"""
    return pattern.replace('[:space:]', ' \\t')


def _shell_match(regex: re.Pattern[str], label: str) -> str:
    m = regex.search(HOOK.read_text(encoding='utf-8'))
    assert m, f'未能从 {HOOK} 提取 {label}（hook 结构可能已变）'
    return m.group(1)


def test_shell_dsn_pattern_present() -> None:
    """提取本身不能静默失效。"""
    assert '://' in _shell_match(_DSN_PATTERN_RE, 'dsn_pattern')


def test_shell_userlist_pattern_present() -> None:
    assert '[^"]+"' in _shell_match(_USERLIST_PATTERN_RE, 'userlist_pattern')


def test_mirror_matches_shell_dsn_pattern() -> None:
    shell = _normalize_cred(_shell_match(_DSN_PATTERN_RE, 'dsn_pattern'))
    mirror = _normalize_cred(DSN_PATTERN.pattern)
    assert mirror == shell, (
        'scripts/_selftest_hook.py 的 DSN_PATTERN 与 .githooks/pre-commit 的 '
        f'dsn_pattern 已漂移。\nshell : {shell}\nmirror: {mirror}'
    )


def test_mirror_matches_shell_userlist_pattern() -> None:
    shell = _normalize_cred(_shell_match(_USERLIST_PATTERN_RE, 'userlist_pattern'))
    mirror = _normalize_cred(USERLIST_PATTERN.pattern)
    assert mirror == shell, (
        'scripts/_selftest_hook.py 的 USERLIST_PATTERN 与 .githooks/pre-commit 的 '
        f'userlist_pattern 已漂移。\nshell : {shell}\nmirror: {mirror}'
    )


def test_shell_pgpass_pattern_present() -> None:
    """提取本身不能静默失效。"""
    assert '[0-9]*' in _shell_match(_PGPASS_PATTERN_RE, 'pgpass_pattern')


def test_mirror_matches_shell_pgpass_pattern() -> None:
    shell = _normalize_cred(_shell_match(_PGPASS_PATTERN_RE, 'pgpass_pattern'))
    mirror = _normalize_cred(PGPASS_PATTERN.pattern)
    assert mirror == shell, (
        'scripts/_selftest_hook.py 的 PGPASS_PATTERN 与 .githooks/pre-commit 的 '
        f'pgpass_pattern 已漂移。\nshell : {shell}\nmirror: {mirror}'
    )


# --- 行为：真实 git commit（拼接构造，避免本文件自身被扫描命中）----------------
_DSN_LITERAL = 'DATABASE_URL=postgresql://erp_app:' + 'Pr0d' + 'Passw0rd' + '@db.internal:5432/erp'
_DSN_PLACEHOLDER = 'DATABASE_URL=postgresql://u:CHANGE_ME@localhost/db'
_DSN_INTERPOLATION = 'x = f"postgresql+asyncpg://{quote_plus(u)}:{quote_plus(p)}@{host}"'
_USERLIST_LITERAL = '"erp_app" "' + 'Pr0d' + 'Passw0rd"'


def _commit_in_temp_repo(tmp_path: Path, body: str, filename: str = 'sample.py') -> subprocess.CompletedProcess:
    """在临时仓库里真跑一次 `git commit`（复制真源 hook，中和第 3 层门禁）。"""
    repo = tmp_path / 'repo'
    (repo / '.githooks').mkdir(parents=True)
    shutil.copy(HOOK, repo / '.githooks' / 'pre-commit')
    (repo / '.githooks' / 'allowlist.txt').write_text('', encoding='utf-8')
    (repo / '.pre-commit-config.yaml').write_text('repos: []\n', encoding='utf-8')
    fake_pc = repo / '.venv' / 'Scripts' / 'pre-commit'
    fake_pc.parent.mkdir(parents=True)
    fake_pc.write_text('#!/bin/sh\nexit 0\n', encoding='utf-8')
    fake_pc.chmod(0o755)
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


def test_hook_blocks_dsn_embedded_password(tmp_path: Path) -> None:
    """URL 内嵌口令必须被本地 hook 拦下（原先是两层同时放行）。"""
    result = _commit_in_temp_repo(tmp_path, _DSN_LITERAL + '\n')
    assert result.returncode != 0, (
        'DSN 内嵌口令未被本地 hook 拦下 —— AGENTS §5-2 又回到「纯靠人」。\n'
        f'{result.stdout}{result.stderr}'
    )


def test_hook_allows_dsn_placeholder(tmp_path: Path) -> None:
    """占位值不得误报（否则模板文件一改就被挡）。"""
    result = _commit_in_temp_repo(tmp_path, _DSN_PLACEHOLDER + '\n')
    assert result.returncode == 0, (
        '占位 DSN 被误判为凭据，模板文件将无法提交。\n'
        f'{result.stdout}{result.stderr}'
    )


def test_hook_allows_dsn_interpolation(tmp_path: Path) -> None:
    """插值表达式不是字面量（本仓 core/config.py::_build_database_uri 的真实写法）。"""
    result = _commit_in_temp_repo(tmp_path, _DSN_INTERPOLATION + '\n')
    assert result.returncode == 0, (
        '插值 DSN 被误判为凭据，_build_database_uri 所在文件将无法提交。\n'
        f'{result.stdout}{result.stderr}'
    )


def test_hook_blocks_userlist_content(tmp_path: Path) -> None:
    """pgbouncer userlist.txt 的内容形态（两段引号）必须被拦。"""
    result = _commit_in_temp_repo(tmp_path, _USERLIST_LITERAL + '\n')
    assert result.returncode != 0, (
        'userlist 形态未被本地 hook 拦下。\n'
        f'{result.stdout}{result.stderr}'
    )


@pytest.mark.parametrize('filename', ['config/pgbouncer/userlist.txt', 'home/.pgpass'])
def test_hook_blocks_credential_filename(tmp_path: Path, filename: str) -> None:
    """凭据文件名本身即红线（AGENTS §5-2）。"""
    result = _commit_in_temp_repo(tmp_path, 'dummy\n', filename=filename)
    assert result.returncode != 0, (
        f'{filename} 未被本地 hook 拦下 —— 路径层漏了。\n'
        f'{result.stdout}{result.stderr}'
    )


# --- 2026-11-18 推送前评审：M3/M4/M5/H1 的回归守卫 ---------------------------
#
# 四条评审发现的共性是「两侧口径走反」：钩子拦、CI 不拦，或反之。
# 只在镜像侧断言不够 —— 必须有一条真 `git commit` 走完整 hook 管道。
# 口令段在拼接处被空格打断 ⇒ 本行的 `{6,}@` 无法跨过，本文件自身不会被扫中。

_DSN_URL_ENCODED = 'DATABASE_URL=postgresql://erp_app:p%40ssw0' + 'rd123@db.internal:5432/erp'
_DSN_DOLLAR = 'REDIS_URL=redis://:Abc$123456' + '789xyz@127.0.0.1:6379/0'
_DSN_USER_INTERPOLATED = 'DATABASE_URL=postgresql://${PGUSER}:HardCoded' + '123@db.internal:5432/erp'
_DSN_REDACTED = 'x = "postgresql://u:[REDACTED]@host/db"'
_PGPASS_LITERAL = 'db.internal:5432:erp:erp_app:' + 'Pr0d' + 'Passw0rd'
_USERLIST_SAME = '"erp_app" "erp_app"'


def test_hook_blocks_url_encoded_password(tmp_path: Path) -> None:
    """M3：`p%40ssw0rd123` 是 `@` 的 URL 编码写法，此前被「含 % 即放行」整条放过。"""
    result = _commit_in_temp_repo(tmp_path, _DSN_URL_ENCODED + '\n', filename='sample.env')
    assert result.returncode != 0, (
        'URL 编码口令未被拦下 —— 越规范的口令越漏（评审 M3 的洞还在）。\n'
        f'{result.stdout}{result.stderr}'
    )


def test_hook_blocks_dollar_inside_password(tmp_path: Path) -> None:
    """M3：`$` 在口令中间仍要命中（只有「整段是表达式」才放行）。"""
    result = _commit_in_temp_repo(tmp_path, _DSN_DOLLAR + '\n', filename='sample.env')
    assert result.returncode != 0, (
        '含 $ 的真口令未被拦下 —— 表达式判定退回了「含 $ 就放行」。\n'
        f'{result.stdout}{result.stderr}'
    )


def test_hook_blocks_interpolated_user_with_literal_password(tmp_path: Path) -> None:
    """M4：user 段是插值不能替口令段开脱（此前钩子放行、CI 判红 = 密钥已进本地提交）。"""
    result = _commit_in_temp_repo(tmp_path, _DSN_USER_INTERPOLATED + '\n', filename='sample.env')
    assert result.returncode != 0, (
        'user 段插值 + 字面量口令未被拦下 —— 钩子仍比 CI 宽（评审 M4 的洞还在）。\n'
        f'{result.stdout}{result.stderr}'
    )


def test_hook_blocks_pgpass_content(tmp_path: Path) -> None:
    """M5：`.pgpass` 五段内容形态此前只有文件名兜底，改名即隐形。"""
    result = _commit_in_temp_repo(tmp_path, _PGPASS_LITERAL + '\n', filename='sample.env')
    assert result.returncode != 0, (
        'pgpass 五段内容未被拦下 —— 内容层对第三种形态仍零覆盖。\n'
        f'{result.stdout}{result.stderr}'
    )


def test_hook_allows_userlist_same_user_and_password(tmp_path: Path) -> None:
    """H1：`"erp_app" "erp_app"` 是模板写法，钩子不得假红（此前 CI 放行、钩子拒）。"""
    result = _commit_in_temp_repo(tmp_path, _USERLIST_SAME + '\n', filename='sample.env')
    assert result.returncode == 0, (
        'userlist 同名占位被误拦 —— 钩子与 CI 口径仍不一致（评审 H1）。\n'
        f'{result.stdout}{result.stderr}'
    )


def test_hook_allows_redacted_marker(tmp_path: Path) -> None:
    """`[REDACTED]` 是已脱敏标记，不该再算凭据。"""
    result = _commit_in_temp_repo(tmp_path, _DSN_REDACTED + '\n', filename='sample.env')
    assert result.returncode == 0, (
        '[REDACTED] 被误判为凭据。\n'
        f'{result.stdout}{result.stderr}'
    )


@pytest.mark.parametrize('line,expected', [
    ('DATABASE_URL=postgresql://erp_app:p%40ssw0' + 'rd123@db:5432/erp', True),
    ('REDIS_URL=redis://:Abc$123456' + '789xyz@127.0.0.1:6379/0', True),
    ('DB=postgresql://${PGUSER}:HardCoded' + '123@db:5432/erp', True),
    ('x = f"{s}://{u}:{quote_plus(p)}@{h}"', False),
    ('PASSWORD=${REDIS_PASSWORD}', False),
    ('PASSWORD=%PGPASSWORD%', False),
    ('DB=postgresql://u:<PLACEHOLDER_PASSWORD>@host/db', False),
    ('x = "postgresql://u:[REDACTED]@host/db"', False),
])
def test_mirror_dsn_expression_is_structural(line: str, expected: bool) -> None:
    """M3/M4：只有「整段就是一个表达式」才放行，含 $ % 不再无条件放行。"""
    assert dsn_rule_hits(line) is expected


@pytest.mark.parametrize('line,expected', [
    ('db.internal:5432:erp:erp_app:' + 'Pr0d' + 'Passw0rd', True),
    ('db.internal:5432:erp:erp_app:erp_app', False),
    ('.main::-webkit-scrollbar-thumb:hover{background:var(--border-strong)}', False),
    ('.nav::-webkit-scrollbar-thumb:hover{background:var(--x)}', False),
    ('127.0.0.1:8080', False),
])
def test_mirror_pgpass_content_and_css_false_positive(line: str, expected: bool) -> None:
    """M5：五段内容命中；CSS 选择器不得误报（实测两处 HTML 曾误报）。"""
    assert pgpass_rule_hits(line) is expected
