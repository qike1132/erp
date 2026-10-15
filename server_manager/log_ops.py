"""server_manager 包的日志运维层：生产日志实时回灌 + 日志文件保留清理(v5.34)。

从 app.py 抽出(与 ``service_ops`` / ``redis_ops`` / ``dev_mode`` 同一边界)：
本模块【只能】依赖标准库与 ``server_manager.constants`` —— 不得 import tkinter
(UI 更新一律经 ``msg_queue`` 交回主线程)，也不得反向 import 本包的 app(循环导入)。

■ 为什么需要 ``ProdLogTailer``(用户实测缺陷:「生产模式打开后运行日志不是实时输出」)
  开发模式的两个子进程由 manager 自己 ``Popen``，stdout 是管道，读到什么就实时
  显示什么(见 ``dev_mode.read_stdout``)。而生产模式跑在 NSSM 服务里，stdout 被
  NSSM 重定向到 ``logs\\{service}.log``，manager 与子进程之间**没有管道** ——
  原实现只在「启动服务」那一刻回灌一次新增字节(``app._start_services_flow``)，
  此后界面一片安静，直到下一次点击才有输出。本类以 1s 轮询补齐这条管道
  (等价于 ``tail -f``)，并对 erp-prod / erp-arq / erp-web 三个服务日志逐一跟踪。

■ 为什么需要 ``prune_log_files``(用户诉求:「日志功能增加一个定时清理，不然越来越多」)
  写入方各管各的：NSSM 只按 ``AppRotateBytes=10MB`` 轮转、**从不删除**旧副本；
  后端 ``fastapi_*.log`` 由自己的 handler 保留 14 天；而 ``server_manager_YYYYMMDD.log``
  每天新增一个且永不清理。没人清就必然只增不减(2026-09-30 现场:``logs/`` 51MB、
  21 个文件，其中 ``erp.log``/``error.log``/``fastapi_*`` 各已 9–15MB)。
  按「最后写入时间」删是对所有写入方都成立的不变量，不需要知道各自的命名规则。

■ 轮转/保留/巡检三件事的**机制**已在 ``utils/log_rotation.py``（与后端 ARQ cron、
  prod_runner 共用同一份实现与同一份策略文件 ``config/log_policy.json``）：
  · 轮转：给无人管的日志止血（NSSM 只转自己的、nginx 靠 ARQ、管理器自己的从不轮转）；
  · 保留：按最后写入时间 + 目录体积上限删旧文件；
  · 巡检：两次采样算字节/天，回答「谁在疯长」（本模块独有，见下）。
  本模块只保留「界面侧运维」与巡检，并把上面那些名字重新导出给 ``log_view`` ——
  不这么做的话，管理器与后端就会各有一份阈值、各写一遍 copytruncate（2026-09-30 前
  的真实状态：同一个机器上「多大该轮转」有三个答案）。

■ 为什么必须用显式 path 读策略
  ``utils/log_rotation.default_policy_path()`` 基于 ``__file__`` 推算，而打包后的 exe
  里 ``__file__`` 指向解包临时目录 —— 会算出不存在的路径并静默回落默认值。
  故管理器一律显式传 ``path``（见 ``log_view`` 用 ``_PROJECT_DIR`` 拼路径）。

■ 为什么需要 ``inspect_log_health``(用户诉求:「列出谁在疯长，异常增长时告警」)
  保留清理只回答「过期了没」，它**不解释增长**:同为 100MB，一个安静攒了 14 天的
  访问日志与一个崩溃循环半小时刷出来的错误栈，处置完全不同。增长率只能靠
  **两次采样**算：每次巡检把 (大小, 时间) 落一份状态快照，下一轮相减得字节/天。
  这正是「谁在疯长」的唯一可靠来源(比按 mtime 猜「最近活跃」准确得多)。
"""
from __future__ import annotations

import contextlib
import json
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from server_manager.constants import _SVC_API, _SVC_ARQ, _SVC_WEB
from server_manager.service_ops import decode_output

