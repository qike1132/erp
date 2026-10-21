"""端到端：暂存「基线被上调」的提交必须被 pre-commit 钩子拒掉（F3-7 / 待核实 #17 的实证）。

审计 F3-7 的缺口是**两头都漏**：基线 JSON 可被手工上调，而纯基线提交不含 .py/.vue，
原先连降级门禁都不触发。修复已写进 `.githooks/pre-commit`（`scripts/gate_baseline.json`
进 case 分支 + `GATE_BASELINE_REF=HEAD … --baseline-check`），但既有测试只做了两类验证：

* `tests/test_quality_gate_baseline.py::test_hook_triggers_on_baseline_file` —— **文本断言**
  （钩子里有那行 case），不能证明这条 shell 分支真的被执行到；
* 同文件的子进程用例 —— 直接调 `quality_gate.py`，绕开了钩子。

本文件补的正是「构造场景跑钩子」这条实证：在临时 git 仓里放**真实钩子**与真实
`quality_gate.py`，造两个提交场景，断言判定结果而不是输出文本。

环境口径（改动前必读）：
* 钩子的第 3 层有两条互斥路径。这里**刻意不提供 `pre-commit`**，让它走
  「未安装 pre-commit → 降级门禁」那条——只有这条是本仓 shell 逻辑，而另一条
  的判定来自 `.pre-commit-config.yaml` 的 `always_run` 全量门禁（已由
  `test_gate_full_run_also_fails_when_baseline_raised` 覆盖）。
* 降级门禁按「暂存里有没有 .py/.vue」决定是否跑**全量扫描**。临时仓里没有真实代码树，
  全量扫描既慢又必然失真，所以两个用例都只暂存基线 JSON（need_gate=0，只跑快检查）；
  建仓时的基线提交用 `--no-verify`，它不是被测行为。
* PATH 被收窄到 git / msys / python 三个目录：跑 pytest 的解释器若来自 `.venv`，
  原样继承 PATH 会让 `command -v pre-commit` 命中 venv 里的 pre-commit，测试就走错分支。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK_SRC = REPO_ROOT / '.githooks' / 'pre-commit'
GATE_SRC = REPO_ROOT / 'scripts' / 'quality_gate.py'
PYPROJECT_SRC = REPO_ROOT / 'pyproject.toml'

BASELINE_KEY = 'ruff_scripts_violations'
BASE_V = 7
RAISED_V = BASE_V + 1
LOWERED_V = BASE_V - 1

pytestmark = pytest.mark.skipif(
    not (shutil.which('git') and shutil.which('sh')),
    reason='需要 git 与 sh 才能驱动真实钩子',
)


def _path_without_precommit() -> str:
    """继承 PATH，但剔除装有 `pre-commit` 的目录 —— 强制钩子走「降级门禁」那条分支。

    两条互斥分支里只有这条是本仓的 shell 逻辑（另一条的判定来自 `.pre-commit-config.yaml`
    的 `always_run` 全量门禁，已由 `test_gate_full_run_also_fails_when_baseline_raised` 覆盖）。
    不能整段收窄 PATH：踩过的坑是钩子由 git 派生 `sh` 执行，而 `sh.exe` 在 `Git\\usr\\bin`
    （不等于 `which git` 所在目录），收窄后 spawn 失败 = 断言的是「起不来」而不是判定逻辑。
    """
    kept = []
    for entry in os.environ.get('PATH', '').split(os.pathsep):
        if not entry:
            continue
        if (Path(entry) / 'pre-commit').is_file() or (Path(entry) / 'pre-commit.exe').is_file():
            continue
        kept.append(entry)
    return os.pathsep.join(kept)


def _make_repo(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    repo = tmp_path / 'repo'
    (repo / '.githooks').mkdir(parents=True)
    (repo / 'scripts').mkdir(parents=True)
    hook = repo / '.githooks' / 'pre-commit'
    hook.write_text(HOOK_SRC.read_text(encoding='utf-8'), encoding='utf-8')
    hook.chmod(0o755)
    (repo / '.githooks' / 'allowlist.txt').write_text('', encoding='utf-8')
    # 真实的门禁实现与被扫的 pyproject：--baseline-check 要读 [tool.code-quality]
    (repo / 'scripts' / 'quality_gate.py').write_text(
        GATE_SRC.read_text(encoding='utf-8'), encoding='utf-8')
    (repo / 'pyproject.toml').write_text(
        PYPROJECT_SRC.read_text(encoding='utf-8'), encoding='utf-8')
    _write_baseline(repo, BASE_V)

    env = dict(os.environ)
    env['PATH'] = _path_without_precommit()
    # 本测试可能在「提交钩子跑门禁」的过程中被调用（那时外层 git 已导出 GIT_DIR 等），
    # 残留变量会让临时仓的 git 指向错误的仓库；GATE_ALLOW_BASELINE_RAISE 同理——
    # 它会把「上调被拒」变成「上调放行」，测出来的就不是钩子的判定逻辑。
    for key in [k for k in env if k.startswith(('GIT_', 'GATE_ALLOW_'))]:
        env.pop(key)
    subprocess.run(['git', 'init', '-q'], cwd=repo, check=True, env=env)
    for args in (['config', 'user.email', 't@t'], ['config', 'user.name', 't'],
                 ['config', 'core.hooksPath', '.githooks']):
        subprocess.run(['git', *args], cwd=repo, check=True, env=env)

    (repo / 'a.txt').write_text('hello\n', encoding='utf-8')
    subprocess.run(['git', 'add', '-A'], cwd=repo, check=True, env=env)
    # 基线提交不是被测行为；且此时还没有 HEAD，全量门禁在临时仓里也无意义
    subprocess.run(['git', 'commit', '-q', '--no-verify', '-m', 'base'], cwd=repo,
                   check=True, env=env)
    return repo, env


def _write_baseline(repo: Path, value: int) -> None:
    (repo / 'scripts' / 'gate_baseline.json').write_text(
        json.dumps({'counts': {BASELINE_KEY: value}}), encoding='utf-8')


def _commit_baseline_change(repo: Path, env: dict[str, str], value: int) -> subprocess.CompletedProcess:
    _write_baseline(repo, value)
    subprocess.run(['git', 'add', 'scripts/gate_baseline.json'], cwd=repo, check=True, env=env)
    # 只暂存基线文件：与缺陷场景同形（纯配置提交，不含 .py/.vue）
    staged = subprocess.run(['git', 'diff', '--cached', '--name-only'], cwd=repo,
                            capture_output=True, text=True, env=env).stdout.split()
    assert staged == ['scripts/gate_baseline.json'], f'场景走形，暂存了 {staged}'
    return subprocess.run(['git', 'commit', '-m', 'raise baseline'], cwd=repo,
                          capture_output=True, text=True, encoding='utf-8',
                          errors='replace', env=env, timeout=300)


def _commit_count(repo: Path, env: dict[str, str]) -> int:
    proc = subprocess.run(['git', 'rev-list', '--count', 'HEAD'], cwd=repo,
                          capture_output=True, text=True, env=env)
    return int(proc.stdout.strip()) if proc.returncode == 0 else 0


class TestHookBlocksBaselineRaise:
    def test_raise_is_rejected(self, tmp_path: Path) -> None:
        repo, env = _make_repo(tmp_path)

        proc = _commit_baseline_change(repo, env, RAISED_V)

        assert proc.returncode != 0, (
            '基线被上调却提交成功——棘轮在钩子层失配（F3-7 复现）：\n'
            f'{proc.stdout}\n{proc.stderr}'
        )
        assert '门禁基线被上调' in proc.stderr, proc.stdout + proc.stderr
        assert _commit_count(repo, env) == 1, '提交被拒却仍然落库'

    def test_lowering_is_allowed(self, tmp_path: Path) -> None:
        """对照组：收紧基线必须放行。

        它同时证明上一条的拒绝**不是**因为「Python 没找到 / 钩子跑不起来」而误伤——
        那种情况下钩子会直接 return 0，本组也就过不了「提交成功」这一步。
        """
        repo, env = _make_repo(tmp_path)

        proc = _commit_baseline_change(repo, env, LOWERED_V)

        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert '未找到可用 Python' not in proc.stderr, proc.stderr
        assert _commit_count(repo, env) == 2, '放行后必须真的生成了提交'
