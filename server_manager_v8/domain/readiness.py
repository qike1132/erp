"""就绪判定规则 —— 纯逻辑，零 I/O，时间由调用方注入。

本模块从 server_manager.py（v5.40）迁移而来，**逐行搬运，未做行为改动**。

═══════════════════════════════════════════════════════════════════
为什么需要它
═══════════════════════════════════════════════════════════════════

原实现把「轮询直到满足条件」复制成了 4 处不同写法：

    _wait_http(url, attempts, timeout)              L1291  固定 attempts 次
    _wait_service_running(name, timeout)            L1436  按 deadline 轮询
    _wait_service_stopped(name, timeout)            L1410  按 deadline 轮询
    _wait_redis_svc_running(name, timeout)          L935   按 deadline 轮询

四者共享同一模式但各写一遍，导致：
    · 超时预算语义不一致（attempts 次 vs deadline）
    · 都无法单测（内部含 time.sleep 与 subprocess）
    · v8 方案 D15 指出的「健康检查写死 30×1s」正是这种散落的后果

本模块把这些收敛为**一个判定原语 + 若干纯谓词**：

    WaitPolicy         —— 等待策略（超时预算、轮询间隔、连续成功门槛）
    WaitOutcome        —— 等待结果（达成/超时/中止 + 已用时长 + 最后一次观测）
    wait_until(...)    —— 通用原语，时间与探针均由调用方注入（本层零 I/O）
    combine_all/any    —— 多路谓词组合（对应 _wait_service_running 的
                          「RUNNING + /api/health + /nginx-health 三项全过」）

借鉴来源（见重构方案 §2.3）：
    · kubernetes-sigs/kind —— readiness 门闩：声明式「等 X 就绪再做 Y」
    · louislam/uptime-kuma —— 探针状态机：连续失败 N 次才判 DOWN（去抖动）
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import Enum

from .service_state import ServiceStatus, classify

# ═══════════════════════════════════════════════════════════════════
# 等待结果
# ═══════════════════════════════════════════════════════════════════


class WaitStatus(Enum):
    """等待的三种终局。"""

    SATISFIED = 'satisfied'   # 谓词达成
    TIMEOUT = 'timeout'       # 超过超时预算仍未达成
    ABORTED = 'aborted'       # 被外部中止（如用户点了取消 / 已有更高优先级动作）

    @property
    def ok(self) -> bool:
        return self is WaitStatus.SATISFIED


@dataclass(frozen=True)
class WaitOutcome:
    """等待结果详情。

    保留 `attempts` 与 `last_observation` 是刻意的：
    失败时日志/UI 需要说清「试了几次、最后一次看到什么」，
    否则运维只能看到一句「超时」而无从下手（v5.33「停不掉」的教训之一：
    失败必须带真实原因，不能是空洞的成功/失败）。
    """

    status: WaitStatus
    attempts: int = 0
    elapsed_s: float = 0.0
    last_observation: str | None = None

    @property
    def ok(self) -> bool:
        return self.status is WaitStatus.SATISFIED

    @property
    def timed_out(self) -> bool:
        return self.status is WaitStatus.TIMEOUT

    @property
    def aborted(self) -> bool:
        return self.status is WaitStatus.ABORTED

    def failure_reason(self, subject: str) -> str | None:
        """生成给运维看的失败原因（成功时返回 None）。"""
        if self.ok:
            return None
        if self.aborted:
            return f'{subject} 等待被中止'
        seen = f'，最后观测: {self.last_observation}' if self.last_observation else ''
        return f'{subject} 未在 {self.elapsed_s:.0f}s 内就绪（尝试 {self.attempts} 次{seen}）'


# ═══════════════════════════════════════════════════════════════════
# 等待策略
# ═══════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class WaitPolicy:
    """等待策略。

    timeout_s      —— 总超时预算（秒）
    interval_s     —— 两次轮询间隔（秒）
    consecutive_ok —— 需连续满足几次才判达成（去抖动，默认 1）

    `consecutive_ok > 1` 借鉴 uptime-kuma：单次探测成功可能是偶然
    （服务正在启动、探针命中了旧进程），连续 N 次才确认可显著降低误判。
    对应地，它也会消耗更多时间预算，须计入 timeout。
    """

    timeout_s: float = 30.0
    interval_s: float = 1.0
    consecutive_ok: int = 1

    def __post_init__(self) -> None:
        if self.timeout_s <= 0:
            raise ValueError('timeout_s 必须为正数')
        if self.interval_s <= 0:
            raise ValueError('interval_s 必须为正数')
        if self.consecutive_ok < 1:
            raise ValueError('consecutive_ok 必须 >= 1')

    @property
    def max_attempts(self) -> int:
        """在预算内最多轮询几次（至少 1 次，保证短超时也会探测一次）。"""
        return max(1, int(self.timeout_s // self.interval_s) + 1)


# ── 项目现用的策略（迁移自各 _wait_* 的默认值，勿随意改） ──

#: _wait_service_stopped(name, timeout=45)
POLICY_SERVICE_STOPPED = WaitPolicy(timeout_s=45.0, interval_s=1.0)
#: _wait_service_running(name, timeout=60)
POLICY_SERVICE_RUNNING = WaitPolicy(timeout_s=60.0, interval_s=1.0)
#: _wait_redis_svc_running(name, timeout=30)
POLICY_REDIS_SERVICE = WaitPolicy(timeout_s=30.0, interval_s=1.0)
#: _wait_http(url, attempts=30) —— 后端健康检查
POLICY_HTTP_BACKEND = WaitPolicy(timeout_s=30.0, interval_s=1.0)
#: _wait_http(url, attempts=60) —— 前端健康检查
POLICY_HTTP_FRONTEND = WaitPolicy(timeout_s=60.0, interval_s=1.0)


# ═══════════════════════════════════════════════════════════════════
# 谓词组合
# ═══════════════════════════════════════════════════════════════════


def combine_all(predicates: Sequence[Callable[[], bool]]) -> Callable[[], bool]:
    """全部满足才算满足（对应 _wait_service_running 的三项全过语义）。

    注意语义细节：**无短路**——四个谓词都会被调用。
    原 `_wait_service_running` 正是这样做的（api_ready / web_ready 各自缓存，
    每轮都尝试推进），因为「已经就绪的探针不再重探」是有意设计：
    避免已就绪的前端探针在每轮重复占用超时预算。
    调用方负责缓存已成功项（见 combine_all_cached）。
    """
    preds = tuple(predicates)

    def _check() -> bool:
        return all(p() for p in preds)

    return _check


def combine_all_cached(
    probes: Sequence[tuple[str, Callable[[], bool]]],
) -> tuple[Callable[[], bool], dict[str, bool]]:
    """带缓存的「全部满足」——已成功的探针不再重探。

    这是 `_wait_service_running` 的精确语义迁移：

        if not api_ready:
            api_ready = self._probe_http(...)   # 只探未就绪的
        if need_web and not web_ready:
            web_ready = self._probe_http(...)

    返回 (谓词, 状态字典)。状态字典由调用方持有并在轮次间复用。

    参数：probes = [('api', probe_fn), ('web', probe_fn2), ...]
    """
    items = tuple(probes)
    state: dict[str, bool] = {name: False for name, _ in items}

    def _check() -> bool:
        for name, probe in items:
            if not state[name]:
                state[name] = probe()
        return all(state.values())

    return _check, state


def combine_any(predicates: Sequence[Callable[[], bool]]) -> Callable[[], bool]:
    """任一满足即满足（短路）。"""
    preds = tuple(predicates)
    return lambda: any(p() for p in preds)


# ═══════════════════════════════════════════════════════════════════
# 通用等待原语
# ═══════════════════════════════════════════════════════════════════


def wait_until(
    predicate: Callable[[], bool],
    policy: WaitPolicy | None = None,
    *,
    clock: Callable[[], float],
    sleep: Callable[[float], None],
    aborted: Callable[[], bool] | None = None,
    observe: Callable[[], str] | None = None,
) -> WaitOutcome:
    """轮询直到谓词满足、超时、或被中止。

    ★ 本层零 I/O：`clock`（取单调时间）与 `sleep`（等待）均由调用方注入，
    探针 `predicate` 亦然。这样纯逻辑可 100% 单测（注入假时钟即可）。

    参数：
        predicate —— 返回 True 表示已就绪
        policy    —— 等待策略，默认 WaitPolicy()
        clock     —— 取当前时间（应传 time.monotonic）
        sleep     —— 睡 interval_s 秒（应传 time.sleep）
        aborted   —— 可选，返回 True 表示应放弃等待（如用户取消）
        observe   —— 可选，返回一句「当前观测到什么」，用于失败原因

    返回：WaitOutcome

    行为契约（**精确对齐原实现**，见下方「时序语义」）：
        1. 每轮先检查中止，再判 deadline，最后探测
        2. 达成后若 consecutive_ok > 1，需连续满足才返回 SATISFIED
        3. 每次探测后 sleep(interval_s)，随后回到循环顶部
        4. 中止检查优先于超时判断

    ★ 时序语义（迁移保真，勿改）
    --------------------------------
    原 `_wait_service_running` / `_wait_service_stopped` 的结构是：

        deadline = monotonic() + timeout
        while monotonic() < deadline:
            探测...
            sleep(1)

    即「**先判超时、后探测**」。在注入时钟下的实测结果：

        timeout=5.0 → 探测 5 次（t=0,1,2,3,4）
        timeout=3.0 → 探测 3 次
        timeout=0.5 → 探测 1 次（t=0 时 0<0.5 成立）
        timeout=1.0 → 探测 1 次

    由于 `WaitPolicy` 已禁止非正 timeout，本原语**不可能**出现零次探测，
    故无需「先探测后判超时」的额外保护 —— 保持原语义即最安全。
    """
    pol = policy or WaitPolicy()
    start = clock()
    deadline = start + pol.timeout_s
    attempts = 0
    streak = 0
    last_obs: str | None = None

    while clock() < deadline:
        if aborted is not None and aborted():
            return WaitOutcome(
                status=WaitStatus.ABORTED,
                attempts=attempts,
                elapsed_s=clock() - start,
                last_observation=last_obs,
            )

        attempts += 1
        satisfied = bool(predicate())
        if observe is not None:
            last_obs = _safe_observe(observe)

        if satisfied:
            streak += 1
            if streak >= pol.consecutive_ok:
                return WaitOutcome(
                    status=WaitStatus.SATISFIED,
                    attempts=attempts,
                    elapsed_s=clock() - start,
                    last_observation=last_obs,
                )
        else:
            streak = 0

        sleep(pol.interval_s)

    return WaitOutcome(
        status=WaitStatus.TIMEOUT,
        attempts=attempts,
        elapsed_s=clock() - start,
        last_observation=last_obs,
    )


def _safe_observe(observe: Callable[[], str]) -> str | None:
    """观测函数绝不能让等待本身崩溃（诊断不得打断主流程）。

    事故溯源：v5.38 的 D15 —— 诊断代码抛 AttributeError 打断了两条清场链。
    """
    try:
        return observe()
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════════
# 谓词构造器（把领域状态转成可直接喂给 wait_until 的谓词）
# ═══════════════════════════════════════════════════════════════════


def is_running_predicate(state_provider: Callable[[], str]) -> Callable[[], bool]:
    """服务 RUNNING 谓词。

    原实现用 `'RUNNING' not in self._svc_state(name)` —— 子串判定。
    这里改为**经 classify 的语义判定**：只认 RUNNING，不认 STOP_PENDING
    （后者文本里不含 RUNNING 但也不该被当成就绪）。

    注意：与 `_wait_service_running` 行为一致——原文就是等 'RUNNING' in state。
    """
    def _check() -> bool:
        return classify(state_provider()) is ServiceStatus.RUNNING

    return _check


def is_stopped_predicate(state_provider: Callable[[], str]) -> Callable[[], bool]:
    """服务 STOPPED 谓词。

    原 `_wait_service_stopped` 等的是 STOPPED 确认（而非 returncode），
    因为 STOP_PENDING 期间强杀被管进程会被 AppExit 判定崩溃而自动重启。
    """
    def _check() -> bool:
        return classify(state_provider()) is ServiceStatus.STOPPED

    return _check


def is_not_conservatively_running(state_provider: Callable[[], str]) -> Callable[[], bool]:
    """「已确认停止」谓词 —— 用于模式切换的前置守卫。

    与 is_stopped_predicate 的区别：本谓词把「未安装」也算作可放行
    （服务不存在自然无需停止），但「未知」**不放行**。

    这正是 _ensure_production_stopped 的核心安全性质：
        查询失败 + 无法确认停止 → 必须返回 ok=False，中止切换，绝不抢端口。
    """
    def _check() -> bool:
        return classify(state_provider()) in (ServiceStatus.STOPPED, ServiceStatus.ABSENT)

    return _check
