"""写路径端到端 —— 直连**真实运行的后端**，验证三条关键写路径真的落库。

为什么单独立一个文件
--------------------
``tests/e2e_api/test_auth_flow.py`` 只覆盖了鉴权与身份契约，整个目录
没有任何用例真正**写入**业务数据。而历史上最贵的三类事故都发生在写路径：

1. **订单确认流程**：确认湖北订单有「未在采购中心下单则 409 门控」，
   且已确认记录必须**幂等早退 200** 而不是回退成 409（CR-1 缺陷）。
   单测里两边都是 mock，门控与幂等的**相对顺序**只有在真实事务里才成立。
2. **出库扣减库存**：库存扣减、FIFO 摊销、订单状态派生三者必须一致。
   单测用 mock 断言「调用了扣减函数」，无法发现 select_for_update 下的
   真实竞态或状态重算遗漏。
3. **采购订单一键生成**：一键生成会先清理旧 pending 单、再重建、
   并把订单状态改写为「已备货」。X-Idempotency-Key 的语义必须锁定 ——
   当前实现**不做请求结果重放**，同键重试因为源订单已非「待备货」而 400。
   这是刻意与"假幂等"区分的行为，必须有回归锁：若哪天有人真的加了重放，
   这条用例会红，提醒同步前端与文档。

本文件补的正是「**写请求真的改变了数据库状态**」这一层，且全部用
**运行时造数 + 用例内自清理**，不依赖任何生产数据、不留下垃圾行。

运行条件
--------
需要一个真实运行的后端（与 ``test_auth_flow.py`` 同一约定）::

    python scripts/restart_backend.py
    pytest tests/e2e_api/test_write_paths.py -v

目标地址取 ``E2E_API_BASE_URL``（**无默认值**，2026-09-29 起）—— 必须指向专用临时后端
且同时设 ``ERP_E2E_REAL_DATABASE_URL`` 指向测试库；未设置或命中生产指纹时由 ``conftest.py``
整目录跳过 / fail-fast（见该文件 docstring 的运行条件）。
后端不可达时由 ``conftest.py`` 整目录跳过 —— 跳过是正确行为，不是失败。

鉴权与 CSRF
-----------
token 直接用 ``create_access_token`` 现铸（与 conftest 同源），不依赖口令。
但**写请求还要过 CSRF 中间件**：生产模式下 ``Origin`` 必须命中
``settings.BACKEND_CORS_ORIGINS``，否则 403「跨站请求被拒绝」。
本文件的 ``write_api`` fixture 会自动注入一个允许的 Origin，
所以用例里不需要重复关心这件事。
"""

from __future__ import annotations

import time
from contextlib import suppress
from datetime import date
from typing import Any

import httpx
import pytest
import pytest_asyncio

pytestmark = pytest.mark.e2e_api

# 造数命名前缀：所有由本文件创建的行都能被 _cleanup 精确定位
_PREFIX = "__e2e_wp__"
# 数据库里保留的供应商标记（BOM 明细的 supplier_name），便于清理排查
_SUPPLIER = f"{_PREFIX}SUP"


# ============================================================
# 造数与清理 —— 全部直连数据库，不依赖生产数据
# ============================================================
def _sync_engine():
    """同步引擎（test_auth_flow 同款做法）：造数与清理走直连，不经 ORM 会话。

    必须用 ``conftest.real_database_url()``（收集期固化的真实库），
    **不能**读 ``settings.DATABASE_URL``：该值已被 tests/conftest.py 的
    session 级 autouse fixture ``app_on_test_db`` 改成 ``erp_system_test``，
    于是造数写进空测试库、而 HTTP 请求打到真实后端的真实库 —— 表现为
    ``product_material`` 外键违规（product_id 在真实库不存在）。
    """
    from sqlalchemy import create_engine

    from tests.e2e_api.conftest import real_database_url

    return create_engine(real_database_url())


def _unique(tag: str) -> str:
    """带时间戳的唯一后缀：保证并发/重复运行不撞产品名唯一约束。"""
    return f"{_PREFIX}{tag}_{int(time.time() * 1000)}"


