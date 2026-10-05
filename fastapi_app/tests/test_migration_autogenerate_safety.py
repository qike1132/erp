"""迁移破坏性 DDL 守卫（棘轮）。

防止「对生产库误跑 `alembic revision --autogenerate`」把生产库的历史堆积
（库有、模型无的索引/表/列）生成成一批 DROP 语句混进仓库。

两道检查：
1. `test_no_new_destructive_migration_statements`：`migrations/versions/` 下
   任何**新增**的破坏性 DDL（DROP TABLE/INDEX/COLUMN/CONSTRAINT 或 DROP 裸 SQL）
   都不在基线里 -> 失败，必须先人工审阅再 `python -m migrations._destructive_scan
   --update-baseline`。
2. `test_readme_documents_autogenerate_prohibition`：`migrations/README` 必须保留
   显式的禁令，防止文档被静默删掉后无人知晓。

背景见 `migrations/README` 与 `docs/audit-round2/03-data-layer.md`。
"""

from pathlib import Path

from migrations import _destructive_scan as scan

_REPO_ROOT = Path(__file__).resolve().parents[2]
_README = _REPO_ROOT / "migrations" / "README"


def test_no_new_destructive_migration_statements():
    current = scan.scan_versions_dir()
    baseline = scan.load_baseline()
    new_ops = scan.find_new_destructive_ops(current, baseline)

    assert not new_ops, (
        "检测到迁移文件里新增的破坏性 DDL（不在基线中）：\n"
        + "\n".join(
            f"  {f}\n" + "\n".join(f"     - {s}" for s in sigs)
            for f, sigs in new_ops.items()
        )
        + "\n\n这通常意味着有人对非空库（尤其是生产库）跑了 autogenerate。\n"
        "请先逐条人工审阅；确认无误后再执行：\n"
        "  python -m migrations._destructive_scan --update-baseline\n"
        "并在提交信息里说明为什么这些破坏性语句是安全的。"
    )


def test_readme_documents_autogenerate_prohibition():
    assert _README.exists(), "migrations/README 不存在"
    text = _README.read_text(encoding="utf-8")
    assert "禁止对生产库运行 alembic revision --autogenerate" in text, (
        "migrations/README 缺少 autogenerate 禁令，请勿删除该警告。"
    )
