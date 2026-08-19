"""生产审核运行脚本(简单 wrapper)。

用法::

    python scripts/run_prod_audit.py
    python scripts/run_prod_audit.py --resume-from L4
    python scripts/run_prod_audit.py --config <path> --rules <path> --evidence-dir <dir>

退出码:
    - 0 — 正常完成
    - 1 — 层门禁阻断
    - 2 — 配置错误
"""

from __future__ import annotations

import sys
from pathlib import Path

# 确保项目根目录在 sys.path 中
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.prod_audit.orchestrator import main


def run() -> int:
    """运行生产审核并打印摘要。"""
    try:
        exit_code = main()
    except KeyboardInterrupt:
        print("\n[中断] 审核被用户中断,可使用 --resume-from 从断点恢复。", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"[错误] 未预期的异常: {exc}", file=sys.stderr)
        return 3

    if exit_code == 0:
        print("\n[完成] 审核成功完成。")
    elif exit_code == 1:
        print("\n[阻断] 审核被门禁阻断,请修复问题后重新运行。", file=sys.stderr)
    elif exit_code == 2:
        print("\n[配置错误] 请检查配置文件后重试。", file=sys.stderr)

    return exit_code


if __name__ == "__main__":
    sys.exit(run())
