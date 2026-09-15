#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""打包 spec 与源码树的同步门禁。

═══════════════════════════════════════════════════════════════════
为什么需要这道门禁
═══════════════════════════════════════════════════════════════════

PyInstaller 的 `hiddenimports` 是一份**手写的**模块清单。手写就有两个
方向的漂移，而且两个方向都只在**打包后**才暴露：

1. **漏列**（源码有、spec 没有）
   → 运行时 `ModuleNotFoundError` / `AttributeError`。
   ★ 最危险的是惰性再导出：`usecases/__init__.py` 用字符串表按需
     import 子模块，静态分析看不到这条边，于是子模块被整体漏掉。
     源码运行完全正常，一打包就炸 —— 本地测不出来的那种。

2. **多列**（spec 有、源码没有）
   → PyInstaller 报 warning 后继续打包，产物里没有那个模块。
   看似无害，但它掩盖了真实问题：说明有人删了模块却忘了清 spec，
   或者模块名写错了（写错的**漏项**等价于情况 1）。

本门禁把两个方向都变成硬失败，并把「惰性再导出」的覆盖也一并检查
（解析 `_EXPORTS` / `_NAME_TO_MODULE` 表，确认表里每个模块都在 spec 中）。

用法：
    python scripts/check_spec_sync.py            # 检查，失败退出码 1
    python scripts/check_spec_sync.py --verbose
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / 'server_manager_v8'
SPEC = ROOT / 'packaging' / 'server_manager_v8.spec'

#: 这些模块允许不在 spec 里（明确不需要打包的）
ALLOW_MISSING: frozenset[str] = frozenset({
    #: 开发期调试脚本/工具，不进产物
    'server_manager_v8.dev_tools',
})

#: ★ 这些模块**已登记在 spec 里但源码尚未创建** —— 属于「计划中」，不是漂移。
#:
#: 必须逐个显式列出（而不是笼统放宽），因为这条豁免会掩盖真正的拼写错误：
#: 一旦某人把 `presentation.bridge` 写成 `presentation.brige`，它就会
#: 落进这里而不再报警。所以每加一项都要有明确理由，且实现后应尽快删除。
#:
#: 现状（P4 完成时）：**已全部清空** —— L4 与启动器均已实现。
#:   保留空表是为了让「将来提前登记新模块」这个用法仍然可用，
#:   且第 5 项检查会持续盯着「登记了却迟迟不实现」的情况。
PLANNED_NOT_YET: dict[str, str] = {}

#: 这些第三方模块必须出现（缺失会导致运行时崩溃）
REQUIRED_THIRDPARTY: tuple[str, ...] = ('webview',)


def _iter_source_modules() -> set[str]:
    """遍历包目录，得出所有真实存在的模块全名。

    ★ 包的 `__init__.py` 映射为**包名本身**（`a.b`），不是 `a.b.__init__` ——
      Python 里 import 的写法是 `import a.b`，`hiddenimports` 同理写 `a.b`。
      把 `__init__` 当独立模块名会产生一堆永远无法满足的假阳性。
    """
    found: set[str] = set()
    if not PKG.exists():
        return found

    def walk(directory: Path, prefix: str) -> None:
        for entry in sorted(directory.iterdir()):
            if entry.name == '__pycache__':
                continue
            if entry.is_dir():
                # 目录 → 包，自身（即 prefix.name）算一个模块
                if (entry / '__init__.py').exists():
                    name = f'{prefix}.{entry.name}'
                    found.add(name)
                    walk(entry, name)
            elif entry.suffix == '.py':
                if entry.stem == '__init__':
                    # 包的 __init__ 已经由父级目录那次 walk 登记过包名
                    found.add(prefix)
                else:
                    found.add(f'{prefix}.{entry.stem}')

    walk(PKG, 'server_manager_v8')
    return found


