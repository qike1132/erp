import logging
from logging.config import fileConfig

from alembic import context
from sqlalchemy import text as sa_text

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


# Alembic 默认把版本表的 version_num 建成 VARCHAR(32)，而本仓库有 34 个 revision id
# 超过 32 字符（最长 53，如 pg_standalone_018_purchase_plan_unique_month_customer）。
# 空库上这会在写入版本号时以 StringDataRightTruncation 失败，导致 upgrade head 无法收尾，
# 故此处预先建表/加宽到 VARCHAR(100)（与现网 erp_system 的实际列宽一致）。
_VERSION_TABLE_DDL = (
    'CREATE TABLE IF NOT EXISTS {table} ('
    'version_num VARCHAR(100) NOT NULL, '
    'CONSTRAINT {table}_pkc PRIMARY KEY (version_num))'
)
_VERSION_TABLE_WIDTH_DDL = 'ALTER TABLE {table} ALTER COLUMN version_num TYPE VARCHAR(100)'


def ensure_version_table_width(connection, version_table: str) -> None:
    """确保 alembic 版本表容得下最长 revision id。幂等，无权限/只读时静默跳过。"""
    try:
        connection.execute(sa_text(_VERSION_TABLE_DDL.format(table=version_table)))
        connection.execute(sa_text(_VERSION_TABLE_WIDTH_DDL.format(table=version_table)))
    except Exception:
        logger.debug('跳过 alembic 版本表加宽（无权限或只读连接）', exc_info=True)


# add your model's MetaData object here
# for 'autogenerate' support
from fastapi_app.shared_models import Base

config.set_main_option('sqlalchemy.url', get_engine_url())
target_metadata = Base.metadata




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
    version_table = config.get_main_option("version_table") or "alembic_version"

    with connectable.connect() as connection:
        # 版本表必须在 alembic 首次写入前就够宽，否则超长 revision id 会以
        # StringDataRightTruncation 失败（见上方 _VERSION_TABLE_DDL 注释）
        ensure_version_table_width(connection, version_table)
        connection.commit()

        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            process_revision_directives=process_revision_directives,
            version_table=version_table,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
