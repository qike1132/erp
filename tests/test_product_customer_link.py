"""SKU 客户归属（product_customer）——搜索可见性过滤与产品关联维护

业务约定（2026-10-09 用户裁定）：
- 一个 SKU 可属于多个客户（多对多）。
- **未挂客户的 SKU 对所有客户可见**（兼容存量数据，上线不打断下单）。
- 下单 / 出货 / 备货 / 备货计划共用 GET /aux/product-search，按客户过滤在此收口。

本文件走真实测试库（conftest 的 test_engine 由 Base.metadata.create_all 建表），
不 mock SQL —— 可见性是一个「查询条件是否真的生效」的问题，mock 掉 execute
会把「条件写没写对」一起 mock 掉。
"""
import uuid

from sqlalchemy import select

from fastapi_app.services import product_service
from fastapi_app.services.product_search_service import ProductSearchService
from fastapi_app.shared_models import Customer, Product, ProductCustomer


async def _make_customer(session, name: str) -> Customer:
    customer = Customer(name=name, status=True)
    session.add(customer)
    await session.flush()
    return customer


async def _make_product(session, name: str, barcode: str, customer_ids: list[int] | None = None) -> Product:
    product = Product(name=name, barcode=barcode, initial_stock=0, current_stock=0)
    session.add(product)
    await session.flush()
    for customer_id in customer_ids or []:
        session.add(ProductCustomer(product_id=product.id, customer_id=customer_id))
    await session.flush()
    return product


async def test_search_visibility_by_customer(async_db_session):
    """按客户过滤：只返回「属于该客户」或「未挂客户」的 SKU。

    同一个测试里连续查两个客户，是为了让 Redis 降级的内存缓存真正被命中：
    若缓存键没有带上客户维度，第二次查询会直接返回第一个客户的结果而失败。
    """
    token = uuid.uuid4().hex[:8]
    cust_a = await _make_customer(async_db_session, f"{token}-客户甲")
    cust_b = await _make_customer(async_db_session, f"{token}-客户乙")

    p_a = await _make_product(async_db_session, f"{token}-甲", f"{token}A", [cust_a.id])
    p_b = await _make_product(async_db_session, f"{token}-乙", f"{token}B", [cust_b.id])
    p_free = await _make_product(async_db_session, f"{token}-未分配", f"{token}F")

    svc = ProductSearchService()

    names_for_a = {
        r["name"]
        for r in await svc.search_visible_to_customer_async_with_cache(async_db_session, token, limit=50, customer_id=cust_a.id)
    }
    assert p_a.name in names_for_a
    assert p_free.name in names_for_a
    assert p_b.name not in names_for_a, "甲不应看到乙的专属 SKU"

    names_for_b = {
        r["name"]
        for r in await svc.search_visible_to_customer_async_with_cache(async_db_session, token, limit=50, customer_id=cust_b.id)
    }
    assert p_b.name in names_for_b
    assert p_free.name in names_for_b
    assert p_a.name not in names_for_b, "乙不应看到甲的专属 SKU"


async def test_search_without_customer_returns_everything(async_db_session):
    """不传客户 = 不过滤（向后兼容：未选客户时列表与现状一致）。"""
    token = uuid.uuid4().hex[:8]
    cust = await _make_customer(async_db_session, f"{token}-客户")
    p_linked = await _make_product(async_db_session, f"{token}-专属", f"{token}A", [cust.id])
    p_free = await _make_product(async_db_session, f"{token}-未分配", f"{token}F")

    svc = ProductSearchService()
    names = {
        r["name"]
        for r in await svc.search_visible_to_customer_async_with_cache(async_db_session, token, limit=50)
    }
    assert {p_linked.name, p_free.name} <= names


async def test_search_shared_product_visible_to_both_customers(async_db_session):
    """一个 SKU 挂多个客户时，两个客户都能搜到它。"""
    token = uuid.uuid4().hex[:8]
    cust_a = await _make_customer(async_db_session, f"{token}-客户甲")
    cust_b = await _make_customer(async_db_session, f"{token}-客户乙")
    shared = await _make_product(async_db_session, f"{token}-共享", f"{token}S", [cust_a.id, cust_b.id])

    svc = ProductSearchService()
    for customer in (cust_a, cust_b):
        names = {
            r["name"]
            for r in await svc.search_visible_to_customer_async_with_cache(async_db_session, token, limit=50, customer_id=customer.id)
        }
        assert shared.name in names


