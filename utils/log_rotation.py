"""日志轮转 + 保留策略 —— 桌面壳与后端**唯一**的一套实现。

Windows 下日志文件被 nginx / NSSM / uvicorn 以共享读写 + 追加方式长期占用，无法
rename，只能先复制再原地截断（copytruncate）；截断瞬间与追加写之间的少量行丢失对
运维日志可接受，追加语义保证持有方后续写入落在新文件尾。

■ 为什么「策略」也要住在这里（2026-09-30）
  此前同一条日志管线上有三个各自为政的阈值与范围：
    · ``prod_runner``：只管自己的 ``logs/<name>.out.log``，50MB（``PROD_LOG_ROTATE_MB`` 可调）；
    · ARQ cron：只管 nginx 两个文件，**100MB**，且没有任何保留期清理；
    · 桌面壳 ``server_manager``：管全部 ``*.log``，50MB + 保留 14 天 / 512MB 上限。
  「多大该轮转」在一台机器上有三个答案，改一个必漏两个；而 nginx 日志的轮转责任
  还押在 ARQ 每日 cron 上（ARQ 停摆就没人管）。现在统一为：
  **策略文件 ``config/log_policy.json`` → ``LogPolicy``；三方都读它、都用本模块的函数。**

■ 为什么必须保持 stdlib-only 且可被桌面壳安全导入
  ``import utils.log_rotation`` 会执行 ``utils/__init__.py``，而它此前 eager 导入
  ``batch_upload_utils``（**硬要求 polars + openpyxl**）与 ``logger``（sqlalchemy）：
    · 桌面壳（PyInstaller 打包，spec 明确 exclude openpyxl/sqlalchemy）一旦 import
      utils 就在启动期 ImportError —— 这正是此前「管理器只能自带一份轮转实现」的根因；
    · prod_runner（生产监督器）也白白在启动期多背一份 openpyxl/polars 的导入风险。
  ``utils/__init__.py`` 已改为惰性导出（PEP 562），本模块因此成为真正可共享的叶子层。

■ 冻结 exe 的坑（调用方必读）
  打包后 ``__file__`` 指向解包临时目录，``default_policy_path()`` 会算成
  ``<解包目录>/config/log_policy.json``。故桌面壳**必须**显式传 ``path``
  （见 ``server_manager/log_view.py`` 用 ``_PROJECT_DIR`` 拼路径）。
"""
from __future__ import annotations

import contextlib
import json
import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

# ── 策略 ─────────────────────────────────────────────────────────────────────

# 取值边界：文件里越界即夹取（抗手改坏值），界面表单里越界即报错（不静默改写用户意图）。
ROTATE_MB_BOUNDS = (1, 4096)
KEEP_DAYS_BOUNDS = (1, 3650)
CAP_MB_BOUNDS = (16, 65536)


@dataclass(frozen=True)
class LogPolicy:
    """日志轮转/保留策略（三方共用）。

    以字节存、以 MB 出示：界面与 JSON 用 MB（人读得懂），机制层用字节（不用到处乘）。
    """

    rotate_bytes: int = 50 * 1024 * 1024      # 单个现行日志超过它就轮转
    keep_days: int = 14                       # 保留天数（与后端 fastapi_*.log 约定一致）
    max_total_bytes: int = 512 * 1024 * 1024  # logs 目录总体积上限（时间闸门之外的兜底）

    @property
    def rotate_mb(self) -> int:
        return self.rotate_bytes // (1024 * 1024)

    @property
    def max_total_mb(self) -> int:
        return self.max_total_bytes // (1024 * 1024)

    def to_json_dict(self) -> dict:
        return {'rotate_mb': self.rotate_mb, 'keep_days': self.keep_days, 'max_total_mb': self.max_total_mb}

    def summary(self) -> str:
        """一行说清三项策略（面板提示与对话框标题都用它）。"""
        return f'轮转 {self.rotate_mb}MB · 保留 {self.keep_days} 天 · 上限 {self.max_total_mb}MB'


