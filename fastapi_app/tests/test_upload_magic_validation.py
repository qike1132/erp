"""上传文件头（魔数）校验：公共校验层 + 6 个端点接入（P0-12）。

背景：端点此前只看扩展名，把任意内容改名成 .xlsx/.png/.pdf 即可进入解析链路
（伪造 xlsx 会一路走到 Excel 解析器，报错信息与真实故障无法区分）。
修复：core/validators.py 提供 validate_upload_magic(head_bytes, allowed_sets)，
端点先过文件头校验再进解析，失败返回 400 并记录文件签名。
"""
import ast
import logging
from pathlib import Path

import pytest
from fastapi import HTTPException

from fastapi_app.core.deps import _get_user_with_permissions
from fastapi_app.core.validators import (
    MAGIC_SETS,
    magic_signature,
    matches_upload_magic,
    require_upload_magic,
    validate_upload_magic,
)
from fastapi_app.main import app
from fastapi_app.shared_models import Permission, User

_REPO = Path(__file__).resolve().parents[2]

_PK = b'PK\x03\x04' + b'\x00' * 32
_PNG = b'\x89PNG\r\n\x1a\n' + b'\x00' * 32
_JPG = b'\xff\xd8\xff\xe0' + b'\x00' * 32
_PDF = b'%PDF-1.7\n%\xe2\xe3\xcf\xd3\n'

# (样本字节, 声明的扩展名, 是否应通过)
_POSITIVE = [
    (_PK, 'xlsx', 'xlsx'),
    (_PK, 'xlsm', 'xlsm'),
    (_PK, 'zip', 'zip'),
    (_PDF, 'pdf', 'pdf'),
    (_PNG, 'png', 'png'),
    (_JPG, 'jpg', 'jpg'),
    (_JPG, 'jpeg', 'jpeg'),
    (b'GIF89a' + b'\x00' * 8, 'gif', 'gif'),
    (b'RIFF\x00\x00\x00\x00WEBP', 'webp', 'webp'),
    (b'II*\x00' + b'\x00' * 8, 'tiff', 'tiff'),
    (b'\x1f\x8b\x08\x00' + b'\x00' * 8, 'gz', 'gz'),
    (b'id,amount\n1,2\n', 'csv', 'csv'),
    (b'{"a": 1}', 'json', 'json'),
    (b'[1, 2]', 'json', 'json'),
    (b'  \n\t{"a": 1}', 'json', 'json'),
]

# (样本字节, 声明的扩展名) —— 内容与扩展名不符，必须拦下
_NEGATIVE = [
    (b'not an excel workbook at all', 'xlsx'),
    (b'<html>nope</html>', 'png'),
    (b'<html>nope</html>', 'pdf'),
    (b'not json', 'json'),
    (b'\x00\x01\x02\x03binary', 'csv'),
    (b'PK\x03\x04', 'csv'),
    (b'', 'png'),
]


def _make_user(codes):
    user = User(username='tmp', password='x', is_super=False, status=True)
    user.permissions = [Permission(name=c, code=c) for c in codes]
    return user


def _use_user_with(codes) -> None:
    async def override():
        return _make_user(codes)
    app.dependency_overrides[_get_user_with_permissions] = override


# --------------------------------------------------------------------------
# 公共校验层
# --------------------------------------------------------------------------
def test_magic_registry_covers_the_documented_formats():
    for fmt in ('xlsx', 'xlsm', 'xls', 'pdf', 'png', 'jpg', 'jpeg', 'gif', 'webp', 'gz'):
        assert fmt in MAGIC_SETS, f'MAGIC_SETS 缺少 {fmt}'


@pytest.mark.parametrize('head,ext,_fmt', _POSITIVE)
def test_real_signatures_pass(head, ext, _fmt):
    assert matches_upload_magic(head, ext) is True, f'{ext} 的真签名被误判'
    assert validate_upload_magic(head, ext) is None


@pytest.mark.parametrize('head,ext', _NEGATIVE)
def test_mismatched_content_is_rejected(head, ext):
    assert matches_upload_magic(head, ext) is False, f'内容与 {ext} 不符却被放行'
    with pytest.raises(ValueError) as excinfo:
        validate_upload_magic(head, ext)
    assert '不匹配' in str(excinfo.value)


@pytest.mark.parametrize('case', ['no_dot', 'with_dot', 'upper'])
def test_extension_normalization(case):
    """扩展名带点/大写（ocr_import 传 '.PNG'）也要正确归一化。"""
    ext = {'no_dot': 'png', 'with_dot': '.png', 'upper': '.PNG'}[case]
    assert matches_upload_magic(_PNG, ext) is True
    assert matches_upload_magic(_JPG, ext) is False


def test_allowed_sets_accepts_a_tuple_of_formats():
    assert matches_upload_magic(_PK, ('xlsx', 'xlsm')) is True
    assert matches_upload_magic(_PDF, ('xlsx', 'xlsm')) is False


def test_magic_signature_is_loggable():
    sig = magic_signature(_PK)
    assert isinstance(sig, str) and 'hex=' in sig and 'ascii=' in sig


def test_require_upload_magic_raises_400_and_logs_signature(caplog):
    with caplog.at_level(logging.WARNING, logger='fastapi_app.core.validators'):
        with pytest.raises(HTTPException) as excinfo:
            require_upload_magic(b'not an excel', 'xlsx', filename='evil.xlsx')
    assert excinfo.value.status_code == 400
    assert '不匹配' in str(excinfo.value.detail)
    logged = ' '.join(rec.getMessage() for rec in caplog.records)
    assert '魔数校验失败' in logged, f'失败未记录文件签名：{logged!r}'
    assert 'evil.xlsx' in logged and 'hex=' in logged