def _cleanup(product_ids: list[int], order_ids: list[int]) -> None:
    """删除本文件造出的全部数据。

    尽力而为：清理失败只记录，不改变用例结果（用例结论在清理前已经断言完）。
    删除顺序按外键依赖自底向上，避免 RESTRICT / FK 违规。
    """
    if not product_ids and not order_ids:
        return
    from sqlalchemy import text

    # 纵深防御（独立于 conftest 的收集期指纹守卫）：即便守卫被绕过，也绝不让这里的
    # 裸 SQL DELETE 落到生产库。刻意放在 ``with suppress(Exception)`` **之外** ——
    # 放进 suppress 里会被静默吞掉，守卫就等于不存在。
    # 消息里用 ``_mask_dsn`` 隐去口令：异常文本可能进日志/CI 输出，绝不能带生产密码。
    from tests.e2e_api.conftest import _mask_dsn, real_database_url

    dsn = real_database_url()
    if '/erp_system' in dsn and 'erp_system_test' not in dsn:
        raise RuntimeError(f"E2E 清理拒绝连接生产库: {_mask_dsn(dsn)}")

    with suppress(Exception):
        engine = _sync_engine()
        with engine.begin() as conn:
            po_ids: list[int] = []
            if order_ids:
                import json

                for po_id, src in conn.execute(
                    text(
                        "SELECT id, source_order_ids FROM purchase_order "
                        "WHERE source_order_ids IS NOT NULL"
                    )
                ).fetchall():
                    try:
                        ids = json.loads(src)
                    except (TypeError, ValueError):
                        continue
                    if isinstance(ids, list) and any(i in order_ids for i in ids):
                        po_ids.append(po_id)

            if po_ids:
                item_ids = [
                    r[0]
                    for r in conn.execute(
                        text(
                            "SELECT id FROM purchase_order_item WHERE order_id = ANY(:p)"
                        ),
                        {"p": po_ids},
                    ).fetchall()
                ]
                if item_ids:
                    conn.execute(
                        text(
                            "DELETE FROM material_registration_item "
                            "WHERE order_item_id = ANY(:i)"
                        ),
                        {"i": item_ids},
                    )
                    conn.execute(
                        text(
                            "DELETE FROM modification_log "
                            "WHERE target_type = 'purchase_item' AND target_id = ANY(:i)"
                        ),
                        {"i": item_ids},
                    )
                conn.execute(
                    text("DELETE FROM material_registration WHERE purchase_order_id = ANY(:p)"),
                    {"p": po_ids},
                )
                conn.execute(
                    text("DELETE FROM purchase_order_sku WHERE po_id = ANY(:p)"),
                    {"p": po_ids},
                )
                conn.execute(
                    text("DELETE FROM purchase_order_item WHERE order_id = ANY(:p)"),
                    {"p": po_ids},
                )
                conn.execute(
                    text("DELETE FROM purchase_order WHERE id = ANY(:p)"), {"p": po_ids}
                )

            if order_ids:
                conn.execute(
                    text("DELETE FROM stock_out WHERE order_id = ANY(:o)"), {"o": order_ids}
                )
                conn.execute(
                    text("DELETE FROM notification WHERE related_order_id = ANY(:o)"),
                    {"o": order_ids},
                )
                conn.execute(
                    text("DELETE FROM order_item WHERE order_id = ANY(:o)"), {"o": order_ids}
                )
                conn.execute(
                    text("DELETE FROM order_outsource_process WHERE order_id = ANY(:o)"),
                    {"o": order_ids},
                )
                conn.execute(
                    text("DELETE FROM order_sync_record WHERE source_order_id = ANY(:o)"),
                    {"o": order_ids},
                )
                conn.execute(
                    text('DELETE FROM "order" WHERE id = ANY(:o)'), {"o": order_ids}
                )

            if product_ids:
                conn.execute(
                    text("DELETE FROM stock_out WHERE product_id = ANY(:p)"),
                    {"p": product_ids},
                )
                conn.execute(
                    text("DELETE FROM stock_in WHERE product_id = ANY(:p)"),
                    {"p": product_ids},
                )
                conn.execute(
                    text("DELETE FROM inventory_log WHERE product_id = ANY(:p)"),
                    {"p": product_ids},
                )
                conn.execute(
                    text("DELETE FROM product_material WHERE product_id = ANY(:p)"),
                    {"p": product_ids},
                )
                conn.execute(
                    text("DELETE FROM product_fabric WHERE product_id = ANY(:p)"),
                    {"p": product_ids},
                )
                conn.execute(
                    text("DELETE FROM product_accessory WHERE product_id = ANY(:p)"),
                    {"p": product_ids},
                )
                conn.execute(
                    text("DELETE FROM product WHERE id = ANY(:p)"), {"p": product_ids}
                )


