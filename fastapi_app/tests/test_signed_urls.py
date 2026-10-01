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
    monkeypatch.delenv("UPLOAD_URL_SIGNING_SECRET", raising=False)


def test_no_secret_returns_plain_url():
    """密钥未配置 = 签发禁用，返回原 URL（fail-safe 联动）。"""
    assert signed_urls.sign_upload_url("a/b.webp") == "/static/uploads/a/b.webp"


def test_sign_and_verify_roundtrip(monkeypatch):
    monkeypatch.setenv("UPLOAD_URL_SIGNING_SECRET", "s3cret")
    url = signed_urls.sign_upload_url("20261001/abc.webp", ttl_seconds=600)
    assert "st=" in url and "s=" in url

    from urllib.parse import parse_qs, urlparse

    q = parse_qs(urlparse(url).query)
    key = "20261001/abc.webp"
    assert signed_urls.verify_signature(key, int(q["st"][0]), q["s"][0]) is True


def test_expired_signature_rejected(monkeypatch):
    monkeypatch.setenv("UPLOAD_URL_SIGNING_SECRET", "s3cret")
    past = int(time.time()) - 10
    assert signed_urls.verify_signature("k/x.png", past, "AAAA") is False


def test_tampered_signature_rejected(monkeypatch):
    monkeypatch.setenv("UPLOAD_URL_SIGNING_SECRET", "s3cret")
    url = signed_urls.sign_upload_url("k/x.png", ttl_seconds=600)
    from urllib.parse import parse_qs, urlparse

    q = parse_qs(urlparse(url).query)
    sig = q["s"][0]
    tampered = ("A" if sig[0] != "A" else "B") + sig[1:]
    assert signed_urls.verify_signature("k/x.png", int(q["st"][0]), tampered) is False
    # 换 key 也不行
    assert signed_urls.verify_signature("k/other.png", int(q["st"][0]), sig) is False


def test_nginx_secure_link_md5_alignment(monkeypatch):
    """核对与 nginx `secure_link_md5 "$secure_link_expires$uri secret"` 的公式一致。"""
    secret = "topsecret"
    monkeypatch.setenv("UPLOAD_URL_SIGNING_SECRET", secret)
    expired = 1750000000
    key = "20261001/x.webp"
    uri = quote(f"/static/uploads/{key}", safe="/")

    url = signed_urls.sign_upload_url(key, ttl_seconds=expired - int(time.time()))
    got = url.split("s=")[1]

    expect = base64.urlsafe_b64encode(
        hashlib.md5(f"{expired}{uri} {secret}".encode()).digest()  # secret 前有空格（nginx conf 写法）
    ).rstrip(b"=").decode()
    assert got == expect
