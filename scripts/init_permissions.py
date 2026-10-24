"""
权限体系初始化脚本
支持大类全选模式的权限结构
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from _prod_write_guard import require_prod_write_consent
from sqlalchemy import text

from fastapi_app.core.database import SyncSessionLocal
from fastapi_app.shared_models import Permission

PERMISSIONS_CONFIG = {
    'user': {
        'module_name': '用户管理',
        'icon': 'fa-users-cog',
        'parent': {'code': 'user_manage', 'name': '用户管理'},
        'children': []
    },
    'permission': {
        'module_name': '权限管理',
        'icon': 'fa-shield-alt',
        'parent': {'code': 'permission_manage', 'name': '权限管理(全部)'},
        'children': []
    },
    'product': {
        'module_name': '产品管理',
        'icon': 'fa-box',
        'parent': {'code': 'product_manage', 'name': '产品管理'},
        'children': []
    },
    'order': {
        'module_name': '订单管理',
        'icon': 'fa-shopping-cart',
        'parent': {'code': 'order_manage', 'name': '订单管理(全部)'},
        'children': []
    },
    'stockin': {
        'module_name': '备货管理',
        'icon': 'fa-truck-loading',
        'parent': {'code': 'stockin_manage', 'name': '备货管理(全部)'},
        'children': []
    },
    'stockout': {
        'module_name': '出库管理',
        'icon': 'fa-truck',
        'parent': {'code': 'stockout_manage', 'name': '出库管理'},
        'children': []
    },
    'case': {
        'module_name': '皮套管理',
        'icon': 'fa-suitcase',
        'parent': {'code': 'case_manage', 'name': '皮套管理'},
        'children': []
    },
    'report': {
        'module_name': '报表统计',
        'icon': 'fa-chart-bar',
        'parent': {'code': 'report_manage', 'name': '订单流水'},
        # 报表域行内操作子码，对齐迁移 pg_standalone_075/079/091 的插入内容：
        # 空库部署链 init_permissions --yes 重建全部权限后，迁移里
        # WHERE p.code='report_manage' 的 INSERT...SELECT 若父行缺失会静默插 0 行，
        # 子码永久缺失（2026-10-09 第 16 轮审计 High-2）。此处补齐保证空库也齐。
        # 一个 tab 一对「编辑/删除」，name 与报表页 tab 名完全一致
        # （对齐 useReportConfig.TAB_CONFIG.label；改这里要同步迁移
        #  pg_standalone_091_report_row_action_per_tab，反之亦然）。
        'children': [
            {'code': 'order_edit', 'name': '编辑订单流水'},
            {'code': 'order_delete', 'name': '删除订单流水'},
            {'code': 'stockin_edit', 'name': '编辑备货流水'},
            {'code': 'stockin_delete', 'name': '删除备货流水'},
            {'code': 'stockout_edit', 'name': '编辑出货流水'},
            {'code': 'stockout_delete', 'name': '删除出货流水'},
            {'code': 'deduction_edit', 'name': '编辑备货抵扣流水'},
            {'code': 'deduction_delete', 'name': '删除备货抵扣流水'},
            {'code': 'return_edit', 'name': '编辑退货流水'},
            {'code': 'return_delete', 'name': '删除退货流水'},
        ]
    },
    'approval': {
        'module_name': '审批管理',
        'icon': 'fa-clipboard-check',
        'parent': {'code': 'approval_manage', 'name': '审批管理'},
        'children': []
    },
    'customer': {
        'module_name': '客户管理',
        'icon': 'fa-building',
        'parent': {'code': 'customer_manage', 'name': '客户管理'},
        'children': []
    },
    'purchase_center': {
        'module_name': '采购中心',
        'icon': 'fa-store',
        'parent': {'code': 'purchase_center_manage', 'name': '采购中心'},
        'children': []
    },
    'production_summary': {
        'module_name': '生产报表',
        'icon': 'fa-industry',
        'parent': {'code': 'production_summary_manage', 'name': '生产报表(全部)'},
        'children': []
    },
    'backup': {
        'module_name': '数据备份',
        'icon': 'fa-database',
        'parent': {'code': 'backup_manage', 'name': '数据备份'},
        # 细粒度子码。备份端点走 require_any_permission(<细粒度码>, 'backup_manage')
        # （见 fastapi_app/api/v1/endpoints/backup/_deps.py），即「持 backup_manage 全通，
        # 也可只授其中一个」。这 4 个码此前**全仓（种子 / 迁移 / 生产库）都不存在**
        # （2026-10-12 提权核查），等于细粒度授权是死配置——/user 里根本点不到。
        # 改这里要同步迁移 pg_standalone_093_backup_child_permissions，反之亦然。
        'children': [
            {'code': 'backup_read', 'name': '查看备份'},
            {'code': 'backup_create', 'name': '创建备份'},
            {'code': 'backup_restore', 'name': '恢复备份'},
            {'code': 'backup_delete', 'name': '删除备份'},
        ]
    },
}


def _builtin_codes() -> set[str]:
    """内置清单覆盖的全部权限码（父 + 子）。"""
    codes: set[str] = set()
    for cfg in PERMISSIONS_CONFIG.values():
        codes.add(cfg['parent']['code'])
        for child in cfg.get('children') or []:
            if child.get('code'):
                codes.add(child['code'])
    return codes


def init_permissions(assume_yes: bool = False, force_wipe: bool = False):
    """初始化权限数据"""
    session = SyncSessionLocal()
    try:
        print("=" * 70)
        print("权限体系初始化 - 大类全选模式")
        print("=" * 70)

        existing_count = session.query(Permission).count()
        if existing_count > 0:
            print(f"\n权限表中已存在 {existing_count} 条数据")
            if assume_yes:
                response = 'y'
                print("--yes：跳过确认，将清除现有权限数据并重新初始化")
            else:
                response = input("是否要重新初始化？这将清除现有权限数据。(y/n): ")
            if response.lower() != 'y':
                print("操作已取消")
                return
            # F3-9：重新初始化会清空全部 user_permission，必须显式生产写授权
            require_prod_write_consent(
                '重新初始化权限（清空 user_permission 并重建权限字典）',
                hint='会影响所有用户的权限关联；请先备份',
            )
            # P1（2026-10-24）：只允许在「权限字典与内置清单一致」的库上重建。
            # 本脚本的清单只有 12 个父模块，而 outsource_manage / pattern_room_manage /
            # production_plan_manage / supplier_manage 及其子码是由 pg_standalone_019/042/043
            # 等迁移种入的 —— 一旦 --yes 全删再按内置清单重建，这四个模块的权限码永久消失
            # （迁移已 applied 不会自动补回），这些模块对所有人 403，只能人工重建。
            existing_codes = {code for (code,) in session.query(Permission.code).all()}
            unknown = sorted(existing_codes - _builtin_codes())
            if unknown and not force_wipe:
                print(
                    f"❌ 检测到 {len(unknown)} 个不在内置清单中的权限码（例：{unknown[:6]}），"
                    "说明该库的权限字典包含迁移种入的模块。\n"
                    "   继续重建会让这些权限码永久消失（迁移已 applied 不会补回）。\n"
                    "   如确认要清空，请加 --force-wipe 并先备份 permission / user_permission 两张表。"
                )
                return
            session.execute(text("DELETE FROM user_permission"))
            session.commit()
            print("已清除用户权限关联")
            session.query(Permission).filter(Permission.parent_id.isnot(None)).delete(synchronize_session=False)
            session.commit()
            session.query(Permission).filter(Permission.parent_id.is_(None)).delete(synchronize_session=False)
            session.commit()
            print("已清除现有权限数据")

        print("\n开始创建权限数据...")
        permission_map = {}

        for _module_code, module_config in PERMISSIONS_CONFIG.items():
            module_name = module_config['module_name']
            parent_data = module_config['parent']
            children = module_config['children']

            print(f"\n【{module_name}】模块:")

            parent_perm = Permission(
                name=parent_data['name'],
                code=parent_data['code']
            )
            session.add(parent_perm)
            session.flush()
            permission_map[parent_data['code']] = parent_perm.id
            print(f"  + 父权限: {parent_data['name']} ({parent_data['code']})")

            for child_data in children:
                child_perm = Permission(
                    name=child_data['name'],
                    code=child_data['code'],
                    parent_id=parent_perm.id
                )
                session.add(child_perm)
                session.flush()
                permission_map[child_data['code']] = child_perm.id
                print(f"    - 子权限: {child_data['name']} ({child_data['code']})")

        session.commit()

        print("\n" + "-" * 70)
        print("验证结果:")
        all_permissions = session.query(Permission).order_by(Permission.id).all()
        print(f"\n权限总数: {len(all_permissions)}")

        parent_perms = [p for p in all_permissions if p.parent_id is None]
        child_perms = [p for p in all_permissions if p.parent_id is not None]

        print(f"父权限数: {len(parent_perms)}")
        print(f"子权限数: {len(child_perms)}")

        print("\n父权限列表:")
        for p in parent_perms:
            children_count = len([c for c in all_permissions if c.parent_id == p.id])
            print(f"  - {p.name} ({p.code}) - 包含 {children_count} 个子权限")

        print("\n" + "=" * 70)
        print("权限数据初始化完成！")
        print("=" * 70)
    finally:
        session.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="权限体系初始化")
    parser.add_argument('--yes', action='store_true', help="已存在数据时跳过交互确认，直接重新初始化")
    parser.add_argument(
        '--force-wipe', action='store_true',
        help="即使库中存在内置清单以外的权限码（迁移种入的模块）也强制清空重建；会永久丢失这些权限码",
    )
    args = parser.parse_args()
    init_permissions(assume_yes=args.yes, force_wipe=args.force_wipe)
