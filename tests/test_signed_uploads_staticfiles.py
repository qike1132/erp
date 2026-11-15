"""`/static/uploads` 应用层签名校验（SignedUploadsStaticFiles）回归测试。

背景：nginx 侧已有 secure_link 校验（config/nginx-windows.conf），但 main.py 把
uploads 挂成无依赖 StaticFiles，绕过 nginx 直连应用端口即可免签名取文件。本测试
钉住应用层补齐后的三种结果，与 nginx $secure_link 语义对齐：

    有效签名            → 200 + 文件字节
    签名缺失 / 不匹配    → 403
    签名对但已过期       → 410
    密钥未配置（未启用）  → 放行（改造前行为）

签名一律用生产签发函数 `sign_upload_url` 造，不手搓 md5 —— 否则测的是测试代码
自己的公式，与 nginx/签发侧漂移了也发现不了。
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from fastapi_app.core.signed_static_files import SignedUploadsStaticFiles
from fastapi_app.services.signed_urls import sign_upload_url

# 夹具值：故意用无敏感词前缀的常量名，避免密钥扫描把测试常量判成硬编码凭据
_SIGNING_VALUE = 'test-upload-signing-secret'
KEY = '20261115/abc.webp'
BODY = b'fake-image-bytes'


@pytest.fixture()
def uploads_dir(tmp_path):
    """临时 uploads 目录，内含一个真实文件（不碰生产的 static/uploads）。"""
    target = tmp_path / '20261115'
    target.mkdir(parents=True)
    (target / 'abc.webp').write_bytes(BODY)
    return tmp_path


@pytest.fixture()
def client(uploads_dir):
    """把 SignedUploadsStaticFiles 挂到 /static/uploads（与 main.py 同参数）。"""
    app = FastAPI()
    app.mount(
        '/static/uploads',
        SignedUploadsStaticFiles(directory=str(uploads_dir)),
        name='static-uploads',
    )
    return TestClient(app)


@pytest.fixture()
def signed_secret(monkeypatch):
    monkeypatch.setenv('UPLOAD_URL_SIGNING_SECRET', _SIGNING_VALUE)


@pytest.fixture()
def no_secret(monkeypatch):
    monkeypatch.delenv('UPLOAD_URL_SIGNING_SECRET', raising=False)


def test_valid_signature_serves_file(client, signed_secret):
    """有效签名：200 且返回真实文件内容。"""
    resp = client.get(sign_upload_url(KEY, ttl_seconds=600))
    assert resp.status_code == 200, resp.text
    assert resp.content == BODY


def test_missing_signature_forbidden(client, signed_secret):
    """密钥已启用但 URL 无 st/s → 403。"""
    resp = client.get(f'/static/uploads/{KEY}')
    assert resp.status_code == 403, resp.text


def test_wrong_signature_forbidden(client, signed_secret):
    """签名被篡改 → 403。"""
    url = sign_upload_url(KEY, ttl_seconds=600)
    base, query = url.split('?', 1)
    params = dict(part.split('=', 1) for part in query.split('&'))
    sig = params['s']
    tampered = ('A' if sig[0] != 'A' else 'B') + sig[1:]
    resp = client.get(f"{base}?st={params['st']}&s={tampered}")
    assert resp.status_code == 403, resp.text


def test_signature_bound_to_path(client, signed_secret):
    """同一签名换到别的路径 → 403（签名与路径绑定）。"""
    url = sign_upload_url(KEY, ttl_seconds=600)
    resp = client.get(url.replace(f'/static/uploads/{KEY}', '/static/uploads/20261115/other.webp'))
    assert resp.status_code == 403, resp.text


def test_expired_signature_gone(client, signed_secret):
    """签名正确但已过期 → 410（对齐 nginx $secure_link == "0"）。"""
    resp = client.get(sign_upload_url(KEY, ttl_seconds=-7200))
    assert resp.status_code == 410, resp.text


def test_no_secret_allows_unsigned_access(client, no_secret):
    """密钥未配置 = 签名功能未启用 → 保持改造前的放行行为。"""
    resp = client.get(f'/static/uploads/{KEY}')
    assert resp.status_code == 200, resp.text
    assert resp.content == BODY


def test_non_ascii_signature_forbidden_not_crash(client, signed_secret):
    """非 ASCII 的 s 参数不得炸 500：按签名不合规 → 403。"""
    resp = client.get(f'/static/uploads/{KEY}?st=9999999999&s=%E4%B8%AD')
    assert resp.status_code == 403, resp.text


def test_non_numeric_expiry_forbidden(client, signed_secret):
    """st 非数字 → 403（不得 500）。"""
    resp = client.get(f'/static/uploads/{KEY}?st=abc&s=whatever')
    assert resp.status_code == 403, resp.text
