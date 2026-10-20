"""ITER-1 T3：chunked-v1 分块加密格式 + 旧格式兼容读。

覆盖三类断言：
1. **正确性** —— 各种边界（空/单块/整倍数/多块）往返一致。
2. **完整性** —— 截断、块重排、头部篡改、尾部追加都必须**报错**而非静默产出错数据。
   这一组是本格式存在的理由：流式写入最危险的失败模式是「写了一半但没人发现」。
3. **兼容** —— 历史上两种 legacy 信封（A 裸信封 / B meta 前缀）必须仍可解密。
"""
from __future__ import annotations

import io
import json
import os
import struct

import pytest

from fastapi_app.core import backup_encryption as be
from fastapi_app.core.atomic_write import TMP_SUFFIX, atomic_output

PW = 'correct horse battery staple'
CHUNK = 4096


# ---------------------------------------------------------------------------
# 测试夹具
# ---------------------------------------------------------------------------

def _payload(size: int) -> bytes:
    """构造 size 字节的伪 ZIP 载荷（不可压缩、可校验）。"""
    return b'PK\x03\x04' + os.urandom(max(0, size - 4))


def _encrypt(data: bytes, password: str = PW, chunk_size: int = CHUNK) -> bytes:
    buf = io.BytesIO()
    be.encrypt_stream(io.BytesIO(data), buf, password, total_size=len(data), chunk_size=chunk_size)
    return buf.getvalue()


def _decrypt(blob: bytes, password: str = PW) -> bytes:
    out = io.BytesIO()
    be.decrypt_stream(io.BytesIO(blob), out, password)
    return out.getvalue()


class TestRoundTrip:
    """正确性：格式自身与边界。"""

    @pytest.mark.parametrize(
        'size',
        [0, 1, 4, CHUNK - 1, CHUNK, CHUNK + 1, CHUNK * 3, CHUNK * 3 + 7],
        ids=['empty', 'one_byte', 'tiny', 'just_under', 'exactly_one', 'just_over',
             'three_chunks', 'ragged_tail'],
    )
    def test_roundtrip_various_sizes(self, size):
        data = _payload(size)
        blob = _encrypt(data)
        assert _decrypt(blob) == data, f'{size} 字节往返不一致'

    def test_header_layout_and_magic(self):
        blob = _encrypt(_payload(CHUNK * 2))
        assert blob[:8] == b'BFBKENC1'
        assert len(blob) > be._CHUNKED_HEADER_LEN
        version = blob[8]
        chunk_size, = struct.unpack('>I', blob[9:13])
        chunk_count, = struct.unpack('>Q', blob[29:37])
        assert version == 1
        assert chunk_size == CHUNK
        assert chunk_count == 2

    def test_ciphertext_does_not_leak_plaintext(self):
        secret = b'SUPER-SECRET-MARKER-' * 4  # secret-scan:allow — 脱敏测试夹具，非真实凭据
        blob = _encrypt(_payload(CHUNK) + secret)
        assert b'SUPER-SECRET-MARKER' not in blob

    def test_sha256_returned_and_stable(self):
        data = _payload(CHUNK * 2 + 11)
        buf = io.BytesIO()
        info = be.encrypt_stream(io.BytesIO(data), buf, PW, total_size=len(data), chunk_size=CHUNK)
        out = io.BytesIO()
        rinfo = be.decrypt_stream(io.BytesIO(buf.getvalue()), out, PW)
        assert info['plaintext_sha256'] == rinfo['plaintext_sha256']
        assert info['plaintext_size'] == rinfo['plaintext_size'] == len(data)
        assert info['encryption_mode'] == rinfo['encryption_mode'] == 'chunked-v1'

    def test_same_plaintext_encrypts_differently(self):
        """每次都有新 salt/nonce —— 相同明文不得产出相同密文。"""
        data = _payload(CHUNK)
        assert _encrypt(data) != _encrypt(data)

    def test_password_as_bytearray(self):
        data = _payload(CHUNK)
        buf = io.BytesIO()
        be.encrypt_stream(io.BytesIO(data), buf, bytearray(PW.encode()), total_size=len(data))
        assert _decrypt(buf.getvalue()) == data


