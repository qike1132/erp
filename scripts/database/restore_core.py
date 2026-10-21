"""PostgreSQL 恢复的**单一实现**（审计 F1-7）。

背景
----
`scripts/database/restore_db.py` 与 `scripts/database/db_manager.py` 各自持有一套
恢复实现（恢复前备份 → 终止连接 → DROP/CREATE → psql 导入 → 判定成败），
两边**互不调用**：任何修复只会落在一侧，漏到另一侧时没人发现。P1-34
（恢复假成功 + 无恢复前备份）就是这么漏的 —— db_manager 侧有「恢复后表数校验」，
restore_db 侧没有；db_manager 侧有写生产库护栏，restore_db 侧没有。

本模块把**会写生产库的那一段**收敛成唯一实现；两个 CLI 只负责「准备输入、
调用本模块、汇报结果」。要改恢复行为，只改这里。

不可协商的四条
--------------
1. **恢复前备份 fail-closed**：DROP DATABASE 之前必须先有一份非空 pg_dump 产物，
   否则中止 —— 这是唯一的回退手段。
2. **psql 一律 ON_ERROR_STOP=1**：该选项为 0 时 SQL 错误**不会**让 psql 返回
   非零退出码，失败判定会假绿。
3. **恢复后校验落地**：psql 退出码为 0 不代表数据真的进去了（dump 本身可能是
   空的），必须查 public schema 的表数，为 0 判失败。
4. **写生产库需显式授权**：统一走 `scripts/_prod_write_guard`。
"""
from __future__ import annotations

import gzip
import os
import subprocess
import sys
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

# scripts/ 下的 _prod_write_guard（本模块位于 scripts/database/）
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _prod_write_guard import require_prod_write_consent

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PRE_RESTORE_DIR = PROJECT_ROOT / 'backups' / 'pre_restore'

PSQL_TIMEOUT = 600
PG_DUMP_TIMEOUT = 3600


class RestoreError(RuntimeError):
    """恢复流程无法继续（调用方应中止并汇报失败）。"""


class UnsupportedBackupFormatError(RestoreError):
    """备份文件格式不支持命令行恢复。"""


@dataclass(frozen=True)
class RestoreOutcome:
    """一次恢复的结果。``ok=False`` 时 ``message`` 是可直接展示给运维的失败原因。"""

    ok: bool
    message: str
    pre_backup: Path | None = None
    table_count: int = 0


def db_config() -> dict[str, str]:
    """目标库连接参数（每次调用现读 env，改 .env 后立即生效）。"""
    return {
        'host': os.getenv('DB_HOST', 'localhost'),
        'port': os.getenv('DB_PORT', '5432'),
        'user': os.getenv('DB_USER', 'erp_app'),
        'password': os.getenv('DB_PASSWORD', ''),
        'database': os.getenv('DB_NAME', 'erp_system'),
    }


def _psql_env(config: dict[str, str]) -> dict[str, str]:
    env = os.environ.copy()
    env['PGPASSWORD'] = config['password']
    return env


def require_restore_consent(action: str = '数据库恢复', *, hint: str = '') -> None:
    """写生产库的显式授权（统一护栏）。未授权 → SystemExit(3)。"""
    require_prod_write_consent(action, hint=hint)


def create_pre_restore_backup(
    config: dict[str, str] | None = None,
    *,
    out_dir: Path | None = None,
    log: Callable[[str], None] = print,
) -> Path:
    """DROP DATABASE 之前唯一的回退手段；失败必须抛错（由调用方决定是否中止）。"""
    config = config or db_config()
    out_dir = out_dir or PRE_RESTORE_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    out = out_dir / f'restore_pre_{stamp}.dump'
    try:
        result = subprocess.run(
            ['pg_dump', '-h', config['host'], '-p', config['port'], '-U', config['user'],
             '-d', config['database'], '-Fc', '-f', str(out)],
            env=_psql_env(config), capture_output=True, timeout=PG_DUMP_TIMEOUT,
        )
    except FileNotFoundError as e:
        raise RestoreError('pg_dump 命令未找到，请确保 PostgreSQL 客户端工具在 PATH 中') from e
    except subprocess.TimeoutExpired as e:
        raise RestoreError(f'pg_dump 执行超时（超过 {PG_DUMP_TIMEOUT} 秒）') from e
    if result.returncode != 0:
        detail = result.stderr.decode(errors='replace')[:500] if result.stderr else ''
        raise RestoreError(f'pg_dump 失败: {detail}')
    if not out.exists() or out.stat().st_size == 0:
        raise RestoreError('pg_dump 产物为空，恢复前备份不可用')
    log(f'  恢复前备份完成: {out}')
    return out


