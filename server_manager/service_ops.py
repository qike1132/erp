"""server_manager 包的 NSSM/sc 服务操作层(T4 包化第 4 步)。

从 app.py 迁出。本模块【只能】依赖标准库、``server_manager.constants`` 与
``server_manager.windows_ops`` —— 不得依赖任何 UI 工具包,也不得反向引用本包的
app 模块(那会循环导入)。

★ 能力注入: ``msg_queue`` / ``gate`` / ``project_dir`` / ``log_message`` 一律由构造
  参数注入;本模块【不】持有任何 app 状态(托管状态如 ``_prod_start_ts`` 留在 app,
  由 app 的动作入口维护)。nssm 搜索由 ``find_nssm`` 自行完成,无外部注入。
★ 进程/端口原语复用 ``windows_ops``(T2 已抽出的纯函数),不复制实现。
"""
import locale
import shutil
import subprocess
import time
from typing import NamedTuple

from server_manager import git_guard, windows_ops
from server_manager.constants import (
    _IS_WINDOWS,
    _NSSM_CANDIDATES,
    _SVC_ALL,
    _SVC_API,
    _SVC_ARQ,
    _SVC_REVERSE,
    _SVC_START_ORDER,
    _SVC_WEB,
)


def decode_output(raw, *, strip=False):
    """把子进程的原始字节流解码为文本（Windows 控制台程序编码并不统一）。

    · nssm 走宽字符 API，输出是 **UTF-16LE**：按 utf-8 解会得到
      "E r r o r   c r e a t i n g   s e r v i c e !" 这种隔字带空格的乱码，
      中文错误文本更是整段变成 U+FFFD。2026-09-16 实测：nssm 明明回了
      「指定的服务已存在。」，界面/日志里却只剩不可读字符，故障定位被直接堵死。
    · sc.exe 走 OEM 代码页（中文系统 cp936/GBK），偶尔夹杂 UTF-8。

    因此先按 BOM / NUL 密度判 UTF-16，再回落到多编码严格试探；
    任何一步都不抛异常——解码失败只降级为 replace，绝不因此吞掉真实返回码。

    ``strip=True`` 供逐行读取用（去行尾换行）。原先这是另一份实现 _decode_line，
    只差「没有 UTF-16 分支」——逐行读 nssm 这类宽字符输出时会退化成乱码。
    （2026-10-16 结构评审 L3：由 ServiceOps 的 staticmethod 提为模块级纯函数，
    使 log_ops 不必为复用它而依赖整个服务层；类内保留同名转发。）
    """
    def _fin(text: str) -> str:
        return text.strip() if strip else text

    if not raw:
        return ''
    if raw[:2] in (b'\xff\xfe', b'\xfe\xff'):
        try:
            return _fin(raw.decode('utf-16', errors='replace').lstrip(chr(0xFEFF)))
        except Exception:  # noqa: S110 - 解码试探，失败即回退下一种编码
            pass
    elif raw.count(b'\x00') * 4 > len(raw):
        # UTF-16LE 的 ASCII 段每个字符后跟一个 \x00，NUL 占比远高于任何 8bit 编码
        try:
            return _fin(raw.decode('utf-16-le', errors='replace'))
        except Exception:  # noqa: S110 - 解码探测，失败即试下一种编码
            pass
    preferred = locale.getpreferredencoding(False) or ''
    for enc in ('utf-8', 'gb18030', 'cp936', preferred):
        if not enc:
            continue
        try:
            return _fin(raw.decode(enc, errors='strict'))
        except Exception:  # noqa: S112 - 解码探测，失败即试下一种编码
            continue
    return _fin(raw.decode('utf-8', errors='replace'))


class ServiceRunResult(NamedTuple):
    """启动/重启的结构化结果（2026-10-25 上线前检查 B1）。

    「服务终态在跑」与「本次重启已生效」是两个独立事实，此前共用一个
    ``ok=True`` —— 同 PID（停机未停成，服务从未换过进程）也被当成功返回，
    调用方（发布脚本/界面）随后用不绑定版本的健康检查验收，旧代码被当
    新版本发布（假成功）。拆分后：

    - ``ok``：服务终态是否 RUNNING（"现在在跑"）。
    - ``effective``：本次动作是否**验证生效**——启动路径 = RUNNING；重启路径
      还要求新 PID 与停机前不同（PID 不可读同样不算，宁可误报不可漏报）。
      发布验收必须同时要求两者，绝不能只看 ``ok``。
    """

    ok: bool
    state: str
    pid: int | None
    effective: bool


