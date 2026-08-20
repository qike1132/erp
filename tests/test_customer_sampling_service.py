"""按客户分类打样信息模块 Service 层测试

测试分层：
1. 纯函数测试（无数据库依赖，稳定可过）
   - _compute_diff：diff 算法（新增/修改/删除三类、字段级 diff、空快照、归一化）
   - _next_version：版本号递增
   - _normalize_value：字段值归一化

2. Mock 测试（mock_async_db，无数据库依赖）
   - service 异常路径：NotFoundError / ConflictError / BusinessError

3. 集成测试（标记 integration，主库 + 事务回滚隔离）
   - 完整业务流程：分组聚合、项目 CRUD、部位 CRUD、版本创建+diff、变更日志

对应需求规格：.codeartsdoer/specs/customer_sampling/spec.md
对应技术设计：.codeartsdoer/specs/customer_sampling/design.md
"""
from __future__ import annotations

import os
import sys
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# 项目根目录入 path
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

# 测试专用数据库（conftest 计算得出，与开发库 erp_system 隔离，避免种子数据污染）
from conftest import TEST_DATABASE_URL

from fastapi_app.core.exceptions import BusinessError, ConflictError, NotFoundError
from fastapi_app.services.customer_sampling_service import (
    _SNAPSHOT_FIELDS,
    _compute_diff,
    _next_version,
    _normalize_value,
    create_part,
    create_project,
    create_version,
    delete_part,
    delete_project,
    get_grouped_list,
    get_project_detail,
    get_version_detail,
    list_change_logs,
    list_parts,
    list_versions,
    update_part,
    update_project,
    update_project_status,
    upload_project_image,
)

# ============================================================
# 1. 纯函数测试 — _next_version
# ============================================================

class TestNextVersion:
    """版本号递增纯函数测试"""

    def test_basic_increment(self):
        """T1 -> T2, T2 -> T3, T10 -> T11"""
        assert _next_version('T1') == 'T2'
        assert _next_version('T2') == 'T3'
        assert _next_version('T10') == 'T11'
        assert _next_version('T99') == 'T100'

    def test_lowercase_prefix(self):
        """小写 t 前缀也应识别"""
        assert _next_version('t1') == 'T2'
        assert _next_version('t5') == 'T6'

    def test_invalid_input_returns_t1(self):
        """无效输入降级为 T1"""
        assert _next_version('') == 'T1'
        assert _next_version('invalid') == 'T1'
        assert _next_version(None) == 'T1'
        assert _next_version('ABC') == 'T1'

    def test_non_numeric_suffix(self):
        """非数字后缀降级为 T1"""
        assert _next_version('TXX') == 'T1'


# ============================================================
# 2. 纯函数测试 — _normalize_value
# ============================================================

class TestNormalizeValue:
    """字段值归一化纯函数测试"""

    def test_none_and_empty_string(self):
        """None 与空字符串统一为 None"""
        assert _normalize_value(None) is None
        assert _normalize_value('') is None

    def test_integer_to_float(self):
        """int 转 float"""
        assert _normalize_value(10) == 10.0
        assert isinstance(_normalize_value(10), float)

    def test_float_unchanged(self):
        """float 保持不变"""
        assert _normalize_value(3.14) == 3.14
        assert isinstance(_normalize_value(3.14), float)

    def test_decimal_to_float(self):
        """Decimal 转 float，消除 Decimal/float 精度差异"""
        assert _normalize_value(Decimal('12.34')) == 12.34
        assert isinstance(_normalize_value(Decimal('12.34')), float)

    def test_string_unchanged(self):
        """非空字符串保持不变"""
        assert _normalize_value('布料A') == '布料A'
        assert _normalize_value('100') == '100'

    def test_zero(self):
        """0 应归一化为 0.0（非 None）"""
        result = _normalize_value(0)
        assert result == 0.0
        assert isinstance(result, float)

    def test_none_vs_empty_equal_after_normalize(self):
        """None 与 '' 归一化后相等（diff 不应误报）"""
        assert _normalize_value(None) == _normalize_value('')


# ============================================================
# 3. 纯函数测试 — _compute_diff（核心 diff 算法）
# ============================================================

def _make_part(part_name='身体', fabric_name='绒布', sort_order=0, **kwargs):
    """构造部位快照 dict（测试 helper）"""
    base = {
        'part_name': part_name,
        'sort_order': sort_order,
        'fabric_name': fabric_name,
        'fabric_spec': '',
        'supplier_id': None,
        'supplier_name': '',
        'contact_person': '',
        'contact_phone': '',
        'unit_price': None,
        'delivery_days': None,
        'remark': '',
    }
    base.update(kwargs)
    return base


