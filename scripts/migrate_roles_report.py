"""角色归并**只读干跑报告**（迁移 045 前置核对，绝不写库）。

用途
----
在生产机执行 `alembic upgrade pg_standalone_045_global_role` **之前**运行本脚本，
人工核对「存量角色将被如何上卷/归并」，把 S2（误并）风险从「事后发现」前移到
「事前确认」（对应 PRD Q-04 / REQ-P1-05）。

本脚本**保证只读**：连接上第一句即 `SET TRANSACTION READ ONLY`，且脚本内只发
SELECT，不执行任何 DDL/DML、不 commit。因此可安全对生产库运行。

输出内容
--------
- **硬性前置条件（BLOCKER）**：`btrim(role_name)` 为空的行数及其样本。回填 SQL 带
  `WHERE btrim(role_name) <> ''`，这些行**无法回填** `global_role_id`，会以 NULL 状态
  存活到 `_tighten_constraints` 的 `SET NOT NULL` → 迁移中途失败。此项非 0 时脚本
  以返回码 **2** 退出（便于脚本化闸门），必须先清理才能迁移。
- 归并组明细：同一产品下 `lower(btrim(role_name))` 相同的多行 `product_role`
  （迁移后会合并为 1 行）——列出 product_id、角色名、将保留的行 id、将删除的行 id，
  以及这些行在三张物料表上的行数（M4：归并若撞唯一约束是关键风险点）。
- 全局角色上卷预演：按 `lower(btrim(role_name))` 分组，多少产品共用、多少 role 行。
- 影响面：涉及的产品数、将新建的全局角色数、按分类的物料行数基线。

`--verify`：迁移后幂等/守恒校验——检查 `global_role_id` 是否已全部回填、
是否仍存在同产品同全局角色的重复组。返回码非 0 表示校验未通过。

用法
----
    python scripts/migrate_roles_report.py                 # 迁移前干跑（有 BLOCKER 则退出码 2）
    python scripts/migrate_roles_report.py --json          # 机器可读
    python scripts/migrate_roles_report.py --verify        # 迁移后校验
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from sqlalchemy import text

from fastapi_app.core.database import get_sync_engine

# 物料分类 → 物理表（读取基线行数用）
_MATERIAL_TABLES = (
    ('filling', 'product_material'),
    ('fabric', 'product_fabric'),
    ('accessory', 'product_accessory'),
)

# 干跑发现硬性前置条件未满足时的返回码（区别于 --verify 的 1）
EXIT_BLOCKED = 2


def _has_column(conn, table: str, column: str) -> bool:
    """判断表上是否存在指定列（用于区分迁移前/后）。"""
    row = conn.execute(
        text(
            'SELECT 1 FROM information_schema.columns '
            'WHERE table_schema = current_schema() '
            'AND table_name = :t AND column_name = :c LIMIT 1'
        ),
        {'t': table, 'c': column},
    ).first()
    return row is not None


def collect_unbackfillable_rows(conn) -> dict:
    """统计**无法回填** `global_role_id` 的行（空白 / NULL 的 role_name）。

    回填 SQL（迁移 045 `_backfill_global_role_id`）带 `WHERE btrim(role_name) <> ''`，
    因此这些行迁移后仍是 NULL，会令随后的 `SET NOT NULL` 直接抛裸 Postgres 错。
    这是迁移前**必须清零**的硬性前置条件——本报告的核心闸门。
    """
    rows = conn.execute(
        text(
            'SELECT id, product_id, role_name FROM product_role '
            "WHERE btrim(role_name) = '' OR role_name IS NULL "
            'ORDER BY product_id, id'
        )
    ).mappings().all()
    return {'count': len(rows), 'sample': [dict(r) for r in rows[:20]]}


def collect_merge_groups(conn) -> list[dict]:
    """归并组明细：同产品下 role_name（trim+lower）相同的多行 product_role。"""
    rows = conn.execute(
        text(
            'SELECT product_id, lower(btrim(role_name)) AS key, '
            'count(*) AS n, array_agg(id ORDER BY id) AS ids, '
            'array_agg(role_name ORDER BY id) AS names '
            'FROM product_role '
            'GROUP BY product_id, lower(btrim(role_name)) '
            'HAVING count(*) > 1 '
            'ORDER BY product_id, key'
        )
    ).mappings().all()
    groups = []
    for row in rows:
        ids = list(row['ids'])
        keep_id = min(ids)
        delete_ids = [i for i in ids if i != keep_id]
        groups.append(
            {
                'product_id': row['product_id'],
                'role_key': row['key'],
                'role_names': list(row['names']),
                'keep_id': keep_id,
                'delete_ids': delete_ids,
                'material_rows': _count_material_rows_for_roles(conn, ids),
            }
        )
    return groups


def _count_material_rows_for_roles(conn, role_ids: list[int]) -> dict:
    """统计归属给定 product_role 行集合的物料行数（M4 归并冲突预判）。"""
    counts: dict[str, int] = {}
    for category, table in _MATERIAL_TABLES:
        row = conn.execute(
            text(f'SELECT count(*) FROM {table} WHERE role_id = ANY(:ids)'),
            {'ids': role_ids},
        ).first()
        counts[category] = int(row[0]) if row else 0
    return counts


def collect_role_census(conn) -> list[dict]:
    """全局角色上卷预演：按 trim+lower 名称分组，统计产品数与 role 行数。"""
    rows = conn.execute(
        text(
            'SELECT lower(btrim(role_name)) AS key, '
            'min(btrim(role_name)) AS sample_name, '
            'count(DISTINCT product_id) AS product_count, '
            'count(*) AS role_rows '
            'FROM product_role WHERE btrim(role_name) <> \'\' '
            'GROUP BY 1 ORDER BY 1'
        )
    ).mappings().all()
    return [dict(r) for r in rows]


def collect_baseline_counts(conn) -> dict:
    """按分类统计三张物料表行数基线（守恒校验用）。"""
    counts = {}
    for category, table in _MATERIAL_TABLES:
        row = conn.execute(text(f'SELECT count(*) FROM {table}')).first()
        counts[category] = int(row[0]) if row else 0
    return counts


def collect_report(conn) -> dict:
    """汇总干跑报告（全部只读）。"""
    return {
        'migrated': _has_column(conn, 'product_role', 'global_role_id'),
        'product_role_total': int(conn.execute(text('SELECT count(*) FROM product_role')).scalar() or 0),
        'affected_product_count': int(
            conn.execute(text('SELECT count(DISTINCT product_id) FROM product_role')).scalar() or 0
        ),
        'unbackfillable_rows': collect_unbackfillable_rows(conn),
        'role_census': collect_role_census(conn),
        'merge_groups': collect_merge_groups(conn),
        'baseline_counts': collect_baseline_counts(conn),
    }


def verify(conn, report: dict) -> tuple[bool, list[str]]:
    """迁移后幂等/守恒校验。返回 (是否通过, 问题清单)。"""
    problems: list[str] = []
    if not report['migrated']:
        problems.append('global_role_id 列不存在：迁移 045 尚未执行，--verify 无意义')
        return False, problems

    null_count = int(
        conn.execute(
            text('SELECT count(*) FROM product_role WHERE global_role_id IS NULL')
        ).scalar() or 0
    )
    if null_count:
        problems.append(f'存在 {null_count} 行 product_role.global_role_id 仍为 NULL（回填不完整）')

    dup_count = int(
        conn.execute(
            text(
                'SELECT count(*) FROM ('
                'SELECT product_id, global_role_id FROM product_role '
                'WHERE global_role_id IS NOT NULL '
                'GROUP BY product_id, global_role_id HAVING count(*) > 1) dup'
            )
        ).scalar() or 0
    )
    if dup_count:
        problems.append(f'存在 {dup_count} 组同产品同全局角色的重复关联（归并不彻底）')

    return (not problems), problems


def render(report: dict) -> None:
    """人类可读输出。"""
    print('=' * 72)
    print('角色归并干跑报告（只读，未修改任何数据）')
    print('=' * 72)
    print(f"迁移状态: {'已执行(global_role_id 存在)' if report['migrated'] else '未执行'}")
    print(f"product_role 总行数: {report['product_role_total']}")
    print(f"涉及产品数: {report['affected_product_count']}")
    print()

    # 硬性前置条件：不满足则 SET NOT NULL 必然失败
    blockers = report['unbackfillable_rows']
    print('-' * 72)
    if blockers['count']:
        print(
            f"[BLOCKER] 存在 {blockers['count']} 行空白/NULL role_name，"
            '无法回填 global_role_id —— SET NOT NULL 会失败，必须先清理：'
        )
        for r in blockers['sample']:
            print(f"  - id={r['id']} product_id={r['product_id']} role_name={r['role_name']!r}")
    else:
        print('[OK] 无空白/NULL role_name 行：SET NOT NULL 前置条件成立')
    print('-' * 72)
    print()

    print(f"按分类物料行数基线: {report['baseline_counts']}")
    print()
    print(f"全局角色上卷预演（{len(report['role_census'])} 个名称分组，"
          f"其中跨产品复用 {sum(1 for c in report['role_census'] if c['product_count'] > 1)} 个）:")
    for c in report['role_census']:
        print(f"  - {c['sample_name']!r}: 产品数 {c['product_count']}, role 行数 {c['role_rows']}")
    print()
    print(f"将归并的重复角色组（同产品同名多行）: {len(report['merge_groups'])} 组")
    for g in report['merge_groups']:
        print(
            f"  - 产品 {g['product_id']} 角色 {g['role_names']}: "
            f"保留 id={g['keep_id']}, 删除 id={g['delete_ids']}, "
            f"物料行 {g['material_rows']}"
        )
    print()
    print('提示：确认无误后，在低峰窗口按 docs/bom-multi-role/02 第 10 节执行迁移。')


def main() -> int:
    parser = argparse.ArgumentParser(description='角色归并只读干跑报告（绝不写库）')
    parser.add_argument('--json', action='store_true', help='输出 JSON')
    parser.add_argument('--verify', action='store_true', help='迁移后幂等/守恒校验')
    args = parser.parse_args()

    engine = get_sync_engine()
    with engine.connect() as conn:
        # 只读保护：本连接任何写操作都会被 PostgreSQL 拒绝
        conn.execute(text('SET TRANSACTION READ ONLY'))
        report = collect_report(conn)
        if args.json:
            payload = {'report': report}
            if args.verify:
                ok, problems = verify(conn, report)
                payload['verify'] = {'ok': ok, 'problems': problems}
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            render(report)
            if args.verify:
                ok, problems = verify(conn, report)
                print()
                if ok:
                    print('[VERIFY OK] 回填完整、无重复关联（幂等/守恒校验通过）')
                else:
                    print('[VERIFY FAIL] 校验未通过:')
                    for p in problems:
                        print(f'  - {p}')
        if args.verify:
            ok, _ = verify(conn, report)
            return 0 if ok else 1
        # 迁移前干跑：硬性前置条件未满足 → 非 0（脚本化闸门用），阻止带着数据问题迁移
        if report['unbackfillable_rows']['count']:
            if not args.json:
                print()
                print(
                    f"[EXIT {EXIT_BLOCKED}] 前置条件未满足：请先清理上列空白 role_name 行，"
                    '否则迁移 045 会在 SET NOT NULL 处失败。'
                )
            return EXIT_BLOCKED
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
