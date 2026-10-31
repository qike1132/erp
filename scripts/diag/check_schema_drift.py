"""ORM 元数据与数据库实际索引的结构对账（只读）。

背景
----
本仓 `alembic autogenerate` 被生产禁令封锁（AGENTS.md §5.7），且历史 psql
备份恢复走「DROP+CREATE 库 + stamp 版本」路径，曾造成「alembic_version=head
但结构落后于迁移终态」的静默漂移（2026-10-31 体检发现 8+ 个幽灵索引声明）。
本脚本让漂移可被机器发现，防止复发。

比对口径
--------
- **名字级**（权威）：ORM ``Base.metadata`` 索引名集合 vs ``pg_indexes``。
  MODEL_ONLY = 模型声明但库里没有（幽灵索引，永不生效）；
  DB_ONLY   = 库里有但模型未声明（结构漂移或迁移遗留）。
  主键/唯一约束的自动索引（``*_pkey``、``<table>_<col>_key``）按 PG 自动命名
  规则剔除，不参与漂移判定。
- **定义级**（尽力而为）：对同名索引比对列名集合（忽略顺序/DESC/谓词差异，
  只报列集不同的高置信差异；谓词/INCLUDE/using 差异不比对，避免格式噪音
  误报洪水——这些差异交给人工 EXPLAIN 核对）。

用法
----
    python scripts/check_schema_drift.py            # 连 .env 指向的库
    python scripts/check_schema_drift.py --dsn postgresql://...  # 显式指定
    python scripts/check_schema_drift.py --table order           # 只看一张表

退出码：0 = 无漂移；1 = 存在漂移（可接 CI/门禁）；2 = 连接/运行错误。
只读：仅 SELECT pg_indexes / pg_roles，无任何写操作。
"""
from __future__ import annotations

import argparse
import asyncio
import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

try:
    import asyncpg
except ImportError:
    print('需要 asyncpg：请在 venv 中运行', file=sys.stderr)
    sys.exit(2)

ENV_PATH = _REPO_ROOT / '.env'


def load_env() -> dict[str, str]:
    cfg: dict[str, str] = {}
    if ENV_PATH.exists():
        for raw in ENV_PATH.read_text(encoding='utf-8').splitlines():
            line = raw.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            k, _, v = line.partition('=')
            cfg[k.strip()] = v.strip()
    return cfg


def _norm_col(text: str) -> str:
    """列名归一化：去引号/类型 cast/DESC 修饰/多余括号/gin ops。"""
    t = text.strip().strip('"')
    t = re.sub(r'::[a-zA-Z_]+(\(\d+(,\d+)?\))?', '', t)
    t = re.sub(r'\s+gin_trgm_ops.*$', '', t)
    t = re.sub(r'\s+(desc|asc)\s*$', '', t, flags=re.IGNORECASE)
    # 去掉包裹性括号：lower((name)) vs lower(name)
    while t.startswith('(') and t.endswith(')'):
        t = t[1:-1].strip()
    t = re.sub(r'\s+', ' ', t)
    return t.lower()


def db_index_columns(indexdef: str) -> set[str]:
    """从 CREATE INDEX ... USING x (cols) [INCLUDE (...)] [WHERE ...] 提取键列集。"""
    m = re.search(r'\((.*?)\)(?:\s+INCLUDE\s*\(.*?\))?(?:\s+WHERE.*)?$', indexdef, re.S)
    if not m:
        return set()
    inner = m.group(1)
    # 按顶层逗号切分（容忍 COALESCE(a,b) 表达式的内层逗号）
    parts, depth, cur = [], 0, ''
    for ch in inner:
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
        if ch == ',' and depth == 0:
            parts.append(cur)
            cur = ''
        else:
            cur += ch
    if cur.strip():
        parts.append(cur)
    result = set()
    for part in parts:
        p = part.strip()
        if not p:
            continue
        # 无表达式 → 取首 token（去掉 DESC/ASC 修饰）；有函数表达式 → 整段保留
        result.add(_norm_col(p.split(' ')[0] if '(' not in p else p))
    return result


def _unwrap_expression(expr):
    """解包 desc()/asc()/lower() 等一元包装，取底层列或文本。"""
    target = expr
    while hasattr(target, 'element'):
        target = target.element
    return target


def model_index_columns(index) -> set[str]:
    """从 ORM Index 提取键列名集。

    用 ``index.expressions``（而不是 ``index.columns``：后者不包含
    desc()/asc() 包装的表达式列）；一元包装解包到底层列名，
    忽略 DESC/ASC 修饰。
    """
    cols = set()
    for expr in getattr(index, 'expressions', None) or index.columns:
        target = _unwrap_expression(expr)
        name = getattr(target, 'name', None)
        if name is None:
            name = str(target).strip()
        cols.add(_norm_col(str(name)))
    return cols