DEFAULT_LOG_POLICY = LogPolicy()


def default_policy_path() -> Path:
    """默认策略文件位置（后端用；桌面壳请显式传 path，见模块 docstring 的冻结 exe 坑）。"""
    return Path(__file__).resolve().parents[1] / 'config' / 'log_policy.json'


def _clamp_int(value, low: int, high: int, fallback: int) -> int:
    """把可能来自手改/旧版本的任意值夹到 [low, high]；不可解析则用 fallback。"""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(low, min(high, number))


def load_log_policy(path=None) -> LogPolicy:
    """读策略文件；缺失/损坏/字段越界一律回落默认值（绝不抛，也不让坏值生效）。

    读不到就用默认值而不是报错：调用方是生产监督器与定时任务，它们**必须**能跑下去；
    唯一后果是「这一轮按默认策略维护」，比「因为一个 JSON 写法错了就不维护」安全得多。
    """
    target = Path(path) if path else default_policy_path()
    try:
        raw = json.loads(target.read_text(encoding='utf-8'))
        if not isinstance(raw, dict):
            return DEFAULT_LOG_POLICY
    except (OSError, ValueError):
        return DEFAULT_LOG_POLICY
    default = DEFAULT_LOG_POLICY
    rotate_mb = _clamp_int(raw.get('rotate_mb'), *ROTATE_MB_BOUNDS, fallback=default.rotate_mb)
    keep_days = _clamp_int(raw.get('keep_days'), *KEEP_DAYS_BOUNDS, fallback=default.keep_days)
    cap_mb = _clamp_int(raw.get('max_total_mb'), *CAP_MB_BOUNDS, fallback=default.max_total_mb)
    return LogPolicy(rotate_bytes=rotate_mb * 1024 * 1024, keep_days=keep_days, max_total_bytes=cap_mb * 1024 * 1024)