def terminate_connections(
    config: dict[str, str] | None = None,
    *,
    log: Callable[[str], None] = print,
) -> None:
    """踢掉连着目标库的会话（否则 DROP DATABASE 会被占住）。失败不致命，仅告警。"""
    config = config or db_config()
    try:
        subprocess.run(
            ['psql', '-h', config['host'], '-p', config['port'], '-U', config['user'],
             '-d', 'postgres', '-c',
             f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
             f"WHERE datname = '{config['database']}' AND pid <> pg_backend_pid();"],
            env=_psql_env(config), capture_output=True, timeout=30,
        )
    except Exception as e:  # defensive: 连不上不影响后续 DROP 的错误判定
        log(f'  终止连接时出现警告: {e}')


def drop_and_recreate_db(
    config: dict[str, str] | None = None,
    *,
    log: Callable[[str], None] = print,
) -> None:
    """重建目标库。旧版 PG 不支持 WITH (FORCE) 时回退到普通 DROP。"""
    config = config or db_config()
    env = _psql_env(config)
    base = ['psql', '-h', config['host'], '-p', config['port'], '-U', config['user'], '-d', 'postgres']
    try:
        subprocess.run(
            [*base, '-c', f'DROP DATABASE IF EXISTS "{config["database"]}" WITH (FORCE);'],
            env=env, capture_output=True, check=True, timeout=30,
        )
    except subprocess.CalledProcessError:
        subprocess.run(
            [*base, '-c', f'DROP DATABASE IF EXISTS "{config["database"]}";'],
            env=env, capture_output=True, check=True, timeout=30,
        )
    subprocess.run(
        [*base, '-c', f'CREATE DATABASE "{config["database"]}" OWNER "{config["user"]}";'],
        env=env, capture_output=True, check=True, timeout=30,
    )
    log(f'  数据库已重建: {config["database"]}')


def _psql_restore(
    config: dict[str, str],
    *,
    sql_path: Path | None = None,
    sql_bytes: bytes | None = None,
) -> subprocess.CompletedProcess:
    """执行 psql 导入。ON_ERROR_STOP=1 是硬要求（见模块 docstring 第 2 条）。"""
    cmd = ['psql', '-h', config['host'], '-p', config['port'], '-U', config['user'],
           '-d', config['database'], '-v', 'ON_ERROR_STOP=1']
    env = _psql_env(config)
    if sql_path is not None:
        with open(sql_path, 'rb') as f:
            return subprocess.run(cmd, stdin=f, capture_output=True, env=env, timeout=PSQL_TIMEOUT)
    return subprocess.run(cmd, input=sql_bytes, capture_output=True, env=env, timeout=PSQL_TIMEOUT)


def _error_lines(stderr_text: str) -> list[str]:
    """psql stderr 里的真错误行。

    `already exists` 排除：恢复进刚建好的空库时，扩展/默认对象可能已存在，
    属于可预期的噪音，不是失败。
    """
    return [
        line for line in stderr_text.split('\n')
        if ('ERROR:' in line or line.strip().startswith('ERROR'))
        and 'already exists' not in line.lower()
    ]


def count_public_tables(config: dict[str, str] | None = None) -> int:
    """恢复后落地校验：public schema 的表数（0 = 数据没进去）。"""
    config = config or db_config()
    result = subprocess.run(
        ['psql', '-h', config['host'], '-p', config['port'], '-U', config['user'],
         '-d', config['database'], '-tAc',
         "SELECT count(*) FROM information_schema.tables WHERE table_schema='public';"],
        env=_psql_env(config), capture_output=True, timeout=30,
    )
    raw = result.stdout.decode('utf-8', errors='replace').strip() if result.stdout else ''
    return int(raw) if raw.isdigit() else 0


def read_backup_sql(path: Path) -> bytes:
    """把备份文件读成 SQL 字节流（.sql / .sql.gz / .zip 里的 database/dump.sql.gz）。"""
    suffix = path.suffix.lower()
    if suffix == '.sql':
        return path.read_bytes()
    if suffix == '.gz':
        with gzip.open(path, 'rb') as f:
            return f.read()
    if suffix == '.zip':
        with zipfile.ZipFile(path, 'r') as zf:
            names = zf.namelist()
            if 'database/dump.sql.gz' in names:
                return gzip.decompress(zf.read('database/dump.sql.gz'))
            if 'database/dump.json' in names:
                raise UnsupportedBackupFormatError(
                    'ZIP 内是 JSON 格式导出，不支持命令行恢复，请使用 Web 界面'
                )
            raise UnsupportedBackupFormatError('ZIP 文件中未找到数据库导出')
    raise UnsupportedBackupFormatError(f'不支持的文件类型: {suffix}')