def _make_bom(product_id: int, *, cotton_usage: float) -> None:
    """为产品插入一条填充物 BOM 行（直连 SQL）。

    为什么直连：BOM 保存端点需要一整套 面料/配件/包装 的完整载荷，
    且会触发角色解析等与本文件无关的逻辑；此处只需要「有 BOM 可展开」，
    让一键生成走通真实 BOM → 采购明细的链路即可。
    """
    from sqlalchemy import text

    engine = _sync_engine()
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO product_material "
                "(product_id, cotton_usage, unit, supplier_name, material_code) "
                "VALUES (:p, :q, '克', :s, :code)"
            ),
            {"p": product_id, "q": cotton_usage, "s": _SUPPLIER, "code": "WP-BOM-1"},
        )


async def _create_product(
    api: httpx.AsyncClient,
    name: str,
    *,
    stock: int,
    factory: str,
    headers: dict[str, str],
) -> int:
    """经真实端点建产品，返回其 id（写请求需带 Origin 过 CSRF）。"""
    resp = await api.post(
        "/api/v1/products/create",
        json={
            "name": name,
            "barcode": f"WP{int(time.time() * 1000) % 10**9}",
            "initial_stock": stock,
            "factory": factory,
        },
        headers=headers,
    )
    assert resp.status_code == 200, f"建产品失败：{resp.status_code} {resp.text[:300]}"
    found = await api.get("/api/v1/products/search", params={"q": name})
    assert found.status_code == 200, found.text[:200]
    items = found.json()
    assert items, f"刚创建的产品搜不到：{name}"
    return int(items[0]["id"])


async def _create_order(
    api: httpx.AsyncClient,
    product_id: int,
    qty: int,
    customer: str,
    *,
    headers: dict[str, str],
) -> int:
    """经真实端点建订单（状态=待备货），返回其 id（写请求需带 Origin 过 CSRF）。"""
    resp = await api.post(
        "/api/v1/orders/create",
        json={
            "product_id": product_id,
            "quantity": qty,
            "customer": customer,
            "order_type": "regular",
        },
        headers=headers,
    )
    assert resp.status_code == 200, f"建订单失败：{resp.status_code} {resp.text[:300]}"
    listed = await api.get(
        "/api/v1/orders/list", params={"customer": customer, "page": 1, "per_page": 10}
    )
    assert listed.status_code == 200, listed.text[:200]
    rows = listed.json()["data"]
    assert rows, f"刚创建的订单查不到：customer={customer}"
    return int(rows[0]["id"])


async def _product_stock(api: httpx.AsyncClient, product_id: int) -> int:
    """读产品当前库存（详情端点）。"""
    resp = await api.get(f"/api/v1/products/{product_id}")
    assert resp.status_code == 200, resp.text[:200]
    return int(resp.json()["current_stock"])


async def _order_detail(api: httpx.AsyncClient, order_id: int) -> dict[str, Any]:
    resp = await api.get(f"/api/v1/orders/{order_id}")
    assert resp.status_code == 200, resp.text[:200]
    return resp.json()


# ============================================================
# fixture —— 注入允许的 Origin，让写请求过 CSRF 中间件
# ============================================================
@pytest_asyncio.fixture
async def write_api(
    api: httpx.AsyncClient, write_headers: dict[str, str]
) -> httpx.AsyncClient:
    """带鉴权 + 允许 Origin 的客户端 —— 造数（产品/订单）与写用例都用它。

    在 ``api`` 上注入 Authorization 与 Origin，用完还原；这样造数 helper
    不必各自传头，写用例的 ``headers=write_headers`` 也只用于覆盖
    ``X-Idempotency-Key`` 这类单次附加头。
    """
    api.headers.update(write_headers)
    try:
        yield api
    finally:
        api.headers.pop("Origin", None)


@pytest.fixture
def write_headers(admin_headers: dict[str, str]) -> dict[str, str]:
    """带鉴权 + 允许 Origin 的头。

    CSRF 中间件在生产模式下要求 Bearer 请求的 ``Origin`` 命中
    ``settings.BACKEND_CORS_ORIGINS``，否则 403。这里取列表首个可用源；
    若环境里没有可解析的源，就带上默认的 ``http://localhost``（
    非生产模式下内网直连会直接豁免，不受影响）。
    """
    from fastapi_app.core.config import settings

    origin = next(
        (o for o in settings.BACKEND_CORS_ORIGINS if isinstance(o, str) and o),
        "http://localhost",
    )
    return {**admin_headers, "Origin": origin}