# 轮转 / 保留 / 策略的**唯一实现**在 utils/log_rotation.py（与后端 ARQ cron、prod_runner
# 共用）。这里全部重新导出：log_view 与测试仍从本模块取名字，机制却只有一份。
# （utils 包已改为惰性导出，故这条 import 不会把 openpyxl/polars 拉进打包 exe。）
from utils.log_rotation import (
    DEFAULT_LOG_POLICY,
    LOG_MIN_AGE_SECONDS,
    LogPolicy,
    LogPruneReport,
    LogRotationReport,
    human_bytes,
    iter_log_files,
    load_log_policy,
    policy_from_fields,
    prune_log_files,
    rotate_file_copytruncate,
    rotate_oversized_logs,
    safe_mtime,
    save_log_policy,
)

# 本模块对 UI 层（log_view）与测试的公开面：既含自有的回灌/巡检，也含从
# utils.log_rotation **重新导出**的机制名。列进 __all__ 是为了让「这里只是中转、
# 不是各自实现」在静态检查层面也成立（否则 ruff F401 会把中转当成漏用的 import）。
__all__ = [
    'DEFAULT_LOG_POLICY',
    'LOG_ALERT_BYTES_PER_DAY',
    'LOG_HEALTH_STATE_NAME',
    'LOG_KEEP_DAYS',
    'LOG_MAX_TOTAL_BYTES',
    'LOG_MIN_AGE_SECONDS',
    'LOG_ROTATE_BYTES',
    'PROD_LOG_SERVICES',
    'LogFileStat',
    'LogHealthReport',
    'LogPolicy',
    'LogPruneReport',
    'LogRotationReport',
    'ProdLogTailer',
    'human_bytes',
    'inspect_log_health',
    'iter_log_files',
    'load_log_policy',
    'policy_from_fields',
    'prune_log_files',
    'rotate_file_copytruncate',
    'rotate_oversized_logs',
    'safe_mtime',
    'save_log_policy',
]

# 生产模式受跟踪的服务日志:与 NSSM 安装时写入的 AppStdout/AppStderr 同名(见 service_ops.nssm_install)
PROD_LOG_SERVICES = (_SVC_API, _SVC_ARQ, _SVC_WEB)

# 策略默认值的**唯一来源**是 utils.LogPolicy（config/log_policy.json 可覆盖）。
# 这三个名字保留作兼容别名：老调用点/文档写的是常量，而真相已经变成「策略对象」。
LOG_KEEP_DAYS = DEFAULT_LOG_POLICY.keep_days
LOG_MAX_TOTAL_BYTES = DEFAULT_LOG_POLICY.max_total_bytes
# 轮转阈值必须**高于** NSSM 的 AppRotateBytes(10MB)，否则会去动 NSSM 自己正在轮转的
# 服务日志（两边抢同一个文件）—— 该不变量在 utils.LogPolicy 的默认值里，且有测试锁住。
LOG_ROTATE_BYTES = DEFAULT_LOG_POLICY.rotate_bytes

# 巡检:单文件日增超过此值即视为「疯长」(现场安静运行时全目录约 1MB/h 级，
# 崩溃循环/DEBUG 泄漏会直接把它打穿，故 1GB/天 既不会误报也足够早报警)。
LOG_ALERT_BYTES_PER_DAY = 1024 * 1024 * 1024
# 巡检状态快照文件名:刻意**不含** '.log' —— 它自己不能被当成日志清理掉或统计进去。
LOG_HEALTH_STATE_NAME = 'log_health_state.json'


def _classify(text: str) -> str:
    """按内容粗判日志级别，让界面上的 ERROR/WARNING 有颜色(与开发模式前端读取一致)。

    刻意只做「包含即命中」的轻量判定:生产日志格式来自三方(uvicorn/arq/nginx)，
    没有统一级别字段可取；判错只影响颜色，不影响内容。
    """
    upper = text.upper()
    if 'ERROR' in upper or 'CRITICAL' in upper or 'TRACEBACK' in upper:
        return 'ERROR'
    if 'WARNING' in upper or 'WARN' in upper:
        return 'WARNING'
    return 'INFO'


