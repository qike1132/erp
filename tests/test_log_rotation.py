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
