"""quality_gate 基线棘轮回归（2026-10-17 审计 AUD-24 / F3-7）

缺陷：
1. 基线 JSON 损坏时 load_baseline 返回 {} → 全部门禁判 NEW（不失败）→ 静默全绿；
2. --update-baseline 不拦 REGRESS → 一条命令把「新增 N 处违规」洗成新基线；
3.（F3-7）gate_baseline.json 可被手工上调且无防护：上调后新增违规被洗进基线，
   CI 用新基线判定恒绿；纯基线提交不含 .py/.vue，连本地 pre-commit 降级门禁
   都不触发 → 缺口两头都漏。
"""
import json
import os
import re
import subprocess
import sys
from argparse import Namespace
from types import SimpleNamespace

import scripts.quality_gate as q

PROJECT_ROOT = q.PROJECT_ROOT
GATE_SCRIPT = PROJECT_ROOT / "scripts" / "quality_gate.py"
HOOK = PROJECT_ROOT / ".githooks" / "pre-commit"


def test_corrupt_baseline_fails_closed(tmp_path, monkeypatch):
    bad = tmp_path / 'gate_baseline.json'
    bad.write_text('{not json', encoding='utf-8')
    monkeypatch.setattr(q, 'BASELINE_PATH', bad)

    assert q.load_baseline() is None


def test_baseline_without_counts_fails_closed(tmp_path, monkeypatch):
    """有文件但缺 counts（形状损坏）也不能当空基线放行。"""
    broken = tmp_path / 'gate_baseline.json'
    broken.write_text('{"_comment": "x"}', encoding='utf-8')
    monkeypatch.setattr(q, 'BASELINE_PATH', broken)

    assert q.load_baseline() is None


def test_missing_baseline_is_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(q, 'BASELINE_PATH', tmp_path / 'nope.json')
    assert q.load_baseline() == {}


def test_valid_baseline_parsed(tmp_path, monkeypatch):
    good = tmp_path / 'gate_baseline.json'
    good.write_text('{"counts": {"ruff": 25}}', encoding='utf-8')
    monkeypatch.setattr(q, 'BASELINE_PATH', good)

    assert q.load_baseline() == {'ruff': 25}


def _regression():
    gate = SimpleNamespace(key='ruff')
    judgement = SimpleNamespace(base=25, count=30)
    return (gate, None, judgement)


def test_update_baseline_refuses_on_regression(monkeypatch):
    saved = []
    monkeypatch.setattr(q, 'save_baseline', lambda counts: saved.append(counts))

    code = q.apply_update_baseline(
        Namespace(force=False), hard_failure=False,
        regressions=[_regression()], counts_now={'ruff': 30},
    )

    assert code == 2
    assert saved == [], '存在新增违规时不得写入新基线'


def test_update_baseline_force_allows_with_trace(monkeypatch, capsys):
    saved = []
    monkeypatch.setattr(q, 'save_baseline', lambda counts: saved.append(counts))

    code = q.apply_update_baseline(
        Namespace(force=True), hard_failure=False,
        regressions=[_regression()], counts_now={'ruff': 30},
    )

    assert code == 0
    assert saved == [{'ruff': 30}]
    out = capsys.readouterr().out
    assert 'ruff: 25 → 30' in out


def test_update_baseline_refuses_on_hard_failure(monkeypatch):
    saved = []
    monkeypatch.setattr(q, 'save_baseline', lambda counts: saved.append(counts))

    code = q.apply_update_baseline(
        Namespace(force=True), hard_failure=True, regressions=[], counts_now={},
    )

    assert code == 2
    assert saved == []


# ---------------------------------------------------------------------------
# F3-7：基线「只降不升」守卫
# ---------------------------------------------------------------------------


def test_detect_raises_flags_increased_key():
    violations = q.detect_baseline_raises(
        {'ruff': 30, 'bom': 0}, [('HEAD', {'ruff': 20, 'bom': 0})],
    )
    assert violations == [('ruff', 20, 30, 'HEAD')]


