"""回归：计算器响应中 ``material_code`` / ``unit`` 为 NULL 时不得 500。

## 背景（2026-09-17 线上事故）

生产环境 `POST /purchase-center/calculate` 返回 500，堆栈为
``fastapi.exceptions.ResponseValidationError``：

    {'loc': ('response','groups',0,'fabric',0,'material_code'),
     'msg': 'Input should be a valid string', 'input': None}

根因是**跨层契约错配**：三张物料表的 ``material_code`` / ``unit`` 列均可空
（生产实测 11 行 ``material_code`` 为 NULL），``to_dict()`` 原样输出 ``None``；
而响应模型 ``MaterialCalcRow.material_code: str``（契约文档亦声明 ``+str``）
要求非空字符串。旧路径因响应模型把扁平字段声明为**无类型 list** 而不校验，
新增的 ``groups`` 用了强类型 ``MaterialCalcRow``，缺陷才被暴露。

## 为什么既有测试没拦住（本文件的存在理由）

``test_calculate_material_scope.py`` 的 ``_mat()`` 替身恒以 ``code=''`` 构造，
**从不产出 None**，与真实 ``to_dict()`` 的可空形状不符 → 测试全绿但线上必炸。
本文件坚持**不 mock 生产者**：物料行一律由真实 ``to_dict()`` 产出。

## fail-before / pass-after

修复前：``material_code`` 为 None 会一路传到 ``MaterialCalculateResponse`` 校验层并抛
``ResponseValidationError``（修复后本文件的断言会拦下任何回退）。
"""
from decimal import Decimal

import pytest
from pydantic import ValidationError

from fastapi_app.schemas.purchase_center import MaterialCalculateResponse
from fastapi_app.services.purchase_product_service import (
    aggregate_materials,
    aggregate_materials_by_scope,
)
from fastapi_app.shared_models.product_material import (
    ProductAccessory,
    ProductFabric,
    ProductMaterial,
)

PID = 9001


class _RealShapeProduct:
    """Product 替身：**物料行由真实 ``to_dict()`` 产出**，仅实现服务所需的最小协议。

    刻意不复用 ``_mat()`` 式手搓字典——那正是漏掉本缺陷的原因。
    """

    def __init__(self, pid, name, *, fabrics=(), accessories=(), materials=()):
        self.id = pid
        self.name = name
        self._fabrics = list(fabrics)
        self._accessories = list(accessories)
        self._materials = list(materials)

    def has_bom(self):
        return bool(self._fabrics or self._accessories or self._materials)

    def get_all_materials(self):
        rows = [m.to_dict() for m in self._materials]
        rows += [f.to_dict() for f in self._fabrics]
        rows += [a.to_dict() for a in self._accessories]
        return rows


def _product_with_null_codes():
    """构造 material_code / unit 均为 NULL 的产品（模拟生产存量数据）。"""
    fabric = ProductFabric(
        id=1, product_id=PID, role_id=None, fabric_name='白胚布',
        material_code=None,        # ← 生产实测：54 行面料中 8 行为 NULL
        specification=None, unit=None, quantity=Decimal('1.5'),
        supplier_name=None, material_category='fabric',
    )
    accessory = ProductAccessory(
        id=2, product_id=PID, role_id=None, accessory_name='拉链',
        material_code=None,        # ← 生产实测：2 行辅料中 1 行为 NULL
        specification=None, unit=None, quantity=Decimal('2'),
        supplier_name=None, material_category='accessory',
    )
    filling = ProductMaterial(
        id=3, product_id=PID, role_id=None,
        material_code=None,        # ← 生产实测：4 行填充物中 1 行为 NULL
        specification=None, unit=None, cotton_usage=Decimal('0.5'),
        supplier_name=None,
        # 注：ProductMaterial 无 material_name 列，且 material_category 是类属性（非列），
        #     故此处不得传这两个 kwarg；to_dict() 会把它们合成出来。
    )
    return _RealShapeProduct(PID, '公仔A', fabrics=[fabric], accessories=[accessory], materials=[filling])


def test_producer_really_emits_none():
    """前置事实：真实 ``to_dict()`` 在列为 NULL 时**确实**产出 None（替身不得合理化它）。"""
    product = _product_with_null_codes()
    codes = [row['material_code'] for row in product.get_all_materials()]
    assert None in codes, f'生产者应产出 None，实际 {codes}'


@pytest.mark.parametrize('scope', [False, True])
def test_aggregated_rows_never_carry_none(scope):
    """聚合结果中 material_code / unit 必须是字符串（NULL 归一为 ''）。"""
    product = _product_with_null_codes()
    product_map = {PID: product}
    orders = [{'product_id': PID, 'quantity': 10}]

    if scope:
        groups = aggregate_materials_by_scope(orders, product_map, name_of=lambda *_: None)
        rows = [r for g in groups for cat in ('filling', 'fabric', 'accessory') for r in g[cat]]
    else:
        flat = aggregate_materials(orders, product_map)
        rows = [r for cat in ('filling', 'fabric', 'accessory') for r in flat[cat]]

    assert rows, '应聚合出物料行'
    bad_code = [(r['material_name'], r['material_code']) for r in rows if not isinstance(r['material_code'], str)]
    bad_unit = [(r['material_name'], r['unit']) for r in rows if not isinstance(r['unit'], str)]
    assert not bad_code, f'material_code 必须为 str，实得 {bad_code}'
    assert not bad_unit, f'unit 必须为 str，实得 {bad_unit}'


def test_response_model_accepts_real_payload():
    """端到端契约：真实生产者 → 聚合 → ``MaterialCalculateResponse`` 校验必须通过。

    修复前此断言抛 ``ResponseValidationError``（线上 500 的直接原因）。
    """
    product = _product_with_null_codes()
    product_map = {PID: product}
    orders = [{'product_id': PID, 'quantity': 10}]

    flat = aggregate_materials(orders, product_map)
    groups = aggregate_materials_by_scope(orders, product_map, name_of=lambda *_: None)

    payload = {**flat, 'groups': groups}
    try:
        MaterialCalculateResponse.model_validate(payload)
    except ValidationError as e:  # noqa: PERF203
        pytest.fail(f'响应模型拒绝了真实生产者的产出（线上 500 同源）：\n{e}')
