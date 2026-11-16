#!/usr/bin/env python3
"""领域事件死信巡检（M-4，2026-10-25 上线前审计）——只读。

背景：logs/domain_events_deadletter.jsonl 只增不消费——2026-10-25 审计时已
积压 1420 条广播死信无人巡检；ARQ 的 CRITICAL「需人工介入」告警也只落本地
日志（H-1 出货同步断流 3 天无人发现即后果）。本脚本把死信巡检变成一条命令：

- 广播死信（无 stage 字段，error=「Redis 广播未发出」）：按类型/日期统计，
  多为 Redis 重启窗口与 pytest 写入，人工决定是否重放；
- handler 死信（stage=handler / handler_cross_process）：**必须立刻处理**
  （2026-10-22 型 ImportError 静默吞单即此类），发现即 exit 2。

用法：python scripts/inspect_deadletter.py [--file PATH] [--days 7]
退出码：0=只有广播死信或为空；2=存在 handler 死信（需人工介入）。
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

RECENT_DAYS = 7


def default_deadletter_file() -> Path:
    """死信文件路径：与写入口、ARQ 巡检**同源**（含 ``ERP_DEADLETTER_DIR`` 覆盖）。

    为什么不能再各算一遍（2026-11-16 审计 B-2）：本仓给死信目录加了覆盖开关，
    写入口与 ARQ 巡检都走 ``core/deadletter_path.py``，只有本脚本还硬编码 ``logs/``。
    演练/测试把写盘指到别处后，本脚本会继续读旧文件 —— 两边看到的不是同一份数据，
    「0 条」这个基线再次分叉，而这正是当初加开关要消除的问题。

    注意只 import 那个**纯标准库**的解析模块：整条 ``fastapi_app.core.config``
    链会 ``load_dotenv``，非提权进程直接 PermissionError（.env 的 ACL 只给
    Administrators/SYSTEM），运维脚本不能因此起不来。
    """
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    from fastapi_app.core.deadletter_path import deadletter_file

    return deadletter_file()


def summarize(path: Path, days: int = RECENT_DAYS, now: datetime | None = None) -> dict:
    """汇总死信文件。坏行跳过（不因单行损坏让巡检崩溃）。"""
    now = now or datetime.now(UTC)
    by_type: Counter[str] = Counter()
    by_stage: Counter[str] = Counter()
    recent_by_day: Counter[str] = Counter()
    newest: list[dict] = []
    handler_samples: list[dict] = []
    total = 0
    with open(path, encoding='utf-8') as f:
        for raw in f:
            stripped = raw.strip()
            if not stripped:
                continue
            try:
                rec = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            total += 1
            by_type[rec.get('event_type', '?')] += 1
            stage = rec.get('stage', '') or 'broadcast'
            by_stage[stage] += 1
            try:
                ts = datetime.fromisoformat(rec.get('ts', ''))
            except ValueError:
                continue
            if now - ts <= timedelta(days=days):
                recent_by_day[ts.date().isoformat()] += 1
                newest.append(rec)
            if stage.startswith('handler') and len(handler_samples) < 5:
                handler_samples.append(rec)
    newest.sort(key=lambda r: r.get('ts', ''))
    return {
        'total': total,
        'by_type': dict(by_type),
        'by_stage': dict(by_stage),
        'recent_by_day': dict(sorted(recent_by_day.items())),
        'newest': newest[-10:],
        'handler_samples': handler_samples,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='领域事件死信巡检（只读）')
    parser.add_argument('--file', type=Path, default=None)
    parser.add_argument('--days', type=int, default=RECENT_DAYS)
    args = parser.parse_args(argv)

    if args.file is None:
        args.file = default_deadletter_file()
    if not args.file.exists():
        print(f'[OK] 死信文件不存在：{args.file}')
        return 0
    s = summarize(args.file, days=args.days)
    print(f'总计 {s["total"]} 条；分 stage：{s["by_stage"] or "{}"}')
    print('按事件类型（top）：'
          + ', '.join(f'{k}={v}' for k, v in sorted(
              s['by_type'].items(), key=lambda kv: -kv[1])[:6]))
    print(f'近 {args.days} 天分布：{s["recent_by_day"] or "无"}')
    if s['handler_samples']:
        print('\n[ALERT] 存在 handler 级死信（数据链路受损，必须人工介入/重放）：')
        for rec in s['handler_samples']:
            print(f'  {rec.get("ts")} stage={rec.get("stage")} '
                  f'handler={rec.get("handler")} error={str(rec.get("error"))[:120]}')
        return 2
    print('\n[OK] 无 handler 级死信（广播死信为跨 worker 通知/缓存失效，'
          '集中在 Redis 重启窗口；量大时再评估重放）。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
