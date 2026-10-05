#!/usr/bin/env python
r"""孤儿模块机械校验（P0-8）。

用法::

    .venv\Scripts\python.exe scripts\check_orphan_modules.py
    .venv\Scripts\python.exe scripts\check_orphan_modules.py --verbose

两条断言（任一失败 → 退出码 1）::

    A. mypy.ini 的 files = 白名单每一项都真实存在，且在导入图内有入边。
       白名单里躺着一个**全仓零入边**的模块，等于「看似被类型检查保护」
       —— 这正是 P0-8 要封堵的失败模式。
       另有 WARN 一档：有入边、但生产图（ROOTS 可达闭包）到不了 —— 例如只被
       scripts/ 下的一次性脚本或测试引用。这类模块是否算死代码是**人的判断**，
       机械校验只负责把它摆到台面上，不阻断。
    B. 扫描范围内不存在「零入边且非 root」的模块（孤儿模块）。

退出码：0 = 两条断言都通过；1 = 有违规。

设计要点
--------
* **只用 ast 解析**（AGENTS.md §6 红线）：不拿正则猜 import。
* **图是保守图**：任何字符串字面量只要能解析成真实存在的模块文件，就记一条
  边。于是 PEP 562 惰性导出表（utils/__init__.py 的 _EXPORTS）、
  importlib.import_module('...')、__import__('...') 这类动态导入都被算作真实
  引用 —— **宁可漏报孤儿，不可误报**：把活模块判死会直接诱导误删。
* **测试是「边的提供者」，不是「被扫描对象」**：tests/、fastapi_app/tests/ 里的
  import 也算真实引用（测试就是消费者，P0-8 里 utils/logger.py 正是靠
  tests/test_logger.py 活着的），但测试模块本身不进孤儿候选集（pytest 按目录
  收集，天然没有字符串入边）。断言 A 的 FAIL 档只认「全仓零入边」；只被测试
  引用不算 FAIL，但会在 WARN 里列出来。
* **扫描范围（universe）** = fastapi_app/ 与 utils/ 两个包（排除测试目录）。
  仓库根的 scripts/、server_manager/、deliverables/ 等既提供边、又不被判定，
  免得把一次性脚本判成孤儿。
* 包 __init__.py 不是孤儿候选：from utils.log_rotation import x 在运行期隐式
  导入父包，静态图里却只记 utils.log_rotation；故可达集向上补齐父包。
  **入边同理**（2026-10-03 修复）：``import a.b.c`` 在运行期必然执行 ``a/__init__.py``
  与 ``a/b/__init__.py``，故每条边同时补上其祖先包（仅限 known 内真实存在的）。
  否则断言 A 会把「子模块被导入、父包必然被导入」的包误判成「全仓零入边」，
  白名单里的 ``__init__.py`` 会无端变红（P2 mypy 扩容 144→370 后暴露）。
  这不削弱检测力：某包若既无子模块被导入、也无人直接引用，它依旧零入边，照旧被抓。
"""
from __future__ import annotations

import argparse
import ast
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------- 配置

#: 真实入口。只有真正会被执行/注册的模块才配当 root，绝不把「白名单里的名字」
#: 反向当 root（那是拿被测对象自证清白）。
ROOTS: tuple[str, ...] = (
    'fastapi_app.main',              # uvicorn fastapi_app.main:app（start.py / prod_runner / NSSM）
    'fastapi_app.core.arq_app',      # arq fastapi_app.core.arq_app.WorkerSettings（prod_runner._cmd_arq）
    'fastapi_app.core.prod_runner',  # python -m fastapi_app.core.prod_runner
)

#: 孤儿候选的扫描范围（包名）。
SCAN_PACKAGES: tuple[str, ...] = ('fastapi_app', 'utils')

#: 提供边但本身不参与判定的目录（相对仓库根）。
SKIP_DIR_NAMES: frozenset[str] = frozenset({
    '.git', '.venv', 'venv', '__pycache__', 'node_modules', '.archive',
    '.mypy_cache', '.pytest_cache', 'frontend-vite', 'dist', 'build',
    '.agent-teams',
})

