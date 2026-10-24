"""pg_dump/psql 恢复。"""
from __future__ import annotations

import asyncio
import contextlib
import gzip
import logging
import os
import shutil
import subprocess
import threading
import time
from collections.abc import Mapping
from pathlib import Path
from typing import IO, Any, NamedTuple, cast

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ._constants import BACKUP_OPERATION_TIMEOUT
from ._proc import run_proc
from .snapshot import get_pg_version

logger = logging.getLogger(__name__)

# 2026-10-17 审计 P2-15：pg_dump 线程此前无超时看门狗，DB 端卡住/管道阻塞时
# 会永久占住一个连接与线程。
# 2026-10-18 OCR 评审：外层 create_full_backup 还有 asyncio.wait_for 总超时
# （BACKUP_OPERATION_TIMEOUT，默认 1800s），to_thread 无法中断线程，所以
# dump 侧必须比外层更早触发，才能真正终止子进程。
_PG_DUMP_TIMEOUT_SECONDS = max(60, BACKUP_OPERATION_TIMEOUT - 60)

# PG 客户端工具自动发现候选目录（F6：pg_dump/psql 常不在服务进程 PATH 上）
_PG_BIN_CANDIDATE_GLOBS = (
    r'C:\Program Files\PostgreSQL\*\bin',
    r'D:\PostgreSQL\bin',
    r'C:\PostgreSQL\bin',
)


def resolve_pg_tool(tool: str) -> str:
    """解析 pg_dump/psql 可执行文件路径（F6，2026-08-24 审计整改）。

    优先级：PG_TOOLS_BIN 环境变量指定目录 > 系统 PATH > 常见安装目录探测。
    找不到时返回原名（保持旧行为：由 FileNotFoundError 提示客户端工具缺失，
    上层回退 JSON 备份路径）。
    """
    env_dir = os.environ.get('PG_TOOLS_BIN', '').strip()
    search_dirs: list[str] = []
    if env_dir:
        search_dirs.append(env_dir)
    for pattern in _PG_BIN_CANDIDATE_GLOBS:
        search_dirs.extend(str(d) for d in __import__('glob').glob(pattern))

    for d in search_dirs:
        for exe in (f'{tool}.exe', tool):
            candidate = Path(d) / exe
            if candidate.is_file():
                return str(candidate)
    return shutil.which(tool) or tool


