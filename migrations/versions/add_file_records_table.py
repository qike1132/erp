"""
add file_records table

P2-1: static/uploads 迁移至对象存储，数据库仅存元数据
"""
import sqlalchemy as sa
from alembic import op

from migrations._legacy_base_guard import (
    base_schema_absent,
    create_index_if_columns_exist,
)

# revision identifiers, used by Alembic.
revision = 'add_file_records_table'
down_revision = 'merge_resolve_all_heads'
branch_labels = None
depends_on = None

def upgrade():
    # 空库守卫：pg_standalone_001 尚未建出基础 schema 时整条增量迁移空转。
    # 判据要求 product / customer 同时缺失，遗留库与已建库一律照常执行。
    if base_schema_absent():
        return
    op.create_table(
        'file_records',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('original_filename', sa.String(length=255), nullable=False, comment='原始文件名'),
        sa.Column('storage_key', sa.String(length=255), nullable=False, comment='对象存储 key 或本地相对路径'),
        sa.Column('bucket', sa.String(length=64), nullable=False, server_default='erp-uploads', comment='对象存储 bucket'),
        sa.Column('storage_type', sa.String(length=20), nullable=False, server_default='local', comment='存储后端: local/s3'),
        sa.Column('size', sa.Integer(), nullable=False, server_default='0', comment='文件大小(字节)'),
        sa.Column('content_type', sa.String(length=128), nullable=True, comment='文件 MIME 类型'),
        sa.Column('uploader_id', sa.Integer(), nullable=True, comment='上传用户ID'),
        sa.Column('extra', sa.Text(), nullable=True, comment='额外 JSON 元数据'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()'), comment='创建时间'),
        sa.ForeignKeyConstraint(['uploader_id'], ['user.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    create_index_if_columns_exist('idx_file_record_uploader', 'file_records', ['uploader_id'])
    create_index_if_columns_exist('idx_file_record_storage_key', 'file_records', ['storage_key'])
    create_index_if_columns_exist('idx_file_record_created_at', 'file_records', ['created_at'])

def downgrade():
    # 空库守卫：pg_standalone_001 尚未建出基础 schema 时整条增量迁移空转。
    # 判据要求 product / customer 同时缺失，遗留库与已建库一律照常执行。
    if base_schema_absent():
        return
    op.drop_index('idx_file_record_created_at', table_name='file_records', if_exists=True)
    op.drop_index('idx_file_record_storage_key', table_name='file_records', if_exists=True)
    op.drop_index('idx_file_record_uploader', table_name='file_records', if_exists=True)
    op.drop_table('file_records')
