"""
BOM 配置·角色字段测试

覆盖：get_bom 返回角色列表；save_bom 角色增删改 + 按角色归属物料；
copy_bom / preview_bom 角色复制；删除角色级联清理物料；无角色默认 BOM 不受影响。
"""
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from fastapi_app.services import bom_service


class TestHasBom:
    """has_bom 填充物判定含各角色行"""

    def test_role_filling_only_counts_as_bom(self):
        p = _mock_product(roles=[], has_bom=False)
        m = MagicMock()
        m.cotton_usage = Decimal('30')
        m.role_id = 12
        p.material_rows = [m]  # 已加载全部填充行
        p.material = None
        assert bom_service.has_bom(p) is True

    def test_fallback_to_product_material(self):
        """未加载 material_rows 的调用方回退产品级 material（兼容既有测试）"""
        p = _mock_product(roles=[], has_bom=False)
        mm = MagicMock()
        mm.cotton_usage = Decimal('100')
        p.material = mm
        p.material_rows = None
        assert bom_service.has_bom(p) is True

    def test_zero_cotton_returns_false(self):
        p = _mock_product(roles=[], has_bom=False)
        m = MagicMock()
        m.cotton_usage = Decimal('0')
        p.material_rows = [m]
        p.material = None
        assert bom_service.has_bom(p) is False


def _mock_product(roles=None, materials=None, has_bom=True):
    product = MagicMock()
    product.id = 1
    product.name = '测试产品'
    product.barcode = '6901234567890'
    product.roles = roles or []
    product.material = None
    product.material_rows = None
    product.fabrics = []
    product.accessories = []
    product.default_bom_label = None
    product.has_bom = MagicMock(return_value=has_bom)
    product.get_all_materials = MagicMock(return_value=materials or [])
    return product


def _mock_role(rid, name, global_role_id=None):
    role = MagicMock()
    role.id = rid
    role.role_name = name
    role.global_role_id = global_role_id
    # lazy='raise' 关系：测试桩显式置 None，_role_display_name 才会回退到 role_name 镜像列
    role.global_role = None
    return role


def _mock_execute_result(product):
    result = MagicMock()
    result.scalars.return_value.first.return_value = product
    return result


class TestGetBom:
    """get_bom 返回角色列表（角色产品私有：仅 ``{id, name}``，按 (name, id) 升序）"""

    async def test_get_bom_returns_roles(self, mock_db):
        product = _mock_product(roles=[_mock_role(11, '白雪公主'), _mock_role(12, '灰姑娘')])
        mock_db.execute = AsyncMock(return_value=_mock_execute_result(product))

        result = await bom_service.get_bom(mock_db, 1)

        # 排序键 (name, id)：'灰姑娘'(U+7070) < '白雪公主'(U+767D)
        assert result['roles'] == [
            {'id': 12, 'name': '灰姑娘'},
            {'id': 11, 'name': '白雪公主'},
        ]

    async def test_get_bom_roles_sorted_by_name_then_id(self, mock_db):
        """排序按 (name, id) 稳定升序（角色私有：不再有 global_role_id）。"""
        product = _mock_product(roles=[
            _mock_role(13, '爸爸'),
            _mock_role(11, '白雪公主'),
            _mock_role(12, '爸爸'),
        ])
        mock_db.execute = AsyncMock(return_value=_mock_execute_result(product))

        result = await bom_service.get_bom(mock_db, 1)

        # 排序键 (name, id)：'爸爸'(U+7238) < '白雪公主'(U+767D)；
        # 同名 '爸爸' 再按 id 升序（12 先于 13）——验证 id 兜底不依赖插入顺序。
        assert result['roles'] == [
            {'id': 12, 'name': '爸爸'},
            {'id': 13, 'name': '爸爸'},
            {'id': 11, 'name': '白雪公主'},
        ]

    async def test_get_bom_no_roles_returns_empty(self, mock_db):
        product = _mock_product(roles=[])
        mock_db.execute = AsyncMock(return_value=_mock_execute_result(product))

        result = await bom_service.get_bom(mock_db, 1)

        assert result['roles'] == []

    async def test_get_bom_returns_default_bom_label(self, mock_db):
        product = _mock_product(roles=[])
        product.default_bom_label = '基础款BOM'
        mock_db.execute = AsyncMock(return_value=_mock_execute_result(product))

        result = await bom_service.get_bom(mock_db, 1)

        assert result['default_bom_label'] == '基础款BOM'


