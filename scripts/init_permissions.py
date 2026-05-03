"""
权限体系初始化脚本
支持大类全选模式的权限结构
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

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
        'parent': {'code': 'report_manage', 'name': '报表管理'},
        'children': []
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
}


def init_permissions():
    """初始化权限数据"""
    session = SyncSessionLocal()
    try:
        print("=" * 70)
        print("权限体系初始化 - 大类全选模式")
        print("=" * 70)

        existing_count = session.query(Permission).count()
        if existing_count > 0:
            print(f"\n权限表中已存在 {existing_count} 条数据")
            response = input("是否要重新初始化？这将清除现有权限数据。(y/n): ")
            if response.lower() != 'y':
                print("操作已取消")
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
    init_permissions()
