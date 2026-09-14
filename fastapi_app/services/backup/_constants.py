"""备份服务共享常量与模块级状态。

从原 backup_service.py 提取的常量、路径配置和可变状态，
供 backup 包内所有子模块共享。
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
BACKUP_DIR = Path(os.environ.get('BACKUP_DIR', 'backups/server'))
MAX_BACKUP_FILE_SIZE = 500 * 1024 * 1024
RESTORE_LOCK_ID = 20240426
BACKUP_LOCK_ID = 20240427
BACKUP_OPERATION_TIMEOUT = int(os.environ.get('BACKUP_OPERATION_TIMEOUT', '1800'))
_backup_in_progress: asyncio.Lock = asyncio.Lock()
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
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

# REV-09: 配置文件白名单 — 敏感文件恢复需二次确认
_SENSITIVE_CONFIG_FILES = {'.env.production', 'jwt/private.pem', 'jwt/public.pem'}

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
