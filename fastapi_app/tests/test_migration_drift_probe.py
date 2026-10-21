"""迁移漂移探针 `scripts/diag/migration_drift_probe.py` 的回归（审计待核实 #9）。

#9 之所以挂了三天核不掉，不是没人想知道答案，而是**问一次的成本太高**：要临时写脚本、
临时找可读的 `.env`（根 `.env` 对非提权进程是 ACL 拒绝）。本探针把问题变成一条命令，
本文件锁住它的判定口径——尤其锁住两条会「把运维带偏」的假信号：

1. **读不到 ≠ 最新**：`alembic_version` 为空 / 版本号不在迁移图里 → 必须 `unknown`，
   绝不能因为「没发现落后」就报 `up_to_date`。
2. **只看单点 ≠ 已应用**：本仓迁移图有 merge revision，stamp 在 merge 点时其整条祖先链
   都已应用。用 `version_num == head` 判等会把已应用的祖先重复列入 pending。
"""

from __future__ import annotations

import importlib
import os

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
probe = importlib.import_module('scripts.diag.migration_drift_probe')

# 线性链：p ← a ← b ← head
LINEAR = {'p': (), 'a': ('p',), 'b': ('a',), 'head': ('b',)}
# 带 merge 的图：x 链与 y 链在 m 汇合，head 在 m 之上
MERGED = {
    'p': (), 'x1': ('p',), 'x2': ('x1',), 'y1': ('p',),
    'm': ('x2', 'y1'), 'head': ('m',),
}


class TestLinearChain:
    def test_at_head_is_up_to_date(self) -> None:
        status, pending, unknown, _reason = probe.classify_drift(['head'], 'head', LINEAR)
        assert (status, pending, unknown) == (probe.STATUS_UP_TO_DATE, [], [])

    def test_behind_lists_only_unapplied_in_apply_order(self) -> None:
        status, pending, _unknown, _reason = probe.classify_drift(['a'], 'head', LINEAR)
        assert status == probe.STATUS_BEHIND
        # p 与 a 已应用，不得出现在 pending；顺序必须「祖先在前」才能直接 upgrade
        assert pending == ['b', 'head']

    def test_empty_db_version_is_unknown_not_up_to_date(self) -> None:
        """探针自身的失效场景不得静默退化成「最新」——这是 runtime_mode_probe 的同一铁律。"""
        status, pending, _unknown, reason = probe.classify_drift([], 'head', LINEAR)
        assert status == probe.STATUS_UNKNOWN
        assert pending == [] and reason

    def test_ghost_version_is_unknown(self) -> None:
        status, _pending, unknown, _reason = probe.classify_drift(['manually_stamped'], 'head', LINEAR)
        assert status == probe.STATUS_UNKNOWN
        assert unknown == ['manually_stamped']


class TestMergeGraph:
    def test_stamp_at_merge_counts_whole_ancestor_closure_as_applied(self) -> None:
        """单点判等在这里会多报 4 条 pending（x1/x2/y1/p）——本用例就是它的反例。"""
        status, pending, _unknown, _reason = probe.classify_drift(['m'], 'head', MERGED)
        assert status == probe.STATUS_BEHIND
        assert pending == ['head']

    def test_only_one_branch_applied(self) -> None:
        status, pending, _unknown, _reason = probe.classify_drift(['x2'], 'head', MERGED)
        assert status == probe.STATUS_BEHIND
        # y 支与 merge 点仍待应用；m 必须先于 head
        assert pending == ['y1', 'm', 'head']

    def test_multi_row_version_table(self) -> None:
        """多行 alembic_version（历史 stamp/并行分支）取并集，不只看第一行。"""
        status, pending, _unknown, _reason = probe.classify_drift(['x2', 'y1'], 'head', MERGED)
        assert status == probe.STATUS_BEHIND
        assert pending == ['m', 'head']


