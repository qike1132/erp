"""生产托管(hosting)视图层——状态采集 + 徽章渲染。

T7 从 ``app.py`` 抽出的纯 UI 胶水:后台线程采集生产服务状态(``_collect_hosting_data``),
主线程按采集结果刷新一组徽章(``_apply_hosting_data``)。二者只经 ``self`` 读写宿主
``ServerManagerApp`` 的状态(``hosting_*_badge`` / ``_msg_queue`` / ``_after_ids`` …),
故以 **mixin** 形式共享 ``self``(``class ServerManagerApp(HostingViewMixin)``),方法体
零改动 —— 仅 ``_collect_hosting_data`` 里 ``_PROJECT_DIR``(app 模块全局)一处改写为
``self._PROJECT_DIR``(app 类体上暴露的同值属性),见 app.py 类属性注释。

调度侧 ``_refresh_hosting_status`` / ``_manual_refresh_hosting`` **仍留在 app.py**:
它们是被 ``__init__`` / ``_poll_queue``(app 内其它代码) 直接调用的**调用方**,按
"被这两者使用的助手才搬" 的切法留在原处。

本模块属 UI 层,允许 import tkinter(与 ops 模块的"不得 import tkinter"约束相反);
当前实现无需。
"""
from __future__ import annotations

import contextlib
import json
import time
from datetime import datetime

from server_manager.constants import (
    _API_PORT,
    _HTTP_DIRECT,
    _REDIS_BROKER_PORT,
    _SVC_API,
    _SVC_ARQ,
    _SVC_WEB,
)


