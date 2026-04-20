/**
 * 统一通知组件
 *
 * 整合 GlobalNotification、ToastNotification、showToast 为统一接口。
 * 所有页面应使用此组件替代各自的通知实现。
 *
 * 用法：
 *   GlobalNotification.success('操作成功');
 *   GlobalNotification.error('操作失败');
 *   showToast('提示信息', 'info');
 *
 * 兼容旧代码的全局接口：
 *   window.GlobalNotification — 兼容 base.html 中的原实现
 *   window.showToast          — 兼容各页面中的 showToast(message, type) 调用
 *   window.ToastNotification  — 兼容 enhanced_ui.js 中的原实现
 */
'use strict';

(function() {
    var NOTIFY_CONTAINER_ID = 'unified-notify-container';
    var NOTIFY_DURATION = 4000;
    var NOTIFY_MAX = 5;

    var TYPE_CONFIG = {
        success: { icon: 'fa-circle-check', bgClass: 'bg-success', textClass: 'text-white' },
        error:   { icon: 'fa-circle-xmark', bgClass: 'bg-danger', textClass: 'text-white' },
        warning: { icon: 'fa-triangle-exclamation', bgClass: 'bg-warning', textClass: 'text-dark' },
        info:    { icon: 'fa-circle-info', bgClass: 'bg-info', textClass: 'text-white' },
    };

    function _escapeHtml(str) {
        if (!str) return '';
        var div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    function _ensureContainer() {
        var container = document.getElementById(NOTIFY_CONTAINER_ID);
        if (!container) {
            container = document.createElement('div');
            container.id = NOTIFY_CONTAINER_ID;
            container.style.cssText = 'position:fixed;top:20px;right:20px;z-index:9999;max-width:400px;display:flex;flex-direction:column;gap:8px;';
            document.body.appendChild(container);
        }
        return container;
    }

    function _show(type, message, duration) {
        var container = _ensureContainer();
        var config = TYPE_CONFIG[type] || TYPE_CONFIG.info;

        // 去重：如果相同消息已在显示中，不重复创建
        var msgKey = type + ':' + message;
        for (var i = 0; i < container.children.length; i++) {
            if (container.children[i].getAttribute('data-notify-key') === msgKey) {
                return;
            }
        }

        // 限制最大数量
        while (container.children.length >= NOTIFY_MAX) {
            container.removeChild(container.firstChild);
        }

        var toast = document.createElement('div');
        toast.className = 'alert ' + config.bgClass + ' ' + config.textClass + ' d-flex align-items-center shadow-sm';
        toast.style.cssText = 'margin:0;padding:10px 16px;border-radius:6px;font-size:14px;opacity:0;transition:opacity 0.3s ease;';
        toast.setAttribute('data-notify-key', msgKey);
        toast.innerHTML = '<i class="fas ' + config.icon + ' me-2"></i><span>' + _escapeHtml(message) + '</span>';

        container.appendChild(toast);
        requestAnimationFrame(function() { toast.style.opacity = '1'; });

        var d = (duration !== undefined && duration !== null) ? duration : NOTIFY_DURATION;
        setTimeout(function() {
            toast.style.opacity = '0';
            setTimeout(function() {
                if (toast.parentNode) toast.parentNode.removeChild(toast);
            }, 300);
        }, d);
    }

    var notify = {
        success: function(msg, duration) { _show('success', msg, duration); },
        error:   function(msg, duration) { _show('error', msg, duration); },
        warning: function(msg, duration) { _show('warning', msg, duration); },
        info:    function(msg, duration) { _show('info', msg, duration); },

        // 兼容 GlobalNotification.show(type, message, title, duration) 调用
        show: function(type, message, _title, duration) {
            _show(type, message, duration);
        },

        // 兼容 GlobalNotification.close() — 统一系统用自动关闭，无需手动关闭
        close: function() {},

        // 兼容 GlobalNotification.init() — 容器按需创建，无需预初始化
        init: function() {}
    };

    // 挂载到全局
    window.GlobalNotification = notify;
    window.showToast = function(message, type) {
        var fn = notify[type || 'info'];
        if (typeof fn === 'function') {
            fn(message);
        } else {
            notify.info(message);
        }
    };
    window.ToastNotification = notify;
    // 兼容 showGlobalNotification(message, type) 调用方式
    window.showGlobalNotification = function(message, type) {
        var t = type || 'info';
        var fn = notify[t];
        if (typeof fn === 'function') {
            fn(message);
        } else {
            notify.info(message);
        }
    };
})();