class TestComputeDiff:
    """diff 算法纯函数测试（design.md 2.1.3.3）"""

    def test_both_empty(self):
        """两个空快照 → 空变更列表"""
        assert _compute_diff([], []) == []
        assert _compute_diff(None, None) == []

    def test_no_change(self):
        """相同快照 → 空变更列表"""
        snapshot = [_make_part('身体')]
        assert _compute_diff(snapshot, snapshot) == []

    def test_add_part(self):
        """新增部位：change_type=add"""
        snapshot_n = [_make_part('身体'), _make_part('头部')]
        snapshot_prev = [_make_part('身体')]
        diff = _compute_diff(snapshot_n, snapshot_prev)
        assert len(diff) == 1
        assert diff[0]['change_type'] == 'add'
        assert diff[0]['part_name'] == '头部'
        assert diff[0]['new_value']['part_name'] == '头部'
        assert diff[0]['old_value'] is None
        assert diff[0]['field_diffs'] is None

    def test_delete_part(self):
        """删除部位：change_type=delete"""
        snapshot_n = [_make_part('身体')]
        snapshot_prev = [_make_part('身体'), _make_part('头部')]
        diff = _compute_diff(snapshot_n, snapshot_prev)
        assert len(diff) == 1
        assert diff[0]['change_type'] == 'delete'
        assert diff[0]['part_name'] == '头部'
        assert diff[0]['new_value'] is None
        assert diff[0]['old_value']['part_name'] == '头部'
        assert diff[0]['field_diffs'] is None

    def test_modify_part_fabric_name(self):
        """修改部位布料名称：change_type=modify，field_diffs 记录字段级变更"""
        snapshot_prev = [_make_part('身体', fabric_name='绒布')]
        snapshot_n = [_make_part('身体', fabric_name='棉布')]
        diff = _compute_diff(snapshot_n, snapshot_prev)
        assert len(diff) == 1
        assert diff[0]['change_type'] == 'modify'
        assert diff[0]['part_name'] == '身体'
        assert diff[0]['field_diffs'] is not None
        assert len(diff[0]['field_diffs']) == 1
        assert diff[0]['field_diffs'][0]['field'] == 'fabric_name'
        assert diff[0]['field_diffs'][0]['old'] == '绒布'
        assert diff[0]['field_diffs'][0]['new'] == '棉布'

    def test_modify_multiple_fields(self):
        """同时修改多个字段：field_diffs 记录所有变更字段"""
        snapshot_prev = [_make_part('身体', fabric_name='绒布', unit_price=10, delivery_days=7)]
        snapshot_n = [_make_part('身体', fabric_name='棉布', unit_price=15, delivery_days=14)]
        diff = _compute_diff(snapshot_n, snapshot_prev)
        assert len(diff) == 1
        assert diff[0]['change_type'] == 'modify'
        changed_fields = {fd['field'] for fd in diff[0]['field_diffs']}
        assert changed_fields == {'fabric_name', 'unit_price', 'delivery_days'}

    def test_mixed_changes(self):
        """混合三类变更：新增 + 修改 + 删除"""
        snapshot_prev = [
            _make_part('身体', fabric_name='绒布'),
            _make_part('头部'),  # 将被删除
        ]
        snapshot_n = [
            _make_part('身体', fabric_name='棉布'),  # 修改
            _make_part('四肢'),  # 新增
        ]
        diff = _compute_diff(snapshot_n, snapshot_prev)
        assert len(diff) == 3
        types = {d['change_type'] for d in diff}
        assert types == {'add', 'modify', 'delete'}
        # 验证各变更部位
        by_type = {d['change_type']: d for d in diff}
        assert by_type['add']['part_name'] == '四肢'
        assert by_type['modify']['part_name'] == '身体'
        assert by_type['delete']['part_name'] == '头部'

    def test_normalize_none_vs_empty(self):
        """None 与 '' 归一化后相等，不应误报为修改"""
        # prev 用 None，n 用 ''（或反之），不应产生 diff
        snapshot_prev = [{
            'part_name': '身体', 'sort_order': 0, 'fabric_name': None,
            'fabric_spec': '', 'supplier_id': None, 'supplier_name': None,
            'contact_person': None, 'contact_phone': None,
            'unit_price': None, 'delivery_days': None, 'remark': None,
        }]
        snapshot_n = [{
            'part_name': '身体', 'sort_order': 0, 'fabric_name': '',
            'fabric_spec': '', 'supplier_id': None, 'supplier_name': '',
            'contact_person': '', 'contact_phone': '',
            'unit_price': None, 'delivery_days': None, 'remark': '',
        }]
        diff = _compute_diff(snapshot_n, snapshot_prev)
        assert diff == []

    def test_numeric_decimal_vs_float(self):
        """Decimal 与 float 归一化后相等，不应误报"""
        snapshot_prev = [{
            'part_name': '身体', 'sort_order': 0, 'fabric_name': '绒布',
            'fabric_spec': '', 'supplier_id': None, 'supplier_name': '',
            'contact_person': '', 'contact_phone': '',
            'unit_price': Decimal('10.00'), 'delivery_days': None, 'remark': '',
        }]
        snapshot_n = [{
            'part_name': '身体', 'sort_order': 0, 'fabric_name': '绒布',
            'fabric_spec': '', 'supplier_id': None, 'supplier_name': '',
            'contact_person': '', 'contact_phone': '',
            'unit_price': 10.0, 'delivery_days': None, 'remark': '',
        }]
        diff = _compute_diff(snapshot_n, snapshot_prev)
        assert diff == []

    def test_snapshot_fields_coverage(self):
        """验证 _SNAPSHOT_FIELDS 包含所有布料业务字段"""
        expected = {
            'part_name', 'sort_order', 'fabric_name', 'fabric_spec',
            'supplier_id', 'supplier_name', 'contact_person', 'contact_phone',
            'unit_price', 'delivery_days', 'remark',
        }
        assert set(_SNAPSHOT_FIELDS) == expected

    def test_part_name_as_index_key(self):
        """diff 算法以 part_name 为索引键，同名部位视为同一部位"""
        snapshot_prev = [_make_part('身体', fabric_name='绒布')]
        snapshot_n = [_make_part('身体', fabric_name='棉布')]
        diff = _compute_diff(snapshot_n, snapshot_prev)
        assert len(diff) == 1
        assert diff[0]['change_type'] == 'modify'

    def test_empty_new_snapshot_all_delete(self):
        """新版本空快照，前一版本所有部位均为删除"""
        snapshot_prev = [_make_part('身体'), _make_part('头部')]
        diff = _compute_diff([], snapshot_prev)
        assert len(diff) == 2
        assert all(d['change_type'] == 'delete' for d in diff)

    def test_empty_prev_snapshot_all_add(self):
        """前一版本空快照，新版本所有部位均为新增"""
        snapshot_n = [_make_part('身体'), _make_part('头部')]
        diff = _compute_diff(snapshot_n, [])
        assert len(diff) == 2
        assert all(d['change_type'] == 'add' for d in diff)