class TestSaveBom:
    """save_bom 角色 CRUD + 按角色物料"""

    def _setup_db(self, mock_db, product):
        product_result = _mock_execute_result(product)
        empty_result = MagicMock()
        empty_result.scalars.return_value.first.return_value = None
        empty_result.scalars.return_value.all.return_value = []
        counter = {'n': 0}
        # save_bom 现在会先按名称解析供应商（对 supplier 表做 select/insert）。
        # 用「语句文本是否含 supplier」把这类调用与既有的「按调用序号」断言解耦，
        # 避免两套断言互相干扰（供应商查询统一返回空结果，不触发真实建卡逻辑的断言）。
        supplier_result = MagicMock()
        supplier_result.all.return_value = []

        async def _execute_side_effect(stmt=None, *args, **kwargs):
            s = str(stmt).lower() if stmt is not None else ''
            # 只认「纯供应商」语句：material 表的 select 也带 supplier_id/name 列，
            # 用 'product' 是否出现把二者区分开，避免误拦填充/面料/辅料查询。
            if 'supplier' in s and 'product' not in s:
                return supplier_result
            counter['n'] += 1
            return product_result if counter['n'] == 1 else empty_result

        mock_db.execute = AsyncMock(side_effect=_execute_side_effect)
        # AsyncSession.add 是同步方法；顺带给新建 ProductRole 分配自增 id，
        # 以便断言「物料经 role_key 归属到新角色行 id」。
        _id_seq = {'n': 1000}

        def _add(obj):
            if isinstance(obj, bom_service.ProductRole) and getattr(obj, 'id', None) is None:
                obj.id = _id_seq['n']
                _id_seq['n'] += 1

        mock_db.add = MagicMock(side_effect=_add)
        # AsyncSession.delete 是**协程**（实测 iscoroutinefunction=True）。
        # 早先误设为 MagicMock() → `db.delete(role)` 漏 await 时测试仍通过，
        # 过于宽容的 mock 掩盖了真实缺陷。必须用 AsyncMock。
        mock_db.delete = AsyncMock()
        mock_db.flush = AsyncMock()
        return empty_result

    def _added_of(self, mock_db, cls):
        return [c.args[0] for c in mock_db.add.call_args_list if isinstance(c.args[0], cls)]

    async def test_create_role(self, mock_db):
        product = _mock_product(roles=[])
        self._setup_db(mock_db, product)

        await bom_service.save_bom(mock_db, 1, {'roles': [{'role_name': '白雪公主'}], 'filling': None, 'fabrics': [], 'accessories': []}, 'tester')

        roles = self._added_of(mock_db, bom_service.ProductRole)
        assert len(roles) == 1
        assert roles[0].product_id == 1
        assert roles[0].role_name == '白雪公主'

    async def test_create_role_skips_empty_name(self, mock_db):
        product = _mock_product(roles=[])
        self._setup_db(mock_db, product)

        await bom_service.save_bom(mock_db, 1, {'roles': [{'role_name': '  '}], 'filling': None, 'fabrics': [], 'accessories': []}, 'tester')

        assert self._added_of(mock_db, bom_service.ProductRole) == []

    async def test_rename_role_writes_log(self, mock_db):
        role = _mock_role(11, '白雪公主')
        product = _mock_product(roles=[role])
        self._setup_db(mock_db, product)

        await bom_service.save_bom(mock_db, 1, {'roles': [{'id': 11, 'role_name': '灰姑娘'}], 'filling': None, 'fabrics': [], 'accessories': []}, 'tester')

        assert role.role_name == '灰姑娘'
        logs = self._added_of(mock_db, bom_service.ModificationLog)
        assert any(
            l.target_type == 'role' and l.field_name == 'role_name'
            and l.old_value == '白雪公主' and l.new_value == '灰姑娘'
            for l in logs
        )

    async def test_delete_role_not_in_payload(self, mock_db):
        role_a = _mock_role(11, '白雪公主')
        role_b = _mock_role(12, '灰姑娘')
        product = _mock_product(roles=[role_a, role_b])
        self._setup_db(mock_db, product)

        await bom_service.save_bom(mock_db, 1, {'roles': [{'id': 11, 'role_name': '白雪公主'}], 'filling': None, 'fabrics': [], 'accessories': []}, 'tester')

        deleted_ids = [c.args[0].id for c in mock_db.delete.call_args_list]
        assert 12 in deleted_ids
        logs = self._added_of(mock_db, bom_service.ModificationLog)
        assert any(
            l.target_type == 'role' and l.field_name == 'deleted' and l.old_value == '灰姑娘'
            for l in logs
        )

    async def test_no_roles_key_keeps_roles(self, mock_db):
        role_a = _mock_role(11, '白雪公主')
        product = _mock_product(roles=[role_a])
        self._setup_db(mock_db, product)

        await bom_service.save_bom(mock_db, 1, {'filling': None, 'fabrics': [], 'accessories': []}, 'tester')

        assert mock_db.delete.call_count == 0
        assert self._added_of(mock_db, bom_service.ProductRole) == []

    async def test_save_default_bom_label(self, mock_db):
        product = _mock_product(roles=[])
        self._setup_db(mock_db, product)

        await bom_service.save_bom(
            mock_db, 1,
            {'default_bom_label': '基础款BOM', 'roles': [], 'filling': None, 'fabrics': [], 'accessories': []},
            'tester',
        )

        assert product.default_bom_label == '基础款BOM'

    async def test_save_without_label_keeps_unchanged(self, mock_db):
        product = _mock_product(roles=[])
        product.default_bom_label = '原有名称'
        self._setup_db(mock_db, product)

        await bom_service.save_bom(mock_db, 1, {'roles': [], 'filling': None, 'fabrics': [], 'accessories': []}, 'tester')

        assert product.default_bom_label == '原有名称'

    async def test_fabric_created_with_role_id(self, mock_db):
        product = _mock_product(roles=[])
        self._setup_db(mock_db, product)

        await bom_service.save_bom(
            mock_db, 1,
            {'roles': [], 'filling': None,
             'fabrics': [{'fabric_name': '雪纺', 'specification': '白', 'unit': '码', 'quantity': 1, 'role_id': 12}],
             'accessories': []},
            'tester',
        )

        fabrics = self._added_of(mock_db, bom_service.ProductFabric)
        assert len(fabrics) == 1
        assert fabrics[0].role_id == 12

    async def test_filling_created_per_role(self, mock_db):
        product = _mock_product(roles=[])
        self._setup_db(mock_db, product)

        await bom_service.save_bom(
            mock_db, 1,
            {'roles': [], 'filling': {'cotton_usage': 35, 'role_id': 12, 'supplier_name': '嘉丰'},
             'fabrics': [], 'accessories': []},
            'tester',
        )

        fillings = self._added_of(mock_db, bom_service.ProductMaterial)
        assert len(fillings) == 1
        assert fillings[0].role_id == 12
        assert float(fillings[0].cotton_usage) == 35

    async def test_new_role_material_via_role_key(self, mock_db):
        """新建角色携带 role_key，其物料经 role_key 解析归属（不抛错且成功创建）"""
        product = _mock_product(roles=[])
        self._setup_db(mock_db, product)

        await bom_service.save_bom(
            mock_db, 1,
            {'roles': [{'role_key': 'rk-1', 'role_name': '新角色'}], 'filling': None,
             'fabrics': [{'fabric_name': '面料A', 'specification': '白', 'unit': '码',
                          'quantity': 1, 'role_key': 'rk-1'}],
             'accessories': []},
            'tester',
        )

        roles = self._added_of(mock_db, bom_service.ProductRole)
        assert len(roles) == 1
        assert roles[0].role_name == '新角色'
        fabrics = self._added_of(mock_db, bom_service.ProductFabric)
        assert len(fabrics) == 1
        assert fabrics[0].fabric_name == '面料A'

    async def test_save_role_from_name_creates_product_role(self, mock_db):
        """仅带名称的角色项 → 本产品新建 ProductRole（角色私有，无全局角色层）。"""
        product = _mock_product(roles=[])
        self._setup_db(mock_db, product)

        await bom_service.save_bom(
            mock_db, 1,
            {'roles': [{'role_name': '爸爸'}],
             'filling': None, 'fabrics': [], 'accessories': []},
            'tester',
        )

        roles = self._added_of(mock_db, bom_service.ProductRole)
        assert len(roles) == 1
        assert roles[0].product_id == 1
        assert roles[0].role_name == '爸爸'
        # 遗留的 global_role_id 即便被旧客户端提交也被忽略（不再写该列）
        assert getattr(roles[0], 'global_role_id', None) is None

    async def test_save_role_key_maps_material_to_new_role(self, mock_db):
        """role_key 路径：本产品新建 ProductRole，物料经 role_key 归属该新行。"""
        product = _mock_product(roles=[])
        self._setup_db(mock_db, product)

        await bom_service.save_bom(
            mock_db, 1,
            {'roles': [{'role_key': 'rk-9', 'role_name': '全新角色'}], 'filling': None,
             'fabrics': [{'fabric_name': '面料X', 'specification': 'S', 'unit': '码',
                          'quantity': 1, 'role_key': 'rk-9'}],
             'accessories': []},
            'tester',
        )

        roles = self._added_of(mock_db, bom_service.ProductRole)
        assert len(roles) == 1
        assert roles[0].role_name == '全新角色'
        fabrics = self._added_of(mock_db, bom_service.ProductFabric)
        assert len(fabrics) == 1
        assert fabrics[0].role_id == roles[0].id, '面料须归属 role_key 解析出的新角色'

    async def test_filling_not_in_payload_is_deleted(self, mock_db):
        """F2 回归：未被提交的填充行在保存时被删除（不残留幽灵行）"""
        product = _mock_product(roles=[])
        product_result = _mock_execute_result(product)
        material_row = MagicMock()
        material_row.id = 99
        material_row.cotton_usage = Decimal('35')
        material_row.supplier_name = '旧供应商'
        material_row.specification = ''
        mat_result = MagicMock()
        mat_result.scalars.return_value.first.return_value = material_row
        mat_result.scalars.return_value.all.return_value = [material_row]
        empty = MagicMock()
        empty.scalars.return_value.first.return_value = None
        empty.scalars.return_value.all.return_value = []

        seq = iter([product_result, mat_result, empty, empty, mat_result, empty])
        supplier_result = MagicMock()
        supplier_result.all.return_value = []

        async def _side_effect(stmt=None, *args, **kwargs):
            # 供应商解析查询（select/insert supplier）不占用下面按序排列的结果
            s = str(stmt).lower() if stmt is not None else ''
            # 只认「纯供应商」语句：material 表的 select 也带 supplier_id/name 列，
            # 用 'product' 是否出现把二者区分开，避免误拦填充/面料/辅料查询。
            if 'supplier' in s and 'product' not in s:
                return supplier_result
            try:
                return next(seq)
            except StopIteration:
                return empty

        mock_db.execute = AsyncMock(side_effect=_side_effect)
        mock_db.add = MagicMock()       # AsyncSession.add 是同步方法
        # AsyncSession.delete 是**协程**（实测 iscoroutinefunction=True）。
        # 早先误设为 MagicMock() → `db.delete(role)` 漏 await 时测试仍通过，
        # 过于宽容的 mock 掩盖了真实缺陷。必须用 AsyncMock。
        mock_db.delete = AsyncMock()
        mock_db.flush = AsyncMock()

        await bom_service.save_bom(
            mock_db, 1,
            {'roles': [], 'fillings': [{'id': 9, 'cotton_usage': 35, 'role_id': 12, 'supplier_name': '嘉丰'}],
             'fabrics': [], 'accessories': []},
            'tester',
        )

        delete_calls = [c.args[0] for c in mock_db.execute.call_args_list
                        if c.args and c.args[0].__class__.__name__ == 'Delete']
        assert len(delete_calls) == 1
        assert 'product_material' in str(delete_calls[0])


