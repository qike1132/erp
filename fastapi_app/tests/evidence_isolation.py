"""测试期「运行期证据文件」隔离——session 级 autouse fixture 的**唯一实现**。

为什么必须是同一份实现（2026-11-16 审计 B-4）：
`tests/conftest.py` 与 `fastapi_app/tests/conftest.py` 原本各写一遍同样的 fixture。
它保护的是**生产巡检读取的证据文件**，两份实现一旦漂移，代价就是「隔离只生效一半」——
而这类半生效不会报错，只会让下一次排查继续踩同一个坑。

根因（2026-11-16 取证）：本机生产主机同时是测试主机，同一个仓库与 `.env` 既跑生产又跑测试。
测试里 `publish_with_retry` 的 Redis 广播**必然失败**（测试不初始化客户端），
于是每条业务写用例都往 `logs/domain_events_deadletter.jsonl` 追加一条广播死信 ——
2026-10-09→11-16 累积 2437 条。该文件同时是生产巡检的读取源
（`deadletter_patrol_task` 按 stage 计数、`scripts/inspect_deadletter.py` 统计重放），
噪音把「应为 0」的基线彻底冲掉，巡检等于永久失去报警意义。
`audit_overflow.log` 同理（httpx 测试请求刷出 2.2MB）。

隔离后测试仍完整覆盖这些路径（写入、读回都在 tmp），只是不再污染生产证据。
"""
from __future__ import annotations

import pytest


@pytest.fixture(scope='session', autouse=True)
def _isolate_runtime_evidence_files(tmp_path_factory):
    """把死信目录与审计溢出文件重定向到临时目录，禁止写仓库级 `logs/`。"""
    from fastapi_app.core import audit_middleware as audit_module

    evidence_dir = tmp_path_factory.mktemp('runtime_evidence')
    patch = pytest.MonkeyPatch()
    patch.setenv('ERP_DEADLETTER_DIR', str(evidence_dir))
    patch.setattr(audit_module, '_OVERFLOW_PATH', evidence_dir / 'audit_overflow.log')
    yield
    patch.undo()
