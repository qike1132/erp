"""备份服务共享常量与模块级状态。

从原 backup_service.py 提取的常量、路径配置和可变状态，
供 backup 包内所有子模块共享。
"""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
BACKUP_DIR = Path(os.environ.get('BACKUP_DIR', 'backups/server'))
MAX_BACKUP_FILE_SIZE = 500 * 1024 * 1024
RESTORE_LOCK_ID = 20240426
BACKUP_LOCK_ID = 20240427
BACKUP_OPERATION_TIMEOUT = int(os.environ.get('BACKUP_OPERATION_TIMEOUT', '1800'))
_backup_in_progress: asyncio.Lock = asyncio.Lock()
# 项目根目录：本文件位于 <root>/fastapi_app/services/backup/，故取 parents[3]。
# 勿改成手写 parent 链——拆包时曾多算一层导致指向盘符根（D:\），
# 备份打包/恢复到错误路径，上传文件与 config 密钥长期未进入备份。
PROJECT_ROOT = Path(__file__).resolve().parents[3]
UPLOADS_DIR = PROJECT_ROOT / 'static' / 'uploads'
CONFIG_DIR = PROJECT_ROOT / 'config'
ENV_FILE = PROJECT_ROOT / '.env.production'
REDIS_DUMP = PROJECT_ROOT / 'dump.rdb'
MEILI_HOST = os.environ.get('MEILI_HOST', 'http://localhost:7700')
MEILI_MASTER_KEY = os.environ.get('MEILI_MASTER_KEY', '')
BACKUP_FORMAT_VERSION = '2.0'
PRE_RESTORE_DIR = BACKUP_DIR / 'pre_restore'
_MAX_PRE_RESTORE_BACKUPS = 5
_TIMESTAMP_CANDIDATES = ('updated_at', 'modified_at', 'created_at', 'deleted_at')
_CHECKSUM_EXCLUDE_TABLES = {'alembic_version'}

# 备份加密配置
# P0-1(2026-08-23): FALLBACK_TO_GENERATED 默认改 false——随机密钥无人能找回,
# 曾导致 /save 产出永久不可还原的 .zip。显式设 true 仅兼容旧部署,新代码禁止依赖。
BACKUP_ENCRYPTION_ENABLED = os.environ.get('BACKUP_ENCRYPTION_ENABLED', 'true').lower() == 'true'
BACKUP_ENCRYPTION_PASSWORD = os.environ.get('BACKUP_ENCRYPTION_PASSWORD', '')
BACKUP_ENCRYPTION_KEY = os.environ.get('BACKUP_ENCRYPTION_KEY', '')
BACKUP_ENCRYPTION_FALLBACK_TO_GENERATED = os.environ.get('BACKUP_ENCRYPTION_FALLBACK_TO_GENERATED', 'false').lower() == 'true'

# 加密落盘格式开关（ITER-1 T3）
#   true （默认）→ 新写密文用 chunked-v1 分块 AEAD（可流式，内存与备份体积解耦）
#   false        → 回退 legacy 单包格式
# 读侧两种格式永远都能解开，所以改这个开关**不会**让任何既有备份变成不可读；
# 它是「新密文怕旧代码读不了」这一回退场景的唯一开关（改环境变量 + 重启即可，不必回滚代码）。
# 注意：实际判定在 fastapi_app/core/backup_encryption.py::chunked_encryption_enabled ——
# core 层不能反向 import 本包（会与 services/backup/orchestration/core.py 形成循环依赖），
# 因此那里直接读同名环境变量。本行仅作开关索引，两处默认值必须一致。
BACKUP_ENCRYPTION_CHUNKED = os.environ.get('BACKUP_ENCRYPTION_CHUNKED', 'true').lower() == 'true'

# 大文件分片配置
BACKUP_CHUNK_SIZE = int(os.environ.get('BACKUP_CHUNK_SIZE', '104857600'))  # 默认 100MB
BACKUP_MAX_CHUNKS = int(os.environ.get('BACKUP_MAX_CHUNKS', '100'))  # 最大分片数

