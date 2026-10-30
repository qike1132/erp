"""S4 备份完整性判据测试。

背景：全量备份的 table_count 只是「数到的表数」，增量备份里某张表查询失败
曾被吞掉，于是缺表的备份照样记 success。本判据把「产物自述的覆盖情况」
收敛成单一入口 evaluate_backup_completeness，所有写记录的地方都必须用它。
"""

import pytest

from fastapi_app.services.backup.records import (
    STATUS_PARTIAL,
    STATUS_SUCCESS,
    STATUS_UNKNOWN,
    _collect_problem_tables,
    compose_remark,
    evaluate_backup_completeness,
)


class TestEvaluateBackupCompleteness:
    def test_no_info_is_unknown_not_success(self):
        status, detail = evaluate_backup_completeness(None)
        assert status == STATUS_UNKNOWN
        assert '自述缺失' in detail

    def test_empty_dict_is_unknown_not_success(self):
        assert evaluate_backup_completeness({})[0] == STATUS_UNKNOWN

    def test_file_metadata_without_completeness_is_unknown(self):
        """只有文件名/大小等文件元数据，不等于备份内容已验证。"""
        status, _ = evaluate_backup_completeness({
            'filename': 'erp_backup_20260101_000000.zip',
            'size': 1024,
            'created_at': '2026-01-01 00:00:00',
        })
        assert status == STATUS_UNKNOWN

    def test_clean_manifest_is_success(self):
        manifest = {
            'table_count': 68,
            'total_rows': 1234,
            'failed_tables': [],
            'coverage': {'complete': True, 'count_failed_tables': []},
        }
        assert evaluate_backup_completeness(manifest) == (STATUS_SUCCESS, '')

    def test_failed_tables_make_partial(self):
        status, detail = evaluate_backup_completeness({'failed_tables': ['approval_log']})
        assert status == STATUS_PARTIAL
        assert 'approval_log' in detail
        assert '缺失/失败表' in detail

    def test_missing_tables_make_partial(self):
        status, detail = evaluate_backup_completeness({'missing_tables': ['a', 'b']})
        assert status == STATUS_PARTIAL
        assert 'a' in detail and 'b' in detail

    def test_coverage_complete_false_makes_partial(self):
        status, detail = evaluate_backup_completeness({'coverage': {'complete': False}})
        assert status == STATUS_PARTIAL
        assert '覆盖度自检未通过' in detail

    def test_coverage_failed_tables_make_partial(self):
        status, detail = evaluate_backup_completeness(
            {'coverage': {'complete': False, 'count_failed_tables': ['stock_out']}}
        )
        assert status == STATUS_PARTIAL
        assert 'stock_out' in detail

    def test_batch_errors_keys_are_table_names(self):
        status, detail = evaluate_backup_completeness(
            {'batch_errors': {'order_item': 'deadlock detected'}}
        )
        assert status == STATUS_PARTIAL
        assert 'order_item' in detail

    def test_result_shape_without_table_count(self):
        """无 table_count 的 result（如历史增量产物）直接喂进来也要判出 partial。"""
        result = {
            'success': True,
            'filename': 'erp_backup_20260930_020503.zip',
            'total_rows': 10,
            'failed_tables': ['approval_request', 'approval_log'],
        }
        status, detail = evaluate_backup_completeness(result)
        assert status == STATUS_PARTIAL
        assert 'approval_request' in detail and 'approval_log' in detail

    def test_many_tables_are_truncated(self):
        names = [f'table_{i:02d}' for i in range(25)]
        status, detail = evaluate_backup_completeness({'failed_tables': names})
        assert status == STATUS_PARTIAL
        assert '等 25 张' in detail
        # 最多列出 _MAX_REPORTED_TABLES 张，避免 remark 被刷爆
        assert 'table_20' not in detail

    def test_non_dict_info_is_unknown(self):
        assert evaluate_backup_completeness('nonsense')[0] == STATUS_UNKNOWN


class TestCollectProblemTables:
    def test_dedup_preserves_order(self):
        assert _collect_problem_tables({'failed_tables': ['b', 'a', 'b']}) == ['b', 'a']

    def test_dict_keys_used(self):
        assert _collect_problem_tables({'failed_tables': {'x': 1, 'y': 2}}) == ['x', 'y']

    def test_scalar_string_accepted(self):
        assert _collect_problem_tables({'failed_tables': 'single'}) == ['single']

    def test_ignores_unknown_shapes(self):
        assert _collect_problem_tables({'failed_tables': 42}) == []


class TestComposeRemark:
    def test_empty_detail_returns_base(self):
        assert compose_remark('手动全量备份', '') == '手动全量备份'

    def test_appends_with_fullwidth_semicolon(self):
        assert compose_remark('手动全量备份', '缺失/失败表: a') == '手动全量备份；缺失/失败表: a'

    def test_empty_base_returns_detail(self):
        assert compose_remark('', '缺失/失败表: a') == '缺失/失败表: a'

    def test_none_base(self):
        assert compose_remark(None, '缺失/失败表: a') == '缺失/失败表: a'


@pytest.mark.parametrize('bad_status', ['partial', 'unknown', 'failed'])
def test_status_constants_are_short_enough_for_column(bad_status):
    """backup_record.status 是 String(20)，新取值必须放得下。"""
    assert len(bad_status) <= 20


def test_list_backup_files_does_not_inject_fake_completeness(tmp_path, monkeypatch):
    """旧 manifest 没有自述键时，fs_entry 不得凭空注入 failed_tables/coverage。

    否则 sync 补录会把「无自述」洗成「自述为干净」，unknown 永远不可达
    （2026-10-30 审计 B-M3）。
    """
    import json
    import zipfile

    from fastapi_app.services.backup import records

    zip_path = tmp_path / 'erp_backup_20260101_000000.zip'
    with zipfile.ZipFile(zip_path, 'w') as zf:
        zf.writestr('manifest.json', json.dumps({'type': 'full', 'exported_at': '2026-01-01 00:00:00'}))
    monkeypatch.setattr(records, 'BACKUP_DIR', tmp_path)

    entry = records.list_backup_files()[0]

    assert 'failed_tables' not in entry
    assert 'coverage' not in entry
    assert entry.get('dump_format') is None
    assert records.evaluate_backup_completeness(entry)[0] == STATUS_UNKNOWN