def test_detect_raises_allows_tightened_and_equal():
    violations = q.detect_baseline_raises(
        {'ruff': 20, 'bom': 0}, [('HEAD', {'ruff': 20, 'bom': 0})],
    )
    assert violations == []


def test_detect_raises_ignores_key_missing_from_reference():
    """分叉之后新增的门禁键没有可比基线 → 不据此判违规。"""
    violations = q.detect_baseline_raises(
        {'ruff': 20, 'nosec_budget': 80}, [('HEAD', {'ruff': 20})],
    )
    assert violations == []


def test_detect_raises_uses_strictest_reference():
    """上限取各参考中最严的那个：分叉点 32 / HEAD 18 → 上限 18。"""
    violations = q.detect_baseline_raises(
        {'ruff': 20}, [('分叉点', {'ruff': 32}), ('上次提交 HEAD', {'ruff': 18})],
    )
    assert violations == [('ruff', 18, 20, '上次提交 HEAD')]


def _args(**kwargs):
    base = {
        'allow_baseline_raise': False, 'report': False,
        'update_baseline': False, 'force': False,
    }
    base.update(kwargs)
    return Namespace(**base)


def test_check_ratchet_blocks_raise(monkeypatch, capsys):
    monkeypatch.setattr(q, 'resolve_baseline_refs',
                        lambda: [('HEAD', {'ruff': 20})])
    monkeypatch.delenv(q.ALLOW_BASELINE_RAISE_ENV, raising=False)

    assert q.check_baseline_ratchet(_args(), {'ruff': 30}) == 1
    out = capsys.readouterr().out
    assert '[FAIL]' in out
    assert 'ruff: 20 → 30' in out


def test_check_ratchet_allows_tighten(monkeypatch):
    monkeypatch.setattr(q, 'resolve_baseline_refs',
                        lambda: [('HEAD', {'ruff': 20})])
    assert q.check_baseline_ratchet(_args(), {'ruff': 10}) == 0


def test_check_ratchet_skips_when_no_reference(monkeypatch, capsys):
    monkeypatch.setattr(q, 'resolve_baseline_refs', lambda: [])
    assert q.check_baseline_ratchet(_args(), {'ruff': 999}) == 0
    assert '参考基线不可用' in capsys.readouterr().out


def test_check_ratchet_allows_explicit_flag(monkeypatch):
    monkeypatch.setattr(q, 'resolve_baseline_refs',
                        lambda: [('HEAD', {'ruff': 20})])
    assert q.check_baseline_ratchet(_args(allow_baseline_raise=True), {'ruff': 30}) == 0


def test_check_ratchet_allows_env(monkeypatch):
    monkeypatch.setattr(q, 'resolve_baseline_refs',
                        lambda: [('HEAD', {'ruff': 20})])
    monkeypatch.setenv(q.ALLOW_BASELINE_RAISE_ENV, '1')
    assert q.check_baseline_ratchet(_args(), {'ruff': 30}) == 0


def test_check_ratchet_allows_update_baseline_force(monkeypatch):
    monkeypatch.setattr(q, 'resolve_baseline_refs',
                        lambda: [('HEAD', {'ruff': 20})])
    args = _args(update_baseline=True, force=True)
    assert q.check_baseline_ratchet(args, {'ruff': 30}) == 0


def test_report_mode_does_not_fail(monkeypatch, capsys):
    monkeypatch.setattr(q, 'resolve_baseline_refs',
                        lambda: [('HEAD', {'ruff': 20})])
    assert q.check_baseline_ratchet(_args(report=True), {'ruff': 30}) == 0
    assert '基线被上调' in capsys.readouterr().out


# ---------------------------------------------------------------------------
# 端到端：真跑 gate 脚本（证明 main() 真的接上了检查，不只是 helper 有 teeth）
# ---------------------------------------------------------------------------


