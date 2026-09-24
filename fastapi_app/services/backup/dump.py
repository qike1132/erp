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
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ._proc import run_proc
from .snapshot import get_pg_version

logger = logging.getLogger(__name__)

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

            def _drain_err() -> None:
                while True:
                    chunk = proc_.stderr.read(65536)
                    if not chunk:
                        break
                    stderr_chunks.append(chunk)

            t_err = threading.Thread(target=_drain_err, daemon=True)
            t_err.start()
            try:
                with open(output_path, 'wb') as raw_f, gzip.GzipFile(
                    fileobj=raw_f, mode='wb', compresslevel=1,
                ) as gz_f:
                    while True:
                        chunk = proc_.stdout.read(1024 * 1024)
                        if not chunk:
                            break
                        gz_f.write(chunk)
                proc_.stdout.close()
                proc_.wait()
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
                t_err.join(timeout=30)
                proc_.stderr.close()

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


async def restore_database_via_psql(zf, db: AsyncSession, task_id: str | None = None) -> dict:
    """通过 psql 从 dump.sql.gz 恢复数据库"""
    import time as time_mod

    from fastapi_app.core.backup_progress import update_progress as _upd_prog

    async def _report(sub: float, detail: str):
        if task_id:
            await _upd_prog(task_id, 'restore_db', sub, detail)

    # H4 流式还原：旧实现 zf.read + gzip.decompress 在内存中同时持有压缩与解压
    # 两份全量副本（峰值 ≈ dump.gz + dump.sql）；现打开 gzip 流，由 psql 导入
    # 线程边解压边写 stdin，峰值内存 ≈ 单个分块（256KB）。
    await _report(0.0, '读取备份文件...')
    await asyncio.sleep(0)  # 让出控制权，确保前端能收到更新

    try:
        total_compressed = zf.getinfo('database/dump.sql.gz').compress_size
    except KeyError:
        total_compressed = 0

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

    try:
        counter = _CountingReader(zf.open('database/dump.sql.gz'))
        gz_stream = gzip.GzipFile(fileobj=counter)
        first_chunk = gz_stream.read(256 * 1024)
    except (OSError, EOFError, KeyError) as e:
        return {'status': 'error', 'error': f'数据库备份文件读取失败: {e}'}
    if not first_chunk:
        gz_stream.close()
        return {'status': 'error', 'error': '数据库备份文件为空，无法恢复'}

    await _report(0.015, '解压并准备恢复...')  # sql-safe: escape_like/绑定参数/常量片段
    await asyncio.sleep(0)

    db_host = os.getenv('DB_HOST', 'localhost')
    db_port = os.getenv('DB_PORT', '5432')
    db_user = os.getenv('DB_USER', 'erp_app')
    db_name = os.getenv('DB_NAME', 'erp_system')
    if not db_name.isidentifier() or not all(c.isalnum() or c == '_' for c in db_name) or db_name[0].isdigit():
        raise ValueError(f'Invalid database name: {db_name!r}')
    db_password = os.getenv('DB_PASSWORD', '')
    env = os.environ.copy()
    env['PGPASSWORD'] = db_password

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

    await _report(0.06, '等待活跃连接释放')
    await asyncio.sleep(0)
    for _retry in range(3):
        await asyncio.sleep(1)
        try:
            check_proc = await run_proc(
                [
                    resolve_pg_tool('psql'), '-h', db_host, '-p', db_port, '-U', db_user, '-d', 'postgres', '-t',
                    '-v', f'db_name={db_name}',
                    '-c', "SELECT COUNT(*) FROM pg_stat_activity WHERE datname = :'db_name';",  # nosec B608 — db_name 经 isidentifier() 白名单校验，psql 变量引用自动转义
                ],
                env=env, timeout=10,
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
                resolve_pg_tool('psql'), '-h', db_host, '-p', db_port, '-U', db_user, '-d', 'postgres',
                '-v', f'db_name={db_name}',
                '-c', "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = :'db_name' AND pid <> pg_backend_pid();",  # nosec B608 — db_name 经 isidentifier() 白名单校验，psql 变量引用自动转义
            ],
            env=env, timeout=30,
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

    await _report(0.14, '重建数据库')
    await asyncio.sleep(0)
    try:
        pg_major = 13
        try:
            ver_proc = await run_proc(
                [
                    resolve_pg_tool('psql'), '-h', db_host, '-p', db_port, '-U', db_user, '-d', 'postgres', '-t', '-c',
                    'SHOW server_version;',
                ],
                env=env, timeout=10,
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
            [resolve_pg_tool('psql'), '-h', db_host, '-p', db_port, '-U', db_user, '-d', 'postgres', '-c', drop_cmd],
            env=env, timeout=60,
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
                resolve_pg_tool('psql'), '-h', db_host, '-p', db_port, '-U', db_user, '-d', 'postgres', '-c',
                f'CREATE DATABASE "{db_name}" OWNER "{db_user}";',
            ],
            env=env, timeout=30,
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

        def _drain(stream, sink: list) -> None:
            while True:
                chunk = stream.read(65536)
                if not chunk:
                    break
                sink.append(chunk)

        def _psql_import() -> None:
            """工作线程：边解压边分块写 stdin，排空 stdout/stderr 防管道死锁。"""
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
            out_chunks: list[bytes] = []
            err_chunks: list[bytes] = []
            t_out = threading.Thread(target=_drain, args=(proc_.stdout, out_chunks), daemon=True)
            t_err = threading.Thread(target=_drain, args=(proc_.stderr, err_chunks), daemon=True)
            t_out.start()
            t_err.start()
            try:
                try:
                    proc_.stdin.write(first_chunk)
                    state['written'] += len(first_chunk)
                    while True:
                        chunk = gz_stream.read(256 * 1024)
                        if not chunk:
                            break
                        proc_.stdin.write(chunk)
                        state['written'] += len(chunk)
                except BrokenPipeError:
                    pass  # psql 提前退出（如 SQL 致命错误），结果由 rc/stderr 判定
                except (OSError, EOFError) as e:
                    result['stream_error'] = f'解压备份数据流失败: {e}'
                state['stream_done'] = True
                with contextlib.suppress(BrokenPipeError):
                    proc_.stdin.close()
                try:
                    proc_.wait(timeout=600)
                    result['rc'] = proc_.returncode
                except subprocess.TimeoutExpired:
                    proc_.kill()
                    proc_.wait()
                    result['timeout'] = True
            finally:
                t_out.join(timeout=30)
                t_err.join(timeout=30)
                result['stderr'] = b''.join(err_chunks)

        worker = threading.Thread(target=_psql_import, daemon=True)
        worker.start()
        try:
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
        finally:
            gz_stream.close()

        if result.get('no_psql'):
            return {'status': 'error', 'error': 'psql 命令未找到，请确保 PostgreSQL 客户端工具已安装'}
        if 'spawn_error' in result:
            return {'status': 'error', 'error': f"数据库恢复失败: {result['spawn_error']}"}
        if 'stream_error' in result:
            return {'status': 'error', 'error': result['stream_error']}
        if result.get('timeout'):
            return {'status': 'error', 'error': '数据库恢复超时（超过 600 秒），进程已终止'}

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
    except (TimeoutError, OSError, ValueError) as e:
        return {'status': 'error', 'error': f'数据库恢复失败: {e}'}


async def restore_database_via_psql_from_bytes(zip_bytes: bytes, db: AsyncSession) -> dict:
    """从 ZIP bytes 恢复数据库（用于安全备份回滚）"""
    import io
    import zipfile
    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile:
        return {'status': 'error', 'error': '无效的 ZIP 备份文件'}
    if 'database/dump.sql.gz' not in zf.namelist():
        return {'status': 'error', 'error': '安全备份中无 database/dump.sql.gz'}
    return await restore_database_via_psql(zf, db)
