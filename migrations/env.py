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


# ============================================================================
# 库独有遗留对象白名单 —— include_object 回调
#
# 生产库因历史手工/早期迁移留下了若干「只存在于库、模型与迁移链都没有」的对象。
# autogenerate 会把它判定为「应删除」，于是 alembic check 长期报噪音，且
# `alembic revision --autogenerate` 会生成 DROP TABLE / DROP INDEX / DROP COLUMN
# 的破坏性 DDL（涉及 trigram 搜索索引与审计索引，误删会掉性能）。本回调把这些
# 对象排除出 check 与 autogenerate 的比较。
#
# 这是**显式白名单**（逐个点名），不是「凡模型没有就忽略」——后者会永久掩盖将来
# 真实的漂移（例如有人手建了表却忘了写迁移）。名字命中即同时豁免「删」与「建」
# 两个方向：库独有对象本就没有「建」侧；对 054 迁移因 create_index_if_absent 跳过
# 而定义分叉的同名索引，两向同时豁免可一并避免产出注定因同名冲突失败的 CREATE。
#
# 本白名单只改比较逻辑，不改动/删除生产库任何对象。
# ============================================================================

# 库独有表：当前为空。
#   app_version                  —— 已由 fastapi_app/shared_models/app_version.py 纳入 ORM
#                                   （配套迁移 pg_standalone_081），不再是漂移项。
#   product_image_orphan_backup  —— 已由迁移 pg_standalone_082 删除（该迁移应用后生效）。
_IGNORED_DB_ONLY_TABLES: set[str] = set()

# 库独有索引（历史迁移所建，模型未声明；多为搜索/审计/覆盖索引，误删会掉性能）：
# 注：idx_app_version_platform_code 已随 app_version 纳入 ORM（迁移 081），故移出白名单。
#     idx_stockout_no_stockin / idx_order_date_id_desc 已纳入 ORM（迁移 083），故移出白名单。
_IGNORED_DB_ONLY_INDEXES = {
    'idx_csfv_created_at',             # 054 建；生产同名旧索引先存在 → 新定义被跳过
    'idx_csfv_status',                 # 历史迁移所建
    'idx_csp_role_part_version',       # 054 建 unique；生产同名旧索引为 non-unique
    'idx_inventory_log_product_time',  # 待迁移 084 改名为 ..._date 后即可移出
    'idx_material_reg_date',           # 历史迁移所建（生产定义与模型分叉）
    'idx_material_reg_supplier',       # 历史迁移所建（生产在 supplier_name，模型在 supplier_id）
    'idx_stockout_has_stockin',        # 待迁移 084 删除后即可移出
    'idx_stockout_order_stockin',      # 待迁移 084 删除后即可移出
}

# 库独有列（模型未声明）：按「表 → 列名」精确匹配，避免与其它表上的同名列
# （如 status 在十余张表都存在）互相污染。
_IGNORED_DB_ONLY_COLUMNS = {
    'customer_sampling_fabric_version': {
        'status',
        'version_label',
        'confirmed_at',
        'confirmed_by',
    },
}


def include_object(object, name, type_, reflected, compare_to):
    """Alembic 比较钩子：返回 False 表示该对象不参与 check / autogenerate 比较。

    仅按上方显式白名单放行；未命中者一律返回 True，保持正常漂移可见。
    """
    if type_ == 'table':
        return name not in _IGNORED_DB_ONLY_TABLES
    if type_ == 'index':
        return name not in _IGNORED_DB_ONLY_INDEXES
    if type_ == 'column':
        table_name = getattr(getattr(object, 'table', None), 'name', None)
        return name not in _IGNORED_DB_ONLY_COLUMNS.get(table_name, ())
    return True


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
        url=url, target_metadata=target_metadata, literal_binds=True,
        include_object=include_object,
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
            include_object=include_object,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
