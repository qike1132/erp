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
    """核对与 nginx `secure_link_md5 "$secure_link_expires$uri secret"` 的公式一致。"""
    secret = 'topsecret'
    monkeypatch.setenv('UPLOAD_URL_SIGNING_SECRET', secret)
    expired = 1750000000
    key = '20261001/x.webp'
    uri = quote(f'/static/uploads/{key}', safe='/')

    url = signed_urls.sign_upload_url(key, ttl_seconds=expired - int(time.time()))
    got = url.split('s=')[1]

    expect = (
        base64.urlsafe_b64encode(
            hashlib.md5(f'{expired}{uri} {secret}'.encode()).digest()  # secret 前有空格（nginx conf 写法）
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