# ==================== 产品列表：客户字段与筛选 ====================

async def test_product_list_carries_customers_and_filters_by_customer(async_db_session):
    """列表项带 customers；customer_id 过滤只留「该客户 + 未挂客户」。"""
    token = uuid.uuid4().hex[:8]
    cust_a = await _make_customer(async_db_session, f"{token}-甲")
    cust_b = await _make_customer(async_db_session, f"{token}-乙")
    p_a = await _make_product(async_db_session, f"{token}-P甲", f"{token}A", [cust_a.id])
    p_b = await _make_product(async_db_session, f"{token}-P乙", f"{token}B", [cust_b.id])
    p_free = await _make_product(async_db_session, f"{token}-P未", f"{token}F")

    page = await product_service.get_products_page(
        async_db_session, page=1, per_page=200, search=token)
    by_name = {item["name"]: item for item in page["items"]}
    assert [c["name"] for c in by_name[p_a.name]["customers"]] == [cust_a.name]
    assert [c["name"] for c in by_name[p_b.name]["customers"]] == [cust_b.name]
    assert by_name[p_free.name]["customers"] == []

    filtered = await product_service.get_products_page(
        async_db_session, page=1, per_page=200, search=token, customer_id=cust_a.id)
    assert {item["name"] for item in filtered["items"]} == {p_a.name, p_free.name}


async def test_product_list_only_unassigned(async_db_session):
    """only_unassigned：只列没挂客户的 SKU（用于补齐存量）。"""
    token = uuid.uuid4().hex[:8]
    cust = await _make_customer(async_db_session, f"{token}-客户")
    p_linked = await _make_product(async_db_session, f"{token}-已挂", f"{token}A", [cust.id])
    p_free = await _make_product(async_db_session, f"{token}-未挂", f"{token}F")

    page = await product_service.get_products_page(
        async_db_session, page=1, per_page=200, search=token, only_unassigned=True)
    names = {item["name"] for item in page["items"]}
    assert names == {p_free.name}
    assert p_linked.name not in names


# ==================== 产品增改：客户关联维护 ====================

async def test_create_product_links_customers(async_db_session):
    token = uuid.uuid4().hex[:8]
    cust_a = await _make_customer(async_db_session, f"{token}-甲")
    cust_b = await _make_customer(async_db_session, f"{token}-乙")

    created = await product_service.create_product(
        async_db_session, name=f"{token}-新建", barcode=f"{token}N",
        image=None, initial_stock=0, customer_ids=[cust_a.id, cust_b.id])

    linked = (await async_db_session.execute(
        select(ProductCustomer.customer_id).where(ProductCustomer.product_id == created["id"])
    )).scalars().all()
    assert sorted(linked) == sorted([cust_a.id, cust_b.id])


async def test_update_product_replaces_and_clears_customer_links(async_db_session):
    token = uuid.uuid4().hex[:8]
    cust_a = await _make_customer(async_db_session, f"{token}-甲")
    cust_b = await _make_customer(async_db_session, f"{token}-乙")
    product = await _make_product(async_db_session, f"{token}-改", f"{token}U", [cust_a.id])

    async def linked_ids() -> list[int]:
        return sorted((await async_db_session.execute(
            select(ProductCustomer.customer_id).where(ProductCustomer.product_id == product.id)
        )).scalars().all())

    # None = 不改动
    await product_service.update_product(
        async_db_session, product.id, name=None, barcode=None, image=None, initial_stock=None)
    assert await linked_ids() == [cust_a.id]

    # 传入新集合 = 整体替换
    await product_service.update_product(
        async_db_session, product.id, name=None, barcode=None, image=None, initial_stock=None,
        customer_ids=[cust_b.id])
    assert await linked_ids() == [cust_b.id]

    # 空列表 = 清空（回到「所有客户可见」）
    await product_service.update_product(
        async_db_session, product.id, name=None, barcode=None, image=None, initial_stock=None,
        customer_ids=[])
    assert await linked_ids() == []


# ==================== 端点：/aux/product-search 按客户过滤 ====================