def save_log_policy(policy: LogPolicy, path=None) -> bool:
    """原子写策略文件（先写 .tmp 再 os.replace）。

    为什么必须原子：后端每一轮（prod_runner 每 60s、ARQ cron）都会读这个文件，
    直接覆盖写会让它们有机会读到半截 JSON —— 那正好会落进上面「读不到就用默认值」
    的分支，表现为「策略间歇性失效」。失败只返回 False，由调用方决定怎么提示。
    """
    target = Path(path) if path else default_policy_path()
    tmp = target.with_suffix(target.suffix + '.tmp')
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(policy.to_json_dict(), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        os.replace(tmp, target)
        return True
    except OSError:
        with contextlib.suppress(OSError):
            tmp.unlink()
        return False


def policy_from_fields(rotate_mb_text, keep_days_text, cap_mb_text) -> tuple[LogPolicy | None, str | None]:
    """界面表单三格文本 → (策略, 错误信息)。越界**报错**而不是夹取（界面不能静默改写意图）。

    返回 (None, 原因) 时调用方应保持对话框打开并把原因显示给用户。
    """
    fields = (('轮转阈值', rotate_mb_text, ROTATE_MB_BOUNDS),
              ('保留天数', keep_days_text, KEEP_DAYS_BOUNDS),
              ('体积上限', cap_mb_text, CAP_MB_BOUNDS))
    values = {}
    for label, text, (low, high) in fields:
        try:
            number = int(str(text).strip())
        except (TypeError, ValueError):
            return None, f'{label}必须是整数（当前填的是「{str(text).strip() or "空"}」）'
        if not low <= number <= high:
            return None, f'{label}必须在 {low} ~ {high} 之间（当前 {number}）'
        values[label] = number
    return LogPolicy(rotate_bytes=values['轮转阈值'] * 1024 * 1024,
                     keep_days=values['保留天数'],
                     max_total_bytes=values['体积上限'] * 1024 * 1024), None


# ── 通用小工具 ───────────────────────────────────────────────────────────────

def human_bytes(value: float) -> str:
    """人类可读体积（MB 起，超过 1GB 转 GB）。"""
    if value >= 1024 ** 3:
        return f'{value / 1024 ** 3:.1f}GB'
    return f'{value / 1048576:.1f}MB'


def safe_mtime(path: Path) -> float:
    """文件 mtime；读不到按 0（最旧）处理 —— 宁可先删它，也不让整轮清理异常。"""
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def iter_log_files(log_dir: Path) -> list[Path]:
    """候选日志文件（按最后写入时间升序）。

    只认 ``*.log*`` 顶层文件：``prod_runner.json`` / ``nginx.pid`` / ``watchdog_state.json``
    这些状态文件不在范围内 —— 它们不是日志，删了会打断监督器与 nginx 的就绪判定。
    轮转与保留**共用**这一条候选规则，否则会出现「巡检看得见、清理够不着」的盲区。
    """
    files = [p for p in Path(log_dir).glob('*.log*') if p.is_file()]
    return sorted(files, key=safe_mtime)


# ── 轮转 ─────────────────────────────────────────────────────────────────────

# 兜底轮转的默认阈值必须**高于** NSSM 的 AppRotateBytes(10MB)，否则会去动 NSSM
# 自己正在轮转的服务日志（两边抢同一个文件）。见 tests/test_server_manager_log_ops.py。
LOG_MIN_AGE_SECONDS = 3600


def rotate_file_copytruncate(path: Path, max_bytes: int) -> bool:
    """超阈值 copytruncate 轮转，保留一代 ``.1`` 副本，返回是否执行了轮转。

    IO 失败不抛（打一行日志返回 False），由调用方下一轮重试 —— 轮转是兜底动作，
    它自己失败绝不能连带把监督器/定时任务弄挂。
    """
    try:
        if not path.is_file() or path.stat().st_size < max_bytes:
            return False
        rotated = path.with_name(path.name + '.1')
        with open(path, 'rb') as src, open(rotated, 'wb') as dst:
            shutil.copyfileobj(src, dst, length=1024 * 1024)
        with open(path, 'r+b') as f:
            f.truncate(0)
        print(f'[log_rotation] {path.name} 超过 {max_bytes // (1024 * 1024)}MB，已轮转到 {rotated.name}')
        return True
    except OSError as e:
        print(f'[log_rotation] {path.name} 轮转失败（下一轮重试）: {e}')
        return False


@dataclass
class LogRotationReport:
    """一轮轮转的结果（供面板日志、任务返回值与测试断言）。"""

    rotated: list[tuple[Path, int]] = field(default_factory=list)   # (文件, 轮转前大小)
    skipped: list[Path] = field(default_factory=list)               # 被占用/失败，下轮重试
    max_bytes: int = DEFAULT_LOG_POLICY.rotate_bytes

    def summary(self) -> str:
        """人话总结：轮转了谁、多大、跳过了谁。"""
        head = f'日志轮转兜底（阈值 {human_bytes(self.max_bytes)}）'
        if self.rotated:
            detail = '、'.join(f'{p.name} {human_bytes(size)}→.1' for p, size in self.rotated)
            head += f'：已轮转 {len(self.rotated)} 个（{detail}）'
        else:
            head += '：无超限日志'
        if self.skipped:
            head += f'；{len(self.skipped)} 个文件被占用未能轮转（{"、".join(p.name for p in self.skipped[:3])}），下一轮重试'
        return head


def rotate_oversized_logs(log_dir, *, max_bytes=DEFAULT_LOG_POLICY.rotate_bytes,
                          rotate=rotate_file_copytruncate) -> LogRotationReport:
    """把日志目录里所有超过阈值的**现行**日志做一次 copytruncate 轮转。

    只扫 ``*.log``（不含 ``*.log.1`` / ``*.log.<时间戳>`` 这些轮转副本）—— 副本已经是
    备份，再被轮转就会出现 ``.1.1`` 这种链，数量会指数长。
    ``rotate`` 可注入（测试与「只报告不动作」的干跑都用它）。
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


# ── 保留清理 ─────────────────────────────────────────────────────────────────

@dataclass
class LogPruneReport:
    """一轮保留清理的结果（供面板日志与测试断言）。

    可变的：清理是**边删边记账**（每删一个就累积 freed_bytes / deleted），
    frozen 会让记账点不得不改写成「先攒局部变量再构造」，反而多一层状态。
    """

    deleted: list[Path] = field(default_factory=list)
    skipped: list[Path] = field(default_factory=list)
    kept: int = 0
    freed_bytes: int = 0
    keep_days: int = DEFAULT_LOG_POLICY.keep_days

    def summary(self) -> str:
        """人话总结：必须同时说清「删了什么」和「跳过了什么」。"""
        if self.deleted:
            head = (f'日志清理完成：删除 {len(self.deleted)} 个文件'
                    f'（{self.freed_bytes / 1048576:.1f}MB），保留 {self.kept} 个（{self.keep_days} 天内/体积上限内）')
        else:
            head = f'日志清理完成：无过期文件，保留 {self.kept} 个（{self.keep_days} 天内/体积上限内）'
        if self.skipped:
            head += (f'；{len(self.skipped)} 个文件被占用跳过（{"、".join(p.name for p in self.skipped[:3])}）'
                     f'，下一轮重试')
        return head


def prune_log_files(log_dir, *, keep_days=DEFAULT_LOG_POLICY.keep_days,
                    max_total_bytes=DEFAULT_LOG_POLICY.max_total_bytes,
                    min_age_seconds=LOG_MIN_AGE_SECONDS, now=None, remove=os.remove) -> LogPruneReport:
    """按「最后写入时间」+「目录总体积上限」清理日志文件。

    两道闸门，先按时间再按体积：时间闸门表达「留多久」，体积闸门兜住「写得太快」
    （例如崩溃循环每秒刷栈，14 天的量也足以撑爆磁盘）。两轮都按最旧的先删，
    且**都**跳过 ``min_age_seconds`` 内有写入的文件（正在写的那一个；Windows 上它们
    也删不掉，这里是干脆不尝试，免得「刚起来的生产日志被自己的清理任务删掉」）。

    ``remove`` 可注入（测试用）：删除失败（被占用/权限不足）只记为 skipped
    并让本轮继续 —— 一个删不掉的日志绝不能让整轮清理失败。
    """
    log_dir = Path(log_dir)
    report = LogPruneReport(keep_days=keep_days)
    if not log_dir.is_dir():
        return report
    now = time.time() if now is None else now
    cutoff = now - keep_days * 86400
    fresh_cutoff = now - min_age_seconds
    candidates = iter_log_files(log_dir)
    survivors: list[Path] = []
    for path in candidates:
        mtime = safe_mtime(path)
        if mtime >= cutoff or mtime >= fresh_cutoff:
            survivors.append(path)                  # 保留期内 / 正在写（体积闸门同样不动它）
            continue
        _try_remove(path, report, remove)
    total = sum(path.stat().st_size for path in survivors if path.is_file())
    while total > max_total_bytes and survivors:
        oldest = survivors[0]
        if safe_mtime(oldest) >= fresh_cutoff:
            break                                   # 剩下的全是正在写的 → 体积上限这一轮只能放弃
        survivors.pop(0)                            # 先摘出去再删：删失败也不重复尝试
        total -= oldest.stat().st_size if oldest.is_file() else 0
        _try_remove(oldest, report, remove)
    report.kept = len(survivors)
    return report


def _try_remove(path: Path, report: LogPruneReport, remove) -> None:
    """删除一个文件并记账；失败只记 skipped（不抛、不中断本轮）。"""
    size = path.stat().st_size if path.is_file() else 0
    try:
        remove(path)
    except OSError:
        report.skipped.append(path)
        return
    report.deleted.append(path)
    report.freed_bytes += size
