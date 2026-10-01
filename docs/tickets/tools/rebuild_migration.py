"""将 pg_standalone_001 迁移中逐行碎片化的 op.execute 合并为完整语句。

背景
----
原文件把一条 DDL 拆成了多行，每行一个 op.execute() 调用：

    op.execute('CREATE TABLE product (')
    op.execute('	id SERIAL NOT NULL,')
    ...
    op.execute(')')
    op.execute(';')

alembic 的 op.execute(str) 每次只下发**一条独立语句**，因此
'CREATE TABLE product (' 单独执行在 PostgreSQL 上必然
`syntax error at end of input`，导致新库无法建立（原文件 1213 次 op.execute）。

本脚本用 ast 精确提取 upgrade()/downgrade() 内所有 op.execute 的字符串常量，
按 ';' 结尾合并为完整语句，重新生成迁移文件。

生成形态
--------
    _UPGRADE_STATEMENTS: tuple[str, ...] = ('CREATE TABLE ...;', ...)

    def upgrade():
        for stmt in _UPGRADE_STATEMENTS:
            op.execute(stmt)

选择"逐条下发"而非"整包一次性下发"的原因：
- 每条语句本身都是完整合法 SQL，不依赖驱动的多语句支持
- 失败时 alembic 报错能直接指出是哪一条 DDL

用法
----
    python rebuild_migration.py <源文件> <输出文件>

安全性
------
- 只读源文件，输出到新文件，不修改原文件
- 生成后用 ast 回读校验：
  ① 语句序列与预期逐条一致
  ② 去掉所有空白后与原始 payload 拼接结果**逐字符一致**（无损）
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

HEADER = '''"""pg_standalone_initial_schema

Revision ID: pg_standalone_001
Revises: None
Create Date: 2026-04-21

Standalone PostgreSQL initial migration - creates complete schema from ORM models.
Independent of MySQL migration chain (which contains MySQL dialect types).

For NEW PostgreSQL deployments:
    alembic upgrade pg_standalone_001@head

For EXISTING PostgreSQL deployments (migrated from MySQL):
    alembic stamp 659467a97350

