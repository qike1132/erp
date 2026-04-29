"""pg_standalone_005_add_pgaudit

Revision ID: pg_standalone_005
Revises: pg_standalone_004
Create Date: 2026-04-27

启用 PostgreSQL pgaudit 扩展，实现数据库级审计日志。
审计日志独立于应用层 InventoryLog，DBA 可独立审计。

注意：Windows 上 pgaudit 需要从源码编译，若未安装则跳过。
已配置 PostgreSQL 内置 log_statement='mod' 作为替代审计方案。
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'pg_standalone_005'
down_revision = 'pg_standalone_004'
branch_labels = ()
depends_on = None


def upgrade() -> None:
    # pgaudit 扩展在 Windows PostgreSQL 18 上未预装，需要从源码编译。
    # 当前使用 PostgreSQL 内置 log_statement='mod' 作为替代审计方案
    # （已在 postgresql.auto.conf 中配置 log_statement, log_connections, log_disconnections）
    #
    # 若将来安装了 pgaudit，取消下面的注释并重启 PostgreSQL：
    # op.execute("CREATE EXTENSION IF NOT EXISTS pgaudit SCHEMA public")
    pass


def downgrade() -> None:
    pass
