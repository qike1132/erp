"""备份文件加密：AES-256-GCM + PBKDF2 密钥派生。

本模块同时承载**两代**落盘格式，读写策略为「新写用 chunked-v1，旧文件照旧可读」：

- ``chunked-v1``（ITER-1 T3 起为新建备份的默认格式）
  分块 AEAD，内存占用与备份体积**解耦**，可流式加密/解密。
- ``legacy``（格式 A 裸信封 / 格式 B meta 前缀信封）
  P0-1 之前的写法，一次性吃下整个 bytes。**只读**保留，不再新写。

读侧（:func:`decrypt_backup` / :func:`decrypt_backup_auto` / :func:`decrypt_stream`）
自动识别三种格式，调用方无需关心文件是哪一代产出的。
"""

import hashlib
import hmac
import io
import json
import os
import struct
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .atomic_write import atomic_output


class BackupFileError(Exception):
    """Raised when backup file operations fail (e.g. wrong password, corrupt data)."""

    def __init__(self, message: str, code: str = "BACKUP_FILE_ERROR"):
        self.message = message
        self.code = code
        super().__init__(message)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_SALT_LEN = 16          # 128-bit salt
_NONCE_LEN = 12         # 96-bit nonce (recommended for GCM)
_TAG_LEN = 16           # 128-bit authentication tag
_KDF_ITERATIONS = 600_000
_KEY_LEN = 32           # 256-bit key


def _derive_key(password: bytearray, salt: bytes) -> bytearray:
    """Derive a 256-bit key from *password* and *salt* using PBKDF2-HMAC-SHA256.

    Returns a ``bytearray`` so the caller can zero it out after use.
    """
    dk = hashlib.pbkdf2_hmac("sha256", bytes(password), salt, _KDF_ITERATIONS, dklen=_KEY_LEN)
    return bytearray(dk)


def _zero(ba: bytearray) -> None:
    """Overwrite a bytearray with zeros to reduce the window where secrets
    reside in memory."""
    for i in range(len(ba)):
        ba[i] = 0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def encrypt_backup(
    zip_bytes: bytes,
    password: str | bytearray,
) -> tuple[bytes, dict]:
    """Encrypt *zip_bytes* with AES-256-GCM.

    Returns ``(encrypted_bytes, meta_dict)``.

    File layout::

        salt  (16 B) | nonce (12 B) | ciphertext (variable) | auth_tag (16 B)

    The auth tag is appended by ``AESGCM.encrypt`` as the last 16 bytes of
    the ciphertext output.
    """
    # --- normalise password to bytearray so we can zero it later -----------
    pw_bytes = bytearray(password if isinstance(password, bytearray) else password.encode("utf-8"))

    salt = os.urandom(_SALT_LEN)
    nonce = os.urandom(_NONCE_LEN)

    key = _derive_key(pw_bytes, salt)
    _zero(pw_bytes)  # clear password from memory ASAP

    aesgcm = AESGCM(bytes(key))
    _zero(key)  # clear derived key — AESGCM keeps its own internal copy

    # AESGCM.encrypt returns ciphertext || auth_tag (16 bytes at the end)
    ct_with_tag = aesgcm.encrypt(nonce, zip_bytes, None)

    encrypted_bytes = salt + nonce + ct_with_tag

    backup_id = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    meta_dict = {
        "backup_id": backup_id,
        "created_at": datetime.now(UTC).isoformat(),
        "type": "encrypted",
        "encrypted": True,
        "algorithm": "AES-256-GCM",
        "kdf": {
            "name": "PBKDF2-HMAC-SHA256",
            "iterations": _KDF_ITERATIONS,
            "salt_len": _SALT_LEN,
        },
    }

    return encrypted_bytes, meta_dict


def decrypt_backup(
    encrypted_bytes: bytes,
    password: str | bytearray,
) -> bytes:
    """解密一份备份密文，**自动识别** ``chunked-v1`` 与 ``legacy`` 格式。

    这是加密数据的唯一读取入口：所有既有调用方（orchestrator / format_strategy /
    adapters / _deps / recovery_test_service）无需改动即可读出新一代格式。

    Raises:
        BackupFileError: 密码错误、数据被截断/篡改，或格式无法识别。
    """
    if encrypted_bytes[:len(_CHUNKED_MAGIC)] == _CHUNKED_MAGIC:
        return _decrypt_chunked_bytes_with_info(encrypted_bytes, password)[0]
    return _decrypt_legacy_envelope(encrypted_bytes, password)


