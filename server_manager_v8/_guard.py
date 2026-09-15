"""单实例守卫 —— 防止同一时刻跑两个管理器实例。

═══════════════════════════════════════════════════════════════════
为什么要单实例
═══════════════════════════════════════════════════════════════════

两个实例同时操作同一批服务，会产生**真实的事故**：

    · 实例 A 正在停止生产服务，实例 B 认为「服务该在运行」于是启动它
      → 两个实例互相打架，服务在启停之间反复横跳
    · 实例 A 拿了确认令牌准备卸载，实例 B 同时也在卸载
      → 服务被删两次，第二次的失败被误报成「卸载失败」
    · 两边的界面显示不同状态，用户不知道该信哪个

所以必须在**启动最早期**就拦住第二个实例。

═══════════════════════════════════════════════════════════════════
★ 为什么优先用 Windows Mutex 而不是锁文件
═══════════════════════════════════════════════════════════════════

Mutex 的生命周期由**内核**持有，进程一旦退出（哪怕是被任务管理器
强杀、段错误崩溃、断电）内核自动释放。

锁文件则相反：进程崩溃后文件还在，下一个实例启动会认为「已有一个
实例在跑」—— **用户永久无法再启动程序**，且报错信息指向一个不存在
的进程。这正是最难排查的那类问题：
    · 用户看到「程序已在运行」
    · 任务管理器里什么都没有
    · 只能 manually 删文件（还得先知道文件在哪）

所以：能用 mutex 就用 mutex，锁文件只作为**非 Windows 的回退**，
且必须带陈旧检测（见 `FileLock`）。

═══════════════════════════════════════════════════════════════════
★ 「拿不到锁」必须明确告知，不能静默
═══════════════════════════════════════════════════════════════════

若拿不到锁就静默退出，用户双击图标后什么都没发生 ——
会以为程序坏了，反复双击，然后来问我们。
所以本模块**只负责判定**，把「怎么告诉用户」交给调用方
（`gui_launcher` 弹一个明确的对话框）。
"""

from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

#: 互斥体名称（Windows 全局，加 Global\\ 前缀跨会话可见）
MUTEX_NAME = r'Global\ERP_Server_Manager_v8_SingleInstance'

#: 锁文件名（非 Windows 回退用）
LOCK_FILENAME = 'server_manager_v8.lock'

#: 锁文件超过这个秒数视为陈旧（进程崩溃残留）
#:
#: ★ 30 分钟的依据：一次完整的服务启停 + 排障通常在这个量级内。
#:   取太长（如 24 小时）会让崩溃后的用户干等；
#:   取太短（如 10 秒）会让**正常**的第二个实例误判为陈旧锁而抢到锁
#:   ——那比不让启动更危险，因为单实例保护就失效了。
STALE_LOCK_S = 1800.0


class AlreadyRunning(RuntimeError):
    """已有另一个实例在运行。

    ★ 这是个「正常情况」而非异常 —— 用户双击了第二次。
      但用异常表达，可以让调用方用 try/except 干净地分流处理。
    """


# ═══════════════════════════════════════════════════════════════════
# Windows Mutex
# ═══════════════════════════════════════════════════════════════════

#: Windows 错误码：互斥体已存在
ERROR_ALREADY_EXISTS = 183

#: Windows 进程退出码：仍在运行（GetExitCodeProcess 返回此值表示未终止）
STILL_ACTIVE = 259


class WinMutex:
    """Windows 命名互斥体（进程退出由内核自动释放）。"""

    def __init__(self, name: str = MUTEX_NAME) -> None:
        self._name = name
        self._handle: Any = None
        self._kernel32: Any = None
        #: ★ 机制是否不可用（区别于「已有实例持有」）
        #:
        #:   这两种情况都表现为 acquire() 返回 False，但语义完全相反：
        #:     · 不可用   → 该回退到文件锁
        #:     · 已被持有 → **绝不能**回退，否则单实例保护被绕过
        #:
        #:   曾经把两者混为一谈，导致「第二个实例照常启动」——
        #:   保护机制被自己的回退逻辑废掉了。
        self.unavailable = False

    def acquire(self) -> bool:
        """尝试获取。

        返回值与 `unavailable` 的组合含义：
            True               → 抢到锁
            False + unavailable=False → **已有实例持有**，调用方应拒绝启动
            False + unavailable=True  → 机制不可用，调用方可回退文件锁

        ★ 句柄**必须**保存在实例上：局部变量会被 GC 回收，
          而 Mutex 的生命周期 = 最后一个句柄关闭时。
          句柄一丢，锁就没了 —— 表现为「第二个实例居然能启动」。
        """
        self.unavailable = False
        if sys.platform != 'win32':
            self.unavailable = True
            return False
        try:
            import ctypes  # noqa: PLC0415

            kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel32.CreateMutexW.restype = ctypes.c_void_p
            kernel32.CreateMutexW.argtypes = [
                ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p,
            ]

            handle = kernel32.CreateMutexW(None, True, self._name)
            if not handle:
                log.warning('CreateMutexW 失败（errno=%s）', ctypes.get_last_error())
                self.unavailable = True
                return False

            if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
                # 拿到的是已存在互斥体的句柄 —— 关掉它，我们不持有。
                # ★ 注意 unavailable 保持 False：这是「已被别人持有」，
                #   不是「机制坏了」，绝不能让调用方回退到文件锁。
                kernel32.CloseHandle(ctypes.c_void_p(handle))
                return False

            self._kernel32 = kernel32
            self._handle = ctypes.c_void_p(handle)
            return True

        except Exception as exc:  # noqa: BLE001
            # 非 Windows 或 ctypes 不可用 → 回退到文件锁
            log.debug('Windows mutex 不可用（%s），将回退文件锁', exc)
            self.unavailable = True
            return False

    def release(self) -> None:
        if self._handle is not None and self._kernel32 is not None:
            try:
                self._kernel32.CloseHandle(self._handle)
            except Exception as exc:  # noqa: BLE001
                log.debug('释放 mutex 失败: %s', exc)
            self._handle = None
            self._kernel32 = None

    def __enter__(self) -> WinMutex:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.release()


