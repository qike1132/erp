"""
add file_records table

P2-1: static/uploads 迁移至对象存储，数据库仅存元数据
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'add_file_records_table'
down_revision = 'merge_resolve_all_heads'
branch_labels = None
depends_on = None


def upgrade():
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
    op.create_index('idx_file_record_uploader', 'file_records', ['uploader_id'])
    op.create_index('idx_file_record_storage_key', 'file_records', ['storage_key'])
    op.create_index('idx_file_record_created_at', 'file_records', ['created_at'])


def downgrade():
    op.drop_index('idx_file_record_created_at', table_name='file_records')
    op.drop_index('idx_file_record_storage_key', table_name='file_records')
    op.drop_index('idx_file_record_uploader', table_name='file_records')
    op.drop_table('file_records')
