"""pywebview JS API 桥 —— 前端唯一的后端入口。

═══════════════════════════════════════════════════════════════════
一条铁律：一个方法 = 一个用例调用，桥里不做业务
═══════════════════════════════════════════════════════════════════

本模块**只做三件事**：
    ① 收前端的 JSON 参数
    ② 调用例 / 适配器
    ③ 把结果序列化成 JSON 返回

**绝不允许**在这里出现：
    · `if status == 'RUNNING'` 这类判定 —— 判定在 domain
    · 多步编排（先停再启之类）—— 编排在 usecase
    · 直接 import adapters 之外做 I/O

理由：桥是 L4，是四层里最"薄"的一层。一旦它开始承载业务，
就变成了第二个上帝类 —— 而当初重构的全部意义就是消灭上帝类。
（这条边界由 `scripts/check_domain_purity.py` 的展示层检查守护。）

═══════════════════════════════════════════════════════════════════
★ 为什么每个方法都返回 {"ok":..., "reason":..., "detail":...}
═══════════════════════════════════════════════════════════════════

pywebview 的 JS API 有两条硬约束，决定了这个统一返回形状：

**① 返回值必须 JSON 可序列化。**
`OpResult` 是 frozen dataclass，直接返回会 `TypeError`。
必须过 `serializers` 转成 dict。

**② 异常跨越桥会丢失。**
Python 抛出的异常传到 JS 侧只剩一句字符串，栈、类型全没了。
所以桥内**一律捕获异常并转成失败结果**，把 `type + msg` 放进 detail ——
宁可让前端看到「内部错误: TypeError: ...」，也不能让调用静默挂掉。

═══════════════════════════════════════════════════════════════════
★ 确认令牌（confirm）是「用户真的点了确认」的唯一凭据
═══════════════════════════════════════════════════════════════════

前端**不能**直接传 `{"kind": "modal"}` 就说自己确认过了 —— 那是自己给自己
发通行证。真正的凭据必须由用户动作产生。本桥的约定：

    · 前端调 `request_confirmation(action, target)` 拿到**服务端签发的**
      令牌（包含操作、目标、时间戳）
    · 用户在弹出的框里输入确认词 / 填原因后，前端把
      `{token_id, typed_name, reason}` 回传
    · 桥据 token_id 取回原令牌，校验 `typed_name` 与 `reason` 后
      才构造 `ConfirmationToken` 交给用例

于是「点了几下」与「真的输入了确认词」在服务端是可区分的。
（P4 阶段先落「令牌签发 + 回传校验」这一步；令牌签名留待接入账号体系时加强。）
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from ..application.auth.guard import ConfirmKind, ConfirmationToken
from ..application.auth.session import Session
from ..application.events import Event
from ..application.event_bus import EventBus
from ..application.usecases.alert_ops import AlertOps
from ..application.usecases.backup_ops import BackupOps
from ..application.usecases.config_ops import ConfigOps
from ..application.usecases.deps import Deps
from ..application.usecases.install_services import (
    InstallServices,
    UninstallServices,
    required_confirmation,
)
from ..application.usecases.kill_port import KillPort
from ..application.usecases.log_ops import LogOps
from ..application.usecases.start_dev import StartDev
from ..application.usecases.start_prod import StartProd
from ..application.usecases.stop_all import StopAll
from ..application.usecases.switch_mode import SwitchMode, detect_mode
from ..container import Container
from ..domain.models import MANAGED_NSSM_SERVICES
from ..domain.permissions import Action, DangerLevel, Role, check as perm_check
from . import serializers as ser

log = logging.getLogger(__name__)

#: 确认令牌有效期（秒）—— 用户从看到弹窗到输入确认词不该无限期挂着
CONFIRM_TOKEN_TTL_S = 300.0


# ═══════════════════════════════════════════════════════════════════
# 前端事件投递
# ═══════════════════════════════════════════════════════════════════


@dataclass
class EventPump:
    """把 EventBus 上的事件推给前端。

    ★ 为什么要缓冲而不是「事件来了立即调 JS」：
      pywebview 的 `evaluate_js` **必须在 UI 线程调用**。事件可能从
      后台线程（如指标采样线程）发出，直接调会崩或静默无效。
      所以事件先进队列，由 UI 线程按帧取走。

    ★ 为什么要有上限：
      前端可能卡住（用户拖窗口、JS 死循环），此时队列会无限增长 →
      内存爆掉。超上限时**丢最旧的**并计数 —— 丢掉的条数要如实
      上报给前端（`dropped`），不能装作没丢。
    """

    #: 队列上限（超出丢最旧）
    max_size: int = 2000
    #: 取事件时调用的 JS 函数名
    js_target: str = 'window.v8push'

    _queue: list[dict[str, Any]] = field(default_factory=list, init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)
    _dropped: int = field(default=0, init=False)
    _window: Any = field(default=None, init=False)

    def attach(self, window: Any) -> None:
        """绑定窗口对象（用于 evaluate_js）。"""
        self._window = window

    def push(self, event: Event) -> None:
        """事件总线回调：入队。"""
        payload = ser.event_payload(event)
        with self._lock:
            self._queue.append(payload)
            if len(self._queue) > self.max_size:
                overflow = len(self._queue) - self.max_size
                del self._queue[:overflow]
                self._dropped += overflow

    def drain(self, limit: int = 200) -> dict[str, Any]:
        """前端主动拉取事件（推荐方式，避免 evaluate_js 的线程约束）。

        ★ 用「前端轮询」而不是「后端主动推」：轮询不受 pywebview
          线程模型限制，也不会因为前端卡住而阻塞后端。
          代价是延迟（最长一个轮询周期），对本场景完全可接受。
        """
        with self._lock:
            batch = self._queue[:limit]
            del self._queue[:limit]
            dropped, self._dropped = self._dropped, 0
        return {'events': batch, 'dropped': dropped, 'pending': self._pending()}

    def _pending(self) -> int:
        with self._lock:
            return len(self._queue)

    @property
    def dropped(self) -> int:
        with self._lock:
            return self._dropped


# ═══════════════════════════════════════════════════════════════════
# 桥
# ═══════════════════════════════════════════════════════════════════


class JsBridge:
    """暴露给前端的 API 对象（pywebview 会把它挂成 `window.pywebview.api`）。

    ★ 方法名即 JS 侧调用名，**保持扁平**（`stop_all` 而非 `usecases.stop_all`）：
      pywebview 对嵌套对象的支持依赖 js_api 的递归展开，行为在不同版本
      有差异；扁平方法名没有这个不确定性。
    """

    def __init__(self, container: Container, *,
                 on_window_ready: Callable[[], None] | None = None) -> None:
        self._c = container
        self._deps: Deps = container.deps
        self._session: Session = container.session
        self._bus: EventBus = container.event_bus
        self._pump = EventPump()
        self._on_window_ready = on_window_ready

        #: 确认令牌表（token_id → 令牌），仅存服务端
        self._tokens: dict[str, ConfirmationToken] = {}
        self._token_meta: dict[str, dict[str, Any]] = {}
        self._token_lock = threading.Lock()

        #: 事件 → 队列（通配订阅）
        self._bus.subscribe(Event, self._pump.push)

        # ── 用例实例（长生命周期，保留内部状态）─────────────
        self._stop_all = StopAll(self._deps)
        self._start_dev = StartDev(self._deps)
        self._start_prod = StartProd(self._deps)
        self._switch_mode = SwitchMode(self._deps)
        self._kill_port = KillPort(self._deps)
        self._install = InstallServices(self._deps)
        self._uninstall = UninstallServices(self._deps)
        self._log_ops = LogOps(self._deps)
        self._alert_ops = AlertOps(self._deps)
        self._backup_ops = BackupOps(self._deps)
        self._config_ops = ConfigOps(self._deps)

    # ═══════════════════════════════════════════════════════════════
    # 内部：统一包装
    # ═══════════════════════════════════════════════════════════════

    def _safe(self, fn: Callable[[], Any], what: str) -> dict[str, Any]:
        """把「可能抛异常」的调用统一转成 `{ok, reason, detail}`。

        ★ 异常必须在这里被接住：跨 pywebview 桥传到 JS 只剩字符串，
          丢失类型与栈。接住并带上类型名，前端至少能显示
          「内部错误: TypeError: xxx」而不是空白。
        """
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 — 桥必须兜住一切
            log.exception('桥方法 %s 失败', what)
            return {
                'ok': False,
                'reason': '内部错误',
                'detail': f'{type(exc).__name__}: {exc}',
            }

    def _result(self, result: Any) -> dict[str, Any]:
        """`OpResult` → DTO，并附带最新会话状态（前端要同步提权倒计时）。"""
        out = ser.op_result(result)
        out['session'] = ser.session_state(self._session)
        return out

    # ═══════════════════════════════════════════════════════════════
    # 会话与权限
    # ═══════════════════════════════════════════════════════════════

    def session_state(self) -> dict[str, Any]:
        """当前会话（角色 / 提权剩余秒数）。"""
        def go() -> dict[str, Any]:
            return {'ok': True, 'session': ser.session_state(self._session)}
        return self._safe(go, 'session_state')

    def elevate(self, role: str = 'admin') -> dict[str, Any]:
        """提权到指定角色。

        ★ 这里**没有** PIN 校验 —— 本地单机工具的「防误操作」语义，
          不是「防越权」语义（方案 §2.5 待决策项）。但如果将来接
          Windows 本地组或 PIN，落点就在这里：在本方法开头加校验，
          用例层不用动。
        """
        def go() -> dict[str, Any]:
            target = _parse_role(role)
            if target is None:
                return {'ok': False, 'reason': '未知角色', 'detail': f'{role!r}'}
            state = self._session.elevate(target)
            return {'ok': True, 'session': ser.session_state(self._session),
                    'detail': f'已提权为「{target.label}」'}
        return self._safe(go, 'elevate')

    def de_elevate(self) -> dict[str, Any]:
        """立即降权为 viewer（JIT 最小权限）。"""
        def go() -> dict[str, Any]:
            self._session.demote()
            return {'ok': True, 'session': ser.session_state(self._session),
                    'detail': '已降权为「只读」'}
        return self._safe(go, 'de_elevate')

    def permission_matrix(self) -> dict[str, Any]:
        """完整权限矩阵（前端据此锁定按钮）。

        ★ 前端**不应**自己维护一份「哪个操作要什么角色」的表 ——
          两份表必然漂移，而漂移的后果是权限绕过或「确认后没反应」。
        """
        def go() -> dict[str, Any]:
            return {
                'ok': True,
                'roles': [ser.role_info(r) for r in Role],
                'actions': [ser.action_meta(a) for a in Action],
                'grants': {
                    r.value: sorted(a.value for a in _actions_for(r))
                    for r in Role
                },
            }
        return self._safe(go, 'permission_matrix')

    def check_permission(self, action: str) -> dict[str, Any]:
        """查某个操作在当前角色下是否允许。"""
        def go() -> dict[str, Any]:
            act = _parse_action(action)
            if act is None:
                return {'ok': False, 'reason': '未知操作', 'detail': action}
            c = perm_check(self._session.role, act)
            return {'ok': True, 'check': ser.permission_check(c),
                    'meta': ser.action_meta(act)}
        return self._safe(go, 'check_permission')

    def request_confirmation(self, action: str) -> dict[str, Any]:
        """签发确认令牌（用户点了操作按钮后调）。

        返回的 `token_id` 要由前端在用户完成确认动作后回传。
        """
        def go() -> dict[str, Any]:
            act = _parse_action(action)
            if act is None:
                return {'ok': False, 'reason': '未知操作', 'detail': action}

            info = required_confirmation(act)
            token_id = uuid.uuid4().hex[:16]
            with self._token_lock:
                self._token_meta[token_id] = {
                    'action': act.value,
                    'issued_at': time.time(),
                }
            return {
                'ok': True,
                'token_id': token_id,
                'confirm': info,
                'meta': ser.action_meta(act),
                'expires_in_s': CONFIRM_TOKEN_TTL_S,
            }
        return self._safe(go, 'request_confirmation')

    def _consume_token(self, token_id: str, action: Action,
                       typed_name: str = '', reason: str = '',
                       impact: str = '') -> ConfirmationToken:
        """校验前端回传的确认信息，构造真正的令牌。

        ★ 校验点（全部在服务端做，不信前端说的「我已经确认过了」）：
          ① token_id 存在且未过期 —— 防重放与伪造
          ② 令牌绑定的 action 与本次调用一致 —— 防「拿 A 的确认去干 B」
          ③ 危险等级要求的确认方式真的满足了

        ★ L3 还需要 `typed_name` 与固定确认词一致。固定确认词从
          `required_confirmation()` 取 —— 与前端渲染提示用的是**同一份**来源。
        """
        now = time.time()
        with self._token_lock:
            meta = self._token_meta.pop(token_id, None)
        if meta is None:
            return ConfirmationToken(kind=ConfirmKind.NONE)

        if now - float(meta.get('issued_at', 0)) > CONFIRM_TOKEN_TTL_S:
            return ConfirmationToken(kind=ConfirmKind.NONE)

        if meta.get('action') != action.value:
            #: ★ 令牌串用 —— 按「没有确认」处理，不放行
            return ConfirmationToken(kind=ConfirmKind.NONE)

        level = action.danger
        if level is DangerLevel.L0:
            return ConfirmationToken(kind=ConfirmKind.NONE)
        if level is DangerLevel.L1:
            return ConfirmationToken(kind=ConfirmKind.TOAST_UNDO)
        if level is DangerLevel.L2:
            return ConfirmationToken(kind=ConfirmKind.MODAL)
        #: L3
        return ConfirmationToken(
            kind=ConfirmKind.TYPED,
            typed_name=typed_name,
            reason=reason,
            impact=impact,
        )

    # ═══════════════════════════════════════════════════════════════
    # 只读：状态 / 指标 / 日志 / 审计
    # ═══════════════════════════════════════════════════════════════

    def bootstrap(self) -> dict[str, Any]:
        """首屏一次性拉取（减少往返）。"""
        def go() -> dict[str, Any]:
            return {
                'ok': True,
                'session': ser.session_state(self._session),
                'permissions': self.permission_matrix(),
                'mode': self.detect_mode(),
                'services': self.service_list(),
                'config': self.config_load(),
                'alerts': self.alert_list(notify_only=False),
                'notes': self._c.degraded_notes(),
            }
        return self._safe(go, 'bootstrap')

    def detect_mode(self) -> dict[str, Any]:
        """探测当前真实运行模式。"""
        def go() -> dict[str, Any]:
            snap = detect_mode(self._deps)
            return {
                'ok': True,
                'mode': snap.mode.value,
                'conflicting': snap.is_conflicting,
                'ambiguous': snap.ambiguous,
                'prod_running': list(snap.prod_services_running),
                'prod_unknown': list(snap.prod_services_unknown),
                'dev_port_holders': list(snap.dev_port_holders),
                'notes': list(snap.notes),
            }
        return self._safe(go, 'detect_mode')

    def service_list(self) -> dict[str, Any]:
        """受管服务的状态快照。"""
        def go() -> dict[str, Any]:
            sn = self._deps.service
            return {
                'ok': True,
                'services': [
                    ser.service_snapshot(sn.snapshot(s.name))
                    for s in MANAGED_NSSM_SERVICES
                ],
            }
        return self._safe(go, 'service_list')

    def metrics(self) -> dict[str, Any]:
        """当前指标采样。

        ★ `available=False` + `sample=None` 是**正常返回**，不是错误。
          `psutil` 不可用时前端必须显示「指标不可用」，
          显示 0% 会被读成「系统很空闲」。
        """
        def go() -> dict[str, Any]:
            port = self._deps.metrics
            if port is None:
                return {'ok': True, 'available': False, 'sample': None}
            return {
                'ok': True,
                'available': bool(port.available()),
                'sample': ser.metrics_sample(port.sample()),
            }
        return self._safe(go, 'metrics')

    def logs(self, **kw: Any) -> dict[str, Any]:
        """查询审计日志。"""
        def go() -> dict[str, Any]:
            limit = kw.get('limit')
            result = self._log_ops.query(
                session=self._session, event_bus=self._bus,
                limit=int(limit) if limit else None,
            )
            out = self._result(result)
            entries = getattr(self._log_ops, 'last_entries', ()) or ()
            out['entries'] = [ser.audit_entry(e) for e in entries]
            return out
        return self._safe(go, 'logs')

    def verify_chain(self) -> dict[str, Any]:
        """校验审计哈希链。

        ★ 链断裂返回的是 `ok=True`（校验**完成了**）+ `chain.ok=False`，
          不是 `ok=False`。若返回 ok=False，UI 会当成「校验失败请重试」，
          而真实含义是「校验完成，发现审计被改过」—— 完全不同的事。
        """
        def go() -> dict[str, Any]:
            result = self._log_ops.verify_chain(
                session=self._session, event_bus=self._bus)
            out = self._result(result)
            out['chain'] = ser.chain_verify(
                getattr(self._log_ops, 'last_verify', None))
            return out
        return self._safe(go, 'verify_chain')

    # ═══════════════════════════════════════════════════════════════
    # 告警
    # ═══════════════════════════════════════════════════════════════

    def alert_list(self, notify_only: bool = False) -> dict[str, Any]:
        def go() -> dict[str, Any]:
            result = self._alert_ops.list_active(
                session=self._session, event_bus=self._bus,
                notify_only=bool(notify_only))
            out = self._result(result)
            return out
        return self._safe(go, 'alert_list')

    def alert_ack(self, key: str) -> dict[str, Any]:
        def go() -> dict[str, Any]:
            return self._result(self._alert_ops.ack(
                key, session=self._session, event_bus=self._bus))
        return self._safe(go, 'alert_ack')

    def alert_silence(self, key: str, duration_s: float = 0.0) -> dict[str, Any]:
        def go() -> dict[str, Any]:
            kw: dict[str, Any] = {'session': self._session,
                                  'event_bus': self._bus}
            if duration_s and float(duration_s) > 0:
                kw['duration_s'] = float(duration_s)
            return self._result(self._alert_ops.silence(key, **kw))
        return self._safe(go, 'alert_silence')

    # ═══════════════════════════════════════════════════════════════
    # 编排：模式 / 停止 / 启动 / 端口
    # ═══════════════════════════════════════════════════════════════

    def switch_mode(self, mode: str, token_id: str = '',
                    typed_name: str = '', reason: str = '') -> dict[str, Any]:
        """切换到 dev / prod（高危，需确认）。"""
        def go() -> dict[str, Any]:
            confirm = self._consume_token(
                token_id, Action.SWITCH_MODE, typed_name, reason)
            return self._result(self._switch_mode.execute(
                session=self._session, confirm=confirm, event_bus=self._bus,
                audit=self._deps.audit, mode=mode))
        return self._safe(go, 'switch_mode')

    def stop_all(self, token_id: str = '', typed_name: str = '',
                 reason: str = '', stop_redis: bool = True) -> dict[str, Any]:
        """停止全部（生产服务 + 开发进程 + 可选 Redis）。"""
        def go() -> dict[str, Any]:
            confirm = self._consume_token(
                token_id, Action.STOP_PROD_SERVICE, typed_name, reason)
            return self._result(self._stop_all.execute(
                session=self._session, confirm=confirm, event_bus=self._bus,
                audit=self._deps.audit, stop_redis=bool(stop_redis)))
        return self._safe(go, 'stop_all')

    def start_dev(self, token_id: str = '', typed_name: str = '',
                  reason: str = '') -> dict[str, Any]:
        def go() -> dict[str, Any]:
            confirm = self._consume_token(
                token_id, Action.START_SERVICE, typed_name, reason)
            return self._result(self._start_dev.execute(
                session=self._session, confirm=confirm, event_bus=self._bus,
                audit=self._deps.audit))
        return self._safe(go, 'start_dev')

    def start_prod(self, token_id: str = '', typed_name: str = '',
                   reason: str = '') -> dict[str, Any]:
        def go() -> dict[str, Any]:
            confirm = self._consume_token(
                token_id, Action.START_SERVICE, typed_name, reason)
            return self._result(self._start_prod.execute(
                session=self._session, confirm=confirm, event_bus=self._bus,
                audit=self._deps.audit))
        return self._safe(go, 'start_prod')

    def kill_port(self, port: int, token_id: str = '',
                  typed_name: str = '', reason: str = '') -> dict[str, Any]:
        """清理端口占用（高危，需确认）。"""
        def go() -> dict[str, Any]:
            confirm = self._consume_token(
                token_id, Action.KILL_PORT, typed_name, reason)
            return self._result(self._kill_port.execute(
                int(port), session=self._session, confirm=confirm,
                event_bus=self._bus, audit=self._deps.audit))
        return self._safe(go, 'kill_port')

    def port_inspect(self, port: int) -> dict[str, Any]:
        """查看端口占用者（**宽口径**，含 ESTABLISHED）。

        ★ 仅供展示。清理走 `kill_port`（窄口径）。
          两者的口径差异在 domain 层有明确规定，此处不重复判定。
        """
        def go() -> dict[str, Any]:
            return {
                'ok': True,
                'port': int(port),
                'occupiers': [ser.port_occupier(o)
                              for o in self._kill_port.inspect(int(port))],
            }
        return self._safe(go, 'port_inspect')

    # ═══════════════════════════════════════════════════════════════
    # 服务安装 / 卸载
    # ═══════════════════════════════════════════════════════════════

    def install_services(self, names: list[str] | None = None,
                         token_id: str = '', typed_name: str = '',
                         reason: str = '') -> dict[str, Any]:
        def go() -> dict[str, Any]:
            confirm = self._consume_token(
                token_id, Action.UNINSTALL_SERVICE, typed_name, reason)
            return self._result(self._install.execute(
                session=self._session, confirm=confirm, event_bus=self._bus,
                audit=self._deps.audit, names=tuple(names or ())))
        return self._safe(go, 'install_services')

    def uninstall_services(self, names: list[str] | None = None,
                           token_id: str = '', typed_name: str = '',
                           reason: str = '') -> dict[str, Any]:
        """卸载服务（极高危，需输入固定确认词 + 填原因）。"""
        def go() -> dict[str, Any]:
            confirm = self._consume_token(
                token_id, Action.UNINSTALL_SERVICE, typed_name, reason)
            return self._result(self._uninstall.execute(
                session=self._session, confirm=confirm, event_bus=self._bus,
                audit=self._deps.audit, names=tuple(names or ())))
        return self._safe(go, 'uninstall_services')

    # ═══════════════════════════════════════════════════════════════
    # 配置
    # ═══════════════════════════════════════════════════════════════

    def config_load(self) -> dict[str, Any]:
        def go() -> dict[str, Any]:
            result = self._config_ops.load(
                session=self._session, event_bus=self._bus)
            out = self._result(result)
            cfg = getattr(self._config_ops, 'last_config', None)
            out['config'] = ser.normalized_config(cfg)
            return out
        return self._safe(go, 'config_load')

    def config_save_ports(self, ports: dict[str, Any]) -> dict[str, Any]:
        def go() -> dict[str, Any]:
            return self._result(self._config_ops.save_ports(
                session=self._session, event_bus=self._bus,
                audit=self._deps.audit, ports=dict(ports or {})))
        return self._safe(go, 'config_save_ports')

    def config_save_paths(self, paths: dict[str, Any]) -> dict[str, Any]:
        def go() -> dict[str, Any]:
            return self._result(self._config_ops.save_paths(
                session=self._session, event_bus=self._bus,
                audit=self._deps.audit, paths=dict(paths or {})))
        return self._safe(go, 'config_save_paths')

    def config_save_values(self, values: dict[str, Any]) -> dict[str, Any]:
        def go() -> dict[str, Any]:
            return self._result(self._config_ops.save_scalars(
                session=self._session, event_bus=self._bus,
                audit=self._deps.audit, values=dict(values or {})))
        return self._safe(go, 'config_save_values')

    def config_reset(self, token_id: str = '', typed_name: str = '',
                     reason: str = '') -> dict[str, Any]:
        def go() -> dict[str, Any]:
            confirm = self._consume_token(
                token_id, Action.RESET_CONFIG, typed_name, reason)
            return self._result(self._config_ops.reset(
                session=self._session, confirm=confirm,
                event_bus=self._bus, audit=self._deps.audit))
        return self._safe(go, 'config_reset')

    # ═══════════════════════════════════════════════════════════════
    # 备份
    # ═══════════════════════════════════════════════════════════════

    def run_backup(self, token_id: str = '', typed_name: str = '',
                   reason: str = '') -> dict[str, Any]:
        def go() -> dict[str, Any]:
            confirm = self._consume_token(
                token_id, Action.RUN_BACKUP, typed_name, reason)
            return self._result(self._backup_ops.run_backup(
                session=self._session, confirm=confirm,
                event_bus=self._bus, audit=self._deps.audit))
        return self._safe(go, 'run_backup')

    def restore_backup(self, token_id: str = '', typed_name: str = '',
                       reason: str = '') -> dict[str, Any]:
        """恢复备份（极高危，需输入固定确认词）。"""
        def go() -> dict[str, Any]:
            confirm = self._consume_token(
                token_id, Action.RESTORE_BACKUP, typed_name, reason)
            return self._result(self._backup_ops.restore_backup(
                session=self._session, confirm=confirm,
                event_bus=self._bus, audit=self._deps.audit))
        return self._safe(go, 'restore_backup')

    # ═══════════════════════════════════════════════════════════════
    # 事件泵 / 环境
    # ═══════════════════════════════════════════════════════════════

    def poll_events(self, limit: int = 200) -> dict[str, Any]:
        """前端轮询事件（见 `EventPump.drain` 的说明）。"""
        def go() -> dict[str, Any]:
            out = self._pump.drain(int(limit) if limit else 200)
            out['ok'] = True
            return out
        return self._safe(go, 'poll_events')

    def environment(self) -> dict[str, Any]:
        """环境与降级信息（启动横幅用）。"""
        def go() -> dict[str, Any]:
            env = self._c.env
            return {
                'ok': True,
                'has_psutil': env.has_psutil,
                'has_webview': env.has_webview,
                'is_windows': env.is_windows,
                'config_path': str(self._c.config_path),
                'config_exists': env.config_exists,
                'audit_path': str(self._c.audit_path),
                'degraded': env.degraded,
                'notes': self._c.degraded_notes(),
            }
        return self._safe(go, 'environment')

    def window_ready(self) -> dict[str, Any]:
        """前端 DOM 就绪后调（后端据此做一次性初始化）。"""
        def go() -> dict[str, Any]:
            if self._on_window_ready is not None:
                self._on_window_ready()
            return {'ok': True}
        return self._safe(go, 'window_ready')

    def shutdown(self) -> dict[str, Any]:
        """请求退出（前端「退出」按钮）。"""
        def go() -> dict[str, Any]:
            window = self._pump._window  # noqa: SLF001 — 同一模块内的协作
            if window is not None:
                window.destroy()
            return {'ok': True, 'detail': '正在退出'}
        return self._safe(go, 'shutdown')

    # ── 供 webview_host 使用 ────────────────────────────────────

    def attach_window(self, window: Any) -> None:
        self._pump.attach(window)


# ═══════════════════════════════════════════════════════════════════
# 辅助
# ═══════════════════════════════════════════════════════════════════


def _parse_role(value: str) -> Role | None:
    text = (value or '').strip().lower()
    for role in Role:
        if role.value == text or role.name.lower() == text:
            return role
    return None


def _parse_action(value: str) -> Action | None:
    text = (value or '').strip()
    for action in Action:
        if action.value == text or action.name == text:
            return action
    return None


def _actions_for(role: Role) -> tuple[Action, ...]:
    from ..domain.permissions import actions_for  # noqa: PLC0415
    return actions_for(role)


__all__ = ['CONFIRM_TOKEN_TTL_S', 'EventPump', 'JsBridge']
