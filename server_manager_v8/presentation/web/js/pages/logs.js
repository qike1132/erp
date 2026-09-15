/* ============================================================
   日志中心 —— 多源分流 / 关键字规则 / 虚拟滚动

   后端对接：
     logs         → API.logs({limit})
     verify_chain → API.verifyChain()   （哈希链完整性校验）

   ★ 关于「清空日志」：
     后端**没有**提供 clear_log 用例，且这是有意的设计 ——
     v8 的审计日志是 append-only 哈希链，清空会直接破坏链条，
     使「是否被篡改过」这个问题再也答不上来。
     所以这里如实返回「未接入」，而不是给一个能点但无效的按钮。

   ★ 日志的 `ts_s` 是 monotonic 秒（不是墙钟时间），
     前端**不能**拿它去 `new Date()` —— 那样会得到 1970 年。
     展示时只标相对时间或原样显示秒数。
   ============================================================ */
(function () {
  'use strict';

  const DEFAULT_LIMIT = 200;

  const Page = {
    name: 'logs',
    lastEntries: [],

    async load() {
      const r = await API.logs({ limit: DEFAULT_LIMIT });
      if (!API.ok(r)) {
        toast('err', '日志加载失败', API.why(r));
        return;
      }
      Page.lastEntries = r.entries || [];
      render(Page.lastEntries, r.truncated);
      if (API.isMock(r)) showDemoBanner();
      return Page.lastEntries;
    },

    ops: {
      async refresh() { return Page.load(); },

      /** 哈希链校验 —— 有真实后端能力 */
      async verify_chain() {
        const r = await API.verifyChain();
        if (!API.ok(r)) return r;
        // ★ 链断裂时 ok 仍为 true（校验**完成**了，只是发现问题）
        //   这与「校验失败请重试」是完全不同的含义，不能混为一谈
        if (r.intact) {
          toast('ok', '哈希链校验通过',
                `${r.total || 0} 条记录，未检出篡改`);
        } else {
          toast('err', '哈希链已断裂',
                `位置 ${r.broken_at ?? '—'}：${r.detail || '记录被修改过'}`);
        }
        return r;
      },

      /* -- 未接入（有意不提供，见文件头说明）-- */
      async clear_log() {
        return { ok: false, reason: '不支持',
                 detail: '审计日志为 append-only 哈希链，清空会破坏链条' };
      },
      async kw_rules() {
        return { ok: false, reason: '未接入',
                 detail: 'v8 后端暂无关键字规则用例' };
      },
      async export_log() {
        return { ok: false, reason: '未接入',
                 detail: 'v8 后端暂无导出接口' };
      }
    }
  };

  /* ---------- 渲染 ---------- */
  function render(entries, truncated) {
    const host = document.getElementById('logBody');
    if (!host) return;
    if (!entries.length) {
      host.innerHTML = '<div class="empty">暂无日志记录</div>';
      return;
    }
    const rows = entries.map(e => `
      <tr>
        <td class="c-ts">${esc(fmtTs(e.ts_s))}</td>
        <td class="c-act">${esc(e.action || '')}</td>
        <td class="c-who">${esc(e.actor || '')}</td>
        <td class="c-tgt">${esc(e.target || '')}</td>
        <td class="c-out ${outClass(e.outcome)}">${esc(e.outcome || '')}</td>
        <td class="c-det">${esc(e.detail || '')}</td>
      </tr>`).join('');
    const more = truncated
      ? '<div class="log-more">结果已截断，仅显示最近记录</div>' : '';
    host.innerHTML = `<table class="log-table"><tbody>${rows}</tbody></table>${more}`;
  }

  /** monotonic 秒 → 只显示秒数（不伪装成日期） */
  function fmtTs(s) {
    if (s == null || s === '') return '—';
    return (typeof s === 'number' ? s.toFixed(3) : String(s)) + 's';
  }

  function outClass(outcome) {
    if (outcome === 'ok') return 'o-ok';
    if (outcome === 'denied') return 'o-deny';
    if (outcome === 'failed') return 'o-fail';
    return '';
  }

  function showDemoBanner() {
    if (document.getElementById('demoBannerLogs')) return;
    const el = document.createElement('div');
    el.id = 'demoBannerLogs';
    el.className = 'demo-banner';
    el.textContent = '演示数据：未连接后端';
    const page = document.getElementById('page-logs');
    if (page) page.insertBefore(el, page.firstChild);
  }

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  window.Pages = window.Pages || {};
  window.Pages.logs = Page;
})();