# ═══════════════════════════════════════════════════════════════════
# 文件锁（回退）
# ═══════════════════════════════════════════════════════════════════


class FileLock:
    """基于锁文件的守卫（非 Windows 回退）。

    ★ 必须处理陈旧锁：进程崩溃后锁文件残留，
      若无条件认为「锁存在 = 有实例在跑」，用户将**永久无法启动**。

    检测方式：文件里写 PID + 时间戳。以下三种情况视为陈旧并接管：
      ① PID 对应的进程已不存在
      ② 时间戳超过 `STALE_LOCK_S`
      ③ PID 与当前进程相同（PID 复用，见 `acquire()` 内注释）

    ★ 如实标注一个**未能解决**的局限：
      若崩溃进程的 PID 被一个**无关的**进程复用（比如某个记事本
      恰好拿到那个 PID），本类会误判为「还活着」从而拒绝启动。
      要彻底解决需要在锁里写入进程创建时间或全局唯一实例标识，
      并在判定时比对 —— 那是行为改动，此处不引入。
      缓解手段是 `STALE_LOCK_S`（超期一律放行），
      所以最坏情况是「一段时间内起不来」，不会永久锁死。
    """

    def __init__(self, path: str | Path | None = None) -> None:
        if path is None:
            base = Path(sys.executable).resolve().parent \
                if getattr(sys, 'frozen', False) else Path.cwd()
            path = base / LOCK_FILENAME
        self._path = Path(path)
        self._acquired = False

    @property
    def path(self) -> Path:
        return self._path

    def _read(self) -> tuple[int, float] | None:
        """读锁文件内容，返回 (pid, ts)。无效则返回 None。"""
        try:
            text = self._path.read_text(encoding='utf-8').strip()
        except OSError:
            return None
        try:
            pid_str, ts_str = text.split(':', 1)
            return int(pid_str), float(ts_str)
        except ValueError:
            # 文件被写坏了 → 按陈旧处理（而不是崩在这里）
            log.warning('锁文件内容异常，按陈旧处理: %r', text[:64])
            return None

    def _pid_alive(self, pid: int) -> bool:
        """进程是否还在。

        ★ 检查失败时**保守返回 True**（当作还活着）：
          宁可拒绝启动（用户可查明原因），
          也不要误判成「进程已死」而抢锁 —— 那会让单实例保护失效。
        """
        if pid <= 0:
            return False
        if sys.platform == 'win32':
            try:
                import ctypes  # noqa: PLC0415

                kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
                kernel32.OpenProcess.argtypes = [
                    ctypes.c_uint32, ctypes.c_bool, ctypes.c_uint32,
                ]
                kernel32.OpenProcess.restype = ctypes.c_void_p
                kernel32.GetExitCodeProcess.argtypes = [
                    ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32),
                ]
                kernel32.GetExitCodeProcess.restype = ctypes.c_bool

                #: PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
                handle = kernel32.OpenProcess(0x1000, False, pid)
                if not handle:
                    return False

                # ★ OpenProcess 成功**不代表进程还活着**：
                #   Windows 的进程对象在最后一个句柄关闭前不会销毁。
                #   若父进程仍持有句柄（哪怕子进程已终止），
                #   OpenProcess 照样返回有效句柄 —— 于是「死进程」被判成活的。
                #   必须再查退出码：仍是 STILL_ACTIVE(259) 才算活着。
                try:
                    code = ctypes.c_uint32()
                    if kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                        return code.value == STILL_ACTIVE
                    return True      # 查不到 → 保守认为活着
                finally:
                    kernel32.CloseHandle(ctypes.c_void_p(handle))
            except Exception:  # noqa: BLE001
                return True     # 查不了 → 保守认为活着
        try:
            os.kill(pid, 0)     # 信号 0：只检测存在性
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True         # 进程存在但无权查询 → 活着
        except Exception:  # noqa: BLE001
            return True         # 保守

    def acquire(self) -> bool:
        info = self._read()
        now = time.time()

        if info is not None:
            pid, ts = info
            stale_by_age = (now - ts) > STALE_LOCK_S
            #: ★ 锁里的 pid 就是**自己** → 必然是上次运行的残留
            #:
            #:   当前进程既然在调 acquire()，说明它此刻**没有**持有锁。
            #:   那么锁文件里若写着自己的 pid，只可能是：
            #:     上次运行崩溃 → 进程退出 → 系统回收 pid → 本次复用到同一个 pid
            #:   （Windows 上 pid 复用相当常见。）
            #:
            #:   若不识别这种情况，会判定「pid 活着 → 已有实例」，
            #:   于是**这个进程永远无法启动** —— 且报错指向一个不存在的实例。
            same_pid = pid == os.getpid()
            alive = self._pid_alive(pid)

            if alive and not stale_by_age and not same_pid:
                log.info('已有实例在运行（pid=%s）', pid)
                return False
            if not alive:
                log.info('检测到陈旧锁（pid=%s 已不存在），接管', pid)
            elif same_pid:
                log.info('锁记录的 pid 与自身相同（pid 复用），按陈旧处理并接管')
            else:
                log.info('锁超过 %s 秒且进程仍存在，按陈旧处理并接管',
                         int(STALE_LOCK_S))

        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                f'{os.getpid()}:{now}', encoding='utf-8',
            )
        except OSError as exc:
            log.warning('写锁文件失败（%s）—— 单实例保护未生效', exc)
            # ★ 拿不到锁文件时**放行**而不是拒绝启动：
            #   不让用户因为一个权限问题就用不了程序
            return True

        self._acquired = True
        return True

    def release(self) -> None:
        if not self._acquired:
            return
        try:
            info = self._read()
            # ★ 只删自己写的锁：若期间被别人接管，不能删掉别人的锁
            if info is None or info[0] == os.getpid():
                self._path.unlink(missing_ok=True)
        except OSError as exc:
            log.debug('删除锁文件失败: %s', exc)
        self._acquired = False

    def __enter__(self) -> FileLock:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.release()