def _parse_spec_hiddenimports() -> set[str]:
    """从 spec 里解析出 hiddenimports 的字符串字面量。"""
    if not SPEC.exists():
        raise FileNotFoundError(f'spec 不存在：{SPEC}')

    source = SPEC.read_text(encoding='utf-8')
    tree = ast.parse(source, str(SPEC))

    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        target = node.targets[0] if node.targets else None
        name = getattr(target, 'id', None)
        if name != 'hiddenimports':
            continue
        if not isinstance(node.value, ast.List):
            raise ValueError('hiddenimports 不是字面量列表，无法静态解析')
        out: set[str] = set()
        for elt in node.value.elts:
            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                out.add(elt.value)
        return out

    raise ValueError('spec 里找不到 hiddenimports 赋值')


def _lazy_exported_modules() -> dict[str, str]:
    """解析惰性再导出表 `_EXPORTS`，返回 {模块全名: 来源文件}。

    ★ 惰性导出的模块**必然**要在 hiddenimports 里 —— 这是本门禁
      最重要的一项，因为它是最容易漏、也最难在源码态发现的一类：
      `__getattr__` 里的 `import_module(f'...{module}')` 用字符串拼模块名，
      PyInstaller 的静态分析完全看不到这条边。

    `_EXPORTS` 的形状是 `{模块短名: (导出名, ...)}`，
    所以取的是 **key**（不是 value —— value 是导出的类/函数名）。
    """
    result: dict[str, str] = {}
    init = PKG / 'application' / 'usecases' / '__init__.py'
    if not init.exists():
        return result

    tree = ast.parse(init.read_text(encoding='utf-8'), str(init))
    origin = str(init.relative_to(ROOT))

    for node in ast.walk(tree):
        # ★ `_EXPORTS: dict[str, tuple[str, ...]] = {...}` 是**带注解**的赋值，
        #   在 AST 里是 AnnAssign 而不是 Assign —— 只判 Assign 会静默漏掉，
        #   表现为「惰性导出模块数 = 0」这种「检查通过但什么都没查」的假绿灯。
        if isinstance(node, ast.AnnAssign):
            target, value = node.target, node.value
        elif isinstance(node, ast.Assign):
            target = node.targets[0] if node.targets else None
            value = node.value
        else:
            continue
        if getattr(target, 'id', None) != '_EXPORTS':
            continue
        if not isinstance(value, ast.Dict):
            raise ValueError('_EXPORTS 不是字面量字典，无法静态解析')
        for key in value.keys:
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                short = key.value
                if re.fullmatch(r'[a-z_][a-z0-9_]*', short):
                    result[f'server_manager_v8.application.usecases.{short}'] = origin
        break

    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verbose', '-v', action='store_true')
    args = parser.parse_args()

@dataclass
class Report:
    """一次检查的结果（把「逻辑」与「打印」分开，便于自检）。"""

    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    source_modules: set[str] = field(default_factory=set)
    spec_pkg: set[str] = field(default_factory=set)
    lazy_modules: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.problems