def _decrypt_legacy_envelope(
    encrypted_bytes: bytes,
    password: str | bytearray,
) -> bytes:
    """解密 legacy 格式 A（裸信封）。

    Raises :class:`BackupFileError` if the password is wrong or the data is
    corrupt (authentication tag verification failure).
    """
    min_len = _SALT_LEN + _NONCE_LEN + _TAG_LEN
    if len(encrypted_bytes) < min_len:
        raise BackupFileError(
            f"Encrypted data too short ({len(encrypted_bytes)} B, minimum {min_len} B)",
            code="BACKUP_DECRYPT_SHORT",
        )

    salt = encrypted_bytes[:_SALT_LEN]
    nonce = encrypted_bytes[_SALT_LEN : _SALT_LEN + _NONCE_LEN]
    ct_with_tag = encrypted_bytes[_SALT_LEN + _NONCE_LEN :]

    pw_bytes = bytearray(password if isinstance(password, bytearray) else password.encode("utf-8"))

    key = _derive_key(pw_bytes, salt)
    _zero(pw_bytes)

    aesgcm = AESGCM(bytes(key))
    _zero(key)

    try:
        plaintext = aesgcm.decrypt(nonce, ct_with_tag, None)
    except (InvalidTag, ValueError) as exc:
        raise BackupFileError(
            "Decryption failed — incorrect password or corrupt data",
            code="BACKUP_DECRYPT_AUTH",
        ) from exc

    return plaintext


# ---------------------------------------------------------------------------
# chunked-v1：分块 AEAD 流式格式（ITER-1 T3）
# ---------------------------------------------------------------------------
# 落盘布局::
#
#     header（定长 69 B）
#       magic          8 B   b'BFBKENC1'
#       version        1 B   0x01
#       chunk_size     4 B   big-endian
#       salt          16 B   PBKDF2 salt
#       chunk_count    8 B   big-endian（0 = 空明文）
#       header_mac    32 B   HMAC-SHA256(mac_key, 前 37 B)
#     chunk[i]，i ∈ [0, chunk_count)
#       nonce         12 B
#       ct_len         4 B   big-endian，含尾部 16 B GCM tag
#       ciphertext   ct_len B
#
# 设计要点：
#
# 1. **每块独立随机 nonce**。GCM 下 nonce 复用是致命的（可恢复认证密钥）；
#    96-bit 随机 nonce 在同一密钥下碰撞概率可忽略，且每块还用块序号做 AAD。
# 2. **块序号进 AAD** → 重排、删除、插入中间块都会让该块校验失败，
#    不会静默产出顺序错误的明文。
# 3. **header_mac** 让「改块大小 / 改块数 / 改 salt」同样被检出，
#    并顺带提供「密码错误」的快速判定（不必解开第一块才发现密码不对）。
# 4. **chunk_count 显式记录** → 尾部截断必然被检出（块数对不上），
#    这是流式写入最危险的失败模式（见 ITER-1 T9）。
#
# ⚠️ 本格式密文**旧版本代码读不了**。需要回退时设
#    ``BACKUP_ENCRYPTION_CHUNKED=false`` 并重启，无需回滚代码。

_CHUNKED_MAGIC = b'BFBKENC1'
_CHUNKED_FORMAT_VERSION = 1
_CHUNKED_HDR_FIXED = 8 + 1 + 4 + _SALT_LEN + 8                 # 37
_CHUNKED_HMAC_LEN = 32
_CHUNKED_HEADER_LEN = _CHUNKED_HDR_FIXED + _CHUNKED_HMAC_LEN   # 69
_CHUNKED_HDR_STRUCT = '>8sBI16sQ'
_CHUNKED_CHUNK_HDR_LEN = _NONCE_LEN + 4                        # 16
_CHUNKED_CHUNK_HDR_STRUCT = '>12sI'
_DEFAULT_CHUNK_SIZE = 4 * 1024 * 1024
_MAX_CHUNK_SIZE = 64 * 1024 * 1024
_CHUNKED_KDF_DKLEN = _KEY_LEN * 2                              # 64 = enc(32) + mac(32)

#: 旧版本代码无法解新版密文 —— 该开关是回退的唯一开关（不需回滚代码）。
_CHUNKED_ENV_KEY = 'BACKUP_ENCRYPTION_CHUNKED'