NOTE (2026-09-12 · P0-05): 原实现把每条 DDL 拆成多行 op.execute()，
alembic 会逐条下发，导致 'CREATE TABLE x (' 单独执行即语法错误、新库无法建立。
现由 tools/rebuild_migration.py 合并为完整语句，逐条下发。
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = 'pg_standalone_001'
down_revision = None
branch_labels = ('pg_standalone',)
depends_on = None
'''


# ── 提取 ──────────────────────────────────────────────────────

def _find_function(source: str, func_name: str) -> ast.FunctionDef:
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == func_name:
            return node
    raise SystemExit(f'未找到函数 {func_name}')


def extract_payloads(source: str, func_name: str) -> list[str]:
    """按出现顺序提取指定函数体内 op.execute(<str>) 的字符串常量"""
    fn = _find_function(source, func_name)
    payloads: list[str] = []
    for stmt in fn.body:
        call = getattr(stmt, 'value', None)
        if call is None:
            raise SystemExit(f'{func_name}(): 出现非表达式语句: {type(stmt).__name__}')
        if not isinstance(call, ast.Call):
            raise SystemExit(f'{func_name}(): 出现非调用表达式: {ast.dump(call)[:80]}')
        if not isinstance(call.func, ast.Attribute) or call.func.attr != 'execute':
            raise SystemExit(f'{func_name}(): 出现非 op.execute(...) 调用')
        if not call.args or not isinstance(call.args[0], ast.Constant):
            raise SystemExit(f'{func_name}(): op.execute 参数不是字符串常量')
        payloads.append(call.args[0].value)
    return payloads


def extract_module_tuple(source: str, var_name: str) -> tuple[str, ...]:
    """读取模块级 tuple[str, ...] 常量"""
    tree = ast.parse(source)
    for node in tree.body:
        if (isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) \
                and node.target.id == var_name) or (isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == var_name for t in node.targets)):
            node = node.value
        else:
            continue
        if not isinstance(node, ast.Tuple):
            raise SystemExit(f'{var_name} 不是 tuple')
        out: list[str] = []
        for elt in node.elts:
            if not isinstance(elt, ast.Constant) or not isinstance(elt.value, str):
                raise SystemExit(f'{var_name} 元素不是字符串常量')
            out.append(elt.value)
        return tuple(out)
    raise SystemExit(f'未找到模块级变量 {var_name}')


def extract_module_string(source: str, var_name: str) -> str:
    """读取模块级字符串常量"""
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == var_name for t in node.targets):
            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                return node.value.value
            raise SystemExit(f'{var_name} 不是字符串常量')
    raise SystemExit(f'未找到模块级变量 {var_name}')


def extract_for_iter_names(source: str, func_name: str) -> list[str]:
    """列出函数体内 for <x> in <Name> 的迭代对象变量名"""
    fn = _find_function(source, func_name)
    names: list[str] = []
    for node in ast.walk(fn):
        if isinstance(node, ast.For) and isinstance(node.iter, ast.Name):
            names.append(node.iter.id)
    return sorted(set(names))


# ── 合并 ──────────────────────────────────────────────────────

def _tidy(stmt: str) -> str:
    """整理可读性：把单独成行的 ';' 并回上一行（')' + ';' → ');'）

    原文件把结尾拆成 op.execute(')') + op.execute(';') 两行，
    合并后会产生孤立的 ';' 行。语义等价，但整理后更贴近正常 SQL 书写。
    """
    lines = stmt.split('\n')
    if len(lines) >= 2 and lines[-1].strip() == ';':
        lines[-2] = lines[-2] + ';'
        lines.pop()
    return '\n'.join(lines)


def merge_statements(payloads: list[str], *, per_payload: bool = False) -> list[str]:
    """把 op.execute 的 payload 还原为完整语句

    两种模式（由原文件结构决定，不可混用）：

    - **终结符模式**（per_payload=False，用于 upgrade）：
      一条 DDL 被拆成多行碎片，最后以一个单独的 ';' payload 收尾。
      按「payload 以 ';' 结尾」切分，把碎片拼回完整语句。

    - **逐条模式**（per_payload=True，用于 downgrade）：
      每个 payload 本身就是一条完整语句，只是没写分号
      （如 'DROP SCHEMA public CASCADE'）。逐条输出并补 ';'。
      ⚠️ 不能用终结符模式：会把多条语句误合并成一条。
    """
    if per_payload:
        out = []
        for raw in payloads:
            if not raw.strip():
                continue
            stmt = _tidy(raw.strip())
            if not stmt.endswith(';'):
                stmt += ';'
            out.append(stmt)
        return out

    statements: list[str] = []
    buf: list[str] = []
    for raw in payloads:
        if not raw.strip():
            continue
        buf.append(raw)
        if raw.strip().endswith(';'):
            statements.append(_tidy('\n'.join(buf)))
            buf = []
    if buf:
        raise SystemExit(
            f'存在未以 ; 结尾的残留语句（{len(buf)} 段），'
            f'原文件结构可能已变化: {buf[:2]}'
        )
    return statements


def render(up_statements: list[str], down_statements: list[str]) -> str:
    for s in (*up_statements, *down_statements):
        if '"""' in s or '\\' in s:
            raise SystemExit('SQL 中含三引号或反斜杠，需改用其它字面量形式')

    up_body = '\n'.join(f'    """{s}""",' for s in up_statements)
    down_body = '\n'.join(f'    """{s}""",' for s in down_statements)

    return f'''{HEADER}
# 完整 DDL 语句（每条均以 ; 结尾且可独立执行）
_UPGRADE_STATEMENTS: tuple[str, ...] = (
{up_body}
)

_DOWNGRADE_STATEMENTS: tuple[str, ...] = (
{down_body}
)


def upgrade():
    # 逐条下发完整 DDL（此前每条语句被拆成多行导致语法错误）
    for _stmt in _UPGRADE_STATEMENTS:
        op.execute(_stmt)


