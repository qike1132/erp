"""旧 bcrypt 哈希登录 的回归护栏（评审 2026-10-11）。

背景：``requirements/migration.txt:13`` 声明了 ``bcrypt==5.0.0``，但 venv 未安装。
``fastapi_app/core/security.py:_verify_bcrypt`` 在函数内 ``import bcrypt``，缺包时
``except ImportError → logger.warning + return False`` —— 于是**用旧 bcrypt 哈希的
用户登不进**（不崩、不绕过鉴权，是可用性缺陷）。本测试锁死「bcrypt 在位时能正确验哈希」。

无 bcrypt 的环境（如未装 migration.txt 的 CI）自动跳过，与 tests/test_new_libraries.py
对 rapidfuzz 的 skipif 降级同款。
"""
import pytest


def test_verify_bcrypt_accepts_valid_hash():
    bcrypt = pytest.importorskip("bcrypt", reason="未装 requirements/migration.txt")

    from fastapi_app.core.security import _verify_bcrypt

    h = bcrypt.hashpw(b"secret123", bcrypt.gensalt()).decode()
    assert _verify_bcrypt("secret123", h) is True, "bcrypt 在位时有效哈希应验过"
    assert _verify_bcrypt("wrong-password", h) is False, "错误口令不得通过"
