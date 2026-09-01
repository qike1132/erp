/* ============ 应用壳：路由 / 主题 / Toast / 事件推送 __push / 权限态 ============ */
'use strict';

const App = (() => {
  let current = 'overview';
  const guardOps = {}; // { action: { allowed, danger, control, role, elevate_to } }
  let pipeline = null;  // { name, total, steps: [{name, state, detail}] }

  /* ---- 工具 ---- */
  function el(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g,
      (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }
  function fmtTs(ts) {
    if (!ts) return '—';
    const d = new Date(ts * 1000);
    const p = (n) => String(n).padStart(2, '0');
    return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
  }

  /* ---- Toast ---- */
  const toastWrap = () => {
    let w = el('toast-wrap');
    if (!w) { w = document.createElement('div'); w.id = 'toast-wrap';
      w.className = 'toast-wrap'; document.body.appendChild(w); }
    return w;
  };
  function toast(level, text) {
    const t = document.createElement('div');
    t.className = `toast toast--${level}`;
    t.textContent = text;
    toastWrap().appendChild(t);
    setTimeout(() => t.remove(), 3800);
  }

  /* ---- 路由 ---- */
  const pages = {
    overview: window.PagesOverview, services: window.PagesServices,
    alerts: window.PagesAlerts, logs: window.PagesLogs,
    config: window.PagesConfig, access: window.PagesAccess,
    settings: window.PagesSettings,
  };
  function navTo(name) {
    current = name;
    document.querySelectorAll('.nav__item').forEach((b) =>
      b.classList.toggle('active', b.dataset.page === name));
    document.querySelectorAll('.page').forEach((p) => p.classList.remove('active'));
    el(`page-${name}`).classList.add('active');
    if (pages[name] && pages[name].onShow) pages[name].onShow();
  }

  /* ---- 顶栏状态 ---- */
  async function refreshTopbar() {
    try {
      const s = await API.status();
      el('mode-chip').textContent = { idle: '空闲', dev: '开发模式', prod: '生产模式', switching: '切换中' }[s.mode] || s.mode;
      el('mode-chip').className = 'chip ' + (s.mode === 'prod' ? 'chip--err' : s.mode === 'dev' ? 'chip--ok' : '');
      const redis = el('redis-chip');
      redis.textContent = s.redis_ok ? 'Redis 运行中' : 'Redis 停止';
      redis.className = 'chip ' + (s.redis_ok ? 'chip--ok' : 'chip--dim');
      const alertBadge = el('alert-badge');
      alertBadge.textContent = s.alerts_unconfirmed;
      alertBadge.style.display = s.alerts_unconfirmed > 0 ? '' : 'none';
    } catch (e) { /* 首屏竞态 */ }
  }

  /* ---- 权限态：拉 guard_state → 应用到按钮（置灰 + danger 标签） ---- */
  async function refreshGuard() {
    try {
      const g = await API.guard_state();
      Object.assign(guardOps, g.ops || {});
      document.querySelectorAll('button[data-action]').forEach((btn) => {
        const op = guardOps[btn.dataset.action];
        if (!op) return;
        // 置灰 = 无权限（禁用而非隐藏）
        btn.disabled = !op.allowed;
        btn.title = op.allowed
          ? `${op.control} · 当前 ${op.role}`
          : `无权限 — 提权至 ${op.elevate_to || 'operator'} 后可执行`;
        // 已有 danger 标签不重复加
        if (!btn.querySelector('.danger-tag') && op.danger && op.danger !== 'L0') {
          const t = document.createElement('span');
          t.className = 'tag tag--' + op.danger.toLowerCase();
          t.style.marginLeft = '6px';
          t.textContent = op.danger;
          btn.appendChild(t);
        }
      });
      if (pages.access && pages.access.onShow) pages.access.onShow();
    } catch (e) { /* 竞态 */ }
  }

  /* ---- 操作流：检查授权 → 弹确认（L2/L3）→ 弹原因（L3）→ 调 API ---- */
  async function callAction(action, runFn, opts) {
    opts = opts || {};
    const op = guardOps[action];
    if (op && !op.allowed) {
      toast('warn', `无权限（需提权至 ${op.elevate_to || 'operator'}）`);
      return;
    }
    if (op && op.control === 'confirm_impact') {
      const ok = confirm('⚠️ 高危操作确认\n\n将影响：' + (opts.impact || '相关服务与进程') + '\n\n确定继续？');
      if (!ok) return;
    }
    let reason = '';
    if (op && op.control === 'type_name_reason') {
      const name = prompt('⚠️ 极高危操作\n\n请键入操作名以确认：');
      if (!name) return;
      reason = prompt('请填写变更原因：');
      if (!reason || !reason.trim()) { toast('warn', '变更原因必填'); return; }
    }
    const r = await runFn(reason);
    if (r && r.denied) {
      toast('warn', `权限不足：${r.reason}`);
      return;
    }
    toast(r && r.ok ? 'ok' : 'err', (r && (r.reason || r.detail)) || '操作完成');
    if (r && r.ok) { refreshTopbar(); refreshGuard(); }
    return r;
  }

  /* ---- Pipeline Stepper ---- */
  function resetStepper(name, total) {
    pipeline = { name, total, steps: [] };
    el('ov-stepper-card').style.display = '';
    el('ov-stepper-name').textContent = `Pipeline · ${name}`;
    el('ov-stepper-progress').textContent = `0 / ${total}`;
    renderStepper();
  }
  function setStep(idx, name, state, detail) {
    if (!pipeline) return;
    const existing = pipeline.steps.findIndex((s) => s.name === name);
    if (existing >= 0) {
      pipeline.steps[existing] = { idx, name, state, detail };
    } else {
      pipeline.steps.push({ idx, name, state, detail });
    }
    const done = pipeline.steps.filter((s) => s.state === 'done').length;
    el('ov-stepper-progress').textContent = `${done} / ${pipeline.total}`;
    renderStepper();
  }
  function finishStepper(ok) {
    if (!pipeline) return;
    el('ov-stepper-progress').textContent = ok ? '✓ 完成' : '✗ 失败';
    setTimeout(() => { el('ov-stepper-card').style.display = 'none'; }, 4000);
  }
  function renderStepper() {
    const box = el('ov-stepper');
    if (!box || !pipeline) return;
    box.innerHTML = pipeline.steps.map((s, i) => {
      const sep = i > 0 ? '<span class="stepper__sep"></span>' : '';
      return sep + `<div class="stepper__step ${s.state}">
        <span class="num">${s.idx}</span>
        <div style="flex:1">
          <div>${App.esc(s.name)}</div>
          ${s.detail ? `<div style="font-size:11px;color:var(--ink-4)">${App.esc(s.detail)}</div>` : ''}
        </div>
      </div>`;
    }).join('');
  }

  /* ---- 事件推送 ---- */
  function onPush(payload) {
    if (!payload || !payload.type) return;
    switch (payload.type) {
      case 'toast':
        toast(payload.level || 'info', payload.text); break;
      case 'log':
        if (pages.logs && pages.logs.append) pages.logs.append(payload); break;
      case 'metrics':
        if (pages.overview && pages.overview.pushMetrics) pages.overview.pushMetrics(payload.sample); break;
      case 'pipeline_start':
        resetStepper(payload.name, payload.steps || 0); break;
      case 'step':
        setStep(payload.index, payload.step, payload.state, payload.detail); break;
      case 'pipeline_finish':
        finishStepper(payload.ok); refreshTopbar(); break;
      case 'mode':
        refreshTopbar(); break;
      case 'alert_raised':
        refreshTopbar();
        if (current === 'alerts' && pages.alerts.onShow) pages.alerts.onShow();
        toast('warn', payload.title); break;
      case 'alert_resolved':
        refreshTopbar();
        if (current === 'alerts' && pages.alerts.onShow) pages.alerts.onShow(); break;
      case 'auth':
        refreshGuard(); break;
      default:
        break;
    }
  }

  /* ---- 主题 ---- */
  function applyTheme(theme) {
    if (theme === 'light') document.documentElement.dataset.theme = 'light';
    else delete document.documentElement.dataset.theme;  // 默认暗色（:root 即暗色变量）
  }
  function getTheme() {
    return document.documentElement.dataset.theme === 'light' ? 'light' : 'dark';
  }
  function toggleTheme() {
    const next = getTheme() === 'light' ? 'dark' : 'light';
    applyTheme(next);
    // 持久化到配置（best-effort，权限不足时降级为仅本次会话生效）
    try { API.config_save({ app: { theme: next } }); } catch (e) { /* 忽略 */ }
  }

  /* ---- 引导 ---- */
  async function boot() {
    document.querySelectorAll('.nav__item').forEach((b) =>
      b.addEventListener('click', () => navTo(b.dataset.page)));
    el('btn-collapse').addEventListener('click', () =>
      document.querySelector('.shell').classList.toggle('collapsed'));
    el('btn-theme').addEventListener('click', toggleTheme);
    el('btn-degrade').addEventListener('click', async () => {
      await API.degrade(); refreshGuard(); refreshTopbar(); App.toast('ok', '已降权');
    });
    window.__push = onPush;
    // 应用已保存主题（配置驱动页面，消解 theme 字段与 GUI 实际暗色的冲突）
    try {
      const cfg = await API.config();
      if (cfg && cfg.app) applyTheme(cfg.app.theme === 'light' ? 'light' : 'dark');
    } catch (e) { /* 配置未就绪，沿用默认暗色 */ }
    Object.values(pages).forEach((p) => { if (p && p.bind) p.bind(); });
    await refreshTopbar();
    await refreshGuard();
    navTo('overview');
    if (pages.overview && pages.overview.startPolling) pages.overview.startPolling();
  }

  return { boot, navTo, toast, refreshTopbar, refreshGuard, callAction,
           esc, fmtTs, onPush, current: () => current, pipeline: () => pipeline,
           applyTheme, getTheme };
})();

document.addEventListener('DOMContentLoaded', () => App.boot());
window.App = App;
