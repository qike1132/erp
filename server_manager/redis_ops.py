"""server_manager 包的 Redis 探活/启停层(T3 包化第 3 步)。

从 app.py 迁出。本模块【只能】依赖标准库与 ``server_manager.constants`` ——
不得依赖任何 UI 工具包,也不得反向引用本包的 app 模块(那会循环导入)。

★ 状态自持: ``redis_process`` 归本类所有(原 app 的 ``self._redis_process``)。
★ 能力注入: 项目路径(``project_dir``)与服务层能力(``wait_service`` /
  ``svc_state`` / ``find_nssm`` / ``run_capture``)以及 app 的 ``read_stdout``
  一律由构造参数注入 —— 这些能力现归 ``service_ops``(Task 4 起)与 app 的
  ``read_stdout``,本模块只消费、不拥有。
"""
import socket
import subprocess
import threading
import time

from server_manager.constants import (
    _IS_WINDOWS,
    _REDIS_BROKER_PORT,
    _REDIS_CONF_PATHS,
    _REDIS_EXE_PATHS,
    _REDIS_PORT,
    _SVC_REDIS_BROKER,
    _SVC_REDIS_CACHE,
)


class RedisOps:
    """Redis 缓存(6379)与 ARQ broker(6380)的探活、启停与状态查询。

    与 app 的关系: ``ServerManagerApp`` 持有实例 ``self.redis``,并保留同名
    瘦转发(``_is_redis_running`` 等),使既有调用点不必改写。
    """

    def __init__(self, msg_queue, gate, project_dir, *, wait_service, svc_state,
                 find_nssm, run_capture, read_stdout):
        """``wait_service``/``svc_state``/``find_nssm``/``run_capture`` 属服务层
        (Task 4 起归 service_ops),``read_stdout`` 属 app(后端/前端进程共用)——
        本模块只消费、不拥有。"""
        self._msg_queue = msg_queue
        self._gate = gate
        self._project_dir = project_dir
        self._wait_service = wait_service
        self._svc_state = svc_state
        self._find_nssm = find_nssm
        self._run_capture = run_capture
        self._read_stdout = read_stdout
        # 本模块自己持有的状态(原 app 的 self._redis_process)。
        self.redis_process = None

    def get_env_value(self, key: str) -> str:
        """从项目 .env 文件读取指定键的值"""
        env_file = self._project_dir / '.env'
        if not env_file.is_file():
            return ''
        try:
            for line in env_file.read_text(encoding='utf-8').splitlines():
                line = line.strip()
                if line.startswith('#') or '=' not in line:
                    continue
                k, _, v = line.partition('=')
                if k.strip() == key:
                    return v.strip()
        except Exception:
            pass
        return ''

    def _find_redis(self):
        """查找Redis可执行文件和配置文件"""
        redis_exe = next((str(p) for p in _REDIS_EXE_PATHS if p.is_file()), None)
        redis_conf = next((str(p) for p in _REDIS_CONF_PATHS if p.is_file()), None)
        return redis_exe, redis_conf

    def ping(self, port, password):
        """RESP PING 判活：+PONG(免密)或 AUTH 后 +PONG 才算可用。

        仅做端口探测会误报（Redis 服务 Paused/停止或密码不匹配时，端口探测仍可能
        短暂通过）。缓存(6379)与 broker(6380)两份实现原本逐字相同、只差端口，
        收敛到此处。
        """
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=1) as sock:
                sock.sendall(b'*1\r\n$4\r\nPING\r\n')
                resp = sock.recv(64)
                if resp.startswith(b'+PONG'):
                    return True
                if resp.startswith(b'-NOAUTH'):
                    if not password:
                        return False
                    auth_cmd = (
                        f'*2\r\n$4\r\nAUTH\r\n${len(password)}\r\n{password}\r\n'
                    ).encode()
                    sock.sendall(auth_cmd)
                    auth_resp = sock.recv(64)
                    if not auth_resp.startswith(b'+OK'):
                        return False
                    sock.sendall(b'*1\r\n$4\r\nPING\r\n')
                    return sock.recv(64).startswith(b'+PONG')
            return False
        except Exception:
            return False

    def is_redis_running(self):
        """检测 Redis(6379) 是否真正可用：TCP 连通 + 认证通过。"""
        return self.ping(_REDIS_PORT, self.get_env_value('REDIS_PASSWORD'))

    def redis_service_state(self, name):
        """Redis 服务的状态文本；空字符串 = 服务不存在。

        复用 _svc_state 以继承其三态语义（未安装 / 未知 / STATE 文本）——旧实现是
        宽松版：任何 `sc` 失败都返回空串，把「查不出来」与「服务不存在」混同，
        于是查询超时会被当成「未安装」并给出误导性指引。
        仍保留「空串=不存在」这一对外契约（调用方据此返回 None 表示未安装）。
        """
        state = self._svc_state(name)
        return '' if '未安装' in state else state

    def start_redis_via_service(self, name):
        """优先通过 Windows 服务启动 Redis（返回 True/False/None=服务不存在）。

        ★ 为什么不直接 Popen：直接拉起的 redis-server 与 erp-redis / erp-redis-broker
        服务没有父子关系，服务管理器会显示「服务存在但无子进程」，而实例的存活实际
        吊在管理器进程上——管理器一退、机器一重启，Redis 就没了，且不会自愈
        （2026-09-16 实测：6379 的监听者父进程链全是 ERP服务器管理器_v5.33.exe）。
        改走服务后，开机自启、崩溃重拉、依赖顺序全部由 SCM 保证。
        """
        state = self.redis_service_state(name)
        if not state:
            return None
        nssm = self._find_nssm()
        cmd = [nssm, 'start', name] if nssm else ['sc', 'start', name]
        self._run_capture(cmd, timeout=20)
        state = self._wait_service(name, 'RUNNING', 20, interval=0.5,
                                   state_fn=self.redis_service_state)
        if 'RUNNING' in state.upper():
            return True
        self._msg_queue.put(('log', {'text': f'{name} 服务未在 20s 内进入 RUNNING（当前: {state or "未知"}）', 'level': 'WARNING'}))
        return False

    def start_redis(self):
        """启动 Redis 缓存实例（6379）。

        顺序：已在运行 → 直接返回；否则先走 Windows 服务（自愈 + 开机自启），
        服务不存在时才回退到直接 Popen（未安装服务的开发场景）。
        """
        if self.is_redis_running():
            self._msg_queue.put(('log', {'text': "Redis 已在运行"}))
            return True
        via_svc = self.start_redis_via_service(_SVC_REDIS_CACHE)
        if via_svc is True:
            if self.is_redis_running():
                self._msg_queue.put(('log', {'text': f"Redis 已由服务 {_SVC_REDIS_CACHE} 启动"}))
                return True
            self._msg_queue.put(('log', {'text': f"{_SVC_REDIS_CACHE} 服务已 RUNNING，但 Redis 未通过 PING 校验", 'level': 'WARNING'}))
            return False
        if via_svc is False:
            self._msg_queue.put(('log', {'text': f"Redis 服务启动失败，回退为直接拉起进程", 'level': 'WARNING'}))
        else:
            self._msg_queue.put(('log', {'text': f"未安装 {_SVC_REDIS_CACHE} 服务，将直接拉起 Redis 进程（不随开机自启）", 'level': 'WARNING'}))
        return self._start_redis_process()

    def _start_redis_process(self):
        """回退路径：直接把 redis-server 作为本管理器子进程拉起。"""
        redis_exe, redis_conf = self._find_redis()
        if not redis_exe:
            self._msg_queue.put(('log', {'text': "Redis 未安装，请安装 Redis for Windows", 'level': 'WARNING'}))
            return False
        try:
            cmd = [redis_exe] + ([redis_conf] if redis_conf else [])
            redis_password = self.get_env_value('REDIS_PASSWORD')
            if redis_password:
                cmd += ['--requirepass', redis_password]
            self._msg_queue.put(('log', {'text': f"正在启动 Redis: {redis_exe}"}))
            # ★ 本地 proc 绑定：self.redis_process 会被并发的 stop_redis() 置 None，
            # 原实现直接解引用 self.redis_process.pid/.poll() → 实测 AttributeError。
            proc = subprocess.Popen(cmd, creationflags=subprocess.CREATE_NO_WINDOW if _IS_WINDOWS else 0, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=False)
            self.redis_process = proc
            threading.Thread(target=self._read_stdout, args=(proc,), daemon=True).start()
            for _ in range(15):
                time.sleep(0.5)
                self._gate.checkpoint()
                if self.is_redis_running():
                    self._msg_queue.put(('log', {'text': f"Redis 启动成功 (PID: {proc.pid})"}))
                    return True
                if proc.poll() is not None:
                    self._msg_queue.put(('log', {'text': f"Redis 进程意外退出 (退出码: {proc.returncode})", 'level': 'ERROR'}))
                    return False
            self._msg_queue.put(('log', {'text': "Redis 启动超时，请检查端口6379是否被占用", 'level': 'WARNING'}))
            return False
        except Exception as e:
            self._msg_queue.put(('log', {'text': f"Redis 启动失败: {str(e)}", 'level': 'ERROR'}))
            return False

    def is_broker_running(self):
        """ARQ broker(6380) 是否真的可用：TCP 连通 + AUTH/PING（与缓存实例同款校验）。"""
        return self.ping(_REDIS_BROKER_PORT, self.get_env_value('REDIS_PASSWORD'))

    def ensure_redis_broker(self):
        """确保 ARQ broker(6380) 就绪——生产启动前调用，返回是否就绪。

        没有这一步，erp-arq 服务起来就直接连不上 6380 反复重启，而整套界面
        （服务状态、prod_runner 就绪徽章）全是绿的，用户完全无从察觉
        cron/备份/报表已经停了（2026-09-16 现场）。
        """
        if self.is_broker_running():
            return True
        self._msg_queue.put(('log', {'text': f'ARQ broker ({_REDIS_BROKER_PORT}) 未就绪，正在启动 {_SVC_REDIS_BROKER} 服务...'}))
        ok = self.start_redis_via_service(_SVC_REDIS_BROKER)
        if ok is None:
            self._msg_queue.put(('log', {
                'text': f'未安装 {_SVC_REDIS_BROKER} 服务，erp-arq 无法运行；'
                        f'请执行 scripts\\install_redis_services.ps1 注册 Redis 服务',
                'level': 'ERROR'}))
            return False
        for _ in range(20):
            time.sleep(0.5)
            self._gate.checkpoint()
            if self.is_broker_running():
                self._msg_queue.put(('log', {'text': f'ARQ broker 已就绪 ({_SVC_REDIS_BROKER})'}))
                return True
        self._msg_queue.put(('log', {'text': f'ARQ broker 启动后仍未通过 PING 校验，erp-arq 可能无法工作', 'level': 'ERROR'}))
        return False

    def stop_redis(self):
        """停止Redis服务"""
        stopped = False
        if self.redis_process and self.redis_process.poll() is None:
            try:
                self.redis_process.terminate()
                self.redis_process.wait(timeout=3)
                stopped = True
            except Exception:
                try:
                    self.redis_process.kill()
                    stopped = True
                except Exception:
                    pass
        # 不再按端口盲杀：受管的两个 Redis 实例已随 _SVC_ALL 经 nssm stop 停止；
        # 这里盲杀只会 taskkill 掉受管进程，5 秒后被 AppExit=Default Restart 拉起，
        # 界面却显示「已停止」(2026-09-28 评审确认)。残留时如实告警，不做静默处理。
        if self.is_redis_running():
            self._msg_queue.put(('log', {
                'text': f'Redis({_REDIS_PORT}) 仍在运行 —— 已跳过盲杀；受管实例请经服务停止',
                'level': 'WARNING'}))
        if stopped:
            self._msg_queue.put(('log', {'text': "Redis 已停止"}))
        self.redis_process = None
