"""写生产库前的统一护栏（2026-10-02 P6 存量审计）。

背景
----
**这台机器既是生产主机，也是运维主机**（AGENTS.md §0）。`scripts/` 下有一簇脚本
直连**生产库**写入 —— 清库、造测试数据、插假 app_version（会触发全设备 OTA）等 ——
其中多数**没有环境判断、没有干跑、没有确认**。误跑一次即毁数据。

本模块提供一次调用式的护栏：打印目标库 + 动作，未显式授权则拒绝执行。

用法
----
在脚本**真正写库之前**调用一次（通常紧跟在 `if __name__ == '__main__':` 之后）：

    from _prod_write_guard import require_prod_write_consent
    require_prod_write_consent('清空全部业务数据')

（`scripts/perf_optimization/` 等子目录下的脚本需先把父目录加入 sys.path。）

授权方式（二者其一）
--------------------
  · 环境变量 `ERP_ALLOW_PROD_WRITE=1`
  · 命令行 `--allow-prod-write`

设计取舍
--------
  · **默认拒绝**（fail-closed）：写生产是不可逆动作，宁可多一步显式授权。
  · 只拦"写"动作的脚本；只读诊断类脚本不应调用本函数。
  · 目标库始终打印且**口令脱敏**，让操作者一眼看到打的是哪个库。
"""
from __future__ import annotations

import os
import sys

_TRUTHY = {'1', 'true', 'yes', 'y', 'on'}
ENV_FLAG = 'ERP_ALLOW_PROD_WRITE'
ARG_FLAG = '--allow-prod-write'


def describe_target_db() -> str:
    """返回目标库的可读描述（host:port/db，口令已脱敏）。解析失败时给出原因。"""
    try:
        from sqlalchemy.engine import make_url

        from fastapi_app.core.config import settings

        url = make_url(settings.DATABASE_URL)
        host = url.host or '(local)'
        port = url.port or 5432
        return f'{host}:{port}/{url.database}（用户 {url.username or "?"}，口令已脱敏）'
    except Exception as exc:  # 解析失败不该阻断"拒绝"，只影响提示信息
        return f'<无法解析 DATABASE_URL: {type(exc).__name__}: {exc}>'


def prod_write_allowed() -> bool:
    """是否已显式授权写生产库。"""
    if os.getenv(ENV_FLAG, '').strip().lower() in _TRUTHY:
        return True
    return ARG_FLAG in sys.argv


def require_prod_write_consent(action: str, *, hint: str = '') -> None:
    """写生产库前调用。未显式授权则打印醒目告警并 **SystemExit(3)**。

    Args:
        action: 将要执行的动作（人类可读，如 '清空全部业务数据'）。
        hint: 额外提示（如不可逆、建议先备份）。
    """
    line = '!' * 78
    msg = [line, f'!! 即将对【生产库】执行写操作：{action}',
           f'!! 目标库：{describe_target_db()}']
    if hint:
        msg.append(f'!! {hint}')
    msg.append(line)

    if not prod_write_allowed():
        msg += [
            '',
            '已拒绝执行：本脚本会写生产库，需显式授权。',
            '确认无误后，用下面任一方式授权后重跑：',
            f'  · 环境变量：  {ENV_FLAG}=1 python <本脚本> ...',
            f'  · 命令行：    python <本脚本> ... {ARG_FLAG}',
            '',
        ]
        print('\n'.join(msg), file=sys.stderr)
        raise SystemExit(3)

    msg.append(f'已显式授权写生产库（{ENV_FLAG} 或 {ARG_FLAG}）。')
    msg.append('')
    print('\n'.join(msg), file=sys.stderr)
