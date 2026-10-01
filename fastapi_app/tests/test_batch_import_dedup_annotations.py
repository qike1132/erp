"""batch_import_dedup 的注解名必须全部可解析（P0-9）。

缺陷：模块带 from __future__ import annotations（注解是字符串，import 时不求值），
若某函数注解写了未导入的名字（历史：Container[Hashable] 而 Container 从未导入），
模块能 import 通过，但任何 typing.get_type_hints() 调用（工具链/pydantic/文档）
都会抛 NameError。

本文件做两件事：
1. 静态（ast）：模块里所有注解引用的名字都必须在模块内绑定（import/def/class/
   赋值/函数参数/except 名/PEP695 类型参数）或是内置名；
2. 运行时：对模块内所有函数执行 typing.get_type_hints()，注解必须能求值。
"""
import ast
import builtins
import inspect
import typing
from pathlib import Path

import fastapi_app.services.batch_import_dedup as mod

_SOURCE = Path(mod.__file__).read_text(encoding='utf-8')


def _bound_names(tree: ast.Module) -> set:
    bound = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                bound.add((alias.asname or alias.name).split('.')[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                bound.add(alias.asname or alias.name)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(node.name)
            for type_param in getattr(node, 'type_params', None) or []:
                name = getattr(type_param, 'name', None)
                if name:
                    bound.add(name)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            bound.add(node.id)
        elif isinstance(node, ast.arg):
            bound.add(node.arg)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            bound.add(node.name)
    return bound


def _annotation_names(tree: ast.Module) -> set:
    names = set()
    for node in ast.walk(tree):
        annotation = None
        if isinstance(node, ast.AnnAssign):
            annotation = node.annotation
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            annotation = node.returns
        elif isinstance(node, ast.arg):
            annotation = node.annotation
        if annotation is None:
            continue
        for sub in ast.walk(annotation):
            if isinstance(sub, ast.Name):
                names.add(sub.id)
    return names


def test_no_annotation_references_an_unbound_name():
    tree = ast.parse(_SOURCE)
    bound = _bound_names(tree)
    missing = sorted(
        name
        for name in _annotation_names(tree)
        if name not in bound and not hasattr(builtins, name)
    )
    assert missing == [], f'注解引用了模块内未绑定的名字（缺 import）: {missing}'


def test_all_function_type_hints_resolve():
    checked = 0
    for name, obj in vars(mod).items():
        if inspect.isfunction(obj) and obj.__module__ == mod.__name__:
            typing.get_type_hints(obj)  # 注解名未导入时这里抛 NameError
            checked += 1
    assert checked >= 4, f'扫描到的函数过少（{checked}），用例可能失效'


def test_dedupe_by_keys_hints_resolve():
    """历史缺陷点：dedupe_by_keys 的注解（Container -> Iterable 收窄后）必须可求值。"""
    hints = typing.get_type_hints(mod.dedupe_by_keys)
    assert hints, 'dedupe_by_keys 没有可解析的类型注解'