async def run_pg_dump(output_path: Path, snapshot_id: str | None = None) -> dict:
    """执行 pg_dump 导出数据库为 gzip 压缩 SQL

    Args:
        output_path: 输出文件路径
        snapshot_id: 可选，PostgreSQL 快照 ID，用于一致性备份

    Returns: dict with pg_version, db_name, dump_size, duration_seconds, snapshot_id
    """
    start = time.monotonic()
    db_host = os.getenv('DB_HOST', 'localhost')
    db_port = os.getenv('DB_PORT', '5432')
    db_user = os.getenv('DB_USER', 'erp_app')
    db_name = os.getenv('DB_NAME', 'erp_system')
    if not db_name.isidentifier() or not all(c.isalnum() or c == '_' for c in db_name) or db_name[0].isdigit():
        raise ValueError(f'Invalid database name: {db_name!r}')
    db_password = os.getenv('DB_PASSWORD', '')
    env = os.environ.copy()
    env['PGPASSWORD'] = db_password
    try:
        # 构建 pg_dump 命令参数
        pg_dump_args = [
            resolve_pg_tool('pg_dump'), '-h', db_host, '-p', db_port, '-U', db_user, '-d', db_name,
            '--no-owner', '--no-privileges'
        ]

        # 如果提供了快照 ID，使用 --snapshot 参数
        if snapshot_id:
            pg_dump_args.extend(['--snapshot', snapshot_id])
            logger.info(f"使用数据库快照 {snapshot_id} 进行备份")

        # H4 流式导出：旧实现 capture_output 整体缓冲未压缩 SQL，再 gzip.compress
        # 生成第二份全量副本（峰值内存 ≈ SQL + 压缩后副本）；现改为 stdout 分块
        # 直接写入 gzip 文件，峰值内存 ≈ 单个分块（1MB）。
        # F6/M5: 仍用 Python 内置 gzip，不依赖外部 gzip 可执行文件。
        output_path.parent.mkdir(parents=True, exist_ok=True)
        stderr_chunks: list[bytes] = []

        def _stream_dump_to_gzip() -> None:
            """工作线程：pg_dump stdout 分块流式压缩落盘。

            与 _proc.run_proc 一样走同步 subprocess（Windows SelectorEventLoop
            不支持 asyncio 子进程 transport）。
            """
            proc_ = subprocess.Popen(  # 参数为白名单校验后的固定列表
                pg_dump_args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
            )
            # stdout/stderr 均为 PIPE，管道对象必然存在；mypy 无法从 Popen 构造参数推断
            stdout_pipe = cast(IO[bytes], proc_.stdout)
            stderr_pipe = cast(IO[bytes], proc_.stderr)

            def _drain_err() -> None:
                while True:
                    chunk = stderr_pipe.read(65536)
                    if not chunk:
                        break
                    stderr_chunks.append(chunk)

            t_err = threading.Thread(target=_drain_err, daemon=True)
            t_err.start()

            # 2026-10-18 OCR 评审：看门狗必须独立于 stdout 读取循环——DB 卡住时
            # read() 会永久阻塞，循环后的 wait(timeout) 永远执行不到。
            #
            # 顺序很关键（2026-10-18 评审复核实测）：原来的写法是 `timed_out.set()`
            # 放在 terminate() **之前**且无条件执行，随后在读循环后又查一次
            # `if timed_out.is_set(): raise TimeoutError`。pg_dump 正常结束时
            # 循环退出 → wait() 立即返回 → 看到标志已置位就判超时。即「进程正常
            # 完成」与「被看门狗杀掉」共用同一标志，而 terminate() 本身会让
            # returncode 变成 -15/非 0，二者无法从返回值区分 → 正常完成也会
            # 被误报成超时。
            # 现在：置位**只在看门狗真的触发时**发生，且读取循环结束后
            # **先 cancel+join 看门狗再判断标志**，彻底消除
            # 「主线程已退出循环、看门苟延残喘补一个 set()」的竞态。
            timed_out = threading.Event()

            def _watchdog_kill() -> None:
                timed_out.set()
                with contextlib.suppress(OSError):
                    proc_.terminate()
                    try:
                        proc_.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        proc_.kill()

            watchdog = threading.Timer(_PG_DUMP_TIMEOUT_SECONDS, _watchdog_kill)
            watchdog.daemon = True
            watchdog.start()
            try:
                with open(output_path, 'wb') as raw_f, gzip.GzipFile(
                    fileobj=raw_f, mode='wb', compresslevel=1,
                ) as gz_f:
                    while True:
                        chunk = stdout_pipe.read(1024 * 1024)
                        if not chunk:
                            break
                        gz_f.write(chunk)
                stdout_pipe.close()
                # 先确保看门狗不再可能触发，再读它的标志：Timer.cancel() 只阻止
                # 「尚未开始」的回调；若回调已在另一个线程里跑到一半，join() 才会
                # 等它做完。少了这一步，主线程可能在 set() 之前判断 → 漏判超时，
                # 或在 set() 之后判断 → 把正常完成误判成超时。
                watchdog.cancel()
                watchdog.join(timeout=_PG_DUMP_TIMEOUT_SECONDS + 10)
                try:
                    proc_.wait(timeout=_PG_DUMP_TIMEOUT_SECONDS)
                except subprocess.TimeoutExpired as exc:
                    # 2026-10-18 OCR 评审：转成 TimeoutError，调用链统一按超时处理
                    raise TimeoutError(
                        f'pg_dump 超时（{_PG_DUMP_TIMEOUT_SECONDS}s）'
                    ) from exc
                if timed_out.is_set():
                    raise TimeoutError(f'pg_dump 超时（{_PG_DUMP_TIMEOUT_SECONDS}s）')
                if proc_.returncode != 0:
                    stderr_text = b''.join(stderr_chunks).decode(errors='replace')
                    raise RuntimeError(
                        f"pg_dump failed (rc={proc_.returncode}): {stderr_text}"
                    )
            except BaseException:
                # WARN-1 修复：写盘/gzip 异常（磁盘满、权限等）时终止 pg_dump，
                # 否则子进程成为孤儿——stdout 管道无人排空会阻塞在 write 上，
                # 且持续占用一个数据库连接
                proc_.terminate()
                try:
                    proc_.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc_.kill()
                    proc_.wait()
                raise
            finally:
                # cancel() 幂等：正常路径已在 wait() 前 cancel+join，异常路径
                # （写盘/gzip 失败）在这里补一次，保证看门狗不会在 terminate()
                # 之后又去 kill 同一个进程。
                watchdog.cancel()
                t_err.join(timeout=30)
                stderr_pipe.close()

        await asyncio.to_thread(_stream_dump_to_gzip)
        duration = time.monotonic() - start
        return {
            'pg_version': await get_pg_version(db_host, db_port, db_user, db_password, env),
            'db_name': db_name,
            'dump_size': output_path.stat().st_size,
            'duration_seconds': round(duration, 2),
            'snapshot_id': snapshot_id,
        }
    except FileNotFoundError:
        raise RuntimeError('pg_dump 命令未找到，请确保 PostgreSQL 客户端工具已安装') from None
    except RuntimeError:
        raise
    except (TimeoutError, OSError, ValueError) as e:
        raise RuntimeError(f'pg_dump 执行失败: {e}') from e


