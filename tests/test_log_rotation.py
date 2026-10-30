"""轮转函数单测:阈值以下不动、超阈值 copytruncate、保留 .1、IO 失败不抛。"""
from __future__ import annotations

from pathlib import Path

from utils.log_rotation import rotate_file_copytruncate


def test_below_threshold_noop(tmp_path: Path) -> None:
    f = tmp_path / "a.log"
    f.write_bytes(b"x" * 100)
    assert rotate_file_copytruncate(f, 1024) is False
    assert f.read_bytes() == b"x" * 100


def test_over_threshold_rotates(tmp_path: Path) -> None:
    f = tmp_path / "a.log"
    f.write_bytes(b"y" * 2048)
    assert rotate_file_copytruncate(f, 1024) is True
    assert f.read_bytes() == b""
    assert (tmp_path / "a.log.1").read_bytes() == b"y" * 2048


def test_rotation_replaces_old_backup(tmp_path: Path) -> None:
    f = tmp_path / "a.log"
    (tmp_path / "a.log.1").write_bytes(b"old")
    f.write_bytes(b"new" * 1000)
    assert rotate_file_copytruncate(f, 1024) is True
    assert (tmp_path / "a.log.1").read_bytes() == b"new" * 1000


def test_missing_file_returns_false(tmp_path: Path) -> None:
    assert rotate_file_copytruncate(tmp_path / "nope.log", 1024) is False


def test_io_error_swallowed(tmp_path: Path, monkeypatch) -> None:
    f = tmp_path / "a.log"
    f.write_bytes(b"z" * 2048)

    def boom(src, dst, length=0):
        raise OSError("disk")

    monkeypatch.setattr("utils.log_rotation.shutil.copyfileobj", boom)
    assert rotate_file_copytruncate(f, 1024) is False


# ── 盘点口径：策略看得到的日志 vs 看不到的其它内容 ──────────────────────────

def test_measure_log_tree_separates_policy_scope(tmp_path: Path) -> None:
    """顶层 *.log* 才算日志；子目录（如误建的 venv）计入非日志并进大目录清单。

    回归（2026-10-30）：logs 目录 1.1GB、面板只显示「上限 80MB」，根因是体积上限
    只累加顶层日志（36MB 未超限），另有 1GB 一次性产物不在统计口径内。
    """
    from utils.log_rotation import measure_log_tree

    (tmp_path / "fastapi_20261030.log").write_bytes(b"x" * 3000)
    (tmp_path / "erp-arq.log.1").write_bytes(b"x" * 2000)     # 轮转副本也算日志
    (tmp_path / "prod_runner.json").write_bytes(b"{}" * 10)   # 状态文件：不是日志

    junk = tmp_path / "_tmp_depval" / "venv"
    junk.mkdir(parents=True)
    (junk / "site-packages.bin").write_bytes(b"z" * 9000)

    tree = measure_log_tree(tmp_path, big_dir_bytes=1024)

    assert tree["log_bytes"] == 5000, tree
    assert tree["other_bytes"] == 20 + 9000, tree
    assert tree["big_dirs"] == [("_tmp_depval", 9000)], tree
    assert tree["truncated"] is False


def test_measure_log_tree_reports_truncation(tmp_path: Path) -> None:
    """条目过多时提前结束，并明确标记体积只是下限（不许假装盘完了）。"""
    from utils.log_rotation import measure_log_tree

    for i in range(6):
        (tmp_path / f"f{i}.log").write_bytes(b"x" * 10)

    tree = measure_log_tree(tmp_path, entry_limit=3)

    assert tree["truncated"] is True
    assert tree["log_bytes"] <= 30


def test_measure_log_tree_missing_dir_is_zero(tmp_path: Path) -> None:
    """目录不存在时返回全零而不是抛异常（面板刷新不该因此崩）。"""
    from utils.log_rotation import measure_log_tree

    tree = measure_log_tree(tmp_path / "not-exist")

    assert tree == {"log_bytes": 0, "other_bytes": 0, "big_dirs": [], "truncated": False}
