"""工具模块包

提供批量上传相关的工具函数。

★ 惰性导出（PEP 562，2026-09-30）：本包此前在 **import 期** eager 导入
  ``batch_upload_utils``（硬要求 polars + openpyxl，缺任一直接 raise）与 ``logger``
  （sqlalchemy），于是任何只想用 stdlib 叶子模块的调用方都被迫拉起整条重依赖链：

  · 桌面壳 ``server_manager``（PyInstaller 打包，``server_manager.spec`` 明确 exclude
    了 openpyxl/sqlalchemy）一旦 ``import utils`` 就在**启动期** ImportError —— 这正是
    「轮转实现只能自带一份、与后端各写一套」的根因；
  · ``prod_runner``（生产监督器）也白白在启动期多背一份 openpyxl/polars 的导入风险：
    哪天这些重依赖没装上，正常该只守护 uvicorn 的监督器会直接起不来。

  实测全仓**没有任何** ``from utils import <名字>`` 的用法（只有 ``from utils.<子模块>
  import ...``），故改为 ``__getattr__`` 惰性解析后：旧名字对外仍可用（首次访问才
  真正导入），而 ``import utils.log_rotation`` 只执行本文件与目标叶子模块。

  守卫测试：``tests/test_utils_lazy_import.py``（子进程校验 import utils.log_rotation
  不会把 openpyxl/polars/sqlalchemy 拉进 sys.modules，且旧名字仍可取到）。
"""
from __future__ import annotations

import importlib

# 名字 → 所在子模块（与原 eager 导入的对外契约逐字一致）
_EXPORTS = {
    'BatchUploadError': 'batch_upload_utils',
    'batch_save_with_transaction': 'batch_upload_utils',
    'generate_error_report': 'batch_upload_utils',
    'parse_excel_file': 'batch_upload_utils',
    'transactional': 'batch_upload_utils',
    'validate_batch_data': 'batch_upload_utils',
    'validate_customer_name': 'batch_upload_utils',
    'validate_date': 'batch_upload_utils',
    'validate_product': 'batch_upload_utils',
    'validate_quantity': 'batch_upload_utils',
    'log_request': 'logger',
    'logger': 'logger',
}

__all__ = [
    'BatchUploadError',
    'batch_save_with_transaction',
    'generate_error_report',
    'log_request',
    'logger',
    'parse_excel_file',
    'transactional',
    'validate_batch_data',
    'validate_customer_name',
    'validate_date',
    'validate_product',
    'validate_quantity',
]


def __getattr__(name: str):
    """惰性解析包级重导出（PEP 562）：只 import 目标叶子模块，不连带整条重依赖链。"""
    submodule = _EXPORTS.get(name)
    if submodule is None:
        raise AttributeError(f'module {__name__!r} has no attribute {name!r}')
    attribute = getattr(importlib.import_module(f'.{submodule}', __name__), name)
    globals()[name] = attribute          # 缓存：后续访问（含 from utils import）不再走 __getattr__
    return attribute


def __dir__() -> list[str]:
    return sorted(__all__)
