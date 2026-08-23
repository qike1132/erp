"""pg_dump/psql 恢复。"""
from __future__ import annotations

import asyncio
import gzip
import logging
import os
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from .snapshot import get_pg_version

logger = logging.getLogger(__name__)


async def run_pg_dump(output_path: Path, snapshot_id: str | None = None) -> dict:
    """执行 pg_dump 导出数据库为 gzip 压缩 SQL

    Args:
        output_path: 输出文件路径
        snapshot_id: 可选，PostgreSQL 快照 ID，用于一致性备份

    Returns: dict with pg_version, db_name, dump_size, duration_seconds, snapshot_id
    """
    import time
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
            'pg_dump', '-h', db_host, '-p', db_port, '-U', db_user, '-d', db_name,
            '--no-owner', '--no-privileges'
        ]

        # 如果提供了快照 ID，使用 --snapshot 参数
        if snapshot_id:
            pg_dump_args.extend(['--snapshot', snapshot_id])
            logger.info(f"使用数据库快照 {snapshot_id} 进行备份")

        proc = await asyncio.create_subprocess_exec(
            *pg_dump_args,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env
        )
        gzip_proc = await asyncio.create_subprocess_exec(
            'gzip', '-1', stdin=proc.stdout,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await gzip_proc.communicate()
        await proc.wait()
        if proc.returncode != 0:
            stderr_data = await proc.stderr.read() if proc.stderr else b''
            raise RuntimeError(f"pg_dump failed (rc={proc.returncode}): {stderr_data.decode(errors='replace')}")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(stdout)
        duration = time.monotonic() - start
        return {
            'pg_version': await get_pg_version(db_host, db_port, db_user, db_password, env),
            'db_name': db_name,
            'dump_size': len(stdout),
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

    # 分步读取和解压，添加进度报告
    await _report(0.0, '读取备份文件...')
    await asyncio.sleep(0)  # 让出控制权，确保前端能收到更新

    # 获取压缩文件大小用于进度计算
    try:
        info = zf.getinfo('database/dump.sql.gz')
        compressed_size = info.file_size
    except KeyError:
        compressed_size = 0

    # 读取压缩数据
    await _report(0.005, f'读取压缩数据 ({compressed_size // 1024 // 1024}MB)...')
    await asyncio.sleep(0)
    dump_gz = zf.read('database/dump.sql.gz')

    # 解压数据
    await _report(0.01, '解压数据库备份...')
    await asyncio.sleep(0)
    dump_sql = gzip.decompress(dump_gz)
    del dump_gz  # 释放压缩数据内存

    if not dump_sql or not dump_sql.strip():
        return {'status': 'error', 'error': '数据库备份文件为空，无法恢复'}

    sql_size_mb = len(dump_sql) // 1024 // 1024
    await _report(0.015, f'解压完成 ({sql_size_mb}MB)，准备恢复...')  # sql-safe: escape_like/绑定参数/常量片段
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
            check_proc = await asyncio.create_subprocess_exec(
                'psql', '-h', db_host, '-p', db_port, '-U', db_user, '-d', 'postgres', '-t', '-c',
                f"SELECT COUNT(*) FROM pg_stat_activity WHERE datname = '{db_name}';",  # nosec B608 — db_name 经 isidentifier() 白名单校验
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env
            )
            try:
                check_stdout, _ = await asyncio.wait_for(check_proc.communicate(), timeout=10)
            except TimeoutError:
                check_proc.kill()
                await check_proc.wait()
                logger.warning(f'检查活跃连接超时，重试 {_retry + 1}/3')
                continue
            if check_proc.returncode == 0:
                active_count = int(check_stdout.decode(errors='replace').strip() or '0')
                if active_count == 0:
                    break
                logger.warning(f'仍有 {active_count} 个活跃连接，重试 {_retry + 1}/3')
        except (TimeoutError, OSError, ValueError) as e:
            logger.warning(f'检查活跃连接失败: {e}，重试 {_retry + 1}/3')

    await _report(0.10, '终止残留数据库连接')
    await asyncio.sleep(0)
    try:
        term_proc = await asyncio.create_subprocess_exec(
            'psql', '-h', db_host, '-p', db_port, '-U', db_user, '-d', 'postgres', '-c',
            f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '{db_name}' AND pid <> pg_backend_pid();",  # nosec B608 — db_name 经 isidentifier() 白名单校验
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env
        )
        try:
            await asyncio.wait_for(term_proc.wait(), timeout=30)
        except TimeoutError:
            term_proc.kill()
            await term_proc.wait()
            logger.warning('终止连接超时，已强制终止')
    except (TimeoutError, OSError, ValueError) as e:
        logger.warning(f'终止现有连接失败: {e}')

    await _report(0.14, '重建数据库')
    await asyncio.sleep(0)
    try:
        pg_major = 13
        try:
            ver_proc = await asyncio.create_subprocess_exec(
                'psql', '-h', db_host, '-p', db_port, '-U', db_user, '-d', 'postgres', '-t', '-c',
                'SHOW server_version;',
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env
            )
            try:
                ver_stdout, _ = await asyncio.wait_for(ver_proc.communicate(), timeout=10)
            except TimeoutError:
                ver_proc.kill()
                await ver_proc.wait()
                ver_stdout = b''
            if ver_proc.returncode == 0:
                ver_str = ver_stdout.decode(errors='replace').strip()
                pg_major = int(ver_str.split('.')[0])
        except (TimeoutError, OSError, ValueError):
            pass  # defensive: 异常静默处理,不影响主流程
        if pg_major >= 13:
            drop_cmd = f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE);'
        else:
            drop_cmd = f'DROP DATABASE IF EXISTS "{db_name}";'
        drop_proc = await asyncio.create_subprocess_exec(
            'psql', '-h', db_host, '-p', db_port, '-U', db_user, '-d', 'postgres', '-c', drop_cmd,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env
        )
        try:
            _, stderr = await asyncio.wait_for(drop_proc.communicate(), timeout=60)
        except TimeoutError:
            drop_proc.kill()
            await drop_proc.wait()
            logger.warning('DROP DATABASE 超时')
            stderr = b'Timeout'
        if drop_proc.returncode != 0:
            logger.warning(f"DROP DATABASE: {stderr.decode(errors='replace')}")
        create_proc = await asyncio.create_subprocess_exec(
            'psql', '-h', db_host, '-p', db_port, '-U', db_user, '-d', 'postgres', '-c',
            f'CREATE DATABASE "{db_name}" OWNER "{db_user}";',
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env
        )  # nosec
        try:
            _, stderr = await asyncio.wait_for(create_proc.communicate(), timeout=30)
        except TimeoutError:
            create_proc.kill()
            await create_proc.wait()
            logger.warning('CREATE DATABASE 超时')
            stderr = b'Timeout'
        if create_proc.returncode != 0:
            logger.warning(f"CREATE DATABASE: {stderr.decode(errors='replace')}")  # nosec
    except (TimeoutError, OSError, ValueError) as e:
        return {'status': 'error', 'error': f'数据库重建失败: {e}'}

    psql_start_time = time_mod.monotonic()

    try:
        await _report(0.20, '开始导入数据库数据')
        await asyncio.sleep(0)
        # P0-5: 单事务导入 + 遇错即停——任一语句失败则整体回滚，不再产生
        # 半还原态数据库（旧实现 ON_ERROR_STOP=0 会吞错继续，残留部分表数据）。
        proc = await asyncio.create_subprocess_exec(
            'psql', '-h', db_host, '-p', db_port, '-U', db_user, '-d', db_name,
            '--single-transaction',
            '-v', 'ON_ERROR_STOP=1',
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, env=env
        )
        try:
            total_size = len(dump_sql)
            written = 0
            chunk_size = 256 * 1024

            async def _write_stdin():
                nonlocal written
                while written < total_size:
                    end = min(written + chunk_size, total_size)
                    proc.stdin.write(dump_sql[written:end])
                    await proc.stdin.drain()
                    written = end
                    sub = 0.20 + 0.30 * (written / total_size)
                    elapsed = int(time_mod.monotonic() - psql_start_time)
                    await _report(sub, f'写入数据 {written * 100 // total_size}% ({elapsed}s)')
                proc.stdin.close()

            async def _read_stream(stream, chunks):
                while True:
                    chunk = await stream.read(65536)
                    if not chunk:
                        break
                    chunks.append(chunk)

            stdout_chunks = []
            stderr_chunks = []
            write_task = asyncio.create_task(_write_stdin())
            read_out_task = asyncio.create_task(_read_stream(proc.stdout, stdout_chunks))
            read_err_task = asyncio.create_task(_read_stream(proc.stderr, stderr_chunks))

            await asyncio.wait_for(write_task, timeout=600)

            while not read_out_task.done() or not read_err_task.done():
                await asyncio.sleep(2)
                elapsed = int(time_mod.monotonic() - psql_start_time)
                await _report(0.70, f'等待 psql 完成... ({elapsed}s)')  # sql-safe: escape_like/绑定参数/常量片段

            await asyncio.wait_for(asyncio.gather(read_out_task, read_err_task), timeout=600)
            await proc.wait()

            b''.join(stdout_chunks)
            stderr = b''.join(stderr_chunks)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            return {'status': 'error', 'error': '数据库恢复超时（超过 600 秒），进程已终止'}

        stderr_text = stderr.decode(errors='replace')
        error_count = stderr_text.lower().count('error:')
        await _report(0.95, '数据导入完成，验证结果')

        if proc.returncode != 0:
            # 单事务模式：导入已整体回滚，目标库为空库；旧数据在 DROP 阶段已被替换，
            # 需要用还原前安全备份（pre_restore_*）恢复——错误信息中明确指引用户
            logger.warning(f'psql restore failed (returncode={proc.returncode}): {stderr_text[:2000]}')  # sql-safe: escape_like/绑定参数/常量片段
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
    except FileNotFoundError:
        return {'status': 'error', 'error': 'psql 命令未找到，请确保 PostgreSQL 客户端工具已安装'}
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