class TestIntegrity:
    """完整性：所有「静默损坏」路径都必须变成显式报错。"""

    def test_truncated_tail_detected(self):
        blob = _encrypt(_payload(CHUNK * 3))
        with pytest.raises(be.BackupFileError) as ei:
            _decrypt(blob[:-10])
        assert ei.value.code in ('BACKUP_DECRYPT_TRUNCATED', 'BACKUP_DECRYPT_AUTH')

    def test_truncated_to_header_only_detected(self):
        blob = _encrypt(_payload(CHUNK * 2))
        with pytest.raises(be.BackupFileError) as ei:
            _decrypt(blob[:be._CHUNKED_HEADER_LEN])
        assert ei.value.code == 'BACKUP_DECRYPT_TRUNCATED'

    def test_chunk_reorder_detected(self):
        """交换两块 —— 块序号已进 AAD，必须报错而不是产出错序明文。"""
        data = _payload(CHUNK * 2)
        blob = _encrypt(data)
        head = blob[:be._CHUNKED_HEADER_LEN]
        # 逐块切分
        chunks, pos = [], len(head)
        while pos < len(blob):
            _, ct_len = struct.unpack('>12sI', blob[pos:pos + 16])
            chunks.append(blob[pos:pos + 16 + ct_len])
            pos += 16 + ct_len
        assert len(chunks) == 2
        with pytest.raises(be.BackupFileError) as ei:
            _decrypt(head + chunks[1] + chunks[0])
        assert ei.value.code == 'BACKUP_DECRYPT_AUTH'

    def test_chunk_duplication_detected(self):
        """复制第一块顶掉第二块 —— 同样必须报错。"""
        blob = _encrypt(_payload(CHUNK * 2))
        head, pos = blob[:be._CHUNKED_HEADER_LEN], be._CHUNKED_HEADER_LEN
        _, ct_len = struct.unpack('>12sI', blob[pos:pos + 16])
        first = blob[pos:pos + 16 + ct_len]
        with pytest.raises(be.BackupFileError):
            _decrypt(head + first + first)

    def test_header_chunk_count_tamper_detected(self):
        blob = bytearray(_encrypt(_payload(CHUNK * 2)))
        blob[29:37] = struct.pack('>Q', 1)          # 谎报只有 1 块
        with pytest.raises(be.BackupFileError):
            _decrypt(bytes(blob))

    def test_header_chunk_size_tamper_detected(self):
        blob = bytearray(_encrypt(_payload(CHUNK * 2)))
        blob[9:13] = struct.pack('>I', 1024)        # 谎报块大小
        with pytest.raises(be.BackupFileError):
            _decrypt(bytes(blob))

    def test_header_salt_tamper_detected(self):
        """改 salt 会让派生密钥变化 —— 由 header MAC 先拦下。"""
        blob = bytearray(_encrypt(_payload(CHUNK)))
        blob[13] ^= 0xFF
        with pytest.raises(be.BackupFileError) as ei:
            _decrypt(bytes(blob))
        assert ei.value.code == 'BACKUP_DECRYPT_AUTH'

    def test_trailing_garbage_detected(self):
        blob = _encrypt(_payload(CHUNK)) + b'extra-bytes'
        with pytest.raises(be.BackupFileError) as ei:
            _decrypt(blob)
        assert ei.value.code == 'BACKUP_DECRYPT_TRAILING'

    def test_wrong_password_fails_on_header_mac(self):
        """密码错误应在读第一块之前就被 header MAC 拦下（快速失败）。"""
        blob = _encrypt(_payload(CHUNK * 2))
        with pytest.raises(be.BackupFileError) as ei:
            _decrypt(blob, 'wrong-password')
        assert ei.value.code == 'BACKUP_DECRYPT_AUTH'

    def test_unsupported_version_rejected(self):
        blob = bytearray(_encrypt(_payload(CHUNK)))
        blob[8] = 99
        with pytest.raises(be.BackupFileError) as ei:
            _decrypt(bytes(blob))
        # 版本检查在 MAC 校验之前，因此是 FORMAT；两者都可接受，但必须是显式报错
        assert ei.value.code in ('BACKUP_DECRYPT_FORMAT', 'BACKUP_DECRYPT_AUTH')

    def test_non_chunked_input_rejected_by_decrypt_stream(self):
        """非 chunked 的垃圾数据走 legacy 分支 → 必须是显式报错，不能静默返回空。"""
        with pytest.raises(be.BackupFileError):
            _decrypt(os.urandom(200))