def downgrade():
    # Drop all tables
    for _stmt in _DOWNGRADE_STATEMENTS:
        op.execute(_stmt)
'''


def main() -> None:
    src_path = Path(sys.argv[1])
    out_path = Path(sys.argv[2])
    source = src_path.read_text(encoding='utf-8')

    up_payloads = extract_payloads(source, 'upgrade')
    down_payloads = extract_payloads(source, 'downgrade')

    up_statements = merge_statements(up_payloads)
    down_statements = merge_statements(down_payloads, per_payload=True)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render(up_statements, down_statements), encoding='utf-8')

    # ── 回读校验 ──────────────────────────────────────────────
    regenerated = out_path.read_text(encoding='utf-8')

    assert extract_for_iter_names(regenerated, 'upgrade') == ['_UPGRADE_STATEMENTS']
    assert extract_for_iter_names(regenerated, 'downgrade') == ['_DOWNGRADE_STATEMENTS']

    check_up = extract_module_tuple(regenerated, '_UPGRADE_STATEMENTS')
    check_down = extract_module_tuple(regenerated, '_DOWNGRADE_STATEMENTS')

    assert list(check_up) == up_statements, 'upgrade 语句序列与预期不一致'
    assert list(check_down) == down_statements, 'downgrade 语句序列与预期不一致'

    norm = lambda s: ''.join(s.split())
    original_concat = norm('\n'.join(up_payloads))
    merged_concat = norm('\n'.join(check_up))
    assert original_concat == merged_concat, (
        'SQL 内容在合并过程中发生变化（非无损）\n'
        f'原长度={len(original_concat)} 新长度={len(merged_concat)}'
    )
    assert norm('\n'.join(check_down)) == norm('\n'.join(down_statements))

    from collections import Counter
    print(f'[OK] 源文件    : {src_path}')
    print(f'[OK] 输出文件  : {out_path}')
    print(f'[OK] upgrade   : {len(up_payloads)} 条 op.execute  →  {len(up_statements)} 条完整语句')
    print(f'[OK] 语句分布  : {dict(Counter(s.split()[0].upper() for s in up_statements))}')
    print(f'[OK] downgrade : {len(down_payloads)} 条  →  {len(down_statements)} 条')
    print('[OK] 无损校验通过（去空白后逐字符一致）')
    print(f'[OK] 文件大小  : {src_path.stat().st_size} → {out_path.stat().st_size} bytes')

    # ── 可选：用 PostgreSQL 官方解析器（libpg_query）校验语法 ──
    try:
        from pglast import parse_sql
    except ImportError:
        print('[--] 跳过 PG 语法校验（未安装 pglast；可选：pip install pglast）')
        return

    print()
    print('── PostgreSQL 语法校验（pglast / libpg_query）──')
    orig_bad = 0
    for p in up_payloads:
        try:
            parse_sql(p)
        except Exception:
            orig_bad += 1
    print(f'[OK] 原实现：{len(up_payloads)} 条中有 {orig_bad} 条不是合法 SQL '
          f'（alembic 逐条下发必失败）')
    for label, stmts in (('upgrade', up_statements), ('downgrade', down_statements)):
        bad = [(i, s[:70]) for i, s in enumerate(stmts, 1)
               if not _parses(parse_sql, s)]
        status = 'OK' if not bad else 'FAIL'
        print(f'[{status}] 修复版 {label}: {len(stmts) - len(bad)}/{len(stmts)} 条通过 PG 解析')
        for i, s in bad[:5]:
            print(f'       ✗ #{i}: {s!r}')
    if orig_bad and all(_parses(parse_sql, s) for s in (*up_statements, *down_statements)):
        print('[OK] 结论：原实现必然失败，修复版全部可被 PostgreSQL 解析')


def _parses(parse_sql, sql: str) -> bool:
    try:
        parse_sql(sql)
        return True
    except Exception:
        return False


if __name__ == '__main__':
    main()