def chunked_encryption_enabled() -> bool:
    """新写入是否使用 chunked-v1 格式（默认 ``True``）。

    直接读环境变量而非从 ``services.backup._constants`` 取：
    ``services/backup/orchestration/core.py`` 依赖本模块，
    反向 import 会形成真实循环导入。每次调用都现读，便于测试与热切换。
    """
    return os.environ.get(_CHUNKED_ENV_KEY, 'true').strip().lower() in ('1', 'true', 'yes', 'on')


def detect_encryption_format(head: bytes) -> str:
    """按文件头判断落盘格式：``'chunked-v1'`` | ``'plaintext'`` | ``'legacy'``。

    只读前 8 字节，供巡检/列表接口零开销识别，不必解密。
    """
    if head[:len(_CHUNKED_MAGIC)] == _CHUNKED_MAGIC:
        return 'chunked-v1'
    if head[:2] == b'PK':
        return 'plaintext'
    return 'legacy'


def _derive_keys(password: bytearray, salt: bytes) -> tuple[bytearray, bytearray]:
    """PBKDF2 一次性派生出「加密密钥」与「头部 MAC 密钥」两把 256-bit 密钥。"""
    dk = hashlib.pbkdf2_hmac(
        'sha256', bytes(password), salt, _KDF_ITERATIONS, dklen=_CHUNKED_KDF_DKLEN
    )
    return bytearray(dk[:_KEY_LEN]), bytearray(dk[_KEY_LEN:])


def _chunk_aad(header_fixed: bytes, index: int) -> bytes:
    """块附加认证数据 = 头部前 37 B + 块序号（8 B 大端）。"""
    return header_fixed + index.to_bytes(8, 'big')


def _read_exact(fh, size: int) -> bytes:
    """从 ``fh`` 读满 ``size`` 字节；提前 EOF 即视为截断。"""
    buf = fh.read(size)
    if len(buf) != size:
        raise BackupFileError(
            f'密文提前结束：期望再读 {size} 字节，实得 {len(buf)} 字节（文件被截断？）',
            code='BACKUP_DECRYPT_TRUNCATED',
        )
    return buf


@contextmanager
def _as_reader(src):
    """把「路径或可读流」统一成可读流上下文。"""
    if isinstance(src, (str, Path)):
        with open(src, 'rb') as fh:
            yield fh
    else:
        yield src


@contextmanager
def _as_writer(dst):
    """把「路径或可写流」统一成可写流上下文；路径走原子落盘。"""
    if isinstance(dst, (str, Path)):
        with atomic_output(Path(dst)) as fh:
            yield fh
    else:
        yield dst