def restore_postgres(
    *,
    config: dict[str, str] | None = None,
    sql_path: Path | None = None,
    sql_bytes: bytes | None = None,
    allow_missing_pre_backup: bool = False,
    require_consent: bool = True,
    log: Callable[[str], None] = print,
) -> RestoreOutcome:
    """执行一次 PostgreSQL 恢复（唯一实现）。

    Args:
        sql_path: 明文 .sql 文件路径（走 stdin 流式导入，大文件不撑内存）。
        sql_bytes: 已读入内存的 SQL（.gz/.zip 解压后的内容）。
        allow_missing_pre_backup: 恢复前备份失败时是否仍然继续（默认否 —— fail-closed）。
        require_consent: 是否先取写生产库的显式授权（CLI 已在更外层取过时传 False）。
    """
    if sql_path is None and sql_bytes is None:
        raise RestoreError('恢复内容缺失：既没有 sql_path 也没有 sql_bytes')
    config = config or db_config()

    if require_consent:
        require_restore_consent(
            f'数据库恢复（{config["host"]}:{config["port"]}/{config["database"]}）',
            hint='不可逆；请先确认已备份当前库',
        )

    pre_backup: Path | None = None
    try:
        pre_backup = create_pre_restore_backup(config, log=log)
    except RestoreError as e:
        if not allow_missing_pre_backup:
            return RestoreOutcome(
                ok=False,
                message=f'恢复前备份失败，已中止恢复以避免数据丢失: {e}',
            )
        log(f'  警告: 恢复前备份失败，但已显式允许继续恢复: {e}')

    terminate_connections(config, log=log)
    try:
        drop_and_recreate_db(config, log=log)
    except subprocess.CalledProcessError as e:
        detail = e.stderr.decode(errors='replace') if e.stderr else str(e)
        return RestoreOutcome(ok=False, message=f'数据库重建失败: {detail}', pre_backup=pre_backup)

    log('  正在恢复数据...')
    try:
        result = _psql_restore(config, sql_path=sql_path, sql_bytes=sql_bytes)
    except subprocess.TimeoutExpired:
        return RestoreOutcome(
            ok=False,
            message=f'数据库恢复超时（超过 {PSQL_TIMEOUT} 秒），'
                    f'可用恢复前备份回滚: {pre_backup}',
            pre_backup=pre_backup,
        )
    except FileNotFoundError:
        return RestoreOutcome(ok=False, message='psql 命令未找到，请确保 PostgreSQL 客户端工具已安装',
                              pre_backup=pre_backup)

    stderr_text = result.stderr.decode('utf-8', errors='replace') if result.stderr else ''
    error_lines = _error_lines(stderr_text)
    # 失败判定只看退出码（合并前审查 H3）：ON_ERROR_STOP=1 下真错误必然令
    # psql 非零退出；而退出码 0 时 stderr 里的 ERROR 行几乎都是非致命噪音
    # （`must be owner of`、`role ... does not exist`、扩展/权限类）。此前
    # 「有 ERROR 行即判失败」会把恢复成功报成失败并提示回滚，事故现场极易
    # 诱导运维对一个好库做破坏性重放。
    if result.returncode != 0:
        detail = error_lines[0].strip() if error_lines else stderr_text.strip()[:200]
        for line in error_lines[1:10]:
            log(f'    {line.strip()}')
        return RestoreOutcome(
            ok=False,
            message=f'PostgreSQL 恢复失败（psql 退出码={result.returncode}，'
                    f'错误行数={len(error_lines)}）: {detail}；'
                    f'可用恢复前备份回滚: {pre_backup}',
            pre_backup=pre_backup,
        )
    if error_lines:
        for line in error_lines[:10]:
            log(f'  [警告] stderr 含非致命错误行（已忽略）: {line.strip()}')

    # 落地校验：退出码 0 不代表数据真的进去了（dump 本身可能是空的）
    table_count = count_public_tables(config)
    if table_count == 0:
        return RestoreOutcome(
            ok=False,
            message=f'PostgreSQL 恢复后 public schema 无任何表，疑似恢复失败；'
                    f'可用恢复前备份回滚: {pre_backup}',
            pre_backup=pre_backup,
        )

    return RestoreOutcome(
        ok=True,
        message=f'PostgreSQL 数据库恢复完成（public schema 表数={table_count}）',
        pre_backup=pre_backup,
        table_count=table_count,
    )


def restore_from_file(
    path: Path,
    *,
    config: dict[str, str] | None = None,
    allow_missing_pre_backup: bool = False,
    require_consent: bool = True,
    log: Callable[[str], None] = print,
) -> RestoreOutcome:
    """从备份文件恢复（.sql 走流式 stdin，.gz/.zip 解压后走内存）。"""
    path = Path(path)
    if path.suffix.lower() == '.sql':
        return restore_postgres(
            config=config, sql_path=path,
            allow_missing_pre_backup=allow_missing_pre_backup,
            require_consent=require_consent, log=log,
        )
    return restore_postgres(
        config=config, sql_bytes=read_backup_sql(path),
        allow_missing_pre_backup=allow_missing_pre_backup,
        require_consent=require_consent, log=log,
    )


__all__ = [
    'PRE_RESTORE_DIR',
    'RestoreError',
    'RestoreOutcome',
    'UnsupportedBackupFormatError',
    'count_public_tables',
    'create_pre_restore_backup',
    'db_config',
    'drop_and_recreate_db',
    'read_backup_sql',
    'require_restore_consent',
    'restore_from_file',
    'restore_postgres',
    'terminate_connections',
]
