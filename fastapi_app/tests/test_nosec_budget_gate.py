"""P1-32：nosec 预算计数口径 + quality_gate 接线回归。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from scripts import check_nosec_budget as nb
from scripts.quality_gate import GATES

_REPO = Path(__file__).resolve().parents[2]
_NOSEC = '# ' + 'nosec'  # 规避本文件被预算正则计数（tests 目录本就跳过，这里再保险）


def test_runtime_dirs_are_excluded(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(nb, '_git_tracked_py', lambda root: None)  # 走 rglob + SKIP_DIRS 分支
    (tmp_path / 'pkg').mkdir()
    (tmp_path / 'pkg' / 'ok.py').write_text(_NOSEC + '\n', encoding='utf-8')
    (tmp_path / 'logs').mkdir()
    (tmp_path / 'logs' / 'copy.py').write_text(_NOSEC + '\n', encoding='utf-8')
    (tmp_path / 'tests').mkdir()
    (tmp_path / 'tests' / 't.py').write_text(_NOSEC + '\n', encoding='utf-8')

    hits = nb.count_nosec(tmp_path)

    assert len(hits) == 1
    assert hits[0].endswith('pkg/ok.py:1')


def test_json_output_and_budget_enforced(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(nb, '_git_tracked_py', lambda root: None)  # 走 rglob + SKIP_DIRS 分支
    (tmp_path / 'pkg').mkdir()
    (tmp_path / 'pkg' / 'ok.py').write_text(_NOSEC + '\n', encoding='utf-8')

    monkeypatch.setattr(
        sys, 'argv',
        ['check_nosec_budget.py', '--root', str(tmp_path), '--json', '--budget', '5'],
    )
    assert nb.main() == 0
    assert json.loads(capsys.readouterr().out) == {'total': 1, 'budget': 5}

    monkeypatch.setattr(
        sys, 'argv',
        ['check_nosec_budget.py', '--root', str(tmp_path), '--json', '--budget', '0'],
    )
    assert nb.main() == 1
    assert json.loads(capsys.readouterr().out)['total'] == 1


def test_quality_gate_wires_nosec_budget() -> None:
    gate = next(g for g in GATES if g.key == 'nosec_budget')

    assert gate.mode == 'json'
    assert gate.extra_args == ('--json',)
    assert gate.count_key == 'total'
    assert gate.script.endswith('check_nosec_budget.py')


def test_baseline_records_nosec_budget() -> None:
    baseline = json.loads(
        (_REPO / 'scripts' / 'gate_baseline.json').read_text(encoding='utf-8'),
    )

    assert isinstance(baseline['counts'].get('nosec_budget'), int)