# 运行时环境文件（生产由 prod_runner / config.py 的 load_dotenv 真正加载的就是它，
# **不是** .env.production）
RUNTIME_ENV_FILE = PROJECT_ROOT / '.env'


def active_jwt_key_relative_paths() -> list[str]:
    """现役 JWT 密钥相对 config/ 的路径（按 settings 推导，**随轮换自动跟进**）。

    H-3（2026-09-29）：此前打包清单硬编码 `jwt/private.pem` + `jwt/public.pem`，
    那是 2026-08-22 轮换前的旧名 —— 备份里装的是退役（且已在 git 历史泄漏）的密钥，
    现役 v2 密钥从不进包。灾难恢复时 ES256 模式找不到 `JWT_PRIVATE_KEY_PATH` 指向的
    文件会直接 RuntimeError，改用包里的旧钥则等于把泄漏钥重新启用。
    密钥落在 config/ 之外时无法进 `config/` 命名空间，记警告并跳过（不静默）。
    """
    from fastapi_app.core.config import settings

    rel_paths: list[str] = []
    for raw in (settings.JWT_PRIVATE_KEY_PATH, settings.JWT_PUBLIC_KEY_PATH):
        if not raw:
            continue
        try:
            rel_paths.append(Path(raw).resolve().relative_to(CONFIG_DIR.resolve()).as_posix())
        except ValueError:
            logger.warning(f'JWT 密钥不在配置目录内，无法随备份分发: {raw}')
    return rel_paths


def config_files_to_package() -> list[tuple[Path, str]]:
    """要打进备份的配置文件：(源文件绝对路径, 归档内相对路径)。

    `config/` 命名空间由 restore_config 还原回 config/；`root/` 命名空间还原回项目根
    （运行时 .env 在那儿）。
    """
    entries: list[tuple[Path, str]] = [
        (CONFIG_DIR / rel, rel) for rel in active_jwt_key_relative_paths()
    ]
    entries += [
        (CONFIG_DIR / 'redis.production.conf', 'redis.production.conf'),
        (CONFIG_DIR / 'nginx.conf', 'nginx.conf'),
        (CONFIG_DIR / '.env.production', '.env.production'),
        (RUNTIME_ENV_FILE, 'root/.env'),
    ]
    return entries


# REV-09: 配置文件白名单 — 敏感文件恢复需二次确认
# 2026-09-29（H-3）：补入运行时 .env 与**现役**密钥；历史名（private.pem /
# public.pem / .env.production）**保留** —— 旧备份包里装着这些退役件，
# 还原闸门必须照样拦得住。
_SENSITIVE_CONFIG_FILES = {'.env.production', '.env', 'jwt/private.pem', 'jwt/public.pem'}
_SENSITIVE_CONFIG_FILES.update(active_jwt_key_relative_paths())
# 从环境变量读取排除文件列表
BACKUP_EXCLUDE_FILES = os.environ.get('BACKUP_EXCLUDE_FILES', '')
if BACKUP_EXCLUDE_FILES:
    _EXCLUDE_FILES = set(BACKUP_EXCLUDE_FILES.split(','))
else:
    _EXCLUDE_FILES = set()

# 合并敏感文件和排除文件
_SENSITIVE_AND_EXCLUDED_FILES = _SENSITIVE_CONFIG_FILES.union(_EXCLUDE_FILES)

# REV-33: information_schema 查询结果缓存
_ts_col_cache: dict[str, str | None] = {}

# 分布式锁（用于恢复操作互斥）
_RESTORE_LOCK_KEY = "erp:restore_lock"
_RESTORE_LOCK_TTL = 3600  # 1 hour

# 备份保留策略（Phase 4.1）
BACKUP_RETENTION_DAYS = 30
BACKUP_MAX_COUNT = 50
