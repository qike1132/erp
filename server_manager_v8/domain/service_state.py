"""服务状态语义 —— 纯逻辑，零 I/O。

本模块从 server_manager.py 迁移而来（v5.40），**逐行搬运，未做行为改动**。

═══════════════════════════════════════════════════════════════════
四态语义（这是用真实生产事故换来的设计，勿回退）
═══════════════════════════════════════════════════════════════════

    RUNNING  / STOPPED  / 未知  / 未安装

「未知」与「未安装」必须严格区分：
    只有 rc == 1060（ERROR_SERVICE_DOES_NOT_EXIST）才判「未安装」；
    其它任何非 0 返回码（5=拒绝访问、被安全软件拦截、超时、异常）一律判「未知」。
    「未知」在业务上按**运行中**保守处理 —— 确认不了停止就中止模式切换。

绝不能把「查不出来」当成「不存在」——否则 _ensure_production_stopped 会静默跳过
仍在运行的生产服务，开发模式随即抢占 5002/3000，与生产互相厮杀。

事故溯源：
    v5.36 堵住「开发/生产互杀」事故，引入三态语义
    v5.39 审查 #1 —— 裸写 `'1060' in out` 使防线自身成为新洞（运行中服务的
            输出含 `PID : 1060` 时被误判未安装）→ v5.40 加 `and 'STATE' not in out`
"""

from __future__ import annotations

from enum import Enum

# ── 状态字面量（对外契约，勿改字符串值：UI 与配置均按字面量匹配） ──
STATE_ABSENT = '未安装'
STATE_UNKNOWN = '未知'


class ServiceStatus(Enum):
    """服务状态的领域枚举。

    RUNNING / STOPPED / 其它中间的 SCM 状态（START_PENDING、STOP_PENDING…）
    统一由 `raw` 承载原始 STATE 文本；查询失败走 UNKNOWN；确认不存在走 ABSENT。
    """

    RUNNING = 'running'
    STOPPED = 'stopped'
    PENDING = 'pending'      # START_PENDING / STOP_PENDING / PAUSED 等中间态
    UNKNOWN = 'unknown'      # 查询失败（拒绝访问 / 超时 / 异常）—— 按运行中保守处理
    ABSENT = 'absent'        # 明确不存在（rc == 1060）

    @property
    def is_absent(self) -> bool:
        return self is ServiceStatus.ABSENT

    @property
    def is_unknown(self) -> bool:
        return self is ServiceStatus.UNKNOWN

    @property
    def is_conservatively_running(self) -> bool:
        """保守判定：未知一律视为「可能仍在运行」。

        业务含义：模式切换的前置停止守卫，遇到此状态**不得放行**。
        """
        return self in (ServiceStatus.RUNNING, ServiceStatus.PENDING, ServiceStatus.UNKNOWN)


def is_absent(state: str) -> bool:
    """服务状态的「未安装」判定（统一入口，避免字面量散落各调用点）。"""
    return STATE_ABSENT in state


def is_unknown(state: str) -> bool:
    """服务状态的「查询失败/未知」判定 —— 语义上必须与「未安装」严格区分。"""
    return state == STATE_UNKNOWN


def classify(raw_state: str) -> ServiceStatus:
    """把 sc STATE 文本分类为领域枚举。

    `raw_state` 形如 '4 RUNNING' / '1 STOPPED' / '3 STOP_PENDING'，或
    STATE_ABSENT / STATE_UNKNOWN 两个哨兵值。

    注意：用**前缀数字**判定，因为 sc 输出的 STATE 行格式是 '<code> <TEXT>'，
    文本受系统语言影响（中文系统可能是「正在运行」），故数字才是稳定锚点。
    """
    if is_absent(raw_state):
        return ServiceStatus.ABSENT
    if is_unknown(raw_state):
        return ServiceStatus.UNKNOWN
    head = raw_state.strip().split(' ', 1)[0]
    if head == '4':
        return ServiceStatus.RUNNING
    if head == '1':
        return ServiceStatus.STOPPED
    # 2=START_PENDING 3=STOP_PENDING 5=PAUSE_PENDING 6=PAUSED 7=CONTINUE_PENDING
    if head in ('2', '3', '5', '6', '7'):
        return ServiceStatus.PENDING
    return ServiceStatus.UNKNOWN


def parse_sc_query_output(code: int, out: str) -> str:
    """sc query 输出 → 服务状态文本（SENTINEL 或 STATE 行文本）。纯函数，供单测。

    ★ v5.40 修复（审查 #1）：「未安装」只认 rc==1060，或输出是 1060 错误文本
      且【没有】STATE 行。旧版裸写 `'1060' in out` —— 运行中服务的输出含
      `PID : 1060` 时（开机早期自启服务的 PID 完全可能落在 1060）会被误判
      「未安装」，导致 _ensure_production_stopped 跳过停止，开发模式直接抢占
      5002/3000 与生产互杀 —— 恰好复发 v5.36 堵住的互杀事故。

    迁移自 server_manager.py L127 `_parse_sc_state()`，行为完全一致。
    """
    if code == 1060 or ('1060' in out and 'STATE' not in out):
        return STATE_ABSENT
    if code != 0 or 'SERVICE_NAME' not in out:
        return STATE_UNKNOWN
    for line in out.splitlines():
        if 'STATE' in line:
            parts = line.split(':', 1)
            if len(parts) > 1:
                return ' '.join(parts[1].split())[:28]
    return STATE_UNKNOWN


def parse_sc_queryex_pid(out: str) -> int | None:
    """sc queryex 输出 → 服务当前进程 PID；未运行返回 None。

    迁移自 server_manager.py L1396 `_svc_pid()` 的解析部分（剥离 subprocess）。
    """
    for line in out.splitlines():
        stripped = line.strip()
        if stripped.startswith('PID'):
            parts = stripped.split(':', 1)
            if len(parts) > 1 and parts[1].strip().isdigit():
                return int(parts[1].strip())
    return None
