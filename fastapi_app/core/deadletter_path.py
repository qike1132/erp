"""领域事件死信落盘位置的**唯一解析点**（2026-11-16 上线前审计 B-2）。

三个消费者都必须走这里，各算一遍路径就是在制造第二真相源：

1. 写入口 —— `fastapi_app/core/domain_events.py`（广播失败 / handler 失败落 JSONL）
2. ARQ 巡检 —— `fastapi_app/tasks/deadletter_patrol_task.py`（按 stage 计数）
3. 运维脚本 —— `scripts/inspect_deadletter.py`（统计与重放建议）

为什么必须可覆盖（2026-11-16 取证）：本机**生产主机同时是测试主机**，同一个仓库和
同一个 `.env` 既跑生产又跑测试。测试里 `publish_with_retry` 的广播必然失败（测试不初始化
Redis 客户端），若落仓库 `logs/`，测试噪音就写进了**生产巡检读的同一个文件**——
2026-10-09→11-16 已累积 2437 条纯测试广播死信，把「应为 0」的巡检基线彻底冲掉。
测试侧由 `fastapi_app/tests/evidence_isolation.py` 的 session autouse fixture 指向 `tmp_path`，
生产侧行为不变（仍需人工重放证据）。

本模块**刻意只依赖标准库**：运维脚本要在没有应用上下文的场景下解析路径，
不能顺手把 `config.py → load_dotenv` 整条链拉进来（非提权进程会 PermissionError）。
"""
from __future__ import annotations

import os
from pathlib import Path

#: 死信文件名（巡检、写入口、运维脚本共用一个字面量）
DEADLETTER_FILENAME = 'domain_events_deadletter.jsonl'

#: 覆盖死信目录的环境变量。留空 = 仓库根 `logs/`；生产保持留空。
ENV_OVERRIDE = 'ERP_DEADLETTER_DIR'


def deadletter_dir() -> Path:
    """死信目录：环境变量 `ERP_DEADLETTER_DIR` 优先，否则仓库根 `logs/`。"""
    override = os.environ.get(ENV_OVERRIDE)
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[2] / 'logs'


def deadletter_file() -> Path:
    """死信 JSONL 的完整路径。"""
    return deadletter_dir() / DEADLETTER_FILENAME