class TestLegacyCompatibility:
    """兼容：既有两个 legacy 信封都必须仍可解密。"""

    def test_format_a_raw_envelope(self):
        data = _payload(CHUNK)
        legacy, _ = be.encrypt_backup(data, PW)
        assert _decrypt(legacy) == data                 # 走 decrypt_stream 的 legacy 分支
        assert be.decrypt_backup(legacy, PW) == data

    def test_format_b_meta_prefixed(self):
        data = _payload(CHUNK)
        inner, meta = be.encrypt_backup(data, PW)
        meta_json = json.dumps({'encrypted': True, **meta}).encode('utf-8')
        prefixed = len(meta_json).to_bytes(4, 'big') + meta_json + inner
        assert _decrypt(prefixed) == data               # decrypt_stream 也要能剥前缀
        plain, got_meta = be.decrypt_backup_auto(prefixed, PW)
        assert plain == data
        assert got_meta is not None and got_meta.get('encrypted') is True

    def test_decrypt_backup_reads_both_generations(self):
        data = _payload(CHUNK * 2)
        legacy, _ = be.encrypt_backup(data, PW)
        chunked = _encrypt(data)
        assert be.decrypt_backup(legacy, PW) == data
        assert be.decrypt_backup(chunked, PW) == data

    def test_decrypt_backup_auto_legacy_has_no_meta(self):
        """保持既有契约：格式 A 裸信封的 auto 解密 meta 为 None。"""
        data = _payload(CHUNK)
        legacy, _ = be.encrypt_backup(data, PW)
        plain, meta = be.decrypt_backup_auto(legacy, PW)
        assert plain == data and meta is None

    def test_decrypt_backup_auto_chunked_reports_mode(self):
        data = _payload(CHUNK)
        plain, meta = be.decrypt_backup_auto(_encrypt(data), PW)
        assert plain == data
        assert meta is not None
        assert meta['encrypted'] is True
        assert meta['encryption_mode'] == 'chunked-v1'
        assert meta['chunk_count'] == 1

    def test_format_b_prefix_wrapping_chunked(self):
        """新组合：``_deps`` 会在 chunked 密文外再包 meta 前缀。

        这条组合此前不存在，必须锁定 —— 两处读侧都是「先剥前缀，再交给
        decrypt_backup」，而 decrypt_backup 现已能识别 chunked。
        """
        data = _payload(CHUNK * 2)
        inner, meta = be.encrypt_backup_chunked(data, PW)
        meta_json = json.dumps(meta, ensure_ascii=False).encode('utf-8')
        prefixed = len(meta_json).to_bytes(4, 'big') + meta_json + inner

        assert _decrypt(prefixed) == data                  # decrypt_stream 剥前缀
        assert be.decrypt_backup(prefixed[4 + len(meta_json):], PW) == data  # _deps 的读法
        plain, got_meta = be.decrypt_backup_auto(prefixed, PW)
        assert plain == data and got_meta.get('encryption_mode') == 'chunked-v1'

    def test_detect_encryption_format(self):
        assert be.detect_encryption_format(b'BFBKENC1' + b'\x00' * 20) == 'chunked-v1'
        assert be.detect_encryption_format(b'PK\x03\x04rest') == 'plaintext'
        assert be.detect_encryption_format(os.urandom(32)) == 'legacy'
        assert be.detect_encryption_format(b'') == 'legacy'