def _resolve_admin_credentials(
    db_user: str, db_password: str, environ: Mapping[str, str] | None = None,
) -> tuple[str, str]:
    """解析重建数据库（DROP/CREATE）所用凭据，返回 (用户名, 口令)。

    配置了 PG_SUPER_PASSWORD 时用超级用户（默认 PG_SUPER_USER=postgres）；否则回退应用角色
    —— 此时该角色必须有 CREATEDB，否则重建前的权限预检会拒绝恢复（不会先删库）。
    """
    env = os.environ if environ is None else environ
    super_password = env.get('PG_SUPER_PASSWORD')
    if super_password:
        # `or 'postgres'`：显式写成 PG_SUPER_USER=（空值）时 get 返回 ''，会让 psql -U '' 失败
        return env.get('PG_SUPER_USER') or 'postgres', super_password
    return db_user, db_password


async def _admin_can_create_database(
    *, db_host: str, db_port: str, admin_user: str, admin_env: dict,
) -> str | None:
    """预检执行者是否具备建库权（超级用户或 CREATEDB）。

    通过返回 None；否则返回可直接展示的错误文案（调用方据此中止，且**不得**删除任何数据库）。
    """
    try:
        cap_proc = await run_proc(
            [
                resolve_pg_tool('psql'), '-h', db_host, '-p', db_port, '-U', admin_user, '-d', 'postgres',
                '-t', '-A', '-c',
                'SELECT (rolsuper OR rolcreatedb)::text FROM pg_roles WHERE rolname = current_user;',
            ],
            env=admin_env, timeout=10,
        )
    except (TimeoutError, OSError, ValueError) as e:
        return f'恢复已中止：无法确认建库权限（{e}）'
    if cap_proc.returncode == 0 and (cap_proc.stdout or b'').decode(errors='replace').strip().lower() == 'true':
        return None
    cap_err = (cap_proc.stderr or b'').decode(errors='replace').strip()[:200]
    logger.error('建库权限预检未通过，恢复中止（未删除任何数据库）: user=%s err=%s', admin_user, cap_err)
    return (
        f'恢复已中止（旧库未被删除）：数据库用户 {admin_user} 缺少建库权限'
        '（既非超级用户也无 CREATEDB），或无法以该用户连接'
        '（如 PG_SUPER_PASSWORD 失效）。继续会导致「删库成功、建库失败」。'
        '请为该用户授予 CREATEDB，或核对 PG_SUPER_USER / PG_SUPER_PASSWORD 后重试。'
        f' {cap_err}'
    )


