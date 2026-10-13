"""signed_urls 签发/校验单测（OPT-19）。

覆盖：密钥未配置 fail-safe（返回原 URL）、签名往返一致、过期拒绝、
篡改拒绝、nginx secure_link_md5 对齐（用已知输入核对摘要公式）。
"""

import base64
import hashlib
import time
from urllib.parse import quote

import pytest

from fastapi_app.services import signed_urls


@pytest.fixture(autouse=True)
def _clean_secret(monkeypatch):
    monkeypatch.delenv('UPLOAD_URL_SIGNING_SECRET', raising=False)


def test_no_secret_returns_plain_url():
    """密钥未配置 = 签发禁用，返回原 URL（fail-safe 联动）。"""
    assert signed_urls.sign_upload_url('a/b.webp') == '/static/uploads/a/b.webp'


def test_sign_and_verify_roundtrip(monkeypatch):
    monkeypatch.setenv('UPLOAD_URL_SIGNING_SECRET', 's3cret')
    url = signed_urls.sign_upload_url('20261001/abc.webp', ttl_seconds=600)
    assert 'st=' in url and 's=' in url

    from urllib.parse import parse_qs, urlparse

    q = parse_qs(urlparse(url).query)
    key = '20261001/abc.webp'
    assert signed_urls.verify_signature(key, int(q['st'][0]), q['s'][0]) is True


def test_expired_signature_rejected(monkeypatch):
    monkeypatch.setenv('UPLOAD_URL_SIGNING_SECRET', 's3cret')
    past = int(time.time()) - 10
    assert signed_urls.verify_signature('k/x.png', past, 'AAAA') is False


def test_tampered_signature_rejected(monkeypatch):
    monkeypatch.setenv('UPLOAD_URL_SIGNING_SECRET', 's3cret')
    url = signed_urls.sign_upload_url('k/x.png', ttl_seconds=600)
    from urllib.parse import parse_qs, urlparse

    q = parse_qs(urlparse(url).query)
    sig = q['s'][0]
    tampered = ('A' if sig[0] != 'A' else 'B') + sig[1:]
    assert signed_urls.verify_signature('k/x.png', int(q['st'][0]), tampered) is False
    # 换 key 也不行
    assert signed_urls.verify_signature('k/other.png', int(q['st'][0]), sig) is False


def test_nginx_secure_link_md5_alignment(monkeypatch):
    """核对与 nginx `secure_link_md5 "$secure_link_expires$uri secret"` 的公式一致。

    st 现在对齐到时间桶（test_repeated_signs_within_bucket_are_identical），
    因此这里不再硬编码目标 expired 反推 ttl，而是取签发结果里**实际的 st**
    核对 md5 公式 —— 公式本身必须逐字节稳定（2026-10-01 实测无空格签名 403）。
    """
    secret = 'topsecret'
    monkeypatch.setenv('UPLOAD_URL_SIGNING_SECRET', secret)
    key = '20261001/x.webp'
    uri = quote(f'/static/uploads/{key}', safe='/')

    url = signed_urls.sign_upload_url(key, ttl_seconds=600)
    got = url.split('s=')[1]
    st = int(url.split('st=')[1].split('&')[0])

    expect = (
        base64.urlsafe_b64encode(
            hashlib.md5(f'{st}{uri} {secret}'.encode(), usedforsecurity=False).digest()  # secret 前有空格（nginx conf 写法）；usedforsecurity=False：与 nginx secure_link_md5 对齐，非安全用途
        )
        .rstrip(b'=')
        .decode()
    )
    assert got == expect