async def test_aux_product_search_endpoint_filters_by_customer(async_client, async_db_session, auth_headers):
    """下单/出货/备货/备货计划共用的搜索端点：?customer=<客户名> 生效。"""
    token = uuid.uuid4().hex[:8]
    cust_a = await _make_customer(async_db_session, f"{token}-甲")
    cust_b = await _make_customer(async_db_session, f"{token}-乙")
    p_a = await _make_product(async_db_session, f"{token}-P甲", f"{token}A", [cust_a.id])
    p_b = await _make_product(async_db_session, f"{token}-P乙", f"{token}B", [cust_b.id])

    resp = await async_client.get(
        "/api/v1/aux/product-search", params={"q": token, "customer": cust_a.name},
        headers=auth_headers)
    assert resp.status_code == 200
    names = {item["name"] for item in resp.json()}
    assert p_a.name in names
    assert p_b.name not in names


async def test_aux_product_search_endpoint_without_customer_returns_all(async_client, async_db_session, auth_headers):
    token = uuid.uuid4().hex[:8]
    cust = await _make_customer(async_db_session, f"{token}-客户")
    p_linked = await _make_product(async_db_session, f"{token}-专属", f"{token}A", [cust.id])
    p_free = await _make_product(async_db_session, f"{token}-未挂", f"{token}F")

    resp = await async_client.get(
        "/api/v1/aux/product-search", params={"q": token}, headers=auth_headers)
    assert resp.status_code == 200
    names = {item["name"] for item in resp.json()}
    assert {p_linked.name, p_free.name} <= names


# ==================== 浏览模式：空关键字 + 有客户 ====================
# 2026-10-10：下单页「产品名称」改成点击弹 SKU 列表，点开时还没有关键字，
# 需要端点能把该客户可见的 SKU 列出来。未选客户时仍返回空 —— 否则会把
# 全部 SKU 放出来，与「只列当前客户的 SKU」的约定相反。

async def test_aux_product_search_empty_keyword_lists_customer_visible_skus(
        async_client, async_db_session, auth_headers):
    token = uuid.uuid4().hex[:8]
    cust_a = await _make_customer(async_db_session, f"{token}-甲")
    cust_b = await _make_customer(async_db_session, f"{token}-乙")
    p_a = await _make_product(async_db_session, f"{token}-P甲", f"{token}A", [cust_a.id])
    p_b = await _make_product(async_db_session, f"{token}-P乙", f"{token}B", [cust_b.id])
    p_free = await _make_product(async_db_session, f"{token}-P未", f"{token}F")

    resp = await async_client.get(
        "/api/v1/aux/product-search", params={"customer": cust_a.name}, headers=auth_headers)
    assert resp.status_code == 200
    names = {item["name"] for item in resp.json()}
    assert p_a.name in names, "甲自己的 SKU 要列出来"
    assert p_free.name in names, "未挂客户的 SKU 对所有客户可见，也要列出来"
    assert p_b.name not in names, "乙的专属 SKU 不能出现在甲的浏览列表里"


async def test_aux_product_search_empty_keyword_without_customer_returns_empty(
        async_client, async_db_session, auth_headers):
    """没选客户就点开弹窗 → 返回空（前端据此提示「请先选择客户」），不能返回全部产品。"""
    token = uuid.uuid4().hex[:8]
    await _make_product(async_db_session, f"{token}-随便一个", f"{token}X")

    resp = await async_client.get(
        "/api/v1/aux/product-search", params={"q": ""}, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == []


async def test_aux_product_search_empty_keyword_unknown_customer_returns_empty(
        async_client, async_db_session, auth_headers):
    token = uuid.uuid4().hex[:8]
    await _make_product(async_db_session, f"{token}-随便一个", f"{token}X")

    resp = await async_client.get(
        "/api/v1/aux/product-search",
        params={"customer": f"{token}-不存在的客户"}, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == []


async def test_aux_product_search_limit_is_honored(async_client, async_db_session, auth_headers):
    """浏览要一次列一批（默认给 200），但上限必须被尊重。"""
    token = uuid.uuid4().hex[:8]
    cust = await _make_customer(async_db_session, f"{token}-客户")
    for i in range(4):
        await _make_product(async_db_session, f"{token}-批量{i}", f"{token}{i}", [cust.id])

    resp = await async_client.get(
        "/api/v1/aux/product-search",
        params={"customer": cust.name, "limit": 2}, headers=auth_headers)
    assert resp.status_code == 200
    assert len(resp.json()) == 2
