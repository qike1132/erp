"""「是否抵扣备货」只有一份解析实现（2026-10-17 审计 Z04-R3③）。

原先三处各写一遍 if/elif：暂存区（``staging/_generic``）、综合导入
（``batch_import_core``）、单 Sheet 端点（``batch_import_service``）。同一列三种语义
——「是」在一处折算 1 件、另两处折算整单量；数字 '3.0'（Polars Float64 形态）在两处
被静默丢弃。改一处漏一处，用户看到的「抵扣」取决于这张表走哪条导入路径。

现在解析只在 ``batch_import_parser._parse_deduct_flag`` 一份。本文件锁两件事：

1. **结构**：全仓只有一处定义，各消费方必须委托、不得再内联一份；
2. **接线**：两条导入路径传给 ``process_order_deduction`` 的抵扣量，等于共享解析函数的
   输出 —— 含收敛后才识别的 ``'3.0'`` / ``'y'`` 两种写法（本次唯一的行为变化，
   与 P1-8 的 staging 修复同口径）。
"""
from __future__ import annotations

import ast
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from fastapi_app.services import batch_import_core as bic
from fastapi_app.services import batch_import_parser as bip
from fastapi_app.services import batch_import_service as bis
from fastapi_app.services.staging import _generic as staging_generic
from fastapi_app.services.staging import order as staging_order
from fastapi_app.shared_models import Customer, Product

REPO = Path(__file__).resolve().parents[1]
SCAN_ROOTS = (REPO / 'fastapi_app' / 'services', REPO / 'fastapi_app' / 'shared')
CONSUMER_FILES = (
    REPO / 'fastapi_app/services/batch_import_core.py',
    REPO / 'fastapi_app/services/batch_import_service.py',
    REPO / 'fastapi_app/services/staging/_generic.py',
    REPO / 'fastapi_app/services/staging/order.py',
)

#: 收敛前的内联写法残留 —— 任一处再现即说明第二份实现又长回来了。
FORBIDDEN_INLINE = (
    'deduct_value = 0',
    'deduct_flag_str',
    'deduct_str.isdigit()',
    "('是', 'yes')",
    "['是', 'yes']",
)

QTY = 7
#: (用例代号, 原始单元格值, 期望抵扣量；None = 不应调用抵扣)。
#: 代号同时用于客户名/单号，保证跨用例的幂等键与单号都不相撞。
FLAG_CASES = [
    ('a', '是', QTY),
    ('b', 'YES', QTY),
    ('c', 'y', QTY),        # 收敛后新增可识别（原先两条导入路径静默丢弃）
    ('d', '3', 3),
    ('e', '3.0', 3),        # 收敛后新增可识别（P1-8 同源：Float64 字符串形态）
    ('f', 3, 3),
    ('g', 3.0, 3),
    ('h', '2.5', None),     # 非整数一律不抵扣，与 _parse_import_row 的「小数拒绝」同口径
    ('i', '否', None),
    ('j', '', None),
    ('k', 0, None),
    ('l', None, None),
]
CASE_PARAMS = [(tag, flag, exp) for tag, flag, exp in FLAG_CASES]


def _definitions() -> list[str]:
    """services/** 与 shared/** 里 ``def _parse_deduct_flag`` 所在文件。"""
    found: list[str] = []
    for root in SCAN_ROOTS:
        for path in sorted(root.rglob('*.py')):
            if 'tests' in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding='utf-8'))
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef) and node.name == '_parse_deduct_flag':
                    found.append(path.relative_to(REPO).as_posix())
    return found


class TestSingleImplementation:
    def test_definition_lives_in_shared_parser_layer(self):
        defs = _definitions()
        assert len(defs) == 1, f'「是否抵扣」解析出现第二份实现: {defs}'
        assert defs == ['fastapi_app/services/batch_import_parser.py']

    def test_consumers_resolve_to_the_same_object(self):
        """四处消费方拿到的是同一个函数对象（re-export，而不是各抄一份）。"""
        for mod in (staging_generic, staging_order, bis, bic):
            assert mod._parse_deduct_flag is bip._parse_deduct_flag, mod.__name__

    @pytest.mark.parametrize('path', CONSUMER_FILES, ids=[p.name for p in CONSUMER_FILES])
    def test_call_sites_delegate_without_inline_parsing(self, path: Path):
        src = path.read_text(encoding='utf-8')
        assert '_parse_deduct_flag' in src, f'{path.name} 不再引用共享解析函数'
        for snippet in FORBIDDEN_INLINE:
            assert snippet not in src, f'{path.name} 仍内联解析抵扣标志: {snippet}'


