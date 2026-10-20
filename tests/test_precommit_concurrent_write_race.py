"""提交钩子对「并发会话写工作区」的处置（2026-10-20 事故）。

缺陷
----
`pre-commit` 的「files were modified by this hook」判定是**跑 hook 前后的全仓 diff
比对**。本机有并发会话在写工作区（AGENTS §6.1-5），第三方写入会被误记成
「hook 改动了文件」→ 提交被永久挡死（2026-10-20 连续两次：第一次连
pre-commit 自己的 stash 还原都因文件被改写而失败，第二次质量门禁明明
`[PASS]`，仍被判「既有门禁未通过」）。

修法
----
`.githooks/pre-commit` 第 3 层新增一条分支：**没有任何 hook 以非零码退出**
（输出里没有 `- exit code:`）而只出现「files were modified by this hook」时，
判定为并发写入误判 → 改按「将要提交的 blob 是否 ruff 干净」复核。

本测试用假的 `pre-commit` / `ruff` 可执行文件驱动钩子，覆盖三条分支：
误判放行、真失败拦截、暂存内容有 ruff 违规时拦截。

⚠️ 钩子通过 `git commit` 触发（而非直接 `sh .githooks/pre-commit`）：
   本机 MSYS2 运行时**不允许从 Python 子进程再套一层 MSYS2 进程**
   （NtCreateDirectoryObject / 0xC0000022），而 git 派生的 sh 不受影响。
   走 `git commit` 才与生产路径一致（core.hooksPath → sh → 钩子）。
"""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK_SRC = REPO_ROOT / '.githooks' / 'pre-commit'

# pre-commit 的两种输出形态（真实输出的结构，文本已裁剪）
OUT_FILES_MODIFIED = """\
ruff check --fix.........................Skipped
代码质量门禁............................Failed
- hook id: quality-gate
- files were modified by this hook
"""

OUT_HOOK_FAILED = """\
代码质量门禁............................Failed
- hook id: quality-gate
- exit code: 1
"""

# 假 ruff：内容含该标记即视为违规
VIOLATION_MARKER = 'RUFF_VIOLATION'

FAKE_RUFF = """\
#!/bin/sh
mode=file
for a in "$@"; do
  case "$a" in
    -) mode=stdin ;;
  esac
done
if [ "$mode" = stdin ]; then
  content=$(cat)
else
  last=""
  for a in "$@"; do last="$a"; done
  content=$(cat "$last" 2>/dev/null)
fi
case "$content" in
  *""" + VIOLATION_MARKER + """*)
    echo "sim.py:1:1: F401 simulated ruff violation" >&2
    exit 1
    ;;
esac
exit 0
"""


def _write_exec(path: Path, body: str) -> None:
    path.write_text(body, encoding='utf-8')
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def _shell_usable() -> bool:
    """本机能否派生出跑钩子所需的 shell。

    钩子是 `#!/bin/sh` 脚本，必须由 sh 解释。某些受限运行环境（如被沙箱包裹的
    工作区内解释器）**不允许子进程创建 MSYS2 共享对象**，此时 sh 启动即报
    `NtCreateDirectoryObject(...): 0xC0000022`（访问被拒），钩子根本跑不起来。
    那种环境下跳过本文件（不是断言失败），换到能跑 shell 的解释器/CI 即执行。
    """
    try:
        proc = subprocess.run(
            ['sh', '-c', 'exit 0'], capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0


_SHELL_OK = _shell_usable() and shutil.which('git') is not None
_SKIP_REASON = (
    '当前环境无法派生 sh/git（受限沙箱禁止 MSYS2 子进程创建共享对象）'
    if not _SHELL_OK else ''
)

pytestmark = pytest.mark.skipif(not _SHELL_OK, reason=_SKIP_REASON)


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ['git', *args], cwd=repo, capture_output=True, text=True,
        encoding='utf-8', errors='replace', timeout=300,
    )


def _commit_count(repo: Path) -> int:
    """仓库里的提交数（还没有任何提交时为 0）。"""
    proc = _git(repo, 'rev-list', '--count', 'HEAD')
    if proc.returncode != 0:
        return 0
    return int(proc.stdout.strip() or 0)


