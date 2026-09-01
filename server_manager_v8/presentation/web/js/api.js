/* ============ JS API 封装：pywebview 原生调用 + 浏览器降级 mock ============ */
/* 在 pywebview 中：window.pywebview.api.* 返回 Promise（bridge.py 定义）。
   直接浏览器打开 index.html 时无 pywebview → 走 MOCK（便于无后端调试 UI）。 */
'use strict';

const API = (() => {
  const native = (window.pywebview && window.pywebview.api) || null;

  /* ---- 浏览器降级数据（无后端时演示） ---- */
  const MOCK = {
    status: () => ({ ok: true, mode: 'idle', switching: false,
      services: [
        { name: 'erp-prod', state: 'stopped', pid: null },
        { name: 'erp-arq', state: 'stopped', pid: null },
      ],
      redis_ok: false, redis_error: '', handles: {}, alerts_unconfirmed: 2, audit_entries: 0 }),
    alerts: () => ({ items: [
      { key: 'demo@api', severity: 'P1', severity_label: '严重', severity_color: '#FA8C16',
        title: '演示告警：API 健康检查失败', desc: 'mock 模式 · 浏览器直开', service: 'api',
        family: 'availability', status: 'firing', firing: true, count: 1, ts: Date.now() / 1000,
        last_ts: Date.now() / 1000, runbook: '', suggested_action: 'restart_api' },
    ], stats: { total: 1, firing: 1, suppressed: 0, mtta_s: -1, mttr_s: -1 }, silences: [] }),
    config: () => ({ schema_version: 2, app: { theme: 'dark' },
      ports: { api: 5002, web: 3000, redis: 6379 }, paths: { redis_exe: '', nssm: '' } }),
    logs: (source, limit) => ({ files: [{ name: 'server_manager.log', size: 1024 }],
      content: 'mock 模式 · 无后端日志\n', error: '' }),
    metrics: () => ({ cpu: 23.4, mem: 61.2, disk: 48.0, net_dn_mb: 0.4, net_up_kb: 12.3,
      saturation: 61.2, procs: [['python.exe (1234)', 12.0, 3.2], ['node.exe (5678)', 8.0, 2.1]] }),
    guard_state: () => {
      const MOCK_OPS = {
        view: { allowed: true, danger: 'L0', control: 'none', role: 'viewer', elevate_to: null },
        export_logs: { allowed: true, danger: 'L0', control: 'none', role: 'viewer', elevate_to: null },
        ack_alert: { allowed: true, danger: 'L0', control: 'none', role: 'viewer', elevate_to: null },
        start_service: { allowed: true, danger: 'L1', control: 'toast_undo', role: 'viewer', elevate_to: null },
        restart_service: { allowed: true, danger: 'L1', control: 'toast_undo', role: 'viewer', elevate_to: null },
        silence_alert: { allowed: true, danger: 'L1', control: 'toast_undo', role: 'viewer', elevate_to: null },
        run_backup: { allowed: true, danger: 'L1', control: 'toast_undo', role: 'viewer', elevate_to: null },
        clear_logs: { allowed: true, danger: 'L1', control: 'toast_undo', role: 'viewer', elevate_to: null },
        stop_service: { allowed: false, danger: 'L2', control: 'confirm_impact', role: 'viewer', elevate_to: 'operator' },
        kill_port: { allowed: false, danger: 'L2', control: 'confirm_impact', role: 'viewer', elevate_to: 'operator' },
        switch_mode: { allowed: false, danger: 'L2', control: 'confirm_impact', role: 'viewer', elevate_to: 'operator' },
        edit_config: { allowed: false, danger: 'L2', control: 'confirm_impact', role: 'viewer', elevate_to: 'operator' },
        start_dev: { allowed: false, danger: 'L2', control: 'confirm_impact', role: 'viewer', elevate_to: 'operator' },
        start_prod: { allowed: false, danger: 'L2', control: 'confirm_impact', role: 'viewer', elevate_to: 'operator' },
        stop_all: { allowed: false, danger: 'L2', control: 'confirm_impact', role: 'viewer', elevate_to: 'operator' },
        install_services: { allowed: false, danger: 'L3', control: 'type_name_reason', role: 'viewer', elevate_to: 'admin' },
        uninstall_services: { allowed: false, danger: 'L3', control: 'type_name_reason', role: 'viewer', elevate_to: 'admin' },
        edit_permissions: { allowed: false, danger: 'L3', control: 'type_name_reason', role: 'viewer', elevate_to: 'admin' },
      };
      return { session: { base_role: 'viewer', elevated: null, elevated_active: false,
        expires_at: 0, ttl_remaining: 0 }, ops: MOCK_OPS };
    },
    audit: () => [],
    authorize: (action) => ({ action, allowed: true, danger: 'L0', control: 'none', elevate_to: null, reason: '' }),
    elevate: () => ({ ok: true, role: 'operator' }),
    degrade: () => ({ ok: true }),
  };

  function call(name, ...args) {
    if (native && typeof native[name] === 'function') {
      return Promise.resolve(native[name](...args)).catch((err) => ({
        ok: false, reason: `bridge 调用失败: ${err.message || err}`,
      }));
    }
    const mock = MOCK[name];
    if (mock) return Promise.resolve(mock(...args));
    return Promise.resolve({ ok: false, reason: '浏览器模式无该接口' });
  }

  return {
    isNative: !!native,
    status: () => call('status'),
    alerts: () => call('alerts'),
    config: () => call('config'),
    logs: (s, l) => call('logs', s, l),
    metrics: () => call('metrics'),
    guard_state: () => call('guard_state'),
    audit: () => call('audit'),
    authorize: (a, r) => call('authorize', a, r),
    elevate: (to, pin) => call('elevate', to, pin),
    degrade: () => call('degrade'),
    start_dev: () => call('start_dev'),
    start_prod: () => call('start_prod'),
    stop_all: () => call('stop_all'),
    switch_mode: (t, r) => call('switch_mode', t, r),
    kill_port: (p) => call('kill_port', p),
    alerts_ack: (k) => call('alerts_ack', k),
    alerts_ack_all: () => call('alerts_ack_all'),
    silence_add: (s, d, r) => call('silence_add', s, d, r),
    silence_remove: (id) => call('silence_remove', id),
    config_save: (patch) => call('config_save', patch),
    config_migrate: () => call('config_migrate'),
    install_services: (r) => call('install_services', r),
    uninstall_services: (r) => call('uninstall_services', r),
  };
})();

window.API = API;
