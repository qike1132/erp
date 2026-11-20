"""M4：图片 PIL 解码校验必须下沉线程池，不能阻塞事件循环。"""
import asyncio
import time

import pytest

from fastapi_app.api.v1.endpoints import customer_sampling as ep


@pytest.mark.asyncio
async def test_validation_does_not_block_loop(monkeypatch):
    ticks = []
    start = time.monotonic()

    def _slow_validate(*args, **kwargs):
        time.sleep(0.2)

    monkeypatch.setattr(ep.svc, "validate_project_image", _slow_validate)

    async def _ticker():
        for _ in range(5):
            ticks.append(time.monotonic() - start)
            await asyncio.sleep(0.02)

    await asyncio.gather(
        ep._validate_project_image_async(b"fake", "image/png"),
        _ticker(),
    )
    assert len(ticks) == 5
    assert ticks[0] < 0.1, f"事件循环被同步校验阻塞了 {ticks[0]:.3f}s"


@pytest.mark.asyncio
async def test_oversize_file_rejected_before_read():
    """审计 M-14：超过 10MB 必须在 read() 之前拒绝，避免整文件进内存。"""
    import io

    from fastapi import HTTPException
    from starlette.datastructures import UploadFile

    class ExplodingUpload(UploadFile):
        async def read(self, size: int = -1) -> bytes:
            raise AssertionError('大小校验前不得读取文件内容')

    file = ExplodingUpload(
        file=io.BytesIO(b''), size=10 * 1024 * 1024 + 1, filename='big.png',
    )

    with pytest.raises(HTTPException) as exc:
        await ep.api_upload_project_image(
            project_id=1, file=file, version=None, db=None, current_user=None,
        )

    assert exc.value.status_code == 413