async def _seed(async_db_session, tag: str) -> None:
    """一个客户 + 一个产品（客户名带代号，避免与同会话其它用例的幂等键相撞）。"""
    async_db_session.add_all([
        Customer(name=f'抵扣客户{tag}'),
        Product(name=f'抵扣产品{tag}', barcode=f'BC{tag}',
                current_stock=100, initial_stock=100),
    ])
    await async_db_session.flush()


def _rows(tag: str, flag) -> list[dict]:
    return [{
        '客户名称': f'抵扣客户{tag}', '产品名称': f'抵扣产品{tag}',
        '数量': QTY, '抵扣备货': flag, '备注': '',
    }]


def _recorder() -> tuple[list[dict], object]:
    """把抵扣实现换成记录器 —— 本文件验「传了什么参数」，抵扣算法另有测试。"""
    calls: list[dict] = []

    async def _record(_db, _order, _product_id, _order_qty, **kwargs):
        calls.append(kwargs)

    return calls, _record


def _assert_deduction(calls: list[dict], expected, tag: str) -> None:
    if expected is None:
        assert calls == [], f'{tag}: 不该抵扣，却调用了 {calls}'
        return
    assert len(calls) == 1, f'{tag}: 抵扣应调用一次，实际 {calls}'
    assert calls[0]['deduct_stock'] is True, calls[0]
    assert calls[0]['custom_deduct_quantity'] == expected, (
        f'{tag}: 期望抵扣 {expected}，实际传 {calls[0]}'
    )


class TestComprehensiveImportPath:
    """综合导入 / ARQ（``batch_import_core.import_orders_from_data``），依赖走 ImportDeps 注入。"""

    @pytest.mark.parametrize(('tag', 'flag', 'expected'), CASE_PARAMS,
                             ids=[f'{t}-{f!r}' for t, f, _ in CASE_PARAMS])
    async def test_deduct_quantity_follows_shared_semantics(
        self, async_db_session, tag, flag, expected,
    ):
        await _seed(async_db_session, tag)
        calls, record = _recorder()

        async def _gen_no(_db):
            return f'CO-{tag}-{datetime.now(UTC):%H%M%S%f}'[:20]

        deps = bic.ImportDeps(process_order_deduction=record, generate_order_number=_gen_no)
        imported, _messages = await bic.import_orders_from_data(
            async_db_session, _rows(tag, flag), deps=deps)

        assert imported == 1, f'{tag}: 订单行本身应导入成功'
        _assert_deduction(calls, expected, tag)


class TestSheetImportEndpointPath:
    """单 Sheet 端点（``batch_import_service.import_orders_service``）。"""

    @pytest.mark.parametrize(('tag', 'flag', 'expected'), CASE_PARAMS,
                             ids=[f'{t}-{f!r}' for t, f, _ in CASE_PARAMS])
    async def test_deduct_quantity_follows_shared_semantics(
        self, async_db_session, monkeypatch, tag, flag, expected,
    ):
        # 两个类各用一套客户名：customer.name 有唯一约束，而 async_db_session 在用例结束
        # 时才 commit（同会话内跨用例留存），同名种子数据会在第二个类整批撞 UniqueViolation。
        tag = f's{tag}'
        await _seed(async_db_session, tag)
        calls, record = _recorder()
        monkeypatch.setattr(bis, 'process_order_deduction', record)

        async def _read(_file, _keywords, _missing):
            return _rows(tag, flag), None

        async def _gen_no(_db):
            return f'SO-{tag}-{datetime.now(UTC):%H%M%S%f}'[:20]

        monkeypatch.setattr(bis, '_validate_xlsx_file', lambda _f: None)
        monkeypatch.setattr(bis, '_read_excel_sheets', _read)
        monkeypatch.setattr(bis, 'generate_order_number', _gen_no)

        result = await bis.import_orders_service(
            async_db_session, SimpleNamespace(filename='x.xlsx'))

        assert result.imported == 1, result.message
        _assert_deduction(calls, expected, tag)
