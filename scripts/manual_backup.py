"""手动执行一次全量备份（不依赖 ARQ worker）

## 为什么需要这个脚本

正常路径下备份由 ARQ cron 驱动（`tasks/backup_tasks.py` 的 `scheduler_poller`
每 5 分钟扫描 `backup_schedule` 表入队）。但 2026-09-15 上线就绪评估发现：

- `erp-arq` Windows 服务处于 **Stopped** → 定时备份已停摆
- 最新备份停留在 2026-09-10（过期 5 天）

本脚本直接调用**同一个生产任务函数** `manual_full_backup_task`，
复用完整的落盘 / meta / backup_record / 校验和逻辑，产出与自动备份**完全同构**的产物。
可在 ARQ 未运行时作为应急备份手段。

## 用法

    python scripts/manual_backup.py --remark "上线前手动备份"
    python scripts/manual_backup.py --dry-run     # 只打印将执行的动作

产物：`{BACKUP_DIR}/erp_backup_<时间戳>.zip` + `.zip.meta`

## 注意

- 备份期间会获取数据库备份锁（`acquire_backup_lock`），与自动备份互斥；
- 与还原操作互斥（还原进行中会拒绝执行）；
- 加密：未配置 `BACKUP_ENCRYPTION_PASSWORD` 时按项目既有行为降级为不加密。
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


async def _run(remark: str) -> int:
    from fastapi_app.tasks.backup_tasks import manual_full_backup_task

    print(f'[备份] 开始全量备份，备注: {remark}')
    started = datetime.now()

    # ctx 仅需提供 job_try（任务内唯一用到的 ctx 字段）。
    # 不传 encrypt：原写死 `encrypt=False` 会**无条件产出不加密备份**，即便
    # BACKUP_ENCRYPTION_ENABLED=true 且口令已配 —— 既与本脚本 docstring
    # “与自动备份完全同构”矛盾，也踩 AGENTS.md 红线 #4（静默降级为不加密）。
    # 用任务默认（encrypt=True），由服务层按 ENABLED/口令决定。
    await manual_full_backup_task({'job_try': 1}, remark=remark)

    elapsed = (datetime.now() - started).total_seconds()
    print(f'[备份] 完成，耗时 {elapsed:.1f}s')
    return 0


def _latest_backup() -> tuple[Path | None, datetime | None]:
    import os
    backup_dir = Path(os.getenv('BACKUP_DIR', 'backups/server'))
    if not backup_dir.is_absolute():
        backup_dir = ROOT / backup_dir
    if not backup_dir.exists():
        return None, None
    # 必须同时匹配 .zip 与 .zip.enc：生产加密开启时落盘是 `erp_backup_*.zip.enc`，
    # 只 glob '*.zip' 会永远报“未找到备份产物”（与 P2 审计的
    # health_check_service 同源缺陷）。
    zips = sorted(backup_dir.glob('erp_backup_*.zip*'), key=lambda p: p.stat().st_mtime)
    if not zips:
        return None, None
    newest = zips[-1]
    return newest, datetime.fromtimestamp(newest.stat().st_mtime)


def main() -> int:
    ap = argparse.ArgumentParser(description='手动执行一次全量备份（不依赖 ARQ）')
    ap.add_argument('--remark', default='手动全量备份', help='备份备注（写入 meta）')
    ap.add_argument('--dry-run', action='store_true', help='只显示当前状态，不执行')
    args = ap.parse_args()

    newest, mtime = _latest_backup()
    if newest:
        age_days = (datetime.now() - mtime).total_seconds() / 86400
        print(f'[现状] 最新备份: {newest.name}')
        print(f'[现状] 备份时间: {mtime:%Y-%m-%d %H:%M}（{age_days:.1f} 天前）')
        print(f'[现状] 大小    : {newest.stat().st_size / 1048576:.1f} MB')
    else:
        print('[现状] 未找到任何备份产物')

    if args.dry_run:
        print('\n（dry-run，未执行备份）')
        return 0

    print()
    return asyncio.run(_run(args.remark))


if __name__ == '__main__':
    sys.exit(main())