async def _rebuild_database_with_admin(
    *,
    db_host: str,
    db_port: str,
    admin_user: str,
    admin_env: dict,
    db_user: str,
    db_name: str,
) -> dict | None:
    """以管理员身份重建目标库（DROP + CREATE）。成功返回 None，失败返回错误 dict。

    关键安全属性：**DROP 之前必须先确认执行者具备建库权**。否则 DROP 成功而 CREATE 失败时，
    库会停在「已删未建」——这正是新机恢复丢库的直接原因（应用角色无 CREATEDB 而重建用它）。
    预检失败一律返回错误且**不删除**任何数据库。
    """
    cap_err_msg = await _admin_can_create_database(
        db_host=db_host, db_port=db_port, admin_user=admin_user, admin_env=admin_env,
    )
    if cap_err_msg is not None:
        return {'status': 'error', 'error': cap_err_msg}
    try:
        pg_major = 13
        try:
            ver_proc = await run_proc(
                [
                    resolve_pg_tool('psql'), '-h', db_host, '-p', db_port, '-U', admin_user, '-d', 'postgres', '-t', '-c',
                    'SHOW server_version;',
                ],
                env=admin_env, timeout=10,
            )
            if ver_proc.returncode == 0:
                ver_str = (ver_proc.stdout or b'').decode(errors='replace').strip()
                pg_major = int(ver_str.split('.')[0])
        except (TimeoutError, OSError, ValueError):
            pass  # defensive: 异常静默处理,不影响主流程
        if pg_major >= 13:
            drop_cmd = f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE);'
        else:
            drop_cmd = f'DROP DATABASE IF EXISTS "{db_name}";'
        drop_proc = await run_proc(
            [resolve_pg_tool('psql'), '-h', db_host, '-p', db_port, '-U', admin_user, '-d', 'postgres', '-c', drop_cmd],
            env=admin_env, timeout=60,
        )  # nosec
        if drop_proc.returncode != 0:
            # P0：DROP 失败必须中止——否则后续会向一个所有权/状态未知的目标库导入，
            # 单事务回滚后该库残留旧状态，"已整体回滚，当前为空库"的提示将不再成立。
            drop_err = (drop_proc.stderr or b'').decode(errors='replace')
            logger.error(f'DROP DATABASE 失败，恢复中止: {drop_err[:500]}')  # sql-safe: escape_like/绑定参数/常量片段
            return {
                'status': 'error',
                'error': f'删除旧数据库失败（恢复已中止，未触碰目标库）: {drop_err[:300]}',
            }
        create_proc = await run_proc(
            [
                resolve_pg_tool('psql'), '-h', db_host, '-p', db_port, '-U', admin_user, '-d', 'postgres', '-c',
                f'CREATE DATABASE "{db_name}" OWNER "{db_user}";',
            ],
            env=admin_env, timeout=30,
        )  # nosec
        if create_proc.returncode != 0:
            # P0：CREATE 失败同样必须中止，理由同上。
            create_err = (create_proc.stderr or b'').decode(errors='replace')
            logger.error(f'CREATE DATABASE 失败，恢复中止: {create_err[:500]}')  # sql-safe: escape_like/绑定参数/常量片段
            return {
                'status': 'error',
                'error': f'创建数据库失败（恢复已中止，旧库已被删除，请立即用 pre_restore 安全备份处理）: {create_err[:300]}',
            }
    except (TimeoutError, OSError, ValueError) as e:
        return {'status': 'error', 'error': f'数据库重建失败: {e}'}
    return None


