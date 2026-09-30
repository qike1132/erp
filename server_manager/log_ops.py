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

■ 为什么需要 ``rotate_oversized_logs``(用户诉求:「给管理器自己的日志与无人轮转的 nginx 日志加轮转兜底，不再依赖外部定时任务」)
  现状是「谁写的谁轮转，但有两个没人管」：NSSM 服务日志有 ``AppRotateBytes=10MB``；
  后端 ``fastapi_*.log`` 有自己的 handler；而 **nginx 的 access/error 日志靠 ARQ 的
  每日 04:30 cron 轮转**（ARQ 一挂就没人转），**管理器自己的 ``server_manager_*.log``
  则从来没有轮转**（只靠保留期删旧文件）。本模块提供一道与外部任务无关的兜底：
  管理器自己把超过阈值的现行日志就地切成「一代 .1 副本 + 清零的现行文件」。
  阈值取 50MB（= NSSM 自身上限的 5 倍），天然不会和 NSSM 抢同一个文件。

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
import shutil
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from server_manager.constants import _SVC_API, _SVC_ARQ, _SVC_WEB
from server_manager.service_ops import ServiceOps

# 生产模式受跟踪的服务日志:与 NSSM 安装时写入的 AppStdout/AppStderr 同名(见 service_ops.nssm_install)
PROD_LOG_SERVICES = (_SVC_API, _SVC_ARQ, _SVC_WEB)

# 保留策略默认值(与后端 core/logger.py 的 fastapi_*.log「保留 14 天」对齐)。
LOG_KEEP_DAYS = 14
LOG_MAX_TOTAL_BYTES = 512 * 1024 * 1024
# 兜底护栏:正在被写入的日志(1 小时内有写入)即使顶着体积上限也绝不删 ——
# Windows 上对被占用的文件删不掉(会如实记为 skipped)，而这里干脆不尝试，
# 免得「刚起来的生产日志被自己的清理任务删掉」这种荒谬故障。
LOG_MIN_AGE_SECONDS = 3600

# 巡检:单文件日增超过此值即视为「疯长」(现场安静运行时全目录约 1MB/h 级，
# 崩溃循环/DEBUG 泄漏会直接把它打穿，故 1GB/天 既不会误报也足够早报警)。
LOG_ALERT_BYTES_PER_DAY = 1024 * 1024 * 1024
# 巡检状态快照文件名:刻意**不含** '.log' —— 它自己不能被当成日志清理掉或统计进去。
LOG_HEALTH_STATE_NAME = 'log_health_state.json'

