r"""采购单撤销链路的延迟导入冒烟：源码里 import 的每个符号都必须真实存在。

背景（2026-10-22 生产事故）：`94194d2d` 把 `purchase_order_revoke._revoke_targets`
里的 `from fastapi_app.services.order_utils import compute_order_status_from_db`
改成 `compute_order_statuses_batch`，但同提交提供该函数的 `order_utils.py` 改动
在**工作区里晚于** revoke 落地。后端重启后 `ORDER_DELETED` 处理器删除订单时
`ImportError`，连崩 8 次（日志 `ORDER_DELETED 处理失败 ... cannot import name`），
导致该订单的 pending 采购单没被撤销 → 客户订单已删，`/purchase` 仍挂着
`PO-20261010-0001`。

**症状极隐蔽**：接口不报错、页面不提示，只是该联动的清理静默没发生，直到用户发现
「我没有这订单」才暴露。而 ImportError 只发生在**运行时**（函数体内的延迟导入），
CI 的 lint/类型检查看不出来。

本测试是一条**廉价的静态快检**（不是唯一防线）：把这两个文件源码里每条
`from fastapi_app... import ...` 的每个符号真实执行一遍 `hasattr`，改坏立刻红。
真防线还有 mypy（`mypy.ini` 已含本文件）与既有行为测试
（`fastapi_app/tests/test_purchase_auto_generate.py` 等会真实走到 `_revoke_targets`）。

**必须用 `ast` 解析，不能用正则**：这两个文件的多符号 import 几乎全是括号式
（`from x import (\n a,\n b,\n)`），正则 `[\w, ]+` 匹配不到 `(` 会整条漏检——
`pitfalls.md` §1 记着因此得出「15 个迁移 head」的纯解析伪影。
"""
import ast
import importlib
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 撤销/事件处理链路的关键文件：源码里每条 fastapi_app 导入的每个符号都会被查一遍。
GUARDED_FILES = [
    'fastapi_app/services/purchase_order_revoke.py',
    'fastapi_app/services/purchase_center_service.py',
]

# 撤销主路径必须在源码里**显式 import** 的符号（(文件, 模块, 符号)）。
# 正面钉住：整行删掉 import 时，"所有 import 都存在"这条会空真绿（变异验证过），
# 必须靠本条把"import 消失了"也变成红。
REQUIRED_IMPORTS = [
    ('fastapi_app/services/purchase_order_revoke.py',
     'fastapi_app.services.order_utils', 'compute_order_statuses_batch'),
    ('fastapi_app/services/purchase_order_revoke.py',
     'fastapi_app.services.purchase_order_crud', 'delete_purchase_order'),
    ('fastapi_app/services/purchase_order_revoke.py',
     'fastapi_app.services.purchase_order_sku', 'po_sku_available'),
]


def _iter_source_imports(rel_path: str):
    """用 AST 产出 (模块, 符号, 行号) —— 文件里所有 fastapi_app 导入。

    覆盖单行、括号多行、`import a as b`（取 `as` 前的原名）三种形态。
    """
    src = (PROJECT_ROOT / rel_path).read_text(encoding='utf-8')
    tree = ast.parse(src, filename=rel_path)
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or not node.module:
            continue
        if not node.module.startswith('fastapi_app'):
            continue
        for alias in node.names:
            yield node.module, alias.name, node.lineno


@pytest.mark.parametrize('rel_path', GUARDED_FILES)
def test_all_fastapi_imports_in_guarded_files_resolve(rel_path: str) -> None:
    """源码里每个导入符号都必须可取——ImportError 即 2026-10-22 事故复现。"""
    found = list(_iter_source_imports(rel_path))
    assert len(found) > 20, (
        f'{rel_path} 只解析到 {len(found)} 条导入，AST 解析可能已失效'
        f'（这两个文件应有 30+ 条）'
    )
    broken = [
        f'{mod}::{name} (L{lineno})'
        for mod, name, lineno in found
        if not hasattr(importlib.import_module(mod), name)
    ]
    assert not broken, (
        f'{rel_path} 里这些导入符号不存在：{broken}。'
        f'运行时 ImportError 会让删订单后的 pending 采购单撤销静默失败'
        f'（2026-10-22 PO-20261010-0001 事故）。'
    )


@pytest.mark.parametrize('rel_path, mod, name', REQUIRED_IMPORTS,
                         ids=[f'{p.rsplit("/", 1)[-1]}::{n}' for p, _m, n in REQUIRED_IMPORTS])
def test_required_imports_present_in_source(rel_path: str, mod: str, name: str) -> None:
    """撤销主路径的 import 必须还在源码里——整行删掉 = 运行时 NameError。"""
    imported = {(m, n) for m, n, _ln in _iter_source_imports(rel_path)}
    assert (mod, name) in imported, (
        f'{rel_path} 不再 import {mod}::{name}：删除订单后的 pending 采购单撤销会'
        f'直接崩（2026-10-22 PO-20261010-0001 事故同款）。'
    )


def test_revoke_chain_critical_symbols_importable() -> None:
    """撤销主路径的关键符号可真实 import（挡住"符号被改名/提供方被删"）。"""
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
