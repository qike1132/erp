"""配置 schema 与归一化 —— 纯逻辑，零 I/O。

本模块从 server_manager.py（v5.40）`_load_app_config()` 迁移而来，
**逐行搬运归一化规则，未做行为改动**（仅剥离文件读取 I/O）。

═══════════════════════════════════════════════════════════════════
核心承诺：绝不因配置崩溃
═══════════════════════════════════════════════════════════════════

原函数 docstring 明写「文件不存在/损坏时回落默认值（绝不因配置崩溃）」，
但 v5.39 审查 🔴#3 发现它**自己违背了这个承诺**：

    __init__ 里直接 int(_APP_CONFIG.get('max_log_lines') or 2000)
    手改配置写坏（如 "max_log_lines": "abc"）→ ValueError → 炸在启动

v5.40 已修（对标量键统一归一化）。本模块把这套规则显式化并可测试。

涉及的归一化规则（全部保留）：

    redis_services        list[str] 非空校验 → 非法回落默认（D5: 空列表视为非法）
    redis_service_wait_s  正整数，非法回落 30
    max_log_lines         整数 >= 100，非法回落 2000
    log_keep_lines        整数 >= 50，非法回落 1600
    full_stop_hold_ms     整数 >= 200，非法回落 1500
    api/web/redis_port    1..65535，非法则记入 invalid 列表（不阻断）
    log_keep_lines < max_log_lines   否则 keep = max(50, max - 200)

    D4: redis_services 始终返回独立副本，绝不与默认值共享别名

循环导入说明：`service_state` 与 `port_contract` 均不 import 本模块，
故模块级导入安全。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from .port_contract import DEFAULT_PORTS, PortConfig, is_valid_port

# ═══════════════════════════════════════════════════════════════════
# 默认值（迁移自 _APP_CONFIG_DEFAULTS，值必须逐一核对）
# ═══════════════════════════════════════════════════════════════════

DEFAULT_API_PORT = 5002
DEFAULT_WEB_PORT = 3000
DEFAULT_REDIS_PORT = 6379

DEFAULT_MAX_LOG_LINES = 2000
DEFAULT_LOG_KEEP_LINES = 1600
DEFAULT_FULL_STOP_HOLD_MS = 1500
DEFAULT_REDIS_SERVICE_WAIT_S = 30

#: v5.40 引入的 floor（下限）
FLOOR_MAX_LOG_LINES = 100
FLOOR_LOG_KEEP_LINES = 50
FLOOR_FULL_STOP_HOLD_MS = 200

#: 迁移自 _DEFAULT_REDIS_SERVICES
DEFAULT_REDIS_SERVICES: tuple[str, ...] = ('erp-redis', 'erp-redis-broker')

APP_CONFIG_DEFAULTS: dict[str, Any] = {
    'api_port': DEFAULT_API_PORT,
    'web_port': DEFAULT_WEB_PORT,
    'redis_port': DEFAULT_REDIS_PORT,
    'redis_exe': '',
    'nssm_path': '',
    'max_log_lines': DEFAULT_MAX_LOG_LINES,
    'log_keep_lines': DEFAULT_LOG_KEEP_LINES,
    'full_stop_hold_ms': DEFAULT_FULL_STOP_HOLD_MS,
    'redis_services': list(DEFAULT_REDIS_SERVICES),
    'redis_service_wait_s': DEFAULT_REDIS_SERVICE_WAIT_S,
}


# ═══════════════════════════════════════════════════════════════════
# 归一化结果
# ═══════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class ConfigWarning:
    """归一化过程中的一条警告（对应原实现的 logging.warning）。

    把这些警告变成**返回值**而非副作用，是纯逻辑化的关键：
    调用方（adapter）负责真正写日志，领域层只负责判定。
    """

    key: str
    message: str


@dataclass
class NormalizedConfig:
    """归一化后的配置 + 处理过程中产生的警告。"""

    values: dict[str, Any] = field(default_factory=dict)
    warnings: list[ConfigWarning] = field(default_factory=list)

    def get(self, key: str, default: Any = None) -> Any:
        return self.values.get(key, default)

    def __getitem__(self, key: str) -> Any:
        return self.values[key]


# ═══════════════════════════════════════════════════════════════════
# 归一化
# ═══════════════════════════════════════════════════════════════════


def _coerce_int_floor(
    raw: Any, default: int, floor: int, key: str, warnings: list[ConfigWarning]
) -> int:
    """把 raw 归一化为「整数且 >= floor」，非法则回落 default 并记警告。

    对应 v5.40 审查 #3 的修复：

        try:
            val = max(floor, int(cfg.get(key)))
        except (TypeError, ValueError):
            val = default
            logging.getLogger(...).warning(f'配置项 {key} 非法({cfg.get(key)!r})，回落默认值 {default}')
    """
    try:
        return max(floor, int(raw))
    except (TypeError, ValueError):
        warnings.append(ConfigWarning(key, f'配置项 {key} 非法({raw!r})，回落默认值 {default}'))
        return default


def normalize_config(stored: Any) -> NormalizedConfig:
    """把「从文件读到的任意值」归一化为可信配置。

    参数 `stored` 是 `json.loads()` 的结果 —— 可能是 dict、可能是 list/str/None
    （用户手改坏了文件）。非 dict 一律视为空配置（全默认）。

    这是 `_load_app_config()` 的**纯逻辑部分**（剥离了文件读取与日志副作用）。
    """
    warnings: list[ConfigWarning] = []
    cfg: dict[str, Any] = dict(APP_CONFIG_DEFAULTS)
    # 深度拷贝默认的 list，避免与 APP_CONFIG_DEFAULTS 共享别名（D4 的精神）
    cfg['redis_services'] = list(DEFAULT_REDIS_SERVICES)

    # ── 逐键白名单合并（未知键丢弃）──
    if isinstance(stored, dict):
        cfg.update({k: v for k, v in stored.items() if k in cfg})

    # ── redis_services：list[str] 非空校验（D5 / D4）──
    services = cfg.get('redis_services')
    valid = (
        isinstance(services, list)
        and bool(services)
        and all(isinstance(s, str) and s for s in services)
    )
    if valid:
        cfg['redis_services'] = list(services)   # D4: 显式拷贝，杜绝共享别名
    else:
        if isinstance(services, list) and not services:
            # D5: 空列表等于「不再托管任何 Redis 服务」，几乎不可能是用户本意
            warnings.append(ConfigWarning('redis_services', 'redis_services 为空列表，按非法配置处理，回落默认托管列表'))
        cfg['redis_services'] = list(DEFAULT_REDIS_SERVICES)

    # ── redis_service_wait_s：正整数，非法回落 30 ──
    try:
        cfg['redis_service_wait_s'] = max(1, int(cfg.get('redis_service_wait_s')))
    except (TypeError, ValueError):
        cfg['redis_service_wait_s'] = DEFAULT_REDIS_SERVICE_WAIT_S

    # ── 标量键统一归一化（v5.40 审查 #3）──
    cfg['max_log_lines'] = _coerce_int_floor(
        cfg.get('max_log_lines'), DEFAULT_MAX_LOG_LINES, FLOOR_MAX_LOG_LINES,
        'max_log_lines', warnings)
    cfg['log_keep_lines'] = _coerce_int_floor(
        cfg.get('log_keep_lines'), DEFAULT_LOG_KEEP_LINES, FLOOR_LOG_KEEP_LINES,
        'log_keep_lines', warnings)
    cfg['full_stop_hold_ms'] = _coerce_int_floor(
        cfg.get('full_stop_hold_ms'), DEFAULT_FULL_STOP_HOLD_MS, FLOOR_FULL_STOP_HOLD_MS,
        'full_stop_hold_ms', warnings)

    # ── keep 必须 < max，否则日志裁剪退化为空操作 ──
    if cfg['log_keep_lines'] >= cfg['max_log_lines']:
        cfg['log_keep_lines'] = max(FLOOR_LOG_KEEP_LINES, cfg['max_log_lines'] - 200)

    # ── 字符串键归一化（redis_exe / nssm_path 必须为 str）──
    for key in ('redis_exe', 'nssm_path'):
        if not isinstance(cfg.get(key), str):
            warnings.append(ConfigWarning(key, f'配置项 {key} 非字符串({cfg.get(key)!r})，回落空字符串'))
            cfg[key] = ''

    return NormalizedConfig(values=cfg, warnings=warnings)


def parse_config_text(text: str) -> NormalizedConfig:
    """从 JSON 文本解析并归一化（对应 `_CONFIG_FILE.read_text()` + `json.loads()`）。

    解析失败不抛异常，回落全默认 + 记警告 —— 这是「绝不因配置崩溃」的实现点。
    """
    try:
        stored = json.loads(text)
    except Exception as exc:
        result = normalize_config(None)
        result.warnings.insert(
            0,
            ConfigWarning('<file>', f'配置文件读取/解析失败，已回落默认配置: {type(exc).__name__}: {exc}'),
        )
        return result
    return normalize_config(stored)


# ═══════════════════════════════════════════════════════════════════
# 端口应用
# ═══════════════════════════════════════════════════════════════════


def extract_ports(cfg: NormalizedConfig | dict[str, Any]) -> tuple[PortConfig, list[str]]:
    """从配置提取端口，返回 (PortConfig, 非法键列表)。

    迁移自 `_apply_config_to_runtime()`：

        for attr, key in (('api','api_port'), ('web','web_port'), ('redis','redis_port')):
            try:
                v = int(cfg.get(key))
            except (TypeError, ValueError):
                invalid.append(key); continue
            if 1 <= v <= 65535:
                setattr(_PORTS, attr, v)
            else:
                invalid.append(key)

    ★ 返回类型从「就地 setattr 全局单例」改为「返回不可变 PortConfig」——
    这消除了原实现的隐式全局状态（v8 方案 D3）。

    非法端口的处理保持原语义：**记入 invalid 列表，不阻断启动**
    （v5.40 审查 #22: 配置损坏必须留痕，不静默），非法项回落到默认值。
    """
    values = cfg.values if isinstance(cfg, NormalizedConfig) else cfg
    invalid: list[str] = []
    resolved: dict[str, int] = {}

    for attr, key, default in (
        ('api', 'api_port', DEFAULT_API_PORT),
        ('web', 'web_port', DEFAULT_WEB_PORT),
        ('redis', 'redis_port', DEFAULT_REDIS_PORT),
    ):
        raw = values.get(key)
        try:
            value = int(raw)
        except (TypeError, ValueError):
            invalid.append(key)
            resolved[attr] = default
            continue
        if is_valid_port(value):
            resolved[attr] = value
        else:
            invalid.append(key)
            resolved[attr] = default

    return (
        PortConfig(api=resolved['api'], web=resolved['web'], redis=resolved['redis']),
        invalid,
    )
