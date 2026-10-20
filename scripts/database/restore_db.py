"""从 pg_dump 产物恢复 PostgreSQL 库（审计 F1-7：实现收敛到 restore_core）。

本文件只做三件事：解析参数 → 取写生产库授权 → 调 `restore_core` 汇报结果。
**恢复逻辑（恢复前备份 / 终止连接 / DROP+CREATE / psql 导入 / 落地校验）只有一份，
在 `scripts/database/restore_core.py`** —— `db_manager.py restore` 走的是同一份。

用法:
    python scripts/database/restore_db.py <备份文件路径>
    python scripts/database/restore_db.py --allow-prod-write <备份文件路径>

支持格式: .sql, .sql.gz, .zip
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# scripts/ 与 scripts/database/ 都在 import 路径上：本文件直接以脚本方式运行，
# 单元测试则用 importlib 按路径加载（此时脚本目录不在 sys.path 里）。
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent))

from _prod_write_guard import require_prod_write_consent
from restore_core import (
    RestoreError,
    UnsupportedBackupFormatError,
    restore_from_file,
)

USAGE = (
    '用法: python scripts/database/restore_db.py '
    '[--allow-prod-write] [--allow-missing-pre-restore-backup] <备份文件路径>'
)


def main() -> None:
    argv = sys.argv[1:]
    allow_missing_backup = '--allow-missing-pre-restore-backup' in argv
    cli_args = [a for a in argv if not a.startswith('--')]

    db_name = os.getenv('DB_NAME', 'erp_system')
    if not db_name.isidentifier():
        print(f'错误: 数据库名称无效: {db_name!r}')
        sys.exit(1)

    if not os.getenv('DB_PASSWORD'):
        print('错误: 请设置环境变量 DB_PASSWORD')
        print(USAGE)
        sys.exit(1)

    if not cli_args or not os.path.exists(cli_args[0]):
        print('错误: 请指定有效的备份文件路径')
        print(USAGE)
        sys.exit(1)
    backup_path = Path(cli_args[0])

    print('警告: 即将恢复数据库，这将覆盖当前所有数据！')
    require_prod_write_consent(
        f'数据库恢复（{backup_path}）',
        hint='不可逆；请先确认已备份当前库',
    )
    confirm = input('确认继续? (yes/no): ')
    if confirm.lower() not in ('yes', 'y'):
        print('已取消恢复操作')
        sys.exit(0)

    try:
        outcome = restore_from_file(
            backup_path,
            allow_missing_pre_backup=allow_missing_backup,
            require_consent=False,  # 上面已取过授权
        )
    except (UnsupportedBackupFormatError, RestoreError) as e:
        print(f'错误: {e}')
        sys.exit(1)

    if not outcome.ok:
        print(outcome.message)
        sys.exit(1)

    print('数据库恢复成功!')


if __name__ == '__main__':
    main()
