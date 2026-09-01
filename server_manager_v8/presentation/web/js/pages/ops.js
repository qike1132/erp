/* ============ 页面：告警（等级筛选 + 静默） / 日志（多源） / 配置（分组表单） / 权限（高危矩阵 + 审计） ============ */
'use strict';

/* ---- 告警中心 ---- */
window.PagesAlerts = (() => {
  const state = { filter: 'all', items: [] };

  function renderFilters() {
    const counts = { all: state.items.length };
    state.items.forEach((a) => { counts[a.severity] = (counts[a.severity] || 0) + 1; });
    const order = ['all', 'P0', 'P1', 'P2', 'P3', 'P4'];
    const box = document.getElementById('alert-filters');
    if (!box) return;
    box.innerHTML = order.filter((s) => s === 'all' || counts[s]).map((s) =>
      `<div class="filter ${state.filter === s ? 'active' : ''}" data-sev="${s}">
        ${s === 'all' ? '全部' : s} <span class="filter__count">${counts[s] || 0}</span>
      </div>`).join('');
    box.querySelectorAll('[data-sev]').forEach((b) => b.addEventListener('click', () => {
      state.filter = b.dataset.sev; render();
    }));
  }

  function render() {
    const box = document.getElementById('alert-list');
    if (!box) return;
    const items = state.filter === 'all' ? state.items : state.items.filter((a) => a.severity === state.filter);
    const stats = state.stats || {};
    document.getElementById('alert-stats').innerHTML = [
      ['未确认', stats.firing || 0, 'tag--err'],
      ['已抑制', stats.suppressed || 0, 'tag--warn'],
      ['MTTA', stats.mtta_s >= 0 ? stats.mtta_s + 's' : '—', 'tag--info'],
      ['MTTR', stats.mttr_s >= 0 ? stats.mttr_s + 's' : '—', 'tag--info'],
    ].map(([l, v, c]) => `<span class="tag ${c}">${l} ${v}</span>`).join(' ');
    box.innerHTML = items.map((a) => `
      <div class="alert-row" style="padding:10px 12px;border:1px solid var(--line);border-radius:var(--r-sm);margin-bottom:8px;background:var(--bg-2)">
        <div style="display:flex;align-items:center;gap:10px">
          <span class="tag" style="border-color:${a.severity_color}66;color:${a.severity_color}">${a.severity} ${a.severity_label}</span>
          <b style="color:var(--ink-1);flex:1">${App.esc(a.title)}</b>
          <span class="tag tag--dim">${App.esc(a.service || 'global')}</span>
          ${a.firing ? `<button class="btn btn--ghost btn--sm" data-ack="${App.esc(a.key)}">确认</button>` : '<span class="tag tag--ok">已确认</span>'}
        </div>
        <div style="color:var(--ink-3);font-size:12.5px;margin-top:6px">${App.esc(a.desc)} · 次数 ${a.count} · ${App.fmtTs(a.ts)}</div>
        ${a.runbook ? `<div style="margin-top:6px"><a href="${App.esc(a.runbook)}" style="color:var(--brand-2);font-size:12px">📖 ${App.esc(a.runbook)}</a></div>` : ''}
        ${a.suggested_action ? `<div style="margin-top:6px"><button class="btn btn--primary btn--sm" data-suggest="${App.esc(a.key)}">推荐修复：${App.esc(a.suggested_action)}</button></div>` : ''}
      </div>`).join('') || '<div class="empty">暂无告警 · 一切正常</div>';
    box.querySelectorAll('[data-ack]').forEach((b) => b.addEventListener('click', async () => {
      await API.alerts_ack(b.dataset.ack); refresh();
    }));
  }

  async function refresh() {
    const data = await API.alerts();
    state.items = data.items || [];
    state.stats = data.stats || {};
    renderFilters();
    render();
  }

  function bind() {
    document.getElementById('btn-ack-all').addEventListener('click', async () => {
      const r = await API.alerts_ack_all(); App.toast(r.ok ? 'ok' : 'err', r.reason || '已全部确认');
      refresh();
    });
    document.getElementById('btn-silence').addEventListener('click', () => App.callAction('silence_add',
      () => {
        const svc = document.getElementById('silence-svc').value.trim();
        const dur = parseFloat(document.getElementById('silence-dur').value) || 900;
        if (!svc) { App.toast('warn', '请输入服务名'); return Promise.resolve({}); }
        return API.silence_add(svc, dur, 'GUI 静默');
      }));
  }

  return { onShow: refresh, bind, refresh };
})();

