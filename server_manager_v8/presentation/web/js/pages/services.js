/* ============ 页面：服务编排（期望态 + 服务清单） ============ */
'use strict';

window.PagesServices = (() => {
  async function refresh() {
    const s = await API.status();
    const tbody = document.getElementById('svc-tbody');
    if (!tbody) return;
    const rows = (s.services || []).map((svc) => {
      const stateTag = svc.state === 'running' ? 'tag--ok' : svc.state === 'stopped' ? 'tag--dim' : 'tag--warn';
      const stateText = { running: '运行中', stopped: '已停止', paused: '已暂停', absent: '未安装', unknown: '未知' }[svc.state] || svc.state;
      return `<tr>
        <td><b style="color:var(--ink-1)">${App.esc(svc.name)}</b></td>
        <td><span class="tag ${stateTag}">${stateText}</span></td>
        <td>${svc.pid ? 'PID ' + svc.pid : '—'}</td>
        <td>NSSM</td>
      </tr>`;
    }).join('');
    tbody.innerHTML = rows || '<tr><td colspan="4" class="empty">暂无服务</td></tr>';
    const mode = s.mode;
    document.getElementById('svc-flow').innerHTML = ['idle', 'dev', 'prod'].map((m) => {
      const active = m === mode;
      return `<span class="tag ${active ? 'tag--brand' : 'tag--dim'}">${active ? '● ' : ''}${m === 'idle' ? '空闲' : m === 'dev' ? '开发' : '生产'}</span>`;
    }).join(' → ');
  }

  function bind() {
    document.getElementById('btn-svc-dev').addEventListener('click', () => App.callAction('switch_mode',
      (reason) => API.switch_mode('dev', reason),
      { impact: '将先停止生产服务，再启动开发模式' }));
    document.getElementById('btn-svc-prod').addEventListener('click', () => App.callAction('switch_mode',
      (reason) => API.switch_mode('prod', reason),
      { impact: '将先停止开发进程，再通过 NSSM 启动生产服务' }));
  }

  return { onShow: refresh, bind, refresh };
})();
