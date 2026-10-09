"""BOM 工具脚本的 stdout 处理：不得在重绑后关闭共享 buffer。

背景（2026-10-09 实测）：两个脚本原先都在模块级做
`sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")`。
重绑后旧 wrapper 失去引用被 GC，其析构会关闭**共享的**底层 buffer；而 `fix_bom`
又 `import check_bom`，两次重绑必触发 —— 脚本跑完最后一行 print 时抛
`ValueError: I/O operation on closed file`（BOM 其实已剥离成功，只是收尾炸掉）。
改用 `sys.stdout.reconfigure(...)` 原地改编码即可。
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]


def _load_module(name: str, rel_path: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, ROOT / rel_path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    # 先注册进 sys.modules：模块用 `from __future__ import annotations` 时，
    # 解析字符串注解可能需要按 __module__ 反查。
    sys.modules[spec.name] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception:
        sys.modules.pop(spec.name, None)
        raise
    return mod


def test_check_bom_import_does_not_rebind_stdout() -> None:
    before = sys.stdout
    _load_module('erp_check_bom_under_test', 'scripts/check_bom.py')
    assert sys.stdout is before, 'check_bom 不得在 import 时替换 sys.stdout（会 GC 掉共享 buffer）'


def test_fix_bom_import_does_not_rebind_stdout() -> None:
    before = sys.stdout
    _load_module('erp_fix_bom_under_test', 'scripts/fix_bom.py')
    assert sys.stdout is before, 'fix_bom 不得在 import 时替换 sys.stdout（会 GC 掉共享 buffer）'


def test_fix_bom_dry_run_exits_clean() -> None:
    """端到端复现：脚本跑完必须退出码 0 且不出现「closed file」收尾报错。"""
    proc = subprocess.run(
        [sys.executable, str(ROOT / 'scripts' / 'fix_bom.py'), '--dry-run'],
        capture_output=True, text=True, encoding='utf-8', errors='replace',
        cwd=str(ROOT), timeout=180,
    )
    assert proc.returncode == 0, proc.stderr
    assert 'I/O operation on closed file' not in (proc.stderr or '')
    assert '[OK]' in (proc.stdout or '')


def test_check_bom_exits_clean() -> None:
    proc = subprocess.run(
        [sys.executable, str(ROOT / 'scripts' / 'check_bom.py')],
        capture_output=True, text=True, encoding='utf-8', errors='replace',
        cwd=str(ROOT), timeout=180,
    )
    # 0=无 BOM，1=检出 BOM（两者都正常；2 才是环境/参数异常），且不得有未捕获异常。
    assert proc.returncode in (0, 1), proc.stderr
    assert 'Traceback' not in (proc.stderr or '')
    assert 'I/O operation on closed file' not in (proc.stderr or '')
