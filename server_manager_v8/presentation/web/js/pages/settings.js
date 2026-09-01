/* ============ 页面：设置（主题 + 运行参数 + 日志 + 安全） ============ */
'use strict';

window.PagesSettings = (() => {
  let cfg = {};

  function el(id) { return document.getElementById(id); }
  function val(id) { const n = el(id); return n ? n.value.trim() : ''; }
  function num(id, dflt) {
    const v = parseInt(val(id), 10);
    return Number.isFinite(v) ? v : dflt;
  }
  function field(id, label, value, hint, type) {
    const t = type || 'text';
    return `<div class="cfg-field">
      <div class="cfg-field__label">${App.esc(label)}</div>
      <input class="cfg-field__input" id="${id}" type="${t}" value="${App.esc(value)}">
      ${hint ? `<div class="cfg-field__hint">${App.esc(hint)}</div>` : ''}
    </div>`;
  }

  async function onShow() { load(); }

  async function load() {
    try { cfg = await API.config() || {}; } catch (e) { cfg = {}; }
    render();
  }

  function render() {
    const app = cfg.app || {};
    const ports = cfg.ports || {};
    const paths = cfg.paths || {};
    const logs = cfg.logs || {};
    const auth = cfg.auth || {};
    const theme = app.theme === 'light' ? 'light' : 'dark';

    el('set-body').innerHTML = `
      <div class="card">
        <div class="card__hd"><h3>外观</h3>
          <span class="sub">配置 schema 的 app.theme 字段现在真实驱动页面（设计文档 5.1：深色优先、亮色可选）</span></div>
        <div class="cfg-form">
          <div class="cfg-field">
            <div class="cfg-field__label">界面主题</div>
            <div style="display:flex;gap:14px;align-items:center;padding:4px 0">
              <label style="display:flex;gap:6px;align-items:center;font-size:13px">
                <input type="radio" name="set-theme" value="dark" ${theme === 'dark' ? 'checked' : ''}> 暗色（默认）</label>
              <label style="display:flex;gap:6px;align-items:center;font-size:13px">
                <input type="radio" name="set-theme" value="light" ${theme === 'light' ? 'checked' : ''}> 亮色</label>
            </div>
            <button class="btn btn--ghost btn--sm" id="set-preview" style="margin-top:6px">预览切换（不保存）</button>
          </div>
        </div>
      </div>

      <div class="card">
        <div class="card__hd"><h3>运行参数</h3>
          <span class="sub">修改端口 / 路径后相关服务需重启生效</span></div>
        <div class="cfg-form">
          ${field('set-port-api', 'API 端口', ports.api ?? 5002, '', 'number')}
          ${field('set-port-web', 'Web 端口', ports.web ?? 3000, '', 'number')}
          ${field('set-port-redis', 'Redis 端口', ports.redis ?? 6379, '', 'number')}
          ${field('set-path-redis', 'Redis 路径', paths.redis_exe || '', '可选，留空则自动探测')}
          ${field('set-path-nssm', 'NSSM 路径', paths.nssm || '', '可选，留空则自动探测')}
          ${field('set-path-python', 'Python 路径', paths.python || '', '可选，留空则使用系统 Python')}
          ${field('set-path-project', '项目路径', paths.project || '', '可选，ERP 后端根目录')}
        </div>
      </div>

      <div class="card">
        <div class="card__hd"><h3>日志</h3></div>
        <div class="cfg-form">
          ${field('set-log-max', '最大行数', logs.max_lines ?? 2000, '', 'number')}
          ${field('set-log-keep', '保留行数', logs.keep_lines ?? 1600, '', 'number')}
          ${field('set-log-ret', '保留天数', logs.retention_days ?? 14, '', 'number')}
        </div>
      </div>

      <div class="card">
        <div class="card__hd"><h3>安全</h3></div>
        <div class="cfg-form">
          <div class="cfg-field">
            <div class="cfg-field__label">默认角色</div>
            <select class="cfg-field__input" id="set-auth-role">
              <option value="viewer" ${auth.default_role === 'viewer' ? 'selected' : ''}>viewer</option>
              <option value="operator" ${auth.default_role === 'operator' ? 'selected' : ''}>operator</option>
              <option value="admin" ${auth.default_role === 'admin' ? 'selected' : ''}>admin</option>
            </select>
          </div>
          <div class="cfg-field">
            <div class="cfg-field__label">极高危操作需填原因</div>
            <label style="display:flex;gap:6px;align-items:center;font-size:13px;padding:8px 0">
              <input type="checkbox" id="set-auth-reason" ${auth.require_reason_for_l3 ? 'checked' : ''}> 启用（L3 操作须键入操作名 + 变更原因）</label>
          </div>
        </div>
      </div>

      <div style="display:flex;gap:10px;margin-top:4px">
        <button class="btn btn--primary" id="set-save">保存配置</button>
        <button class="btn btn--ghost" id="set-discard">放弃修改</button>
      </div>
    `;

    el('set-preview').addEventListener('click', () => {
      const t = document.querySelector('input[name="set-theme"]:checked');
      if (t) App.applyTheme(t.value);
    });
    el('set-discard').addEventListener('click', render);
    el('set-save').addEventListener('click', save);
  }

  async function save() {
    const t = document.querySelector('input[name="set-theme"]:checked');
    const theme = (t && t.value) || 'dark';
    const patch = {
      app: { theme },
      ports: {
        api: num('set-port-api', 5002),
        web: num('set-port-web', 3000),
        redis: num('set-port-redis', 6379),
      },
      paths: {
        redis_exe: val('set-path-redis'),
        nssm: val('set-path-nssm'),
        python: val('set-path-python'),
        project: val('set-path-project'),
      },
      logs: {
        max_lines: num('set-log-max', 2000),
        keep_lines: num('set-log-keep', 1600),
        retention_days: num('set-log-ret', 14),
      },
      auth: {
        default_role: val('set-auth-role') || 'viewer',
        require_reason_for_l3: el('set-auth-reason').checked,
      },
    };
    for (const [k, v] of Object.entries(patch.ports)) {
      if (!(v >= 1 && v <= 65535)) { App.toast('warn', `端口 ${k} 超出范围 (1–65535)`); return; }
    }
    const r = await App.callAction('edit_config', () => API.config_save(patch),
      { impact: '更新运行参数、日志与权限默认值（部分项需重启服务生效）' });
    if (r && r.ok) App.applyTheme(theme);
  }

  return { onShow, load, render, save };
})();
