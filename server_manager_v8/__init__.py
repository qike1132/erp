"""ERP 服务器管理器 v8 — 四层架构包（迁移期包名带 _v8 后缀，P8 退役 v6 时改名 server_manager）。

分层与依赖方向（CI 由 server_manager_v8._guard 强制）：

    L4 presentation  表现层（web + bridge）      只调 Application
    L3 application   应用层（usecases/pipeline） 只调 Domain
    L2 domain        领域层（纯逻辑，零 I/O）    只依赖 stdlib
    L1 adapters      适配层（实现 Domain Ports） 只调 Domain

版本：v8.0.0-alpha（P1 骨架 + P2 Domain）
"""
from __future__ import annotations

__version__ = '8.0.0a1'

__all__ = ['__version__']
