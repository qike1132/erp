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
        ]

    def test_outsource_mapping_unchanged(self):
        # 既有映射行为不得改变
        assert nav_permission_codes('outsource_manage') == ['outsource_manage', 'outsource_view']

    def test_unmapped_code_falls_back_to_itself(self):
        assert nav_permission_codes('product_manage') == ['product_manage']

    def test_code_always_present_in_result(self):
        for code in ('production_summary_view', 'outsource_manage', 'permission_manage'):
            assert code in nav_permission_codes(code)
