"""XLSX 统一资源预算（M5，2026-10-25 上线前检查）。

请求体 10MiB 只限制**压缩后**的上传体积；xlsx 是 zip 容器，解压后的 XML、
shared strings、样式表、单元格数量与解析耗时都不受它约束——zip 炸弹
（高压缩比成员）可以让 10MiB 的上传在解析时膨胀数百倍。此前只有
``xlsx_cell_images`` 对图片字节有 64MiB 局部上限，关系/XML 成员与整个工作簿
解析没有统一预算。

本模块给**所有** Excel 解析入口（包装部上传、生产计划、采购计划、批量综合
导入、单元格图片提取）提供同一套前置闸门：

- ZIP 层（``assert_zip_budget``，读 infolist 不解压）：成员数、声明解压总量、
  单成员声明大小、压缩比上限；
- 工作簿层（``clip_iter_rows`` / ``assert_rows_within_budget``）：行/列上限，
  结果物化前拦截；
- 时间层（``run_sync_with_timeout`` / ``run_parse_with_timeout``）：解析在
  **专用有界线程池**中执行 + 显式超时，防止病态工作簿把 worker/事件循环钉死，
  并在超时返回后仍能跟踪线程真实终态（结束回调里清理临时文件）。

攻击前提是持有对应上传权限的已认证用户（五条链各有权限码），故阈值取
「合法业务文件远够用、病态文件必被拒」的宽紧度，不追求对抗国家级行为。
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import io
import logging
import os
import threading
import zipfile
from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)

#: zip 成员数上限。合法 xlsx 的结构成员（content types/rels/worksheets/styles/
#: sharedStrings/theme）不到 100 个；媒体再多也是几十个量级。
MAX_ZIP_MEMBERS = 500

#: 全部成员声明解压总量上限（xlsx 头部声明的 file_size 之和）。
#: 正常工作簿压缩比 2~5x，10MiB 上传的解压总量通常 < 50MiB；128MiB 给合法
#: 文件留足余量，同时把压缩比上限压到 ~12.8:1。
MAX_TOTAL_UNCOMPRESSED_BYTES = 128 * 1024 * 1024

#: 单成员声明解压大小上限。worksheet XML 正常在几 MiB 量级。
MAX_MEMBER_UNCOMPRESSED_BYTES = 64 * 1024 * 1024

#: 压缩比上限（file_size / compress_size）。合法 Excel 内容（XML 文本）压缩比
#: 通常 < 10x；42:1 是 zip 炸弹的典型指纹（重复内容的 deflate 可达 1000x+）。
MAX_COMPRESSION_RATIO = 100

#: 工作簿行/列上限（防超宽/超长工作簿把内存与 CPU 拖垮）。
MAX_SHEET_ROWS = 100_000
MAX_SHEET_COLS = 64

#: 解析超时（秒）。正常文件在毫秒~秒级完成；60s 足以覆盖大而合法的工作簿。
PARSE_TIMEOUT_SECONDS = 60.0


class XlsxBudgetError(ValueError):
    """工作簿超出统一资源预算（对外表现为普通的「文件无法解析」400/导入失败）。"""


def assert_zip_budget(source: str | bytes) -> None:
    """对 xlsx（zip 容器）执行前置资源预算，超出抛 :class:`XlsxBudgetError`。

    只读中央目录（infolist），不解压成员本身——声明的 file_size/compress_size
    足以在毫秒级拦下成员数/压缩比/解压总量三类炸弹；头部谎报的成员会在真实
    解析时因 CRC 不符炸 BadZipFile（各链路已有该异常口径），配合
    ``run_parse_with_timeout`` 的超时兜底。
    """
    try:
        with zipfile.ZipFile(io.BytesIO(source) if isinstance(source, bytes) else source) as zf:
            infos = zf.infolist()
            if len(infos) > MAX_ZIP_MEMBERS:
                raise XlsxBudgetError(
                    f'文件内部结构异常（成员数 {len(infos)} 超过上限 {MAX_ZIP_MEMBERS}）')
            total = 0
            for info in infos:
                size = info.file_size
                total += size
                if size > MAX_MEMBER_UNCOMPRESSED_BYTES:
                    raise XlsxBudgetError(
                        f'文件内部单个成员过大（{size} 字节，上限 {MAX_MEMBER_UNCOMPRESSED_BYTES}）')
                if info.compress_size > 0 and size / info.compress_size > MAX_COMPRESSION_RATIO:
                    raise XlsxBudgetError(
                        f'文件压缩比异常（{size / info.compress_size:.0f}:1，'
                        f'上限 {MAX_COMPRESSION_RATIO}:1），疑似压缩炸弹')
            if total > MAX_TOTAL_UNCOMPRESSED_BYTES:
                raise XlsxBudgetError(
                    f'文件解压后总量过大（{total} 字节，上限 {MAX_TOTAL_UNCOMPRESSED_BYTES}）')
    except zipfile.BadZipFile:
        raise  # 各链路已有 BadZipFile →「文件无法解析」口径
    except XlsxBudgetError:
        raise
    except (OSError, RuntimeError, ValueError) as e:
        # zipfile 对损坏中央目录可能抛其它异常：统一按解析失败处理（不吞预算判定）
        raise XlsxBudgetError(f'文件无法读取: {e}') from e


def clip_iter_rows(ws, *, min_row: int = 2):
    """按行预算裁剪的 ``ws.iter_rows``（openpyxl read_only 流式，不越界物化）。

    多读**一行**（max_row = 上限 + min_row）：物化后调用方必须以
    ``assert_rows_within_budget(len(rows), 真实列数)`` 显式拒绝超限文件。
    行有 max_row 硬裁剪（防海量行流式物化，多读的探测行由调用方判定）；
    列**不**在此裁剪——max_col 会把超宽行静默截断成合法宽度，调用方看到的
    len(row) 是假象，必须物化全宽后按真实列数判定。
    """
    return ws.iter_rows(
        min_row=min_row, max_row=MAX_SHEET_ROWS + min_row,
        values_only=True,
    )


def assert_rows_within_budget(n_rows: int, n_cols: int, *, what: str = '工作表') -> None:
    """解析结果物化后的行列预算判定（超限显式拒绝，绝不静默丢弃）。"""
    if n_rows > MAX_SHEET_ROWS:
        raise XlsxBudgetError(f'{what}行数 {n_rows} 超过上限 {MAX_SHEET_ROWS}')
    if n_cols > MAX_SHEET_COLS:
        raise XlsxBudgetError(f'{what}列数 {n_cols} 超过上限 {MAX_SHEET_COLS}')


async def run_parse_with_timeout[T](parse: Awaitable[T], timeout: float = PARSE_TIMEOUT_SECONDS) -> T:
    """带超时地等待解析结果；超时抛 :class:`XlsxBudgetError`（链路转 400/导入失败）。

    ⚠️ ``asyncio.wait_for`` 对 ``to_thread`` 的超时是**放弃等待**而非中止线程
    （线程池任务不可取消）——请求被及时释放并按失败返回，解析线程会跑到自然
    结束。配合 ZIP 层预算（声明解压总量/压缩比），失控解析的绝对时长已被压到
    可接受量级；本层防的是「病态文件反复上传把请求挂死」。

    M1（2026-10-26）：本函数只接受**已创建的 awaitable**，无法跟踪线程真实终态，
    也无法在超时后执行清理。新代码请用 :func:`run_sync_with_timeout`（专用有界
    线程池 + 结束回调 + 可观测的在途计数），本函数仅为兼容既有调用点保留。
    """
    try:
        return await asyncio.wait_for(parse, timeout)
    except TimeoutError as e:  # 3.11+ 即 asyncio.TimeoutError（UP041）
        raise XlsxBudgetError(
            f'文件解析超时（>{timeout:.0f}s），已中止等待——请拆分或精简后重试') from e


def parse_in_thread[T](fn, /, *args, **kwargs) -> Awaitable[T]:
    """``asyncio.to_thread`` 的语义别名：同步解析必须离开事件循环（超时可放弃等待）。"""
    return asyncio.to_thread(fn, *args, **kwargs)


# ---------------------------------------------------------------------------
# M1：可跟踪终态的解析执行器
# ---------------------------------------------------------------------------
#: 专用**有界**线程池。默认 executor 与 ``asyncio.to_thread`` 共用，一个病态
#: 工作簿把默认池占满会连带饿死同进程的其它 to_thread 调用（备份哈希、文件写入
#: 等）。并发上限按 CPU 取小值：xlsx 解析是 CPU 密集，超过核数只会互相拖慢并
#: 放大内存峰值。
_PARSE_MAX_WORKERS = max(2, min(4, os.cpu_count() or 2))
_PARSE_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=_PARSE_MAX_WORKERS, thread_name_prefix='xlsx-parse',
)

_pending_lock = threading.Lock()
_pending_parses: set[concurrent.futures.Future] = set()


def pending_parse_count() -> int:
    """仍在运行的解析任务数。

    超时返回后线程可能继续跑（线程不可取消），这个计数是「请求已失败但资源
    仍被占用」的唯一可观测信号；也供测试断言终态跟踪真的生效。
    """
    with _pending_lock:
        return len(_pending_parses)


async def run_sync_with_timeout[T](
    fn: Callable[..., T], /, *args,
    timeout: float = PARSE_TIMEOUT_SECONDS,
    cleanup: Callable[[], None] | None = None,
    **kwargs,
) -> T:
    """在线程池里跑同步解析，带超时与**真实的结束回调**。

    与 ``run_parse_with_timeout`` 的区别：

    * 提交到专用有界线程池，不占用默认 executor；
    * ``cleanup`` 在线程**真正结束**时执行（而不是在超时返回时），因此临时文件
      不会在 Windows 上因仍被工作线程占用而删不掉；
    * 在途任务数可观测（:func:`pending_parse_count`）。

    超时仍只停止等待（Python 无法安全终止线程），但此时解析线程受 ZIP/行列预算
    约束会自行结束，``cleanup`` 随后触发。
    """
    loop = asyncio.get_running_loop()
    future = _PARSE_EXECUTOR.submit(fn, *args, **kwargs)
    with _pending_lock:
        _pending_parses.add(future)

    def _on_done(fut: concurrent.futures.Future) -> None:
        # done_callback 只会触发一次（正常结束/异常/超时后的迟到结束都算一次）
        with _pending_lock:
            _pending_parses.discard(fut)
        if cleanup is None:
            return
        try:
            cleanup()
        except OSError as e:
            logger.warning('解析结束后的清理失败: %s', e)

    future.add_done_callback(_on_done)
    try:
        return await asyncio.wait_for(asyncio.wrap_future(future, loop=loop), timeout)
    except TimeoutError as e:
        raise XlsxBudgetError(
            f'文件解析超时（>{timeout:.0f}s），已中止等待——请拆分或精简后重试') from e
