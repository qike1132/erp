"""备份链路流式写入工具（ITER-1 T2 门面）。

实现落在 :mod:`fastapi_app.core.atomic_write`。之所以放在 ``core`` 层：
``services/backup/orchestration/core.py`` 依赖 ``core.backup_encryption``，
若把实现放本模块会让 ``core`` 反向依赖 ``services``，形成真实循环导入。

本模块按项目既有约定（services/<域>/ 门面 re-export）作为备份域的统一入口，
使备份/恢复代码只需记住一个 import。
"""
from __future__ import annotations

from fastapi_app.core.atomic_write import TMP_SUFFIX, atomic_output

__all__ = ['TMP_SUFFIX', 'atomic_output']
