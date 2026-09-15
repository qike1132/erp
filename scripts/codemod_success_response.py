"""Codemod：把内联 `{'success': True, ...}` 响应信封迁移到 `success_response(...)`（A1）

**为什么用 codemod 而不是手改**：79+ 处跨 19 个文件，且形态不一（单行 / 多行 /
`**result` 展开 / `'message': x, **result` 混合），手改成本高且容易漏。

**正确性依据（关键）**

    {'success': True, <rest>}   ≡   success_response(**{<rest>})

因为 `success_response(**fields)` 的实现就是 `{'success': True, **fields}`。
所以转换**只需替换前缀**，完全不必解析其余键值 —— 这消除了键名转换、
嵌套 dict、f-string 等全部风险。

**输出形态**
- 单行、且键均为简单字符串字面量、无 `**` 展开 → `success_response(k=v, ...)`（可读）
- 其余（多行 / 含 `**`）→ `success_response(**{<rest>})`（保底，恒等价）

**刻意不处理**：`services/` 层的同名写法。那里混有**内部结果字典**
（如 `backup/incremental.py` 的备份结果）与**单项部分结果**
（如 `stock_in_service.py` 的 `results[i] = {'success': False, ...}`），
一刀切会破坏语义。仅迁移 `api/v1/endpoints/**` 的 HTTP 响应信封。

用法：
    python scripts/codemod_success_response.py --dry-run     # 只看将改什么
    python scripts/codemod_success_response.py --apply       # 实际写入
"""
from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET_GLOB = 'fastapi_app/api/v1/endpoints/**/*.py'
IMPORT_LINE = 'from fastapi_app.core.response import success_response\n'
IMPORT_MODULE = 'fastapi_app.core.response'


class _Match:
    """一个待替换的 dict 字面量。"""

    def __init__(self, node: ast.Dict, keys_simple: bool) -> None:
        self.node = node
        self.keys_simple = keys_simple

    @property
    def start(self) -> int:
        return self.node.lineno

    @property
    def end(self) -> int:
        return self.node.end_lineno or self.node.lineno


def _is_success_true(node: ast.Dict) -> bool:
    """首键为 success 且值为 True。"""
    if not node.keys or not node.values:
        return False
    k = node.keys[0]
    if not (isinstance(k, ast.Constant) and k.value == 'success'):
        return False
    v = node.values[0]
    return isinstance(v, ast.Constant) and v.value is True


def _keys_all_simple(node: ast.Dict) -> bool:
    """除首键外，其余键均为字符串字面量且无 `**` 展开。"""
    for k in node.keys[1:]:
        if k is None:                       # `**spread`
            return False
        if not (isinstance(k, ast.Constant) and isinstance(k.value, str)):
            return False
    return True


def collect(src: str) -> list[_Match]:
    """收集待替换的 dict，跳过嵌套在外层目标 dict 内部的（只处理最外层）。"""
    tree = ast.parse(src)
    found: list[ast.Dict] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict) and _is_success_true(node):
            found.append(node)

    # 去嵌套：若 A 的跨度包含 B，则丢弃 B
    outer: list[ast.Dict] = []
    for a in found:
        if any(
            a is not b
            and b.lineno <= a.lineno
            and (b.end_lineno or b.lineno) >= (a.end_lineno or a.lineno)
            and not (b.lineno == a.lineno and b.col_offset == a.col_offset)
            for b in found
        ):
            continue
        outer.append(a)

    return [_Match(d, _keys_all_simple(d)) for d in outer]


def _strip_first_key(seg: str) -> str:
    """从 `'success': True, <rest>` 中剥掉首键，返回 `<rest>`（保留原格式）。"""
    i = seg.index(':') + 1            # 第一个冒号（键为字符串字面量，安全）
    j = i
    while j < len(seg) and seg[j] in ' \t':
        j += 1
    if seg[j:j + 4] == 'True':
        j += 4
    while j < len(seg) and seg[j] in ' \t':
        j += 1
    if j < len(seg) and seg[j] == ',':
        j += 1
    return seg[j:]


def _render_simple(node: ast.Dict, seg: str) -> str | None:
    """单行 + 简单键 → `success_response(k=v, ...)`；失败返回 None 走保底形态。"""
    if '\n' in seg:
        return None
    inner = seg[1:-1]                        # 去掉花括号
    rest = _strip_first_key(inner).strip().rstrip(',')
    if not rest:
        return 'success_response()'

    parts = [p.strip() for p in _split_top_level(rest)]
    args = []
    for p in parts:
        if ':' not in p:
            return None                      # 形态不符，走保底
        k, _, v = p.partition(':')
        k = k.strip().strip("'\"")
        if not k.isidentifier():
            return None
        args.append(f'{k}={v.strip()}')
    return f"success_response({', '.join(args)})"