class _CountingReader:
    """包装 ZIP 成员原始流，统计已消费的压缩字节数（进度分母）。

    gzip 解压流无法预知解压后总量，但已消费的压缩字节是单调递增的
    真实进度信号（compress_size 为分母），远优于按固定 1GB 估算。
    """

    def __init__(self, raw):
        self._raw = raw
        self.consumed = 0

    def read(self, size: int = -1) -> bytes:
        data = self._raw.read(size)
        self.consumed += len(data)
        return data

    def close(self) -> None:
        self._raw.close()


class _DumpStream(NamedTuple):
    """已打开的 dump 流及其进度分母。"""

    gz_stream: Any
    counter: _CountingReader
    first_chunk: bytes
    total_compressed: int


def _open_dump_stream(zf) -> _DumpStream | dict:
    """打开 database/dump.sql.gz 流并读首块。

    H4 流式还原：旧实现 zf.read + gzip.decompress 在内存中同时持有压缩与解压
    两份全量副本（峰值 ≈ dump.gz + dump.sql）；现打开 gzip 流，由 psql 导入
    线程边解压边写 stdin，峰值内存 ≈ 单个分块（256KB）。
    失败（读不出/空文件）返回可直接返回给调用方的 error dict。
    """
    try:
        total_compressed = zf.getinfo('database/dump.sql.gz').compress_size
    except KeyError:
        total_compressed = 0

    try:
        counter = _CountingReader(zf.open('database/dump.sql.gz'))
        # _CountingReader 只需实现 read()（gzip 只调用该方法）；mypy 按完整 IO[bytes] 协议要求
        gz_stream = gzip.GzipFile(fileobj=cast(IO[bytes], counter))
        first_chunk = gz_stream.read(256 * 1024)
    except (OSError, EOFError, KeyError) as e:
        return {'status': 'error', 'error': f'数据库备份文件读取失败: {e}'}
    if not first_chunk:
        gz_stream.close()
        return {'status': 'error', 'error': '数据库备份文件为空，无法恢复'}
    return _DumpStream(gz_stream, counter, first_chunk, total_compressed)


def _resolve_db_env() -> dict:
    """解析目标库连接参数与重建用管理员凭据。

    重建数据库（DROP/CREATE）需要建库权，而应用角色 erp_app 默认**没有** CREATEDB
    （新机安装脚本 deploy/install_package.ps1 建角色时即未授予；生产机是历史上手工建的
    角色才碰巧有）。此前重建用应用角色自身执行，该角色一旦无 CREATEDB 就必然
    「删库成功、建库失败」，库停在已删未建。故重建改用超级用户，应用角色只负责数据导入。
    """
    db_host = os.getenv('DB_HOST', 'localhost')
    db_port = os.getenv('DB_PORT', '5432')
    db_user = os.getenv('DB_USER', 'erp_app')
    db_name = os.getenv('DB_NAME', 'erp_system')
    if not db_name.isidentifier() or not all(c.isalnum() or c == '_' for c in db_name) or db_name[0].isdigit():
        raise ValueError(f'Invalid database name: {db_name!r}')
    db_password = os.getenv('DB_PASSWORD', '')
    env = os.environ.copy()
    env['PGPASSWORD'] = db_password

    admin_user, admin_password = _resolve_admin_credentials(db_user, db_password)
    admin_env = os.environ.copy()
    admin_env['PGPASSWORD'] = admin_password
    return {
        'db_host': db_host, 'db_port': db_port, 'db_user': db_user, 'db_name': db_name,
        'env': env, 'admin_user': admin_user, 'admin_env': admin_env,
    }