# ═══════════════════════════════════════════════════════════════════
# 统一入口
# ═══════════════════════════════════════════════════════════════════


class SingleInstanceGuard:
    """统一的单实例守卫：优先 Windows Mutex，失败回退文件锁。

    用法：
        guard = SingleInstanceGuard()
        try:
            guard.acquire()      # 失败抛 AlreadyRunning
        except AlreadyRunning:
            ...提示用户...
        ...
        guard.release()
    """

    def __init__(self, *, name: str = MUTEX_NAME,
                 lock_path: str | Path | None = None) -> None:
        self._mutex = WinMutex(name)
        self._file = FileLock(lock_path)
        self._using: str = ''
        self._held = False

    @property
    def mechanism(self) -> str:
        """实际生效的机制（`'mutex'` / `'file'` / `''`）。"""
        return self._using

    @property
    def held(self) -> bool:
        return self._held

    def acquire(self) -> bool:
        """获取守卫。返回 False 表示已有实例在运行。

        ★ 回退的**唯一**前提是 mutex 机制本身不可用，
          而不是「mutex 判定已有实例在跑」。
          后者若也回退，文件锁会成功拿到（因为没人写锁文件），
          于是第二个实例照常启动 —— 单实例保护形同虚设。
        """
        if self._mutex.acquire():
            self._using = 'mutex'
            self._held = True
            return True

        if not self._mutex.unavailable:
            # mutex 正常工作，只是锁被别人持有了 → 拒绝，不回退
            return False

        if self._file.acquire():
            self._using = 'file'
            self._held = True
            return True
        return False

    def require(self) -> None:
        """获取守卫，失败抛 `AlreadyRunning`。"""
        if not self.acquire():
            raise AlreadyRunning(
                '已有一个 ERP 服务器管理器实例在运行。\n\n'
                '同时运行多个实例会导致服务状态互相冲突。\n'
                '请先关闭已有实例（或结束残留进程）后重试。'
            )

    def release(self) -> None:
        if not self._held:
            return
        self._mutex.release()
        self._file.release()
        self._held = False
        self._using = ''

    def __enter__(self) -> SingleInstanceGuard:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.release()


def already_running() -> bool:
    """快速判断：是否已有实例在运行（不改变状态）。

    ★ 这会**消耗**一次 mutex 获取 —— Windows 下若成功持有会立即释放，
      存在极小的竞态（两个实例同时探测都得到 False）。
      正式判定请用 `SingleInstanceGuard.acquire()`。
    """
    guard = SingleInstanceGuard()
    got = guard.acquire()
    if got:
        guard.release()
    return not got


__all__ = [
    'AlreadyRunning',
    'FileLock',
    'LOCK_FILENAME',
    'MUTEX_NAME',
    'STALE_LOCK_S',
    'SingleInstanceGuard',
    'WinMutex',
    'already_running',
]