# ============================================================
# 4. Mock 测试 — Service 异常路径
# ============================================================

def _mock_result(scalar_value=None, scalars_value=None):
    """构造 mock db.execute 返回值"""
    mr = MagicMock()
    mr.scalar_one_or_none.return_value = scalar_value
    mr.scalars.return_value.all.return_value = scalars_value or []
    mr.scalars.return_value.first.return_value = scalar_value
    return mr


class TestServiceMockErrors:
    """Service 层异常路径 Mock 测试（无需数据库）"""

    async def test_get_project_detail_not_found(self, mock_async_db):
        """项目不存在 → NotFoundError"""
        mock_async_db.execute = AsyncMock(return_value=_mock_result(scalar_value=None))
        with pytest.raises(NotFoundError):
            await get_project_detail(mock_async_db, 9999)

    async def test_update_project_not_found(self, mock_async_db):
        """编辑项目：项目不存在 → NotFoundError"""
        mock_async_db.execute = AsyncMock(return_value=_mock_result(scalar_value=None))
        with pytest.raises(NotFoundError):
            await update_project(mock_async_db, 9999, product_name='x', version=0)

    async def test_update_project_optimistic_lock_conflict(self, mock_async_db):
        """编辑项目：乐观锁不匹配 → ConflictError"""
        project = MagicMock()
        project.id = 1
        project.version = 5  # 数据库中版本为 5
        mock_async_db.execute = AsyncMock(return_value=_mock_result(scalar_value=project))
        with pytest.raises(ConflictError):
            # 传入 version=3，与 5 不匹配
            await update_project(mock_async_db, 1, product_name='新名称', version=3)

    async def test_update_project_status_not_found(self, mock_async_db):
        """更新项目状态：项目不存在 → NotFoundError"""
        mock_async_db.execute = AsyncMock(return_value=_mock_result(scalar_value=None))
        with pytest.raises(NotFoundError):
            await update_project_status(mock_async_db, 9999, status='completed')

    async def test_delete_project_not_found(self, mock_async_db):
        """删除项目：项目不存在 → NotFoundError"""
        mock_async_db.execute = AsyncMock(return_value=_mock_result(scalar_value=None))
        with pytest.raises(NotFoundError):
            await delete_project(mock_async_db, 9999)

    async def test_list_parts_project_not_found(self, mock_async_db):
        """部位列表：项目不存在 → NotFoundError"""
        # _ensure_project_exists 内部 execute 查 id，scalar_one_or_none 返回 None
        mock_async_db.execute = AsyncMock(return_value=_mock_result(scalar_value=None))
        with pytest.raises(NotFoundError):
            await list_parts(mock_async_db, 9999)

    async def test_list_versions_project_not_found(self, mock_async_db):
        """版本列表：项目不存在 → NotFoundError"""
        mock_async_db.execute = AsyncMock(return_value=_mock_result(scalar_value=None))
        with pytest.raises(NotFoundError):
            await list_versions(mock_async_db, 9999)

    async def test_list_change_logs_project_not_found(self, mock_async_db):
        """变更日志：项目不存在 → NotFoundError"""
        mock_async_db.execute = AsyncMock(return_value=_mock_result(scalar_value=None))
        with pytest.raises(NotFoundError):
            await list_change_logs(mock_async_db, 9999)

    async def test_get_version_detail_not_found(self, mock_async_db):
        """版本详情：版本不存在 → NotFoundError"""
        mock_async_db.execute = AsyncMock(return_value=_mock_result(scalar_value=None))
        with pytest.raises(NotFoundError):
            await get_version_detail(mock_async_db, 9999)

    async def test_update_part_not_found(self, mock_async_db):
        """编辑部位：部位不存在 → NotFoundError"""
        mock_async_db.execute = AsyncMock(return_value=_mock_result(scalar_value=None))
        with pytest.raises(NotFoundError):
            await update_part(mock_async_db, 9999, part_name='x', version=0)

    async def test_update_part_optimistic_lock_conflict(self, mock_async_db):
        """编辑部位：乐观锁不匹配 → ConflictError"""
        part = MagicMock()
        part.id = 1
        part.version = 5
        part.project_id = 1
        part.part_name = '身体'
        mock_async_db.execute = AsyncMock(return_value=_mock_result(scalar_value=part))
        with pytest.raises(ConflictError):
            await update_part(mock_async_db, 1, part_name='身体', version=3)

    async def test_delete_part_not_found(self, mock_async_db):
        """删除部位：部位不存在 → NotFoundError"""
        mock_async_db.execute = AsyncMock(return_value=_mock_result(scalar_value=None))
        with pytest.raises(NotFoundError):
            await delete_part(mock_async_db, 9999)

    async def test_create_part_duplicate_name(self, mock_async_db):
        """新增部位：部位名重复 → BusinessError

        _ensure_project_exists 通过后，_ensure_part_name_unique 查到已存在记录。
        用 side_effect 模拟三次 execute 返回不同结果。
        """
        # 第一次 execute（_ensure_project_exists）返回项目存在
        # 第二次 execute（_get_default_role_id）返回默认角色 id=1
        # 第三次 execute（_ensure_part_name_unique）返回已存在 id=2
        project_exists_result = _mock_result(scalar_value=1)
        default_role_result = _mock_result(scalar_value=1)
        duplicate_result = _mock_result(scalar_value=2)  # 查到已存在部位 id=2
        mock_async_db.execute = AsyncMock(
            side_effect=[project_exists_result, default_role_result, duplicate_result]
        )
        with pytest.raises(BusinessError):
            await create_part(mock_async_db, 1, part_name='身体')

    async def test_upload_image_unsupported_type(self, mock_async_db):
        """上传图片：不支持的格式 → BusinessError"""
        # _ensure_project_exists 通过
        mock_async_db.execute = AsyncMock(return_value=_mock_result(scalar_value=1))
        with pytest.raises(BusinessError):
            await upload_project_image(
                mock_async_db, 1,
                content=b'\x00',
                original_filename='test.gif',
                content_type='image/gif',
            )

    async def test_upload_image_too_large(self, mock_async_db):
        """上传图片：超过 10MB → BusinessError"""
        mock_async_db.execute = AsyncMock(return_value=_mock_result(scalar_value=1))
        large_content = b'\x00' * (10 * 1024 * 1024 + 1)
        with pytest.raises(BusinessError):
            await upload_project_image(
                mock_async_db, 1,
                content=large_content,
                original_filename='test.png',
                content_type='image/png',
            )

    async def test_create_project_pattern_maker_not_found(self, mock_async_db):
        """创建项目：版师不存在 → NotFoundError

        _resolve_pattern_maker_name 内部 execute 查版师名，返回 None（版师不存在）。
        """
        mock_async_db.execute = AsyncMock(return_value=_mock_result(scalar_value=None))
        with pytest.raises(NotFoundError):
            await create_project(mock_async_db, product_name='测试', pattern_maker_id=9999)