def _split_top_level(s: str) -> list[str]:
    """按顶层逗号切分（跳过括号/引号内部）。"""
    out, buf, depth, quote = [], [], 0, ''
    for ch in s:
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = ''
            continue
        if ch in '\'"':
            quote = ch
            buf.append(ch)
        elif ch in '([{':
            depth += 1
            buf.append(ch)
        elif ch in ')]}':
            depth -= 1
            buf.append(ch)
        elif ch == ',' and depth == 0:
            out.append(''.join(buf))
            buf = []
        else:
            buf.append(ch)
    if buf:
        out.append(''.join(buf))
    return out


def rewrite(src: str) -> tuple[str, int]:
    """返回 (新源码, 替换处数)。"""
    matches = collect(src)
    if not matches:
        return src, 0

    lines = src.splitlines(keepends=True)
    # 先算出行级替换（多行时按行拼接），从后往前替换避免偏移错乱
    edits: list[tuple[int, int, str]] = []
    for m in sorted(matches, key=lambda x: x.start, reverse=True):
        start, end = m.start, m.end
        seg = ''.join(lines[start - 1:end])
        # 定位 dict 在片段中的精确起止
        off = seg.index('{')
        seg_dict = seg[off:]
        # 找到与首花括号配对的收尾花括号
        depth, quote, close = 0, '', None
        for idx, ch in enumerate(seg_dict):
            if quote:
                if ch == quote:
                    quote = ''
                continue
            if ch in '\'"':
                quote = ch
            elif ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    close = idx
                    break
        if close is None:
            continue
        dict_text = seg_dict[:close + 1]

        new_text = None
        if m.keys_simple:
            new_text = _render_simple(m.node, dict_text)
        if new_text is None:
            rest = _strip_first_key(dict_text[1:-1]).rstrip()
            if rest.endswith(','):
                rest = rest[:-1]
            if '\n' not in rest:
                rest = rest.strip()          # 单行：清掉首尾空白，避免 `{ **result}`
            new_text = f'success_response(**{{{rest}}})' if rest else 'success_response()'

        prefix = seg[:off]
        suffix = seg_dict[close + 1:]
        edits.append((start - 1, end, prefix + new_text + suffix))

    new_lines = list(lines)
    for s, e, text in edits:
        new_lines[s:e] = [text]

    out = ''.join(new_lines)
    return out, len(edits)


def _module_of(node: ast.AST) -> str:
    """取 import 语句的模块名（`import a.b` 与 `from a.b import c` 统一）。"""
    if isinstance(node, ast.ImportFrom):
        return node.module or ''
    if isinstance(node, ast.Import):
        return node.names[0].name if node.names else ''
    return ''


def ensure_import(src: str) -> tuple[str, bool]:
    """按模块序插入 import；已存在则不动。

    ⚠️ 只考虑**模块级**（`tree.body`）的一手 import。早先版本按文本行扫描，
    会把**函数内的局部 import**（如 auth.py 里 `from fastapi_app.services import ...`）
    当成模块级，导致 import 被插进函数体 → IndentationError。
    """
    if IMPORT_MODULE in src:
        return src, False

    tree = ast.parse(src)
    first_party = [
        n for n in tree.body
        if isinstance(n, (ast.Import, ast.ImportFrom))
        and _module_of(n).startswith('fastapi_app')
    ]
    if not first_party:
        return src, False

    insert_at = None
    for n in first_party:
        if _module_of(n) > IMPORT_MODULE:
            insert_at = n.lineno - 1
            break
    if insert_at is None:
        insert_at = max(n.end_lineno or n.lineno for n in first_party)

    lines = src.splitlines(keepends=True)
    lines.insert(insert_at, IMPORT_LINE)
    return ''.join(lines), True


def main() -> None:
    ap = argparse.ArgumentParser(description='A1 响应信封迁移 codemod')
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--dry-run', action='store_true')
    g.add_argument('--apply', action='store_true')
    args = ap.parse_args()

    files = sorted(ROOT.glob(TARGET_GLOB))
    total_sites = total_files = 0
    for path in files:
        src = path.read_text(encoding='utf-8')
        new, n = rewrite(src)
        if n == 0:
            continue
        new, added = ensure_import(new)
        rel = path.relative_to(ROOT).as_posix()
        print(f'  {rel:<62} {n:>2} 处' + ('  (+import)' if added else ''))
        total_sites += n
        total_files += 1
        if args.apply:
            path.write_text(new, encoding='utf-8')

    mode = '将修改' if args.dry_run else '已修改'
    print(f'\n{mode} {total_files} 个文件 / {total_sites} 处')
    if args.dry_run:
        print('（dry-run，未写入。确认无误后加 --apply）')


if __name__ == '__main__':
    sys.exit(main())
