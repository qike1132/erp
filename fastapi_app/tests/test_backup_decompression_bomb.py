"""备份文件的大小上限：压缩炸弹与超大文件不得撑爆工作进程。

背景（/backup 审计，high）
-------------------------
两处「读了再说」的入口，输入上限形同虚设：

1. `_read_backup_file` 对 `.gz` 直接 `gzip.decompress(content)` —— 上传体积被
   `MAX_BACKUP_FILE_SIZE`(500MB) 卡住，但 gzip 压缩比可达 ~1000:1，500MB 密文
   能解出 500GB，`decompress` 一次性读进内存 ⇒ OOM 打挂进程。
2. `/backup/validate/{filename}` 既不限服务器文件大小，又对 ZIP 每个成员
   `f.read()` 全文解压 ⇒ 校验接口成了同一个炸弹的第二入口。

修法：解压改为**有上限的分块读**（`GzipFile.read(limit+1)`），超限即 400；
校验入口补上与还原链路一致的体积检查，成员改为分块读 + 总量上限。
"""
from __future__ import annotations

import ast
import gzip
from pathlib import Path

import pytest
from fastapi import HTTPException

from fastapi_app.api.v1.endpoints.backup import restore as restore_mod
from fastapi_app.api.v1.endpoints.backup.restore import (
    _decompress_gzip_bounded,
    _read_backup_file,
)

_RESTORE_PY = Path(restore_mod.__file__)
_VALIDATION_PY = _RESTORE_PY.parent / 'validation.py'


class _UploadFileStub:
    def __init__(self, filename: str, data: bytes) -> None:
        self.filename = filename
        self._data = data

    async def read(self) -> bytes:
        return self._data


# ---------------------------------------------------------------------------
# 有上限解压
# ---------------------------------------------------------------------------

def test_bomb_is_rejected() -> None:
    """高压缩比内容必须被上限拦下 —— 这正是 decompress 会 OOM 的输入。"""
    bomb = gzip.compress(b'\0' * (8 * 1024 * 1024))

    with pytest.raises(ValueError, match='压缩炸弹'):
        _decompress_gzip_bounded(bomb, 1024 * 1024)


def test_normal_payload_round_trips() -> None:
    payload = b'{"tables": {"orders": []}}' * 100

    assert _decompress_gzip_bounded(gzip.compress(payload), 10 * 1024 * 1024) == payload


def test_exactly_at_limit_is_allowed() -> None:
    """边界：正好等于上限要放行（读 limit+1 就是为了区分「等于」与「超过」）。"""
    payload = b'A' * 4096

    assert _decompress_gzip_bounded(gzip.compress(payload), 4096) == payload


def test_one_byte_over_limit_is_rejected() -> None:
    with pytest.raises(ValueError, match='压缩炸弹'):
        _decompress_gzip_bounded(gzip.compress(b'A' * 4097), 4096)


# ---------------------------------------------------------------------------
# 端点行为
# ---------------------------------------------------------------------------

async def test_bomb_upload_becomes_400_not_oom(monkeypatch: pytest.MonkeyPatch) -> None:
    """把上限压到 1MB，用 8MB 的高压缩比内容触发 —— 真实上限(500MB)下造样本太慢。"""
    monkeypatch.setattr(restore_mod.backup_service, 'MAX_BACKUP_FILE_SIZE', 1024 * 1024)
    bomb = gzip.compress(b'\0' * (8 * 1024 * 1024))

    with pytest.raises(HTTPException) as ei:
        await _read_backup_file(_UploadFileStub('bomb.json.gz', bomb))

    assert ei.value.status_code == 400


async def test_corrupt_gzip_becomes_400_not_500() -> None:
    """截断/损坏的 gz 此前会冒成 500（BadGzipFile/EOFError 无人接）。"""
    with pytest.raises(HTTPException) as ei:
        await _read_backup_file(_UploadFileStub('broken.json.gz', b'\x1f\x8b\x08\x00not-really-gzip'))

    assert ei.value.status_code == 400


async def test_plain_json_still_passes_through() -> None:
    body = b'{"tables": {}}'

    content, is_zip, name = await _read_backup_file(_UploadFileStub('ok.json', body))

    assert content == body and is_zip is False and name == 'ok.json'


# ---------------------------------------------------------------------------
# 静态守卫
# ---------------------------------------------------------------------------

def _source(path: Path) -> str:
    return path.read_text(encoding='utf-8')


def test_no_unbounded_gzip_decompress() -> None:
    """`gzip.decompress` 无上限，仓库里不得再出现。

    按 AST 找 `gzip.decompress` 的**属性访问**（而非仅调用）：`to_thread(gzip.decompress, x)`
    这种把函数当参数传的写法同样危险，只匹配 Call 会漏掉它。
    文档字符串里的同名字样不会被 AST 认作属性访问。
    """
    tree = ast.parse(_source(_RESTORE_PY))
    offenders = [
        node.lineno for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and node.attr == 'decompress'
        and isinstance(node.value, ast.Name)
        and node.value.id == 'gzip'
    ]

    assert offenders == [], f'第 {offenders} 行仍引用无上限的 gzip.decompress'


async def test_oversized_server_file_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """行为验证：超大服务器备份文件必须 400，而不是被整体读进内存。"""
    from fastapi_app.api.v1.endpoints.backup import validation as validation_mod

    monkeypatch.setattr(validation_mod.backup_service, 'BACKUP_DIR', tmp_path)
    monkeypatch.setattr(validation_mod.backup_service, 'MAX_BACKUP_FILE_SIZE', 16)
    (tmp_path / 'big.zip').write_bytes(b'PK\x03\x04' + b'\0' * 64)

    with pytest.raises(HTTPException) as ei:
        # 直调端点：绕过 Depends，只验证大小闸门本身
        await validation_mod.validate_backup_file('big.zip', None, object())

    assert ei.value.status_code == 400
    assert '大小限制' in str(ei.value.detail)


async def test_normal_sized_server_file_still_validates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """上限不能误伤正常文件（保证上面那条不是因为「什么都拒」而通过）。"""
    import io as _io
    import zipfile as _zipfile

    from fastapi_app.api.v1.endpoints.backup import validation as validation_mod

    buf = _io.BytesIO()
    with _zipfile.ZipFile(buf, 'w') as zf:
        zf.writestr('manifest.json', '{"tables": {}}')
    monkeypatch.setattr(validation_mod.backup_service, 'BACKUP_DIR', tmp_path)
    (tmp_path / 'ok.zip').write_bytes(buf.getvalue())

    result = await validation_mod.validate_backup_file('ok.zip', None, object())

    assert result['valid'] is True, result.get('issues')


def test_validation_zip_member_read_is_bounded() -> None:
    """成员读取不得是无参 `f.read()`（一次性解压全文）。"""
    src = _source(_VALIDATION_PY)
    tree = ast.parse(src)
    unbounded = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != 'read' or node.args:
            continue
        if (ast.get_source_segment(src, node) or '').strip() == 'f.read()':
            unbounded.append(node.lineno)

    assert unbounded == [], f'第 {unbounded} 行仍对 ZIP 成员无上限 f.read()'
