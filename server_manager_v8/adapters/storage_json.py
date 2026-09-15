"""JSON 配置文件适配器 —— 读写 + schema 迁移 + 备份。

═══════════════════════════════════════════════════════════════════
迁移来源：server_manager.py v5.40
═══════════════════════════════════════════════════════════════════

| 原实现 | 位置 | 迁移为 |
|---|---|---|
| `_CONFIG_FILE` 路径与读文件 | L84 | `config_path()` |
| `_load_app_config()` 的 I/O 部分 | — | `load()` |
| （无） | — | `save()` / `backup()` / `migrate()` |

★ 归一化逻辑**不在本模块** —— 全部在 `domain.config_schema`。
  本模块只负责「把文件内容取回来」和「把内容写回去」，
  绝不自己判断「这个值合不合法」（那是领域判定，会被反向门禁拦截）。

═══════════════════════════════════════════════════════════════════
schema v1 → v2 迁移（v8 方案 §3.6）
═══════════════════════════════════════════════════════════════════

v1 是扁平的「键 → 值」结构（api_port / web_port / max_log_lines …）。
v2 引入分组（app / ports / paths / health / logs / alerts / auth / audit / backup）。

迁移策略是**保守的**：
    · 检测 `schema_version` 缺失 → 视为 v1
    · 按字段映射升级，**不删除任何 v1 键**（放进 `_legacy_v1` 保留）
    · 迁移前先把原文件备份为 `*.v1.bak`
    · 迁移**只写文件，不改内存里的 v1 语义** ——
      因为 domain.config_schema 仍然按 v1 扁平键归一化，
      在 P4 完成配置读取全面切到 v2 之前，v1 扁平键必须继续可用。

★ 为什么保留 v1 键而不是直接删：v1 键是**当前唯一被 domain 层消费的形态**。
  若迁移时删掉，`normalize_config()` 会读到空配置、全部回落默认值 ——
  用户手改的端口与路径设置会静默丢失。这是「迁移期行为漂移」的典型陷阱，
  必须在设计上就堵掉。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..domain.config_schema import (
    APP_CONFIG_DEFAULTS,
    NormalizedConfig,
    parse_config_text,
)
from ..domain.results import OpResult

#: 当前 schema 版本（v8 方案 §3.6）
CURRENT_SCHEMA_VERSION = 2

#: 配置文件默认位置（迁移自原 `_CONFIG_FILE`，相对 exe 同级目录）
DEFAULT_CONFIG_NAME = 'server_manager_config.json'

#: v1 扁平键 → v2 分组路径 的映射表
V1_TO_V2_MAP: dict[str, tuple[str, str]] = {
    'api_port': ('ports', 'api'),
    'web_port': ('ports', 'web'),
    'redis_port': ('ports', 'redis'),
    'redis_exe': ('paths', 'redis_exe'),
    'nssm_path': ('paths', 'nssm'),
    'max_log_lines': ('logs', 'max_lines'),
    'log_keep_lines': ('logs', 'keep_lines'),
    'full_stop_hold_ms': ('app', 'full_stop_hold_ms'),
    'redis_services': ('_legacy_v1', 'redis_services'),
    'redis_service_wait_s': ('_legacy_v1', 'redis_service_wait_s'),
}


def config_path(base_dir: str | os.PathLike[str] | None = None) -> Path:
    """配置文件路径。

    `base_dir` 为空时用当前工作目录（对齐原实现「exe 同级目录」的意图）。
    抽成函数是为了让测试能注入临时目录，不必 monkeypatch 模块级常量。
    """
    root = Path(base_dir) if base_dir is not None else Path.cwd()
    return root / DEFAULT_CONFIG_NAME


# ═══════════════════════════════════════════════════════════════════
# 读取
# ═══════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class LoadResult:
    """一次配置读取的结果。

    `existed` 区分「文件不存在（首次运行）」与「存在但内容损坏」——
    两者都回落默认配置，但对用户的提示完全不同：
    前者是正常首次运行，后者必须警告用户配置有问题。
    """

    config: NormalizedConfig
    raw: dict[str, Any]
    existed: bool
    migrated: bool = False
    error: str | None = None


def _read_text(path: Path) -> tuple[str | None, str | None]:
    """读文件，返回 (文本, 错误)。文件不存在返回 (None, None)。"""
    try:
        return path.read_text(encoding='utf-8'), None
    except FileNotFoundError:
        return None, None
    except (OSError, UnicodeDecodeError) as exc:
        return None, f'{type(exc).__name__}: {exc}'


def load(path: str | os.PathLike[str]) -> LoadResult:
    """读取并归一化配置文件。

    **绝不抛出** —— 任何异常都回落默认配置并记入 `error`。
    对齐原 `_load_app_config()` 的「绝不因配置崩溃」承诺。
    """
    target = Path(path)
    text, read_error = _read_text(target)

    if text is None:
        # 文件不存在（首次运行）或读失败
        if read_error is None:
            return LoadResult(parse_config_text('{}'), {}, existed=False)
        result = parse_config_text('{}')
        return LoadResult(result, {}, existed=False, error=read_error)

    # 交给领域层的 parse_config_text（它负责解析失败回落 + 归一化）
    normalized = parse_config_text(text)

    # 尝试解析原始 dict（仅用于判断 schema 版本，失败不致命）
    try:
        raw = json.loads(text)
        if not isinstance(raw, dict):
            raw = {}
    except Exception:
        raw = {}

    return LoadResult(normalized, raw, existed=True)


# ═══════════════════════════════════════════════════════════════════
# schema 迁移
# ═══════════════════════════════════════════════════════════════════


def detect_version(data: dict[str, Any]) -> int:
    """探测配置的 schema 版本。缺失或非法 → 1（v1）。"""
    raw = data.get('schema_version')
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return 1
    return value if value in (1, 2) else 1


def migrate(data: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """v1 → v2 迁移。返回 (迁移后数据, 是否发生过迁移)。

    ★ 迁移**不删除** v1 扁平键：v2 分组是**新增**的，v1 键原地保留。
      原因见模块 docstring —— 领域层目前仍按 v1 扁平键归一化，
      删掉会让用户设置静默丢失。

    对已经是 v2 的配置，本函数返回原样（幂等）。
    """
    if detect_version(data) >= CURRENT_SCHEMA_VERSION:
        return data, False

    migrated: dict[str, Any] = dict(data)
    migrated['schema_version'] = CURRENT_SCHEMA_VERSION

    # 建立 v2 分组骨架
    for group in ('app', 'ports', 'paths', 'logs', '_legacy_v1'):
        migrated.setdefault(group, {})

    # 按映射表搬运（同时保留 v1 原键）
    for v1_key, (group, v2_key) in V1_TO_V2_MAP.items():
        if v1_key in data:
            target = migrated[group]
            if isinstance(target, dict):
                target[v2_key] = data[v1_key]

    # _legacy_v1 里原样留一份完整 v1 快照，便于将来人工回溯
    legacy = migrated['_legacy_v1']
    if isinstance(legacy, dict):
        for key, value in data.items():
            if key not in ('schema_version', 'app', 'ports', 'paths', 'logs',
                           'health', 'alerts', 'auth', 'audit', 'backup',
                           '_legacy_v1'):
                legacy.setdefault(key, value)

    # 记录迁移来源，便于排障时知道这份配置从哪来
    migrated['_migrated_from'] = 1

    return migrated, True


# ═══════════════════════════════════════════════════════════════════
# 写入与备份
# ═══════════════════════════════════════════════════════════════════


def backup(path: str | os.PathLike[str], suffix: str = '.bak') -> OpResult:
    """备份配置文件到 `<path><suffix>`。

    文件不存在时返回**成功**（无事可做不算失败），但 detail 说清原因 ——
    「没备份」和「备份成功」在排障时是两件必须能区分的事。
    """
    target = Path(path)
    if not target.exists():
        return OpResult.success(f'源文件不存在，无需备份: {target.name}')

    dest = target.with_name(target.name + suffix)
    try:
        dest.write_bytes(target.read_bytes())
    except OSError as exc:
        return OpResult.failure('备份失败', f'{type(exc).__name__}: {exc}')
    return OpResult.success(f'已备份到 {dest.name}')


def save(path: str | os.PathLike[str], data: dict[str, Any]) -> OpResult:
    """写回配置（原子写：先写临时文件再替换）。

    ★ 原子写的必要性：原实现直接 `write_text()`。若写入过程中崩溃/断电，
      会留下**半截 JSON** —— 下次启动 `json.loads()` 失败，
      用户所有设置静默回落默认值。原子替换杜绝这个窗口。
    """
    target = Path(path)
    tmp = target.with_name(target.name + '.tmp')
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                       encoding='utf-8')
        os.replace(tmp, target)
    except OSError as exc:
        # 清理临时文件（尽力而为，失败不影响错误上报）
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        return OpResult.failure('写入配置失败', f'{type(exc).__name__}: {exc}')
    return OpResult.success(f'已写入 {target.name}')


def load_and_migrate(path: str | os.PathLike[str]) -> LoadResult:
    """读取 + 自动迁移 + 备份 + 回写。

    这是给调用方的「一条命令搞定」入口，内部保持上述顺序不变：
        读 → 判断版本 → 备份 → 迁移 → 回写
    备份必须在回写**之前**，否则备份的就是迁移后的内容（等于没备份）。
    """
    result = load(path)

    if not result.existed or not result.raw:
        return result

    if detect_version(result.raw) >= CURRENT_SCHEMA_VERSION:
        return result

    # v1 → v2：先备份再写
    bak = backup(path, '.v1.bak')
    if not bak.ok:
        # 备份失败就**不迁移** —— 宁可继续用 v1，也不能在没有回退路径时改用户文件
        return LoadResult(
            result.config, result.raw, existed=True, migrated=False,
            error=f'迁移前备份失败，已跳过迁移: {bak.reason} {bak.detail}',
        )

    migrated_data, _ = migrate(result.raw)
    write = save(path, migrated_data)
    if not write.ok:
        return LoadResult(
            result.config, result.raw, existed=True, migrated=False,
            error=f'迁移写入失败: {write.reason} {write.detail}',
        )

    # 迁移后重新读一次，保证返回的 raw 与磁盘一致
    refreshed = load(path)
    return LoadResult(refreshed.config, refreshed.raw, existed=True, migrated=True)


__all__ = [
    'CURRENT_SCHEMA_VERSION',
    'DEFAULT_CONFIG_NAME',
    'V1_TO_V2_MAP',
    'LoadResult',
    'backup',
    'config_path',
    'detect_version',
    'load',
    'load_and_migrate',
    'migrate',
    'save',
]
