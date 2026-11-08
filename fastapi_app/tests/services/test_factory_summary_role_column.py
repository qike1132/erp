"""工厂内部订单「角色名称」列：物料行的角色归属（纯函数）。

需求（2026-11-08）：一个产品名称下有多个角色时，工厂内部订单要能看出每一行物料
属于哪个角色。角色归属来自 BOM 行的 ``role_id``（生成采购单时同一套作用域），
由 ``_sku_material_rows`` 记账、定稿为 ``role_display``：

- 同一物料被多个角色共用 → **按角色各成一行**（各自数量 = 该角色的分配量），
  不合并成一行——合并后工厂看不出每个角色各要多少（2026-11-08 用户反馈）；
- 排序第一键是角色（默认 BOM 在前，其后 role_id 升序），保证同角色物料连续；
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


def test_shared_material_splits_per_role():
    """同一物料被两个角色共用：**按角色各成一行**（数量各按该角色分配量），不合并。

    这是 2026-11-08 用户反馈的缺陷：工厂内部订单要「按角色分类汇总」，
    合并成一行再并列角色名，工厂看不出每个角色各要多少。
    """
    rows = _rows(
        [_bom('共享布', role_id=7, quantity=2), _bom('共享布', role_id=8, quantity=3)],
        role_names={7: '角色A', 8: '角色B'},
    )
    assert len(rows) == 2
    assert [(row['role_display'], row['quantity']) for row in rows] == [
        ('角色A', 20.0),  # 2 × 10
        ('角色B', 30.0),  # 3 × 10
    ]
    # 两行仍是同一个物料（落库侧只有一行明细，前端据此把它标为只读）
    assert {row['material_name'] for row in rows} == {'共享布'}


def test_rows_are_grouped_by_role():
    """排序第一键是角色：同一角色的物料必须连续，不能被供应商/物料名打散。"""
    rows = _rows(
        [
            _bom('乙布', role_id=8),
            _bom('甲布', role_id=7),
            _bom('丙布', role_id=8),
            _bom('默认布', role_id=None),
        ],
        role_names={7: '角色A', 8: '角色B'},
    )
    # 默认 BOM 在前，其后 role_id 升序；角色内再按供应商/部位/物料名
    assert [row['role_display'] for row in rows] == ['', '角色A', '角色B', '角色B']
    # 角色内再按物料名排序（丙 U+4E19 < 乙 U+4E59）
    assert [row['material_name'] for row in rows] == ['默认布', '甲布', '丙布', '乙布']


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