def log_file_size(path) -> int:
    """日志文件当前字节数；读取失败返回 0（原 app._log_size，T9 收编，纯文件 IO）。"""
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def read_log_tail_lines(path, start_offset=0, lines=15, max_bytes=65536) -> list[str]:
    """读取日志文件自 start_offset 起新增内容的末尾 lines 行（有界读取）。

    NSSM 的 stdout/stderr 重定向是追加写：start 之前先记下文件大小，之后把
    「新增字节」的尾部回灌界面才是本次运行的输出；文件被轮转重开（大小小于
    offset）时按全新文件处理。历史日志绝不回灌。
    （原 app._read_log_lines，T9 收编 —— 纯文件 IO 住 ops 层。）
    """
    try:
        with open(path, 'rb') as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            if start_offset > size:
                # 文件被轮转重开（当前大小小于记录的 offset）：按全新文件处理
                begin = max(0, size - max_bytes)
            else:
                begin = max(start_offset, size - max_bytes, 0)
            f.seek(begin)
            raw = f.read().splitlines()
        return [ln.decode('utf-8', 'replace').strip() for ln in raw[-lines:] if ln.strip()]
    except OSError:
        return []


def _group_by_level(lines: list[str]):
    """把逐行级别归并成「同级别的连续段」，减少投递的消息条数。"""
    run: list[str] = []
    level = None
    for line in lines:
        cur = _classify(line)
        if cur != level and run:
            yield level, run
            run = []
        level = cur
        run.append(line)
    if run:
        yield level, run


