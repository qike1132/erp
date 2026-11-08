"""工厂内部订单「角色名称」列：物料行的角色归属（纯函数）。

需求（2026-11-08）：一个产品名称下有多个角色时，工厂内部订单要能看出每一行物料
属于哪个角色。角色归属来自 BOM 行的 ``role_id``（生成采购单时同一套作用域），
由 ``_sku_material_rows`` 记账、定稿为 ``role_display``：

- 同一物料被多个角色共用 → 聚合行**并列**角色名（``角色A/角色B``），不拆行
  （拆行会让同一落库明细被多行共享，编辑一个角色就改写整行数量）；
- 默认 BOM（``role_id=None``）→ 空串（没有角色可标）；
- 旧调用方不传 ``role_names`` → 空串（零行为变化）。
"""
from fastapi_app.services.purchase._factory import (
    _finalize_part_display,
    _finalize_role_display,
    _sku_material_rows,
)


def _bom(material: str, *, role_id: int | None, quantity: float = 2.0) -> dict:
    return {
        'material_name': material,
        'specification': 'S1',
        'unit': '米',
        'quantity': quantity,
        'supplier_name': '供应商甲',
        'part_name': '身体',
        'category': 'fabric',
        'role_id': role_id,
    }


def _rows(boms: list[dict], role_names: dict[int, str] | None = None) -> list[dict]:
    rows = _sku_material_rows(boms, 10, '兜底供应商', role_names=role_names)
    return [_finalize_role_display(_finalize_part_display(dict(row))) for row in rows]


def test_each_role_keeps_its_own_role_name():
    """不同角色的不同物料：逐行标出各自角色名（多角色产品分行展示的基础）。"""
    rows = _rows(
        [_bom('角色A布', role_id=7), _bom('角色B布', role_id=8)],
        role_names={7: '角色A', 8: '角色B'},
    )
    assert {row['material_name']: row['role_display'] for row in rows} == {
        '角色A布': '角色A', '角色B布': '角色B',
    }


def test_shared_material_lists_every_role():
    """同一物料被两个角色共用：聚合行并列角色名，数量累加（不拆行）。"""
    rows = _rows(
        [_bom('共享布', role_id=7, quantity=2), _bom('共享布', role_id=8, quantity=3)],
        role_names={7: '角色A', 8: '角色B'},
    )
    assert len(rows) == 1
    assert rows[0]['role_display'] == '角色A/角色B'
    assert rows[0]['quantity'] == 50.0  # (2 + 3) × 10


def test_default_bom_has_empty_role_display():
    """默认 BOM（role_id=None）没有角色可标 → 空串，不编造「默认BOM」字样。"""
    rows = _rows([_bom('默认布', role_id=None)], role_names={7: '角色A'})
    assert rows[0]['role_display'] == ''


def test_unknown_role_id_falls_back_to_empty():
    """role_id 在角色表里查不到（历史脏数据）→ 空串，不抛错、不瞎猜名字。"""
    rows = _rows([_bom('孤儿布', role_id=99)], role_names={7: '角色A'})
    assert rows[0]['role_display'] == ''


def test_without_role_names_is_noop():
    """旧调用方不传 role_names：角色列全空，其它字段与既有口径逐字一致。"""
    rows = _rows([_bom('角色A布', role_id=7)])
    assert rows[0]['role_display'] == ''
    assert rows[0]['part_display'] == '身体'
    assert rows[0]['quantity'] == 20.0


def test_finalize_is_idempotent():
    """二次定稿（重复调用）不得把已定稿的 role_display 抹成空串。"""
    row = _finalize_role_display(
        _finalize_part_display(dict(_bom('角色A布', role_id=7))),
    )
    # 手工塞入记账字段模拟首轮未定稿的行，再走一次定稿
    row['role_display'] = '角色A'
    again = _finalize_role_display(row)
    assert again['role_display'] == '角色A'