# 轮转兜底阈值:必须**高于** NSSM 的 AppRotateBytes(10MB)，否则会去动 NSSM 自己
# 正在轮转的服务日志（两边抢同一个文件）。50MB 仍远低于任何“大到打不开”的体量。
LOG_ROTATE_BYTES = 50 * 1024 * 1024


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
                 decode=ServiceOps.decode_output):
        """``msg_queue`` / ``project_dir`` 由 app 注入；``interval`` 为轮询周期(秒)。

        ``decode`` 默认复用管理器**唯一的**字节流解码器
        (``service_ops.ServiceOps.decode_output``，含 UTF-16/GBK 回退):
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


@dataclass
class LogPruneReport:
    """一轮日志清理的结果(供界面日志与测试断言)。

    可变的：清理是**边删边记账**（每删一个就累积 freed_bytes / deleted），
    frozen 会让记账点不得不改写成「先攒局部变量再构造」，反而多一层状态。
    """

    deleted: list[Path] = field(default_factory=list)
    skipped: list[Path] = field(default_factory=list)
    kept: int = 0
    freed_bytes: int = 0
    keep_days: int = LOG_KEEP_DAYS

    def summary(self) -> str:
        """人话总结:必须同时说清「删了什么」和「跳过了什么」。"""
        if self.deleted:
            head = (f'日志清理完成：删除 {len(self.deleted)} 个文件'
                    f'（{self.freed_bytes / 1048576:.1f}MB），保留 {self.kept} 个（{self.keep_days} 天内/体积上限内）')
        else:
            head = f'日志清理完成：无过期文件，保留 {self.kept} 个（{self.keep_days} 天内/体积上限内）'
        if self.skipped:
            head += (f'；{len(self.skipped)} 个文件被占用跳过（{"、".join(p.name for p in self.skipped[:3])}）'
                     f'，下一轮重试')
        return head


def _iter_log_files(log_dir: Path) -> list[Path]:
    """候选日志文件(按最后写入时间升序)。

    只扫 ``*.log*`` 顶层文件:``prod_runner.json`` / ``nginx.pid`` / ``watchdog_state.json``
    这些状态文件不在范围内 —— 它们不是日志，删了会打断监督器与 nginx 的就绪判定。
    """
    files = [p for p in log_dir.glob('*.log*') if p.is_file()]
    return sorted(files, key=lambda p: _safe_mtime(p))


def _safe_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def prune_log_files(log_dir, *, keep_days=LOG_KEEP_DAYS, max_total_bytes=LOG_MAX_TOTAL_BYTES,
                    min_age_seconds=LOG_MIN_AGE_SECONDS, now=None, remove=os.remove) -> LogPruneReport:
    """按「最后写入时间」+「目录总体积上限」清理日志文件。

    两道闸门，先按时间再按体积:时间闸门表达「留多久」，体积闸门兜住「写得太快」
    (例如崩溃循环每秒刷栈，14 天的量也足以撑爆磁盘)。两轮都按最旧的先删，
    且**都**跳过 ``min_age_seconds`` 内有写入的文件(正在写的那一个)。

    ``remove`` 可注入(测试用):删除失败(文件被占用/权限不足)只记为 skipped
    并让本轮继续 —— 一个删不掉的日志绝不能让整轮清理失败。
    """
    log_dir = Path(log_dir)
    report = LogPruneReport(keep_days=keep_days)
    if not log_dir.is_dir():
        return report
    now = time.time() if now is None else now
    cutoff = now - keep_days * 86400
    fresh_cutoff = now - min_age_seconds
    candidates = _iter_log_files(log_dir)
    survivors: list[Path] = []
    for path in candidates:
        mtime = _safe_mtime(path)
        if mtime >= cutoff or mtime >= fresh_cutoff:
            survivors.append(path)                  # 保留期内 / 正在写(体积闸门同样不动它)
            continue
        _try_remove(path, report, remove)
    total = sum(path.stat().st_size for path in survivors if path.is_file())
    while total > max_total_bytes and survivors:
        oldest = survivors[0]
        if _safe_mtime(oldest) >= fresh_cutoff:
            break                                   # 剩下的全是正在写的 → 体积上限这一轮只能放弃
        survivors.pop(0)                            # 先摘出去再删:删失败也不重复尝试
        total -= oldest.stat().st_size if oldest.is_file() else 0
        _try_remove(oldest, report, remove)
    report.kept = len(survivors)
    return report


def _try_remove(path: Path, report: LogPruneReport, remove) -> None:
    """删除一个文件并记账；失败只记 skipped(不抛、不中断本轮)。"""
    size = path.stat().st_size if path.is_file() else 0
    try:
        remove(path)
    except OSError:
        report.skipped.append(path)
        return
    report.deleted.append(path)
    report.freed_bytes += size


# ── 轮转兜底（copytruncate） ─────────────────────────────────────────────────

def rotate_file_by_copytruncate(path: Path, max_bytes: int) -> bool:
    """把超阈值日志就地轮转为「一代 .1 副本 + 清零的现行文件」，返回是否轮转。

    Windows 不允许 rename/delete 被进程持有的文件（nginx 与 NSSM 都长期打开着
    日志），所以只能先复制副本、再把现行文件截断为 0；持有方按**追加**语义继续写，
    自然落在新文件尾。截断与下次追加之间的极小窗口可能丢几行—— 对运维日志可接受
    而「不轮转导致日志涨到 1GB 打不开」不可接受。

    ★ 为什么不复用 ``utils.log_rotation.rotate_file_copytruncate``（与本函数逐字等价）：
      ``utils/__init__.py`` 会连带导入 ``batch_upload_utils``，而后者**硬要求
      polars + openpyxl**（缺失直接 raise）；``server_manager.spec`` 又明确 exclude 了
      openpyxl/sqlalchemy 等重依赖 —— 管理器一旦在顶层 import utils，打包后的 exe
      会在启动期 ImportError。轮转兜底宁可自带这份等价实现，也不能在打包环境里没有。
    """
    try:
        if not path.is_file() or path.stat().st_size < max_bytes:
            return False
        rotated = path.with_name(path.name + '.1')
        with open(path, 'rb') as src, open(rotated, 'wb') as dst:
            shutil.copyfileobj(src, dst, length=1024 * 1024)
        with open(path, 'r+b') as handle:
            handle.truncate(0)
        return True
    except OSError:
        return False


@dataclass
class LogRotationReport:
    """一轮轮转兜底的结果(供面板日志与测试断言)。"""

    rotated: list[tuple[Path, int]] = field(default_factory=list)   # (文件, 轮转前大小)
    skipped: list[Path] = field(default_factory=list)               # 被占用/失败，下轮重试
    max_bytes: int = LOG_ROTATE_BYTES

    def summary(self) -> str:
        """人话总结：轮转了谁、多大、跳过了谁。"""
        head = f'日志轮转兜底（阈值 {_human_bytes(self.max_bytes)}）'
        if self.rotated:
            detail = '、'.join(f'{p.name} {_human_bytes(size)}→.1' for p, size in self.rotated)
            head += f'：已轮转 {len(self.rotated)} 个（{detail}）'
        else:
            head += '：无超限日志'
        if self.skipped:
            head += f'；{len(self.skipped)} 个文件被占用未能轮转（{"、".join(p.name for p in self.skipped[:3])}），下一轮重试'
        return head


def rotate_oversized_logs(log_dir, *, max_bytes=LOG_ROTATE_BYTES, rotate=rotate_file_by_copytruncate) -> LogRotationReport:
    """把日志目录里所有超过阈值的**现行**日志做一次 copytruncate 轮转。

    只扫 ``*.log``（不含 ``*.log.1`` / ``*.log.<时间戳>`` 这些轮转副本）—— 副本已经是
    备份，再被轮转就会出现 ``.1.1`` 这种链，数量会指数长。
    """
    report = LogRotationReport(max_bytes=max_bytes)
    log_dir = Path(log_dir)
    if not log_dir.is_dir():
        return report
    for path in sorted(log_dir.glob('*.log')):
        if not path.is_file():
            continue
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if size < max_bytes:
            continue
        if rotate(path, max_bytes):
            report.rotated.append((path, size))
        else:
            report.skipped.append(path)
    return report


# ── 日志健康巡检（增长源识别 + 异常增长告警） ──────────────────────────────────

def _human_bytes(value: float) -> str:
    """人类可读体积(MB 起，超过 1GB 转 GB)。"""
    if value >= 1024 ** 3:
        return f'{value / 1024 ** 3:.1f}GB'
    return f'{value / 1048576:.1f}MB'


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
        return '—' if self.growth_bytes_per_day is None else f'{_human_bytes(self.growth_bytes_per_day)}/天'


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
                f'合计 {_human_bytes(self.total_bytes)} / {len(self.files)} 个文件')
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
        msgs = [f'日志异常增长：{f.name} 约 {f.growth_text}（现存 {_human_bytes(f.size)}）——'
                f'可能是崩溃循环刷栈或 DEBUG 级别泄漏，建议查看 logs\\{f.name}'
                for f in self.warn_files()]
        if self.over_cap:
            msgs.append(f'日志目录 {_human_bytes(self.total_bytes)} 已超保留上限 '
                        f'{_human_bytes(self.max_total_bytes)}（正在写入的文件不能被回收）：'
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
    for path in _iter_log_files(log_dir):
        mtime = _safe_mtime(path)
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
