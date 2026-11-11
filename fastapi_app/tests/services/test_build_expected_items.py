from types import SimpleNamespace

from fastapi_app.services.purchase_order_generate import _BomContext, build_expected_items


def _fabric(pid, name, usage, part=None, supplier='美利达', spec='S1'):
    return SimpleNamespace(product_id=pid, role_id=None, fabric_name=name,
                           specification=spec, part_name=part, supplier_name=supplier,
                           unit='码', quantity=usage, material_code='', supplier_id=None)


def _acc(pid, rid, name, usage):
    return SimpleNamespace(product_id=pid, role_id=rid, accessory_name=name,
                           specification='1条', part_name=None, supplier_name='木棒',
                           unit='个', quantity=usage, material_code='', supplier_id=None)


def test_blind_box_roles_split_and_allocate():
    """6 角色盲盒：默认BOM 两条同物料跨身体/脚底不合并；辅料每角色一行。"""
    ctx = _BomContext()
    ctx.fabric = {None: [_fabric(1, '绿色超柔', 1.0, '身体'), _fabric(1, '绿色超柔', 1.0, '脚底')]}
    ctx.accessory = {rid: [_acc(1, rid, '木棒按摩锤', 1.0)] for rid in range(11, 17)}
    ctx.role_names = {(1, rid): f'角色{rid}' for rid in range(11, 17)}
    ctx.scopes_by_pid = {1: [None, 11, 12, 13, 14, 15, 16]}
    ctx.blind_box_pids = {1}

    items = build_expected_items(
        [{'product_name': '产品A', 'order_qty': 3000}], ctx, {'产品A': 1}, '客户甲',
    )

    green = [i for i in items if i['material_name'] == '绿色超柔']
    assert sorted(i['quantity'] for i in green) == [3000.0, 3000.0]  # 默认BOM 两条 × N
    assert sorted(i['part_name'] for i in green) == ['脚底', '身体']
    wood = [i for i in items if i['material_name'] == '木棒按摩锤']
    assert len(wood) == 6  # 每角色一行
    assert all(i['quantity'] == 500.0 for i in wood)
