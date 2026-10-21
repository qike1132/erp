# tests/test_selftest_gate_stderr_encoding.py
"""回归锁：门禁自检 `_selftest_gate.py` 读子进程 stderr 必须按 UTF-8，不能是本地码页。

背景（2026-10-21）
----------------
`python scripts/_selftest_gate.py` 在**干净树**上恒 exit 1，两条红项是
「check_bare_except.py / check_function_length.py 对语法错误文件发出 WARN」——
单独跑子进程实测 WARN 确实发在 stderr。红因在父进程：`run()` 用
`encoding="utf-8"` 解码，而子进程的 **stderr 没有被包装**（这两个脚本只包 stdout，
`check_n_plus_one.py` 亦然），Windows 默认按本地码页 cp936 写出 → UTF-8 解码得乱码 →
`"解析失败" in err` 恒 False。

为什么值得单独锁：这个自检是「改门禁后必跑」的那道防线，它自己恒红就等于**没有**防线
（红项被习惯性地忽略掉，是比缺门禁更坏的状态）。修法只有一行（子进程 env 加
`PYTHONIOENCODING=utf-8`），但必须有断言钉住，否则下次有人"清理"参数就又回到恒红。

比对纯 ASCII 串的断言（"WARN"/"REGRESS"/"[FAIL]"）不受此坑影响，所以此前只有
**中文**比对项在红——看起来像"个别用例有问题"，实际是编码前提整个坏了。
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SELFTEST = ROOT / "scripts" / "_selftest_gate.py"
BAD_SOURCE = "def broken(:\n    pass\n"


@pytest.fixture(scope="module")
def selftest_mod():
    spec = importlib.util.spec_from_file_location("stg_probe", SELFTEST)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["stg_probe"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_run_reads_chinese_stderr_as_utf8(selftest_mod) -> None:
    """机制锁：去掉 run() 里的 PYTHONIOENCODING 即变红。"""
    _rc, _out, err = selftest_mod.run("-c", "import sys; sys.stderr.write('解析失败')")
    assert "解析失败" in err, f"子进程中文 stderr 被解成乱码：{err[:40]!r}"


def test_real_consumer_warn_is_visible_to_selftest(selftest_mod, tmp_path: Path) -> None:
    """真实消费路径锁：自检靠 "解析失败" 判 WARN 的那两条，必须真能在 stderr 里看到。

    探针落在仓库内（与 `_selftest_gate.py` 自己的做法一致）：checker 内部要
    `relative_to(PROJECT_ROOT)`，仓库外路径会直接 ValueError。
    """
    probe = ROOT / "fastapi_app" / "_zz_env_probe.py"
    try:
        probe.write_text(BAD_SOURCE, encoding="utf-8")
        for gate in ("check_bare_except.py", "check_function_length.py"):
            _rc, _out, err = selftest_mod.run(f"scripts/{gate}", str(probe.relative_to(ROOT)))
            assert "解析失败" in err, f"{gate} 的 WARN 在自检的解码口径下不可见：{err[:60]!r}"
    finally:
        probe.unlink(missing_ok=True)
        assert not probe.exists()
