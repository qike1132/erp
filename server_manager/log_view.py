"""日志面板视图层——界面渲染 + 日志运维(实时回灌 / 文件定时清理)。

从 ``app.py`` 抽出(T8),承接 ``hosting_view.HostingViewMixin`` 的同一套切法:
纯 UI 胶水以 **mixin** 形式共享宿主 ``ServerManagerApp`` 的 ``self``(
``log_text`` / ``_msg_queue`` / ``_after_ids`` / ``_PALETTE`` …)，方法体零改动，
仅模块全局 ``_PROJECT_DIR`` 一处改写为 ``self._PROJECT_DIR``(app 类体上暴露的同值
属性，与 hosting_view 用的同一个 Path 对象)。

★ 为什么必须抽这一层:``tests/test_gates_cover_repo_root.py`` 永久锁住
  ``server_manager/app.py ≤ 1600 行``(规模门禁阈值，见 pyproject 的 max_file_size)。
  本次「生产日志不实时 + 日志只增不减」两个改动若直接堆在 app.py 里会把
  app.py 顶到 1676 行，门禁判红 —— 该锁自己的提示就是「请再抽一层出去」。

★ 留在 app.py 的为什么留:``__init__`` 里的调度起手(``_schedule_log_cleanup`` /
  ``_schedule_log_flush`` / ``_schedule_log_file_cleanup``)、退出前收尾
  (``_do_quit``)、以及生产启动流程里的「接入实时回灌」一行 —— 它们是被
  app 的**调用方**代码直接调用的时序点，按「被调用方使用才搬」的切法留在原处。

本模块属 UI 层(允许 import tkinter)；日志的**机制**在 ``server_manager/log_ops.py``
(不碰 Tk，可单测)，本层只负责「把机制的结果贴到面板上、把面板的意图翻译成调用」。
"""
from __future__ import annotations

import threading
import tkinter as tk
from datetime import datetime
from tkinter import ttk

from server_manager.log_ops import (
    ProdLogTailer,
    inspect_log_health,
    load_log_policy,
    policy_from_fields,
    prune_log_files,
    rotate_oversized_logs,
    save_log_policy,
)