class ProdLogTailer:
    """NSSM 服务日志(Python 侧无管道)的增量跟踪器 —— 生产模式的「实时输出」。

    与 app 的关系:``ServerManagerApp`` 持有实例 ``self.prod_logs``，由
    「生产服务是否在跑」驱动 ``ensure_started`` / ``stop``(幂等)；消息一律投
    ``msg_queue`` 的 ``log`` / ``log_batch``，绝不在本线程碰 Tk。
    """

    # 单轮单文件最多读多少新增字节；读不完的下一轮继续(offset 已推进)
    MAX_READ_BYTES = 65536
    # 单轮单文件最多回灌多少行;超出的留在读缓冲里下一轮继续(不丢内容，只是慢一点)
    MAX_LINES_PER_POLL = 200
    # 读缓冲上限:写入速度长期高于回灌速度时才触发，超出部分丢弃并明确告知
    MAX_PENDING_BYTES = 512 * 1024

    def __init__(self, msg_queue, project_dir, services=PROD_LOG_SERVICES, interval=1.0,
                 decode=decode_output):
        """``msg_queue`` / ``project_dir`` 由 app 注入；``interval`` 为轮询周期(秒)。

        ``decode`` 默认复用管理器**唯一的**字节流解码器
        (``service_ops.decode_output`` 模块级纯函数，含 UTF-16/GBK 回退):
        日志文件由 uvicorn/ARQ/nginx 按各自编码写入，再写一份只认 UTF-8 的
        解码器就会重演「中文日志乱码、排障被堵死」的老问题。
        """
        self._msg_queue = msg_queue
        self._log_dir = Path(project_dir) / 'logs'
        self._services = tuple(services)
        self._interval = interval
        self._decode = decode
        self._offsets: dict[str, int] = {}
        self._ids: dict[str, tuple | None] = {}
        self._pending: dict[str, bytes] = {}
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    # ── 生命周期 ────────────────────────────────────────────────────────────
    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def ensure_started(self) -> bool:
        """幂等接入实时输出；返回本次是否**新**接入(调用方据此避免重复提示)。

        起点取「当前 EOF」:接入前的历史输出绝不倒出来 —— 那是上一次运行的内容
        (旧 PID、旧崩溃栈)，把它当现状展示正是本项目反复踩过的坑。语义与开发模式
        「只显示本次进程的输出」一致；「启动服务」那一刻的新增字节由 app 的回灌
        负责，二者拼起来正好接上，不重不漏。
        """
        if self.running:
            return False
        self._offsets, self._ids, self._pending = {}, {}, {}
        for name in self._services:
            st = self._stat(name)
            self._offsets[name] = st.st_size if st else 0
            self._ids[name] = self._file_id(st) if st else None
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name='prod-log-tail', daemon=True)
        self._thread.start()
        self._msg_queue.put(('log', {
            'text': f"已接入生产日志实时输出（{'、'.join(self._services)} → logs 目录，{self._interval:g}s 轮询增量）"}))
        return True

    def stop(self) -> bool:
        """停止轮询(可重复调用)；返回此前是否在跑。"""
        thread = self._thread
        self._thread = None
        self._stop.set()
        if thread is None:
            return False
        thread.join(timeout=2)
        self._msg_queue.put(('log', {'text': '已停止生产日志实时输出'}))
        return True

    def _loop(self):
        while not self._stop.wait(self._interval):
            try:
                self.poll_once()
            except Exception as e:  # defensive: 单轮异常绝不能终止轮询线程(否则日志无声停摆)
                self._msg_queue.put(('log', {'text': f'生产日志轮询异常: {e}', 'level': 'WARNING'}))

    def poll_once(self):
        """把三个服务日志的新增内容回灌一次(测试直接调用，无需等轮询)。"""
        for name in self._services:
            if self._stop.is_set():
                return
            lines = self._read_new_lines(name)
            if lines:
                for level, run in _group_by_level(lines):
                    self._msg_queue.put(('log_batch', {'lines': [f'[{name}] {ln}' for ln in run], 'level': level}))

    # ── 增量读取 ────────────────────────────────────────────────────────────
    def _path(self, name) -> Path:
        return self._log_dir / f'{name}.log'

    def _stat(self, name):
        """文件的 stat；不存在/不可读返回 None(下一轮再看，绝不抛)。"""
        try:
            return self._path(name).stat()
        except OSError:
            return None

    @staticmethod
    def _file_id(st) -> tuple:
        """文件标识(卷 + 句柄号):被轮转「改名后新建」时必然不同。"""
        return (st.st_dev, st.st_ino)

    def _read_new_lines(self, name) -> list[str]:
        path = self._path(name)
        st = self._stat(name)
        if st is None:
            return []          # 文件还没创建(服务未起过)或暂时不可读 —— 下一轮再看
        offset = self._offsets.get(name, 0)
        if self._rotated(name, st, offset):
            # 轮转/截断:从头继续，并如实说明，免得界面内容跳变被当成故障
            self._offsets[name] = offset = 0
            self._pending[name] = b''
            self._msg_queue.put(('log', {'text': f'[{name}] 日志已轮转，继续实时输出新内容'}))
        self._ids[name] = self._file_id(st)
        try:
            with open(path, 'rb') as fh:
                fh.seek(offset)
                chunk = fh.read(self.MAX_READ_BYTES)
        except OSError:
            return []
        self._offsets[name] = offset + len(chunk)
        return self._consume(name, chunk)

    def _rotated(self, name, st, offset) -> bool:
        """轮转判据:文件被换掉(句柄号变)或 被就地截断(变小)。

        只比大小是不够的:NSSM 按大小轮转时把旧文件改名、新文件已从头写入，
        若新文件恰好已经长过旧 offset，照旧 offset 读会**静默吞掉新开头几行**
        ——「日志看着跳行」正是这么来的。句柄号（st_ino）换了就一定是新文件。
        """
        prev = self._ids.get(name)
        if prev is not None and prev != self._file_id(st):
            return True
        return st.st_size < offset

    def _consume(self, name, chunk) -> list[str]:
        """把新读到的字节切成完整行；不足一行的尾巴留在缓冲里等下一轮。"""
        data = self._pending.get(name, b'') + chunk
        raw_lines = data.split(b'\n')
        raw_lines.pop()                             # 末尾可能是不完整的行，留在缓冲里
        lines: list[str] = []
        consumed = 0
        for raw in raw_lines:
            if len(lines) >= self.MAX_LINES_PER_POLL:
                break                               # 超量:剩下的留在缓冲，下一轮继续读
            consumed += len(raw) + 1                # +1 = '\n'
            text = self._decode(raw, strip=True)
            if text:
                lines.append(text)
        pending = data[consumed:]
        dropped = 0
        if len(pending) > self.MAX_PENDING_BYTES:
            pending, dropped = self._trim(pending)
        self._pending[name] = pending
        if not lines and len(pending) >= self.MAX_PENDING_BYTES:
            # 极端情况:写入方长时间不换行(无换行的大块输出)。此时既不能把缓冲
            # 无限攒下去，也不能永远不显示 —— 按一行吐出来。
            text = self._decode(pending, strip=True)
            self._pending[name] = b''
            if text:
                lines.append(text)
        if dropped:
            lines.insert(0, f'（日志增速超过回灌速度，已省略 {dropped} 字节，完整内容见 logs\\{name}.log）')
        return lines

    @staticmethod
    def _trim(pending: bytes) -> tuple[bytes, int]:
        """缓冲超限时只保留最后一段，并从换行处切开以免拼出半行。"""
        cut = pending[-ProdLogTailer.MAX_PENDING_BYTES:]
        idx = cut.find(b'\n')
        kept = cut[idx + 1:] if idx >= 0 else cut
        return kept, len(pending) - len(kept)


