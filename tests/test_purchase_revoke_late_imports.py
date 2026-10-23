"""采购单撤销链路的延迟导入冒烟：源码里 import 的每个符号都必须真实存在。

背景（2026-10-22 生产事故）：`94194d2d` 把 `purchase_order_revoke._revoke_targets`
里的 `from fastapi_app.services.order_utils import compute_order_status_from_db`
改成 `compute_order_statuses_batch`，但同提交提供该函数的 `order_utils.py` 改动
在**工作区里晚于** revoke 落地。后端重启后 `ORDER_DELETED` 处理器每次删除订单都
`ImportError`，连崩 8 次（日志 `ORDER_DELETED 处理失败 ... cannot import name`），
导致该订单的 pending 采购单没被撤销 → 客户订单已删，`/purchase` 仍挂着
`PO-20261010-0001`。

**症状极隐蔽**：接口不报错、页面不提示，只是该联动的清理静默没发生，直到用户发现
「我没有这订单」才暴露。而 ImportError 只发生在**运行时**（函数体内的延迟导入），
import 期、类型检查、lint 全看不出来。

判据是**逐符号存在性**，不是整行文本比对：整行比对在多符号 import（`import a, b`）
下会因字符串不相等而误报，且抓不到「追加一个假符号」；逐个符号查 `hasattr` 才同时
覆盖改名、删符号、追加假符号三种改坏（均已变异验证）。
"""
import importlib
import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 撤销/事件处理链路上的关键文件：源码里每条 `from fastapi_app... import ...`
# 的每个符号都会被真实执行一遍 hasattr。
GUARDED_FILES = [
    'fastapi_app/services/purchase_order_revoke.py',
    'fastapi_app/services/purchase_center_service.py',
]

# 撤销主路径必须在源码里**显式 import** 的符号（(文件, 模块, 符号)）。
# 正面钉住：整行删掉 import 时，"所有 import 都存在"这条仍是空真绿（变异 C 验证过），
# 必须靠本条把"import 消失了"也变成红。
REQUIRED_IMPORTS = [
    ('fastapi_app/services/purchase_order_revoke.py',
     'fastapi_app.services.order_utils', 'compute_order_statuses_batch'),
    ('fastapi_app/services/purchase_order_revoke.py',
     'fastapi_app.services.purchase_order_crud', 'delete_purchase_order'),
    ('fastapi_app/services/purchase_order_revoke.py',
     'fastapi_app.services.purchase_order_sku', 'po_sku_available'),
]

_IMPORT_RE = re.compile(r'^\s*from (fastapi_app[\w.]*) import ([\w, ]+)', re.M)


def _iter_source_imports(rel_path: str):
    """产出 (模块, 符号) —— 文件里所有 fastapi_app 延迟导入。

    支持 `import a, b as c`：别名形式取 `as` 前的原名（真正被 import 的符号）。
    """
    src = (PROJECT_ROOT / rel_path).read_text(encoding='utf-8')
    for mod, names in _IMPORT_RE.findall(src):
        for raw in names.split(','):
            name = raw.strip().split(' as ')[0].strip()
            if name:
                yield mod, name


@pytest.mark.parametrize('rel_path, mod, name', REQUIRED_IMPORTS,
                         ids=[f'{p.rsplit("/", 1)[-1]}::{n}' for p, _m, n in REQUIRED_IMPORTS])
def test_required_imports_present_in_source(rel_path: str, mod: str, name: str) -> None:
    """撤销主路径的 import 必须还在源码里——整行删掉 = 运行时 NameError/ImportError。"""
    imported = set(_iter_source_imports(rel_path))
    assert (mod, name) in imported, (
        f'{rel_path} 不再 import {mod}::{name}：删除订单后的 pending 采购单撤销会'
        f'直接崩（2026-10-22 PO-20261010-0001 事故同款）。'
    )


@pytest.mark.parametrize('rel_path', GUARDED_FILES)
def test_all_fastapi_imports_in_guarded_files_resolve(rel_path: str) -> None:
    """源码里每个延迟导入符号都必须可取——ImportError 即 2026-10-22 事故复现。"""
    pairs = list(_iter_source_imports(rel_path))
    assert pairs, f'{rel_path} 未解析到任何 fastapi_app 导入，正则可能已失效'
    broken = [
        f'{mod}::{name}'
        for mod, name in pairs
        if not hasattr(importlib.import_module(mod), name)
    ]
    assert not broken, (
        f'{rel_path} 里这些导入符号不存在：{broken}。'
        f'运行时 ImportError 会让删订单后的 pending 采购单撤销静默失败'
        f'（2026-10-22 PO-20261010-0001 事故）。'
    )


def test_revoke_chain_critical_symbols_present() -> None:
    """撤销主路径的关键符号点名存在（防止被重命名后上面那条被"整体无导入"绕过）。"""
    from fastapi_app.services.order_utils import compute_order_statuses_batch
    from fastapi_app.services.purchase_order_crud import delete_purchase_order
    from fastapi_app.services.purchase_order_revoke import (
        revoke_pending_purchase_orders_for_order,
    )
    from fastapi_app.services.purchase_order_sku import po_sku_available

    assert callable(compute_order_statuses_batch)
    assert callable(delete_purchase_order)
    assert callable(revoke_pending_purchase_orders_for_order)
    assert callable(po_sku_available)


def test_order_deleted_handler_importable() -> None:
    """ORDER_DELETED 处理器模块必须能完整导入（订阅注册在 import 期执行）。"""
    importlib.import_module('fastapi_app.services.purchase_center_service')
    from fastapi_app.core.domain_events import DomainEventType, _subscribers

    assert DomainEventType.ORDER_DELETED in _subscribers, (
        'ORDER_DELETED 没有订阅者：删订单后不会撤销 pending 采购单。'
    )
