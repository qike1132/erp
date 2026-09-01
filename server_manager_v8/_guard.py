"""架构门禁 — AST 静态检查，零第三方依赖（CI / pytest / CLI 三处复用）。

守护 v8 方案 §3.3 的五条防腐化规则：

    R1 分层依赖：L4→L3→L2←L1 单向，越层 import 即失败
       （domain→[] application→{domain} adapters→{domain} presentation→{application}）
    R2 Domain 纯净：禁 subprocess/psutil/tkinter/socket/urllib/requests/shallow…
       禁 open() / os.system / eval / exec
    R3 禁静默失败：空 except-pass 与 contextlib.suppress 全面禁止
       （v6 有 148 处静默吞错，这是最深的坑）
    R4 规模门禁：文件 ≤800 行 / 函数 ≤80 行 / 类方法 ≤20 个
    R5 模块级变量只允许常量（UPPER_CASE / _PRIVATE / __dunder__）

用法::

    python -m server_manager_v8 selfcheck        # CLI
    pytest tests/server_manager_v8/test_guard.py # CI
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

__all__ = ['RULE_BOOK', 'Violation', 'check_package']

_PKG = 'server_manager_v8'
_ROOT = Path(__file__).resolve().parent

# R1 分层依赖白名单：当前层 -> 允许 import 的层（自身层内互引恒允许）
_LAYER_DEPS: dict[str, frozenset[str]] = {
    'domain': frozenset(),
    'application': frozenset({'domain'}),
    'adapters': frozenset({'domain'}),
    'presentation': frozenset({'application'}),
}
_LAYERS = ('domain', 'application', 'adapters', 'presentation')

# R2 Domain 禁用的平台/IO 模块
_DOMAIN_BANNED_MODULES = frozenset({
    'subprocess', 'psutil', 'tkinter', 'socket', 'urllib', 'urllib3',
    'requests', 'shutil', 'ctypes', 'winreg', 'pystray', 'webview',
})
# R2 Domain 禁用的危险调用（Name / Attribute 末段）
_DOMAIN_BANNED_CALLS = frozenset({'open', 'system', 'popen', 'eval', 'exec', 'compile'})

# R3 静默失败：contextlib.suppress（AST 精确匹配，避免误报 docstring 文本）
_SUPPRESS_ATTR = 'suppress'

# R4 规模门禁（对齐 docs/CODE_STANDARDS.md 2.5）
MAX_FILE_LINES = 800
MAX_FUNC_LINES = 80
MAX_CLASS_METHODS = 20

# R5 模块级允许的赋值目标形态：
#   UPPER_CASE 常量 / _PRIVATE / __dunder__ / PascalCase 类型别名（Callable 等）
_CONST_NAME_RE = re.compile(r'^_{0,2}[A-Z][a-zA-Z0-9_]*$')
_DUNDER_RE = re.compile(r'^__[a-z][a-z0-9_]*__$')


@dataclass(frozen=True)
class Violation:
    """一条门禁违规。file 相对仓库根，便于 CI 直接点击跳转。"""

    file: str
    line: int
    rule: str  # R1..R5
    message: str

    def __str__(self) -> str:  # pragma: no cover - 展示用
        return f'{self.file}:{self.line} [{self.rule}] {self.message}'


def check_package(package_dir: Path | None = None) -> list[Violation]:
    """检查整个包，返回违规清单（空列表 = 全部通过）。"""
    root = package_dir or _ROOT
    out: list[Violation] = []
    for py in sorted(root.rglob('*.py')):
        if '__pycache__' in py.parts:
            continue
        rel = py.relative_to(root.parent)
        src = py.read_text(encoding='utf-8')
        out.extend(_check_file(rel, py, src))
    return out


def _layer_of(rel_path: Path) -> str | None:
    """文件所属层。包根文件（__init__/__main__/_guard）不属于任何层。"""
    parts = rel_path.parts
    if len(parts) >= 2 and parts[0] == _PKG and parts[1] in _LAYERS:
        return parts[1]
    return None


def _check_file(rel: Path, py: Path, src: str) -> list[Violation]:
    out: list[Violation] = []
    lines = src.splitlines()
    # R4 文件行数
    if len(lines) > MAX_FILE_LINES:
        out.append(Violation(str(rel), len(lines), 'R4',
                             f'文件 {len(lines)} 行，超过 {MAX_FILE_LINES} 行上限'))
    try:
        tree = ast.parse(src)
    except SyntaxError as e:  # pragma: no cover - 语法错误由 import 冒烟暴露
        out.append(Violation(str(rel), e.lineno or 1, 'SYNTAX', f'语法错误: {e.msg}'))
        return out
    out.extend(_check_imports(rel, tree))
    out.extend(_check_suppress(rel, tree))
    out.extend(_check_empty_except(rel, tree))
    out.extend(_check_sizes(rel, tree))
    out.extend(_check_module_vars(rel, tree))
    layer = _layer_of(rel)
    if layer == 'domain':
        out.extend(_check_domain_purity(rel, tree))
    return out


def _check_suppress(rel: Path, tree: ast.Module) -> list[Violation]:
    """R3 contextlib.suppress（精确 AST 匹配：调用表达式或 from-import）。"""
    out: list[Violation] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == _SUPPRESS_ATTR and isinstance(node.func.value, ast.Name):
                if node.func.value.id == 'contextlib':
                    out.append(Violation(str(rel), node.lineno, 'R3',
                                         '禁止 contextlib.suppress（显式处理异常）'))
        elif isinstance(node, ast.ImportFrom) and node.module == 'contextlib':
            if any(a.name == _SUPPRESS_ATTR for a in node.names):
                out.append(Violation(str(rel), node.lineno, 'R3',
                                     '禁止 from contextlib import suppress（显式处理异常）'))
    return out


def _check_imports(rel: Path, tree: ast.Module) -> list[Violation]:
    """R1 分层依赖。"""
    out: list[Violation] = []
    layer = _layer_of(rel)
    if layer is None:
        return out
    allowed = _LAYER_DEPS[layer]
    for node in ast.walk(tree):
        targets: list[str] = []
        if isinstance(node, ast.Import):
            targets = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level > 0:
                # 相对导入解析：模块所在包为 [PKG, layer]，
                # level=1 即当前包，level=2 上跳一级（`from ..adapters` → PKG.adapters）
                base = [_PKG, layer]
                drop = node.level - 1
                if drop > len(base):
                    continue  # 越出包顶（不可能出现），交由运行期暴露
                base = base[: len(base) - drop] if drop else base
                if node.module:
                    base = [*base, *node.module.split('.')]
                targets = ['.'.join(base)]
            elif node.module:
                targets = [node.module]
            else:  # pragma: no cover
                continue
        for t in targets:
            if not t.startswith(_PKG + '.'):
                continue  # 第三方/stdlib 不归 R1 管
            target_layer = t.split('.')[1] if len(t.split('.')) > 1 else ''
            if target_layer in _LAYERS and target_layer != layer and target_layer not in allowed:
                out.append(Violation(
                    str(rel), node.lineno, 'R1',
                    f'{layer} 层禁止 import {target_layer} 层（{t}）；'
                    f'允许: {sorted(allowed) or "无"}',
                ))
    return out


def _check_empty_except(rel: Path, tree: ast.Module) -> list[Violation]:
    """R3 空 except-pass（v6 最深的坑：静默吞错）。"""
    out: list[Violation] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        if len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
            out.append(Violation(
                str(rel), node.lineno, 'R3',
                '禁止 except: pass —— 改为记录原因并返回显式失败结果',
            ))
    return out


def _check_sizes(rel: Path, tree: ast.Module) -> list[Violation]:
    """R4 函数 ≤80 行、类方法 ≤20 个。"""
    out: list[Violation] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            length = (node.end_lineno or node.lineno) - node.lineno + 1
            if length > MAX_FUNC_LINES:
                out.append(Violation(
                    str(rel), node.lineno, 'R4',
                    f'函数 {node.name} {length} 行，超过 {MAX_FUNC_LINES} 行上限，必须拆分',
                ))
        elif isinstance(node, ast.ClassDef):
            methods = sum(
                1 for n in node.body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            )
            if methods > MAX_CLASS_METHODS:
                out.append(Violation(
                    str(rel), node.lineno, 'R4',
                    f'类 {node.name} 有 {methods} 个方法，超过 {MAX_CLASS_METHODS} 上限'
                    f'（v6 上帝类 96 个方法的教训）',
                ))
    return out


def _check_module_vars(rel: Path, tree: ast.Module) -> list[Violation]:
    """R5 模块级只允许常量赋值。"""
    out: list[Violation] = []
    for node in tree.body:
        assigns: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            assigns = node.targets
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            assigns = [node.target]
        for t in assigns:
            if isinstance(t, ast.Name):
                name = t.id
            elif isinstance(t, (ast.Tuple, ast.List)):
                name = ','.join(getattr(e, 'id', '?') for e in t.elts)
            else:
                continue  # 属性/下标赋值不在此管
            for part in name.split(','):
                if _DUNDER_RE.match(part) or _CONST_NAME_RE.match(part):
                    continue
                out.append(Violation(
                    str(rel), node.lineno, 'R5',
                    f'模块级变量 {part!r} 必须是常量（UPPER_CASE / _PRIVATE / __dunder__），'
                    f'可变全局状态会重现 v6 的耦合',
                ))
    return out


def _check_domain_purity(rel: Path, tree: ast.Module) -> list[Violation]:
    """R2 Domain 纯净：禁平台模块、禁 IO 调用。"""
    out: list[Violation] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                top = a.name.split('.')[0]
                if top in _DOMAIN_BANNED_MODULES:
                    out.append(Violation(str(rel), node.lineno, 'R2',
                                         f'domain 禁止 import {top}（I/O 一律经 Ports 抽象）'))
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            top = node.module.split('.')[0]
            if top in _DOMAIN_BANNED_MODULES:
                out.append(Violation(str(rel), node.lineno, 'R2',
                                     f'domain 禁止 import {top}（I/O 一律经 Ports 抽象）'))
        elif isinstance(node, ast.Call):
            name = node.func
            leaf = name.id if isinstance(name, ast.Name) else (
                name.attr if isinstance(name, ast.Attribute) else ''
            )
            if leaf in _DOMAIN_BANNED_CALLS:
                out.append(Violation(str(rel), node.lineno, 'R2',
                                     f'domain 禁止调用 {leaf}()'))
    return out


RULE_BOOK: tuple[tuple[str, str], ...] = (
    ('R1', '分层依赖单向：L4→L3→L2←L1，越层 import 即失败'),
    ('R2', 'Domain 纯净：禁平台模块与 I/O 调用'),
    ('R3', '禁静默失败：空 except-pass 与 contextlib.suppress'),
    ('R4', f'规模门禁：文件≤{MAX_FILE_LINES} 行 / 函数≤{MAX_FUNC_LINES} 行 / 类方法≤{MAX_CLASS_METHODS} 个'),
    ('R5', '模块级变量只允许常量（UPPER_CASE / _PRIVATE / __dunder__）'),
)