def _psql_import_worker(psql_args: list[str], env: dict, gz_stream, first_chunk: bytes,
                        state: dict, result: dict) -> None:
    """工作线程（同步）：边解压边分块写 stdin，排空 stdout/stderr 防管道死锁。"""

    def _drain(stream, sink: list) -> None:
        while True:
            chunk = stream.read(65536)
            if not chunk:
                break
            sink.append(chunk)

    try:
        proc_ = subprocess.Popen(  # 参数为白名单校验后的固定列表
            psql_args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, env=env,
        )
    except FileNotFoundError:
        result['no_psql'] = True
        return
    except OSError as e:
        result['spawn_error'] = str(e)
        return
    # stdin 为 PIPE，管道对象必然存在；mypy 无法从 Popen 构造参数推断
    stdin_pipe = cast(IO[bytes], proc_.stdin)
    out_chunks: list[bytes] = []
    err_chunks: list[bytes] = []
    t_out = threading.Thread(target=_drain, args=(proc_.stdout, out_chunks), daemon=True)
    t_err = threading.Thread(target=_drain, args=(proc_.stderr, err_chunks), daemon=True)
    t_out.start()
    t_err.start()
    try:
        try:
            stdin_pipe.write(first_chunk)
            state['written'] += len(first_chunk)
            while True:
                chunk = gz_stream.read(256 * 1024)
                if not chunk:
                    break
                stdin_pipe.write(chunk)
                state['written'] += len(chunk)
        except BrokenPipeError:
            pass  # psql 提前退出（如 SQL 致命错误），结果由 rc/stderr 判定
        except (OSError, EOFError) as e:
            result['stream_error'] = f'解压备份数据流失败: {e}'
        state['stream_done'] = True
        with contextlib.suppress(BrokenPipeError):
            stdin_pipe.close()
        try:
            proc_.wait(timeout=BACKUP_OPERATION_TIMEOUT)
            result['rc'] = proc_.returncode
        except subprocess.TimeoutExpired:
            proc_.kill()
            proc_.wait()
            result['timeout'] = True
            result['timeout_seconds'] = BACKUP_OPERATION_TIMEOUT
    finally:
        t_out.join(timeout=30)
        t_err.join(timeout=30)
        result['stderr'] = b''.join(err_chunks)


async def _await_psql_progress(worker, state: dict, counter: _CountingReader,
                               total_compressed: int, psql_start_time: float, _report) -> None:
    """主循环：等导入线程完成，期间按已消费压缩字节上报真实进度。"""
    import time as time_mod

    while worker.is_alive():
        await asyncio.sleep(2)
        elapsed = int(time_mod.monotonic() - psql_start_time)
        written_mb = state['written'] // 1024 // 1024
        if not state['stream_done']:
            if total_compressed:
                # WARN-2 修复：已消费压缩字节 / compress_size 为真实进度
                frac = min(1.0, counter.consumed / total_compressed)
                await _report(0.20 + 0.30 * frac,
                              f'写入数据 {int(frac * 100)}%（已解压 {written_mb}MB, {elapsed}s）')
            else:
                # 无压缩大小信息时退化为诚实的 MB 计数（不再伪造百分比）
                await _report(0.20 + 0.30 * min(1.0, written_mb / 1024),
                              f'写入数据 {written_mb}MB ({elapsed}s)')
        else:
            await _report(0.70, f'等待 psql 完成... ({elapsed}s)')
    worker.join()


