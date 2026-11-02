"""server_manager 包的开发模式层(T5 包化第 5 步):双进程(uvicorn + vite)管理。

从 app.py 迁出。本模块【只能】依赖标准库、``server_manager.constants`` 与
``server_manager.windows_ops`` —— 不得依赖任何 UI 工具包,也不得反向引用本包的
app 模块(那会循环导入)。

★ 状态自持: 开发模式的 7 个状态(``mode`` / ``process`` / ``frontend_process`` /
  ``current_mode_key`` / ``startup_progress`` / ``startup_steps`` /
  ``startup_current_step``)归本类所有(原 app 的 ``self._mode`` 等)。app 侧为其中
  6 个名字(``startup_steps`` 除外,它仅本模块内部使用)提供**读写双向**属性桥,
  使既有 ~50 处读写点不必改写。
★ 兄弟 ops 直接注入**实例**: ``svc``(ServiceOps,供生产运行态判定)与 ``redis``
  (RedisOps,供 start_redis / stop_redis)——不为兄弟对象再包一层回调。
★ app 侧能力按先例注入: ``msg_queue`` / ``gate`` / ``project_dir`` / ``python_exe`` /
  ``frontend_dir``。
★ 2026-11-02 并行改造(v5.45): 开发栈迁独立端口(_DEV_API_PORT/_DEV_WEB_PORT),
  不再抢生产的 5002/3000,启动前也**不再停生产**——开发/生产两栈可同时运行。
  Redis 是共享基础设施: 生产在跑(或状态不可知)时,停止/重启开发模式**保留** Redis。
★ UI 胶水(`_start_dual_server` 的校验与 messagebox、``_on_dual_started`` /
  ``_on_dual_failed`` 的 status_bar_label / _update_all_ui)刻意留在 app —— 它们碰
  Tk,搬进来会违反本模块的红线(评审批准方案 A)。
"""
import contextlib
import os
import subprocess
import threading
import time

from server_manager import windows_ops
from server_manager.constants import _DEV_API_PORT, _DEV_WEB_PORT, _HTTP_DIRECT, _IS_WINDOWS, _SVC_API


