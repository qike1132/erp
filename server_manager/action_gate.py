"""动作闸门(ActionGate / _ActionCancelled)。

自 server_manager.py 原样迁出,未做重构。
"""
import threading
import time

# ===================== 动作闸门（P0-3 重构：单一持有者 / 自动释放 / 可协作取消） =====================
# 为什么要有这个类（2026-09-16 审计实测出的两个缺陷）：
#   ① 旧实现把「取锁 / 起线程 / 解锁」拆在三个方法里：任何一处异常（例如 UI 刷新报
#      TclError）就会永久持锁 → 所有动作按钮永久置灰、状态卡在 starting，只能重启进程。
#   ② 紧急停止绕过互斥，却没有任何取消机制：在飞行中的启动流程会继续把 Redis / 后端
#      拉起来（实测 UI 已显示 none 而后端进程真的在跑）。
# 本类的三条结构性约束：
#   1. 单一持有者 —— 只有 start() 一个入口，且它自己负责起线程；调用方拿不到
#      「只获取不释放」的用法；
#   2. 自动释放 —— worker 无论正常返回 / 抛异常 / 被取消，都由 try/finally 收尾，
#      另有看门狗兜底「worker 永不返回」；
#   3. 可协作取消 —— cancel() 置标志，worker 在步骤边界调 checkpoint() 立即中止，
#      不再产生后续副作用。
_OP_WATCHDOG_SEC = 600          # 单次动作上限（安装服务最坏 ≈ 400s，故取 600）
_EMERGENCY_JOIN_SEC = 8         # 紧急停止等待在飞行动作自行退出的上限

class _ActionCancelled(BaseException):
    """动作被取消的信号。

    ★ 刻意继承 BaseException 而非 Exception：本模块有 17 处 `except Exception: pass`，
    若继承 Exception，取消信号会在半路被吞掉、流程继续执行后续副作用 ——
    那正是「紧急停止后进程又被拉起来」的来路。
    """


class ActionGate:
    """动作闸门：一个不变量，一个主人，一条执行路径。"""

    def __init__(self, watchdog_seconds=_OP_WATCHDOG_SEC, on_event=None):
        self._lock = threading.Lock()
        self._owner = ''
        self._cancel = threading.Event()
        self._cancel_reason = ''      # 谁取消的（紧急停止 / 看门狗超时）—— 日志里必须能区分
        self._watchdog = None
        self._active_run = None
        self._run_seq = 0
        self._local = threading.local()   # 每个 worker 线程记录自己的 run_id（用于识别僵尸 worker）
        self._watchdog_seconds = watchdog_seconds
        self._on_event = on_event or (lambda kind, payload: None)

    # ---------- 只读状态（唯一的"占用"真相源就是这把锁） ----------
    @property
    def owner(self):
        return self._owner

    def busy(self):
        return self._lock.locked()

    def cancelled(self):
        return self._cancel.is_set()

    # ---------- 唯一入口 ----------
    def start(self, name, worker, *args):
        """开始一个动作；已有动作在执行则拒绝（不排队、不阻塞，由调用方决定提示）。"""
        if not self._lock.acquire(blocking=False):
            self._on_event('rejected', {'owner': self._owner, 'attempt': name})
            return False
        self._run_seq += 1
        run_id = self._run_seq
        self._active_run = run_id
        self._owner = name
        self._cancel.clear()
        self._cancel_reason = ''
        timer = threading.Timer(self._watchdog_seconds, self._watchdog_fire, args=(run_id, name))
        timer.daemon = True
        self._watchdog = timer
        timer.start()
        self._on_event('started', {'owner': name})
        threading.Thread(target=self._run, args=(run_id, name, worker, args), daemon=True).start()
        return True

    def cancel(self, reason='紧急停止'):
        """请求取消在飞行动作（紧急停止调用）。无动作时仅置标志，下一次 start 会清掉。

        ★ 空闲时不发事件：紧急停止在没动作在跑时也会调 cancel()，若照样上报，
        日志里会反复出现「正在取消动作：（空闲）…」这类噪音。
        """
        self._cancel.set()
        self._cancel_reason = reason or self._cancel_reason
        if self._active_run is not None:
            self._on_event('cancel-requested', {'owner': self._owner, 'reason': reason})

    def checkpoint(self):
        """worker 的步骤边界：已取消 / 所属动作已作废则抛 _ActionCancelled，阻断后续副作用。

        ★ 除了取消标志，还要看「这次运行是否还是当前运行」：看门狗强制释放后，旧 worker
        可能仍在跑，而下一个动作会 clear() 掉取消标志 —— 只查标志的话，僵尸 worker 会被
        「复活」并把进程拉起来。run_id 比对让它永久作废。
        非闸门线程（run_id 为 None）仍按取消标志判断，保持原有语义。
        """
        my_run = getattr(self._local, 'run_id', None)
        is_zombie = my_run is not None and my_run != self._active_run
        if is_zombie or self._cancel.is_set():
            raise _ActionCancelled()

    def wait_idle(self, timeout=_EMERGENCY_JOIN_SEC):
        """等待在飞行动作退出；False = 超时（调用方应继续强制清扫）。"""
        deadline = time.monotonic() + timeout
        while self._active_run is not None and time.monotonic() < deadline:
            time.sleep(0.1)
        return self._active_run is None

    # ---------- 内部：执行与收尾 ----------
    def _run(self, run_id, name, worker, args):
        self._local.run_id = run_id
        try:
            worker(*args)
        except _ActionCancelled:
            # 带上真实取消原因：看门狗超时不能用「紧急停止」四个字糊过去（审计实测到该歧义）
            self._on_event('cancelled', {'owner': name, 'reason': self._cancel_reason})
        except BaseException as e:      # noqa: BLE001 — 收尾责任在此，必须转成事件上报
            self._on_event('failed', {'owner': name, 'error': f'{type(e).__name__}: {e}'})
        finally:
            self._finish(run_id)

    def _watchdog_fire(self, run_id, name):
        if run_id != self._active_run:
            return
        self._on_event('watchdog', {'owner': name, 'seconds': self._watchdog_seconds})
        self._cancel_reason = f'看门狗超时 {self._watchdog_seconds}s'
        self._cancel.set()
        self._finish(run_id)

    def _finish(self, run_id):
        if run_id != self._active_run:
            return                      # 已被看门狗收尾，不重复释放
        self._active_run = None
        self._owner = ''
        timer, self._watchdog = self._watchdog, None
        if timer is not None:
            timer.cancel()
        self._lock.release()
        self._on_event('finished', {'owner': ''})