class TestCopyBom:
    """copy_bom 角色及其物料复制"""

    def _source_product(self):
        # 源角色携带 global_role_id（迁移 045 后 ProductRole.global_role_id 为 NOT NULL）：
        # copy_bom 的源角色复制走「携带 gid」快路径，不再触发历史遗留补齐查询。
        role_a = _mock_role(11, '白雪公主', global_role_id=101)
        role_b = _mock_role(12, '灰姑娘', global_role_id=102)

        fabric_default = MagicMock()
        fabric_default.role_id = None
        fabric_default.fabric_name = '默认面料'
        fabric_default.quantity = 1

        fabric_a = MagicMock()
        fabric_a.role_id = 11
        fabric_a.fabric_name = '白雪公主裙面料'
        fabric_a.quantity = 1.2

        accessory_b = MagicMock()
        accessory_b.role_id = 12
        accessory_b.accessory_name = '灰姑娘水晶鞋'
        accessory_b.quantity = 1
        accessory_b.material_category = 'accessory'

        material_default = MagicMock()
        material_default.role_id = None
        material_default.cotton_usage = 50

        material_b = MagicMock()
        material_b.role_id = 12
        material_b.cotton_usage = 32

        src = _mock_product(roles=[role_a, role_b], has_bom=True)
        src.fabrics = [fabric_default, fabric_a]
        src.accessories = [accessory_b]
        src.material = material_default
        src.name = '源产品'
        return src, [material_default, material_b]

    def _setup(self, mock_db, src, src_materials, overwrite):
        src_result = MagicMock()
        src_result.scalar_one_or_none.return_value = src
        tgt = _mock_product(roles=[], has_bom=False)
        tgt.name = '目标产品'
        tgt_result = MagicMock()
        tgt_result.scalar_one_or_none.return_value = tgt
        mat_result = MagicMock()
        mat_result.scalars.return_value.all.return_value = src_materials
        fallback = MagicMock()
        fallback.scalar_one_or_none.return_value = None
        fallback.scalars.return_value.all.return_value = []

        calls = iter([src_result, tgt_result, mat_result, fallback, fallback, fallback, fallback, fallback])
        mock_db.execute = AsyncMock(side_effect=lambda *a, **k: next(calls))
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()
        return tgt

    async def test_copy_creates_roles_and_role_materials(self, mock_db):
        src, src_materials = self._source_product()
        self._setup(mock_db, src, src_materials, overwrite=False)

        result = await bom_service.copy_bom(mock_db, 2, {'source_product_id': 1, 'overwrite': False}, 'tester')

        roles = [c.args[0] for c in mock_db.add.call_args_list if isinstance(c.args[0], bom_service.ProductRole)]
        assert len(roles) == 2
        assert {r.role_name for r in roles} == {'白雪公主', '灰姑娘'}
        assert all(r.product_id == 2 for r in roles)
        # 角色面料 + 产品级面料均已复制
        fabrics = [c.args[0] for c in mock_db.add.call_args_list if isinstance(c.args[0], bom_service.ProductFabric)]
        assert len(fabrics) == 2
        assert any(f.fabric_name == '默认面料' for f in fabrics)
        assert any(f.fabric_name == '白雪公主裙面料' for f in fabrics)
        assert result['copied_count'] >= 6  # 2角色+2面料+1辅料+2填充(含默认)

    async def test_copy_without_overwrite_keeps_target_roles(self, mock_db):
        src, src_materials = self._source_product()
        self._setup(mock_db, src, src_materials, overwrite=False)

        await bom_service.copy_bom(mock_db, 2, {'source_product_id': 1, 'overwrite': False}, 'tester')

        delete_calls = [c for c in mock_db.execute.call_args_list if c.args and c.args[0].__class__.__name__ == 'Delete']
        assert len(delete_calls) == 0

    async def test_copy_overwrite_deletes_target_roles(self, mock_db):
        src, src_materials = self._source_product()
        self._setup(mock_db, src, src_materials, overwrite=True)

        await bom_service.copy_bom(mock_db, 2, {'source_product_id': 1, 'overwrite': True}, 'tester')

        delete_calls = [c.args[0] for c in mock_db.execute.call_args_list if c.args and c.args[0].__class__.__name__ == 'Delete']
        # 覆盖模式：删目标角色 + 三张物料表
        assert len(delete_calls) == 4
        target_role_delete = next(
            c for c in delete_calls if hasattr(c, 'whereclause')
            and 'product_role' in str(c)
        )
        assert target_role_delete is not None

    # ===== 目标角色模式（传 role_id）=====
    def _setup_role(self, mock_db, src, src_materials, target_role_id=21):
        """构造目标角色模式：目标产品携带一个角色，物料查询顺序为 源产品/目标产品/源填充物。"""
        src_result = MagicMock()
        src_result.scalar_one_or_none.return_value = src
        tgt = _mock_product(roles=[_mock_role(target_role_id, '目标角色')], has_bom=True)
        tgt.name = '目标产品'
        tgt_result = MagicMock()
        tgt_result.scalar_one_or_none.return_value = tgt
        mat_result = MagicMock()
        mat_result.scalars.return_value.all.return_value = src_materials
        fallback = MagicMock()
        fallback.scalar_one_or_none.return_value = None
        fallback.scalars.return_value.all.return_value = []

        calls = iter([src_result, tgt_result, mat_result, fallback, fallback, fallback, fallback, fallback])
        mock_db.execute = AsyncMock(side_effect=lambda *a, **k: next(calls))
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()
        return tgt

    def _added_of(self, mock_db, cls):
        return [c.args[0] for c in mock_db.add.call_args_list if isinstance(c.args[0], cls)]

    async def test_copy_into_role_assigns_role_id(self, mock_db):
        """传 role_id：物料全部归属该角色，且不新建任何 ProductRole。"""
        src, src_materials = self._source_product()
        self._setup_role(mock_db, src, src_materials, target_role_id=21)

        result = await bom_service.copy_bom(
            mock_db, 2, {'source_product_id': 1, 'overwrite': False, 'role_id': 21}, 'tester',
        )

        assert self._added_of(mock_db, bom_service.ProductRole) == []
        fabrics = self._added_of(mock_db, bom_service.ProductFabric)
        accessories = self._added_of(mock_db, bom_service.ProductAccessory)
        materials = self._added_of(mock_db, bom_service.ProductMaterial)
        assert fabrics and all(f.role_id == 21 for f in fabrics)
        assert all(a.role_id == 21 for a in accessories)
        assert materials and all(m.role_id == 21 for m in materials)
        # 仅复制默认作用域：默认面料 + 产品级填充
        assert result['copied_count'] == 2
        assert result['target_role']['id'] == 21
        # 角色11面料 + 角色12辅料 + 角色12填充
        assert result['skipped_role_items'] == 3

    async def test_copy_into_role_overwrite_only_scoped_to_role(self, mock_db):
        """传 role_id + overwrite：只删该角色名下物料行，绝不删 ProductRole。"""
        src, src_materials = self._source_product()
        self._setup_role(mock_db, src, src_materials, target_role_id=21)

        await bom_service.copy_bom(
            mock_db, 2, {'source_product_id': 1, 'overwrite': True, 'role_id': 21}, 'tester',
        )

        delete_calls = [c.args[0] for c in mock_db.execute.call_args_list
                        if c.args and c.args[0].__class__.__name__ == 'Delete']
        assert len(delete_calls) == 3
        assert not any('product_role' in str(c) for c in delete_calls)
        tables = {
            next(t for t in ('product_fabric', 'product_accessory', 'product_material') if t in str(c))
            for c in delete_calls
        }
        assert tables == {'product_fabric', 'product_accessory', 'product_material'}
        # 每条删除都限定 role_id
        assert all('role_id' in str(c) for c in delete_calls)

    async def test_copy_into_role_rejects_foreign_role(self, mock_db):
        """role_id 不属于目标产品时抛 ValueError，且不写入任何数据。"""
        src, src_materials = self._source_product()
        self._setup_role(mock_db, src, src_materials, target_role_id=99)

        with pytest.raises(ValueError, match='目标角色不存在或不属于该产品'):
            await bom_service.copy_bom(
                mock_db, 2, {'source_product_id': 1, 'overwrite': False, 'role_id': 21}, 'tester',
            )

        assert mock_db.add.call_count == 0

    async def test_copy_into_role_conflict_when_role_has_materials(self, mock_db):
        """目标角色已有物料且未覆盖 → 抛冲突错误。"""
        src, src_materials = self._source_product()
        tgt = self._setup_role(mock_db, src, src_materials, target_role_id=21)
        existing = MagicMock()
        existing.role_id = 21
        tgt.fabrics = [existing]

        with pytest.raises(ValueError, match='目标角色已有BOM表'):
            await bom_service.copy_bom(
                mock_db, 2, {'source_product_id': 1, 'overwrite': False, 'role_id': 21}, 'tester',
            )

        assert mock_db.add.call_count == 0

    # ===== 目标角色名模式（传 role_name，支持前端未保存的新角色）=====
    def _setup_role_by_name(self, mock_db, src, src_materials, target_roles=None, new_role_id=31,
                            lookup_role_name=None):
        """构造目标角色名模式：目标产品携带给定角色列表；新建角色时 db.add 负责分配 id。

        角色为产品私有：``_resolve_role_by_name`` 只在本产品内按名复用/新建，**不再**查
        全局角色字典，故无额外 ``db.execute`` 槽位。
        """
        targets = list(target_roles or [])
        src_result = MagicMock()
        src_result.scalar_one_or_none.return_value = src
        tgt = _mock_product(roles=targets, has_bom=True)
        tgt.name = '目标产品'
        tgt_result = MagicMock()
        tgt_result.scalar_one_or_none.return_value = tgt
        mat_result = MagicMock()
        mat_result.scalars.return_value.all.return_value = src_materials
        fallback = MagicMock()
        fallback.scalar_one_or_none.return_value = None
        fallback.scalars.return_value.all.return_value = []

        calls = iter([src_result, tgt_result, mat_result, fallback, fallback, fallback, fallback, fallback])
        mock_db.execute = AsyncMock(side_effect=lambda *a, **k: next(calls))

        def _add(obj):
            # 模拟 DB 自增主键：新建 ProductRole 时补上 id
            if isinstance(obj, bom_service.ProductRole) and getattr(obj, 'id', None) is None:
                obj.id = new_role_id

        mock_db.add = MagicMock(side_effect=_add)
        mock_db.flush = AsyncMock()
        return tgt

    async def test_copy_into_role_by_name_reuses_existing_role(self, mock_db):
        """传 role_name 且目标产品已有同名角色 → 复用该角色，不新建 ProductRole。"""
        src, src_materials = self._source_product()
        self._setup_role_by_name(mock_db, src, src_materials, target_roles=[_mock_role(21, '目标角色')],
                                 lookup_role_name='目标角色')

        result = await bom_service.copy_bom(
            mock_db, 2, {'source_product_id': 1, 'overwrite': False, 'role_name': '目标角色'}, 'tester',
        )

        assert self._added_of(mock_db, bom_service.ProductRole) == []
        fabrics = self._added_of(mock_db, bom_service.ProductFabric)
        accessories = self._added_of(mock_db, bom_service.ProductAccessory)
        materials = self._added_of(mock_db, bom_service.ProductMaterial)
        assert fabrics and all(f.role_id == 21 for f in fabrics)
        assert all(a.role_id == 21 for a in accessories)
        assert materials and all(m.role_id == 21 for m in materials)
        assert result['target_role'] == {'id': 21, 'name': '目标角色'}

    async def test_copy_into_role_by_name_creates_role_when_missing(self, mock_db):
        """传 role_name 且目标产品无该角色 → 新建 ProductRole，物料归属新角色 id。"""
        src, src_materials = self._source_product()
        self._setup_role_by_name(mock_db, src, src_materials, target_roles=[], new_role_id=31,
                                 lookup_role_name='新建角色')

        result = await bom_service.copy_bom(
            mock_db, 2, {'source_product_id': 1, 'overwrite': False, 'role_name': '新建角色'}, 'tester',
        )

        roles = self._added_of(mock_db, bom_service.ProductRole)
        assert len(roles) == 1
        assert roles[0].role_name == '新建角色'
        assert roles[0].product_id == 2
        assert roles[0].id == 31
        fabrics = self._added_of(mock_db, bom_service.ProductFabric)
        accessories = self._added_of(mock_db, bom_service.ProductAccessory)
        materials = self._added_of(mock_db, bom_service.ProductMaterial)
        assert fabrics and all(f.role_id == 31 for f in fabrics)
        assert all(a.role_id == 31 for a in accessories)
        assert materials and all(m.role_id == 31 for m in materials)
        assert result['copied_count'] == 2
        assert result['target_role'] == {'id': 31, 'name': '新建角色'}

    async def test_role_id_takes_precedence_over_role_name(self, mock_db):
        """同时传 role_id 和 role_name → 以 role_id 为准，role_name 被忽略。"""
        src, src_materials = self._source_product()
        self._setup_role(mock_db, src, src_materials, target_role_id=21)

        result = await bom_service.copy_bom(
            mock_db, 2,
            {'source_product_id': 1, 'overwrite': False, 'role_id': 21, 'role_name': '另一个角色'},
            'tester',
        )

        assert self._added_of(mock_db, bom_service.ProductRole) == []
        fabrics = self._added_of(mock_db, bom_service.ProductFabric)
        accessories = self._added_of(mock_db, bom_service.ProductAccessory)
        assert fabrics and all(f.role_id == 21 for f in fabrics)
        assert all(a.role_id == 21 for a in accessories)
        assert result['target_role']['id'] == 21


