"""env_backup — ERP 服务器管理器「备份与恢复」模块（P0 打包内核）。

职责（P0，方案见 docs/backup-restore/备份与恢复模块设计方案.md）:
  - manifest/meta 格式 v3.0 冻结（单一 .envbak 自包含环境包）
  - 环境清单收集器（app / conf / env / services / runtime）
  - ZIP 打包 / SHA-256 验包 / 解包（zip-slip 防护）
  - AES-256-GCM 加密（主密码 scrypt 派生；P3 主密码体系落地时评估 argon2-cffi）

边界:
  - 独立包，禁止 import fastapi_app（管理器 exe 独立打包）
  - db(pg_dump)/redis(RDB) 采集属 P1；本包预留 section 占位
  - 进度回调协议 progress(stage, current, total, message)，GUI 侧接队列（主线程零阻塞）
"""
from env_backup.manifest import FORMAT_VERSION, Entry, Manifest, build_manifest
from env_backup.packer import (
    PackResult,
    VerifyReport,
    pack_environment,
    unpack_envbak,
    verify_envbak,
)

__all__ = [
    'FORMAT_VERSION',
    'Entry',
    'Manifest',
    'build_manifest',
    'PackResult',
    'VerifyReport',
    'pack_environment',
    'unpack_envbak',
    'verify_envbak',
]