def test_sign_idempotent_and_full_path(monkeypatch):
    """幂等：已签名 URL 原样返回；完整路径自动剥前缀（2026-10-01 前端切换补充）。"""
    monkeypatch.setenv('UPLOAD_URL_SIGNING_SECRET', 's3cret')
    signed = signed_urls.sign_upload_url('a/b.webp', ttl_seconds=600)
    assert signed_urls.sign_upload_url(signed) == signed  # 已带 query 不二次签名
    # 完整路径与裸 key 结果一致
    from urllib.parse import parse_qs, urlparse

    q1 = parse_qs(urlparse(signed_urls.sign_upload_url('/static/uploads/a/b.webp', ttl_seconds=600)).query)
    q2 = parse_qs(urlparse(signed).query)
    assert q1['s'] == q2['s']


_PRODUCT_LIST_ITEM = {
    'id': 1, 'name': '测试产品', 'barcode': None, 'price': 1.0,
    'image': '/static/uploads/20261001/a.webp', 'factory': None,
    'initial_stock': 0, 'current_stock': 0, 'create_time': None,
}


def test_product_list_response_signs_image(monkeypatch):
    """回归：产品列表项的 image 必须经 ProductListResponse 签发。

    列表项曾是裸 list[dict]，不走 ProductResponse 的 sign_image_url 校验器，
    于是列表页的 image 不带 st/s 参数 —— nginx secure_link 生效后整页图片 403
    （详情页走 ProductResponse 有签发，故此前只有列表这一处漏掉）。
    """
    monkeypatch.setenv('UPLOAD_URL_SIGNING_SECRET', 's3cret')

    from fastapi_app.schemas.product import ProductListResponse

    resp = ProductListResponse(items=[dict(_PRODUCT_LIST_ITEM)], total=1)

    image = resp.items[0].image
    assert image is not None
    assert 'st=' in image and 's=' in image
    assert image.startswith('/static/uploads/20261001/a.webp?')


def test_product_list_response_keeps_plain_url_without_secret():
    """密钥未配置时列表项 image 原样返回（与签发层的 fail-safe 联动）。"""
    from fastapi_app.schemas.product import ProductListResponse

    resp = ProductListResponse(items=[dict(_PRODUCT_LIST_ITEM)], total=1)

    assert resp.items[0].image == '/static/uploads/20261001/a.webp'


def test_absolute_image_url_is_not_signed(monkeypatch):
    """外部直链不得被签发改写（回归 N-3）。

    入库侧 sanitize_url 明确放行 http/https 等绝对 URL，而出站签发会把任意
    非 /static/uploads/ 的值拼成 /static/uploads/<值>，照签会把外链拼成
    /static/uploads/https://... 而损坏。协议相对（//host/...）同理。
    """
    monkeypatch.setenv('UPLOAD_URL_SIGNING_SECRET', 's3cret')
    from fastapi_app.schemas.product import ProductResponse

    for url in ('https://cdn.example.com/a.png', 'http://x/a.png', '//cdn.x/a.png'):
        resp = ProductResponse(id=1, name='P', initial_stock=0, current_stock=0, image=url)
        assert resp.image == url, f'{url} 被签发改写了'


def test_local_upload_path_is_signed(monkeypatch):
    """对照：本地上传路径仍照常签发（确认上面那条不是把签发整个关掉）。"""
    monkeypatch.setenv('UPLOAD_URL_SIGNING_SECRET', 's3cret')
    from fastapi_app.schemas.product import ProductResponse

    resp = ProductResponse(
        id=1, name='P', initial_stock=0, current_stock=0,
        image='/static/uploads/20261001/a.webp',
    )
    assert resp.image is not None
    assert resp.image.startswith('/static/uploads/20261001/a.webp?')
    assert 'st=' in resp.image and 's=' in resp.image