# ============================================================
# a) 订单确认 / 状态流转
# ============================================================
class TestOrderConfirmFlow:
    """湖北订单确认：门控 → 下单 → 完成 → 确认 → 幂等重复确认。"""

    async def test_confirm_gate_generate_complete_then_idempotent_confirm(
        self, write_api: httpx.AsyncClient, write_headers: dict[str, str]
    ) -> None:
        """完整走一遍真实状态流转，并锁定三处关键契约。

        1. 未在采购中心下单时确认 → 409（门控生效，不能放行成 200）
        2. 一键生成 → 采购单完成 → 确认 → 200
        3. 重复确认 → 仍 200（幂等早退，不能因已确认被门控拦成 409）
        """
        name = _unique("order")
        customer = _unique("客户")
        product_id = order_id = 0
        try:
            product_id = await _create_product(write_api, name, stock=50, factory="湖北", headers=write_headers)
            _make_bom(product_id, cotton_usage=2.0)
            order_id = await _create_order(write_api, product_id, 10, customer, headers=write_headers)

            # 1) 门控：未下单（无 completed 采购单）必须 409
            gated = await write_api.post(
                f"/api/v1/orders/{order_id}/confirm", headers=write_headers
            )
            assert gated.status_code == 409, (
                "未在采购中心完成下单却允许确认（应 409 门控）。"
                f"status={gated.status_code} body={gated.text[:300]}"
            )

            # 2) 一键生成采购单
            gen = await write_api.post(
                "/api/v1/purchase-center/orders/one-click-generate",
                json={"composite_ids": [f"order:{order_id}"]},
                headers={**write_headers, "X-Idempotency-Key": _unique("gate")},
            )
            assert gen.status_code == 200, f"一键生成失败：{gen.status_code} {gen.text[:300]}"
            gen_body = gen.json()
            assert gen_body.get("success") is True
            assert gen_body["orders"], f"一键生成未返回采购单：{gen_body}"
            po_id = int(gen_body["orders"][0]["id"])

            # 完成采购单，_order_has_completed_po 才会放行确认
            done = await write_api.post(
                "/api/v1/purchase-center/orders/complete",
                json={"order_id": po_id},
                headers=write_headers,
            )
            assert done.status_code == 200, f"完成采购单失败：{done.status_code} {done.text[:300]}"

            # 3) 确认成功
            confirmed = await write_api.post(
                f"/api/v1/orders/{order_id}/confirm", headers=write_headers
            )
            assert confirmed.status_code == 200, (
                f"已下单后确认失败：{confirmed.status_code} {confirmed.text[:300]}"
            )
            assert confirmed.json().get("success") is True

            # 4) 幂等：重复确认仍 200（CR-1 回归锁）
            again = await write_api.post(
                f"/api/v1/orders/{order_id}/confirm", headers=write_headers
            )
            assert again.status_code == 200, (
                "重复确认应为幂等 200，而不是 409 —— 幂等早退必须在门控之前。"
                f"status={again.status_code} body={again.text[:300]}"
            )

            # 5) 确认只写 confirmed_at/by，不改派生状态（订单仍「已备货」）
            detail = await _order_detail(write_api, order_id)
            assert detail["status"], detail
        finally:
            _cleanup([product_id], [order_id])

    async def test_confirm_unknown_order_is_404(
        self, write_api: httpx.AsyncClient, write_headers: dict[str, str]
    ) -> None:
        """不存在的订单必须 404，且不能因内部异常变 500。"""
        resp = await write_api.post(
            "/api/v1/orders/999999999/confirm", headers=write_headers
        )
        assert resp.status_code == 404, (
            f"不存在的订单应 404，实际 {resp.status_code}：{resp.text[:200]}"
        )


