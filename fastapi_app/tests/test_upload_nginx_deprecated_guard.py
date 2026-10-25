"""L-3（2026-10-25 上线前审计）：upload_nginx.py 弃用守卫。

该脚本是远端 Linux nginx 部署工具，上传目标是死配置 config/nginx.conf；
本机生产配置为 config/nginx-windows.conf。默认拒绝执行，防止误用把死配置
推上远端。只测守卫判定函数（放行后走 SSH 连接，不做网络测试）。
"""


def test_guard_blocks_by_default(capsys):
    from scripts.upload_nginx import deprecated_guard_engaged

    assert deprecated_guard_engaged([]) is True, '默认必须拒绝执行（弃用守卫）'
    assert deprecated_guard_engaged(['--from', 'x']) is True
    out = capsys.readouterr().out
    assert 'Deprecated' in out
    assert 'nginx-windows.conf' in out, '提示必须指向本机生效配置'


def test_guard_passes_only_with_explicit_flag():
    from scripts.upload_nginx import deprecated_guard_engaged

    assert deprecated_guard_engaged(['--accept-deprecated']) is False