def test_require_upload_magic_keeps_custom_detail():
    with pytest.raises(HTTPException) as excinfo:
        require_upload_magic(b'<html>', 'png', filename='x.png', detail='文件内容与扩展名不匹配，可能不是有效的图片文件')
    assert excinfo.value.status_code == 400
    assert excinfo.value.detail == '文件内容与扩展名不匹配，可能不是有效的图片文件'


# --------------------------------------------------------------------------
# 端点接入（HTTP）
# --------------------------------------------------------------------------
# (路径, 表单字段名, 文件名, 内容, 所需权限码)
_FAKE_UPLOADS = [
    ('/api/v1/production-plans/upload', 'file', 'evil.xlsx', b'not an excel workbook', ('production_plan_manage',)),
    ('/api/v1/production-summary/packaging/upload', 'file', 'evil.xlsx', b'not an excel workbook', ('production_summary_manage',)),
    ('/api/v1/auth/upload', 'file', 'evil.png', b'<html>not an image</html>', None),
    ('/api/v1/ocr-import/preview', 'file', 'evil.png', b'not an image at all', ('batch_import',)),
    ('/api/v1/backup/validate', 'file', 'evil.zip', b'not a zip archive', ('backup_read',)),
]


@pytest.mark.parametrize('url,field,filename,content,codes', _FAKE_UPLOADS)
async def test_fake_upload_is_rejected_with_400(client, url, field, filename, content, codes):
    """改扩展名的伪文件必须在进解析器之前 400（而不是 500 或解析报错）。"""
    if codes:
        _use_user_with(list(codes))
    resp = await client.post(url, files={field: (filename, content, 'application/octet-stream')})
    assert resp.status_code == 400, f'{url} 未拦下伪 {filename}: {resp.status_code} {resp.text[:300]}'
    assert '不匹配' in resp.text, f'{url} 的 400 不是魔数校验（可能是别的原因）: {resp.text[:300]}'


@pytest.mark.asyncio
async def test_batch_ocr_upload_skips_mismatched_file(client):
    """批量端点按「跳过该文件」处理，并把原因回显给用户（不是整批 400）。"""
    _use_user_with(['batch_import'])
    resp = await client.post(
        '/api/v1/ocr-import/upload',
        params={'session_id': 's-p012'},
        files={'files': ('evil.pdf', b'definitely not a pdf', 'application/pdf')},
    )
    assert resp.status_code == 200, resp.text[:300]
    body = resp.text
    assert '内容与扩展名不符' in body, f'跳过原因未回显: {body[:300]}'
    assert resp.json()['file_count'] == 0, '伪文件不应进入解析链路'


@pytest.mark.asyncio
async def test_encrypted_backup_is_not_rejected_by_magic(client):
    """加密备份的密文不是 PK 头，魔数校验必须让路（否则合法加密备份全被拒）。"""
    import json as _json
    meta = _json.dumps({'encrypted': True}, ensure_ascii=False).encode('utf-8')
    fake_encrypted = len(meta).to_bytes(4, 'big') + meta + b'\x00' * 64
    _use_user_with(['backup_read'])
    resp = await client.post(
        '/api/v1/backup/validate',
        files={'file': ('backup.zip', fake_encrypted, 'application/zip')},
    )
    assert resp.status_code == 400, resp.text[:300]
    assert '扩展名不匹配' not in resp.text, f'加密备份被魔数校验误伤: {resp.text[:300]}'


# --------------------------------------------------------------------------
# 布线守卫（防止接入点被回退掉）
# --------------------------------------------------------------------------
_REQUIRE_SITES = {
    'fastapi_app/api/v1/endpoints/production_plan.py': ('upload_excel',),
    'fastapi_app/api/v1/endpoints/production_summary.py': ('upload_packaging_excel',),
    'fastapi_app/api/v1/endpoints/auth.py': ('upload_file',),
    'fastapi_app/api/v1/endpoints/ocr_import.py': ('upload_shipping_docs', 'preview_shipping_doc', 'preview_order_doc'),
    'fastapi_app/api/v1/endpoints/backup/validation.py': ('validate_backup',),
}
_MAGIC_CALLS = {'require_upload_magic', 'matches_upload_magic'}

_BATCH_FUNC = ('fastapi_app/api/v1/endpoints/ocr_import.py', 'upload_shipping_docs')


def _calls_in_function(path: str, func_name: str) -> set:
    tree = ast.parse((_REPO / path).read_text(encoding='utf-8'))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_name:
            names = set()
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call):
                    func = sub.func
                    names.add(getattr(func, 'id', None) or getattr(func, 'attr', None))
            return names
    raise AssertionError(f'{path} 里找不到函数 {func_name}')


@pytest.mark.parametrize('path,funcs', sorted(_REQUIRE_SITES.items()))
def test_each_upload_endpoint_calls_the_magic_layer(path, funcs):
    for func_name in funcs:
        calls = _calls_in_function(path, func_name)
        assert calls & _MAGIC_CALLS, f'{path}::{func_name} 没有调用魔数校验（接入被回退？）'


def test_batch_endpoint_uses_the_bool_variant():
    """批量端点必须用 bool 版（跳过该文件），不能用抛 400 的版本。"""
    calls = _calls_in_function(*_BATCH_FUNC)
    assert 'matches_upload_magic' in calls


def test_backup_validate_exempts_encrypted_payloads():
    calls = _calls_in_function('fastapi_app/api/v1/endpoints/backup/validation.py', 'validate_backup')
    assert '_is_encrypted_data' in calls, '加密备份会让魔数校验误伤，必须放行'
    assert 'require_upload_magic' in calls
