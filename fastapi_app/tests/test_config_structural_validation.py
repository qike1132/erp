"""
配置结构边界单测（OPT-12，2026-10-01）

Settings.__init__ 的手写闸门覆盖安全项（SECRET_KEY/JWT/ALLOWED_HOSTS/备份），
本文件锁死「结构写错即运行期诡异爆炸」的一类：API_PREFIX 形状、Redis 端口/库号
边界、令牌时效为正。坏值必须在启动期 RuntimeError，而不是运行期静默错乱。
"""
import pytest

from fastapi_app.core.config import Settings


def test_default_settings_pass_structural_validation():
    """当前 .env/默认值必须能通过全部结构校验（守护默认值本身不被改坏）。"""
    Settings()  # 不抛即通过


@pytest.mark.parametrize(
    'kwargs, needle',
    [
        ({'API_PREFIX': 'api/v1'}, 'API_PREFIX'),      # 缺前导斜杠
        ({'API_PREFIX': '/api/v1/'}, 'API_PREFIX'),    # 尾斜杠
        ({'API_PREFIX': ''}, 'API_PREFIX'),            # 空串
        ({'REDIS_PORT': 0}, 'REDIS_PORT'),
        ({'REDIS_PORT': 70000}, 'REDIS_PORT'),
        ({'REDIS_DB': 16}, 'REDIS_DB'),                # Redis 逻辑库只有 0-15
        ({'REDIS_DB': -1}, 'REDIS_DB'),
        ({'ACCESS_TOKEN_EXPIRE_MINUTES': 0}, '令牌时效'),
        ({'REFRESH_TOKEN_EXPIRE_DAYS': -3}, '令牌时效'),
    ],
)
def test_bad_structural_values_rejected(kwargs, needle):
    with pytest.raises(RuntimeError, match=needle):
        Settings(**kwargs)
