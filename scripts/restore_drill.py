"""恢复演练：把最新全量备份恢复到 erp_system_drill，验证备份 artifact 真实可恢复。

复用生产恢复函数 restore_database_via_psql —— 演练的就是灾难发生时会走的那条代码路径。
通过给子进程环境设置 DB_NAME=erp_system_drill，使 DROP/CREATE/导入全部只作用于演练库，
绝不影响生产库 erp_system。

用法：python scripts/restore_drill.py [备份zip路径]（默认取 backups/server/ 下最新一个）
"""
from __future__ import annotations

import asyncio
import os
import sys
import zipfile
from pathlib import Path

# 项目根目录
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / '.env')

# 关键安全护栏：必须在导入任何 app 模块之前把演练库名注入环境，
# restore_database_via_psql 全程只读 DB_NAME 环境变量。
DRILL_DB = 'erp_system_drill'
os.environ['DB_NAME'] = DRILL_DB

import fastapi_app.services.backup.dump as dump_mod
from fastapi_app.core.database import require_async_session_local


def newest_backup() -> Path:
    backups = sorted((ROOT / 'backups' / 'server').glob('erp_backup_*.zip'))
    if not backups:
        raise SystemExit('未找到任何 erp_backup_*.zip 备份文件')
    return backups[-1]


async def main() -> int:
    zip_path = Path(sys.argv[1]) if len(sys.argv) > 1 else newest_backup()
    print(f'[drill] 备份文件: {zip_path.name}')
    print(f'[drill] 目标库:   {DRILL_DB} (生产库 erp_system 不受影响)')

    zf = zipfile.ZipFile(zip_path)
    async with require_async_session_local()() as db:
        result = await dump_mod.restore_database_via_psql(zf, db)

    print(f'[drill] 恢复结果: {result}')
    return 0 if result.get('status') == 'ok' else 1


if __name__ == '__main__':
    raise SystemExit(asyncio.run(main()))
