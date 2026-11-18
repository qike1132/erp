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

from scripts._selftest_hook import DSN_PATTERN, USERLIST_PATTERN

PROJECT_ROOT = Path(__file__).resolve().parents[3]
HOOK = PROJECT_ROOT / '.githooks' / 'pre-commit'

_DSN_PATTERN_RE = re.compile(r"dsn_pattern='([^']*)'")
_USERLIST_PATTERN_RE = re.compile(r"userlist_pattern='([^']*)'")


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
