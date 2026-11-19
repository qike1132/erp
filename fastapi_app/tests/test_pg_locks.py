"""core/pg_locks 的 advisory lock 键必须与历史实现**逐位一致**（搬家不改行为）。

2.4（2026-10-17 审计 P2）：原用例把期望值写成
``int(hashlib.md5(f"{scope}:{no}".encode())[:15], 16)`` —— 也就是用**与实现相同的公式**
现算出一个必然相等的数：实现整体换口径（md5→sha1、位数 15→16、拼接符改变）时用例照绿，
测到的只是「实现和它自己一致」。锁键的真实约束是「与线上可能仍持有的 advisory lock 同号」，
因此期望值必须是**字面量常数**：改动它 = 与未释放的锁脱钩。
"""
from fastapi_app.core.pg_locks import number_lock_key

#: 历史实现（旧 core/number_generator._number_lock_key）对 ('CASE_PRODUCT', '42') 的取值，
#: 2026-11-19 从当时的实现实跑固化。**不要改成现算**——固化正是这条用例的意义。
_LEGACY_CASE_PRODUCT_42 = 845771213813760814


def test_number_lock_key_value_unchanged_from_legacy():
    assert number_lock_key('CASE_PRODUCT', '42') == _LEGACY_CASE_PRODUCT_42, (
        '锁键变了：与线上仍可能未释放的 advisory lock 脱钩，会放行本应被互斥的并发编号'
    )


def test_number_lock_key_scope_sensitive():
    assert number_lock_key('A', '1') != number_lock_key('B', '1')


def test_number_lock_key_within_bigint():
    key = number_lock_key('PO', '20260929')
    assert 0 <= key < 2 ** 63
