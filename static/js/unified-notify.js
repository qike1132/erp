/**
 * 统一通知组件
 *
 * 整合 GlobalNotification、ToastNotification、showToast 为统一接口。
 * 所有页面应使用此组件替代各自的通知实现。
 *
 * 用法：
 *   import { notify } from '/static/js/unified-notify.js';
 *   notify.success('操作成功');
 *   notify.error('操作失败');
 *   notify.warning('请注意');
 *   notify.info('提示信息');
 */
'use strict';

const NOTIFY_CONTAINER_ID = 'unified-notify-container';
const NOTIFY_DURATION = 4000; // ms
const NOTIFY_MAX = 5; // 同时最多显示条数

const TYPE_CONFIG = {
    success: { icon: 'fa-circle-check', bgClass: 'bg-success', textClass: 'text-white' },
    error:   { icon: 'fa-circle-xmark', bgClass: 'bg-danger', textClass: 'text-white' },
    warning: { icon: 'fa-triangle-exclamation', bgClass: 'bg-warning', textClass: 'text-dark' },
    info:    { icon: 'fa-circle-info', bgClass: 'bg-info', textClass: 'text-white' },
};

function _ensureContainer() {
    let container = document.getElementById(NOTIFY_CONTAINER_ID);
    if (!container) {
        container = document.createElement('div');
        container.id = NOTIFY_CONTAINER_ID;
        container.style.cssText = 'position:fixed;top:20px;right:20px;z-index:9999;max-width:400px;display:flex;flex-direction:column;gap:8px;';
        document.body.appendChild(container);
    }
    return container;
}

function _show(type, message, duration = NOTIFY_DURATION) {
    const container = _ensureContainer();
    const config = TYPE_CONFIG[type] || TYPE_CONFIG.info;

    // 限制最大数量
    while (container.children.length >= NOTIFY_MAX) {
        container.removeChild(container.firstChild);
    }

    const toast = document.createElement('div');
    toast.className = `alert ${config.bgClass} ${config.textClass} d-flex align-items-center shadow-sm`;
    toast.style.cssText = 'margin:0;padding:10px 16px;border-radius:6px;font-size:14px;opacity:0;transition:opacity 0.3s ease;';
    toast.innerHTML = `<i class="fas ${config.icon} me-2"></i><span>${escapeHtml(message)}</span>`;

    container.appendChild(toast);
    requestAnimationFrame(() => { toast.style.opacity = '1'; });

    setTimeout(() => {
        toast.style.opacity = '0';
        setTimeout(() => {
            if (toast.parentNode) toast.parentNode.removeChild(toast);
        }, 300);
    }, duration);
}

function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

export const notify = {
    success: (msg, duration) => _show('success', msg, duration),
    error:   (msg, duration) => _show('error', msg, duration),
    warning: (msg, duration) => _show('warning', msg, duration),
    info:    (msg, duration) => _show('info', msg, duration),
};

// 兼容旧代码：挂载到全局
if (typeof window !== 'undefined') {
    window.GlobalNotification = notify;
    window.showToast = notify;
    window.ToastNotification = notify;
}
