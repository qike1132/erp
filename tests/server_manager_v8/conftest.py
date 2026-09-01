"""server_manager_v8 Domain 层测试。运行：python -m pytest tests/server_manager_v8 -v"""
from __future__ import annotations

import sys
from pathlib import Path

# 保证从仓库根以外的任意 CWD 运行时都能 import server_manager_v8
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
