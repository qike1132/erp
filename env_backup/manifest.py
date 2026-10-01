"""manifest/meta 格式 v3.0 —— 数据结构冻结（改动需升 format_version）。

.envbak 内部 manifest.json:
    格式版本 / 创建时间 / 应用版本 / 主机与平台指纹 / 一致性点 /
    entries[](section+path+sha256+size+compression) / sections[]

sidecar meta（xxx.envbak.meta，与既有 backups/*.meta 模式对齐）:
    created_at / filename / size / type / encrypted / format_version /
    checksum(对 .envbak 全文件的 SHA-256) / app_version / entry_count / sections
"""
from __future__ import annotations

import hashlib
import json
import platform
import socket
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

FORMAT_VERSION = '3.0'
BACKUP_TYPE = 'env_full'
META_SUFFIX = '.meta'
MANIFEST_NAME = 'manifest.json'

# 备份内 section 顺序即打包顺序；db/redis 为 P1 占位（collectors 尚未产出）
SECTIONS = ('app', 'conf', 'env', 'services', 'runtime', 'db', 'redis')

ENVBAK_SUFFIX = '.envbak'


@dataclass(frozen=True)
class Entry:
    """manifest 内单个文件条目。path 为 zip 内 posix 相对路径。"""

    section: str
    path: str
    sha256: str
    size: int
    compression: str = 'deflate'


@dataclass
class Manifest:
    format_version: str = FORMAT_VERSION
    created_at: str = ''
    app_version: str = ''
    hostname: str = ''
    platform_desc: str = ''
    consistency_point: str = ''
    sections: list[str] = field(default_factory=list)
    entries: list[Entry] = field(default_factory=list)

    def to_json_bytes(self) -> bytes:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2).encode('utf-8')

    @classmethod
    def from_json_bytes(cls, raw: bytes) -> Manifest:
        data = json.loads(raw.decode('utf-8'))
        entries = [Entry(**e) for e in data.pop('entries', [])]
        return cls(entries=entries, **data)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path, chunk_size: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as fh:
        for chunk in iter(lambda: fh.read(chunk_size), b''):
            digest.update(chunk)
    return digest.hexdigest()


def now_str() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def platform_fingerprint() -> str:
    return f'{platform.system()}-{platform.release()}-{platform.machine()}'


def build_manifest(
    *,
    entries: list[Entry],
    app_version: str,
    sections: list[str],
    consistency_point: str | None = None,
) -> Manifest:
    """构建 manifest（仅填充元信息，entries 由 packer 产出后注入）。"""
    return Manifest(
        created_at=now_str(),
        app_version=app_version,
        hostname=socket.gethostname(),
        platform_desc=platform_fingerprint(),
        consistency_point=consistency_point or now_str(),
        sections=sections,
        entries=entries,
    )


def build_sidecar_meta(
    *,
    envbak_path: Path,
    manifest: Manifest,
    encrypted: bool,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """构建 sidecar meta（对最终 .envbak 全文件取 SHA-256）。"""
    meta: dict[str, Any] = {
        'created_at': manifest.created_at,
        'filename': envbak_path.name,
        'size': envbak_path.stat().st_size,
        'type': BACKUP_TYPE,
        'encrypted': encrypted,
        'format_version': FORMAT_VERSION,
        'checksum': sha256_file(envbak_path),
        'app_version': manifest.app_version,
        'entry_count': len(manifest.entries),
        'sections': list(manifest.sections),
        'hostname': manifest.hostname,
        'platform': manifest.platform_desc,
    }
    if extra:
        meta.update(extra)
    return meta


def write_sidecar_meta(meta_path: Path, meta: dict[str, Any]) -> None:
    meta_path.write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + '\n', encoding='utf-8'
    )