class LogViewMixin:
    """运行日志面板 + 生产日志实时回灌 + 日志文件保留清理(详见模块 docstring)。"""

    # 界面缓冲上限(与磁盘文件的保留策略无关)：超过 MAX 就裁到 KEEP，
    # 否则 Tk Text 越写越慢，整个界面会跟着卡。
    MAX_LOG_LINES, LOG_KEEP_LINES, LOG_CLEANUP_MS, LOG_FLUSH_MS = 500, 300, 120000, 500
    # 日志**文件**维护（轮转兜底 + 过期清理）：保留期/体积上限/轮转阈值由共享策略文件
    # config/log_policy.json 决定（默认 50MB / 14 天 / 512MB，可在面板「设置」里改），
    # 这里只决定「多久跑一轮」与「启动后多久首跑」(避开启动那几秒的 IO 高峰)。
    # 取 6 小时而非一天：轮转兜底的意义就是「外部任务靠不住时自己止血」，无人轮转的
    # nginx access 日志按小时涨，一天才发现就已经很大了（巡检负责发告警，这里负责止血）。
    LOG_FILE_CLEANUP_FIRST_MS, LOG_FILE_CLEANUP_MS = 20000, 6 * 60 * 60 * 1000
    # 生产日志实时回灌轮询周期(秒)：1s 与开发模式 stdout 的观感一致。
    PROD_LOG_POLL_S = 1.0
    # 日志健康巡检：启动 30s 后首轮(避开启动 IO 高峰)，此后每 5 分钟一轮。
    # 5 分钟是「增长率算得准」与「发现得早」的折中：崩溃循环半小时就能被抓到。
    LOG_HEALTH_FIRST_MS, LOG_HEALTH_MS = 30000, 5 * 60 * 1000
    LOG_HEALTH_PENDING_TEXT = '日志巡检：等待首轮采样（启动约 30s 后给出增长源）'

    def _init_log_view(self):
        """初始化日志缓冲(由 app.__init__ 早期调用，早于 _build_ui)。"""
        self._log_buffer, self._flush_pending = [], False
        self._log_health_warned: set[str] = set()
        self._log_health_baselined = False

    @property
    def prod_logs(self) -> ProdLogTailer:
        """生产日志实时回灌器(惰性创建)。

        惰性而非在 ``__init__`` 里建:本 mixin 的方法(含 ``_sync_prod_log_tailer``)
        也会被只构造了部分状态的测试直接调用，惰性创建让这些调用不必先跑完整
        ``__init__`` 也能用。
        """
        tailer = getattr(self, '_prod_logs', None)
        if tailer is None:
            tailer = self._prod_logs = ProdLogTailer(
                self._msg_queue, self._PROJECT_DIR, interval=self.PROD_LOG_POLL_S)
        return tailer

    def _sync_prod_log_tailer(self, running):
        """生产服务运行状态 → 实时日志管线开关（幂等，可每轮托管刷新调用）。

        ★ 两个方向都是真缺陷：服务在跑却没有管线 = 「生产模式打开后日志不实时」
          （用户实测）；服务停了还在回灌 = 旧内容持续刷屏 + 白占一个线程。
          故不放在启动流程里一次性挂上，而是跟随权威状态（sc query）自动跟随。
        """
        if running:
            self.prod_logs.ensure_started()
        else:
            self.prod_logs.stop()

    # ── 共享日志策略（config/log_policy.json） ──────────────────────────────
    def _log_policy_path(self):
        """策略文件路径：必须显式给出。

        ``utils.log_rotation.default_policy_path()`` 基于 ``__file__`` 推算，而打包后
        ``__file__`` 指向 PyInstaller 解包临时目录 —— 会算出不存在的路径并静默回落
        默认值（表现：面板改了设置却像没生效）。桌面壳一律用项目目录拼。
        """
        return self._PROJECT_DIR / 'config' / 'log_policy.json'

    def _log_policy(self):
        """当前生效策略（缺失/损坏时回落默认 50MB / 14 天 / 512MB）。"""
        return load_log_policy(self._log_policy_path())

    def _log_policy_text(self) -> str:
        return f'自动轮转+清理：{self._log_policy().summary()}'

    def _refresh_log_policy_label(self):
        """设置保存后刷新面板上的策略提示（控件可能尚未构建，故容错）。"""
        label = getattr(self, 'log_policy_label', None)
        if label is not None:
            label.configure(text=self._log_policy_text())

    def open_log_policy_dialog(self):
        """打开「日志轮转与保留策略」对话框（三格：轮转阈值 / 保留天数 / 体积上限）。

        策略是三方共用的一份文件（桌面壳 / prod_runner / ARQ），所以这里改了就立刻
        对后端生效，无需重启任何服务；越界**报错不静默夹取**（界面不能替用户改写意图，
        而文件侧的夹取是给手改坏值兜底的）。
        """
        policy = self._log_policy()
        dlg = tk.Toplevel(self.root)
        dlg.title('日志轮转与保留策略')
        dlg.configure(bg=self._PALETTE['bg_card'])
        dlg.transient(self.root)
        dlg.resizable(False, False)
        tk.Label(dlg, text=self._log_policy_text(), font=('Microsoft YaHei UI', 9),
                 fg=self._PALETTE['text_primary'], bg=self._PALETTE['bg_card']).grid(
            row=0, column=0, columnspan=2, padx=16, pady=(12, 4), sticky='w')
        entries = []
        for i, (label, value) in enumerate([('轮转阈值 (MB)', policy.rotate_mb),
                                            ('保留天数', policy.keep_days),
                                            ('体积上限 (MB)', policy.max_total_mb)]):
            tk.Label(dlg, text=label, font=('Microsoft YaHei UI', 9),
                     fg=self._PALETTE['text_secondary'], bg=self._PALETTE['bg_card']).grid(
                row=i + 1, column=0, padx=(16, 8), pady=4, sticky='e')
            entry = tk.Entry(dlg, width=12, font=('Microsoft YaHei UI', 9))
            entry.insert(0, str(value))
            entry.grid(row=i + 1, column=1, padx=(0, 16), pady=4, sticky='w')
            entries.append(entry)
        error = tk.Label(dlg, text='', font=('Microsoft YaHei UI', 8),
                         fg=self._PALETTE['log_error'], bg=self._PALETTE['bg_card'])
        error.grid(row=4, column=0, columnspan=2, padx=16, sticky='w')

        def on_save():
            new_policy, message = policy_from_fields(
                entries[0].get(), entries[1].get(), entries[2].get())
            if new_policy is None:
                error.configure(text=message or '输入无效')
                return
            if not save_log_policy(new_policy, self._log_policy_path()):
                error.configure(text='保存失败：无法写入 config/log_policy.json（权限/占用）')
                return
            self._refresh_log_policy_label()
            self.log_message(f'日志策略已更新：{new_policy.summary()}')
            dlg.destroy()

        btns = tk.Frame(dlg, bg=self._PALETTE['bg_card'])
        btns.grid(row=5, column=0, columnspan=2, padx=16, pady=(4, 14), sticky='e')
        self._pill(btns, '取消', dlg.destroy)
        self._pill(btns, '保存', on_save)

    # ── 面板 ────────────────────────────────────────────────────────────────────────
    def _build_log_section(self, parent):
        log_card = tk.Frame(parent, bg=self._PALETTE['bg_card'], highlightbackground=self._PALETTE['border_card'], highlightthickness=1)
        log_card.grid(row=1, column=0, columnspan=2, sticky='nsew', pady=(10, 0))
        log_card.columnconfigure(0, weight=1)
        log_card.rowconfigure(2, weight=1)
        log_hdr = tk.Frame(log_card, bg=self._PALETTE['bg_card'])
        log_hdr.grid(row=0, column=0, sticky='ew', padx=20, pady=(12, 0))
        tk.Label(log_hdr, text='运行日志', font=('Microsoft YaHei UI', 11, 'bold'), fg=self._PALETTE['text_primary'], bg=self._PALETTE['bg_card']).pack(side=tk.LEFT)
        tk.Label(log_hdr, text='实时输出', font=('Microsoft YaHei UI', 8), fg=self._PALETTE['text_dim'], bg=self._PALETTE['bg_card']).pack(side=tk.LEFT, padx=(8, 0))
        # 把「磁盘上的日志也会被定时清理」写在界面上：否则用户看到「清空」只清了显示，
        # 会以为文件没人管 —— 这正是「不然日志越来越多」这条诉求的来路。
        self.log_policy_label = tk.Label(log_hdr, text=self._log_policy_text(), font=('Microsoft YaHei UI', 8), fg=self._PALETTE['text_dim'], bg=self._PALETTE['bg_card'])
        self.log_policy_label.pack(side=tk.LEFT, padx=(8, 0))
        log_btns = tk.Frame(log_hdr, bg=self._PALETTE['bg_card'])
        log_btns.pack(side=tk.RIGHT)
        for txt, cmd in [('导出', self.export_log), ('清空', self.clear_log), ('清理旧日志', self.cleanup_log_files), ('设置', self.open_log_policy_dialog)]:
            self._pill(log_btns, txt, cmd)
        # 巡检行：一行讲清「总共多少 / 谁在长 / 长得多快」，右侧可手动补一轮。
        # 放在标题行下一行而非塞进标题行 —— 增长源名字长，挤在一行会互相顶掉。
        health = tk.Frame(log_card, bg=self._PALETTE['bg_card'])
        health.grid(row=1, column=0, sticky='ew', padx=20, pady=(6, 0))
        self.log_health_label = tk.Label(health, text=self.LOG_HEALTH_PENDING_TEXT, font=('Microsoft YaHei UI', 8), fg=self._PALETTE['text_dim'], bg=self._PALETTE['bg_card'], anchor='w', justify=tk.LEFT)
        self.log_health_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._pill(health, '巡检', self.run_log_health_check)
        log_body = tk.Frame(log_card, bg=self._PALETTE['bg_input'], highlightbackground=self._PALETTE['border'], highlightthickness=1)
        log_body.grid(row=2, column=0, sticky='nsew', padx=14, pady=(8, 14))
        log_body.columnconfigure(0, weight=1)
        log_body.rowconfigure(0, weight=1)
        log_font = self._pick_log_font()
        self.log_text = tk.Text(log_body, bg=self._PALETTE['bg_log'], fg=self._PALETTE['log_fg'], insertbackground=self._PALETTE['log_fg'], selectbackground=self._PALETTE['bg_input'], font=log_font, wrap=tk.WORD, state=tk.DISABLED, relief=tk.FLAT, padx=14, pady=10, cursor='arrow')
        self.log_text.grid(row=0, column=0, sticky='nsew')
        self.log_text.tag_configure('INFO', foreground=self._PALETTE['log_info'])
        self.log_text.tag_configure('ERROR', foreground=self._PALETTE['log_error'])
        self.log_text.tag_configure('WARNING', foreground=self._PALETTE['log_warn'])
        sb = ttk.Scrollbar(log_body, command=self.log_text.yview)
        sb.grid(row=0, column=1, sticky='ns')
        self.log_text.config(yscrollcommand=sb.set)

    def _pill(self, parent, text, cmd):
        """胶囊小按钮（导出 / 清空 / 清理旧日志 / 巡检 共用一套悬停样式）。

        原先每个按钮各写一遍 pack + 4 条 bind（连悬停高亮都要分两次 bind，
        一次管底框一次管字），加到第三个按钮就已经要抄三份 —— 故收敛成一个工厂。
        """
        pill = tk.Frame(parent, bg=self._PALETTE['bg_card'], cursor='hand2', highlightbackground=self._PALETTE['border'], highlightthickness=1)
        pill.pack(side=tk.RIGHT, padx=(4, 0))
        label = tk.Label(pill, text=text, font=('Microsoft YaHei UI', 8), fg=self._PALETTE['text_secondary'], bg=self._PALETTE['bg_card'], padx=12, pady=3, cursor='hand2')
        label.pack()
        for w in (pill, label):
            w.bind('<Button-1>', lambda e, c=cmd: c())
            w.bind('<Enter>', lambda e, p=pill, l=label: (p.config(bg=self._PALETTE['bg_input']), l.config(bg=self._PALETTE['bg_input'])))
            w.bind('<Leave>', lambda e, p=pill, l=label: (p.config(bg=self._PALETTE['bg_card']), l.config(bg=self._PALETTE['bg_card'])))
        return pill

    # ── 日志健康巡检（增长源识别 + 异常增长告警） ────────────────────────────
    def _schedule_log_health(self, delay_ms=None):
        """定时巡检（首次沿用 LOG_HEALTH_FIRST_MS，之后每 LOG_HEALTH_MS 一轮）。"""
        self._after_ids['log_health'] = self.root.after(
            self.LOG_HEALTH_FIRST_MS if delay_ms is None else delay_ms, self._log_health_tick)

    def _log_health_tick(self):
        """定时器回调：巡检一轮并续上下一轮（无论成败都不中断调度链）。"""
        self.run_log_health_check()
        self._schedule_log_health(self.LOG_HEALTH_MS)

    def run_log_health_check(self):
        """巡检一轮日志目录（后台线程；结果经队列回主线程渲染，绝不在子线程碰 Tk）。

        巡检要 stat 目录里每个文件并读写一份状态快照 —— 放主线程会让界面在
        日志文件多时卡一下，而这是每 5 分钟就要跑一次的固定动作。
        """
        def worker():
            try:
                report = inspect_log_health(
                    self._PROJECT_DIR / 'logs',
                    max_total_bytes=self._log_policy().max_total_bytes)
                self._msg_queue.put(('log_health', {'report': report}))
            except Exception as e:  # defensive: 巡检失败只报告，不影响面板与其它功能
                self._msg_queue.put(('log', {'text': f'日志巡检异常: {e}', 'level': 'WARNING'}))
        threading.Thread(target=worker, name='log-health', daemon=True).start()

    def _apply_log_health(self, report):
        """主线程渲染巡检结果：一行摘要 + 异常增长的 WARNING（同类只报一次）。

        告警去重按「当前告警集合」整体替换，而不是只增不减：异常消失后再出现
        会**重新**报一次（否则「报过一次就永远闭嘴」会把复发埋掉）。
        """
        abnormal = bool(report.warn_files()) or report.over_cap
        self.log_health_label.configure(
            text=report.summary(),
            fg=self._PALETTE['warning'] if abnormal else self._PALETTE['text_dim'])
        alerts = set(report.alerts())
        for text in sorted(alerts - self._log_health_warned):
            self.log_message(f'[日志巡检] {text}', 'WARNING')
        self._log_health_warned = alerts
        # 首个「含增长率」的结果额外记一行 INFO：它就是本次会话的增长基线，
        # 事后复盘「谁从什么时候开始长的」要有它。
        # 之后每 5 分钟不再出声（只在异常时告警）—— 巡检流水会把面板日志刷成噪声。
        if not abnormal and not report.first_sample and not self._log_health_baselined:
            self._log_health_baselined = True
            self.log_message(f'[日志巡检] {report.summary()}')

    # ── 写入与裁剪 ──────────────────────────────────────────────────────────
    def log_message(self, message, level='INFO'):
        timestamp = datetime.now().strftime('%H:%M:%S')
        self._log_buffer.append((f"[{timestamp}] {level}: {message}\n", level))
        fn = getattr(self.logger, level.lower(), None) or self.logger.warning
        if fn:
            fn(message)
        if not self._flush_pending:
            self._flush_pending = True
            try:
                self.root.after_idle(self._do_flush)
            except RuntimeError:
                # 窗口销毁竞态：after_idle 会抛 RuntimeError —— 复位标志，
                # 免得 _flush_pending 卡在 True 让后续日志永远不再刷新。
                self._flush_pending = False

    def _do_flush(self):
        self._flush_pending = False
        self._flush_log_buffer()

    def _flush_log_buffer(self):
        if not self._log_buffer:
            return
        buf = self._log_buffer[:]
        self._log_buffer.clear()
        self.log_text.config(state=tk.NORMAL)
        for entry, level in buf:
            self.log_text.insert(tk.END, entry, level)
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)

    def _schedule_log_flush(self):
        if self._log_buffer:
            self._flush_log_buffer()
        self._after_ids['flush'] = self.root.after(self.LOG_FLUSH_MS, self._schedule_log_flush)

    def clear_log(self):
        self.log_text.config(state=tk.NORMAL)
        self.log_text.delete('1.0', tk.END)
        self.log_text.config(state=tk.DISABLED)
        self.log_message("日志已清空")

    def export_log(self):
        from tkinter import filedialog
        log_dir = self._PROJECT_DIR / 'logs'
        log_dir.mkdir(exist_ok=True)
        filename = filedialog.asksaveasfilename(initialdir=log_dir, initialfile=f"server_log_{datetime.now():%Y%m%d_%H%M%S}.txt", defaultextension=".txt", filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")])
        if filename:
            try:
                with open(filename, 'w', encoding='utf-8') as f:
                    f.write(self.log_text.get('1.0', tk.END))
                self.log_message(f"日志已导出到: {filename}")
            except Exception as e:
                self.log_message(f"导出日志失败: {e!s}", 'ERROR')

    def _schedule_log_cleanup(self):
        self._perform_log_cleanup()
        self._after_ids['cleanup'] = self.root.after(self.LOG_CLEANUP_MS, self._schedule_log_cleanup)

    def _perform_log_cleanup(self):
        try:
            total = int(self.log_text.index('end-1c').split('.')[0])
            if total > self.MAX_LOG_LINES:
                self.log_text.config(state=tk.NORMAL)
                self.log_text.delete('1.0', f'{total - self.LOG_KEEP_LINES}.0')
                self.log_text.config(state=tk.DISABLED)
        except (tk.TclError, ValueError):
            pass

    # ── 日志文件保留清理（与上面的界面缓冲裁剪是两件事） ────────────────────
    def _schedule_log_file_cleanup(self, delay_ms=None):
        """定时清理 logs 目录（默认 14 天 / 512MB，见 log_ops）。

        为什么必须由管理器定时做：NSSM 只按 10MB 轮转、**从不删除**旧副本，
        server_manager_YYYYMMDD.log 每天新增一个也永不清理 —— 没人清就只增不减
        （用户诉求：「日志功能增加一个定时清理，不然日志越来越多」）。
        """
        self._after_ids['log_files'] = self.root.after(
            self.LOG_FILE_CLEANUP_FIRST_MS if delay_ms is None else delay_ms,
            self._log_file_cleanup_tick)

    def _log_file_cleanup_tick(self):
        """定时器回调：跑一轮维护（轮转+清理），并续上下一轮（无论成败都不中断调度链）。"""
        self.cleanup_log_files()
        self._schedule_log_file_cleanup(self.LOG_FILE_CLEANUP_MS)

    def cleanup_log_files(self):
        """日志维护一轮：**先轮转兜底、再清理过期**（后台线程，主线程只收总结）。

        顺序有意义：先把超限的现行日志切成 .1 副本（止血），再按保留期删旧文件
        （腾空间）—— 反过来先删的话，本轮刚轮转出的 .1 会白占一个保留周期。

        IO 不能放主线程：目录里可能有上百个文件（每个都要 stat），而轮转/删除都可能
        碰被占用的文件（被 NSSM/nginx 打开），只能在原语里如实记账、绝不能让界面卡住。
        """
        def worker():
            try:
                logs = self._PROJECT_DIR / 'logs'
                policy = self._log_policy()   # 每轮现读：设置改了下一轮就生效，不必重启管理器
                rotation = rotate_oversized_logs(logs, max_bytes=policy.rotate_bytes)
                report = prune_log_files(logs, keep_days=policy.keep_days,
                                         max_total_bytes=policy.max_total_bytes)
                level = 'WARNING' if (rotation.skipped or report.skipped) else 'INFO'
                self._msg_queue.put(('log', {'text': rotation.summary(), 'level': level}))
                self._msg_queue.put(('log', {'text': report.summary(), 'level': level}))
            except Exception as e:  # defensive: 维护失败只报告，不影响其它功能
                self._msg_queue.put(('log', {'text': f'日志维护异常: {e}', 'level': 'WARNING'}))
        threading.Thread(target=worker, name='log-file-cleanup', daemon=True).start()