class TestParameterGuards:
    """参数守卫：错误用法要立刻报错，不进主流程。"""

    def test_chunk_size_out_of_range(self):
        for bad in (0, -1, be._MAX_CHUNK_SIZE + 1):
            with pytest.raises(ValueError, match='chunk_size'):
                be.encrypt_stream(io.BytesIO(b'x'), io.BytesIO(), PW, total_size=1, chunk_size=bad)

    def test_stream_source_requires_total_size(self):
        with pytest.raises(ValueError, match='total_size'):
            be.encrypt_stream(io.BytesIO(b'x'), io.BytesIO(), PW)

    def test_negative_total_size(self):
        with pytest.raises(ValueError, match='total_size'):
            be.encrypt_stream(io.BytesIO(), io.BytesIO(), PW, total_size=-1)

    def test_declared_size_mismatch_detected(self):
        """声明的 total_size 小于实际可读字节 → 块数对不上，必须报错。

        场景：备份过程中源文件被并发改写。若不校验，会产出一个
        「块数正确但内容被截断」的密文，恢复时才发现 —— 那时已经晚了。
        """
        data = _payload(CHUNK * 2)
        with pytest.raises(be.BackupFileError) as ei:
            be.encrypt_stream(
                io.BytesIO(data), io.BytesIO(), PW,
                total_size=len(data) - CHUNK, chunk_size=CHUNK,
            )
        assert ei.value.code == 'BACKUP_ENCRYPT_SIZE_MISMATCH'

    def test_declared_size_larger_than_source_detected(self):
        """声明的比实际多 → 同样必须报错（否则会少写块）。"""
        data = _payload(CHUNK)
        with pytest.raises(be.BackupFileError) as ei:
            be.encrypt_stream(
                io.BytesIO(data), io.BytesIO(), PW,
                total_size=len(data) + CHUNK, chunk_size=CHUNK,
            )
        assert ei.value.code == 'BACKUP_ENCRYPT_SIZE_MISMATCH'


class TestFileLevelAndAtomicity:
    """文件级 API 与原子落盘。"""

    def test_file_roundtrip(self, tmp_path):
        data = _payload(CHUNK * 5 + 3)
        src = tmp_path / 'src.bin'
        src.write_bytes(data)
        info = be.encrypt_backup_to_file(src, tmp_path / 'dst.enc', PW, chunk_size=CHUNK)
        assert info['chunk_count'] == 6

        rinfo = be.decrypt_backup_to_file(tmp_path / 'dst.enc', tmp_path / 'back.bin', PW)
        assert rinfo['plaintext_sha256'] == info['plaintext_sha256']
        assert (tmp_path / 'back.bin').read_bytes() == data

    def test_encrypt_to_file_leaves_no_tmp(self, tmp_path):
        src = tmp_path / 'src.bin'
        src.write_bytes(_payload(1024))
        dst = tmp_path / 'dst.enc'
        be.encrypt_backup_to_file(src, dst, PW)
        assert dst.exists()
        assert not (tmp_path / ('dst.enc' + TMP_SUFFIX)).exists()

    def test_failed_decrypt_leaves_no_partial_target(self, tmp_path):
        """解密失败时目标路径不得出现半成品 —— 否则恢复流程会拿到损坏文件。"""
        blob = bytearray(_encrypt(_payload(CHUNK * 2)))
        blob[29:37] = struct.pack('>Q', 9)              # 谎报 9 块 → 中途失败
        src = tmp_path / 'bad.enc'
        src.write_bytes(bytes(blob))
        dst = tmp_path / 'out.bin'
        with pytest.raises(be.BackupFileError):
            be.decrypt_backup_to_file(src, dst, PW)
        assert not dst.exists()
        assert not (tmp_path / ('out.bin' + TMP_SUFFIX)).exists()

    def test_atomic_output_writes_and_replaces(self, tmp_path):
        target = tmp_path / 'a.txt'
        target.write_bytes(b'OLD')
        with atomic_output(target) as fh:
            fh.write(b'NEW-CONTENT')
        assert target.read_bytes() == b'NEW-CONTENT'
        assert not (tmp_path / ('a.txt' + TMP_SUFFIX)).exists()

    def test_atomic_output_discards_on_error(self, tmp_path):
        target = tmp_path / 'a.txt'
        target.write_bytes(b'ORIGINAL')
        with pytest.raises(RuntimeError):
            with atomic_output(target) as fh:
                fh.write(b'PARTIAL')
                raise RuntimeError('boom')
        assert target.read_bytes() == b'ORIGINAL'        # 原文件未被触碰
        assert not (tmp_path / ('a.txt' + TMP_SUFFIX)).exists()

    def test_atomic_output_creates_parent_dirs(self, tmp_path):
        target = tmp_path / 'deep' / 'nested' / 'a.bin'
        with atomic_output(target) as fh:
            fh.write(b'x')
        assert target.read_bytes() == b'x'


