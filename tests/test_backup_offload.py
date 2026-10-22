"""H1：备份加密必须下沉线程池，不能阻塞事件循环。"""
import asyncio
import time

import pytest


@pytest.mark.asyncio
async def test_encrypt_does_not_block_loop(monkeypatch):
    from fastapi_app.services.backup.orchestration import core

    ticks = []
    start = time.monotonic()

    def _slow_encrypt(*args, **kwargs):
        time.sleep(0.2)
        return b"enc", {}

    monkeypatch.setattr(core, "_encrypt_backup", _slow_encrypt)

    async def _ticker():
        for _ in range(5):
            ticks.append(time.monotonic() - start)
            await asyncio.sleep(0.02)

    await asyncio.gather(
        core._encrypt_backup_async(b"zip", "pw", {}, None),
        _ticker(),
    )

    assert len(ticks) == 5
    assert ticks[0] < 0.1, f"事件循环被加密阻塞了 {ticks[0]:.3f}s"


@pytest.mark.asyncio
async def test_zip_write_offloaded():
    """dump.sql.gz / RDB 等大文件写入 ZIP 也必须下沉线程池。"""
    from fastapi_app.services.backup.orchestration import core

    ticks = []
    start = time.monotonic()

    class _SlowZip:
        def write(self, path, arcname):
            time.sleep(0.2)

    async def _ticker():
        for _ in range(5):
            ticks.append(time.monotonic() - start)
            await asyncio.sleep(0.02)

    await asyncio.gather(
        core._write_to_zip_async(_SlowZip(), "p", "a"),
        _ticker(),
    )

    assert ticks[0] < 0.1, f"事件循环被 ZIP 写入阻塞了 {ticks[0]:.3f}s"
