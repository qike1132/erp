/* ============ 页面：总览驾驶舱（Stepper + KPI + 一键操作） ============ */
'use strict';

window.PagesOverview = (() => {
  const pollMs = 4000;
  let timer = null;

  function el(id) { return document.getElementById(id); }
  function setText(id, v) { const n = el(id); if (n) n.textContent = v; }

  async function refresh() {
    const [s, m] = await Promise.all([API.status(), API.metrics()]);
    if (s) {
      setText('ov-mode', { idle: '空闲', dev: '开发模式', prod: '生产模式', switching: '切换中' }[s.mode] || s.mode);
      setText('ov-redis', s.redis_ok ? '运行中' : '已停止');
      setText('ov-alerts', String(s.alerts_unconfirmed));
      setText('ov-services', String((s.services || []).filter((x) => x.state === 'running').length) + ' / ' + (s.services ? s.services.length : 0));
      const handles = Object.entries(s.handles || {}).map(([k, pid]) => `${k}(PID ${pid})`).join(' · ') || '无开发进程';
      setText('ov-handles', handles);
    }
    if (m) {
      setText('ov-cpu', m.cpu.toFixed(1) + '%');
      setText('ov-mem', m.mem.toFixed(1) + '%');
      setText('ov-sat', m.saturation.toFixed(1) + '%');
      setText('ov-net', m.net_dn_mb.toFixed(2) + ' MB/s');
      const procs = el('ov-procs');
      procs.innerHTML = (m.procs || []).map((p) =>
        `<div class="proc-row"><span>${App.esc(p[0])}</span><span style="color:var(--brand)">${p[1].toFixed(0)}%</span></div>`).join('')
        || '<div class="empty">安装 psutil 后可查看进程</div>';
    }
  }

  function pushMetrics(sample) {
    if (!sample) return;
    setText('ov-cpu', sample.cpu.toFixed(1) + '%');
    setText('ov-mem', sample.mem.toFixed(1) + '%');
    setText('ov-sat', sample.saturation.toFixed(1) + '%');
    setText('ov-net', sample.net_dn_mb.toFixed(2) + ' MB/s');
  }

  function bind() {
    el('btn-start-dev').addEventListener('click', () => App.callAction('start_dev',
      (reason) => API.start_dev(reason),
      { impact: '将启动 Redis + 后端 + 前端，启用 5002/3000/6379 端口' }));
    el('btn-start-prod').addEventListener('click', () => App.callAction('start_prod',
      (reason) => API.start_prod(reason),
      { impact: '将通过 NSSM 启动 erp-prod / erp-arq 服务' }));
    el('btn-stop-all').addEventListener('click', () => App.callAction('stop_all',
      (reason) => API.stop_all(reason),
      { impact: '将停止所有服务（开发进程 + NSSM 服务）' }));
    el('btn-install').addEventListener('click', () => App.callAction('install_services',
      (reason) => API.install_services(reason || 'GUI 安装'),
      { impact: '将向 NSSM 注册 erp-prod / erp-arq（开机自启）' }));
    el('btn-uninstall').addEventListener('click', () => App.callAction('uninstall_services',
      (reason) => API.uninstall_services(reason || 'GUI 卸载'),
      { impact: '将停止并卸载 erp-prod / erp-arq Windows 服务' }));
    el('btn-refresh-ov').addEventListener('click', refresh);
  }

  return {
    onShow: refresh,
    startPolling: () => { if (!timer) { timer = setInterval(refresh, pollMs); } },
    stopPolling: () => { if (timer) { clearInterval(timer); timer = null; } },
    pushMetrics,
    refresh,
    bind,
  };
})();