def test_strip_upload_signature_removes_query():
    """回归（2026-10-02 P4/P5 审计）：入库前必须剥掉限时签名 query。

    上传接口回传的是已签名 URL；若原样入库，读时 sign_upload_url 会因"已含 ?"
    走幂等分支**原样返回**（不重签）→ 过了 st 的到期时间 nginx secure_link 返回
    410，图片永久失效。产品新增/编辑（哪怕只改名）约 1 小时后即触发。
    """
    from fastapi_app.services.signed_urls import strip_upload_signature

    assert strip_upload_signature(
        '/static/uploads/2026/10/x.webp?st=1759&s=abc'
    ) == '/static/uploads/2026/10/x.webp'
    # 无签名的原样返回
    assert strip_upload_signature('/static/uploads/a.webp') == '/static/uploads/a.webp'
    assert strip_upload_signature('') == ''
    # 兼容裸 storage key 形态（无前缀但带本系统签名参数）
    assert strip_upload_signature('2026/10/x.webp?st=1&s=abc') == '2026/10/x.webp'
    # **自站绝对 URL**（用户从地址栏整串粘贴）：path 落在地上传目录 → 要剥，
    # 且必须**还原成相对 path** —— 出站 sign_image_url 对带 scheme 的值原样返回不重签，
    # 若把绝对 URL 落库，nginx secure_link 会**立即 403**（比过期 410 更糟）。
    assert strip_upload_signature(
        'https://host:3000/static/uploads/x.webp?st=1&s=abc'
    ) == '/static/uploads/x.webp'
    assert strip_upload_signature(
        '//host/static/uploads/x.webp?st=1&s=abc'
    ) == '/static/uploads/x.webp'
    # scheme 大小写不敏感
    assert strip_upload_signature(
        'HTTPS://HOST/static/uploads/x.webp?st=1&s=abc'
    ) == '/static/uploads/x.webp'
    # ⚠️ 外部绝对 URL **不动**：query 是对方 CDN 签发的，剥掉会让外链失效
    # （schemas/product.py 明确放行外部 http(s) 直链）
    assert strip_upload_signature('https://cdn.x/a.png?v=1') == 'https://cdn.x/a.png?v=1'
    assert strip_upload_signature('https://cdn.x/a.png?token=abc') == 'https://cdn.x/a.png?token=abc'
    assert strip_upload_signature('//cdn.x/a.png?token=abc') == '//cdn.x/a.png?token=abc'


def test_stripped_url_is_reissued_not_passthrough(monkeypatch):
    """剥签名后再签发，必须得到**新鲜签名**而不是过期透传。"""
    monkeypatch.setenv('UPLOAD_URL_SIGNING_SECRET', 's3cret')
    from fastapi_app.services.signed_urls import sign_upload_url, strip_upload_signature

    expired = '/static/uploads/2026/10/x.webp?st=1&s=deadbeef'
    # 未剥：幂等透传，拿回的是同一个已过期串
    assert sign_upload_url(expired) == expired
    # 剥后再签：重新签发，带上全新的 st/s
    fresh = sign_upload_url(strip_upload_signature(expired))
    assert fresh != expired
    assert fresh.startswith('/static/uploads/2026/10/x.webp?')
    assert 'st=' in fresh and 's=' in fresh


def test_repeated_signs_within_bucket_are_identical(monkeypatch):
    """回归（2026-10-09 用户报告）：翻页后图片延迟 1-2s 才显示。

    根因：st=int(time.time())+ttl 每秒都变 → 翻页后同一张图的 URL query
    不同 → 浏览器缓存全失效，每页 ~25 张图全部重下。
    修复：expired 对齐到时间桶（BUCKET 秒的整数倍），桶内重复签发得到
    **逐字节相同**的 URL → 浏览器磁盘缓存命中，翻页秒显。
    安全性：桶化只让实际有效期在 ttl ~ ttl+BUCKET 之间浮动，nginx
    secure_link 的过期判定与签名公式零改动。
    """
    monkeypatch.setenv('UPLOAD_URL_SIGNING_SECRET', 's3cret')
    u1 = signed_urls.sign_upload_url('k/a.webp', ttl_seconds=600)
    u2 = signed_urls.sign_upload_url('k/a.webp', ttl_seconds=600)
    assert u1 == u2, '桶内重复签发必须得到相同 URL（浏览器缓存命中的前提）'