# 注：轮转（copytruncate）、保留清理、以及两者的报告类型，**机制与策略都已统一到**
# utils/log_rotation.py（与后端 ARQ cron、prod_runner 共用同一实现与同一份策略文件
# config/log_policy.json）。本模块只把那些名字重新导出给 UI 层（见文件头 import），
# 不再自带实现 —— 否则同一台机器上「多大该轮转」会有多个答案：2026-09-30 之前正是
# 三个（prod_runner 50MB/只转自己的 .out.log、ARQ cron 100MB/只转 nginx、管理器
# 50MB/转全部 *.log 并清理），改一个必漏两个。

# ── 日志健康巡检（增长源识别 + 异常增长告警） ──────────────────────────────────

@dataclass
class LogFileStat:
    """单个日志文件的一次采样：体积 + 增长率(首次采样时为 None)。"""

    path: Path
    size: int
    mtime: float
    growth_bytes_per_day: float | None = None

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def growth_text(self) -> str:
        return '—' if self.growth_bytes_per_day is None else f'{human_bytes(self.growth_bytes_per_day)}/天'


@dataclass
class LogHealthReport:
    """一轮日志巡检的结果(供面板渲染与告警)。"""

    files: list[LogFileStat] = field(default_factory=list)
    total_bytes: int = 0
    sampled_at: float = 0.0
    first_sample: bool = True
    over_cap: bool = False
    max_total_bytes: int = LOG_MAX_TOTAL_BYTES
    alert_bytes_per_day: float = LOG_ALERT_BYTES_PER_DAY

    def share_of(self, stat: LogFileStat) -> float:
        """该文件占日志目录总量的百分比(总量为 0 时按 0 计)。"""
        return stat.size / self.total_bytes * 100 if self.total_bytes else 0.0

    def hottest(self, limit=3) -> list[LogFileStat]:
        """增长最快的几个文件：只含**确实在长**的 —— 「谁在疯长」就看它。

        刻意排除 0 增长：安静时绝大多文件都不长，把它们排进「增长最快」等于用
        噪声把真正的增长源（如果有）顶出榜单外(2026-09-30 真机实测踩到)。
        """
        ranked = [f for f in self.files if (f.growth_bytes_per_day or 0) > 0]
        return sorted(ranked, key=lambda f: f.growth_bytes_per_day, reverse=True)[:limit]

    def warn_files(self) -> list[LogFileStat]:
        """日增超阈值的文件(第一次采样算不出增长率，自然为空)。"""
        return [f for f in self.files
                if f.growth_bytes_per_day is not None and f.growth_bytes_per_day > self.alert_bytes_per_day]

    def summary(self) -> str:
        """面板上一行字讲清:总量多大、谁在长、长得有多快。"""
        head = (f"日志巡检 {time.strftime('%H:%M:%S', time.localtime(self.sampled_at))} · "
                f'合计 {human_bytes(self.total_bytes)} / {len(self.files)} 个文件')
        hot = self.hottest()
        if self.first_sample:
            return head + ' · 增长率需两次采样（下一轮巡检出结果）'
        if not hot:
            return head + ' · 本轮采样区间内无文件增长'
        parts = [f'{f.name} {f.growth_text}（占 {self.share_of(f):.0f}%）' for f in hot]
        return head + ' · 增长最快：' + '、'.join(parts)

    def alerts(self) -> list[str]:
        """异常增长的告警文本(空列表 = 健康)。"""
        if self.first_sample:
            return []                                # 首轮没有基线，断言增长就是瞎报
        msgs = [f'日志异常增长：{f.name} 约 {f.growth_text}（现存 {human_bytes(f.size)}）——'
                f'可能是崩溃循环刷栈或 DEBUG 级别泄漏，建议查看 logs\\{f.name}'
                for f in self.warn_files()]
        if self.over_cap:
            msgs.append(f'日志目录 {human_bytes(self.total_bytes)} 已超保留上限 '
                        f'{human_bytes(self.max_total_bytes)}（正在写入的文件不能被回收）：'
                        f'请排查上面的增长源，或调小保留期')
        return msgs


