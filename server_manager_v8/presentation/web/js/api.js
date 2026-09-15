/* ============================================================
   ERP 服务器管理器 v8 —— 后端 API 封装（前端唯一的后端出口）

   ★ 所有后端调用都必须经过本模块，不允许页面直接碰 pywebview。

   这么约束有三个具体理由：

   ① **降级可演示**：`window.pywebview` 只在打包/宿主运行时存在。
      直接用它，本原型在浏览器里打开会满屏报错（UI 完全不可用）。
      统一在这里做「无后端 → 用原型数据」的回退，
      于是同一份 HTML 既能接真实后端，也能独立演示。

   ② **错误形状统一**：后端所有方法都返回 `{ok, reason, detail}`。
      但 pywebview 的 Promise 在桥方法抛异常时会 reject，
      直接 await 会得到一个没有 `ok` 字段的错误对象 ——
      页面若各自 try/catch，会因漏判而把失败当成功。
      这里统一兜成 `{ok:false, reason, detail}`。

   ③ **调用点可审计**：想知道前端调了哪些后端能力，
      看这一个文件就够了。散落在 8 个页面里就没法审了。

   ============================================================ */
(function () {
  'use strict';

  /* ---------- 后端可用性 ---------- */
  function backend() {
    return (typeof window !== 'undefined' &&
            window.pywebview &&
            window.pywebview.api) || null;
  }

  /** 后端是否真的可用（接上了 python 宿主） */
  function isLive() { return backend() !== null; }

  /* ---------- 统一调用 ---------- */
  /**
   * 调用后端方法。
   *
   * ★ 无论成功失败都返回 `{ok, reason, detail, ...}` 形状，
   *   **永不抛异常、永不 reject** —— 页面可以无条件 await 后判 `ok`。
   *
   * @param {string} name  后端方法名（与 bridge.py 的扁平方法名一致）
   * @param {...any} args  位置参数
   * @returns {Promise<object>}
   */
  async function call(name) {
    var args = Array.prototype.slice.call(arguments, 1);
    var api = backend();

    if (!api) {
      return mock(name, args);
    }

    var fn = api[name];
    if (typeof fn !== 'function') {
      return {
        ok: false,
        reason: '后端缺少方法',
        detail: 'bridge 未暴露 ' + name + '（前端与后端版本不匹配？）'
      };
    }

    try {
      var r = await fn.apply(api, args);
      // 后端异常时可能返回 null/undefined，兜成明确失败
      if (r == null) {
        return { ok: false, reason: '后端返回空', detail: name };
      }
      return r;
    } catch (e) {
      return { ok: false, reason: '调用失败', detail: String(e && e.message || e) };
    }
  }

  /* ============================================================
     原型数据回退（无后端时使用）

     ★ 这些数据的存在意义是「让界面能被评审」，
       不是「假装系统在运行」。所以每个 mock 都带 `__mock: true`，
       页面可在醒目位置显示「演示数据」横幅 ——
       把假数据显示成真数据是最糟的一种误导。
     ============================================================ */
  function mock(name, args) {
    switch (name) {
      case 'bootstrap':
        return Promise.resolve({
          ok: true, __mock: true,
          session: mockSession(),
          permissions: { role: 'viewer', actions: [] },
          mode: { ok: true, mode: 'none', conflicting: false, ambiguous: false,
                  prod_running: [], prod_unknown: [], dev_port_holders: [] },
          services: { ok: true, services: mockServices() },
          config: { ok: true, config: null },
          alerts: { ok: true, alerts: [] },
          notes: ['演示数据：未连接后端']
        });
      case 'session_state':
        return Promise.resolve({ ok: true, __mock: true, ...mockSession() });
      case 'detect_mode':
        return Promise.resolve({ ok: true, __mock: true, mode: 'none' });
      case 'service_list':
        return Promise.resolve({ ok: true, __mock: true, services: mockServices() });
      case 'metrics':
        return Promise.resolve({ ok: true, __mock: true, sample: null });
      case 'alert_list':
        return Promise.resolve({ ok: true, __mock: true, alerts: [] });
      case 'logs':
        return Promise.resolve({ ok: true, __mock: true, entries: [] });
      case 'verify_chain':
        return Promise.resolve({ ok: true, __mock: true, intact: true, total: 0 });
      case 'poll_events':
        return Promise.resolve({ ok: true, __mock: true, events: [], dropped: 0 });
      case 'environment':
        return Promise.resolve({ ok: true, __mock: true, has_psutil: false });
      default:
        // 变更类操作在演示模式下**拒绝执行**，而不是假装成功 ——
        // 假装成功会让用户以为服务真的被停了。
        return Promise.resolve({
          ok: false, __mock: true,
          reason: '演示模式',
          detail: '未连接后端，' + name + ' 未真正执行'
        });
    }
  }

  function mockSession() {
    return {
      role: state && state.role ? state.role : 'viewer',
      elevated: !!(state && state.role && state.role !== 'viewer'),
      remaining_s: 0, expires_at: null
    };
  }

  function mockServices() {
    return [
      { name: 'erp-prod', status: 'absent', status_label: '未安装', pid: null },
      { name: 'erp-arq',  status: 'absent', status_label: '未安装', pid: null }
    ];
  }

  /* ============================================================
     语义化封装（页面应优先用这些，而不是裸 call）

     ★ 每个方法都显式列出参数，而不是让页面自己拼 ——
       这样后端改签名时，改这里一处即可，页面不必跟着动。
     ============================================================ */
  const API = {
    isLive, call,

    /* -- 会话与权限 -- */
    bootstrap:        () => call('bootstrap'),
    sessionState:     () => call('session_state'),
    elevate:          (role) => call('elevate', role || 'operator'),
    deElevate:        () => call('de_elevate'),
    permissionMatrix: () => call('permission_matrix'),
    checkPermission:  (action) => call('check_permission', action),

    /* -- 确认流程（L2/L3）-- */
    requestConfirmation: (action) => call('request_confirmation', action),

    /* -- 只读查询 -- */
    detectMode:   () => call('detect_mode'),
    serviceList:  () => call('service_list'),
    metrics:      () => call('metrics'),
    logs:         (opts) => call('logs', opts || {}),
    verifyChain:  () => call('verify_chain'),
    alertList:    (notifyOnly) => call('alert_list', !!notifyOnly),
    portInspect:  (port) => call('port_inspect', port),
    configLoad:   () => call('config_load'),
    environment:  () => call('environment'),
    pollEvents:   (limit) => call('poll_events', limit || 200),
    windowReady:  () => call('window_ready'),

    /* -- 变更操作（统一形状：tokenId / typedName / reason）-- */
    switchMode: (mode, t) => call('switch_mode', mode, t.tokenId || '',
                                  t.typedName || '', t.reason || ''),
    stopAll:    (stopRedis, t) => call('stop_all', t.tokenId || '',
                                       t.typedName || '', t.reason || '',
                                       stopRedis !== false),
    startDev:   (t) => call('start_dev', t.tokenId || '',
                            t.typedName || '', t.reason || ''),
    startProd:  (t) => call('start_prod', t.tokenId || '',
                            t.typedName || '', t.reason || ''),
    killPort:   (port, t) => call('kill_port', port, t.tokenId || '',
                                  t.typedName || '', t.reason || ''),

    installServices:   (names, t) => call('install_services', names || [],
                                          t.tokenId || '', t.typedName || '',
                                          t.reason || ''),
    uninstallServices: (names, t) => call('uninstall_services', names || [],
                                          t.tokenId || '', t.typedName || '',
                                          t.reason || ''),

    configSavePorts:  (ports) => call('config_save_ports', ports || {}),
    configSavePaths:  (paths) => call('config_save_paths', paths || {}),
    configSaveValues: (vals)  => call('config_save_values', vals || {}),
    configReset:      (t) => call('config_reset', t.tokenId || '',
                                  t.typedName || '', t.reason || ''),

    runBackup:     (t) => call('run_backup', t.tokenId || '',
                               t.typedName || '', t.reason || ''),
    restoreBackup: (t) => call('restore_backup', t.tokenId || '',
                               t.typedName || '', t.reason || ''),

    /* -- 告警 -- */
    alertAck:     (key) => call('alert_ack', key),
    alertSilence: (key, seconds) => call('alert_silence', key, seconds || 0),

    /* -- 退出 -- */
    shutdown: () => call('shutdown')
  };

  /* ---------- 结果判定辅助 ---------- */
  /** 是否成功（兼容后端直接返回 ok 字段） */
  API.ok = (r) => !!(r && r.ok);
  /** 取失败原因（优先 reason，退化 detail，最后给个兜底） */
  API.why = (r) => {
    if (!r) return '无响应';
    return r.reason || r.detail || '未知原因';
  };
  /** 是否演示数据 */
  API.isMock = (r) => !!(r && r.__mock);

  window.API = API;
})();