def encrypt_stream(
    src,
    dst,
    password: str | bytearray,
    *,
    total_size: int | None = None,
    chunk_size: int = _DEFAULT_CHUNK_SIZE,
) -> dict:
    """分块加密 ``src`` 并把密文流式写入 ``dst``，返回结构信息 dict。

    内存占用与块大小同阶（≈ ``chunk_size``），与备份体积**无关**。

    Args:
        src: 源；``Path``/``str`` 或可读二进制流。
        dst: 目标；``Path``/``str``（走原子落盘）或可写二进制流。
        total_size: 明文总字节数。``src`` 为路径时可省略（由 ``stat`` 得出）；
            为流对象时**必须显式给出** —— 块数要写进文件头，无法边读边猜。
        chunk_size: 每块明文大小，默认 4 MiB，上限 64 MiB。

    Raises:
        ValueError: 参数非法（``chunk_size`` 越界 / 流式源未给 ``total_size``）。
        BackupFileError: 实际读到的字节数与声明的 ``total_size`` 不符
            （源文件被并发修改，继续下去会产出一个块数错乱的密文）。
    """
    if not 1 <= chunk_size <= _MAX_CHUNK_SIZE:
        raise ValueError(f'chunk_size 必须落在 [1, {_MAX_CHUNK_SIZE}]，收到 {chunk_size}')

    if total_size is None:
        if not isinstance(src, (str, Path)):
            raise ValueError('src 为流对象时必须显式给出 total_size（块数需写入文件头）')
        total_size = Path(src).stat().st_size
    if total_size < 0:
        raise ValueError(f'total_size 不能为负：{total_size}')

    chunk_count = (total_size + chunk_size - 1) // chunk_size

    pw_bytes = bytearray(password if isinstance(password, bytearray) else password.encode('utf-8'))
    salt = os.urandom(_SALT_LEN)
    enc_key, mac_key = _derive_keys(pw_bytes, salt)
    _zero(pw_bytes)

    header_fixed = struct.pack(
        _CHUNKED_HDR_STRUCT, _CHUNKED_MAGIC, _CHUNKED_FORMAT_VERSION, chunk_size, salt, chunk_count
    )
    header = header_fixed + hmac.new(bytes(mac_key), header_fixed, hashlib.sha256).digest()
    _zero(mac_key)

    aesgcm = AESGCM(bytes(enc_key))
    _zero(enc_key)

    digits = hashlib.sha256()
    written = 0
    idx = 0
    with _as_reader(src) as fin, _as_writer(dst) as fout:
        fout.write(header)
        while True:
            block = fin.read(chunk_size)
            if not block:
                break
            nonce = os.urandom(_NONCE_LEN)
            ciphertext = aesgcm.encrypt(nonce, block, _chunk_aad(header_fixed, idx))
            fout.write(struct.pack(_CHUNKED_CHUNK_HDR_STRUCT, nonce, len(ciphertext)))
            fout.write(ciphertext)
            digits.update(block)
            written += len(block)
            idx += 1

        # Z07-R1：完整性校验必须在 atomic_output 的 with 块内完成——放在块外时
        # os.replace 已把坏密文落到正式文件名，抛异常也收不回上一个好备份。
        if idx != chunk_count or written != total_size:
            raise BackupFileError(
                f'加密时明文长度与声明不符（声明 {total_size} B，实读 {written} B，'
                f'块数 {idx}/{chunk_count}）——源文件被并发改动？',
                code='BACKUP_ENCRYPT_SIZE_MISMATCH',
            )

    return {
        'encryption_mode': 'chunked-v1',
        'format_version': _CHUNKED_FORMAT_VERSION,
        'algorithm': 'AES-256-GCM',
        'chunk_size': chunk_size,
        'chunk_count': chunk_count,
        'plaintext_size': written,
        'plaintext_sha256': digits.hexdigest(),
        'kdf': {'name': 'PBKDF2-HMAC-SHA256', 'iterations': _KDF_ITERATIONS, 'salt_len': _SALT_LEN},
    }


def decrypt_stream(src, dst, password: str | bytearray) -> dict:
    """解密 ``src`` 到 ``dst``，**自动识别** chunked-v1 与 legacy 两种落盘格式。

    chunked-v1 直写文件走真流式（内存与块大小同阶）。以下两种情况会整包读入：
    文件以 4 B meta 长度前缀开头（历史「格式 B」），或本身是 legacy 信封 ——
    这两种历史形态必须先剥前缀才知道内层是什么，无法在不解包的前提下流式处理。

    ⚠️ 因此「格式 B 前缀 + chunked 内层」这一组合虽然能正确解密，但享受不到
    流式收益。要彻底去掉这层前缀，属于 ITER-1 阶段 B（切换 ``_deps`` /
    ``format_strategy`` 的调用方）的工作。
    """
    with _as_reader(src) as fin, _as_writer(dst) as fout:
        first = fin.read(len(_CHUNKED_MAGIC))
        if first == _CHUNKED_MAGIC:
            header = first + _read_exact(fin, _CHUNKED_HEADER_LEN - len(_CHUNKED_MAGIC))
            return _decrypt_chunked_into(header, fin, fout, password)
        # 非 chunked 直写：可能是 legacy 信封，也可能是「格式 B 前缀 + chunked 内层」。
        # 统一交给 decrypt_backup 调度，避免在这里重复一套格式判断。
        plaintext = decrypt_backup(_strip_meta_prefix(first + fin.read()), password)
        fout.write(plaintext)
        return {'encryption_mode': 'legacy', 'plaintext_size': len(plaintext)}


