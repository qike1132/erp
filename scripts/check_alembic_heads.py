# scripts/check_alembic_heads.py
"""Alembic 迁移图门禁：单 head + root 数不增。

为什么需要它
------------
本仓库的迁移图**不是线性链**：99 个 revision 里有 4 个 root
（add_product_factory / add_product_price / add_pp_composite_idx /
pg_standalone_001）与 6 个 merge revision。多 root 本身是历史产物、可以接受，
但**新增第二个 head** 意味着 `alembic upgrade head` 会直接报
`Multiple head revisions are present`，生产升级即失败。

因此本门禁把「迁移图形状」也变成可回归的约束：
  - head 数必须恰好为 1；
  - root（base）数不得超过 EXPECTED_MAX_BASES（新增 root 需显式改这个常量，
    相当于一次有意识的评审动作）。

注意：解析必须走 alembic 的 ScriptDirectory，**不能用朴素 AST**。
只用 `ast.Assign` 找 revision/down_revision 会漏掉 `AnnAssign`
（`revision: str = ...`），实测会得出「5 roots / 4 heads / dangling
pg_standalone_003,007」的伪影。

用法:
    python scripts/check_alembic_heads.py

退出码:
    0: 迁移图正常（单 head 且 root 数未超限）
    1: 迁移图异常
    2: 环境异常（alembic 不可用 / 无法解析迁移目录）
"""

from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS_DIR = PROJECT_ROOT / "migrations"

# 历史遗留的 root 数。新增 root 会让 alembic 产生新的独立分支，
# 必须连同 migrations/versions/README.md 的迁移图一起评审后上调。
EXPECTED_MAX_BASES = 4


def load_script_directory():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    return ScriptDirectory.from_config(cfg)


def main() -> int:
    parser = argparse.ArgumentParser(description="校验 alembic 迁移图形状")
    parser.parse_args()

    if not MIGRATIONS_DIR.is_dir():
        print(f"[ERROR] 未找到迁移目录：{MIGRATIONS_DIR}")
        return 2

    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))

    try:
        script = load_script_directory()
        heads = sorted(script.get_heads())
        bases = sorted(script.get_bases())
        revisions = list(script.walk_revisions())
    except ImportError as exc:
        print(f"[ERROR] alembic 不可用：{exc}")
        return 2
    except Exception as exc:  # noqa: BLE001 - 解析失败一律保守失败
        print(f"[ERROR] 解析迁移目录失败：{exc!r}")
        return 2

    problems: list[str] = []
    if len(heads) != 1:
        problems.append(f"head 数 = {len(heads)}（必须为 1）：{heads}")
    if len(bases) > EXPECTED_MAX_BASES:
        problems.append(
            f"root(base) 数 = {len(bases)} 超过上限 {EXPECTED_MAX_BASES}：{bases}"
        )

    summary = (
        f"revisions={len(revisions)} heads={len(heads)} bases={len(bases)}"
    )
    if not problems:
        print(f"[PASS] 迁移图正常（{summary}）")
        return 0

    print(f"[FAIL] 迁移图异常：发现 {len(problems)} 处（{summary}）：\n")
    for item in problems:
        print(f"  - {item}")
    print()
    print("修复：合并分支需新增 merge revision；详见 migrations/versions/README.md")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
