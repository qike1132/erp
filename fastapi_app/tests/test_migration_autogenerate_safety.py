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

import pytest

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


def test_fstring_raw_sql_drop_is_detected():
    """P1-07：f-string 拼接的裸 SQL DROP 必须被扫描器识别（原实现只认字面量）。"""
    source = (
        "def upgrade():\n"
        "    op.execute(sa.text(f'DROP INDEX IF EXISTS {name}'))\n"
    )
    assert scan.scan_source(source) == ["execute:DROP INDEX IF EXISTS {name}"]


# ---------------------------------------------------------------------------
# 2026-10-18 OCR 评审：env.py 的版本表加宽兜底不得吞掉真正的错误
# ---------------------------------------------------------------------------

def _wrap(sqlstate: str) -> Exception:
    """按真实驱动行为包一层：psycopg 异常带 .sqlstate，SQLAlchemy 再包成 DBAPIError。"""
    import psycopg
    from sqlalchemy.exc import ProgrammingError

    orig = psycopg.errors.lookup(sqlstate)
    return ProgrammingError('CREATE TABLE IF NOT EXISTS alembic_version ...', {}, orig)


class TestVersionTableWidthSwallowPolicy:
    """只对「预期内」失败静默（无权限 / 只读连接），其余一律抛出。

    历史写法按异常类捕获（先是裸 `except Exception`，后收窄为
    `(SQLAlchemyError, OSError)`），两者都达不到目的——SQL 语法错是
    `ProgrammingError`，正是 `SQLAlchemyError` 的子类，照吞不误。一旦 DDL
    写错，症状是「加宽静默没生效」，排查时看不到任何报错。
    """

    def _call(self, exc: Exception) -> None:
        from unittest.mock import MagicMock

        # 2026-10-18：加宽逻辑已抽到 migrations/_version_table_width.py
        # （migrations/env.py 模块级依赖 alembic.context，不能被单测直接 import）。
        from migrations._version_table_width import ensure_version_table_width

        conn = MagicMock()
        conn.execute.side_effect = exc
        ensure_version_table_width(conn, 'alembic_version')

    def test_insufficient_privilege_is_swallowed(self) -> None:
        # 42501：无建表/改列权限，本函数本就是尽力而为的幂等预处理
        self._call(_wrap('42501'))

    def test_read_only_transaction_is_swallowed(self) -> None:
        # 25006：连到 standby 等只读连接
        self._call(_wrap('25006'))

    def test_syntax_error_propagates(self) -> None:
        # 42601：DDL 写错必须炸出来，不能被静默吞掉
        with pytest.raises(Exception, match='alembic_version'):
            self._call(_wrap('42601'))

    def test_connection_error_propagates(self) -> None:
        from sqlalchemy.exc import OperationalError

        with pytest.raises(OperationalError):
            self._call(OperationalError('SELECT 1', {}, RuntimeError('connection lost')))