def _decrypt_chunked_into(header: bytes, fin, fout, password: str | bytearray) -> dict:
    """校验 chunked-v1 文件头并逐块解密，返回结构信息 dict。"""
    magic, version, chunk_size, salt, chunk_count = struct.unpack(
        _CHUNKED_HDR_STRUCT, header[:_CHUNKED_HDR_FIXED]
    )
    if magic != _CHUNKED_MAGIC:
        raise BackupFileError('不是 chunked-v1 密文', code='BACKUP_DECRYPT_FORMAT')
    if version != _CHUNKED_FORMAT_VERSION:
        raise BackupFileError(
            f'不支持的备份加密格式版本：{version}（本代码支持 {_CHUNKED_FORMAT_VERSION}）',
            code='BACKUP_DECRYPT_FORMAT',
        )
    if not 1 <= chunk_size <= _MAX_CHUNK_SIZE:
        raise BackupFileError(f'文件头 chunk_size 非法：{chunk_size}', code='BACKUP_DECRYPT_FORMAT')

    pw_bytes = bytearray(password if isinstance(password, bytearray) else password.encode('utf-8'))
    enc_key, mac_key = _derive_keys(pw_bytes, salt)
    _zero(pw_bytes)

    header_fixed = header[:_CHUNKED_HDR_FIXED]
    expected_mac = hmac.new(bytes(mac_key), header_fixed, hashlib.sha256).digest()
    _zero(mac_key)
    if not hmac.compare_digest(expected_mac, header[_CHUNKED_HDR_FIXED:_CHUNKED_HEADER_LEN]):
        raise BackupFileError(
            '密码错误，或文件头被篡改（header MAC 校验失败）',
            code='BACKUP_DECRYPT_AUTH',
        )

    aesgcm = AESGCM(bytes(enc_key))
    _zero(enc_key)

    digits = hashlib.sha256()
    written = 0
    for idx in range(chunk_count):
        nonce, ct_len = struct.unpack(
            _CHUNKED_CHUNK_HDR_STRUCT, _read_exact(fin, _CHUNKED_CHUNK_HDR_LEN)
        )
        if ct_len < _TAG_LEN:
            raise BackupFileError(
                f'第 {idx} 块长度非法：{ct_len}（至少应含 {_TAG_LEN} B 认证标签）',
                code='BACKUP_DECRYPT_FORMAT',
            )
        try:
            block = aesgcm.decrypt(
                nonce, _read_exact(fin, ct_len), _chunk_aad(header_fixed, idx)
            )
        except (InvalidTag, ValueError) as exc:
            raise BackupFileError(
                f'第 {idx + 1}/{chunk_count} 块解密失败 —— 密码错误、密文被篡改或块顺序被改动',
                code='BACKUP_DECRYPT_AUTH',
            ) from exc
        fout.write(block)
        digits.update(block)
        written += len(block)

    if fin.read(1):
        raise BackupFileError(
            '密文在声明的块数之后仍有残留数据（文件被追加，或块数被改写）',
            code='BACKUP_DECRYPT_TRAILING',
        )

    return {
        'encryption_mode': 'chunked-v1',
        'format_version': version,
        'algorithm': 'AES-256-GCM',
        'chunk_size': chunk_size,
        'chunk_count': chunk_count,
        'plaintext_size': written,
        'plaintext_sha256': digits.hexdigest(),
    }


def _decrypt_chunked_bytes_with_info(data: bytes, password: str | bytearray) -> tuple[bytes, dict]:
    """内存版分块解密，返回 ``(plaintext, info)``。"""
    out = io.BytesIO()
    info = decrypt_stream(io.BytesIO(data), out, password)
    return out.getvalue(), info


def _chunked_meta(info: dict) -> dict:
    """把 :func:`encrypt_stream` / :func:`decrypt_stream` 的结构信息整理成 meta。"""
    return {
        'backup_id': datetime.now(UTC).strftime('%Y%m%d%H%M%S'),
        'created_at': datetime.now(UTC).isoformat(),
        'type': 'encrypted',
        'encrypted': True,
        'encryption_mode': info.get('encryption_mode', 'chunked-v1'),
        'algorithm': info.get('algorithm', 'AES-256-GCM'),
        'chunk_size': info.get('chunk_size'),
        'chunk_count': info.get('chunk_count'),
        'kdf': info.get('kdf', {
            'name': 'PBKDF2-HMAC-SHA256', 'iterations': _KDF_ITERATIONS, 'salt_len': _SALT_LEN,
        }),
    }


def encrypt_backup_chunked(zip_bytes: bytes, password: str | bytearray) -> tuple[bytes, dict]:
    """分块加密（内存版），签名与 :func:`encrypt_backup` 一致，便于就地替换。

    ⚠️ 本函数为迁就调用方契约仍把明文整包持在内存里。
    真正「内存与体积解耦」要走 :func:`encrypt_backup_to_file` 的流式路径 ——
    这是 ITER-1 阶段 B 切换调用方的目标。
    """
    buf = io.BytesIO()
    info = encrypt_stream(io.BytesIO(zip_bytes), buf, password, total_size=len(zip_bytes))
    return buf.getvalue(), _chunked_meta(info)


