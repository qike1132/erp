"""存储 key 生成的路径穿越回归。

背景（2026-11-15 审计）：`_generate_key` 直接使用客户端文件名最后一个 `.` 之后的
全部字符作为扩展名，`filename` 里带 `/`、`..` 时会把它们拼进 key，
`Path(base_dir) / key` 随即跳出上传根目录（`mkdir(parents=True)` 还会顺手建目录）。
"""
import re

from fastapi_app.services.storage_service import _generate_key

# 合法形状：<YYYYMMDD>/<32 位 uuid>.<1-8 位字母数字扩展名>
_KEY_RE = re.compile(r'^\d{8}/[0-9a-f]{32}\.[a-z0-9]{1,8}$')


def test_extension_is_whitelisted():
    key = _generate_key('evil./../../../../tmp/x')
    assert _KEY_RE.match(key), f'key 形状不合法（可能有穿越片段）: {key!r}'


def test_path_separators_never_reach_key():
    for name in ('a.b/c', 'a.b\\c', 'x.php%2f..%2fetc', 'a.b:c', '..%2f..%2fwin.ini'):
        key = _generate_key(name)
        # 除了日期目录那一个分隔符，不得再有路径片段；也不得出现 `..`
        assert key.count('/') == 1, f'{name!r} → {key!r}'
        assert '..' not in key, f'{name!r} → {key!r}'
        assert '\\' not in key, f'{name!r} → {key!r}'
        assert _KEY_RE.match(key), f'{name!r} → {key!r}'


def test_empty_or_dotless_name_falls_back_to_bin():
    key = _generate_key('noext')
    assert key.endswith('.bin')
