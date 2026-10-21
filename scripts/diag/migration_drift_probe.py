"""迁移漂移探针（只读）：数据库当前停在哪个 revision、离脚本 head 还差哪几条。

为什么需要这个脚本
------------------
本仓**部署流程不会自动跑迁移**（`start.py` / `prod_runner.py` 零 alembic 命中），所以
「代码已到 103、库还在 099」这种状态可以无限期存在且不报错——2026-10-17 审计的待核实 #9
正是卡在这里：疑点没有静态答案，只能问库；而问一次要临时写脚本、临时找可读的 `.env`，
于是结论一直挂着「待运维确认」。本脚本把它变成一条可重复命令。

判活三态（同 `scripts/diag/runtime_mode_probe.py` 的铁律）：**读不到不得折算成「最新」**。
    up_to_date  库已在 head
    behind      库落后，pending 给出待应用顺序（旧→新）
    unknown     库里的 version_num 不在迁移图里（手工 stamp / ghost），或版本表为空
    error       连不上库 / 迁移图多 head——探针自身失败必须显式报，不得静默降级

只读纪律：全程 SELECT，不建/不删任何东西，不打印 DSN 与口令。

用法：
    python scripts/diag/migration_drift_probe.py            # 人读摘要
    python scripts/diag/migration_drift_probe.py --json     # 纯 JSON（供巡检采集）

运行前提：根 `.env` 的 ACL 只授予 Administrators/SYSTEM，非提权进程读不到 → 本探针会报
`error: PermissionError '.env'`（**不会**折算成「最新」）。请在提权 shell 里跑。

退出码：0 = up_to_date；1 = behind / unknown；2 = error。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

STATUS_UP_TO_DATE = "up_to_date"
STATUS_BEHIND = "behind"
STATUS_UNKNOWN = "unknown"
STATUS_ERROR = "error"


def _ancestors(rev: str, parents: Mapping[str, tuple[str, ...]]) -> set[str]:
    """rev 的全部祖先（不含自身），沿 down_revision 向上闭包；merge 的多父都走。"""
    seen: set[str] = set()
    stack = list(parents.get(rev, ()))
    while stack:
        cur = stack.pop()
        if cur not in seen:
            seen.add(cur)
            stack.extend(parents.get(cur, ()))
    return seen


def _order_old_to_new(revs: Iterable[str], parents: Mapping[str, tuple[str, ...]]) -> list[str]:
    """按「祖先在前」拓扑排序，使 pending 可直接顺序 `upgrade`。"""
    wanted = set(revs)
    emitted: list[str] = []
    done: set[str] = set()

    def emit(rev: str) -> None:
        if rev in done:
            return
        for up in sorted(parents.get(rev, ())):
            emit(up)  # 图是 DAG 且此处规模 <200，递归深度远小于栈限
        if rev in wanted:
            emitted.append(rev)
        done.add(rev)

    for rev in sorted(wanted):
        emit(rev)
    return emitted


def classify_drift(
    db_versions: Sequence[str],
    head: str,
    parents: Mapping[str, tuple[str, ...]],
) -> tuple[str, list[str], list[str], str | None]:
    """判定库相对 head 的位置，返回 (status, pending 旧→新, 图外版本号, 说明)。

    判据不是「version_num 等不等于 head」——merge revision 之下整条链都算已应用，
    只看单点会把「已 stamp 到 merge 点」误判成落后。做法：取 head 的祖先闭包 ∪ {head}
    作为图内全集，减去 db_versions 及其祖先闭包（=已应用），差集即待应用集。
    """
    if not db_versions:
        return STATUS_UNKNOWN, [], [], "alembic_version 为空或表不存在：库未 stamp，无法判定位置"

    graph = {head, *_ancestors(head, parents)}
    unrecognized = sorted(v for v in db_versions if v not in graph)
    applied: set[str] = set()
    for ver in db_versions:
        if ver in graph:
            applied |= {ver, *_ancestors(ver, parents)}

    pending = _order_old_to_new(graph - applied, parents)
    if unrecognized:
        # 图里找不到库声明的版本：可能手工 stamp 了不存在的 revision，也可能脚本被回退过。
        # 两种都不能报「最新」，pending 也不保证可直接顺序执行。
        return STATUS_UNKNOWN, pending, unrecognized, "库声明的版本号不在迁移图中（stamp/ghost）"
    if not pending:
        return STATUS_UP_TO_DATE, [], [], None
    return STATUS_BEHIND, pending, [], None


def load_graph(root: str) -> tuple[list[str], dict[str, tuple[str, ...]]]:
    """从 alembic 脚本目录读 (heads, revision→down_revision 元组)。

    必须走 ScriptDirectory：朴素 AST 会漏 `AnnAssign`（`revision: str = ...`），
    实测得出「4 heads / 5 roots」伪影——见 `scripts/check_alembic_heads.py` 头注。
    """
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    cfg = Config(os.path.join(root, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(root, "migrations"))
    sd = ScriptDirectory.from_config(cfg)
    parents: dict[str, tuple[str, ...]] = {}
    for script in sd.walk_revisions():
        down = script.down_revision
        parents[script.revision] = () if down is None else (down if isinstance(down, tuple) else (down,))
    return sorted(sd.get_heads()), parents


def query_db(url: str) -> tuple[str, list[str]]:
    """只读查询：(current_database, alembic_version 去重行)。表不存在时返回空列表。"""
    from sqlalchemy import create_engine, text
    from sqlalchemy.exc import ProgrammingError

    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            dbname = str(conn.execute(text("SELECT current_database()")).scalar())
            try:
                rows = conn.execute(text("SELECT version_num FROM alembic_version")).all()
            except ProgrammingError:
                rows = []
            return dbname, sorted({str(r[0]) for r in rows})
    finally:
        engine.dispose()


def build_report(root: str, db_url: str) -> tuple[int, dict[str, Any]]:
    heads, parents = load_graph(root)
    dbname, db_versions = query_db(db_url)
    base: dict[str, Any] = {"database": dbname, "db_versions": db_versions}

    if len(heads) != 1:
        base.update(status=STATUS_ERROR, reason=f"迁移图有 {len(heads)} 个 head，无唯一终点可判定")
        return 2, base

    head = heads[0]
    status, pending, unrecognized, reason = classify_drift(db_versions, head, parents)
    base.update(
        status=status,
        script_head=head,
        pending=pending,
        unrecognized=unrecognized,
        **({"reason": reason} if reason else {}),
    )
    return (0 if status == STATUS_UP_TO_DATE else 1), base


def _print_human(report: dict[str, Any]) -> None:
    print(f"database           = {report.get('database', '(未取到)')}")
    print(f"script head        = {report.get('script_head', '(未判定)')}")
    print(f"db alembic_version = {report.get('db_versions') or '(空/表不存在/未取到)'}")
    print(f"status             = {report.get('status')}")
    if report.get("reason"):
        print(f"reason             = {report['reason']}")
    if report.get("pending"):
        print(f"pending（{len(report['pending'])} 条，应用顺序 旧→新）：")
        for rev in report["pending"]:
            print(f"  - {rev}")
    if report.get("unrecognized"):
        print(f"⚠️ 图外版本号: {report['unrecognized']}")


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="迁移位置只读探针（不写任何东西）")
    parser.add_argument("--json", action="store_true", help="输出纯 JSON")
    args = parser.parse_args(list(argv) if argv is not None else None)

    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    try:
        from fastapi_app.core.config import settings

        code, report = build_report(root, settings.DATABASE_URL)
    except Exception as exc:  # noqa: BLE001 — 探针失败必须显式 error，不得退化成「最新」
        report = {"status": STATUS_ERROR, "reason": f"{type(exc).__name__}: {exc}"}
        code = 2

    if args.json:
        print(json.dumps(report, ensure_ascii=False))
    else:
        _print_human(report)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
