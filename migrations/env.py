import logging
from logging.config import fileConfig

from alembic import context
from sqlalchemy import text

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
if config.config_file_name:
    fileConfig(config.config_file_name)
logger = logging.getLogger('alembic.env')


def get_engine():
    """获取同步数据库引擎（psycopg3 驱动，供 Alembic 迁移使用）"""
    from fastapi_app.core.database import get_sync_engine
    return get_sync_engine()


def get_engine_url():
    try:
        return get_engine().url.render_as_string(hide_password=False).replace(
            '%', '%%')
    except AttributeError:
        return str(get_engine().url).replace('%', '%%')


# add your model's MetaData object here
# for 'autogenerate' support
from fastapi_app.shared_models import Base
config.set_main_option('sqlalchemy.url', get_engine_url())
target_metadata = Base.metadata

# 自动检测数据库类型并选择正确的 Alembic 迁移分支
# PostgreSQL: 使用 pg_standalone 分支（全新部署）或 MySQL 链 head（已迁移环境）
# 避免多 head 共存时 `alembic upgrade head` 报错
import os
_db_type = os.getenv('DB_TYPE', 'postgresql').lower()
if _db_type == 'postgresql':
    config.set_main_option('version_path', 'migrations/versions')


def run_migrations_offline():
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well. By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url, target_metadata=target_metadata, literal_binds=True
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """

    # this callback is used to prevent an auto-migration from being generated
    # when there are no changes to the schema
    # reference: http://alembic.zzzcomputing.com/en/latest/cookbook.html
    def process_revision_directives(context, revision, directives):
        if getattr(config.cmd_opts, 'autogenerate', False):
            script = directives[0]
            if script.upgrade_ops.is_empty():
                directives[:] = []
                logger.info('No changes in schema detected.')

    connectable = get_engine()

    # 自动检测 PG 并选择 pg_standalone 分支（新环境）
    # 对于已迁移环境，数据库已 stamp 到 MySQL 链 head，不会重复执行
    version_table = config.get_main_option("version_table") or "alembic_version"

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            process_revision_directives=process_revision_directives,
            version_table=version_table,
        )

        # PG 新环境：如果 alembic_version 表不存在，自动使用 pg_standalone 分支
        if _db_type == 'postgresql':
            try:
                result = connection.execute(text(
                    "SELECT COUNT(*) FROM information_schema.tables "
                    "WHERE table_name = :tbl"
                ), {"tbl": version_table})
                if result.scalar() == 0:
                    logger.info('检测到全新 PostgreSQL 数据库，使用 pg_standalone 分支')
                    config.set_main_option('version_path', 'migrations/versions')
            except Exception:
                pass

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