class DevModeOps:
    """开发模式(前后端双进程)的启动、停止、重启与状态自持。

    与 app 的关系: ``ServerManagerApp`` 持有实例 ``self.dev``,为其中的 6 个状态名
    提供属性桥,并保留同名瘦转发(``_terminate_dev_processes`` 等),使既有调用点与
    静态断言不必改写。
    """

    def __init__(self, msg_queue, gate, project_dir, svc, redis, *,
                 python_exe, frontend_dir):
        """``msg_queue``/``gate``/``project_dir``/``python_exe``/``frontend_dir``
        由 app 注入;``svc``/``redis`` 为兄弟 ops 实例。"""
        self._msg_queue = msg_queue
        self._gate = gate
        self._project_dir = project_dir
        self._svc = svc
        self._redis = redis
        self._python_exe = python_exe
        self._frontend_dir = frontend_dir
        # ── 本模块自持的开发模式状态(原 app 的 self._mode / self._process / ...) ──
        self.mode = 'none'
        self.process = None
        self.frontend_process = None
        self.current_mode_key = ''
        self.startup_progress = 0
        self.startup_steps = []
        self.startup_current_step = ''

    # ── 启动 ────────────────────────────────────────────────────────────────
    # ★ 并行改造(v5.45): 开发模式不再与生产互斥——独占 5102/5173 两个端口,
    #   启动前只清这两个**开发专用**端口,绝不动生产的 5002/3000(也就不会
    #   taskkill 在跑的受管进程)。生产是否在跑与开发栈无关,可同时运行。
    def start_dual_flow(self, label):
        self.mode = 'starting'
        self.current_mode_key = 'dual_dev'
        self.startup_progress, self.startup_steps, self.startup_current_step = 0, ['检查开发端口', '确保Redis服务', '启动后端服务', '启动前端服务', '完成'], ''
        self._msg_queue.put(('log', {'text': f"正在启动{label}..."}))
        self._msg_queue.put(('status', {'text': f"正在启动{label}..."}))
        self._msg_queue.put(('ui_update', {}))
        self.start_dual_worker(label)

    def start_dual_worker(self, label):
        """后台执行端口清理（仅开发端口），随后复用现有启动流程。"""
        try:
            self._gate.checkpoint()
            self._msg_queue.put(('startup_progress', {'step': self.startup_steps[0], 'progress': 1, 'total': len(self.startup_steps)}))
            if not self._release_dev_ports():
                self._msg_queue.put(('dual_failed', {'label': label, 'reason': '开发端口清理失败'}))
                return
            self.start_dual_thread(label)
        except Exception as e:
            # 后台线程无 try/except 会静默终止，导致启动流程卡在 'starting' 且无任何日志；
            # 这里兜底记录并重置状态，让用户能看到失败原因。
            self._msg_queue.put(('log', {'text': f"启动流程异常: {e!s}", 'level': 'ERROR'}))
            self._msg_queue.put(('dual_failed', {'label': label, 'reason': str(e)}))

    def _release_dev_ports(self) -> bool:
        """清理开发专用端口(5102/5173)，返回是否确认清干净。

        与生产端口清理(app._release_ports)的语义差异：NSSM 受管服务**永不**
        监听开发端口，故无需受管 PID 排除集；但仍必须消费 kill_port_sync 的
        返回值——'still_occupied' 时若继续启动，新进程绑不上端口（或绑上却
        收不到流量），启动假成功。
        """
        ok = True
        for port in (_DEV_API_PORT, _DEV_WEB_PORT):
            state = windows_ops.kill_port_sync(port)
            if state == 'still_occupied':
                pids = windows_ops.find_port_pids(port)
                self._msg_queue.put(('log', {
                    'text': f'开发端口 {port} 清理失败：仍被 PID {pids or "?"} 占用'
                            f'（可能是提权进程，taskkill 被拒绝）。'
                            f'请用管理员终端执行 taskkill /F /T /PID <PID> 后重试。',
                    'level': 'ERROR',
                }))
                ok = False
        if ok:
            self._msg_queue.put(('log', {'text': f'开发端口已就绪 (API {_DEV_API_PORT} / WEB {_DEV_WEB_PORT})，不影响生产模式'}))
        return ok

    def start_dual_thread(self, label):
        try:
            creationflags = subprocess.CREATE_NO_WINDOW if _IS_WINDOWS else 0
            self._gate.checkpoint()

            # 仅清开发端口（worker 已清过一轮，此处兜底重启直入本函数的路径）
            windows_ops.kill_port_sync(_DEV_API_PORT)
            windows_ops.kill_port_sync(_DEV_WEB_PORT)

            self.startup_current_step, self.startup_progress = self.startup_steps[1], 2
            self._msg_queue.put(('startup_progress', {'step': self.startup_current_step, 'progress': self.startup_progress, 'total': len(self.startup_steps)}))
            self._gate.checkpoint()
            if not self._redis.start_redis():
                self._msg_queue.put(('log', {'text': '警告: Redis 未启动，部分功能可能不可用', 'level': 'WARNING'}))
            self.startup_current_step, self.startup_progress = self.startup_steps[2], 3
            self._msg_queue.put(('startup_progress', {'step': self.startup_current_step, 'progress': self.startup_progress, 'total': len(self.startup_steps)}))
            env = os.environ.copy()
            env.update({'PYTHONUNBUFFERED': '1', 'PYTHONIOENCODING': 'utf-8', 'PYTHONUTF8': '1', 'PYTHONPATH': str(self._project_dir)})
            self._gate.checkpoint()
            # 必须绑回环（AGENTS.md 红线 #3）：绑 0.0.0.0 会**绕过 nginx** 并把
            # /api/docs、/metrics 暴露给同网段（历史观察到的「:5002 绑 0.0.0.0 = GUI 开发栈」即此）。
            # 开发栈也只绑回环：前端 vite dev 走同机反代，回环已足够。
            backend_cmd = [self._python_exe, '-u', '-m', 'uvicorn', 'fastapi_app.main:app', '--host', '127.0.0.1', '--port', str(_DEV_API_PORT), '--log-level', 'info', '--reload', '--reload-dir', 'fastapi_app']
            self.process = subprocess.Popen(backend_cmd, cwd=str(self._project_dir), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=creationflags, text=False)
            self._msg_queue.put(('log', {'text': f"后端进程已启动 (PID: {self.process.pid})"}))
            threading.Thread(target=self.read_stdout, args=(self.process,), daemon=True).start()
            backend_ready = False
            for _ in range(30):
                self._gate.checkpoint()
                try:
                    # ★ 必须绕开系统代理（constants 的既有事故：prod_runner 曾因
                    #   代理转发 127.0.0.1 探测间歇失败而误判后端崩溃）。
                    #   ★ 必须用 .open：_HTTP_DIRECT 是 OpenerDirector，没有
                    #     urlopen 方法（2026-10-16 事故：.urlopen 每次必抛
                    #     AttributeError，被外层 except 吞掉 → 30 次探测全失败
                    #     → 杀掉已 startup complete 的健康后端）。hosting_view
                    #     用的正是 .open，此处对齐。
                    _HTTP_DIRECT.open(f'http://127.0.0.1:{_DEV_API_PORT}/api/health', timeout=2)
                    backend_ready = True
                    break
                except Exception:
                    time.sleep(1)
            if not backend_ready:
                self._msg_queue.put(('log', {'text': '后端启动失败或健康检查未通过', 'level': 'ERROR'}))
                if self.process and self.process.poll() is None:
                    self._msg_queue.put(('log', {'text': f'正在终止未就绪的后端进程 (PID: {self.process.pid})...'}))
                    windows_ops.kill_process_tree(self.process.pid)
                    with contextlib.suppress(Exception):
                        self.process.wait(timeout=3)
                self.process = None
                self._msg_queue.put(('dual_failed', {'label': label, 'reason': '后端未就绪'}))
                return
            self.startup_current_step, self.startup_progress = self.startup_steps[3], 4
            self._msg_queue.put(('startup_progress', {'step': self.startup_current_step, 'progress': self.startup_progress, 'total': len(self.startup_steps)}))
            npm_cmd = 'npm.cmd' if _IS_WINDOWS else 'npm'
            # 启动 Vite dev server。BACKEND_INTERNAL_URL 指向**开发后端**端口：
            # vite.config.ts 的 /api、/static、/ws 代理按该变量转发——手工
            # `npm run dev` 不带该变量时回落生产后端 5002（既有行为不变）。
            self._gate.checkpoint()
            self.frontend_process = subprocess.Popen([npm_cmd, 'run', 'dev', '--', '--port', str(_DEV_WEB_PORT)], cwd=str(self._frontend_dir), env={**os.environ, 'BACKEND_INTERNAL_URL': f'http://127.0.0.1:{_DEV_API_PORT}'}, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=creationflags, text=False)
            self._msg_queue.put(('log', {'text': f"前端进程已启动 (PID: {self.frontend_process.pid})"}))
            threading.Thread(target=self.read_frontend_stdout, args=(self.frontend_process,), daemon=True).start()
            frontend_ready = False
            for _ in range(60):
                self._gate.checkpoint()
                try:
                    # 同后端探测：直连 opener + .open（见上注释）
                    _HTTP_DIRECT.open(f'http://127.0.0.1:{_DEV_WEB_PORT}/', timeout=2)
                    frontend_ready = True
                    break
                except Exception:
                    time.sleep(1)
            if not frontend_ready:
                self._msg_queue.put(('log', {'text': '前端启动失败或健康检查未通过', 'level': 'ERROR'}))
                self.terminate_dev_processes('未就绪的')
                self._msg_queue.put(('dual_failed', {'label': label, 'reason': '前端未就绪'}))
                return
            self.startup_current_step, self.startup_progress = self.startup_steps[4], 5
            self._msg_queue.put(('startup_progress', {'step': self.startup_current_step, 'progress': self.startup_progress, 'total': len(self.startup_steps)}))
            self._msg_queue.put(('dual_started', {'label': label}))
        except Exception as e:
            self.process, self.frontend_process = None, None
            self._msg_queue.put(('dual_failed', {'label': label, 'reason': f'异常: {e!s}'}))

    # ── 停止 / 重启 ─────────────────────────────────────────────────────────
    def _production_may_run(self) -> bool:
        """生产模式是否在跑（或状态不可知）——决定停止开发时能否顺带停 Redis。

        Redis(6379) 是开发/生产**共享**的基础设施：生产在跑时停掉它会让
        erp-prod 的缓存层大面积降级。「未知」按可能在跑处理（查不出来 ≠ 已停止）。
        """
        state = self._svc.svc_state(_SVC_API)
        return 'RUNNING' in state.upper() or state == '未知'

    def stop_dual_mode_async(self, label):
        self._gate.start(f'停止{label}', self.stop_dual_flow, label)

    def stop_dual_flow(self, label):
        self._msg_queue.put(('log', {'text': f"正在停止{label}..."}))
        self._gate.checkpoint()
        frontend_proc, backend_proc = self.frontend_process, self.process
        self.frontend_process, self.process = None, None
        for proc, name in [(frontend_proc, '前端'), (backend_proc, '后端')]:
            if proc and proc.poll() is None:
                self._gate.checkpoint()
                self._msg_queue.put(('log', {'text': f'正在终止{name}进程树 (PID: {proc.pid})...'}))
                if _IS_WINDOWS:
                    with contextlib.suppress(Exception):
                        windows_ops.taskkill(proc.pid)
                else:
                    try:
                        proc.terminate()
                        proc.wait(timeout=5)
                    except Exception:
                        with contextlib.suppress(Exception):
                            proc.kill()
                self._msg_queue.put(('log', {'text': f'{name}进程已终止 (PID: {proc.pid})'}))
        # Redis 是共享基础设施：生产在跑（或状态不可知）时保留，避免把在跑的
        # 生产缓存层一起拔掉；生产确定没在跑时维持原行为（顺带收掉回退拉起的实例）。
        if self._production_may_run():
            self._msg_queue.put(('log', {'text': '生产模式在运行（或状态不可知），共享 Redis 已保留', 'level': 'INFO'}))
        else:
            self._redis.stop_redis()
        windows_ops.kill_port_sync(_DEV_API_PORT)
        windows_ops.kill_port_sync(_DEV_WEB_PORT)
        self.mode = 'none'
        self.current_mode_key = ""
        self._msg_queue.put(('ui_update', {}))
        self._msg_queue.put(('log', {'text': f"{label}已停止，开发端口已释放（不影响生产模式）"}))

    def restart_dual_thread(self):
        self.mode, self.current_mode_key = 'restarting', 'dual_dev'
        self.startup_progress, self.startup_steps, self.startup_current_step = 0, ['检查开发端口', '确保Redis服务', '启动后端服务', '启动前端服务', '完成'], ''
        self._msg_queue.put(('ui_update', {}))
        label = '开发模式'
        self.terminate_dev_processes('（重启）')
        # 与 stop_dual_flow 同款判断：生产在跑时 Redis 是共享设施，重启开发不动它。
        if not self._production_may_run():
            self._redis.stop_redis()
        windows_ops.kill_port_sync(_DEV_API_PORT)
        windows_ops.kill_port_sync(_DEV_WEB_PORT)
        time.sleep(0.5)
        self._gate.checkpoint()
        self.start_dual_thread(label)

    # ── 统一的开发进程终止原语 ──────────────────────────────────────────────
    def terminate_dev_processes(self, reason='', *, wait=True) -> bool:
        """终止管理器自启的开发前端/后端进程树并清空句柄；返回是否有进程被终止。

        收敛前这里散着 4 份变体（stop_all / 启动失败回退 / 重启 / 切生产前）：
        有的单杀、有的先手工收子树、有的等 3s、有的等 5s、有的不等 —— 终止语义
        已经漂移，调优一处不会传播到其余三处（2026-09-28 评审）。

        ``windows_ops.kill_process_tree`` 在 Windows 走 `taskkill /T`，本就会连树
        一起杀，故重启路径原先「先逐个杀子进程再杀父」的写法是冗余的。
        """
        terminated = False
        for proc, name in ((self.frontend_process, '前端'), (self.process, '后端')):
            if not (proc and proc.poll() is None):
                continue
            self._msg_queue.put(('log', {'text': f'正在终止{reason}{name}进程树 (PID: {proc.pid})...'}))
            windows_ops.kill_process_tree(proc.pid)
            if wait:
                with contextlib.suppress(Exception):
                    proc.wait(timeout=5)
            self._msg_queue.put(('log', {'text': f'{reason}{name}进程已终止 (PID: {proc.pid})'}))
            terminated = True
        self.frontend_process = None
        self.process = None
        return terminated

    # ── 子进程输出读取 ──────────────────────────────────────────────────────
    def read_stdout(self, proc):
        try:
            if proc.stdout:
                try:
                    # 按行读取（readline 迭代器）：读到 '\n' 即返回，不会像 read(4096) 那样
                    # 阻塞凑块导致 uvicorn 启动日志延迟显示；'\n' 是 ASCII 字节，UTF-8 中文
                    # 不会跨行被切断，统一解码器(含 UTF-16 回退)已足够处理乱码。
                    batch = []
                    for raw_line in proc.stdout:
                        line = self._svc.decode_output(raw_line, strip=True) if isinstance(raw_line, bytes) else str(raw_line).strip()
                        if line:
                            batch.append(line)
                            if len(batch) >= 10:
                                self._msg_queue.put(('log_batch', {'lines': batch[:], 'level': 'INFO'}))
                                batch.clear()
                    if batch:
                        self._msg_queue.put(('log_batch', {'lines': batch, 'level': 'INFO'}))
                finally:
                    proc.stdout.close()
        except Exception as e:
            self._msg_queue.put(('log', {'text': f"读取日志异常: {e!s}", 'level': 'ERROR'}))

    def read_frontend_stdout(self, proc):
        # 与 read_stdout 同款 try/finally：循环退出后必须关 stdout，
        # 否则管道句柄悬到 GC（对齐 read_stdout 的收尾契约）。
        try:
            batch = []
            while True:
                try:
                    line = proc.stdout.readline()
                    if not line:
                        break
                    text = self._svc.decode_output(line, strip=True)  # 统一解码(含 UTF-16)，修复中文 Windows 前端输出乱码
                    if text:
                        level = 'ERROR' if any(k in text.lower() for k in ['error', 'exception', 'failed']) else 'INFO'
                        batch.append((f'[WEB] {text}', level))
                        if len(batch) >= 10:
                            for t, l in batch:
                                self._msg_queue.put(('log', {'text': t, 'level': l}))
                            batch.clear()
                except Exception:
                    break
            if batch:
                for t, l in batch:
                    self._msg_queue.put(('log', {'text': t, 'level': l}))
        finally:
            with contextlib.suppress(Exception):
                proc.stdout.close()