class TestMemoryBounded:
    """流式诉求的硬断言：内存峰值必须与明文体积**解耦**。"""

    def test_peak_memory_much_smaller_than_plaintext(self, tmp_path):
        import tracemalloc

        plaintext_mb = 24
        chunk_mb = 1
        src = tmp_path / 'big.bin'
        with open(src, 'wb') as fh:
            written = 0
            while written < plaintext_mb * 1024 * 1024:
                fh.write(os.urandom(256 * 1024))
                written += 256 * 1024
        dst = tmp_path / 'big.enc'

        tracemalloc.start()
        info = be.encrypt_backup_to_file(src, dst, PW, chunk_size=chunk_mb * 1024 * 1024)
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        plaintext_bytes = plaintext_mb * 1024 * 1024
        assert info['plaintext_size'] >= plaintext_bytes
        # chunked 格式的峰值应与「块大小」同阶，而非与明文体积同阶。
        # 留 4 倍块大小的余量给 Python 对象与缓冲；关键是远小于明文体积。
        assert peak < chunk_mb * 1024 * 1024 * 4, (
            f'加密 {plaintext_mb} MB 时峰值 {peak / 1024 / 1024:.1f} MB —— 未做到流式'
        )

        # 解密的对称断言
        out = tmp_path / 'big.out'
        tracemalloc.start()
        be.decrypt_backup_to_file(dst, out, PW)
        _, dpeak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        assert out.stat().st_size == info['plaintext_size']
        assert dpeak < chunk_mb * 1024 * 1024 * 4, (
            f'解密 {plaintext_mb} MB 时峰值 {dpeak / 1024 / 1024:.1f} MB —— 未做到流式'
        )


class TestFormatSwitch:
    """开关语义：新写入格式由 BACKUP_ENCRYPTION_CHUNKED 决定，可一键回退。"""

    def test_default_is_chunked(self, monkeypatch):
        monkeypatch.delenv(be._CHUNKED_ENV_KEY, raising=False)
        assert be.chunked_encryption_enabled() is True
        data = _payload(CHUNK)
        blob, meta = be.encrypt_backup_auto(data, PW)
        assert blob[:8] == b'BFBKENC1'
        assert meta['encryption_mode'] == 'chunked-v1'
        assert be.decrypt_backup(blob, PW) == data

    def test_flag_off_falls_back_to_legacy(self, monkeypatch):
        monkeypatch.setenv(be._CHUNKED_ENV_KEY, 'false')
        assert be.chunked_encryption_enabled() is False
        data = _payload(CHUNK)
        blob, meta = be.encrypt_backup_auto(data, PW)
        assert blob[:8] != b'BFBKENC1'
        assert meta.get('encryption_mode') is None       # legacy meta 无该字段
        assert be.decrypt_backup(blob, PW) == data       # 回退后仍可解

    @pytest.mark.parametrize('raw,expected', [
        ('true', True), ('TRUE', True), ('1', True), ('yes', True), ('on', True),
        ('false', False), ('0', False), ('no', False), ('off', False), ('', False),
    ])
    def test_flag_parsing(self, monkeypatch, raw, expected):
        monkeypatch.setenv(be._CHUNKED_ENV_KEY, raw)
        assert be.chunked_encryption_enabled() is expected

    def test_both_generations_readable_after_switch(self, monkeypatch):
        """切换开关不应让任一代密文变成不可读。"""
        data = _payload(CHUNK * 2)
        monkeypatch.setenv(be._CHUNKED_ENV_KEY, 'false')
        old_blob, _ = be.encrypt_backup_auto(data, PW)
        monkeypatch.setenv(be._CHUNKED_ENV_KEY, 'true')
        new_blob, _ = be.encrypt_backup_auto(data, PW)
        assert be.decrypt_backup(old_blob, PW) == data
        assert be.decrypt_backup(new_blob, PW) == data
