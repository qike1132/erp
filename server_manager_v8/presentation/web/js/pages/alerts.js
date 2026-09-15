/* ============================================================
   监控告警页 —— 症状化规则 / 事件聚合 / 抑制静默

   后端对接：
     alert_list    → API.alertList()
     alert_ack     → API.alertAck(key)
     alert_silence → API.alertSilence(key, seconds)

   ★ 未接入的两项（如实标注，不假装能用）：
     · rules（告警规则编辑）—— 后端无规则增删用例
     · export_alerts（导出）—— 后端无导出接口
   ============================================================ */
(function () {
  'use strict';

  /** 后端严重度 → 原型使用的 kind */
  const SEV_KIND = { P0: 'err', P1: 'err', P2: 'warn', P3: 'warn', info: '' };

  function kindOf(severity) { return SEV_KIND[severity] || ''; }

  /** 秒 → 人类可读（用于静默剩余时间） */
  function humanSec(s) {
    if (s == null) return '—';
    if (s < 60) return Math.round(s) + ' 秒';
    if (s < 3600) return Math.round(s / 60) + ' 分钟';
    return (s / 3600).toFixed(1) + ' 小时';
  }

  const Page = {
    name: 'alerts',

    /** 拉取并渲染告警列表 */
    async load() {
      const r = await API.alertList(false);
      if (!API.ok(r)) {
        toast('err', '告警加载失败', API.why(r));
        return;
      }
      const list = (r.alerts || []);
      const host = document.getElementById('alertList');
      if (host) host.innerHTML = renderList(list);
      if (API.isMock(r)) showDemoBanner();
      return list;
    },

    ops: {
      /** 确认告警（L0，无需额外确认） */
      async ack(btn) {
        const key = btn && btn.dataset.alertKey;
        if (!key) return { ok: false, reason: '缺少告警标识' };
        const r = await API.alertAck(key);
        if (API.ok(r)) await Page.load();
        return r;
      },

      /** 静默告警（L1，会让系统停止提醒真实故障） */
      async silence(btn) {
        const key = btn && btn.dataset.alertKey;
        if (!key) return { ok: false, reason: '缺少告警标识' };
        const seconds = Number((btn && btn.dataset.silenceSec) || 900);
        const r = await API.alertSilence(key, seconds);
        if (API.ok(r)) await Page.load();
        return r;
      },

      async refresh() { return Page.load(); },

      /* -- 未接入 -- */
      async rules() {
        return { ok: false, reason: '未接入',
                 detail: 'v8 后端暂无告警规则编辑用例' };
      },
      async export_alerts() {
        return { ok: false, reason: '未接入',
                 detail: 'v8 后端暂无导出接口' };
      },
      async fix_redis() {
        return { ok: false, reason: '未接入',
                 detail: 'Redis 自动修复尚需服务规格（P4 后续接入）' };
      }
    }
  };

  /* ---------- 渲染 ---------- */
  function renderList(list) {
    if (!list.length) {
      return '<div class="empty">当前无活动告警</div>';
    }
    return list.map(a => {
      const kind = kindOf(a.severity);
      const silenced = a.silenced_until != null;
      const badge = a.is_acked
        ? '<span class="badge b-ok">已确认</span>'
        : (silenced ? '<span class="badge b-idle">已静默</span>' : '');
      return `
        <div class="alert-row" data-alert-key="${esc(a.key)}">
          <span class="dot ${kind}"></span>
          <div class="ar-main">
            <div class="ar-t">${esc(a.title || a.key)}</div>
            ${a.body ? `<div class="ar-b">${esc(a.body)}</div>` : ''}
          </div>
          <div class="ar-meta">
            <span class="badge">${esc(a.severity || '')}</span>${badge}
          </div>
          <div class="ar-ops">
            <button class="btn sm" data-op="ack"
                    data-alert-key="${esc(a.key)}">确认</button>
            <button class="btn sm" data-op="silence"
                    data-alert-key="${esc(a.key)}"
                    data-silence-sec="900">静默 15 分钟</button>
          </div>
        </div>`;
    }).join('');
  }

  function showDemoBanner() {
    if (document.getElementById('demoBanner')) return;
    const el = document.createElement('div');
    el.id = 'demoBanner';
    el.className = 'demo-banner';
    el.textContent = '演示数据：未连接后端';
    const page = document.getElementById('page-alerts');
    if (page) page.insertBefore(el, page.firstChild);
  }

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  window.Pages = window.Pages || {};
  window.Pages.alerts = Page;
})();