def expected_constraint_index_names(metadata) -> set[tuple[str, str]]:
    """按 PG 自动命名规则收集约束索引名（不参与漂移判定）。

    - PrimaryKeyConstraint → ``<table>_pkey``
    - 列级 unique=True / 显式 UniqueConstraint → ``<table>_<col>_key``
    """
    names: set[tuple[str, str]] = set()
    for table in metadata.sorted_tables:
        names.add((table.name, f'{table.name}_pkey'))
        unique_cols = [c.name for c in table.columns if c.unique]
        for c in table.constraints:
            if c.__class__.__name__ == 'UniqueConstraint':
                for col in getattr(c, 'columns', []):
                    if col.name and col.name not in unique_cols:
                        unique_cols.append(col.name)
        for col in unique_cols:
            names.add((table.name, f'{table.name}_{col}_key'))
    return names


async def main() -> int:
    parser = argparse.ArgumentParser(description='ORM vs DB 索引结构对账（只读）')
    parser.add_argument('--dsn', default='', help='postgresql://user:pass@host:port/db')
    parser.add_argument('--table', default='', help='只比对指定表（调试用）')
    parser.add_argument('--out', default='', help='报告同时写入该文件（提权运行时捕获输出的通道）')
    args = parser.parse_args()

    cfg = load_env()
    dsn = args.dsn or (
        'postgresql://{user}:{pw}@{host}:{port}/{db}'.format(
            user=cfg.get('DB_USER', 'erp_app'), pw=cfg.get('DB_PASSWORD', ''),
            host=cfg.get('DB_HOST', '127.0.0.1'), port=cfg.get('DB_PORT', '5432'),
            db=cfg.get('DB_NAME', 'erp_system')))

    # ---- 模型侧（纯声明式 import，不触发 core.database 引擎副作用）----
    from fastapi_app.shared_models import Base

    tables = [t for t in Base.metadata.sorted_tables if not args.table or t.name == args.table]
    model_indexes: dict[tuple[str, str], object] = {}
    for table in tables:
        for idx in table.indexes:
            model_indexes[(table.name, idx.name)] = idx
    constraint_names = expected_constraint_index_names(Base.metadata)

    # ---- 数据库侧 ----
    conn = await asyncpg.connect(dsn=dsn, timeout=15)
    await conn.execute("SET default_transaction_read_only = on")
    rows = await conn.fetch(
        "SELECT tablename, indexname, indexdef FROM pg_indexes "
        "WHERE schemaname = 'public' ORDER BY tablename, indexname")
    is_super = await conn.fetchval("SELECT rolsuper FROM pg_roles WHERE rolname = current_user")
    await conn.close()

    db_indexes: dict[tuple[str, str], str] = {
        (r['tablename'], r['indexname']): r['indexdef'] for r in rows}

    # ---- 名字级比对（约束自动索引不参与判定）----
    model_keys = set(model_indexes)
    db_keys = set(db_indexes)
    model_only = sorted(k for k in model_keys - db_keys if k not in constraint_names)
    db_only = sorted(k for k in db_keys - model_keys if k not in constraint_names)

    # ---- 定义级比对（同名索引列集差异；含函数表达式的索引跳过——
    # 表达式的文本归一化不可靠（绑定占位符/括号形态），交给人工核对）----
    mismatches = []
    for key in sorted(model_keys & db_keys):
        mcols = model_index_columns(model_indexes[key])
        if any('(' in c or 'coalesce' in c for c in mcols):
            continue  # 表达式索引：签名不稳定，跳过
        dcols = db_index_columns(db_indexes[key])
        if mcols and dcols and mcols != dcols:
            mismatches.append((key, sorted(mcols), sorted(dcols)))

    # ---- 报告 ----
    out = []
    out.append('=== ORM vs DB 索引结构对账（只读） ===')
    db_name = cfg.get('DB_NAME', 'erp_system')
    out.append(f'比对对象: {db_name} | ORM 索引 {len(model_keys)} 个 | DB 索引 {len(db_keys)} 个 | 当前用户 superuser={is_super}')
    out.append('')
    out.append(f'--- MODEL_ONLY（模型声明但库里没有 = 幽灵索引，永不生效）{len(model_only)} 个 ---')
    for t, n in model_only:
        out.append(f'  {t:<30} {n}')
    out.append('')
    out.append(f'--- DB_ONLY（库里有但模型未声明）{len(db_only)} 个 ---')
    for t, n in db_only:
        out.append(f'  {t:<30} {n}')
    out.append('')
    out.append(f'--- COLUMN_MISMATCH（同名索引列集不同，高置信差异）{len(mismatches)} 个 ---')
    for (t, n), mc, dc in mismatches:
        out.append(f'  {t:<30} {n}')
        out.append('    model: ' + ', '.join(mc))
        out.append('    db   : ' + ', '.join(dc))
    print('\n'.join(out))

    drift = model_only or db_only or mismatches
    conclusion = '结论: %s' % ('发现漂移（见上）' if drift else '结构一致')
    print('\n' + conclusion)
    if args.out:
        Path(args.out).write_text('\n'.join(out) + '\n' + conclusion + '\n', encoding='utf-8')
    return 1 if drift else 0


if __name__ == '__main__':
    try:
        sys.exit(asyncio.run(main()))
    except Exception as exc:  # noqa: BLE001 - 诊断脚本：失败即报错退出
        print(f'对账失败: {exc!r}', file=sys.stderr)
        sys.exit(2)
