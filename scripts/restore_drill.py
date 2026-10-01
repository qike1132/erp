"""恢复演练：把最新全量备份恢复到 erp_system_drill，验证备份 artifact 真实可恢复。

复用生产恢复函数 restore_database_via_psql —— 演练的就是灾难发生时会走的那条代码路径。
通过给子进程环境设置 DB_NAME=erp_system_drill，使 DROP/CREATE/导入全部只作用于演练库，
绝不影响生产库 erp_system。

P0-2 修订（此前本脚本只 glob erp_backup_*.zip，对生产实际产物 erp_auto_daily_*.zip.enc
必然 SystemExit）：现在同时匹配 .zip 与 .zip.enc 并取最新；加密包必须提供口令，
口令缺失时显式报错，绝不静默按明文处理。选包/口令判定逻辑抽成纯函数以便函数级测试。

用法：
    python scripts/restore_drill.py [备份路径] [口令] [--dry-run]
    （备份路径默认取 backups/server/ 下最新一个；口令默认取 env
      BACKUP_ENCRYPTION_PASSWORD；--dry-run 只选包+解密+校验归档，不连库不恢复）
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import tempfile
import zipfile
from pathlib import Path

# 项目根目录
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / '.env')

# 关键安全护栏：必须在导入任何 app 模块之前把演练库名注入环境，
# restore_database_via_psql 全程只读 DB_NAME 环境变量。
# 因此本模块的 app 依赖（dump / database）一律延迟到 main() 内部再 import。
DRILL_DB = 'erp_system_drill'
os.environ['DB_NAME'] = DRILL_DB

BACKUP_DIR = ROOT / 'backups' / 'server'
# 可演练的备份产物前缀：
#   erp_backup_*      —— 手工/接口触发的全量备份
#   erp_auto_daily_*  —— 每日自动全量备份（生产实际产物名，2026-09 起为 .zip.enc）
# 刻意排除 erp_incremental_*：增量包不是自洽的全量 dump，不能单独做恢复演练。
BACKUP_NAME_PREFIXES = ('erp_backup_', 'erp_auto_daily_')
PLAIN_SUFFIX = '.zip'
ENCRYPTED_SUFFIX = '.zip.enc'
# 伴随文件（元数据/记录）永远不是可恢复的备份产物
SIDECAR_SUFFIXES = ('.meta', '.record')
PASSPHRASE_ENV = 'BACKUP_ENCRYPTION_PASSWORD'


class MissingPassphraseError(RuntimeError):
    """加密备份缺少演练口令：显式失败，绝不静默按明文处理。"""


def is_backup_candidate(name: str) -> bool:
    """判断文件名是否为可演练的全量备份产物。

    形态：<前缀>*.zip 或 <前缀>*.zip.enc（前缀见 BACKUP_NAME_PREFIXES）。
    显式排除 .meta / .record 伴随文件：erp_backup_x.zip.enc.meta 既不匹配 .zip 也
    不匹配 .zip.enc，这里仍显式挡一层，避免日后放宽后缀时把伴随文件选成备份。
    """
    if name.endswith(SIDECAR_SUFFIXES):
        return False
    if not name.startswith(BACKUP_NAME_PREFIXES):
        return False
    return name.endswith(ENCRYPTED_SUFFIX) or name.endswith(PLAIN_SUFFIX)


def list_backup_candidates(directory: Path | None = None) -> list[Path]:
    """按 mtime 升序列出候选备份（最新的在最后）。

    按 mtime 而非文件名排序：文件名时间戳是 UTC（incremental.py / backup_tasks.py 用
    datetime.now(UTC)），mtime 是同一瞬间的本地时区显示，二者单调性一致；mtime 还能
    覆盖手工备份这类按名排序无意义的产物。
    """
    base = Path(directory) if directory is not None else BACKUP_DIR
    if not base.is_dir():
        return []
    items = [f for f in base.iterdir() if f.is_file() and is_backup_candidate(f.name)]
    return sorted(items, key=lambda f: (f.stat().st_mtime, f.name))


def newest_backup(directory: Path | None = None) -> Path:
    """返回目录中最新的备份产物；一个都没有时显式报错。"""
    candidates = list_backup_candidates(directory)
    if not candidates:
        target = Path(directory) if directory is not None else BACKUP_DIR
        raise SystemExit(
            f'未找到任何可演练的全量备份（<前缀>*.zip 或 <前缀>*.zip.enc，前缀 {BACKUP_NAME_PREFIXES}）（目录: {target}）'
        )
    return candidates[-1]


def is_encrypted_backup(path: Path | str) -> bool:
    """是否为加密备份产物（.zip.enc）。"""
    return Path(path).name.endswith(ENCRYPTED_SUFFIX)


def resolve_passphrase(cli_passphrase: str | None = None) -> str:
    """演练口令：命令行优先，其次环境变量 BACKUP_ENCRYPTION_PASSWORD。"""
    if cli_passphrase:
        return cli_passphrase.strip()
    return (os.environ.get(PASSPHRASE_ENV) or '').strip()


def require_passphrase(path: Path | str, cli_passphrase: str | None = None) -> str:
    """返回演练口令；选中的是加密包而口令为空时显式报错。

    明文 zip 不需要口令，返回空串即可。加密包缺口令时**绝不**退回明文路径：
    把密文交给 psql 只会得到无意义的结果与误导性的演练记录。
    """
    passphrase = resolve_passphrase(cli_passphrase)
    if is_encrypted_backup(path) and not passphrase:
        raise MissingPassphraseError(
            f'{Path(path).name} 是加密备份，但未提供口令：请设置环境变量 {PASSPHRASE_ENV} '
            '或用第二个位置参数传入口令（--dry-run 同样需要口令才能验证可解密）'
        )
    return passphrase


def open_backup_archive(
    path: Path | str, cli_passphrase: str | None = None
) -> tuple[zipfile.ZipFile, Path | None]:
    """打开备份归档；加密包先解密到临时文件再交给 zipfile。

    Returns: (ZipFile, 解密临时文件路径或 None —— 调用方负责删除)
    Raises: MissingPassphraseError 口令缺失；ValueError 解密失败。
    """
    archive = Path(path)
    if not is_encrypted_backup(archive):
        return zipfile.ZipFile(archive), None
    passphrase = require_passphrase(archive, cli_passphrase)
    # 延迟导入：把 app 依赖限制在执行期（见文件头 DB_NAME 护栏说明）
    from fastapi_app.core.backup_encryption import decrypt_backup_auto

    plaintext, _meta = decrypt_backup_auto(archive.read_bytes(), passphrase)
    with tempfile.NamedTemporaryFile(prefix='dr_drill_', suffix='.zip', delete=False) as tmp:
        tmp.write(plaintext)
        tmp_path = Path(tmp.name)
    return zipfile.ZipFile(tmp_path), tmp_path


def parse_args(argv: list[str]) -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(
        description='恢复演练：把最新备份恢复到演练库 ' + DRILL_DB
    )
    parser.add_argument('backup', nargs='?', help='备份文件路径（默认取 backups/server/ 下最新一个）')
    parser.add_argument('passphrase', nargs='?', help=f'解密口令（默认取 env {PASSPHRASE_ENV}）')
    parser.add_argument('--dry-run', action='store_true', help='只选包/解密/校验，不连库不恢复')
    return parser.parse_args(argv)


async def main(argv: list[str] | None = None) -> int:
    """演练主流程。"""
    args = parse_args(sys.argv[1:] if argv is None else argv)
    backup_path = Path(args.backup) if args.backup else newest_backup()
    print(f'[drill] 备份文件: {backup_path}')
    encrypted = is_encrypted_backup(backup_path)
    print(f'[drill] 加密:     {"是（先解密）" if encrypted else "否（明文 zip）"}')
    print(f'[drill] 目标库:   {DRILL_DB} (生产库 erp_system 不受影响)')

    zf, decrypted_path = open_backup_archive(backup_path, args.passphrase)
    try:
        names = zf.namelist()
        has_dump = 'database/dump.sql.gz' in names
        print(f'[drill] 归档条目: {len(names)} 个，database/dump.sql.gz {"存在" if has_dump else "缺失"}')
        if not has_dump:
            print('[drill] 错误：归档缺少 database/dump.sql.gz，中止')
            return 1
        if args.dry_run:
            print('[drill] --dry-run：不连库、不执行恢复')
            return 0
        # 延迟导入：见文件头 DB_NAME 护栏说明
        import fastapi_app.services.backup.dump as dump_mod
        from fastapi_app.core.database import require_async_session_local

        async with require_async_session_local()() as db:
            result = await dump_mod.restore_database_via_psql(zf, db)
        print(f'[drill] 恢复结果: {result}')
        return 0 if result.get('status') == 'ok' else 1
    finally:
        zf.close()
        if decrypted_path is not None:
            decrypted_path.unlink(missing_ok=True)


if __name__ == '__main__':
    try:
        raise SystemExit(asyncio.run(main()))
    except MissingPassphraseError as exc:
        print(f'[drill] 拒绝执行：{exc}', file=sys.stderr)
        raise SystemExit(2) from None
