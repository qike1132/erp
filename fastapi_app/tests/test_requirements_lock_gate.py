"""锁门禁判据回归（2026-10-26 重写）。

旧判据「重新解析整棵依赖树 == 已提交 .lock」把**传递依赖**也算进判等：上游每发一个
补丁（10-25 ``pytest-asyncio`` 1.4.0→1.4.1，10-26 ``grpcio`` 1.84.1→1.85.0），7 个
tier 同时"失配"，main 的 CI 无端变红。而它真正要拦的是「改了 ``.txt`` 却没刷新
``.lock``」。新判据只看**声明的直接依赖**是否被锁满足。

本文件锁的是判定语义本身（不联网、不需要 uv）：
1. 声明了但锁里没有 → 失败；
2. 钉了 ``==x.y`` 而锁里是别的版本 → 失败；
3. 范围约束（``>=`` / ``<`` / ``~=``）被锁满足 → 通过；不满足 → 失败；
4. 锁里多出的传递依赖 → 不影响判定；
5. ``-r`` 递归包含、注释、选项行、extras、平台标记都按 pip/uv 口径处理。
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_MODULE_PATH = Path(__file__).resolve().parents[2] / "scripts" / "check_requirements_lock.py"


@pytest.fixture(scope="module")
def gate():
    spec = importlib.util.spec_from_file_location("check_requirements_lock", _MODULE_PATH)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _write(tmp_path: Path, name: str, text: str) -> Path:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def _check(gate, tmp_path: Path, txt_text: str, lock_text: str):
    txt = _write(tmp_path, "t.txt", txt_text)
    lock = _write(tmp_path, "t.lock", lock_text)
    return gate.check_declared("t", txt, lock)


def test_range_satisfied_passes(gate, tmp_path):
    failures, n = _check(gate, tmp_path, "aiohttp>=3.14.4\n", "aiohttp==3.14.4\n")
    assert failures == []
    assert n == 1


def test_range_violated_fails(gate, tmp_path):
    failures, _ = _check(gate, tmp_path, "aiohttp>=3.14.4\n", "aiohttp==3.14.0\n")
    assert failures and "版本不满足" in failures[0]


def test_exact_pin_mismatch_fails(gate, tmp_path):
    failures, _ = _check(gate, tmp_path, "faker==40.15.0\n", "faker==40.16.0\n")
    assert failures and "版本不满足" in failures[0]


def test_declared_but_not_locked_fails(gate, tmp_path):
    """本门禁的核心场景：改了 .txt 却没刷新 .lock。"""
    failures, _ = _check(gate, tmp_path, "brand-new-dep>=1.0\n", "other==1.0\n")
    assert failures and "未锁定" in failures[0]


def test_unpinned_declaration_only_needs_presence(gate, tmp_path):
    failures, _ = _check(gate, tmp_path, "pytest\n", "pytest==9.1.0\n")
    assert failures == []


def test_transitive_extras_do_not_fail(gate, tmp_path):
    """锁里多出的传递依赖（哪怕版本很旧）不应影响判定 —— 这是旧判据误红的地方。"""
    lock = "fastapi==0.121.0\ngrpcio==1.84.1\nstarlette==0.50.0\n"
    failures, _ = _check(gate, tmp_path, "fastapi>=0.115\n", lock)
    assert failures == []


def test_platform_marker_without_lock_entry_is_skipped(gate, tmp_path):
    failures, _ = _check(
        gate, tmp_path,
        'colorama; sys_platform == "win32"\nuvloop; sys_platform != "win32"\n',
        "colorama==0.4.6\n",
    )
    assert failures == [], "非本平台标记的依赖不该被判缺锁"


def test_marker_with_lock_entry_still_version_checked(gate, tmp_path):
    failures, _ = _check(
        gate, tmp_path,
        'colorama>=0.5; sys_platform == "win32"\n',
        "colorama==0.4.6\n",
    )
    assert failures and "版本不满足" in failures[0]


def test_extras_and_canonical_names(gate, tmp_path):
    """``uvicorn[standard]`` / ``typing_extensions`` 与锁里的写法差异不能误判。"""
    failures, _ = _check(
        gate, tmp_path,
        "uvicorn[standard]>=0.30\ntyping_extensions>=4.8\n",
        "uvicorn==0.42.0\ntyping-extensions==4.15.0\n",
    )
    assert failures == []


def test_recursive_include_and_comments(gate, tmp_path):
    _write(tmp_path, "base.txt", "# 注释\nboto3>=1.35  # 行尾注释\n")
    failures, n = _check(
        gate, tmp_path,
        "-r base.txt\n--index-url https://example.invalid/simple\nrequests>=2.32\n",
        "boto3==1.41.0\nrequests==2.33.0\n",
    )
    assert failures == []
    assert n == 2, "递归包含的声明也要计入"


def test_missing_lock_file_is_reported_as_unchecked(gate, tmp_path, capsys):
    """缺 .lock 必须失败（旧实现曾把它当"跳过"，导致新增依赖永远不生成锁）。"""
    (tmp_path / "requirements").mkdir()
    tier = "x"
    (tmp_path / "requirements" / f"{tier}.txt").write_text("a==1\n", encoding="utf-8")
    # 借 main() 的分支：把 ROOT 指到 tmp_path
    gate.ROOT = tmp_path
    rc = gate.main([tier])
    assert rc == 1
    assert "缺" in capsys.readouterr().out
