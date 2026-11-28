"""Remove approval system (tables, order lock columns, approval_manage nav permission)

审批系统于 2026-11-28 整体下线（后端 commit 89b658a0 起代码零引用）：
- drop approval_log / approval_request（生产与测试库均为 0 行，2026-11-28 只读盘点）；
- drop order 锁列 is_locked/locked_by_id/lock_time + FK + idx_order_locked_by
  （ORM 已同步移除， alembic check 以此对齐）；
- 删除权限点 approval_manage（审批管理导航项，user_permission 绑定 0 人）。

Revision ID: pg_standalone_123_remove_approval_system
Revises: pg_standalone_122_csp_part_unique_index
Create Date: 2026-11-28
"""
import sqlalchemy as sa
from alembic import op

from migrations._legacy_base_guard import base_schema_absent

# revision identifiers, used by Alembic.
revision = 'pg_standalone_123_remove_approval_system'
down_revision = 'pg_standalone_122_csp_part_unique_index'
branch_labels = None
depends_on = None


def upgrade():
    # 空库守卫：基础 schema 尚未建出时整条迁移空转（与 659467a97350 同判据：
    # product / customer 同时缺失的遗留库不会有审批表）。
    if base_schema_absent():
        return
    op.execute('DELETE FROM approval_log')
    op.execute('DELETE FROM approval_request')
    op.drop_table('approval_log')
    op.drop_table('approval_request')
    with op.batch_alter_table('order', schema=None) as batch_op:
        batch_op.drop_constraint('order_locked_by_id_fkey', type_='foreignkey')
        batch_op.drop_index('idx_order_locked_by')
        batch_op.drop_column('lock_time')
        batch_op.drop_column('locked_by_id')
        batch_op.drop_column('is_locked')
    op.execute(
        "DELETE FROM user_permission WHERE permission_id IN "
        "(SELECT id FROM permission WHERE code = 'approval_manage')"
    )
    op.execute("DELETE FROM permission WHERE code = 'approval_manage'")


def downgrade():
    """回滚路径：按 659467a97350 的原状重建结构与权限行（数据不可恢复，
    但下线时两表为 0 行，无业务数据损失）。"""
    if base_schema_absent():
        return
    op.create_table(
        'approval_request',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('order_id', sa.Integer(), nullable=False, comment='关联订单ID'),
        sa.Column('requester_id', sa.Integer(), nullable=False, comment='申请人ID'),
        sa.Column('operation_type', sa.String(length=20), nullable=False, comment='操作类型：edit/delete'),
        sa.Column('operation_data', sa.Text(), nullable=True, comment='操作数据JSON（编辑时保存修改内容）'),
        sa.Column('status', sa.String(length=20), nullable=True, comment='状态：pending/approved/rejected/cancelled'),
        sa.Column('request_time', sa.DateTime(), nullable=True, comment='申请时间'),
        sa.Column('approver_id', sa.Integer(), nullable=True, comment='审批人ID'),
        sa.Column('approval_time', sa.DateTime(), nullable=True, comment='审批时间'),
        sa.Column('rejection_reason', sa.Text(), nullable=True, comment='拒绝原因'),
        sa.Column('lock_time', sa.DateTime(), nullable=True, comment='锁定时间'),
        sa.Column('updated_at', sa.DateTime(), nullable=True, comment='更新时间'),
        sa.ForeignKeyConstraint(['approver_id'], ['user.id']),
        sa.ForeignKeyConstraint(['order_id'], ['order.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['requester_id'], ['user.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('approval_request', schema=None) as batch_op:
        batch_op.create_index('idx_approval_status_time', ['status', 'request_time'], unique=False)
        batch_op.create_index(batch_op.f('ix_approval_request_request_time'), ['request_time'], unique=False)
        batch_op.create_index(batch_op.f('ix_approval_request_status'), ['status'], unique=False)
        batch_op.create_index('idx_approval_request_order', ['order_id'], unique=False)
        batch_op.create_index('idx_approval_request_requester', ['requester_id'], unique=False)
        batch_op.create_index('idx_approval_approver', ['approver_id'], unique=False)

    op.create_table(
        'approval_log',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('approval_request_id', sa.Integer(), nullable=False, comment='审批请求ID'),
        sa.Column('action', sa.String(length=50), nullable=False, comment='操作动作：create/approve/reject/cancel/execute'),
        sa.Column('actor_id', sa.Integer(), nullable=True, comment='操作人ID'),
        sa.Column('actor_name', sa.String(length=50), nullable=True, comment='操作人名称'),
        sa.Column('action_time', sa.DateTime(), nullable=True, comment='操作时间'),
        sa.Column('details', sa.Text(), nullable=True, comment='操作详情JSON'),
        sa.Column('updated_at', sa.DateTime(), nullable=True, comment='更新时间'),
        sa.ForeignKeyConstraint(['actor_id'], ['user.id']),
        sa.ForeignKeyConstraint(['approval_request_id'], ['approval_request.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('approval_log', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_approval_log_action_time'), ['action_time'], unique=False)
        batch_op.create_index('idx_approval_log_request', ['approval_request_id'], unique=False)
        batch_op.create_index('idx_approval_log_actor', ['actor_id'], unique=False)

    with op.batch_alter_table('order', schema=None) as batch_op:
        batch_op.add_column(sa.Column('is_locked', sa.Boolean(), nullable=True, comment='是否被审批锁定'))
        batch_op.add_column(sa.Column('locked_by_id', sa.Integer(), nullable=True, comment='锁定人ID'))
        batch_op.add_column(sa.Column('lock_time', sa.DateTime(), nullable=True, comment='锁定时间'))
        batch_op.create_index('idx_order_locked_by', ['locked_by_id'], unique=False)
        batch_op.create_foreign_key('order_locked_by_id_fkey', 'user', ['locked_by_id'], ['id'])

    op.execute(
        "INSERT INTO permission (name, code, icon, url, section, section_name, sort_order, is_nav) "
        "VALUES ('审批管理', 'approval_manage', 'fa-clipboard-check', 'approval.approval_list', "
        "'system', '系统管理', 4, true)"
    )