class TestRealMigrationGraph:
    """用仓库真实迁移图验证——这里不钉死条数（新迁移会追加），只钉住形状。"""

    @pytest.fixture(scope='class')
    def graph(self) -> tuple[list[str], dict[str, tuple[str, ...]]]:
        heads, parents = probe.load_graph(ROOT)
        assert len(heads) == 1, f'迁移图必须单 head，实际 {heads}'
        return heads[0], parents

    def test_probe_reads_the_099_position_as_behind(self, graph: tuple[str, dict[str, tuple[str, ...]]]) -> None:
        head, parents = graph
        status, pending, unknown, _reason = probe.classify_drift(
            ['pg_standalone_099_finished_stock_remark'], head, parents,
        )
        assert status == probe.STATUS_BEHIND
        assert unknown == []
        assert 'pg_standalone_100_fs_remark_key' in pending

    def test_pending_is_topologically_ordered(self, graph: tuple[str, dict[str, tuple[str, ...]]]) -> None:
        """pending 的每个元素，其（在 pending 内的）祖先必须排在它前面。"""
        head, parents = graph
        _status, pending, _unknown, _reason = probe.classify_drift(
            ['pg_standalone_099_finished_stock_remark'], head, parents,
        )
        pos = {rev: i for i, rev in enumerate(pending)}
        for idx, rev in enumerate(pending):
            for up in parents.get(rev, ()):
                if up in pos:
                    assert pos[up] < idx, f'{up} 是 {rev} 的祖先，却被排到了后面'


class TestReportAndExitCodes:
    """`build_report` / `main` 的失败路径。

    只测 `classify_drift` 是不够的：探针自己坏掉（多 head、连不上库、读不到 .env）时
    必须报 error，不能静默降级成「没发现落后」。下面几条各自钉一个出口。
    """

    def test_multi_head_graph_is_error_not_guessed(self, monkeypatch: pytest.MonkeyPatch, tmp_path: object) -> None:
        """多 head 没有唯一终点可判定——必须 error，不能挑一个当 head 猜。"""
        monkeypatch.setattr(probe, 'load_graph', lambda _root: (['h1', 'h2'], {'h1': (), 'h2': ()}))
        monkeypatch.setattr(probe, 'query_db', lambda _url: ('erp_system', ['h1']))

        code, report = probe.build_report(str(tmp_path), 'sqlite://')

        assert code == 2
        assert report['status'] == probe.STATUS_ERROR
        assert 'head' in report['reason']

    def test_empty_version_table_exits_3_not_1(self, monkeypatch: pytest.MonkeyPatch, tmp_path: object) -> None:
        """unknown 必须与 behind 分码：巡检脚本 `exit==1 → upgrade` 不能在这里被触发。"""
        monkeypatch.setattr(probe, 'load_graph', lambda _root: (['head'], LINEAR))
        monkeypatch.setattr(probe, 'query_db', lambda _url: ('erp_system', []))

        code, report = probe.build_report(str(tmp_path), 'sqlite://')

        assert code == 3
        assert report['status'] == probe.STATUS_UNKNOWN
        assert report['pending_is_apply_order'] is False

    def test_behind_exits_1_with_apply_order(self, monkeypatch: pytest.MonkeyPatch, tmp_path: object) -> None:
        monkeypatch.setattr(probe, 'load_graph', lambda _root: (['head'], LINEAR))
        monkeypatch.setattr(probe, 'query_db', lambda _url: ('erp_system', ['a']))

        code, report = probe.build_report(str(tmp_path), 'sqlite://')

        assert code == 1
        assert report['pending'] == ['b', 'head']
        assert report['pending_is_apply_order'] is True

    def test_main_turns_probe_crash_into_error_exit(self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
        """探针自身异常（连不上库 / 读不到 .env）必须是 error，不得当成「没发现落后」。

        `_db_url` 与 `build_report` 都注入，测试才不依赖运行环境能否读到根 `.env`
        ——否则非提权机上测的是 settings 的导入失败，而不是这条兜底路径。
        """
        monkeypatch.setattr(probe, '_db_url', lambda: 'sqlite://')

        def _boom(*_args: object, **_kwargs: object) -> tuple[int, dict[str, object]]:
            raise RuntimeError('permission denied: .env')

        monkeypatch.setattr(probe, 'build_report', _boom)

        code = probe.main(['--json'])

        assert code == 2
        # 钉住 reason 内容而非仅状态码：换成别的异常也必须是这条路径的产物
        assert 'permission denied: .env' in capsys.readouterr().out

    def test_unknown_pending_is_not_labelled_as_apply_order(self, capsys: pytest.CaptureFixture[str]) -> None:
        """unknown 的 pending 是图内全集，人读输出不能标成「应用顺序 旧→新」。"""
        probe._print_human({
            'status': probe.STATUS_UNKNOWN,
            'pending': ['a', 'b'],
            'pending_is_apply_order': False,
        })

        out = capsys.readouterr().out
        assert '不可' in out
        assert '应用顺序 旧→新' not in out