#: 测试目录（提供边；其模块不进孤儿候选集）。
TEST_DIR_NAMES: frozenset[str] = frozenset({'tests', 'test'})

#: mypy 白名单来源。
MYPY_INI = ROOT / 'mypy.ini'


def _iter_py_files() -> list[Path]:
    out: list[Path] = []
    for path in ROOT.rglob('*.py'):
        rel_parts = path.relative_to(ROOT).parts
        if any(part in SKIP_DIR_NAMES for part in rel_parts[:-1]):
            continue
        out.append(path)
    return out


def _module_id(path: Path) -> str:
    parts = list(path.relative_to(ROOT).with_suffix('').parts)
    if parts[-1] == '__init__':
        parts.pop()
    return '.'.join(parts)


def _is_test_path(path: Path) -> bool:
    rel_parts = path.relative_to(ROOT).parts
    if any(part in TEST_DIR_NAMES for part in rel_parts[:-1]):
        return True
    return rel_parts[-1].startswith('test_') or rel_parts[-1].endswith('_test.py')


def _collect_edges(path: Path, module: str, is_package: bool, known: frozenset[str]) -> set[str]:
    """返回 module 指向的模块集合（保守图：静态 import + 可解析的字符串字面量）。"""
    try:
        # filename= 让 ast 的 SyntaxWarning（如无效转义）指向真实文件而不是 <unknown>
        tree = ast.parse(path.read_text(encoding='utf-8'), filename=path.relative_to(ROOT).as_posix())
    except (OSError, SyntaxError, UnicodeDecodeError):
        return set()

    parts = module.split('.') if module else []
    pkg = parts if is_package else parts[:-1]
    pkg_joined = '.'.join(pkg)
    targets: set[str] = set()

    def _add(candidate: str) -> None:
        if candidate in known:
            targets.add(candidate)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                _add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            level = node.level or 0
            if level:
                base_parts = pkg[:len(pkg) - (level - 1)] if level > 1 else list(pkg)
                base = '.'.join([*base_parts, node.module] if node.module else base_parts)
            else:
                base = node.module or ''
            _add(base)
            for alias in node.names:
                if alias.name == '*':
                    continue
                _add(base + '.' + alias.name if base else alias.name)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            raw = node.value.strip()
            if not raw or len(raw) > 200 or ' ' in raw or '\n' in raw:
                continue
            # 绝对模块路径，或相对本包的叶子名（PEP 562 _EXPORTS 表那一类）
            _add(raw)
            if pkg_joined:
                _add(pkg_joined + '.' + raw)
    return targets


def _with_parent_packages(dsts: set[str], known: frozenset[str]) -> set[str]:
    """把「导入子模块 ⇒ 运行期必执行其全部祖先包 __init__」补进边集（只补 known 内的）。

    这是 Python 的导入语义，**不是放宽判定**：包若有任一子模块被导入，它本身就活着；
    反之（无子模块被导入、也无人直接 import 它）它仍然零入边，断言 A 照旧抓得到。
    """
    out = set(dsts)
    for dst in dsts:
        parts = dst.split('.')
        for i in range(1, len(parts)):
            parent = '.'.join(parts[:i])
            if parent in known:
                out.add(parent)
    return out


def _split_entries(buf: str) -> list[str]:
    return [tok.strip().replace('\\', '/') for tok in buf.replace('\n', ',').split(',') if tok.strip()]


def _read_mypy_whitelist(ini: Path) -> list[str]:
    """手工解析 mypy.ini 的 files =（多行、逗号分隔、缩进续行）。"""
    entries: list[str] = []
    collecting = False
    buf = ''
    for raw in ini.read_text(encoding='utf-8-sig').splitlines():
        if raw.lstrip().startswith('#'):
            continue
        line = raw.rstrip()
        if not line.strip():
            continue
        if collecting:
            if line[:1] in (' ', '\t'):
                buf += ' ' + line.strip()
                continue
            collecting = False
            entries.extend(_split_entries(buf))
            buf = ''
        if line.startswith('files') and '=' in line:
            buf = line.split('=', 1)[1]
            collecting = True
    entries.extend(_split_entries(buf))
    return entries


