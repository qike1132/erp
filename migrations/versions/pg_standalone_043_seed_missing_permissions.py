"""补齐生产库缺失的权限点：batch_import / outsource_ship / outsource_receive

背景（与 pg_standalone_042 同类问题——代码已使用、生产库却未种入的权限码）：

1. batch_import
   - batch.py / staging_order.py / staging_stockin.py / staging_stockout.py /
     ocr_import.py / tasks.py 共约 30 个接口要求该权限，生产库从未存在
     （历史仅有导航权限 batch_manage，即「批次号查询」）。
   - 方案：创建为 batch_manage 的子权限，持有 batch_manage 的用户经
     has_permission 的子权限继承自动通过（与前端无显式 gate 的现状一致）。

2. outsource_ship / outsource_receive
   - outsource.py 发货/收货接口要求该权限，且前端 useOutsourceProcess.ts
     据此控制按钮显隐；outsource.py 模块文档明确要求配套授权脚本
     scripts/add_outsource_ship_receive_perms.py 先于代码上线执行，
     但生产库未执行。
   - 方案：按该脚本的幂等逻辑——创建为 outsource_manage 的子权限，
     并按改造前「用户名==贝乐」规则回填授权（ship→非贝乐持有者，receive→贝乐）。

幂等：权限创建带 NOT EXISTS 守卫，授权回填带 ON CONFLICT DO NOTHING，
重复执行/已手工补齐的环境不会产生重复数据。

Revision ID: pg_standalone_043_seed_missing_permissions
Revises: pg_standalone_042_rename_pattern_room_permission
Create Date: 2026-09-15
"""
from alembic import op

revision = 'pg_standalone_043_seed_missing_permissions'
down_revision = 'pg_standalone_042_rename_pattern_room_permission'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. batch_import：批量导入操作权限（batch_manage 的子权限）
    op.execute(
        """
        INSERT INTO permission (name, code, parent_id, section, section_name, sort_order, is_nav, updated_at)
        SELECT '批量导入', 'batch_import', id, section, section_name, sort_order + 1, false, now()
        FROM permission
        WHERE code = 'batch_manage'
          AND NOT EXISTS (SELECT 1 FROM permission p2 WHERE p2.code = 'batch_import')
        """
    )

    # 2. outsource_ship：外发工序发货（outsource_manage 的子权限）
    op.execute(
        """
        INSERT INTO permission (name, code, parent_id, section, section_name, sort_order, is_nav, updated_at)
        SELECT '湖北外发（发货）', 'outsource_ship', id, section, section_name, sort_order + 2, false, now()
        FROM permission
        WHERE code = 'outsource_manage'
          AND NOT EXISTS (SELECT 1 FROM permission p2 WHERE p2.code = 'outsource_ship')
        """
    )

    # 3. outsource_receive：确认收货（outsource_manage 的子权限）
    op.execute(
        """
        INSERT INTO permission (name, code, parent_id, section, section_name, sort_order, is_nav, updated_at)
        SELECT '湖北外发（收货）', 'outsource_receive', id, section, section_name, sort_order + 3, false, now()
        FROM permission
        WHERE code = 'outsource_manage'
          AND NOT EXISTS (SELECT 1 FROM permission p2 WHERE p2.code = 'outsource_receive')
        """
    )

    # 4. 按改造前规则回填授权（与 scripts/add_outsource_ship_receive_perms.py 一致）：
    #    ship   → 持有 outsource_manage 且用户名 != 贝乐
    #    receive→ 持有 outsource_manage 且用户名 == 贝乐
    op.execute(
        """
        INSERT INTO user_permission (user_id, permission_id)
        SELECT up.user_id, p.id
        FROM user_permission up
        JOIN permission pm ON pm.id = up.permission_id AND pm.code = 'outsource_manage'
        JOIN "user" u ON u.id = up.user_id
        JOIN permission p ON p.code = 'outsource_ship'
        WHERE u.username <> '贝乐'
        ON CONFLICT DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO user_permission (user_id, permission_id)
        SELECT up.user_id, p.id
        FROM user_permission up
        JOIN permission pm ON pm.id = up.permission_id AND pm.code = 'outsource_manage'
        JOIN "user" u ON u.id = up.user_id
        JOIN permission p ON p.code = 'outsource_receive'
        WHERE u.username = '贝乐'
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    for code in ('batch_import', 'outsource_ship', 'outsource_receive'):
        op.execute(
            f"""
            DELETE FROM user_permission
            WHERE permission_id IN (SELECT id FROM permission WHERE code = '{code}')
            """
        )
        op.execute(f"DELETE FROM permission WHERE code = '{code}'")