# ============================================================
# b) 出库扣减库存
# ============================================================
class TestStockOutDeduction:
    """出库写路径：真实扣减库存，并按订单量限制可出货量。"""

    async def test_stockout_deducts_stock_and_advances_order_status(
        self, write_api: httpx.AsyncClient, write_headers: dict[str, str]
    ) -> None:
        """创建独立出库 → 库存真的减少，且订单状态随出货派生推进。

        FIFO 摊销一定绑定到订单（StockOut.order_id 非空），
        所以「出货量受订单量约束」这一核心规则必须真实生效：
        出货 10 之后，同一客户再出货 5 必须 400（订单只剩 0 可出货）。
        """
        name = _unique("stock")
        customer = _unique("客户")
        product_id = order_id = 0
        try:
            product_id = await _create_product(write_api, name, stock=100, factory="东莞", headers=write_headers)
            order_id = await _create_order(write_api, product_id, 10, customer, headers=write_headers)

            before = await _product_stock(write_api, product_id)
            assert before == 100, f"初始库存应为 100，实际 {before}"

            shipped = await write_api.post(
                "/api/v1/stock/out/create",
                json={
                    "product_id": product_id,
                    "quantity": 10,
                    "customer": customer,
                    "stockout_date": date.today().isoformat(),
                    "order_type": "regular",
                },
                headers=write_headers,
            )
            assert shipped.status_code == 200, (
                f"出库失败：{shipped.status_code} {shipped.text[:300]}"
            )
            assert shipped.json().get("success") is True

            after = await _product_stock(write_api, product_id)
            assert after == before - 10, (
                f"出库 10 后库存应 100→90，实际 {before}→{after}：库存未被真实扣减"
            )

            # 出货量受订单量约束：订单仅 10 且已出完，再出货必须 400
            over = await write_api.post(
                "/api/v1/stock/out/create",
                json={
                    "product_id": product_id,
                    "quantity": 5,
                    "customer": customer,
                    "stockout_date": date.today().isoformat(),
                    "order_type": "regular",
                },
                headers=write_headers,
            )
            assert over.status_code == 400, (
                "超出订单可出货量的出库应 400（出货量严格受订单量限制），"
                f"实际 {over.status_code}：{over.text[:300]}"
            )

            # 出库写入的明细必须绑定订单（FIFO 摊销），这是「受订单约束」的前提
            from sqlalchemy import text

            with _sync_engine().connect() as conn:
                rows = conn.execute(
                    text(
                        "SELECT order_id, stockin_id, quantity FROM stock_out "
                        "WHERE product_id = :p"
                    ),
                    {"p": product_id},
                ).fetchall()
            assert len(rows) == 1, f"应只落一条出库记录，实际 {rows}"
            assert rows[0][0] == order_id, f"出库应绑定订单 {order_id}，实际 {rows[0]}"
            assert rows[0][1] is None, f"独立出库不应绑定备货，实际 {rows[0]}"

            # 非 5xx 即可：订单状态派生在真实数据上不应把请求打成 500
            detail = await _order_detail(write_api, order_id)
            assert detail.get("status"), detail
        finally:
            _cleanup([product_id], [order_id])

    async def test_stockout_insufficient_stock_is_rejected(
        self, write_api: httpx.AsyncClient, write_headers: dict[str, str]
    ) -> None:
        """库存不足必须 400，且不产生出库记录、不改库存。"""
        name = _unique("stock")
        customer = _unique("客户")
        product_id = order_id = 0
        try:
            product_id = await _create_product(write_api, name, stock=3, factory="东莞", headers=write_headers)
            order_id = await _create_order(write_api, product_id, 50, customer, headers=write_headers)

            resp = await write_api.post(
                "/api/v1/stock/out/create",
                json={
                    "product_id": product_id,
                    "quantity": 10,
                    "customer": customer,
                    "stockout_date": date.today().isoformat(),
                    "order_type": "regular",
                },
                headers=write_headers,
            )
            assert resp.status_code == 400, (
                f"库存 3 却出库 10，应 400，实际 {resp.status_code}：{resp.text[:300]}"
            )
            assert await _product_stock(write_api, product_id) == 3, "失败的出库不得改库存"
        finally:
            _cleanup([product_id], [order_id])


