"""清理板房模块遗留表（pattern_room 旧实现，已被 customer_sampling 接管）

Revision ID: pg_standalone_027_drop_pattern_room
Revises: pg_standalone_026_search_trgm
Create Date: 2026-08-11

背景与表谱系：
- 015 创建旧 BOM 模型 4 表：pattern_room_bom / pattern_room_bom_item /
  pattern_room_bom_item_version / pattern_room_change_log（对应已删除的
  shared_models/pattern_room.py，打样编号 BF-*）
- 017 删除上述 4 表并创建 sample 模型 4 表：pattern_room_sample /
  pattern_room_sample_part / pattern_room_part_fabric /
  pattern_room_change_log_v2（打样编号 YS-*，无任何代码引用）
- 019 起由 customer_sampling 模块（customer_sampling_project /
  customer_sampling_part / customer_sampling_fabric_version /
  customer_sampling_change_log）完全接管 /pattern-room 路由

本次迁移删除以上 8 张遗留表。全部使用 IF EXISTS 保证幂等：
- 已应用过 017 的库：BOM 4 表已不存在，仅清理 sample 4 表
- 未应用过 017 的库：BOM 4 表一并清理

⚠️ 数据丢失警告：升级会永久删除这些表中的全部数据。确认生产环境
customer_sampling_* 表已完整接管业务、旧表无待迁移数据后再执行。
所有表已确认无代码引用、无其他表外键依赖（仅表间自引用与外链
customer/supplier/user）。

downgrade 与 017 的约定一致（见 pg_standalone_017_pattern_room_v2 注释
“重建旧表省略，通常不需要在 downgrade 中重建”）：删除为破坏性操作，
不重建表结构。
"""
from alembic import op

revision = 'pg_standalone_027_drop_pattern_room'
down_revision = 'pg_standalone_026_search_trgm'
branch_labels = None
depends_on = None

# 旧 BOM 模型（015 创建，017 已删则不存在）
# 旧 sample 模型（017 创建，无代码引用）
# 按子表→父表顺序列出，保证外键依赖先于父表删除
LEGACY_TABLES = (
    # 子表（外键引用父表）
    'pattern_room_bom_item_version',
    'pattern_room_bom_item',
    'pattern_room_change_log',
    'pattern_room_part_fabric',
    'pattern_room_sample_part',
    'pattern_room_change_log_v2',
    # 父表
    'pattern_room_bom',
    'pattern_room_sample',
)


def upgrade():
    for table in LEGACY_TABLES:
        op.drop_table(table, if_exists=True)


def downgrade():
    # 破坏性迁移：不重建（同 pg_standalone_017 约定）
    # 如需恢复请使用备份恢复，或参考 pg_standalone_015 / 017 的建表 DDL。
    pass
