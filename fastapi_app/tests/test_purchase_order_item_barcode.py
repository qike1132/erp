"""采购明细的产品条码必须从 SKU 来源一路带到落库列（2026-11-16 审计 A-52）。

拦哪种错：`purchase_order_item.barcode` 曾经全仓零写入，于是
`/orders/completed?barcode=` 的 EXISTS 子查询永远零命中（前端无入口，但 API 与脚本
按条码查会永远查不到）。本文件锁住「生成路径把条码带下来」这条链路。

说明：这里用**接线断言**（读源码 + 断言参数名与传递点），与
`test_stock_chip_cache_invalidation.py::test_get_all_customers_disables_l1` 同一路数——
`_material_row` 需要构造整套 BOM 上下文，端到端跑它得搭一堆夹具，而它唯一的失败模式
就是「忘了把参数带出去」，读源码能精确钉住。

变异检查：删掉 `_material_row` 的 `product_barcode` 形参或任一处
`product_barcode=pid_barcode.get(pid)`，对应用例必红。
"""
from __future__ import annotations

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
GEN = PROJECT_ROOT / 'fastapi_app/services/purchase_order_generate.py'
CRUD = PROJECT_ROOT / 'fastapi_app/services/purchase_order_crud.py'


def _src(path: Path) -> str:
    return path.read_text(encoding='utf-8')


def test_material_row_accepts_and_emits_barcode():
    src = _src(GEN)
    sig = re.search(r'def _material_row\((.*?)\) -> dict:', src, re.S)
    assert sig, '未找到 _material_row 定义'
    assert 'product_barcode' in sig.group(1), (
        '_material_row 没有 product_barcode 形参：条码无法从 SKU 来源带进明细'
    )
    assert "'barcode': product_barcode or None" in src, '返回字典里没有 barcode 键'


def test_both_generation_paths_thread_the_barcode():
    src = _src(GEN)
    # 盲盒合并路径 + 常规路径 + 快照重算路径，三处调用都要带条码
    calls = re.findall(r'_material_row\(\s*spec, row,[^)]*?\)', src, re.S)
    assert len(calls) >= 3, f'预期至少 3 处 _material_row 调用，实际 {len(calls)}'
    missing = [c for c in calls if 'product_barcode=' not in c]
    assert not missing, f'以下调用没带 product_barcode: {missing}'


def test_barcode_is_collected_from_sku_sources():
    src = _src(GEN)
    assert 'pid_barcode' in src, '没有按 pid 收敛条码的映射'
    assert src.count('pid_barcode.setdefault') >= 3, '条码映射没有同时从 sku_lines 与记录 items 收集'


def test_crud_persists_barcode_on_item_creation():
    src = _src(CRUD)
    assert "barcode=item_data.get('barcode') or item_data.get('product_barcode')" in src, (
        'create_purchase_order 没把条码写进 PurchaseOrderItem.barcode'
    )