def _load_health_state(state_path: Path) -> dict[str, tuple[int, float]]:
    """读上一轮的 (文件名 → (大小, 采样时刻))；缺失/损坏一律当「没有基线」处理。"""
    try:
        data = json.loads(state_path.read_text(encoding='utf-8'))
        return {str(k): (int(v[0]), float(v[1])) for k, v in (data.get('files') or {}).items()}
    except (OSError, ValueError, TypeError, KeyError, IndexError):
        return {}


def _save_health_state(state_path: Path, files: list[LogFileStat], now: float) -> None:
    """落本轮快照；写不进去(权限/占用)只降级为「下轮仍是首次采样」，绝不抛。"""
    payload = {'sampled_at': now, 'files': {f.name: [f.size, now] for f in files}}
    with contextlib.suppress(OSError):
        state_path.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')


def inspect_log_health(log_dir, *, max_total_bytes=LOG_MAX_TOTAL_BYTES,
                       alert_bytes_per_day=LOG_ALERT_BYTES_PER_DAY,
                       state_path=None, now=None, min_span_seconds=60) -> LogHealthReport:
    """巡检一轮日志目录:体积占比 + 相对上轮快照的增长率，并落新快照。

    ``min_span_seconds`` 是算增长率的最小采样间隔 —— 两次采样太近（进程刚重启就
    连着跑两轮）时相除会放大噪声，宁可这一轮不给数字。
    """
    log_dir = Path(log_dir)
    now = time.time() if now is None else now
    report = LogHealthReport(sampled_at=now, max_total_bytes=max_total_bytes,
                             alert_bytes_per_day=alert_bytes_per_day)
    if not log_dir.is_dir():
        return report
    state_path = Path(state_path) if state_path else log_dir / LOG_HEALTH_STATE_NAME
    previous = _load_health_state(state_path)
    report.first_sample = not previous
    for path in iter_log_files(log_dir):
        mtime = safe_mtime(path)
        try:
            size = path.stat().st_size
        except OSError:
            continue
        report.files.append(LogFileStat(path, size, mtime, _growth_of(path.name, size, previous, now, min_span_seconds)))
    report.files.sort(key=lambda f: f.size, reverse=True)
    report.total_bytes = sum(f.size for f in report.files)
    report.over_cap = report.total_bytes > max_total_bytes
    _save_health_state(state_path, report.files, now)
    return report


def _growth_of(name: str, size: int, previous: dict, now: float, min_span_seconds: float):
    """按上轮快照算字节/天；无基线、间隔太短或文件被轮转(变小)时返回 None。"""
    prev = previous.get(name)
    if not prev:
        return None
    prev_size, prev_ts = prev
    span = now - prev_ts
    if span < min_span_seconds or size < prev_size:
        # 被轮转/截断的文件：增长率的正确含义是「每轮新增」，用总量差算会得到负数，
        # 并且真正的问题是「轮转频繁」——这属于体积闸门的职责，不在这里编数字。
        return None
    return (size - prev_size) / span * 86400
