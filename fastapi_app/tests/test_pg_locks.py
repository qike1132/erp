"""core/pg_locks 的 advisory lock 键与 core/number_generator 逐位一致（搬家不改行为）。"""
import hashlib

from fastapi_app.core.pg_locks import number_lock_key


def test_number_lock_key_value_unchanged_from_legacy():
    # 与 core/number_generator._number_lock_key 的 md5 前 15 位十六进制方案逐位一致
    legacy = int(hashlib.md5(f"{'CASE_PRODUCT'}:{'42'}".encode(), usedforsecurity=False).hexdigest()[:15], 16)
    assert number_lock_key('CASE_PRODUCT', '42') == legacy


def test_number_lock_key_scope_sensitive():
    assert number_lock_key('A', '1') != number_lock_key('B', '1')


def test_number_lock_key_within_bigint():
    key = number_lock_key('PO', '20260929')
    assert 0 <= key < 2 ** 63