async def _interpret_psql_result(result: dict, _report) -> dict:
    """把导入线程的原始结果翻译为 restore 的返回 dict。"""
    if result.get('no_psql'):
        return {'status': 'error', 'error': 'psql 命令未找到，请确保 PostgreSQL 客户端工具已安装'}
    if 'spawn_error' in result:
        return {'status': 'error', 'error': f"数据库恢复失败: {result['spawn_error']}"}
    if 'stream_error' in result:
        return {'status': 'error', 'error': result['stream_error']}
    if result.get('timeout'):
        timeout_seconds = result.get('timeout_seconds', BACKUP_OPERATION_TIMEOUT)
        return {
            'status': 'error',
            'message': f'数据库恢复超时（超过 {timeout_seconds} 秒），进程已终止',
            'recovery_hint': '可使用还原前安全备份（backups/server/pre_restore/pre_restore_*.zip）恢复原数据',
            'timeout_seconds': timeout_seconds,
        }

    stderr_text = (result.get('stderr') or b'').decode(errors='replace')
    error_count = stderr_text.lower().count('error:')
    await _report(0.95, '数据导入完成，验证结果')

    rc = result.get('rc')
    if rc != 0:
        # 单事务模式：导入已整体回滚，目标库为空库；旧数据在 DROP 阶段已被替换，
        # 需要用还原前安全备份（pre_restore_*）恢复——错误信息中明确指引用户
        logger.warning(f'psql restore failed (returncode={rc}): {stderr_text[:2000]}')  # sql-safe: escape_like/绑定参数/常量片段
        return {
            'status': 'error',
            'message': '数据库恢复失败（已整体回滚，当前为空库）',
            'errors': stderr_text[:2000],
            'recovery_hint': '可使用还原前安全备份（backups/server/pre_restore/pre_restore_*.zip）恢复原数据',
        }
    if error_count > 0:
        logger.warning(f'psql restore completed with {error_count} errors: {stderr_text[:2000]}')  # sql-safe: escape_like/绑定参数/常量片段
        return {'status': 'partial', 'message': f'数据库已恢复，但有 {error_count} 个语句执行失败', 'errors': stderr_text[:2000]}  # sql-safe: escape_like/绑定参数/常量片段
    return {'status': 'ok', 'message': '数据库恢复成功'}


async def _release_app_connections(db: AsyncSession, _report) -> None:
    """psql 前关闭应用数据库会话与连接池。"""
    await _report(0.02, '关闭应用数据库连接')
    await asyncio.sleep(0)
    try:
        await db.close()
    except (OSError, SQLAlchemyError):
        logger.warning('psql前关闭数据库会话失败')
    try:
        from fastapi_app.core.database import _async_engine
        if _async_engine is not None:
            await _async_engine.dispose()
    except (OSError, ValueError):
        logger.warning('psql前释放连接池失败')


async def _drain_and_terminate_connections(*, db_host: str, db_port: str, db_name: str,
                                           admin_user: str, admin_env: dict, _report) -> None:
    """等活跃连接释放（最多重试 3 次）后终止残留连接。"""
    await _report(0.06, '等待活跃连接释放')
    await asyncio.sleep(0)
    for _retry in range(3):
        await asyncio.sleep(1)
        try:
            check_proc = await run_proc(
                [
                    resolve_pg_tool('psql'), '-h', db_host, '-p', db_port, '-U', admin_user, '-d', 'postgres', '-t', '-A',
                    # 用字面量而非 :'db_name'：psql 的 -c 不做变量插值（实测直接语法错误），
                    # 旧写法让这两步恒失败并静默降级为「没有活跃连接」。db_name 已白名单校验。
                    '-c', f"SELECT COUNT(*) FROM pg_stat_activity WHERE datname = '{db_name}';",  # nosec B608 — db_name 经 isidentifier() 白名单校验
                ],
                env=admin_env, timeout=10,
            )
            if check_proc.returncode == 0:
                active_count = int((check_proc.stdout or b'').decode(errors='replace').strip() or '0')
                if active_count == 0:
                    break
                logger.warning(f'仍有 {active_count} 个活跃连接，重试 {_retry + 1}/3')
        except (TimeoutError, OSError, ValueError) as e:
            logger.warning(f'检查活跃连接失败: {e}，重试 {_retry + 1}/3')

    await _report(0.10, '终止残留数据库连接')
    await asyncio.sleep(0)
    try:
        term_proc = await run_proc(
            [
                resolve_pg_tool('psql'), '-h', db_host, '-p', db_port, '-U', admin_user, '-d', 'postgres',
                '-c', f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '{db_name}' AND pid <> pg_backend_pid();",  # nosec B608 — db_name 经 isidentifier() 白名单校验
            ],
            env=admin_env, timeout=30,
        )
        # 返回码此前被丢弃：终止失败会被静默吞掉，随后「重建数据库」以晦涩的 DROP 报错收场。
        if term_proc.returncode != 0:
            logger.warning(
                '终止现有连接返回非零: rc=%s, stderr=%s',
                term_proc.returncode,
                (term_proc.stderr or b'').decode(errors='replace').strip()[:200],
            )
    except (TimeoutError, OSError) as e:
        logger.warning(f'终止现有连接失败: {e}')