def _make_repo(
    tmp_path: Path,
    pre_commit_output: str,
    pre_commit_rc: int,
) -> tuple[Path, dict[str, str]]:
    repo = tmp_path / 'repo'
    (repo / '.githooks').mkdir(parents=True)
    (repo / '.githooks' / 'pre-commit').write_text(
        HOOK_SRC.read_text(encoding='utf-8'), encoding='utf-8')
    (repo / '.githooks' / 'pre-commit').chmod(0o755)
    (repo / '.githooks' / 'allowlist.txt').write_text('', encoding='utf-8')

    # 假 pre-commit：打印指定输出并返回指定退出码
    fake_bin = tmp_path / 'bin'
    fake_bin.mkdir()
    _write_exec(
        fake_bin / 'pre-commit',
        f"#!/bin/sh\ncat <<'EOF'\n{pre_commit_output}EOF\nexit {pre_commit_rc}\n",
    )

    # 假 ruff：check_staged_ruff_clean 以 `ruff check --stdin-filename X -` 调用它
    venv_scripts = repo / '.venv' / 'Scripts'
    venv_scripts.mkdir(parents=True)
    _write_exec(venv_scripts / 'ruff', FAKE_RUFF)

    env = dict(os.environ)
    env['PATH'] = f"{fake_bin}{os.pathsep}{env['PATH']}"
    subprocess.run(['git', 'init', '-q'], cwd=repo, check=True)
    _git(repo, 'config', 'user.email', 't@t')
    _git(repo, 'config', 'user.name', 't')
    _git(repo, 'config', 'core.hooksPath', '.githooks')
    (repo / 'a.txt').write_text('hello\n', encoding='utf-8')
    _git(repo, 'add', 'a.txt')
    return repo, env


def _commit(repo: Path, env: dict[str, str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ['git', 'commit', '-m', 'test'], cwd=repo, capture_output=True, text=True,
        encoding='utf-8', errors='replace', env=env, timeout=300,
    )


def test_concurrent_write_misattribution_does_not_block_commit(tmp_path):
    """误判场景：门禁自身成功（无 exit code），只因并发写入被判「改了文件」→ 放行。"""
    repo, env = _make_repo(tmp_path, OUT_FILES_MODIFIED, 1)

    proc = _commit(repo, env)

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert '并发会话写入' in proc.stderr
    assert _commit_count(repo) == 1, '放行后必须真的生成了提交'


def test_real_hook_failure_still_blocks(tmp_path):
    """真失败（hook 以非零码退出）依旧拒绝提交 —— 新分支不得放宽这一条。"""
    repo, env = _make_repo(tmp_path, OUT_HOOK_FAILED, 1)

    proc = _commit(repo, env)

    assert proc.returncode != 0, proc.stdout + proc.stderr
    assert '既有门禁未通过' in proc.stderr
    assert _commit_count(repo) == 0, '拦截后不得留下提交'


def test_staged_ruff_violation_blocks_even_in_misattribution_branch(tmp_path):
    """误判分支里暂存内容若不 ruff 干净 → 仍须拦截（否则 fixer 的修复会被漏提交）。"""
    repo, env = _make_repo(tmp_path, OUT_FILES_MODIFIED, 1)
    (repo / 'sim.py').write_text(f'x = 1  # {VIOLATION_MARKER}\n', encoding='utf-8')
    _git(repo, 'add', 'sim.py')

    proc = _commit(repo, env)

    assert proc.returncode != 0, proc.stdout + proc.stderr
    assert 'ruff' in proc.stderr
    assert _commit_count(repo) == 0


def test_clean_staged_python_passes_in_misattribution_branch(tmp_path):
    """误判分支里暂存内容 ruff 干净 → 必须放行（否则该分支等于全拦，提交仍被挡死）。"""
    repo, env = _make_repo(tmp_path, OUT_FILES_MODIFIED, 1)
    (repo / 'sim.py').write_text('x = 1\n', encoding='utf-8')
    _git(repo, 'add', 'sim.py')

    proc = _commit(repo, env)

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert _commit_count(repo) == 1


def test_hook_is_executable_and_synced_with_repo():
    """钩子本体在仓库里存在且非空（防止误删导致提交完全无保护）。"""
    assert HOOK_SRC.exists()
    assert HOOK_SRC.stat().st_size > 0
    assert 'files were modified by this hook' in HOOK_SRC.read_text(encoding='utf-8')


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
