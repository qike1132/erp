"""备份验证子包。

重新导出 core.py（原 verify.py）以及从 flat 文件搬入的健康检查与查询服务。
"""
from .core import *  # noqa: F403
from .health_check_service import *  # noqa: F403
from .query_service import *  # noqa: F403