def _reachable(graph: dict[str, set[str]], roots: tuple[str, ...]) -> set[str]:
    seen: set[str] = set()
    stack = list(roots)
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        for dst in graph.get(cur, ()):
            if dst not in seen:
                stack.append(dst)
    return seen


@dataclass
class _Graph:
    """导入图快照（保守图：静态 import + 可解析的字符串字面量）。"""

    known: set[str]
    path_by_module: dict[str, Path]
    is_package: dict[str, bool]
    is_test: dict[str, bool]
    indegree: dict[str, int]
    prod_reachable: set[str]
    all_reachable: set[str]
    missing_roots: list[str]


def _build_graph(files: list[Path]) -> _Graph:
    known: set[str] = set()
    path_by_module: dict[str, Path] = {}
    is_package: dict[str, bool] = {}
    is_test: dict[str, bool] = {}
    for path in files:
        mod = _module_id(path)
        if not mod:
            continue
        known.add(mod)
        path_by_module[mod] = path
        is_package[mod] = path.name == '__init__.py'
        is_test[mod] = _is_test_path(path)

    frozen = frozenset(known)
    all_edges: dict[str, set[str]] = {}
    prod_edges: dict[str, set[str]] = {}
    for mod, path in path_by_module.items():
        dsts = _collect_edges(path, mod, is_package[mod], frozen)
        dsts = _with_parent_packages(dsts, frozen)
        # 必须在补边之后：包导入自己的子模块时会把自己的祖先补回来（含自身）
        dsts.discard(mod)
        all_edges[mod] = dsts
        if not is_test[mod]:
            prod_edges[mod] = dsts

    indegree_all: dict[str, int] = dict.fromkeys(known, 0)
    for dsts in all_edges.values():
        for dst in dsts:
            indegree_all[dst] = indegree_all.get(dst, 0) + 1

    missing_roots = [r for r in ROOTS if r not in known]
    prod_reachable = _reachable(prod_edges, ROOTS)
    all_reachable = _reachable(all_edges, ROOTS)
    for mod in list(prod_reachable) + list(all_reachable):
        parts = mod.split('.')
        for i in range(1, len(parts)):
            prod_reachable.add('.'.join(parts[:i]))
            all_reachable.add('.'.join(parts[:i]))

    return _Graph(
        known=known,
        path_by_module=path_by_module,
        is_package=is_package,
        is_test=is_test,
        indegree=indegree_all,
        prod_reachable=prod_reachable,
        all_reachable=all_reachable,
        missing_roots=missing_roots,
    )


def _whitelist_check(graph: _Graph) -> tuple[list[str], list[str], list[str], list[str], list[str]]:
    """断言 A：mypy.ini 的 files 白名单 ⊆ 导入图。

    返回 (failures, prod_gap, dangling, no_edge, whitelist)。
    """
    known, indegree_all = graph.known, graph.indegree
    prod_reachable = graph.prod_reachable
    failures: list[str] = []

    whitelist = _read_mypy_whitelist(MYPY_INI) if MYPY_INI.exists() else []
    if not MYPY_INI.exists():
        failures.append('[A] 找不到 ' + MYPY_INI.name)
    dangling: list[str] = []   # 条目指向的 .py 不存在
    no_edge: list[str] = []    # 全仓零入边 —— 白名单里的死模块
    prod_gap: list[str] = []   # 有入边但生产图到不了（只被 scripts/ 或测试引用）
    for entry in whitelist:
        rel = entry[:-3] if entry.endswith('.py') else entry
        rel = rel.replace('/', '.')
        if rel.endswith('.__init__'):
            rel = rel[: -len('.__init__')]
        if rel not in known:
            dangling.append(entry)
        elif indegree_all.get(rel, 0) == 0:
            no_edge.append(entry + ' (-> ' + rel + ')')
        elif rel not in prod_reachable:
            prod_gap.append(entry + ' (-> ' + rel + ')')

    if graph.missing_roots:
        failures.append('[A] ROOTS 里的入口不存在于仓库：' + ', '.join(graph.missing_roots))
    if dangling:
        failures.append('[A] mypy.ini 白名单指向不存在的模块（悬挂条目）：\n    ' + '\n    '.join(dangling))
    if no_edge:
        failures.append('[A] mypy.ini 白名单模块全仓零入边（"看似被类型检查保护"的死人）：\n    '
                        + '\n    '.join(no_edge))
    return failures, prod_gap, dangling, no_edge, whitelist