/* ---- 日志中心（多源） ---- */
window.PagesLogs = (() => {
  const live = { source: '' };
  const SOURCES = [
    { id: '', label: '全部' },
    { id: 'server_manager', label: '管理器' },
    { id: 'fastapi_app', label: '后端' },
    { id: 'frontend', label: '前端' },
    { id: 'redis', label: 'Redis' },
  ];

  function renderTabs() {
    const box = document.getElementById('log-tabs');
    if (!box) return;
    box.innerHTML = SOURCES.map((s) =>
      `<div class="filter ${live.source === s.id ? 'active' : ''}" data-src="${App.esc(s.id)}">${s.label}</div>`
    ).join('');
    box.querySelectorAll('[data-src]').forEach((b) => b.addEventListener('click', () => {
      live.source = b.dataset.src; renderTabs(); refresh();
    }));
  }

  async function refresh() {
    const data = await API.logs(live.source, 500);
    const view = document.getElementById('log-view');
    if (!view) return;
    view.innerHTML = data.content ? App.esc(data.content) : '(空)';
    view.scrollTop = view.scrollHeight;
  }

  function append(payload) {
    const view = document.getElementById('log-view');
    if (!view || !view.dataset.live) return;
    if (live.source && payload.source && !payload.source.includes(live.source)) return;
    const line = document.createElement('div');
    line.className = 'lvl-' + (payload.level || 'INFO');
    line.textContent = `[${App.fmtTs(payload.ts || Date.now() / 1000)}] ${payload.text}`;
    view.appendChild(line);
    view.scrollTop = view.scrollHeight;
  }

  function bind() {
    document.getElementById('btn-log-refresh').addEventListener('click', refresh);
    const toggle = document.getElementById('log-live');
    if (toggle) toggle.addEventListener('change', () => {
      document.getElementById('log-view').dataset.live = toggle.checked ? '1' : '';
    });
    renderTabs();
  }

  return { onShow: refresh, append, bind };
})();

/* ---- 配置中心（分组表单 + JSON 高级模式） ---- */
window.PagesConfig = (() => {
  const GROUPS = [
    { key: 'app', label: '应用', fields: [
      { path: ['app', 'theme'], label: '主题', hint: 'light / dark' },
      { path: ['app', 'nav_collapsed'], label: '导航折叠', hint: 'true / false' },
    ]},
    { key: 'ports', label: '端口', fields: [
      { path: ['ports', 'api'], label: 'API', hint: '5002' },
      { path: ['ports', 'web'], label: 'Web', hint: '3000' },
      { path: ['ports', 'redis'], label: 'Redis', hint: '6379' },
    ]},
    { key: 'paths', label: '路径', fields: [
      { path: ['paths', 'redis_exe'], label: 'redis-server.exe', hint: '可空' },
      { path: ['paths', 'nssm'], label: 'nssm.exe', hint: '可空' },
      { path: ['paths', 'python'], label: 'Python 解释器', hint: '绝对路径' },
      { path: ['paths', 'project'], label: '项目目录', hint: '绝对路径' },
    ]},
    { key: 'logs', label: '日志', fields: [
      { path: ['logs', 'max_lines'], label: '最大行数', hint: '默认 2000' },
      { path: ['logs', 'keep_lines'], label: '保留行数', hint: '默认 1600' },
      { path: ['logs', 'retention_days'], label: '保留天数', hint: '默认 14' },
    ]},
  ];

  function get(d, p) { return p.reduce((x, k) => (x ? x[k] : undefined), d); }
  function set(d, p, v) {
    const clone = JSON.parse(JSON.stringify(d));
    let cur = clone;
    for (let i = 0; i < p.length - 1; i++) cur[p[i]] = cur[p[i]] || {};
    cur[p[p.length - 1]] = v;
    return clone;
  }

  let current = GROUPS[0].key;
  let form = {};

  async function refresh() {
    form = await API.config();
    renderTabs();
    renderForm();
  }
  function renderTabs() {
    const box = document.getElementById('cfg-tabs');
    if (!box) return;
    box.innerHTML = GROUPS.map((g) =>
      `<div class="filter ${current === g.key ? 'active' : ''}" data-g="${g.key}">${g.label}</div>`
    ).join('');
    box.querySelectorAll('[data-g]').forEach((b) => b.addEventListener('click', () => {
      current = b.dataset.g; renderTabs(); renderForm();
    }));
  }
  function renderForm() {
    const box = document.getElementById('cfg-form');
    const group = GROUPS.find((g) => g.key === current);
    if (!box || !group) return;
    box.style.display = '';
    box.innerHTML = group.fields.map((f) => {
      const v = get(form, f.path);
      return `<div class="cfg-field">
        <div class="cfg-field__label">${f.label}</div>
        <input class="cfg-field__input" data-path="${App.esc(f.path.join('.'))}" value="${App.esc(v == null ? '' : String(v))}">
        <div class="cfg-field__hint">${f.hint}</div>
      </div>`;
    }).join('');
    // 同步下方 JSON 视图（编辑即双向同步）
    const json = document.getElementById('cfg-json');
    if (json) json.textContent = JSON.stringify(form, null, 2);
  }
  function collectPatch() {
    document.querySelectorAll('#cfg-form .cfg-field__input').forEach((inp) => {
      const path = inp.dataset.path.split('.');
      let v = inp.value;
      if (v === 'true') v = true; else if (v === 'false') v = false;
      else if (/^\d+$/.test(v)) v = parseInt(v, 10);
      form = set(form, path, v);
    });
    return form;
  }

  function bind() {
    document.getElementById('btn-cfg-save').addEventListener('click', () => App.callAction('config_save',
      () => API.config_save(collectPatch())));
    document.getElementById('btn-cfg-migrate').addEventListener('click', async () => {
      const r = await API.config_migrate(); App.toast(r.ok ? 'ok' : 'err', r.reason || '迁移完成');
      refresh();
    });
  }

  return { onShow: refresh, bind, refresh };
})();

