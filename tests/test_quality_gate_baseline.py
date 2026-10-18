"""quality_gate 基线棘轮回归（2026-10-17 审计 AUD-24）

缺陷：
1. 基线 JSON 损坏时 load_baseline 返回 {} → 全部门禁判 NEW（不失败）→ 静默全绿；
2. --update-baseline 不拦 REGRESS → 一条命令把「新增 N 处违规」洗成新基线。
"""
from argparse import Namespace
from types import SimpleNamespace

import scripts.quality_gate as q


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
