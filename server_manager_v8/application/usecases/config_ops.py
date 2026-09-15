"""配置读写与校验。

═══════════════════════════════════════════════════════════════════
迁移来源：server_manager.py v5.40 `_load_app_config()` / `_save_config()`
          + `_on_save_ports()` / `_on_save_paths()`
═══════════════════════════════════════════════════════════════════

旧实现把「读文件 → 解析 JSON → 归一化 → 写日志 → 应用到 UI」
写在一个方法里（`_load_app_config` 约 80 行），导致：

    · **无法测试**：要测「配置里端口是 'abc' 时怎么处理」得真的写个文件
    · **副作用混杂**：读取失败时顺手弹了 messagebox，业务逻辑与展示耦合
    · **写回覆盖**：保存单个端口时把整个配置字典重写，
      若此时另一个线程刚改了路径，那次修改会被静默丢掉（lost update）

本模块把两侧分开：

    **归一化**（纯逻辑，零 I/O） → `domain.config_schema.normalize_config`
    **读写**（I/O）              → `StoragePort.load_raw()` / `save_raw()`
    **本模块**                    → 编排 + 校验 + 显式失败

═══════════════════════════════════════════════════════════════════
★ 「读回来再改」而不是「改内存再整块写」
═══════════════════════════════════════════════════════════════════

保存配置时**先重新读一次文件**，在最新内容上打补丁，再整体写回。

为什么：若直接拿内存里的 dict 整块覆盖，会把「在本进程运行时由外部
修改的其他字段」抹掉。这个场景真实存在 —— 用户可能手工编辑了配置文件
（比如加了 nssm_path），而管理器还在运行。

代价是多一次读盘（配置文件只有几 KB）。

★ 并发写仍不是原子的：读-改-写之间存在窗口。
  要真正解决需要文件锁（`StoragePort` 目前没有）。
  本模块**如实标注**这个边界，而不是假装它是原子的 ——
  真正的原子性应由适配器层用 `os.replace` + 锁实现（`save_raw` 已做到
  「写入原子」，但「读-改-写」整体不原子）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ...domain.config_schema import (
    APP_CONFIG_DEFAULTS,
    NormalizedConfig,
    normalize_config,
)
from ...domain.permissions import Action
from ...domain.port_contract import is_valid_port
from ...domain.results import OpResult
from ..auth.guard import ConfirmationToken, require
from .deps import Deps

#: 允许通过本模块修改的端口键
PORT_KEYS: tuple[str, ...] = ('api_port', 'web_port', 'redis_port')

#: 允许通过本模块修改的路径类键
PATH_KEYS: tuple[str, ...] = ('redis_exe', 'nssm_path')

#: 允许通过本模块修改的数值类键
NUMERIC_KEYS: tuple[str, ...] = (
    'max_log_lines', 'log_keep_lines', 'redis_service_wait_s', 'full_stop_hold_ms',
)

#: 允许通过本模块修改的字符串列表键
LIST_KEYS: tuple[str, ...] = ('redis_services',)

#: 全部可写键（白名单 —— 不在其中的键一律拒绝写入）
EDITABLE_KEYS: tuple[str, ...] = (
    PORT_KEYS + PATH_KEYS + NUMERIC_KEYS + LIST_KEYS
)

#: 重置配置的确认词（L3）
CONFIRM_WORD_RESET = '重置配置'


@dataclass
class ConfigLoadResult:
    """一次配置读取的结果。"""

    config: NormalizedConfig
    existed: bool = True
    """文件是否存在。「首次运行」与「文件损坏」要区分开 ——
    前者是正常的，后者需要提醒用户（否则用户会发现设置莫名其妙没了）。"""

    raw: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @property
    def warning_texts(self) -> list[str]:
        """把 ConfigWarning 转成给人看的一行行文字。

        ★ warning 里可能包含非 JSON 安全的对象（如 None、数字），
          统一转字符串，避免直接拼进 `detail` 时报类型错。
        """
        return [f'{w.key}: {w.message}' for w in self.config.warnings]


class ConfigOps:
    """配置的读取、校验与写入。

    读配置是 L0（任何角色可看）；改端口/路径是 L2；
    重置整个配置是 L3（不可逆）。
    """

    def __init__(self, deps: Deps) -> None:
        self._deps = deps

    # ── 读取（L0）────────────────────────────────────────────────

    @require(Action.VIEW_ALL)
    def load(
        self,
        *,
        session: object,
        confirm: ConfirmationToken | None = None,
        event_bus: object = None,
        audit: object = None,
    ) -> OpResult:
        """读取并归一化配置。

        ★ 归一化后的配置通过 `last_config` 取（`OpResult` 不适合带大数据）。
        """
        del confirm, event_bus, audit
        ctx = self._read()
        self._last = ctx

        if not ctx.existed:
            return OpResult.success('首次运行，使用默认配置')
        if ctx.warning_texts:
            # ★ 有警告时用 failure 更合适吗？不 —— 读取成功了。
            #   但警告必须让用户看到，所以放进 detail。
            return OpResult.success(
                '配置已加载（有 ' + str(len(ctx.warning_texts)) + ' 处已自动修正）：'
                + '；'.join(ctx.warning_texts)
            )
        return OpResult.success('配置已加载')

    @property
    def last_config(self) -> NormalizedConfig | None:
        """最近一次 `load()` 的结果（供 UI 取结构化数据）。"""
        return getattr(self, '_last', None) and self._last.config

    # ── 修改端口（L2）────────────────────────────────────────────

    @require(Action.EDIT_PORTS)
    def save_ports(
        self,
        *,
        session: object,
        confirm: ConfirmationToken | None = None,
        event_bus: object = None,
        audit: object = None,
        ports: dict[str, int] | None = None,
    ) -> OpResult:
        """保存端口配置。

        ★ **先全量校验再写入** —— 部分写入会让配置处于「一半新一半旧」
          的状态，而这种状态下的服务绑定行为无法预测。
          校验失败时一个字节都不写。
        """
        if not ports:
            return OpResult.failure('未提供端口', 'ports 为空')

        unknown = [k for k in ports if k not in PORT_KEYS]
        if unknown:
            return OpResult.failure(
                '存在不可写的配置键', f'未知端口键: {", ".join(unknown)}',
            )

        # ── 全量校验 ──
        bad: list[str] = []
        for key, value in ports.items():
            if not is_valid_port(value):
                bad.append(f'{key}={value!r}')
        if bad:
            return OpResult.failure(
                '端口值非法',
                f'须为 1-65535 的整数: {"; ".join(bad)}',
            )

        # ── 端口互斥校验（★ 领域规则：不能有两个相同端口）──
        merged = self._read_raw()
        merged.update(ports)
        conflict = self._port_conflicts(merged)
        if conflict:
            return OpResult.failure('端口冲突', conflict)

        return self._patch(ports, f'已保存端口配置（{self._describe(ports)}）',
                           event_bus=event_bus, audit=audit, session=session,
                           confirm=confirm)

    # ── 修改路径（L2）────────────────────────────────────────────

    @require(Action.EDIT_PATHS)
    def save_paths(
        self,
        *,
        session: object,
        confirm: ConfirmationToken | None = None,
        event_bus: object = None,
        audit: object = None,
        paths: dict[str, str] | None = None,
    ) -> OpResult:
        """保存路径类配置（redis_exe / nssm_path）。"""
        if not paths:
            return OpResult.failure('未提供路径', 'paths 为空')

        unknown = [k for k in paths if k not in PATH_KEYS]
        if unknown:
            return OpResult.failure(
                '存在不可写的配置键', f'未知路径键: {", ".join(unknown)}',
            )

        bad = [f'{k}={v!r}' for k, v in paths.items() if not isinstance(v, str)]
        if bad:
            return OpResult.failure('路径值非法', f'须为字符串: {"; ".join(bad)}')

        cleaned = {k: v.strip() for k, v in paths.items()}
        return self._patch(cleaned, f'已保存路径配置（{self._describe(cleaned)}）',
                           event_bus=event_bus, audit=audit, session=session,
                           confirm=confirm)

    # ── 修改数值/列表（L2）──────────────────────────────────────

    @require(Action.EDIT_PATHS)
    def save_scalars(
        self,
        *,
        session: object,
        confirm: ConfirmationToken | None = None,
        event_bus: object = None,
        audit: object = None,
        values: dict[str, Any] | None = None,
    ) -> OpResult:
        """保存数值类与字符串列表类配置。

        ★ 复用 `EDIT_PATHS` 权限是有意的：这两类键（日志行数、Redis 服务列表）
          的危害等级与「改路径」同级（不会立刻打断线上服务，
          但会影响下一次启动）。为它们单独造 Action 只会让权限表膨胀。
        """
        if not values:
            return OpResult.failure('未提供配置值', 'values 为空')

        allowed = set(NUMERIC_KEYS) | set(LIST_KEYS)
        unknown = [k for k in values if k not in allowed]
        if unknown:
            return OpResult.failure(
                '存在不可写的配置键', f'未知键: {", ".join(unknown)}',
            )

        bad: list[str] = []
        for key, value in values.items():
            if key in NUMERIC_KEYS:
                if isinstance(value, bool) or not isinstance(value, int):
                    bad.append(f'{key}={value!r}（须为整数）')
                elif value <= 0:
                    bad.append(f'{key}={value!r}（须为正数）')
            else:   # LIST_KEYS
                if not (isinstance(value, list) and value
                        and all(isinstance(s, str) and s for s in value)):
                    bad.append(f'{key}={value!r}（须为非空字符串列表）')
        if bad:
            return OpResult.failure('配置值非法', '; '.join(bad))

        return self._patch(dict(values), f'已保存配置（{self._describe(values)}）',
                           event_bus=event_bus, audit=audit, session=session,
                           confirm=confirm)

    # ── 重置（L3）────────────────────────────────────────────────

    @require(Action.RESET_CONFIG, target_arg='confirm_target')
    def reset(
        self,
        *,
        session: object,
        confirm: ConfirmationToken | None = None,
        event_bus: object = None,
        audit: object = None,
        confirm_target: str = CONFIRM_WORD_RESET,
    ) -> OpResult:
        """重置配置为出厂默认（★ 不可逆）。

        ★ 重置前先备份 —— 与 `restore_backup` 同一纪律：
          用户很可能在「改坏了、想回到干净状态」的情绪下点这个按钮，
          而后发现自己其实只是想把端口改回去。
        """
        deps = self._deps
        if deps.storage is None:
            return OpResult.failure('存储适配器不可用', '未注入 StoragePort')

        pre = deps.storage.backup('.prereset')
        if not pre.ok:
            return OpResult.failure(
                '重置前快照失败（已中止，配置未被修改）',
                detail=f'{pre.reason} {pre.detail}',
            )

        saved = deps.storage.save_raw(dict(APP_CONFIG_DEFAULTS))
        if not saved.ok:
            return OpResult.failure(
                '重置写入失败',
                detail=f'{saved.reason}；重置前快照可用（.prereset）',
            )
        return OpResult.success('配置已重置为默认值（快照: .prereset）')

    # ── 内部 ──────────────────────────────────────────────────────

    def _read(self) -> ConfigLoadResult:
        """读文件 + 归一化。"""
        deps = self._deps
        if deps.storage is None:
            # ★ 无存储时返回纯默认值，并明确标注 —— 不是静默给一个空配置
            normalized = normalize_config({})
            return ConfigLoadResult(
                config=normalized, existed=False,
                notes=['未注入 StoragePort，使用默认配置'],
            )

        raw = deps.storage.load_raw()
        existed = bool(raw)
        normalized = normalize_config(raw)
        notes = []
        if not existed:
            notes.append('配置文件不存在或为空，使用默认配置')
        # 归一化的副作用：把规范化结果与默认值合并后的完整配置作为 raw 返回
        merged = dict(APP_CONFIG_DEFAULTS)
        merged.update(normalized.values)
        return ConfigLoadResult(
            config=normalized, existed=existed, raw=merged, notes=notes,
        )

    def _read_raw(self) -> dict[str, Any]:
        """读当前**有效**配置（归一化后的完整字典）。"""
        return dict(self._read().raw)

    def _patch(self, patch: dict[str, Any], success_detail: str, *,
               event_bus: object, audit: object, session: object,
               confirm: ConfirmationToken | None) -> OpResult:
        """读-改-写：在**当前文件内容**上打补丁。

        ★ 用 `_read_raw()` 而不是内存缓存 —— 见模块文档「读回来再改」。
        """
        deps = self._deps
        if deps.storage is None:
            return OpResult.failure(
                '存储适配器不可用', '未注入 StoragePort，配置无法保存',
            )

        current = self._read_raw()
        existing = deps.storage.load_raw()
        # ★ 迁移不删除 v1 扁平键（见 adapters/storage_json 的说明），
        #   这里同样保留未知键：我们只覆盖要改的那些。
        merged = {**existing, **current}
        merged.update(patch)

        saved = deps.storage.save_raw(merged)
        if not saved.ok:
            return OpResult.failure(
                '配置保存失败', detail=f'{saved.reason} {saved.detail}',
            )
        return OpResult.success(success_detail)

    @staticmethod
    def _port_conflicts(config: dict[str, Any]) -> str:
        """检查端口是否重复。返回冲突描述（无冲突返回空串）。"""
        seen: dict[int, str] = {}
        conflicts: list[str] = []
        for key in PORT_KEYS:
            value = config.get(key)
            if not is_valid_port(value):
                continue
            if value in seen:
                conflicts.append(f'{key}({value}) 与 {seen[value]} 重复')
            else:
                seen[value] = key
        return '；'.join(conflicts)

    @staticmethod
    def _describe(values: dict[str, Any]) -> str:
        return ', '.join(f'{k}={v}' for k, v in values.items())


def build_config_ops(deps: Deps) -> ConfigOps:
    return ConfigOps(deps)


__all__ = [
    'CONFIRM_WORD_RESET',
    'ConfigLoadResult',
    'ConfigOps',
    'EDITABLE_KEYS',
    'LIST_KEYS',
    'NUMERIC_KEYS',
    'PATH_KEYS',
    'PORT_KEYS',
    'build_config_ops',
]