def _collect_universe(graph: _Graph) -> list[str]:
    """断言 B 的候选集：扫描包内、非测试、非 __init__ 的模块。"""
    is_test, is_package = graph.is_test, graph.is_package
    universe: list[str] = []
    for mod in sorted(graph.known):
        if is_test[mod] or is_package[mod]:
            continue
        if mod.split('.')[0] not in SCAN_PACKAGES:
            continue
        if any(part in TEST_DIR_NAMES for part in mod.split('.')):
            continue
        universe.append(mod)

    return universe


def _assert_no_orphans(graph: _Graph, universe: list[str]) -> list[str]:
    """断言 B：扫描范围内不存在「零入边且非 root」的模块。"""
    orphans = [m for m in universe if graph.indegree.get(m, 0) == 0 and m not in ROOTS]
    if not orphans:
        return []
    return ['[B] 零入边且非 root 的孤儿模块：\n    '
            + '\n    '.join(m + '  (' + graph.path_by_module[m].relative_to(ROOT).as_posix() + ')'
                            for m in orphans)]

def _report(graph: _Graph, files: list[Path], universe: list[str], whitelist: list[str],
            dangling: list[str], no_edge: list[str], prod_gap: list[str],
            test_only: list[str], verbose: bool) -> None:
    print('扫描范围：' + ', '.join(SCAN_PACKAGES) + '（排除测试目录）；解析 .py 文件 '
          + str(len(files)) + ' 个，模块 ' + str(len(graph.known)) + ' 个；孤儿候选 '
          + str(len(universe)) + ' 个')
    print('ROOTS（' + str(len(ROOTS)) + '）：' + ', '.join(ROOTS))
    print('mypy.ini 白名单条目：' + str(len(whitelist)) + ' 个（有入边 '
          + str(len(whitelist) - len(dangling) - len(no_edge)) + '）')
    if prod_gap:
        print('[WARN] 白名单模块有入边但生产导入图不可达（只被 scripts/ 或测试引用），需人工判定是否仍该被类型保护：')
        for item in prod_gap:
            print('    ' + item)
    if test_only:
        print('[提示] 仅被测试引用（无生产入边）的模块 ' + str(len(test_only)) + ' 个：'
              + ', '.join(test_only[:20]) + (' …' if len(test_only) > 20 else ''))
    if verbose:
        print('--- 每个孤儿候选的入边数（0 = 孤儿）---')
        for mod in universe:
            print('  ' + str(graph.indegree.get(mod, 0)).rjust(3) + '  ' + mod)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description='孤儿模块校验：mypy 白名单 ⊆ 导入图，且无「零入边且非 root」模块')
    parser.add_argument('--verbose', '-v', action='store_true', help='打印每个孤儿候选模块的入边数')
    args = parser.parse_args(argv)

    files = _iter_py_files()
    graph = _build_graph(files)
    universe = _collect_universe(graph)
    failures, prod_gap, dangling, no_edge, whitelist = _whitelist_check(graph)
    failures.extend(_assert_no_orphans(graph, universe))
    test_only = [m for m in universe
                 if m not in graph.prod_reachable and m in graph.all_reachable]
    _report(graph, files, universe, whitelist, dangling, no_edge, prod_gap, test_only, args.verbose)

    if failures:
        print('\n结果：FAIL')
        for item in failures:
            print('\n' + item)
        return 1
    print('\n结果：PASS —— mypy 白名单全部在导入图内、无零入边死模块，且无零入边非 root 模块'
          + ('（' + str(len(prod_gap)) + ' 项 WARN 需人工判定）' if prod_gap else ''))
    return 0


if __name__ == '__main__':
    sys.exit(main())