class HostingViewMixin:
    """生产托管状态采集 + 徽章渲染(详见模块 docstring)。"""

    def _warn_once(self, key, text):
        """同类警告只记一次，避免每 5s 刷屏把真实信号埋掉（状态好转时由调用方复位）。

        key 必须是稳定标识 —— 把「已 N 秒未更新」这类逐轮递增的量放进 key，
        去重就会失效，变成每 5s 刷一条。
        """
        if key != self._hosting_last_warn:
            self._hosting_last_warn = key
            self.log_message(f'[生产模式] {text}', 'WARNING')

    def _collect_hosting_data(self):
        """纯数据收集（后台线程执行）——不触碰任何 UI 组件"""
        data = {
            'api_state': self._svc_state(_SVC_API),
            'arq_state': self._svc_state(_SVC_ARQ),
        }
        data['api_running'] = 'RUNNING' in data['api_state'].upper() if data['api_state'] else False
        data['api_unknown'] = data['api_state'] == '未知'
        data['redis_ok'] = self._is_redis_running()
        # broker 独立探测：它不在 prod_runner 的就绪判据里（ARQ 是独立服务），
        # 必须单独采集，否则「ARQ 已死」和「一切正常」在界面上长得一模一样。
        data['broker_ok'] = self._is_broker_running()
        # 注：曾采集 nssm / arq_unknown / redis_svc_state / broker_svc_state / status_file
        # 五个键但**无任何读取方**(2026-09-28 评审实测)，其中后两项每 5 秒白跑一次
        # `sc query`，已删。
        status_file = self._PROJECT_DIR / 'logs' / 'prod_runner.json'
        data['status'], data['read_err'], data['mtime'], data['stale'], data['mtime_str'] = {}, None, 0, False, '—'
        if not data['api_running']:
            return data
        # 服务运行中：读取状态文件并校验新鲜度
        try:
            if status_file.is_file():
                data['status'] = json.loads(status_file.read_text(encoding='utf-8'))
            else:
                data['read_err'] = f'文件不存在: {status_file}'
        except Exception as e:
            data['read_err'] = f'读取失败: {type(e).__name__}: {e}'
        mtime = status_file.stat().st_mtime if status_file.is_file() else 0
        data['mtime'] = mtime
        data['stale'] = bool(status_file.is_file()) and (time.time() - mtime) > self.HOSTING_STALE_SEC
        data['mtime_str'] = datetime.fromtimestamp(mtime).strftime('%H:%M:%S') if mtime else '—'
        # ARQ 由独立 NSSM 服务托管时（--no-arq），从 erp-arq 服务查询真实 PID（IO 归入收集阶段）
        if data['status'].get('services', {}).get('arq', {}).get('status') == 'external':
            data['arq_svc_pid'] = self._svc_pid(_SVC_ARQ)
        else:
            data['arq_svc_pid'] = None
        # 备份可观测性：/api/health 的 backup 块（产物新鲜度 + ARQ 在线）。
        # 本机、10s 缓存、开销小；失败即空 dict，徽章显示「未上报」而非误报正常。
        data['backup'] = {}
        with contextlib.suppress(Exception):
            with _HTTP_DIRECT.open(f'http://127.0.0.1:{_API_PORT}/api/health', timeout=3) as resp:
                payload = json.loads(resp.read().decode('utf-8'))
            blk = payload.get('backup')
            if isinstance(blk, dict):
                data['backup'] = blk
        return data

    def _apply_hosting_data(self, data):
        """主线程应用收集到的生产模式状态（仅 UI 更新，无阻塞 IO）

        155 行的单函数已超函数长度门禁（≤80 行），按「放弃理由」拆为 1 个调度器 +
        4 个助手（collect_error / services_stopped / status_untrusted）+ 2 个渲染助手。
        纯搬运：判定顺序、三态/陈旧/启动窗口语义与全部文案逐字未变；``finally`` 里的
        计时器重挂留在调度器上，故各助手的 ``return`` 语义与拆分前一致。
        """
        try:
            self._prod_running = data.get('api_running', False)
            # ★ 三态语义贯通：sc query 失败(未知)必须独立记录，展示层据此显示「状态未知」，
            # 绝不能落成「已停止」——否则查不出来会被误当成生产已停、诱导误判。
            self._prod_unknown = data.get('api_unknown', False)
            if data.get('collect_error'):
                self._apply_collect_error(data)
                return
            # 服务未运行：以 sc query 为权威，不读状态文件，避免残留旧数据
            if not data['api_running']:
                self._apply_services_stopped(data)
                return
            if self._apply_status_untrusted(data):
                return
            self._hosting_last_warn = ''
            self._apply_running_status(data)
        finally:
            self._hosting_collecting = False
            self._update_mode_badge()
            # 收集期间有刷新请求 → 立即补一轮；否则按 5s 周期继续
            delay = 50 if self._hosting_refresh_requested else 5000
            self._hosting_refresh_requested = False
            self._after_ids['hosting'] = self.root.after(delay, self._refresh_hosting_status)

    def _set_badge(self, badge, state, text):
        """原 ``_apply_hosting_data`` 内的局部闭包 ``_detail`` 的方法化。

        拆分后各调用点都要带 ``self.``（作用域由函数内变为类内）。
        """
        badge.set_state(state, text)

    def _apply_svc_detail(self, badge, label, svc, running, starting=()):
        """按 prod_runner 上报的 status 如实映射（原局部闭包 ``_svc_detail``）。

        关键：backend 的 running ≠ ready（进程已起、健康门未过）是「启动中」，
        不是「已停止」—— 把它显示成红色「已停止」正是用户点「启动服务」后
        看到的那条误导信息。
        """
        s = (svc or {}).get('status')
        if s in running:
            self._set_badge(badge, 'running', f'{label} 运行中')
        elif s in starting:
            self._set_badge(badge, 'deploying', f'{label} 启动中')
        elif s in ('failed', 'crashed'):
            self._set_badge(badge, 'error', f'{label} 异常({s})')
        elif s == 'stopped':
            self._set_badge(badge, 'stopped', f'{label} 已停止')
        else:
            self._set_badge(badge, 'stopped', f'{label} 未上报')

    def _apply_collect_error(self, data):
        """采集失败分支：必须先置灰备份徽章，再由调度器提前 return。"""
        # 必须先重置备份徽章:它不在状态文件里,靠每轮采集刷新——
        # 采集失败提前 return 会让旧值滞留,把上一次的绿色显示成现状。
        self.hosting_backup_badge.set_state('stopped', '备份 状态未知')
        self._warn_once('collect-error',
                        f"状态收集失败（{data.get('error', '未知原因')}），界面本轮不更新")

    def _apply_services_stopped(self, data):
        """服务未运行分支：以 sc query 为权威，不读状态文件。出口唯一。"""
        # ★ 查询失败(未知) ≠ 已停止：sc query 报「未知」时服务可能仍在运行，
        # 不得显示「服务停止」，须显式标「状态未知」并保留原状。
        api_unknown = data.get('api_unknown', False)
        if api_unknown:
            self.hosting_svc_badge.set_state('unknown', '状态未知')
            self._set_badge(self.hosting_backend_badge, 'stopped', '后端 状态未知')
            self._set_badge(self.hosting_arq_badge, 'stopped', 'ARQ 状态未知')
            self._set_badge(self.hosting_frontend_badge, 'stopped', '前端 状态未知')
            self._set_badge(self.hosting_ready_badge, 'stopped', '就绪 状态未知')
            self._set_badge(self.hosting_backup_badge, 'stopped', '备份 状态未知')
        else:
            self.hosting_svc_badge.set_state('stopped', '服务停止')
            self._set_badge(self.hosting_backend_badge, 'stopped', '后端 已停止')
            self._set_badge(self.hosting_arq_badge, 'stopped', 'ARQ 未运行')
            self._set_badge(self.hosting_frontend_badge, 'stopped', '前端 已停止')
            self._set_badge(self.hosting_ready_badge, 'stopped', '就绪 —')
            # 服务全停时 ARQ 也停了 ⇒ 备份不会执行。此处必须一同置灰,
            # 否则徽章保留上一次的绿色「正常(Nh)」= 假健康(2026-09-28 用户实测发现)。
            self._set_badge(self.hosting_backup_badge, 'stopped', '备份 已停止')
        redis_ok = data['redis_ok']
        broker_ok = data.get('broker_ok', False)
        # 缓存与 broker 分开显示：broker 决定 ARQ（cron/备份/报表）能否工作，
        # 合并成一个「Redis 运行中」会把「缓存正常但队列已死」当健康上报。
        if redis_ok and broker_ok:
            self._set_badge(self.hosting_redis_badge, 'running', 'Redis 运行中')
        elif redis_ok:
            self._set_badge(self.hosting_redis_badge, 'error',
                            f'broker({_REDIS_BROKER_PORT}) 未运行')
        else:
            self._set_badge(self.hosting_redis_badge, 'stopped', 'Redis 已停止')

    def _apply_status_untrusted(self, data) -> bool:
        """状态文件不足信（陈旧/缺失/读失败）时渲染「未知」；True=已处理，调用方应 return。

        绝不把旧快照当现状展示：prod_runner 停写后，旧快照会永久冻在界面上，
        让人误判「已停止」而服务其实仍在 RUNNING —— 这正是「没有实时更新」的来路。
        """
        read_err = data['read_err']
        stale = data.get('stale', False)
        mtime_str = data.get('mtime_str', '—')

        self.hosting_svc_badge.set_state('running', '服务运行')
        if not (stale or read_err):
            return False
        # 但要先摘掉「启动窗口」这一段：刚发出启动/重启、且快照还早于那次启动时，
        # 陈旧是必然的（那是上一轮的快照），此时说「prod_runner 可能已退出、
        # 请重启服务」是假警报，照着做只会白重启一次服务。
        start_ts = getattr(self, '_prod_start_ts', 0.0)
        start_age = time.time() - start_ts if start_ts else None
        starting_up = (start_age is not None
                       and start_age < self.HOSTING_START_GRACE_SEC
                       and data['mtime'] < start_ts)
        if starting_up:
            self._warn_once(f'starting:{data.get("mtime")}',
                            f'生产服务 {int(start_age)}s 前刚启动，prod_runner 尚未写入首份状态'
                            f'（状态文件最后更新 {mtime_str}）；界面暂按「启动中」显示')
            for badge, label in ((self.hosting_backend_badge, '后端'),
                                 (self.hosting_frontend_badge, '前端'),
                                 (self.hosting_arq_badge, 'ARQ')):
                self._set_badge(badge, 'deploying', f'{label} 启动中')
            self._set_badge(self.hosting_ready_badge, 'deploying', '就绪 启动中')
            # 启动窗口内备份状态无从得知(尚未采到新快照),置「状态未知」,
            # 否则徽章会滞留上一轮的绿/红(同 f31457eb 修的假信号类)。
            self._set_badge(self.hosting_backup_badge, 'stopped', '备份 状态未知')
            return True
        reason = (f"已 {int(time.time() - data['mtime'])}s 未更新，最后 {mtime_str}"
                  if stale else (read_err or '状态文件不可用'))
        self._warn_once(f'stale:{data.get("mtime")}',
                        f'状态文件不可信（{reason}），界面不再跟随服务状态；'
                        f'prod_runner 可能已退出，可在服务管理里重启 {_SVC_API}')
        for badge, label in ((self.hosting_backend_badge, '后端'),
                             (self.hosting_frontend_badge, '前端'),
                             (self.hosting_arq_badge, 'ARQ')):
            self._set_badge(badge, 'stopped', f'{label} 状态未知')
        self._set_badge(self.hosting_ready_badge, 'stopped', f'就绪 无数据({mtime_str})')
        # 状态文件不可信 ⇒ 备份真相也无从得知,不得滞留上一轮的绿/红。
        self._set_badge(self.hosting_backup_badge, 'stopped', '备份 状态未知')
        return True

    def _apply_running_status(self, data):
        """状态文件可信：按 prod_runner 快照渲染 backend/arq/frontend/backup/redis/ready。"""
        status = data['status']
        svcs = status.get('services', {})
        self._apply_svc_detail(self.hosting_backend_badge, '后端', svcs.get('backend'),
                               running=('ready',), starting=('running',))
        arq = svcs.get('arq') or {}
        if arq.get('status') == 'external':
            # ARQ 由独立 NSSM 服务托管：以 sc queryex 的真实 PID 为准。
            # ★ 但「服务在跑」不等于「ARQ 在干活」：broker 6380 不可达时 erp-arq
            # 进程仍是 RUNNING（Python 正在重试连接），徽章若只认 PID 就会
            # 把「死循环重启中」显示成「运行中」。broker 不健康时如实报异常。
            arq_pid = data.get('arq_svc_pid')
            if not arq_pid:
                self._set_badge(self.hosting_arq_badge, 'stopped', 'ARQ 未运行')
            elif not data.get('broker_ok', False):
                self._set_badge(self.hosting_arq_badge, 'error', 'ARQ 异常(broker 不可达)')
            else:
                self._set_badge(self.hosting_arq_badge, 'running', 'ARQ 运行中')
        else:
            self._apply_svc_detail(self.hosting_arq_badge, 'ARQ', arq,
                                   running=('running', 'ready'))
        # 前端:erp-web 为独立 NSSM 服务,status=external 时以服务状态为准,
        # prod_runner 的 frontend_ok 探针作交叉验证(探针区分 SPA fallback)。
        fe = svcs.get('frontend') or {}
        if fe.get('status') == 'external':
            web_state = self._svc_state(_SVC_WEB)
            if 'RUNNING' in web_state:
                if status.get('frontend_ok'):
                    self._set_badge(self.hosting_frontend_badge, 'running', '前端 运行中')
                else:
                    self._set_badge(self.hosting_frontend_badge, 'deploying', '前端 服务在跑但探针未过')
            elif 'STOPPED' in web_state:
                self._set_badge(self.hosting_frontend_badge, 'stopped', '前端 已停止')
            else:
                self._set_badge(self.hosting_frontend_badge, 'stopped', f'前端 {web_state}')
        else:
            self._apply_svc_detail(self.hosting_frontend_badge, '前端', svcs.get('frontend'),
                                   running=('running', 'ready'))
        # 备份：采集阶段已从 /api/health 取到 backup 块（见 _collect_hosting_data）
        bk = data.get('backup') or {}
        if not bk:
            self._set_badge(self.hosting_backup_badge, 'stopped', '备份 未上报')
        elif not bk.get('arq_ok', False):
            self._set_badge(self.hosting_backup_badge, 'error', '备份 ARQ 掉线')
        elif bk.get('ok'):
            age = bk.get('age_hours')
            self._set_badge(self.hosting_backup_badge, 'running',
                            f'备份 正常({age}h)' if age is not None else '备份 正常')
        else:
            age = bk.get('age_hours')
            self._set_badge(self.hosting_backup_badge, 'error',
                            f'备份 陈旧({age}h)' if age is not None else '备份 无产物')
        redis_ok = data['redis_ok']
        broker_ok = data.get('broker_ok', False)
        if redis_ok and broker_ok:
            self._set_badge(self.hosting_redis_badge, 'running', 'Redis 运行中')
        elif redis_ok:
            self._set_badge(self.hosting_redis_badge, 'error',
                            f'broker({_REDIS_BROKER_PORT}) 未运行')
        else:
            self._set_badge(self.hosting_redis_badge, 'error', 'Redis 已停止')
        if status.get('ready'):
            # 「就绪」只在 ARQ 也健康时才算真的就绪，否则给一个可区分的文案
            if broker_ok:
                self._set_badge(self.hosting_ready_badge, 'running', '就绪 是')
            else:
                self._set_badge(self.hosting_ready_badge, 'error', '就绪 降级(broker 不可达)')
        elif ((svcs.get('backend') or {}).get('status') in ('failed', 'crashed')
              or (svcs.get('frontend') or {}).get('status') in ('failed', 'crashed')):
            self._set_badge(self.hosting_ready_badge, 'error', '就绪 启动失败')
        else:
            self._set_badge(self.hosting_ready_badge, 'deploying', '就绪 启动中')