def test_bucket_expiry_stays_in_ttl_window(monkeypatch):
    """桶化后的 st 必须落在 [now+ttl, now+ttl+BUCKET) —— 有效期不缩水。"""
    monkeypatch.setenv('UPLOAD_URL_SIGNING_SECRET', 's3cret')
    ttl, bucket = 600, signed_urls.SIGN_EXPIRY_BUCKET_SECONDS
    st = int(signed_urls.sign_upload_url('k/a.webp', ttl_seconds=ttl).split('st=')[1].split('&')[0])
    now = int(time.time())
    assert now + ttl <= st <= now + ttl + bucket


def test_verify_still_works_with_bucketed_expiry(monkeypatch):
    """桶化时间戳经 verify_signature 校验必须通过（公式未变）。"""
    monkeypatch.setenv('UPLOAD_URL_SIGNING_SECRET', 's3cret')
    url = signed_urls.sign_upload_url('k/a.webp', ttl_seconds=600)
    from urllib.parse import parse_qs, urlparse

    q = parse_qs(urlparse(url).query)
    assert signed_urls.verify_signature('k/a.webp', int(q['st'][0]), q['s'][0]) is True


def test_product_response_derives_signed_image_thumb(monkeypatch):
    """回归（2026-10-13 图片优化）：ProductResponse 必须出站派生 image_thumb。

    列表页此前直接用原图：存量 50 张 png/jpg 合计 ~50MB（最大 4.1MB），每页图片
    流量数十 MB。缩略图 key 是确定性后缀（原图 key + '.thumb.webp'），故由已签名的
    image 直接派生即可，无需给 DB 加列。这里核对派生出的路径与签发参数。
    """
    monkeypatch.setenv('UPLOAD_URL_SIGNING_SECRET', 's3cret')
    from fastapi_app.schemas.product import ProductResponse

    resp = ProductResponse(
        id=1, name='P', initial_stock=0, current_stock=0,
        image='/static/uploads/20261001/a.png',
    )
    assert resp.image_thumb is not None
    assert resp.image_thumb.startswith('/static/uploads/20261001/a.png.thumb.webp?')
    assert 'st=' in resp.image_thumb and 's=' in resp.image_thumb
    # 与主图落在同一个时间桶 —— 否则两者缓存生命周期不一致
    assert (resp.image_thumb.split('st=')[1].split('&')[0]
            == resp.image.split('st=')[1].split('&')[0])
    # 缩略图 key 与主图 key 不同 → 摘要必须不同（防「原样透传主图」的退化）
    assert resp.image_thumb.split('s=')[1] != resp.image.split('s=')[1]


def test_image_thumb_is_none_for_external_url(monkeypatch):
    """外部直链没有本地缩略图 → image_thumb 必须为 None（前端据此回退原图）。"""
    monkeypatch.setenv('UPLOAD_URL_SIGNING_SECRET', 's3cret')
    from fastapi_app.schemas.product import ProductResponse

    for url in ('https://cdn.example.com/a.png', 'http://x/a.png', '//cdn.x/a.png'):
        resp = ProductResponse(id=1, name='P', initial_stock=0, current_stock=0, image=url)
        assert resp.image_thumb is None, f'{url} 不该派生出缩略图'


def test_image_thumb_is_none_without_image():
    """无图 → 两个字段都为 None。"""
    from fastapi_app.schemas.product import ProductResponse

    resp = ProductResponse(id=1, name='P', initial_stock=0, current_stock=0, image=None)
    assert resp.image is None and resp.image_thumb is None


def test_image_thumb_unsigned_when_no_secret():
    """密钥未配置时缩略图 URL 不带签名（与签发层 fail-safe 联动）。"""
    from fastapi_app.schemas.product import ProductResponse

    resp = ProductResponse(
        id=1, name='P', initial_stock=0, current_stock=0,
        image='/static/uploads/20261001/a.png',
    )
    assert resp.image_thumb == '/static/uploads/20261001/a.png.thumb.webp'
