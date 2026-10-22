"""L9：JWT 签名密钥缓存必须有 TTL，轮换后无需全量重启。"""


def test_signing_key_cache_expires(monkeypatch, tmp_path):
    from fastapi_app.core.auth import token

    key_path = tmp_path / 'private.pem'
    key_path.write_text('KEY1', encoding='utf-8')
    monkeypatch.setattr(token.settings, 'ALGORITHM', 'RS256')
    monkeypatch.setattr(token.settings, 'JWT_PRIVATE_KEY_PATH', str(key_path))

    clock = {'t': 1000.0}
    monkeypatch.setattr(token.time, 'monotonic', lambda: clock['t'])
    monkeypatch.setattr(token, '_signing_key_cache', None)
    monkeypatch.setattr(token, '_signing_key_cache_at', 0.0)

    assert token._get_signing_key() == 'KEY1'

    key_path.write_text('KEY2', encoding='utf-8')
    clock['t'] += token._KEY_CACHE_TTL + 1
    assert token._get_signing_key() == 'KEY2'