# ============================================================
# 5. 集成测试 — 完整业务流程（主库 + 事务回滚隔离）
# ============================================================

# 集成测试标记：需要数据库
pytestmark_integration = pytest.mark.integration


@pytest_asyncio.fixture
async def cs_db():
    """function-scoped 测试数据库会话（主库 + 外层事务回滚隔离）

    规避 conftest.py 中 session-scoped test_engine 的 ScopeMismatch bug。
    每个测试函数在独立 connection + 外层事务中运行，结束 rollback，不污染数据库。
    service 层用 flush() 不 commit()，事务由端点层 db_transaction 控制。
    首次运行时通过 Base.metadata.create_all 幂等创建缺失表（开发环境安全）。
    """
    from fastapi_app.shared_models import Base

    engine = create_async_engine(TEST_DATABASE_URL, echo=False, pool_pre_ping=True)
    try:
        # 确保表存在（幂等：CREATE TABLE IF NOT EXISTS，已存在则跳过）
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async with engine.connect() as conn:
            trans = await conn.begin()
            session_factory = async_sessionmaker(
                bind=conn, class_=AsyncSession, expire_on_commit=False,
            )
            async with session_factory() as session:
                try:
                    yield session
                finally:
                    await session.close()
            await trans.rollback()
    finally:
        await engine.dispose()