class ServiceOps:
    """生产模式(Windows 服务 + NSSM)的查询、启停、安装与卸载。

    与 app 的关系: ``ServerManagerApp`` 持有实例 ``self.svc``,并保留同名
    瘦转发(``_svc_state`` / ``_nssm_install`` 等),使既有调用点不必改写。
    """

    def __init__(self, msg_queue, gate, project_dir, log_message, release_ports=None):
        """``msg_queue`` / ``gate`` / ``project_dir`` / ``log_message`` 由 app 注入。

        ``release_ports`` 可选注入：重启链路启动前清 5002/3000 的能力（实现留在 app，
        与 ``DevModeOps`` 同一注入方式）。未注入则跳过清理。
        """
        self._msg_queue = msg_queue
        self._gate = gate
        self._project_dir = project_dir
        self._log_message = log_message
        self._release_ports = release_ports

    def find_nssm(self):
        found = shutil.which('nssm')
        if found:
            return found
        for cand in _NSSM_CANDIDATES:
            if cand.is_file():
                return str(cand)
        return None

    @staticmethod
    def decode_output(raw, *, strip=False):
        """统一解码器的既有入口（实现已提为模块级 ``decode_output``，见其 docstring）。
        保留 staticmethod 形态：既有调用点（dev_mode 经实例、run_capture 内部）不必改写。"""
        return decode_output(raw, strip=strip)

    def run_capture(self, args, timeout=20):
        try:
            result = subprocess.run(args, creationflags=subprocess.CREATE_NO_WINDOW if _IS_WINDOWS else 0,
                                    capture_output=True, timeout=timeout)
            return (result.returncode,
                    self.decode_output(result.stdout or b'') + self.decode_output(result.stderr or b''))
        except Exception as e:
            return -1, str(e)

    def svc_state(self, name):
        """返回三态：'未安装' | '未知' | STATE 文本（如 '4 RUNNING' / '1 STOPPED'）。

        ★ 三态语义（勿回退）：只有 rc==1060（ERROR_SERVICE_DOES_NOT_EXIST）或输出
        明确含 1060 且【没有】STATE 行才判「未安装」；其它任何查询失败（5=拒绝访问、
        超时、被安全软件拦截、解码异常）一律判「未知」——绝不把「查不出来」当「不存在」，
        否则 _ensure_production_stopped 会静默跳过仍在运行的生产服务，开发模式随即
        抢占 5002/3000 与生产互杀。
        """
        code, out = self.run_capture(['sc', 'query', name], timeout=5)
        if code == 1060 or ('1060' in out and 'STATE' not in out):
            return '未安装'
        if code != 0 or 'SERVICE_NAME' not in out:
            return '未知'
        for line in out.splitlines():
            if 'STATE' in line:
                parts = line.split(':', 1)
                if len(parts) > 1:
                    return ' '.join(parts[1].split())[:28]
        return '未知'

    def svc_pid_ex(self, name):
        """`svc_pid` 的可判失败版本：返回 ``(pid, ok)``。

        ``ok=False`` 表示**探测通道不可用**（sc 非零退出 / 被安全策略拦 / 超时），
        与「通道正常但服务未运行（pid=None, ok=True）」严格区分 —— 前者是
        「不可知」（用于受管集合的 sentinel None），后者是「确认为空」。
        混淆两者会让调用方把「查不出来」当成「没有受管进程」→ 误杀 erp-prod。

        ⚠️ 既有 ``svc_pid`` 保持「拿不到就 None」的旧语义不变（其消费者不关心通道健康）。
        """
        code, out = self.run_capture(['sc', 'queryex', name], timeout=5)
        if code != 0:
            return None, False
        for line in out.splitlines():
            stripped = line.strip()
            if stripped.startswith('PID'):
                parts = stripped.split(':', 1)
                if len(parts) > 1 and parts[1].strip().isdigit():
                    return int(parts[1].strip()), True
        return None, True

    def svc_pid(self, name):
        """查询 Windows 服务当前进程 PID（sc queryex），未运行返回 None"""
        return self.svc_pid_ex(name)[0]

    def wait_service(self, name, target, timeout, *, checkpoint=True, interval=1.0, state_fn=None,
                     abort_on_unknown=False):
        """轮询服务状态直到包含 ``target``(大写比对)；返回最后一次读到的状态。

        收敛前这里有 4 份手写副本(_start_redis_via_service / _wait_service_stopped /
        _stop_managed_services 内联 / _wait_service_running)，超时与措辞各不相同，
        调优一处不会传播到其余三处。

        ``checkpoint=False`` 供紧急停止用：stop_all 已先 cancel() 置位，任何
        checkpoint 都会抛 _ActionCancelled 把「停服务」半路打断 —— 服务没停成，
        端口清理又会误杀受管进程触发 NSSM 重启。

        ``state_fn`` 供 Redis 用(它读 _redis_service_state 的宽松契约)。

        ``abort_on_unknown`` 供**停止路径**用：状态为 '未知'（探测通道不可用）时立即
        返回，不再空转完整个超时 —— 通道已经查不出来，继续轮询注定没有结果，而
        45s 全浪费掉。默认 False，等待「RUNNING」的正向路径（Redis 启动）不受影响。
        """
        fn = state_fn or self.svc_state
        deadline = time.monotonic() + timeout
        state = fn(name)
        while True:
            if target in state.upper():
                return state
            if abort_on_unknown and state == '未知':
                # 通道不可用：状态**不可知**，既不等于 STOPPED 也不等于还在跑。
                # 立刻返回让调用方按『未能确认』处理并如实汇报，而非空转超时。
                return state
            if time.monotonic() >= deadline:
                return state
            # gate 可为 None（headless 消费方，如 scripts/restart_backend.py 直跑）：
            # 无 GUI 门时 checkpoint 即 no-op，不得 AttributeError——否则 stop 已发出、
            # start 永不执行，服务停在 STOPPED（恰是 stop_start 原语要防的形态）。
            if checkpoint and self._gate is not None:
                self._gate.checkpoint()
            time.sleep(interval)
            state = fn(name)

    def wait_service_stopped(self, name, timeout=45):
        """发出 nssm stop 后轮询服务状态直到 STOPPED；超时返回 False。

        NSSM stop 立即返回，服务进入 STOP_PENDING，优雅关闭需数秒。
        若在 STOP_PENDING 期间强杀被管进程，会被 AppExit Default Restart
        判定为崩溃而自动重启，与目标模式抢占端口。因此必须等待确认 STOPPED。

        ★ '未知'（探测通道不可用）时立刻返回 False，让调用方按『未能确认』
        如实汇报 —— 不能把「查不出来」洗成「已停止」。

        ★ nssm 缺失时必须回退 `sc stop`（与 _stop_service_sync / stop_managed_services
        同款分支）：直接把 find_nssm() 的 None 塞进 argv 会让 subprocess.run 抛异常、
        被 run_capture 吞成 (-1, ...) —— 停止命令根本没发出，调用方却继续轮询到超时。
        """
        nssm = self.find_nssm()
        if nssm:
            self.run_capture([nssm, 'stop', name], timeout=15)
        else:
            self.run_capture(['sc', 'stop', name], timeout=30)
        return 'STOPPED' in self.wait_service(name, 'STOPPED', timeout, abort_on_unknown=True)

    def managed_service_pids(self):
        """NSSM 受管进程集合（服务根 PID + 整棵子树）。

        ★ P0-4 的核心闸门：受管进程**绝不能被直接 kill** —— NSSM 的
        AppExit=Default Restart + AppRestartDelay=5000 会在 5 秒后把它拉起来，
        杀掉→复活→再杀就是「杀不死」死循环。受管进程只能经 `nssm stop` 停止。

        ★ sentinel 语义（fail-safe）：本方法有**两种**返回类型，调用方必须区分，
        **严禁用 `or set()` / `or ()` 之类做静默归一**：
          - 返回 `set()`（可空）= 「**已知**受管集合」；空 set 表示**确认**当前无受管进程。
          - 返回 `None`（sentinel）= 「受管集合**不可知**」——探测通道（sc queryex）
            不可用，此时**不能**假定「没有受管进程」（那 = fail-open → 全杀 → 误杀
            erp-prod → NSSM 5 秒拉起 → 死循环）。
        调用方正确处置：`None` → 告警 + **放弃清理**（fail-safe），绝不进入任何
        「按该集合排除后再 kill」的路径。
        """
        managed = set()
        for name in _SVC_ALL:
            pid, ok = self.svc_pid_ex(name)
            if not ok:
                # 探测通道整体不可用（sc 被拦 / queryex 非零退出）：不可知 → sentinel
                return None
            if pid:
                managed.add(pid)
                managed.update(windows_ops.collect_process_tree(pid))
        return managed

    def stop_managed_services(self):
        """正常停止 NSSM 受管服务（erp-prod / erp-arq / erp-web），返回受管 PID 集合供端口清理兜底。

        ★ 与 _service_cmd_sync('stop') 的关键区别：本方法【不带 checkpoint】——
        紧急停止 stop_all 已先 cancel() 置位取消标志，任何 checkpoint 都会抛
        _ActionCancelled 把「停服务」半路打断，于是服务根本没停、端口清理又误杀
        受管进程触发 NSSM 5 秒自动重启 —— 这正是「紧急停止变成重启」的根因。

        返回 (成功停止的服务数, 受管 PID 集合)。受管 PID 无论 stop 成败都要返回，
        供后续 _kill_port_sync 排除，避免 stop 超时失败时端口清理误杀受管进程。

        ★ 返回 (成功停止的服务数, 受管 PID 集合, 未能确认停止的服务名列表)。
        第二个元素可能是 `None`（受管集合不可知，见 `managed_service_pids`）——
        调用方**必须**显式判 None 并放弃「按集合排除后清理端口」的路径，
        绝不能把它当空集用（`exclude=None` 会被折叠成空集 → 误杀受管进程）。
        第三个元素供调用方生成**如实的**汇总语 —— 统计「端口清了但服务没停全」
        这类「部分成功」必须说出来，否则汇总语会与上方的 WARNING 自相矛盾。
        """
        nssm = self.find_nssm()
        managed = self.managed_service_pids()
        if managed is None:
            self._msg_queue.put(('log', {
                'text': '无法确认 NSSM 受管进程集合（服务查询失败）：'
                        '后续端口清理将不再按集合排除，改为自行探测并 fail-safe。',
                'level': 'WARNING',
            }))
        stopped = 0
        failed = []
        for name in _SVC_ALL:
            state = self.svc_state(name)
            if '未安装' in state or 'STOPPED' in state:
                continue
            self._msg_queue.put(('log', {'text': f'正在停止生产服务 {name}...'}))
            if nssm:
                self.run_capture([nssm, 'stop', name], timeout=30)
            else:
                self.run_capture(['sc', 'stop', name], timeout=30)
            st = self.wait_service(name, 'STOPPED', 45, checkpoint=False, abort_on_unknown=True)
            if 'STOPPED' in st:
                stopped += 1
                self._msg_queue.put(('log', {'text': f'{name} 已停止'}))
            else:
                failed.append(name)
                self._msg_queue.put(('log', {'text': f'{name} 在 45s 内未确认 STOPPED，将在端口清理时排除其受管进程以避免误杀触发重启', 'level': 'WARNING'}))
        return stopped, managed, failed

    def ensure_production_stopped(self):
        """切换前停止生产模式：停 NSSM 服务 + 清游离的 prod_runner 进程树。

        ★ 返回契约固定为 3 元组 (ok, fail_reason, stopped_any)。
          P0-1：原实现在超时分支返回 2 元组，而调用方按 3 元组解包
                → ValueError → 「开发模式 100% 无法启动」。
          P0-2：原实现在 `except Exception: pass` 之后落到 `return True, None, ...`
                → 任何异常都被静默转成「成功」，调用方继续启动 → 双进程抢端口。
                现改为：失败必须带真实原因返回，不存在静默成功路径。
        """
        stopped_any = False
        # ★ uncertain 标志：本次是否出现「无法确认是否已停止」的服务。
        #   为什么不能 `continue` 了事：continue 之后会落到函数结尾的
        #   `return True, None, ...` —— 对外宣告「生产已停止」，而日志里明明写着
        #   「无法验证是否已停止」。这正是本方案要消灭的**假成功**。
        #   正确姿态：尽量去停（不能因为查不到就不停），但最终**如实降级**为 False。
        uncertain = []
        nssm = self.find_nssm()
        if nssm:
            for name in (_SVC_API, _SVC_ARQ, _SVC_WEB):
                state = self.svc_state(name)
                if 'STOPPED' in state or '未安装' in state:
                    continue
                unknowable = state == '未知'
                if unknowable:
                    # 通道不可用 ≠ 未安装。不能像 '未安装' 那样跳过（那会在
                    # 「服务其实在跑」时宣告切换成功），也不能当场判失败
                    # （那会把「查不到」定性成「停不掉」而根本不去尝试停）。
                    self._msg_queue.put(('log', {
                        'text': f'服务 {name} 状态查询失败（sc 不可用），仍尝试停止并等待确认',
                        'level': 'WARNING',
                    }))
                self._msg_queue.put(('log', {'text': f'正在停止生产服务 {name}...'}))
                if not self.wait_service_stopped(name):
                    if unknowable or self.svc_state(name) == '未知':
                        # 停是确实尝试过了，但结果**无法验证** → 如实记账，绝不当成功
                        uncertain.append(name)
                        self._msg_queue.put(('log', {
                            'text': f'{name} 状态查询失败且未能确认 STOPPED，无法验证是否已停止',
                            'level': 'WARNING',
                        }))
                        continue
                    return False, f'{name} 停止超时（STOP_PENDING 未确认），已中止切换', stopped_any
                stopped_any = True
        # 清理游离的 prod_runner（不受 NSSM 控制）；受管进程跳过，交给 nssm stop（P0-4）
        self._gate.checkpoint()
        try:
            managed = self.managed_service_pids()
            # ★ sentinel：None = 受管集合不可知。此时不能进入「排除后再杀」的路径
            # （exclude 会被 `or ()` 折叠成空集 → 误杀受管进程）。fail-safe：跳过清理并告警。
            if managed is None:
                self._msg_queue.put(('log', {
                    'text': '无法确认 NSSM 受管进程集合（服务查询失败），已跳过残留 prod_runner 清理以免误杀',
                    'level': 'WARNING',
                }))
                loose = []
            else:
                loose = windows_ops.find_loose_prod_runner_pids(exclude=managed)
            for pid in loose:
                windows_ops.kill_process_tree(pid)
                self._msg_queue.put(('log', {'text': f'已清理游离 prod_runner 进程 (PID: {pid})'}))
                stopped_any = True
            if managed:
                self._msg_queue.put(('log', {'text': f'已跳过 {len(managed)} 个 NSSM 受管进程（须经服务停止命令处理）'}))
        except Exception as e:
            # 失败如实返回：不允许「扫不到 / 扫描报错」等同于「没有残留」
            self._msg_queue.put(('log', {'text': f'残留 prod_runner 扫描失败: {e}', 'level': 'WARNING'}))
            return False, f'残留进程扫描失败: {e}', stopped_any
        if uncertain:
            # ★ 如实降级：有服务「无法确认是否已停止」时，**不能**返回成功。
            #   调用方（切换生产→开发）会据此中止，避免在「生产可能还在跑」的
            #   前提下启动开发模式 → 双进程抢 5002 端口。
            return (False,
                    f'未能确认 {"、".join(uncertain)} 是否已停止（sc 查询失败），'
                    f'已中止切换以免与生产进程抢占端口',
                    stopped_any)
        return True, None, stopped_any

    def svc_installed(self, name):
        """服务是否已注册到 SCM（供安装幂等判定使用）。

        与 `_svc_state` 的分工：这里只回答「在不在」，且**不把「查不出来」当成未安装**
        —— `sc query` 失败时返回 False，随后的 `nssm install` 会用自己的错误码报出
        真实原因（拒绝访问 / 找不到文件…），而不是被静默跳过。
        """
        code, out = self.run_capture(['sc', 'query', name], timeout=5)
        return code == 0 and 'SERVICE_NAME' in out

    @staticmethod
    def _looks_like_exists_error(out):
        """识别 nssm 的「服务已存在」失败（Windows 1073 ERROR_SERVICE_EXISTS）。

        兜底用：`sc query` 可能因权限/策略/瞬时故障查不到（此时 `_svc_installed`
        只能返回 False），此时只能靠 install 自己的错误文本判断，
        否则一个「重复注册」会被当成真失败，把整轮安装判死。
        """
        text = (out or '').lower()
        return any(marker in text for marker in ('已存在', 'already exists', '1073'))

    def nssm_install(self, nssm, name, app, params, env_extra, depends=None):
        # Step 1: 创建服务（仅注册应用路径，不传参数，避免 NSSM 弹 GUI）
        #   已存在时**不能再 install**：CreateService 会以 1073「指定的服务已存在。」
        #   失败，整轮安装被判定为失败（2026-09-16 实测：erp-prod/erp-arq 早已注册，
        #   点『安装服务』必然报「注册失败」，且乱码后连原因都读不出来）。
        #   改为「跳过创建 + 覆盖配置」——「安装服务」可反复点击且结果幂等。
        existed = self.svc_installed(name)
        if existed:
            self._log_message(f'{name} 服务已存在，跳过创建，改为更新配置')
        else:
            code, out = self.run_capture([nssm, 'install', name, app], timeout=30)
            if code != 0:
                if self._looks_like_exists_error(out):
                    # 预判失败但服务其实在 → 同样按「已存在」处理，绝不因重复注册判死
                    existed = True
                    self._log_message(f'{name} 服务已存在（install 返回 1073），改为更新配置', 'WARNING')
                else:
                    self._log_message(f'{name} 注册失败: {out}', 'ERROR')
                    return False
        if existed and 'RUNNING' in self.svc_state(name):
            self._log_message(f'{name} 正在运行，配置变更将在下次启动生效（可点『重启』立即生效）', 'WARNING')
        # Step 2: 设置启动参数（NSSM AppParameters 接受空格分隔的完整命令行）
        if params:
            self.run_capture([nssm, 'set', name, 'AppParameters', ' '.join(params)], timeout=15)
        # Step 3: 设置其他属性
        #   Application 也一并写入：服务已存在时，这一步会把可执行文件路径纠正为当前值
        #   （换过 Python / 虚拟环境后，重新点『安装服务』即可修复指向）。
        settings = [
            ('Application', app),
            ('AppDirectory', str(self._project_dir)),
            ('AppStdout', str(self._project_dir / 'logs' / f'{name}.log')),
            ('AppStderr', str(self._project_dir / 'logs' / f'{name}.log')),
            ('AppRotateFiles', '1'),
            ('AppRotateBytes', '10485760'),
            ('AppExit', 'Default Restart'),
            ('AppRestartDelay', '5000'),
            ('Start', 'SERVICE_AUTO_START'),
            ('AppEnvironmentExtra', env_extra),
            ('AppNoConsole', '1'),
        ]
        for key, val in settings:
            # 列表值逐元素展开传参(仅 AppEnvironmentExtra)：NSSM 把该参数按每个 argv
            # 元素设一个环境变量、在第一个 '=' 处切分 —— 拼成一整串会让 6 个变量里
            # 只剩 1 个(且值畸变成整串)，其余静默丢失，而界面照报「已注册」
            # (2026-09-28 评审确认，本机注册表实测只有 1 个元素)。
            args = [nssm, 'set', name, key] + (list(val) if isinstance(val, list) else [val])
            if isinstance(val, list) and not val:
                continue  # 空列表：该服务无需额外环境变量(如 erp-web)
            code, out = self.run_capture(args, timeout=15)
            if code != 0:
                # 旧实现丢弃了全部返回码：某项没写进去也照样报「已注册」，无从判断。
                self._log_message(f'{name} 设置 {key} 失败: {out.strip() or f"退出码 {code}"}', 'WARNING')
        # Step 4: 依赖关系（开机由 SCM 串行保证启动顺序）
        #   只写已注册的依赖服务：依赖一个不存在的服务会让 SCM 直接拒绝启动本服务
        #   （错误 1068「依存服务或组无法启动」），比没有依赖更糟。
        self.apply_depends(name, depends)
        self._log_message(f'{name} {"已存在，配置已更新" if existed else "已注册为 Windows 服务"}（开机自启 + 崩溃自动重启）')
        return True

    # ---------- AppEnvironmentExtra 单键读写（Worker 数等「改完重启即生效」的配置）----------
    # 与 nssm_install 的区别：后者整包覆盖 AppEnvironmentExtra（安装流程用），
    # 这里只替换一个键、其余元素逐项原样保留 —— 免得为了改 worker 数把
    # APP_ENV/PYTHONUTF8 等一并重写。

    def _read_env_extra(self, nssm, name, timeout=20) -> list[str] | None:
        """读 AppEnvironmentExtra 的元素列表；None 表示读取失败（与「空列表」区分）。"""
        code, out = self.run_capture([nssm, 'get', name, 'AppEnvironmentExtra'], timeout=timeout)
        if code != 0:
            return None
        # nssm get 对 MULTI_SZ 逐元素一行输出；空白行是终止空元素，剔除。
        return [line.strip() for line in out.splitlines() if line.strip()]

    def get_env_extra_key(self, nssm, name, key, read_timeout=None) -> str | None:
        """读某个键的**已配置**值。界面用它显示真值，避免「显示 4、实际 8」的静默降级。

        ``read_timeout``：主线程调用方可传短超时（如 3s）防 nssm 卡住冻界面；
        None 沿用 run_capture 默认 20s。
        """
        if read_timeout is not None:
            elements = self._read_env_extra(nssm, name, timeout=read_timeout)
        else:
            elements = self._read_env_extra(nssm, name)
        if elements is None:
            return None
        prefix = f'{key}='
        for element in elements:
            if element.upper().startswith(prefix.upper()):
                return element[len(prefix):]
        return None

    def set_env_extra_key(self, nssm, name, key, value) -> tuple[bool, str]:
        """只替换一个键并回读校验。

        ★ 必须逐项作为独立 argv 传给 ``nssm set``：拼成一整串时 NSSM 只在第一个
          ``=`` 处切分，6 个变量只有第一项生效（2026-09-28 评审确认的既有缺陷）。
        """
        value = str(value).strip()
        if not value:
            return False, f'{key} 不能为空'
        elements = self._read_env_extra(nssm, name)
        if elements is None:
            return False, f'读取 {name} 的 AppEnvironmentExtra 失败（server_manager 是否以管理员身份运行？）'

        prefix = f'{key}='
        new_element = f'{key}={value}'
        updated: list[str] = []
        replaced = False
        for element in elements:
            if not replaced and element.upper().startswith(prefix.upper()):
                updated.append(new_element)
                replaced = True
            else:
                updated.append(element)
        if not replaced:  # 该键原本不存在 → 追加，而不是丢弃其余
            updated.append(new_element)

        code, out = self.run_capture([nssm, 'set', name, 'AppEnvironmentExtra', *updated])
        if code != 0:
            return False, f'写入 {name} 失败：{out.strip() or f"退出码 {code}"}'

        after = self._read_env_extra(nssm, name)
        if after != updated:
            got = '读取失败' if after is None else f'{len(after)} 项'
            return False, f'写后校验不一致：期望 {len(updated)} 项，回读 {got}'
        return True, f'{name} 已写入 {new_element}（重启该服务后生效）'

    def apply_depends(self, name, depends):
        """设置服务的 SCM 依赖关系（DependOnService）。"""
        if not depends:
            return
        missing = [d for d in depends if not self.svc_installed(d)]
        if missing:
            self._log_message(
                f'{name} 跳过依赖设置：{", ".join(missing)} 服务不存在，'
                f'请先安装 Redis 服务（依赖不存在的服务会导致本服务无法启动）', 'WARNING')
            return
        nssm = self.find_nssm()
        if not nssm:
            return
        code, out = self.run_capture([nssm, 'set', name, 'DependOnService', ' '.join(depends)], timeout=15)
        if code != 0:
            # 旧版 NSSM 无该参数，回退直接写注册表（SCM 实际读取的位置）
            self._set_depends_registry(name, depends, out)
        else:
            self._log_message(f'{name} 依赖已设置: {", ".join(depends)}')

    def _set_depends_registry(self, name, depends, reason=''):
        """回退路径：直接写 HKLM\\SYSTEM\\...\\Services\\<name>\\DependOnService (REG_MULTI_SZ)。"""
        if not _IS_WINDOWS:
            return
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                rf'SYSTEM\CurrentControlSet\Services\{name}', 0, winreg.KEY_SET_VALUE)
            with key:
                winreg.SetValueEx(key, 'DependOnService', 0, winreg.REG_MULTI_SZ, list(depends))
            self._log_message(f'{name} 依赖已写入注册表: {", ".join(depends)}')
        except OSError as e:
            self._log_message(f'{name} 设置依赖失败（nssm: {reason.strip() or "非零退出"}）: {e}', 'WARNING')

    def _clean_ports_if_injected(self):
        """启动前清 5002/3000 端口占用（能力由 app 注入；未注入则跳过）。

        ★ 重启链路必须和「启动生产模式」一样先清端口：:5002 若被**非受管**进程占着
        （历史孤儿后端、GUI 开发栈顶着），新后端起不来 —— 而服务状态照样 RUNNING、
        界面照样报「启动成功」，ERP 实际不可用（假成功）。app 注入的 ``_release_ports``
        自带受管 PID 排除与 managed_unknown fail-safe，不会误杀正在服务的受管进程。
        """
        if not self._release_ports:
            return
        self._msg_queue.put(('log', {'text': '正在清理端口...'}))
        self._release_ports()

    def restart_service_via_stop_start(self, name, nssm=None, stop_timeout=20, start_timeout=25):
        """重启单个服务：显式 `nssm stop` → 等 STOPPED → `nssm start` → 等 RUNNING。

        ★ 为什么不用 `nssm restart`（2026-10-13 实证根因）：NSSM 2.24 的 restart 是

            int ret = control_service(SERVICE_CONTROL_STOP, ...);
            if (ret) nssm_exit(ret);              // ← 停机阶段返回非 0 就**直接退出**
            nssm_exit(control_service(START, ...));   // ← 于是 start 根本没发出

        （nssm.cpp:271-275）。停机阶段一失败，服务就永远停在 STOPPED，而本模块
        原先只报一句「25s 内未进入 RUNNING」，用户必须手点『启动』才能恢复。
        erp-prod 的停机正好容易踩到：被管进程收尾若超出 NSSM 停机预算
        （AppStopMethodConsole/Threads 各 1500ms），stop 这条链就会失败。
        2026-10-12 17:34 / 20:58、2026-10-13 08:12 三次复现；Windows 事件日志里
        只有 STOP 控制、没有 START 控制，是这条路径的指纹。

        显式 stop→start 让 start **无条件**执行（与 ``sc`` 回退分支同一语义），
        stop 的返回码只用来如实告警 —— 否则「重启后起不来」永远无据可查。

        停前先记 PID：停后 PID 未变即服务从未停成（SCM 因依赖方在跑而拒停），本次
        「重启」实际没发生 —— 由 ``wait_service_running`` 据此改报「未生效」而非「启动成功」。

        返回 :class:`ServiceRunResult`（ok/state/pid/effective），与 ``start_one_service``
        一致。发布类调用方必须同时校验 ``ok and effective``。
        """
        nssm = nssm or self.find_nssm()
        # 2026-10-18 OCR 复评：闸门必须在**任何副作用之前**（记录 prev_pid 之前），
        # 否则被拒绝时已经动过本地状态，且日志顺序会误导。
        # 2026-10-18 OCR 评审：单服务重启（如「应用 Worker 数」）此前绕过 AUD-28
        # 闸门；这些服务同样吃工作区源码，必须一视同仁。
        if name in (_SVC_API, _SVC_ARQ, _SVC_WEB):
            ok, msg = git_guard.check_production_branch(self._project_dir)
            if not ok:
                self._msg_queue.put(('log', {'text': f'拒绝执行：{msg}', 'level': 'ERROR'}))
                return ServiceRunResult(False, 'REJECTED', None, False)
            if git_guard.is_warning(msg):
                self._msg_queue.put(('log', {'text': msg, 'level': 'WARNING'}))
            # 只有重启 erp-prod 才刷新启动宽限（arq/web 不影响 prod_runner 快照）
            if name == _SVC_API:
                self._msg_queue.put(('service_action_accepted', {'verb': 'restart'}))
        # 停前 PID 必须保留三态。``svc_pid`` 把「确认未运行」与「探测通道
        # 故障」都折叠成 None：后者若继续停服，wait_service_running 会把
        # 事后可读的同一旧 PID 当成新进程，产生 effective=True 的假重启。
        # 发布安全优先于可用性，身份 unknown 时在**任何副作用之前**拒绝。
        prev_pid, prev_ok = self.svc_pid_ex(name)
        if not prev_ok:
            self._msg_queue.put(('log', {
                'text': f'{name} 停机前 PID 探测失败，无法确认重启是否生效；'
                        '已在执行 stop 前拒绝本次重启，请先修复 SCM 探测通道',
                'level': 'ERROR',
            }))
            return ServiceRunResult(False, 'PID_UNKNOWN', None, False)
        self._msg_queue.put(('log', {'text': f'正在重启生产服务 {name}...'}))
        self._stop_service_sync(name, nssm, stop_timeout)
        return self.start_one_service(name, timeout=start_timeout, prev_pid=prev_pid)

    def _stop_service_sync(self, name, nssm, stop_timeout=20):
        """显式 `nssm stop` 并轮询确认 STOPPED；停机非零返回 / 超时都如实告警。

        停机阶段的失败必须写进日志，否则「重启后起不来」永远无据可查——这正是
        2026-10-13 那次只能靠 Windows 事件日志反推的原因。返回确认到的终态字符串。
        单服务重启与整栈两阶段停机的**停机侧**共用本方法，避免两处告警口径漂移。
        """
        if nssm:
            code, out = self.run_capture([nssm, 'stop', name], timeout=15)
            if code != 0:
                # 非 0 不代表一定没停成（1056「已在运行中」、1052 之类都可能出现），
                # 但必须如实说；吞掉返回码正是「重启后起不来」查不出原因的原因。
                self._msg_queue.put(('log', {
                    'text': f'{name} stop 返回非零 (code={code}): {(out or "").strip()[:160]}；仍继续启动',
                    'level': 'WARNING'}))
            state = self.wait_service(name, 'STOPPED', stop_timeout, abort_on_unknown=True)
        else:
            self.run_capture(['sc', 'stop', name], timeout=30)
            state = self.wait_service(name, 'STOPPED', stop_timeout)
        if 'STOPPED' not in state.upper():
            # 停机没等到终态也必须如实说：否则日志里只剩 start 一侧的消息，停机阶段的
            # 超时完全静默，与「故障无据可查」正相反。仍继续启动 —— start 一侧会给出
            # 「已在运行中」或轮询超时的真实结论，不会假报成功。
            self._msg_queue.put(('log', {
                'text': f'{name} 在 {stop_timeout}s 内未确认 STOPPED（当前: {state}），仍继续启动',
                'level': 'WARNING'}))
        return state

    def service_cmd_sync(self, verb):
        """停止/重启生产服务：逐服务执行 + 轮询确认终态。

        NSSM 的 stop/restart 都是立即返回——不等终态就报「已执行」等于什么都没说
        （2026-09-16 用户实测：stop 打印完 5 秒后服务仍在 RUNNING）。

        ★ 重启走**依赖拓扑两阶段**：停机序取 ``_SVC_REVERSE``（由 ``_SVC_DEPENDS``
        拓扑排序：依赖方先停、被依赖者后停），确认全部 STOPPED 后再原序全起。
        ★ 停机失败必须**中止本轮重启**（2026-10-16 实机事故）：曾有无视停机终态、
          无条件进入启动阶段的实现 —— broker 停不掉却照常启动 → arq 重连 6380 把
          被依赖服务永久钉死 → 下次重启同样失败（自锁循环）。停不掉就不起。
        ★ 2026-10-17 审计 AUD-28：重启/启动前先过 git 分支闸门。NSSM 的
          AppDirectory 是本仓库工作区，重启 = 把当前签出分支跑进生产
          （2026-10-14 已有 75 分钟实害事故）。非 main 直接拒绝。
        """
        if verb in ('restart', 'start'):
            ok, msg = git_guard.check_production_branch(self._project_dir)
            if not ok:
                self._msg_queue.put(('log', {'text': f'拒绝执行：{msg}', 'level': 'ERROR'}))
                # 2026-10-18 OCR 复评：被拒绝时也要收_hosting_refresh，否则界面
                # 停在「动作执行中」的空档；_prod_start_ts 未刷新，hosting 会按
                # 陈旧状态文件真实告警。
                self._msg_queue.put(('hosting_refresh', {}))
                return
            if git_guard.is_warning(msg):
                self._msg_queue.put(('log', {'text': msg, 'level': 'WARNING'}))
            # 闸门已放行：通知 app 刷新启动宽限时间戳（拒绝路径投 hosting_refresh、不投本消息）
            self._msg_queue.put(('service_action_accepted', {'verb': verb}))
        nssm = self.find_nssm()
        if verb == 'restart':
            # 清一次即可：清的是**非受管**端口占用，与迭代顺序无关，不必每个服务重扫。
            self._clean_ports_if_injected()
            # 阶段一：逆拓扑停机——依赖方先停，不挡被依赖的 Redis。
            # 停前记 PID：停后 PID 未变即服务从未停成，由 wait_service_running
            # 据此改报「未生效」，与单服务重启同口径。
            prev_pids: dict[str, int | None] = {}
            failed_stop: list[str] = []
            for name in _SVC_REVERSE:
                self._gate.checkpoint()
                prev_pids[name] = self.svc_pid(name)
                self._msg_queue.put(('log', {'text': f'正在停止生产服务 {name}...'}))
                state = self._stop_service_sync(name, nssm)
                # ★ 消费停机终态：任一服务没停成即中止本轮重启。
                #   SCM 拒停（1051，被运行中的依赖方占着）与被依赖方拒绝收尾都属此类。
                #   '未安装' 例外：服务不存在（sc query 返 1060）时无需停，不能当成
                #   「停不掉」而中止整栈 —— 与 stop_managed_services / ensure_production_stopped
                #   对「未安装」的同口径一致（erp-web 无 nginx、Redis 手工起时都会出现）。
                if 'STOPPED' not in state.upper() and '未安装' not in state:
                    failed_stop.append(name)
                    break
            if failed_stop:
                # 如实汇报：哪个服务没停成、当前什么状态、以及为什么必须停下（防自锁）。
                self._msg_queue.put(('log', {
                    'text': f'{"、".join(failed_stop)} 未能确认 STOPPED（当前: '
                            f'{"、".join(self.svc_state(n) for n in failed_stop)}），'
                            f'已中止本轮重启（未停成的服务不会被启动，已停服务将尝试恢复）。'
                            f'若强行启动会让 erp-arq '
                            f'重连 6380 把被依赖服务永久钉死（自锁循环）。'
                            f'请到 services.msc 检查依赖方状态，或稍后重试。',
                    'level': 'WARNING'}))
                # ★ 恢复可用性：停机是**逆拓扑**（被依赖者最后停），中止发生在中间时，
                #   已停掉的都是排在前面的依赖方（prod/arq/web/cache）—— 不把它们拉回来
                #   ERP 就整体下线，而故障只是「某个被依赖服务停不掉」。故按启动序补拉起
                #   已停服务，把现场还原成「全部在跑、本次重启部分未生效」，由
                #   wait_service_running 的 prev_pid 判定如实标注。
                #   ★ 判据一律取**当下的 svc_state**，不按 failed_stop 名单跳过：失败的那个
                #     服务也可能已到达 STOPPED（wait_service 只返最后一次轮询态），按名跳过
                #     会把它留在 STOPPED 且无日志；仍在跑的会被下面的判据跳过。
                #   ★ '未知' / STOP_PENDING 不可确认时也尝试拉起（start 已在跑的服务只会回
                #     「已在运行中」，无害），绝不静默丢下一个已停服务。
                for name in _SVC_START_ORDER:
                    self._gate.checkpoint()
                    state_now = self.svc_state(name).upper()
                    if 'RUNNING' in state_now:
                        continue
                    # '未安装'（sc 1060）无可恢复，跳过 —— 与上面的停机豁免同口径；否则会误报
                    # 「状态不可确认」+ 对不存在的服务 start（1060）+ 白等 25s 超时。
                    if '未安装' in state_now:
                        continue
                    if 'STOPPED' not in state_now:
                        self._msg_queue.put(('log', {
                            'text': f'中止重启：{name} 状态不可确认（当前: {state_now}），仍尝试拉起',
                            'level': 'WARNING'}))
                    else:
                        self._msg_queue.put(('log', {'text': f'中止重启：恢复已停止的 {name}...'}))
                    self.start_one_service(name, prev_pid=prev_pids.get(name))
                self._msg_queue.put(('hosting_refresh', {}))
                return
            # 阶段二：按启动序全起——被依赖者（Redis）先起，与停机序相反。
            for name in _SVC_START_ORDER:
                self._gate.checkpoint()
                self.start_one_service(name, prev_pid=prev_pids.get(name))
        elif verb == 'stop':
            for name in _SVC_ALL:
                self._gate.checkpoint()
                self._msg_queue.put(('log', {'text': f'正在停止生产服务 {name}...'}))
                if self.wait_service_stopped(name, timeout=45):
                    self._msg_queue.put(('log', {'text': f'{name} 已停止 (state={self.svc_state(name)})'}))
                else:
                    self._msg_queue.put(('log', {'text': f'{name} 在 45s 内未确认 STOPPED（当前: {self.svc_state(name)}），请到服务管理器检查', 'level': 'WARNING'}))
        self._msg_queue.put(('hosting_refresh', {}))

    def wait_service_running(self, name, timeout=25, prev_pid=None) -> ServiceRunResult:
        """轮询直到服务 RUNNING；返回 :class:`ServiceRunResult`，成功/超时都写日志。

        NSSM start/restart 立即返回，服务要经 START_PENDING 才到 RUNNING——
        不轮询就报「已执行」等于什么都没说。超时仍未 RUNNING 如实告警并指路日志文件。

        ``prev_pid`` 由**重启**路径传入停机前的 PID：停后 PID 未变 = 服务从未停成
        （如 SCM 因「有正在运行的依赖方」拒停 erp-redis / erp-redis-broker），本次
        「重启」实际没发生。此时 ``ok=True``（服务确实在跑）但 ``effective=False``，
        消费方**不得**把该结果当重启成功——发布验收只看 ok 会把旧代码当新版本放行
        （2026-10-25 上线前检查 B1 正是拿掉了这个假成功口子）。

        PID 读取用 ``svc_pid_ex`` 区分「服务未运行（pid=None, ok=True）」与「探测
        通道不可用（ok=False）」：通道故障时身份未经证实，effective=False 并告警——
        否则「SCM 拒停 + 探测通道恰好故障」的组合会让同 PID 旧进程再次被当新版本
        （评审 2026-10-25 finding 2，宁可误报不可漏报）。``prev_pid=None`` 且通道
        正常时，停机前服务确认为未运行，起来的必是新进程，effective=True。
        """
        state = self.wait_service(name, 'RUNNING', timeout)
        if 'RUNNING' in state.upper():
            pid, pid_ok = self.svc_pid_ex(name)
            if not pid_ok or pid is None:
                self._msg_queue.put(('log', {
                    'text': f'{name} 已 RUNNING 但读取新 PID 失败'
                            f'（{"探测通道不可用" if not pid_ok else "SCM 未报告 PID"}），'
                            '无法验证本次重启是否生效',
                    'level': 'WARNING'}))
                return ServiceRunResult(True, state, None, False)
            if prev_pid is not None and pid == prev_pid:
                self._msg_queue.put(('log', {
                    'text': f'{name} 仍是原进程 (PID: {pid})，本次重启未生效（停机未停成）',
                    'level': 'WARNING'}))
                return ServiceRunResult(True, state, pid, False)
            self._msg_queue.put(('log', {'text': f'{name} 启动成功 (state={state}, PID: {pid})'}))
            return ServiceRunResult(True, state, pid, True)
        self._msg_queue.put(('log', {'text': f'{name} 在 {timeout}s 内未进入 RUNNING（当前: {state}），请查看 logs\\{name}.log', 'level': 'WARNING'}))
        return ServiceRunResult(False, state, None, False)

    def start_one_service(self, name, timeout=25, prev_pid=None) -> ServiceRunResult:
        """发出启动命令并轮询确认 RUNNING；返回 :class:`ServiceRunResult`。

        ``prev_pid`` 透传给 ``wait_service_running``，供重启路径判定本次是否真的重启。
        """
        nssm = self.find_nssm()
        self._msg_queue.put(('log', {'text': f'正在启动生产服务 {name}...'}))
        if nssm:
            code, out = self.run_capture([nssm, 'start', name], timeout=20)
        else:
            code, out = self.run_capture(['sc', 'start', name], timeout=20)
        if code != 0:
            out_l = (out or '').lower()
            # 中文系统 nssm 不带数字码、文案本地化，故同时匹配中文（对照 svc_installed）。
            if '1056' in out or 'already' in out_l or '已在运行' in out:
                self._msg_queue.put(('log', {'text': f'{name} 已在运行中，跳过 start'}))
            elif not ('1053' in out or '没有及时响应' in out):
                # 1053/超时类错误不代表失败（服务可能仍在启动中），以轮询结果为准
                self._msg_queue.put(('log', {'text': f'{name} start 返回非零 (code={code}): {(out or "").strip()[:160]}', 'level': 'WARNING'}))
        return self.wait_service_running(name, timeout=timeout, prev_pid=prev_pid)

    def restart_one_service(self, name, timeout=25):
        """只重启一个服务。

        与 ``service_cmd_sync('restart')`` 的区别：后者遍历 ``_SVC_ALL``（含 erp-arq、
        前端与两个 Redis）。改 worker 数只需重启 erp-prod —— 不该顺带掐掉 ARQ 的在途
        任务与 Redis。重启语义统一走 ``restart_service_via_stop_start``（不再用
        ``nssm restart``：停机阶段失败它会跳过 start，理由见该方法 docstring）。
        """
        self._clean_ports_if_injected()
        return self.restart_service_via_stop_start(name, start_timeout=timeout)

    def uninstall_services_flow(self, nssm):
        for name in (_SVC_API, _SVC_ARQ, _SVC_WEB):
            self._gate.checkpoint()
            self.run_capture([nssm, 'stop', name], timeout=30)
            self._gate.checkpoint()
            code, out = self.run_capture([nssm, 'remove', name, 'confirm'], timeout=30)
            if code == 0:
                self._msg_queue.put(('log', {'text': f'{name} 已卸载'}))
            else:
                self._msg_queue.put(('log', {'text': f'{name} 卸载失败: {out}', 'level': 'WARNING'}))
        self._msg_queue.put(('hosting_refresh', {}))