def evaluate(
    source_modules: set[str],
    spec_modules: set[str],
    lazy_modules: dict[str, str],
) -> Report:
    """核心检查逻辑（纯函数，不碰文件系统）。

    ★ 抽成纯函数是为了**自检**：门禁本身也会写错（比如上一版把
      `_EXPORTS` 当普通 Assign 解析，于是永远返回 0 个惰性模块 ——
      一个「通过但什么都没查」的假绿灯）。纯函数让这些场景可以用
      合成输入直接验证，而不必真的去改坏仓库里的 spec。
    """
    report = Report(
        source_modules=set(source_modules),
        lazy_modules=dict(lazy_modules),
    )

    #: spec 里本包的条目（含根包 `server_manager_v8` 自身 —— 它在 spec 里
    #: 是裸名不带点，用 startswith('server_manager_v8.') 会把它漏掉，
    #: 于是「根包没登记」这种真问题会被误报成缺失）
    spec_pkg = {
        m for m in spec_modules
        if m == 'server_manager_v8' or m.startswith('server_manager_v8.')
    }
    spec_other = set(spec_modules) - spec_pkg
    report.spec_pkg = spec_pkg

    # ── 检查 1：源码有、spec 没有（漏列 → 运行时会炸）──────
    missing = source_modules - spec_pkg - set(ALLOW_MISSING)
    if missing:
        report.problems.append(
            f'以下 {len(missing)} 个源码模块未登记进 spec 的 hiddenimports：'
        )
        for name in sorted(missing):
            report.problems.append(f'    - {name}')

    # ── 检查 2：惰性再导出的模块必须登记 ────────────────────
    lazy_missing = set(lazy_modules) - spec_pkg
    if lazy_missing:
        report.problems.append(
            f'以下 {len(lazy_missing)} 个「惰性再导出」模块未登记 '
            f'（静态分析看不到，打包后必炸）：'
        )
        for name in sorted(lazy_missing):
            report.problems.append(f'    - {name}   (来源 {lazy_modules[name]})')

    # ── 检查 3：spec 有、源码没有（写错名或删了模块忘了清）──
    #: 计划中的模块单独成一类：仍然报告（提醒别忘实现），但不算失败
    planned = {n for n in spec_pkg if n in PLANNED_NOT_YET}
    stale = spec_pkg - source_modules - planned
    if stale:
        report.problems.append(
            f'以下 {len(stale)} 个 spec 条目在源码里不存在（拼写错误或已删除）：'
        )
        for name in sorted(stale):
            report.problems.append(f'    - {name}')

    # ── 检查 4：必装的第三方 ────────────────────────────────
    for name in REQUIRED_THIRDPARTY:
        if name not in spec_other:
            report.problems.append(f'第三方隐藏导入缺失：{name}')

    # ── 检查 5：计划中的模块是否已实现（实现了就该清豁免）──
    fulfilled = [n for n in PLANNED_NOT_YET if n in source_modules]
    if fulfilled:
        report.warnings.append(
            f'以下 {len(fulfilled)} 个模块已实现，应从 PLANNED_NOT_YET 豁免表中删除：'
        )
        for name in sorted(fulfilled):
            report.warnings.append(f'    - {name}   ({PLANNED_NOT_YET[name]})')

    # ── 检查 6：惰性解析结果非空（防「假绿灯」自检）────────
    #:
    #: ★ 如果 usecases 包存在但解析出 0 个惰性模块，说明解析器坏了
    #:   （改成了非字面量写法、或 AST 节点类型变了）。此时若放行，
    #:   就会变成一个「通过但什么都没查」的门禁 —— 比报红更危险。
    usecases_init = PKG / 'application' / 'usecases' / '__init__.py'
    if usecases_init.exists() and not lazy_modules:
        report.problems.append(
            '惰性再导出解析结果为 0，但 usecases/__init__.py 存在 —— '
            '解析器可能已失效（写法变更？），门禁处于「假绿灯」状态'
        )

    return report


def _print_report(report: Report, verbose: bool) -> None:
    print(f'源码模块数      : {len(report.source_modules)}')
    print(f'spec 本包条目数 : {len(report.spec_pkg)}')
    print(f'惰性再导出模块  : {len(report.lazy_modules)}')
    if verbose:
        print()
        for name in sorted(report.lazy_modules):
            mark = '✓' if name in report.spec_pkg else '✗'
            print(f'  {mark} {name}')

    if report.warnings:
        print()
        for w in report.warnings:
            print(f'⚠️  {w}')

    if report.problems:
        print()
        for line in report.problems:
            print(f'❌ {line}' if not line.startswith('    ') else line)
        print()
        print('❌ 打包 spec 同步门禁未通过')
    else:
        print()
        print('✅ 打包 spec 同步门禁通过：hiddenimports 与源码树一致，'
              '惰性再导出全部覆盖')