def _run_gate(*args, env_extra=None):
    env = dict(os.environ)
    env.pop(q.ALLOW_BASELINE_RAISE_ENV, None)
    env.update(env_extra or {})
    return subprocess.run(
        [sys.executable, str(GATE_SCRIPT), *args],
        cwd=PROJECT_ROOT, capture_output=True, text=True, encoding='utf-8',
        errors='replace', timeout=300, env=env,
    )


def _lowered_reference(tmp_path):
    """造一份比真实基线更严的参考基线（每个非零键 -1）。"""
    counts = q.load_baseline()
    assert counts, '真实基线为空，无法构造「被上调」场景'
    assert any(v > 0 for v in counts.values()), '真实基线全为 0，本用例失去意义'
    lowered = {k: (v - 1 if v > 0 else 0) for k, v in counts.items()}
    path = tmp_path / 'reference_baseline.json'
    path.write_text(json.dumps({'counts': lowered}), encoding='utf-8')
    return path


def test_gate_fails_when_baseline_raised(tmp_path):
    ref = _lowered_reference(tmp_path)
    proc = _run_gate('--baseline-check', env_extra={q.BASELINE_REF_ENV: str(ref)})
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert '[FAIL]' in proc.stdout


def test_gate_full_run_also_fails_when_baseline_raised(tmp_path):
    """不只 --baseline-check：普通判定路径也必须拦（证明 main() 接上了检查）。"""
    ref = _lowered_reference(tmp_path)
    proc = _run_gate('--only', 'n_plus_one', env_extra={q.BASELINE_REF_ENV: str(ref)})
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert '[FAIL]' in proc.stdout


def test_gate_passes_when_baseline_equal():
    proc = _run_gate('--baseline-check',
                     env_extra={q.BASELINE_REF_ENV: str(GATE_SCRIPT.parent / 'gate_baseline.json')})
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_gate_env_allows_raise(tmp_path):
    ref = _lowered_reference(tmp_path)
    proc = _run_gate('--baseline-check', env_extra={
        q.BASELINE_REF_ENV: str(ref), q.ALLOW_BASELINE_RAISE_ENV: '1',
    })
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_update_baseline_refuses_to_write_raised_baseline(tmp_path, monkeypatch, capsys):
    """--update-baseline 重建出的新基线高于参考基线时必须拒绝写回。"""
    target = tmp_path / 'gate_baseline.json'
    target.write_text(json.dumps({'counts': {'ruff': 5}}), encoding='utf-8')
    ref = tmp_path / 'reference.json'
    ref.write_text(json.dumps({'counts': {'ruff': 0}}), encoding='utf-8')

    monkeypatch.setattr(q, 'BASELINE_PATH', target)
    monkeypatch.setattr(q, 'run_gate',
                        lambda gate, thresholds, probe_dir, audit_report: q.GateOutcome(0, 5, ''))
    monkeypatch.setenv(q.BASELINE_REF_ENV, str(ref))
    monkeypatch.setattr(sys, 'argv', ['quality_gate.py', '--update-baseline'])

    assert q.main() == 2
    assert json.loads(target.read_text(encoding='utf-8'))['counts'] == {'ruff': 5}, \
        '拒绝写回时基线文件不得被改写'
    assert '只允许下调' in capsys.readouterr().out


# ---------------------------------------------------------------------------
# pre-commit 接线：基线文件必须在暂存时触发检查
# ---------------------------------------------------------------------------


def test_hook_triggers_on_baseline_file():
    text = HOOK.read_text(encoding='utf-8')
    assert re.search(r'^\s*scripts/gate_baseline\.json\)', text, re.M), \
        'hook 未把基线文件纳入触发条件（需精确匹配 scripts/gate_baseline.json）'
    assert 'GATE_BASELINE_REF=HEAD' in text, 'hook 未以 HEAD 为参考基线'
    assert '--baseline-check' in text, 'hook 未调用基线检查'