class TestPreviewBom:
    """preview_bom 返回角色与物料计数"""

    async def test_preview_returns_roles_and_counts(self, mock_db):
        role_a = _mock_role(11, '白雪公主')
        role_b = _mock_role(12, '灰姑娘')

        fabric_a = MagicMock()
        fabric_a.role_id = 11
        fabric_a.to_dict = MagicMock(return_value={'name': '裙面料'})
        fabric_default = MagicMock()
        fabric_default.role_id = None
        fabric_default.to_dict = MagicMock(return_value={'name': '默认面料'})

        material_b = MagicMock()
        material_b.role_id = 12

        material_default = MagicMock()
        material_default.role_id = None
        material_default.cotton_usage = 50

        src = _mock_product(roles=[role_a, role_b], has_bom=True)
        src.fabrics = [fabric_a, fabric_default]
        src.accessories = []
        src.material = material_default
        src.create_time = None

        product_result = MagicMock()
        product_result.scalar_one_or_none.return_value = src
        mat_result = MagicMock()
        mat_result.scalars.return_value.all.return_value = [material_default, material_b]

        calls = iter([product_result, mat_result])
        mock_db.execute = AsyncMock(side_effect=lambda *a, **k: next(calls))

        result = await bom_service.preview_bom(mock_db, 1)

        assert result['role_count'] == 2
        assert result['bom']['roles'][0]['name'] == '白雪公主'
        assert result['bom']['roles'][0]['fabric_count'] == 1
        assert result['bom']['roles'][1]['filling_count'] == 1
        # 默认面料 + 产品级填充 + 各角色物料
        assert result['material_count'] == 1 + 1 + (1 + 1)
