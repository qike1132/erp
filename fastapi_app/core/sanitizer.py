"""SQL 与查询输入净化、日志敏感信息过滤工具函数

通用工具函数，不依赖任何业务层，可被 shared/services/endpoints 各层安全引用。
"""
from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

# 敏感字段名（不区分大小写），命中后值会被脱敏
_SENSITIVE_KEYS = frozenset({
    'password', 'passwd', 'pwd',
    'token', 'access_token', 'refresh_token', 'csrf_token',
    'secret', 'api_key', 'apikey', 'authorization',
    'x_backup_password', 'backup_password',
    'session', 'session_id', 'cookie',
})

# 常见的 token / 凭据模式（用于在字符串中识别并脱敏）
_TOKEN_PATTERNS: tuple[str, ...] = (
    'bearer ',
    'basic ',
)

# 字符串内部的 key=value 形式敏感字段（用于在异常消息等自由文本中脱敏）
_INNER_SENSITIVE_KEYS: tuple[str, ...] = (
    'password', 'passwd', 'pwd',
    'token', 'access_token', 'refresh_token', 'csrf_token',
    'secret', 'api_key', 'apikey', 'authorization',
    'x_backup_password', 'backup_password',
)


def escape_like(value: str) -> str:
    """转义 SQL LIKE 通配符，防止 LIKE 注入"""
    return value.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')


def _mask_value(value: Any) -> str:
    """将敏感值替换为固定长度的脱敏占位符。"""
    return '***REDACTED***'


def sanitize_for_log(data: Any) -> Any:
    """
    递归清洗数据结构中的敏感字段，避免明文密码/Token 写入日志。

    支持 dict / list / tuple / 基础类型；命中 `_SENSITIVE_KEYS` 的字段值会被替换。
    对普通字符串会识别 Bearer/Basic 前缀和明显的凭据格式进行脱敏。
    """
    if isinstance(data, Mapping):
        sanitized: dict[Any, Any] = {}
        for key, value in data.items():
            if isinstance(key, str) and key.lower() in _SENSITIVE_KEYS:
                sanitized[key] = _mask_value(value)
            else:
                sanitized[key] = sanitize_for_log(value)
        return sanitized
    if isinstance(data, (list, tuple)):
        return [sanitize_for_log(item) for item in data]
    if isinstance(data, str):
        lowered = data.lower()
        for pattern in _TOKEN_PATTERNS:
            idx = lowered.find(pattern)
            if idx >= 0:
                return data[: idx + len(pattern)] + _mask_value(None)
        # 识别字符串内 "key=value" 形式的敏感字段（如 "token=abc123"）。
        # 找出所有匹配中最早出现的位置，确保优先脱敏字符串前段的敏感信息。
        earliest_idx: int | None = None
        match_len = 0
        for sensitive_key in _INNER_SENSITIVE_KEYS:
            for sep in ('=', ':'):
                needle = sensitive_key + sep
                idx = lowered.find(needle)
                if idx >= 0 and (earliest_idx is None or idx < earliest_idx):
                    earliest_idx = idx
                    match_len = len(needle)
        if earliest_idx is not None:
            end = earliest_idx + match_len
            return data[:end] + _mask_value(None)
        return data
    return data


def safe_exception_message(exc: BaseException, *, max_length: int = 500) -> str:
    """
    返回异常消息的安全版本：截断长度并移除可能包含的敏感片段。
    """
    msg = str(exc).strip()
    if not msg:
        return exc.__class__.__name__
    sanitized = sanitize_for_log(msg)
    if not isinstance(sanitized, str):
        sanitized = str(sanitized)
    if len(sanitized) > max_length:
        sanitized = sanitized[: max_length - 3] + '...'
    return sanitized


class SanitizingFilter(logging.Filter):
    """
    日志过滤器：自动对 record.msg / record.args 进行敏感信息脱敏。

    使用方式：
        handler.addFilter(SanitizingFilter())
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            if isinstance(record.msg, str):
                record.msg = sanitize_for_log(record.msg)
            if record.args:
                record.args = tuple(
                    sanitize_for_log(arg) if isinstance(arg, (str, Mapping, list, tuple)) else arg
                    for arg in record.args
                )
        except (TypeError, ValueError, AttributeError):
            return True
        return True