async def _create_pattern_maker(db, name='测试版师A'):
    """创建测试版师"""
    from fastapi_app.shared_models import PatternMaker
    maker = PatternMaker(name=name)
    db.add(maker)
    await db.flush()
    return maker


async def _create_supplier(db, name='测试供应商A'):
    """创建测试供应商"""
    from fastapi_app.shared_models import Supplier
    supplier = Supplier(name=name, contact_person='联系人', phone='13800138001', address='地址')
    db.add(supplier)
    await db.flush()
    return supplier


@pytest.mark.integration
class TestServiceIntegration:
    """Service 层集成测试 — 完整业务流程"""

    async def test_grouped_list_empty(self, cs_db):
        """分组查询：空数据返回空分组"""
        result = await get_grouped_list(cs_db)
        assert result['success'] is True
        assert result['groups'] == []
        assert result['total_projects'] == 0

    async def test_grouped_list_with_unclassified(self, cs_db):
        """分组查询：未关联版师的项目归入"未分类"分组"""
        # 创建无版师的项目
        await create_project(cs_db, product_name='未分类产品1')
        await create_project(cs_db, product_name='未分类产品2')
        await cs_db.flush()

        result = await get_grouped_list(cs_db)
        assert result['total_projects'] == 2
        assert len(result['groups']) == 1
        group = result['groups'][0]
        assert group['pattern_maker_name'] == '未分类'
        assert group['pattern_maker_id'] is None
        assert group['project_count'] == 2

    async def test_grouped_list_by_pattern_maker(self, cs_db):
        """分组查询：按版师分组聚合"""
        maker = await _create_pattern_maker(cs_db, '分组测试版师')
        await cs_db.flush()

        # 创建关联版师的项目
        await create_project(cs_db, product_name='版师产品1', pattern_maker_id=maker.id)
        # 创建无版师项目
        await create_project(cs_db, product_name='未分类产品')
        await cs_db.flush()

        result = await get_grouped_list(cs_db)
        assert result['total_projects'] == 2
        # 应有 2 个分组：版师分组 + 未分类
        assert len(result['groups']) == 2
        # 未分类始终最后
        assert result['groups'][-1]['pattern_maker_name'] == '未分类'
        # 版师分组在前
        maker_group = result['groups'][0]
        assert maker_group['pattern_maker_name'] == '分组测试版师'
        assert maker_group['project_count'] == 1

    async def test_grouped_list_keyword_search(self, cs_db):
        """分组查询：关键词搜索（序列号/产品名）"""
        await create_project(cs_db, product_name='毛绒玩具A')
        await create_project(cs_db, product_name='毛绒玩具B')
        await create_project(cs_db, product_name='其他产品')
        await cs_db.flush()

        result = await get_grouped_list(cs_db, keyword='毛绒玩具')
        assert result['total_projects'] == 2
        group = result['groups'][0]
        assert group['project_count'] == 2

    async def test_grouped_list_default_in_progress(self, cs_db):
        """分组查询：status 缺省默认只返回进行中项目（兜底，避免混入已完成项目）"""
        await create_project(cs_db, product_name='进行中项目')
        r2 = await create_project(cs_db, product_name='已完成项目')
        await cs_db.flush()
        await update_project_status(cs_db, r2['id'], status='completed')
        await cs_db.flush()

        # status 缺省：只返回进行中项目
        result = await get_grouped_list(cs_db)
        assert result['total_projects'] == 1
        projects = [p for g in result['groups'] for p in g['projects']]
        assert all(p['status'] == 'in_progress' for p in projects)
        assert all(p['id'] != r2['id'] for p in projects)

        # 显式传 'all'：返回全部状态的项目
        result_all = await get_grouped_list(cs_db, status='all')
        assert result_all['total_projects'] == 2
        assert len(result_all['groups']) == 1

    async def test_project_create_auto_t1(self, cs_db):
        """创建项目：自动生成序列号 + T1 基线版本"""
        result = await create_project(cs_db, product_name='T1基线测试')
        await cs_db.flush()

        assert 'id' in result
        assert 'sequence_no' in result
        # 序列号格式 CS-YYYYMMDD-XXXX
        assert result['sequence_no'].startswith('CS-')
        assert len(result['sequence_no'].split('-')) == 3

        # 验证 T1 基线版本自动创建
        from sqlalchemy import select

        from fastapi_app.shared_models import CustomerSamplingFabricVersion
        ver_result = await cs_db.execute(
            select(CustomerSamplingFabricVersion)
            .where(CustomerSamplingFabricVersion.project_id == result['id'])
        )
        versions = ver_result.scalars().all()
        assert len(versions) == 1
        assert versions[0].version_no == 'T1'
        assert versions[0].snapshot_data == []
        assert versions[0].change_summary is None

    async def test_project_detail(self, cs_db):
        """项目详情：含部位 + 版本列表"""
        r = await create_project(cs_db, product_name='详情测试')
        await cs_db.flush()

        detail = await get_project_detail(cs_db, r['id'])
        assert detail['id'] == r['id']
        assert detail['product_name'] == '详情测试'
        assert detail['current_version'] == 'T1'
        assert detail['parts'] == []
        assert len(detail['versions']) == 1
        assert detail['versions'][0]['version_no'] == 'T1'

    async def test_project_update_optimistic_lock(self, cs_db):
        """编辑项目：乐观锁 +1"""
        r = await create_project(cs_db, product_name='乐观锁测试')
        await cs_db.flush()

        detail = await get_project_detail(cs_db, r['id'])
        current_version = detail['version']

        # 正确 version 更新成功
        await update_project(cs_db, r['id'], product_name='更新后', version=current_version)
        await cs_db.flush()

        detail2 = await get_project_detail(cs_db, r['id'])
        assert detail2['product_name'] == '更新后'
        assert detail2['version'] == current_version + 1

        # 旧 version 应触发 ConflictError
        with pytest.raises(ConflictError):
            await update_project(cs_db, r['id'], product_name='冲突', version=current_version)

    async def test_project_update_pattern_maker(self, cs_db):
        """编辑项目：关联版师后冗余存储 pattern_maker_name"""
        maker = await _create_pattern_maker(cs_db, '关联版师')
        r = await create_project(cs_db, product_name='版师关联测试')
        await cs_db.flush()

        detail = await get_project_detail(cs_db, r['id'])
        await update_project(cs_db, r['id'], pattern_maker_id=maker.id, version=detail['version'])
        await cs_db.flush()

        detail2 = await get_project_detail(cs_db, r['id'])
        assert detail2['pattern_maker_id'] == maker.id
        assert detail2['pattern_maker_name'] == '关联版师'

    async def test_project_update_status(self, cs_db):
        """更新项目状态：置为已完成，详情与分组摘要均带状态，审计日志可追溯"""
        r = await create_project(cs_db, product_name='状态测试')
        await cs_db.flush()

        # 初始状态为进行中
        detail = await get_project_detail(cs_db, r['id'])
        assert detail['status'] == 'in_progress'

        # 更新为已完成
        await update_project_status(cs_db, r['id'], status='completed')
        await cs_db.flush()

        detail2 = await get_project_detail(cs_db, r['id'])
        assert detail2['status'] == 'completed'

        # 分组摘要同样带状态（status 缺省默认只返回进行中，此处显式传 'all' 才能看到已完成项目）
        grouped = await get_grouped_list(cs_db, status='all')
        summary = next(
            p for g in grouped['groups'] for p in g['projects'] if p['id'] == r['id']
        )
        assert summary['status'] == 'completed'

        # 审计日志记录状态变更
        logs = await list_change_logs(cs_db, r['id'])
        assert any(
            log['action'] == 'update_project_status' for log in logs['items']
        )

    async def test_part_crud_full_flow(self, cs_db):
        """部位 CRUD 完整流程"""
        r = await create_project(cs_db, product_name='部位CRUD测试')
        await cs_db.flush()

        # 新增部位
        part_r = await create_part(
            cs_db, r['id'],
            part_name='身体',
            sort_order=1,
            fabric_name='绒布',
            fabric_spec='100g',
            unit_price=10.5,
            delivery_days=7,
        )
        await cs_db.flush()
        assert 'id' in part_r

        # 查询部位列表
        parts = await list_parts(cs_db, r['id'])
        assert len(parts['items']) == 1
        assert parts['items'][0]['part_name'] == '身体'
        assert parts['items'][0]['fabric_name'] == '绒布'
        assert parts['items'][0]['unit_price'] == 10.5

        # 编辑部位
        part_id = parts['items'][0]['id']
        part_version = parts['items'][0]['version']
        await update_part(
            cs_db, part_id,
            fabric_name='棉布',
            unit_price=12.0,
            version=part_version,
        )
        await cs_db.flush()

        parts2 = await list_parts(cs_db, r['id'])
        assert parts2['items'][0]['fabric_name'] == '棉布'
        assert parts2['items'][0]['unit_price'] == 12.0
        assert parts2['items'][0]['version'] == part_version + 1

        # 删除部位
        await delete_part(cs_db, part_id)
        await cs_db.flush()
        parts3 = await list_parts(cs_db, r['id'])
        assert len(parts3['items']) == 0

    async def test_part_name_unique_per_project(self, cs_db):
        """部位名称同项目下唯一校验"""
        r = await create_project(cs_db, product_name='部位唯一性测试')
        await cs_db.flush()

        await create_part(cs_db, r['id'], part_name='身体')
        await cs_db.flush()

        # 同项目下重复部位名 → BusinessError
        with pytest.raises(BusinessError):
            await create_part(cs_db, r['id'], part_name='身体')

    async def test_part_name_unique_across_projects(self, cs_db):
        """不同项目下部位名可相同"""
        r1 = await create_project(cs_db, product_name='项目1')
        r2 = await create_project(cs_db, product_name='项目2')
        await cs_db.flush()

        await create_part(cs_db, r1['id'], part_name='身体')
        await cs_db.flush()
        # 不同项目同名部位应成功
        await create_part(cs_db, r2['id'], part_name='身体')
        await cs_db.flush()

    async def test_part_sort_order(self, cs_db):
        """部位按 sort_order 升序"""
        r = await create_project(cs_db, product_name='排序测试')
        await cs_db.flush()

        await create_part(cs_db, r['id'], part_name='头部', sort_order=2)
        await create_part(cs_db, r['id'], part_name='身体', sort_order=1)
        await create_part(cs_db, r['id'], part_name='四肢', sort_order=3)
        await cs_db.flush()

        parts = await list_parts(cs_db, r['id'])
        names = [p['part_name'] for p in parts['items']]
        assert names == ['身体', '头部', '四肢']

    async def test_version_create_with_diff(self, cs_db):
        """版本创建：快照 + diff 计算

        流程：创建项目(T1) → 新增部位 → 创建 T2 → T2 应有 diff
        """
        r = await create_project(cs_db, product_name='版本diff测试')
        await cs_db.flush()

        # 新增部位
        await create_part(
            cs_db, r['id'],
            part_name='身体',
            fabric_name='绒布',
            unit_price=10,
        )
        await cs_db.flush()

        # 创建 T2
        v2 = await create_version(cs_db, r['id'], reason='新增身体部位')
        await cs_db.flush()
        assert v2['version_no'] == 'T2'

        # 查询 T2 详情：应返回 change_summary（diff）
        detail_v2 = await get_version_detail(cs_db, v2['version_id'])
        assert detail_v2['version_no'] == 'T2'
        assert detail_v2['is_baseline'] is False
        assert detail_v2['degraded'] is False
        assert detail_v2['full_snapshot'] is None
        assert detail_v2['change_summary'] is not None
        # T1 快照为空，T2 有"身体"部位 → diff 应为 add
        assert len(detail_v2['change_summary']) == 1
        assert detail_v2['change_summary'][0]['change_type'] == 'add'
        assert detail_v2['change_summary'][0]['part_name'] == '身体'

    async def test_version_detail_t1_baseline(self, cs_db):
        """版本详情：T1 返回 full_snapshot，change_summary=null"""
        r = await create_project(cs_db, product_name='T1详情测试')
        await cs_db.flush()

        # 查询 T1
        from sqlalchemy import select

        from fastapi_app.shared_models import CustomerSamplingFabricVersion
        ver_result = await cs_db.execute(
            select(CustomerSamplingFabricVersion)
            .where(CustomerSamplingFabricVersion.project_id == r['id'])
        )
        t1 = ver_result.scalars().first()

        detail = await get_version_detail(cs_db, t1.id)
        assert detail['version_no'] == 'T1'
        assert detail['is_baseline'] is True
        assert detail['degraded'] is False
        assert detail['full_snapshot'] == []
        assert detail['change_summary'] is None

    async def test_version_detail_t2_modify_diff(self, cs_db):
        """版本详情：T3 相对 T2 的修改类 diff"""
        r = await create_project(cs_db, product_name='T3修改diff测试')
        await cs_db.flush()

        # 新增部位 → T2
        await create_part(cs_db, r['id'], part_name='身体', fabric_name='绒布', unit_price=10)
        await cs_db.flush()
        await create_version(cs_db, r['id'])
        await cs_db.flush()

        # 修改部位布料 → T3
        parts = await list_parts(cs_db, r['id'])
        part = parts['items'][0]
        await update_part(cs_db, part['id'], fabric_name='棉布', unit_price=15, version=part['version'])
        await cs_db.flush()
        v3 = await create_version(cs_db, r['id'])
        await cs_db.flush()

        # T3 diff 应为 modify
        detail_v3 = await get_version_detail(cs_db, v3['version_id'])
        assert detail_v3['version_no'] == 'T3'
        assert detail_v3['change_summary'] is not None
        assert len(detail_v3['change_summary']) == 1
        assert detail_v3['change_summary'][0]['change_type'] == 'modify'
        assert detail_v3['change_summary'][0]['part_name'] == '身体'
        changed_fields = {fd['field'] for fd in detail_v3['change_summary'][0]['field_diffs']}
        assert 'fabric_name' in changed_fields
        assert 'unit_price' in changed_fields

    async def test_version_detail_delete_diff(self, cs_db):
        """版本详情：删除部位的 diff"""
        r = await create_project(cs_db, product_name='删除diff测试')
        await cs_db.flush()

        # 新增两个部位 → T2
        await create_part(cs_db, r['id'], part_name='身体')
        await create_part(cs_db, r['id'], part_name='头部')
        await cs_db.flush()
        await create_version(cs_db, r['id'])
        await cs_db.flush()

        # 删除"头部" → T3
        parts = await list_parts(cs_db, r['id'])
        head = next(p for p in parts['items'] if p['part_name'] == '头部')
        await delete_part(cs_db, head['id'])
        await cs_db.flush()
        v3 = await create_version(cs_db, r['id'])
        await cs_db.flush()

        # T3 diff 应为 delete
        detail_v3 = await get_version_detail(cs_db, v3['version_id'])
        assert detail_v3['change_summary'] is not None
        types = {d['change_type'] for d in detail_v3['change_summary']}
        assert 'delete' in types
        delete_record = next(d for d in detail_v3['change_summary'] if d['change_type'] == 'delete')
        assert delete_record['part_name'] == '头部'

    async def test_version_list_ordered(self, cs_db):
        """版本列表按 version_no 升序"""
        r = await create_project(cs_db, product_name='版本列表测试')
        await cs_db.flush()

        await create_part(cs_db, r['id'], part_name='身体')
        await cs_db.flush()
        await create_version(cs_db, r['id'])
        await cs_db.flush()
        await create_version(cs_db, r['id'])
        await cs_db.flush()

        versions = await list_versions(cs_db, r['id'])
        assert len(versions['items']) == 3
        assert [v['version_no'] for v in versions['items']] == ['T1', 'T2', 'T3']

    async def test_change_logs_recorded(self, cs_db):
        """变更日志：关键操作记录审计日志"""
        r = await create_project(cs_db, product_name='日志测试')
        await cs_db.flush()

        # create_project 已写日志
        logs = await list_change_logs(cs_db, r['id'])
        assert logs['total'] >= 1
        actions = [log['action'] for log in logs['items']]
        assert 'create_project' in actions

        # 新增部位 → create_part 日志
        await create_part(cs_db, r['id'], part_name='身体')
        await cs_db.flush()
        logs2 = await list_change_logs(cs_db, r['id'])
        actions2 = [log['action'] for log in logs2['items']]
        assert 'create_part' in actions2

        # 创建版本 → create_version 日志
        await create_version(cs_db, r['id'])
        await cs_db.flush()
        logs3 = await list_change_logs(cs_db, r['id'])
        actions3 = [log['action'] for log in logs3['items']]
        assert 'create_version' in actions3

    async def test_change_logs_paginated(self, cs_db):
        """变更日志分页"""
        r = await create_project(cs_db, product_name='分页日志测试')
        await cs_db.flush()

        logs = await list_change_logs(cs_db, r['id'], page=1, per_page=1)
        assert logs['pages'] >= 1
        assert len(logs['items']) <= 1

    async def test_project_delete_cascade(self, cs_db):
        """删除项目：级联删除部位/版本/日志"""
        r = await create_project(cs_db, product_name='级联删除测试')
        await cs_db.flush()
        await create_part(cs_db, r['id'], part_name='身体')
        await cs_db.flush()
        await create_version(cs_db, r['id'])
        await cs_db.flush()

        project_id = r['id']
        await delete_project(cs_db, project_id)
        await cs_db.flush()

        # 项目已删除 → NotFoundError
        with pytest.raises(NotFoundError):
            await get_project_detail(cs_db, project_id)

    async def test_grouped_list_pattern_maker_filter(self, cs_db):
        """分组查询：pattern_maker_id 筛选"""
        maker = await _create_pattern_maker(cs_db, '筛选版师')
        await cs_db.flush()

        await create_project(cs_db, product_name='版师项目', pattern_maker_id=maker.id)
        await create_project(cs_db, product_name='未分类项目')
        await cs_db.flush()

        result = await get_grouped_list(cs_db, pattern_maker_id=maker.id)
        assert result['total_projects'] == 1
        assert result['groups'][0]['pattern_maker_name'] == '筛选版师'
