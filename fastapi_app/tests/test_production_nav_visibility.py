"""导航权限码展开：部门码用户也要能看到「生产报表」入口"""
from fastapi_app.core.nav_context import nav_permission_codes


class TestNavPermissionCodes:
    def test_production_nav_lists_aggregate_and_three_dept_codes(self):
        codes = nav_permission_codes('production_summary_view')
        assert codes == [
            'production_summary_view',
            'production_summary_view_filling',
            'production_summary_view_handcraft',
            'production_summary_view_packaging',
            'production_summary_manage_filling',
            'production_summary_manage_handcraft',
            'production_summary_manage_packaging',
        ]

    def test_manage_only_dept_user_can_reach_entry(self):
        # C1 的核心：只持 manage_filling 的录单员，其原始权限列表
        # （前端侧栏不做 manage→view 展开）必须与入口的 permission_codes 有交集，
        # 否则他会被前端 fail-closed 路由静默弹回仪表盘。
        entry_codes = nav_permission_codes('production_summary_view')
        user_raw_permissions = {'production_summary_manage_filling'}
        assert user_raw_permissions & set(entry_codes)

    def test_outsource_mapping_unchanged(self):
        # 既有映射行为不得改变
        assert nav_permission_codes('outsource_manage') == ['outsource_manage', 'outsource_view']

    def test_unmapped_code_falls_back_to_itself(self):
        assert nav_permission_codes('product_manage') == ['product_manage']

    def test_code_always_present_in_result(self):
        for code in ('production_summary_view', 'outsource_manage', 'permission_manage'):
            assert code in nav_permission_codes(code)
