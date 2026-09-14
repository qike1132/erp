"""原子文件写入原语（ITER-1 T2）。

统一的「写临时文件 → fsync → 原子改名」写入方式，供备份/恢复产物
（ZIP 包 / 加密密文 / WAL 段 / 元数据 sidecar）以及任何需要
「目标路径上要么没有、要么完整」语义的落盘场景复用。

两个收益：

1. **读到的永远是完整文件**。直接写目标路径时，读侧（下载接口、恢复流程、
   校验任务）可能读到写了一半的文件，而且**不会报错**——ZIP 被当成损坏包、
   JSON 被当成解析失败，排障成本很高。``os.replace`` 在同一文件系统内是原子的，
   所以目标路径上要么不存在，要么是完整内容。
2. **顺带解决 P1-13**：清理任务按正式文件名匹配（``*.zip`` / ``*.zip.enc``），
   而写入中占用的是 ``<target>.tmp``，天然不会被清理任务删掉。

放在 ``core/`` 而非 ``services/backup/`` 是刻意的：本模块被
``core/backup_encryption.py`` 使用，而 ``services/backup/`` 反过来
依赖 ``core.backup_encryption``（见 ``services/backup/orchestration/core.py``），
若把实现放在 services 层会形成真实循环导入。

注意：``os.replace`` 的原子性要求临时文件与目标文件**在同一文件系统**，
因此临时文件与目标同目录同名（仅加后缀），不做跨盘中转。
"""
from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import IO

__all__ = ['TMP_SUFFIX', 'atomic_output']

#: 写入中文件的统一后缀。清理逻辑只匹配正式文件名，因此不会撞上它。
TMP_SUFFIX = '.tmp'


@contextmanager
def atomic_output(target: Path, *, suffix: str = TMP_SUFFIX) -> Iterator[IO[bytes]]:
    """以「原子落盘」方式写 ``target``。

    用法::

        with atomic_output(dest) as fh:
            fh.write(chunk)

    退出上下文时顺序为 ``flush`` → ``fsync`` → ``os.replace``。
    ``fsync`` 不能省：备份的价值就是掉电/崩溃后可恢复，仅 ``flush``
    只把数据交给操作系统页缓存，并未落盘。

    任何异常（含 ``KeyboardInterrupt`` / ``asyncio.CancelledError``）都会
    删除临时文件并把原异常向上抛；目标路径保持「未被本次写入触碰」的状态。
    """
    target = Path(target)
    tmp = target.with_name(target.name + suffix)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(tmp, 'wb') as fh:
            yield fh
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, target)
    except BaseException:
        _unlink_quietly(tmp)
        raise


def _unlink_quietly(path: Path) -> None:
    """删除临时文件，绝不因为删除失败而掩盖真正的异常。

    Windows 上文件可能仍被其它句柄占用；残留 ``*.tmp`` 无害（下次写会覆盖），
    但绝不能让删除失败顶掉原始异常。
    """
    with suppress(OSError):
        path.unlink(missing_ok=True)