def encrypt_backup_auto(zip_bytes: bytes, password: str | bytearray) -> tuple[bytes, dict]:
    """按配置选择加密格式 —— **所有新建备份的写入路径都应调用本函数**。

    :func:`chunked_encryption_enabled` 为真（默认）时产出 chunked-v1，
    否则回退 legacy 格式。回退只需改环境变量 + 重启，不必回滚代码。
    """
    if chunked_encryption_enabled():
        return encrypt_backup_chunked(zip_bytes, password)
    return encrypt_backup(zip_bytes, password)


def encrypt_backup_to_file(
    src_path: Path | str,
    dst_path: Path | str,
    password: str | bytearray,
    *,
    chunk_size: int = _DEFAULT_CHUNK_SIZE,
) -> dict:
    """把 ``src_path`` 分块加密后原子落盘到 ``dst_path``（内存有界）。

    落盘前先写 ``<dst>.tmp``，``fsync`` 后原子改名 —— 读侧永远看不到半成品。
    """
    return encrypt_stream(
        Path(src_path), Path(dst_path), password, chunk_size=chunk_size
    )


def decrypt_backup_to_file(
    src_path: Path | str,
    dst_path: Path | str,
    password: str | bytearray,
) -> dict:
    """解密 ``src_path`` 到 ``dst_path``（自动识别格式，原子落盘）。"""
    return decrypt_stream(Path(src_path), Path(dst_path), password)


# ---------------------------------------------------------------------------
# Dual-format support (P0-1)
# ---------------------------------------------------------------------------
# 历史上有两种加密落盘格式：
#   A. 裸信封  salt|nonce|ciphertext|tag          —— create_full_backup / incremental 内部加密
#   B. 前缀信封 4B-meta-len|JSON meta|裸信封       —— 旧 /save 端点 _encrypt_backup_data
# P0-1 起新备份统一为格式 A；还原需兼容两种历史文件。

def _strip_meta_prefix(encrypted_bytes: bytes) -> bytes:
    """若数据以 4 字节长度前缀 + JSON meta 开头（格式 B），剥离前缀返回裸信封。

    非前缀格式（格式 A）原样返回。解析失败视为格式 A，交给 decrypt_backup 报错。
    """
    try:
        if len(encrypted_bytes) < 4:
            return encrypted_bytes
        meta_len = int.from_bytes(encrypted_bytes[:4], "big")
        if meta_len <= 0 or len(encrypted_bytes) < 4 + meta_len:
            return encrypted_bytes
        meta = json.loads(encrypted_bytes[4 : 4 + meta_len].decode("utf-8"))
        if isinstance(meta, dict) and meta.get("encrypted") is True:
            return encrypted_bytes[4 + meta_len :]
    except (ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError):
        pass
    return encrypted_bytes


def decrypt_backup_auto(
    encrypted_bytes: bytes,
    password: str | bytearray,
) -> tuple[bytes, dict | None]:
    """自适应解密：自动识别 chunked-v1 / 格式 A（裸信封）/ 格式 B（meta 前缀）。

    Returns ``(plaintext, meta_dict_or_None)``。
    """
    if encrypted_bytes[:len(_CHUNKED_MAGIC)] == _CHUNKED_MAGIC:
        plaintext, info = _decrypt_chunked_bytes_with_info(encrypted_bytes, password)
        return plaintext, _chunked_meta(info)

    payload = _strip_meta_prefix(encrypted_bytes)
    plaintext = decrypt_backup(payload, password)
    meta = None
    if payload is not encrypted_bytes:
        try:
            meta_len = int.from_bytes(encrypted_bytes[:4], "big")
            meta = json.loads(encrypted_bytes[4 : 4 + meta_len].decode("utf-8"))
        except (ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError):
            meta = None
    return plaintext, meta


def create_meta_file(meta_dict: dict) -> bytes:
    """Serialise *meta_dict* as pretty-printed UTF-8 JSON bytes suitable for
    writing to a ``.meta`` sidecar file."""
    return json.dumps(meta_dict, indent=2, ensure_ascii=False).encode("utf-8")