/* ---- 权限与审计（高危矩阵 + 审计流水） ---- */
window.PagesAccess = (() => {
  async function refresh() {
    const g = await API.guard_state();
    const s = g.session || {};
    document.getElementById('acc-session').innerHTML = `
      <div style="display:flex;gap:10px;align-items:center">
        <span class="tag tag--brand">当前角色 ${App.esc(s.base_role || 'viewer')}</span>
        ${s.elevated_active ? `<span class="tag tag--violet">提权至 ${App.esc(s.elevated)} · 剩余 ${Math.ceil(s.ttl_remaining || 0)}s</span>` : '<span class="tag tag--dim">未提权</span>'}
      </div>`;
    // 高危矩阵
    const ops = g.ops || {};
    const rows = Object.entries(ops).map(([action, op]) => {
      const dangerClass = `tag--${(op.danger || 'L0').toLowerCase()}`;
      const stateMark = op.allowed ? '<span class="tag tag--ok">允许</span>' : `<span class="tag tag--err">禁用</span>`;
      return `<div class="acc-matrix__row">
        <code style="color:var(--ink-1);font-family:ui-monospace,Consolas,monospace">${App.esc(action)}</code>
        <span style="color:var(--ink-3)">${App.esc(op.control || '')}</span>
        <span class="tag ${dangerClass}">${App.esc(op.danger || '')}</span>
        <span>${stateMark}</span>
        <span style="color:var(--ink-4);font-size:11px">${op.elevate_to ? '→ ' + op.elevate_to : ''}</span>
      </div>`;
    }).join('');
    const box = document.getElementById('acc-matrix');
    if (box) box.innerHTML = `<div class="acc-matrix__row header">
      <span>操作</span><span>管控方式</span><span>等级</span><span>状态</span><span>提权目标</span>
    </div>` + rows;
    // 审计
    const audit = await API.audit(80);
    document.getElementById('acc-audit').innerHTML = (audit || []).map((e) => `
      <tr>
        <td>${App.fmtTs(e.ts)}</td><td>${App.esc(e.actor)}</td><td>${App.esc(e.role)}</td>
        <td><code style="font-family:ui-monospace,Consolas,monospace;font-size:12px">${App.esc(e.action)}</code></td>
        <td>${App.esc(e.target || '—')}</td>
        <td><span class="tag ${e.result === 'ok' ? 'tag--ok' : 'tag--err'}">${e.result}</span></td>
      </tr>`).join('') || '<tr><td colspan="6" class="empty">暂无审计记录</td></tr>';
  }
  function bind() {
    document.getElementById('btn-elevate').addEventListener('click', () => App.callAction('elevate',
      () => API.elevate(document.getElementById('elevate-role').value, prompt('输入本地 PIN（P5 演示：任意）') || '')));
    document.getElementById('btn-degrade-acc').addEventListener('click', () => App.callAction('degrade',
      () => API.degrade()));
  }
  return { onShow: refresh, bind, refresh };
})();