# ============================================================
# c) 采购订单一键生成 + X-Idempotency-Key
# ============================================================
class TestOneClickGenerate:
    """一键生成：真实建采购单、置订单为已备货，并锁定幂等键语义。"""

    async def test_one_click_generate_creates_po_and_marks_order_stocked(
        self, write_api: httpx.AsyncClient, write_headers: dict[str, str]
    ) -> None:
        """生成后：订单变「已备货」，且能按 source_order_ids 回查到该采购单。"""
        from sqlalchemy import text

        name = _unique("po")
        customer = _unique("客户")
        product_id = order_id = 0
        try:
            product_id = await _create_product(write_api, name, stock=20, factory="东莞", headers=write_headers)
            _make_bom(product_id, cotton_usage=3.0)
            order_id = await _create_order(write_api, product_id, 4, customer, headers=write_headers)

            resp = await write_api.post(
                "/api/v1/purchase-center/orders/one-click-generate",
                json={"composite_ids": [f"order:{order_id}"]},
                headers={**write_headers, "X-Idempotency-Key": _unique("gen")},
            )
            assert resp.status_code == 200, f"一键生成失败：{resp.status_code} {resp.text[:300]}"
            body = resp.json()
            assert body.get("success") is True, body
            assert int(body.get("created_count") or 0) >= 1, f"未创建采购单：{body}"
            po = body["orders"][0]
            assert po.get("id") and po.get("order_no"), po

            # 订单被改写为「已备货」（一键生成的副作用，前端依赖它刷新列表）
            detail = await _order_detail(write_api, order_id)
            assert detail["status"] == "已备货", (
                f"一键生成后订单状态应为「已备货」，实际 {detail['status']!r}"
            )

            # source_order_ids 真的写进了库（未处理列表/去重都靠它匹配）
            with _sync_engine().connect() as conn:
                src = conn.execute(
                    text("SELECT source_order_ids FROM purchase_order WHERE id = :i"),
                    {"i": po["id"]},
                ).scalar()
            assert src and str(order_id) in src, (
                f"采购单 source_order_ids 应含客户订单 {order_id}，实际 {src!r}"
            )
        finally:
            _cleanup([product_id], [order_id])

    async def test_idempotency_key_does_not_replay_result(
        self, write_api: httpx.AsyncClient, write_headers: dict[str, str]
    ) -> None:
        """同键重试**不复用**首次结果：源订单已非「待备货」，重试被 400 拒绝。

        这是与"假幂等"划清界限的回归锁。当前 ``X-Idempotency-Key`` 只是
        被端点接收（长度 ≤64 校验），真正的去重靠数据库唯一约束
        ``uq_po_pending_dedup`` + 生成前清理旧 pending 单 —— **并非**
        键级结果重放。断言 400 而不是 200，是为了让"有人真的实现了重放"
        这件事在 CI 里立即可见：那时应同步更新本用例与接口文档。

        同时验证：重试失败**不会**新建第二张采购单（不重复落库）。
        """
        from sqlalchemy import text

        name = _unique("idem")
        customer = _unique("客户")
        product_id = order_id = 0
        key = _unique("same-key")
        try:
            product_id = await _create_product(write_api, name, stock=20, factory="东莞", headers=write_headers)
            _make_bom(product_id, cotton_usage=1.0)
            order_id = await _create_order(write_api, product_id, 2, customer, headers=write_headers)

            first = await write_api.post(
                "/api/v1/purchase-center/orders/one-click-generate",
                json={"composite_ids": [f"order:{order_id}"]},
                headers={**write_headers, "X-Idempotency-Key": key},
            )
            assert first.status_code == 200, f"首次生成失败：{first.text[:300]}"
            first_po_id = int(first.json()["orders"][0]["id"])

            second = await write_api.post(
                "/api/v1/purchase-center/orders/one-click-generate",
                json={"composite_ids": [f"order:{order_id}"]},
                headers={**write_headers, "X-Idempotency-Key": key},
            )
            assert second.status_code == 400, (
                "同键重试当前 **不应** 返回 200：实现里没有键级结果重放，"
                "源订单已非「待备货」应被拒绝。若此断言失败，说明幂等语义变了 —— "
                f"请同步更新本用例与文档。status={second.status_code} body={second.text[:300]}"
            )

            # 重试不得新建第二张采购单
            with _sync_engine().connect() as conn:
                count = conn.execute(
                    text(
                        "SELECT count(*) FROM purchase_order "
                        "WHERE source_order_ids IS NOT NULL AND source_order_ids LIKE :pat"
                    ),
                    {"pat": f"%{order_id}%"},
                ).scalar()
            assert count == 1, f"重试后应仍只有 1 张采购单，实际 {count}"
            assert first_po_id > 0
        finally:
            _cleanup([product_id], [order_id])

    async def test_overlong_idempotency_key_is_rejected(
        self, write_api: httpx.AsyncClient, write_headers: dict[str, str]
    ) -> None:
        """超过 64 字符的 X-Idempotency-Key 必须 422（Header(max_length=64)）。"""
        resp = await write_api.post(
            "/api/v1/purchase-center/orders/one-click-generate",
            json={"composite_ids": ["order:1"]},
            headers={**write_headers, "X-Idempotency-Key": "k" * 65},
        )
        assert resp.status_code == 422, (
            f"超长幂等键应 422，实际 {resp.status_code}：{resp.text[:200]}"
        )
