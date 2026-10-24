"""
导航权限种子脚本 —— 新库/新机器部署后补齐左侧导航的**权威单一来源**。

背景：init_permissions.py 只写 code/name/icon，不写 url/section/section_name，
导致全新库 GET /api/v1/dashboard/nav-sections 返回空（左栏空白）。
历史上导航映射散落在十几个 fix_*_nav.py / add_*_nav.py 一次性脚本里，
本脚本把生产库 2026-10-08 导出的父权限（parent_id IS NULL）全部内嵌收口。

行为：
- 按code 查行，缺则 INSERT、已有则 UPDATE 全部种子字段（幂等，可重复执行）；
- 不删除种子之外的行（手工加的行不会被误删）；
- 只处理父权限行；子权限（按钮级）仍由 init_permissions.py 负责；
- 结束后正确清理 Redis 导航缓存（asyncio.run + safe_delete）。

运行方式（在项目根目录）:
    .venv\\Scripts\\python.exe scripts\\seed_nav.py
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from fastapi_app.core.database import SyncSessionLocal
from fastapi_app.shared_models import Permission

# 生产库 permission 表 parent_id IS NULL 的全部父权限行（2026-10-08 只读导出）。
# 字段: code, name, icon, url, section, section_name, sort_order, is_nav
NAV_SEED: list[dict] = [
    {'code': 'product_manage', 'name': '产品清单', 'icon': 'fa-box', 'url': 'product.products', 'section': 'core', 'section_name': '核心业务', 'sort_order': 1, 'is_nav': True},
    {'code': 'order_manage', 'name': '客户订单', 'icon': 'fa-file-invoice', 'url': 'customer_order.index', 'section': 'core', 'section_name': '核心业务', 'sort_order': 2, 'is_nav': True},
    {'code': 'stockin_manage', 'name': '备货管理(全部)', 'icon': 'fa-truck-loading', 'url': 'stock.stockins', 'section': 'core', 'section_name': '核心业务', 'sort_order': 3, 'is_nav': False},
    {'code': 'case_manage', 'name': '皮套管理', 'icon': 'fa-box-open', 'url': 'case.case_management_page', 'section': 'core', 'section_name': '核心业务', 'sort_order': 3, 'is_nav': True},
    {'code': 'stockout_manage', 'name': '出库管理', 'icon': 'fa-shipping-fast', 'url': 'stock.stockouts', 'section': 'core', 'section_name': '核心业务', 'sort_order': 4, 'is_nav': True},
    {'code': 'order_batch_manage', 'name': '订单批次号', 'icon': 'fa-layer-group', 'url': 'order_batch.index', 'section': 'core', 'section_name': '核心业务', 'sort_order': 5, 'is_nav': True},
    {'code': 'stock_return_view', 'name': '退货管理', 'icon': 'fa-rotate-left', 'url': '/stock-return', 'section': 'core', 'section_name': '核心业务', 'sort_order': 6, 'is_nav': True},
    {'code': 'stock_return_manage', 'name': '退货管理(全部)', 'icon': None, 'url': None, 'section': 'core', 'section_name': '核心业务', 'sort_order': 7, 'is_nav': False},
    {'code': 'finished_stock_view', 'name': '成品库存', 'icon': 'fa-boxes-stacked', 'url': '/finished-stock', 'section': 'core', 'section_name': '核心业务', 'sort_order': 8, 'is_nav': True},
    {'code': 'production_plan_view', 'name': '出货计划', 'icon': 'fa-truck', 'url': 'purchase_plan.plan_list', 'section': 'core', 'section_name': '核心业务', 'sort_order': 14, 'is_nav': True},
    {'code': 'production_summary_view', 'name': '生产报表', 'icon': 'fa-industry', 'url': 'production_summary.index', 'section': 'core', 'section_name': '核心业务', 'sort_order': 24, 'is_nav': True},
    {'code': 'batch_manage', 'name': '批次号查询', 'icon': 'fa-table-cells', 'url': 'sku_batch.sku_batch_page', 'section': 'core', 'section_name': '核心业务', 'sort_order': 34, 'is_nav': True},
    {'code': 'stock_view', 'name': '订单查询', 'icon': 'fa-warehouse', 'url': 'stock.inventory', 'section': 'data', 'section_name': '订单查询', 'sort_order': 0, 'is_nav': True},
    {'code': 'report_manage', 'name': '订单流水', 'icon': 'fa-chart-bar', 'url': 'report.reports', 'section': 'data', 'section_name': '订单查询', 'sort_order': 2, 'is_nav': True},
    {'code': 'customer_sampling_manage', 'name': '板房管理', 'icon': 'fa-scissors', 'url': '/pattern-room', 'section': 'dev', 'section_name': '板房管理', 'sort_order': 44, 'is_nav': True},
    {'code': 'beile_order_view', 'name': '湖北订单', 'icon': 'fa-industry', 'url': 'beile_order.index', 'section': 'hubei', 'section_name': '湖北订单', 'sort_order': 54, 'is_nav': True},
    {'code': 'outsource_manage', 'name': '湖北外发', 'icon': 'fa-shuttle-van', 'url': '/outsource', 'section': 'hubei', 'section_name': '湖北订单', 'sort_order': 64, 'is_nav': True},
    {'code': 'purchase_center_manage', 'name': '采购中心', 'icon': 'fa-store', 'url': 'purchase_center.index', 'section': 'purchase', 'section_name': '采购中心', 'sort_order': 1, 'is_nav': True},
    {'code': 'supplier_manage', 'name': '供应商管理', 'icon': 'fa-truck', 'url': 'supplier.suppliers', 'section': 'purchase', 'section_name': '采购管理', 'sort_order': 11, 'is_nav': True},
    {'code': 'material_calculator', 'name': '物料计算器', 'icon': 'fa-calculator', 'url': 'material.calculator', 'section': 'purchase', 'section_name': '采购中心', 'sort_order': 12, 'is_nav': True},
    {'code': 'material_registration', 'name': '来料登记', 'icon': 'fa-truck-loading', 'url': 'material_registration.index', 'section': 'purchase', 'section_name': '采购中心', 'sort_order': 13, 'is_nav': True},
    {'code': 'user_manage', 'name': '用户管理', 'icon': 'fa-users-cog', 'url': 'user.users', 'section': 'system', 'section_name': '系统管理', 'sort_order': 1, 'is_nav': True},
    {'code': 'customer_manage', 'name': '客户管理', 'icon': 'fa-building', 'url': 'customer.customers', 'section': 'system', 'section_name': '系统管理', 'sort_order': 3, 'is_nav': True},
    {'code': 'approval_manage', 'name': '审批管理', 'icon': 'fa-clipboard-check', 'url': 'approval.approval_list', 'section': 'system', 'section_name': '系统管理', 'sort_order': 4, 'is_nav': True},
    {'code': 'backup_manage', 'name': '数据备份', 'icon': 'fa-database', 'url': '/backup', 'section': 'system', 'section_name': '系统管理', 'sort_order': 14, 'is_nav': True},
    {'code': 'production_plan_manage', 'name': '管理出货计划', 'icon': None, 'url': None, 'section': None, 'section_name': None, 'sort_order': 0, 'is_nav': False},
    {'code': 'production_summary_manage', 'name': '管理生产报表', 'icon': None, 'url': None, 'section': None, 'section_name': None, 'sort_order': 0, 'is_nav': False},
]

_SEED_FIELDS = ('name', 'icon', 'url', 'section', 'section_name', 'sort_order', 'is_nav')


def _seed_row(session, data: dict) -> None:
    code = data['code']
    perm = session.query(Permission).filter_by(code=code).first()
    if perm is None:
        perm = Permission(code=code, parent_id=None)
        session.add(perm)
        print(f"[INSERT] {code} {data['name']}")
    else:
        if perm.parent_id is not None:
            print(f"[SKIP] {code} 存在同名但为子权限行 (id={perm.id})，跳过（请人工核查）")
            return
        print(f"[UPDATE] {code} (id={perm.id})")
    for field in _SEED_FIELDS:
        setattr(perm, field, data[field])


def main():
    session = SyncSessionLocal()
    try:
        for data in NAV_SEED:
            _seed_row(session, data)
        session.commit()
        print(f"[OK] 共处理 {len(NAV_SEED)} 个父权限行")

        # 正确清理两级导航缓存（进程内缓存在 API 进程里，TTL 60s 自然过期；
        # Redis 缓存 TTL 300s，必须显式删，且 delete 是协程必须真正执行）
        try:
            from fastapi_app.core.redis_wrapper import safe_delete

            asyncio.run(safe_delete('nav_sections', context="导航种子"))
            print("[OK] 已清除 Redis 导航缓存")
        except Exception as exc:
            print(f"[WARN] 清除 Redis 导航缓存失败（等待 5 分钟 TTL 过期即可）: {exc}")
    finally:
        session.close()


if __name__ == '__main__':
    # AUD-18（2026-10-24 审计）：与 add_*_nav 族同款写守卫（打目标库+显式授权）
    from _prod_write_guard import require_prod_write_consent
    require_prod_write_consent('写入导航/权限种子数据（生产库）')
    main()