def _selftest() -> int:
    """门禁自检：用合成输入验证每一类防御真的生效。

    ★ 为什么门禁也要自检：一个「永远通过」的门禁比没有门禁更有害 ——
      它给出虚假的安全感。本门禁在开发中就出现过一次假绿灯
      （`_EXPORTS` 是 AnnAssign 而非 Assign，解析器返回 0 个模块却报通过），
      所以这里把每一类失败都用合成数据跑一遍。
    """
    lazy = {
        'server_manager_v8.application.usecases.alert_ops': 'init',
        'server_manager_v8.application.usecases.stop_all': 'init',
    }
    good_src = {
        'server_manager_v8',
        'server_manager_v8.container',
        'server_manager_v8.application.usecases.alert_ops',
        'server_manager_v8.application.usecases.stop_all',
    }
    good_spec = set(good_src) | {'webview', 'psutil'}

    failures: list[str] = []

    def check(label: str, cond: bool, detail: str = '') -> None:
        if cond:
            print(f'  ✓ {label}')
        else:
            print(f'  ✗ {label}  {detail}')
            failures.append(label)

    print('门禁自检：')

    # 1. 正常输入 → 通过
    r = evaluate(good_src, good_spec, lazy)
    check('正常输入应通过', r.ok, f'problems={r.problems}')

    # 2. 源码有、spec 漏列 → 必须失败
    r = evaluate(good_src, good_spec - {'server_manager_v8.container'}, lazy)
    check('漏列源码模块应被抓到', not r.ok)

    # 3. spec 拼写错误 → 必须失败
    r = evaluate(good_src, good_spec | {'server_manager_v8.contianer'}, lazy)
    check('spec 拼写错误应被抓到', not r.ok)

    # 4. 惰性导出模块漏列 → 必须失败（即使它在源码集里被算作已覆盖）
    r = evaluate(
        good_src,
        good_spec - {'server_manager_v8.application.usecases.stop_all'},
        lazy,
    )
    check('惰性导出漏列应被抓到', not r.ok)

    # 5. 必装第三方缺失 → 必须失败
    r = evaluate(good_src, (good_spec - {'webview'}), lazy)
    check('缺少 webview 应被抓到', not r.ok)

    # 6. ★ 解析器失效（惰性模块数为 0）→ 必须失败，不能假绿灯
    r = evaluate(good_src, good_spec, {})
    check('惰性解析为 0 应报假绿灯', not r.ok, '这是最关键的一项')

    # 7. 已实现的「计划中」模块 → 应给 warning（不是 problem）
    #:
    #: ★ 用**临时注入**的条目，不依赖 PLANNED_NOT_YET 的真实内容 ——
    #:   否则一旦把豁免表清空（P4 完成后正是如此），这项自检就会失败，
    #:   而失败原因与「门禁是否正常工作」毫无关系。
    #:   测试应当断言自己构造的数据，而不是仓库当前的状态。
    _probe_key = 'server_manager_v8._selftest_planned'
    PLANNED_NOT_YET[_probe_key] = '自检用临时条目'
    try:
        src = good_src | {_probe_key}
        spec = good_spec | {_probe_key}
        r = evaluate(src, spec, lazy)
        check('已实现的计划模块应给 warning', bool(r.warnings))
        check('已实现的计划模块不应报错', r.ok, f'problems={r.problems}')
    finally:
        PLANNED_NOT_YET.pop(_probe_key, None)

    # 8. 空输入但 usecases 存在 → 触发假绿灯保护（真实仓库里 usecases 存在）
    r = evaluate(set(), {'webview', 'psutil'}, {})
    check('空输入应触发假绿灯保护', not r.ok)

    print()
    if failures:
        print(f'❌ 门禁自检未通过：{len(failures)} 项')
        return 1
    print('✅ 门禁自检通过：8 项防御全部生效')
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verbose', '-v', action='store_true')
    parser.add_argument('--selftest', action='store_true',
                        help='用合成输入验证门禁本身有效（防假绿灯）')
    args = parser.parse_args()

    if args.selftest:
        return _selftest()

    report = evaluate(
        _iter_source_modules(),
        _parse_spec_hiddenimports(),
        _lazy_exported_modules(),
    )
    _print_report(report, args.verbose)
    return 0 if report.ok else 1


if __name__ == '__main__':
    sys.exit(main())