async def restore_database_via_psql(zf, db: AsyncSession, task_id: str | None = None) -> dict:
    """通过 psql 从 dump.sql.gz 恢复数据库（2026-10-11 复核 P2-14⑤ 拆分）。"""
    import time as time_mod

    from fastapi_app.core.backup_progress import update_progress as _upd_prog

    async def _report(sub: float, detail: str):
        if task_id:
            await _upd_prog(task_id, 'restore_db', sub, detail)

    # H4 流式还原：打开 gzip 流，由 psql 导入线程边解压边写 stdin，
    # 峰值内存 ≈ 单个分块（256KB），不再同时持有压缩与解压两份全量副本。
    await _report(0.0, '读取备份文件...')
    await asyncio.sleep(0)  # 让出控制权，确保前端能收到更新

    opened = _open_dump_stream(zf)
    if isinstance(opened, dict):
        return opened
    gz_stream, counter, first_chunk, total_compressed = opened

    await _report(0.015, '解压并准备恢复...')  # sql-safe: escape_like/绑定参数/常量片段
    await asyncio.sleep(0)

    cfg = _resolve_db_env()
    db_host, db_port, db_user, db_name = cfg['db_host'], cfg['db_port'], cfg['db_user'], cfg['db_name']

    await _release_app_connections(db, _report)
    await _drain_and_terminate_connections(
        db_host=db_host, db_port=db_port, db_name=db_name,
        admin_user=cfg['admin_user'], admin_env=cfg['admin_env'], _report=_report,
    )

    await _report(0.14, '重建数据库')
    await asyncio.sleep(0)
    # P0-5：DROP 之前落中断标记。导入结束（无论成败）在 finally 里清除；
    # 若进程在两者之间被杀，标记会留到下次启动，由 main.lifespan 打 CRITICAL
    # 并给出 pre_restore 回滚指引（见 restore_guard）。
    from fastapi_app.services.backup.restore_guard import (
        mark_restore_finished,
        mark_restore_started,
    )

    mark_restore_started(db_name, task_id)
    try:
        rebuild_err = await _rebuild_database_with_admin(
            db_host=db_host, db_port=db_port, admin_user=cfg['admin_user'], admin_env=cfg['admin_env'],
            db_user=db_user, db_name=db_name,
        )
        if rebuild_err is not None:
            # 重建失败直接返回时不会进入下面的导入 try/finally，显式关流避免句柄泄漏
            gz_stream.close()
            return rebuild_err

        psql_start_time = time_mod.monotonic()
        try:
            await _report(0.20, '开始导入数据库数据')
            await asyncio.sleep(0)
            # P0-5: 单事务导入 + 遇错即停——任一语句失败则整体回滚，不再产生
            # 半还原态数据库（旧实现 ON_ERROR_STOP=0 会吞错继续，残留部分表数据）。
            psql_args = [
                resolve_pg_tool('psql'), '-h', db_host, '-p', db_port, '-U', db_user, '-d', db_name,
                '--single-transaction',
                '-v', 'ON_ERROR_STOP=1',
            ]
            state: dict = {'written': 0, 'stream_done': False}
            result: dict = {}
            worker = threading.Thread(
                target=_psql_import_worker,
                args=(psql_args, cfg['env'], gz_stream, first_chunk, state, result),
                daemon=True,
            )
            worker.start()
            try:
                await _await_psql_progress(worker, state, counter, total_compressed, psql_start_time, _report)
            finally:
                gz_stream.close()
            return await _interpret_psql_result(result, _report)
        except (TimeoutError, OSError, ValueError) as e:
            return {'status': 'error', 'error': f'数据库恢复失败: {e}'}
    finally:
        mark_restore_finished()
