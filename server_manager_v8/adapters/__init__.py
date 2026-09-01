"""L1 适配层 — 所有 I/O 与平台细节的唯一出口。

实现 domain/ports.py 中定义的 Protocol。v6 的踩坑资产（进程树清理、
NSSM STOP_PENDING 等待、sc 输出 OEM 解码、服务依赖探测）全部迁移至此层，
且必须保留原有行为语义。

依赖规则（_guard R1）：adapters 只允许 import domain，禁止向上依赖。
"""
from __future__ import annotations

from . import _proc, audit_jsonl, health_http, metrics_psutil, notify_win, process_win, service_nssm, storage_json
from .audit_jsonl import AuditJsonlStore
from .health_http import HttpHealthAdapter, redis_ping
from .metrics_psutil import MetricsSamplerLoop, PsutilMetricsAdapter
from .notify_win import WinNotifyAdapter
from .process_win import ProcessWinAdapter
from .service_nssm import NssmServiceAdapter
from .storage_json import JsonConfigStorage, migrate_v1_to_v2

__all__ = [
    'AuditJsonlStore',
    'HttpHealthAdapter',
    'JsonConfigStorage',
    'MetricsSamplerLoop',
    'NssmServiceAdapter',
    'ProcessWinAdapter',
    'PsutilMetricsAdapter',
    'WinNotifyAdapter',
    '_proc',
    'audit_jsonl',
    'health_http',
    'metrics_psutil',
    'migrate_v1_to_v2',
    'notify_win',
    'process_win',
    'redis_ping',
    'service_nssm',
    'storage_json',
]
