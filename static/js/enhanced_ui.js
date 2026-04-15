/**
 * Trae AI UI/UX 增强模块 (借鉴 Claude CLI 的 PermissionPrompt 交互设计)
 * 
 * 包含:
 *   1. KeyboardShortcutManager - 全局键盘快捷键系统 (Y/N/Esc/Tab)
 *   2. StatusIndicator - 工具执行状态实时指示器
 *   3. ToastNotification - 反馈通知系统
 *   4. InlineDiffViewer - 内联差异展示组件
 *   5. ProgressTracker - 细粒度进度追踪
 *   6. UndoManager - 操作撤销管理
 */

class KeyboardShortcutManager {
    constructor() {
        this.shortcuts = new Map();
        this.enabled = true;
        this.contextStack = [];
        this._init();
    }

    _init() {
        document.addEventListener('keydown', (e) => this._handleKeyDown(e));
    }

    register(key, handler, description = '', context = 'global') {
        const normalizedKey = key.toLowerCase().trim();
        if (!this.shortcuts.has(context)) {
            this.shortcuts.set(context, new Map());
        }
        this.shortcuts.get(context).set(normalizedKey, {
            handler,
            description,
            key
        });
    }

    unregister(key, context = 'global') {
        const ctxMap = this.shortcuts.get(context);
        if (ctxMap) {
            ctxMap.delete(key.toLowerCase().trim());
        }
    }

    pushContext(context) {
        this.contextStack.push(context);
    }

    popContext() {
        return this.contextStack.pop();
    }

    getCurrentContext() {
        return this.contextStack[this.contextStack.length - 1] || 'global';
    }

    enable() { this.enabled = true; }

    disable() { this.enabled = false; }

    _handleKeyDown(e) {
        if (!this.enabled) return;
        if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' 
            || e.target.tagName === 'SELECT' || e.target.isContentEditable) {
            if (e.key !== 'Escape') return;
        }

        let keyStr = '';
        if (e.ctrlKey || e.metaKey) keyStr += 'ctrl+';
        if (e.altKey) keyStr += 'alt+';
        if (e.shiftKey) keyStr += 'shift+';
        keyStr += e.key.toLowerCase();

        const currentContext = this.getCurrentContext();

        for (let i = this.contextStack.length - 1; i >= 0; i--) {
            const ctx = this.contextStack[i];
            const ctxMap = this.shortcuts.get(ctx);
            if (ctxMap && ctxMap.has(keyStr)) {
                e.preventDefault();
                const { handler } = ctxMap.get(keyStr);
                handler(e);
                return;
            }
        }

        const globalMap = this.shortcuts.get('global');
        if (globalMap && globalMap.has(keyStr)) {
            e.preventDefault();
            const { handler } = globalMap.get(keyStr);
            handler(e);
        }
    }

    getHelpText(context = null) {
        const targetContext = context || this.getCurrentContext();
        const lines = [`=== 快捷键帮助 (${targetContext}) ===`];
        
        const contextsToCheck = [...this.contextStack].reverse();
        if (!contextsToCheck.includes(targetContext)) {
            contextsToCheck.push(targetContext);
        }
        contextsToCheck.push('global');

        const seen = new Set();
        for (const ctx of contextsToCheck) {
            const ctxMap = this.shortcuts.get(ctx);
            if (ctxMap) {
                ctxMap.forEach((value, key) => {
                    if (!seen.has(key)) {
                        seen.add(key);
                        lines.push(`  ${key.padEnd(15)} → ${value.description}`);
                    }
                });
            }
        }
        return lines.join('\n');
    }
}

const keyboardManager = new KeyboardShortcutManager();

keyboardManager.register('escape', () => {
    document.querySelectorAll('.modal-overlay.active').forEach(m => m.classList.remove('active'));
}, '关闭弹窗/对话框');

keyboardManager.register('ctrl+s', (e) => {
    e.preventDefault();
    const saveBtn = document.querySelector('[data-action="save"]');
    if (saveBtn && !saveBtn.disabled) saveBtn.click();
}, '保存当前操作');

keyboardManager.register('ctrl+enter', () => {
    const submitBtn = document.querySelector('[data-action="submit"]');
    if (submitBtn && !submitBtn.disabled) submitBtn.click();
}, '提交表单');

keyboardManager.register('ctrl+f', (e) => {
    const searchInput = document.querySelector('.search-bar input, input[type="search"], #searchInput');
    if (searchInput) {
        e.preventDefault();
        searchInput.focus();
        searchInput.select();
    }
}, '聚焦搜索框');

keyboardManager.register('y', () => {
    const approveBtn = document.querySelector('[data-action="approve"], .btn-approve, [data-confirm="yes"]');
    if (approveBtn && document.querySelector('.modal-overlay.active')) {
        approveBtn.click();
    }
}, '确认/批准(Y)', 'permission');

keyboardManager.register('n', () => {
    const rejectBtn = document.querySelector('[data-action="reject"], .btn-reject, [data-confirm="no"]');
    if (rejectBtn && document.querySelector('.modal-overlay.active')) {
        rejectBtn.click();
    }
}, '拒绝(N)', 'permission');

keyboardManager.register('tab', (e) => {
    const activeModal = document.querySelector('.modal-overlay.active');
    if (activeModal) {
        const focusable = activeModal.querySelectorAll(
            'button:not([disabled]), input:not([disabled]), select:not([disabled])'
        );
        if (focusable.length > 0) {
            e.preventDefault();
            const currentIdx = Array.from(focusable).indexOf(document.activeElement);
            const nextIdx = (currentIdx + 1) % focusable.length;
            focusable[nextIdx].focus();
        }
    }
}, '切换焦点(Tab)', 'permission');

class StatusIndicator {
    constructor(containerId = 'status-indicator') {
        this.containerId = containerId;
        this.container = null;
        this.currentStatus = {};
        this._ensureContainer();
    }

    _ensureContainer() {
        this.container = document.getElementById(this.containerId);
        if (!this.container) {
            this.container = document.createElement('div');
            this.container.id = this.containerId;
            this.container.style.cssText = `
                position: fixed; bottom: 20px; right: 20px; z-index: 9999;
                display: flex; flex-direction: column; gap: 8px; max-width: 360px;
            `;
            document.body.appendChild(this.container);
        }
    }

    show(toolName, status, message = '', progress = null) {
        const id = `status-${toolName.replace(/[^a-zA-Z0-9]/g, '-')}`;
        let el = document.getElementById(id);

        const configs = {
            running: { icon: 'fa-spinner fa-spin', color: '#00d4aa', bg: 'rgba(0,212,170,0.1)' },
            success: { icon: 'fa-check-circle', color: '#00d4aa', bg: 'rgba(0,212,170,0.1)' },
            error: { icon: 'fa-times-circle', color: '#ff6b6b', bg: 'rgba(255,107,107,0.1)' },
            warning: { icon: 'fa-exclamation-triangle', color: '#ffd93d', bg: 'rgba(255,217,61,0.1)' },
            pending: { icon: 'fa-clock', color: '#8b9cb5', bg: 'rgba(139,156,181,0.1)' }
        };
        const config = configs[status] || configs.pending;

        if (!el) {
            el = document.createElement('div');
            el.id = id;
            el.style.cssText = `
                display: flex; align-items: center; gap: 10px;
                padding: 12px 16px; border-radius: 8px;
                background: var(--bg-card, #1a2332); border: 1px solid var(--border-color, #2d3e50);
                font-size: 13px; font-family: inherit;
                animation: slideInRight 0.3s ease;
                box-shadow: 0 4px 12px rgba(0,0,0,0.3);
            `;
            this.container.appendChild(el);
        }

        const progressBar = progress !== null ? `
            <div style="flex:1;height:4px;background:var(--bg-input,#242f3d);border-radius:2px;margin-top:4px;">
                <div style="width:${progress}%;height:100%;background:${config.color};border-radius:2px;transition:width 0.3s;"></div>
            </div>
        ` : '';

        el.innerHTML = `
            <i class="fas ${config.icon}" style="color:${config.color};font-size:14px;"></i>
            <div style="flex:1;min-width:0;">
                <div style="display:flex;justify-content:space-between;align-items:center;">
                    <span style="font-weight:600;color:var(--text-primary,#fff);">${toolName}</span>
                    <span style="font-size:11px;color:var(--text-secondary,#8b9cb5);">${status.toUpperCase()}</span>
                </div>
                ${message ? `<div style="color:var(--text-secondary,#8b9cb5);font-size:12px;margin-top:2px;">${message}</div>` : ''}
                ${progressBar}
            </div>
            <button onclick="document.getElementById('${id}').remove()" 
                    style="background:none;border:none;color:var(--text-secondary,#8b9cb5);cursor:pointer;font-size:16px;padding:2px;">
                &times;
            </button>
        `;

        this.currentStatus[toolName] = { status, message, progress };

        if (status === 'success' || status === 'error') {
            setTimeout(() => {
                if (el.parentNode) el.remove();
                delete this.currentStatus[toolName];
            }, status === 'success' ? 3000 : 8000);
        }

        return el;
    }

    update(toolName, updates) {
        const current = this.currentStatus[toolName];
        if (current) {
            this.show(toolName, updates.status || current.status, 
                       updates.message !== undefined ? updates.message : current.message,
                       updates.progress !== undefined ? updates.progress : current.progress);
        }
    }

    clear(toolName) {
        const el = document.getElementById(`status-${toolName.replace(/[^a-zA-Z0-9]/g, '-')}`);
        if (el) el.remove();
        delete this.currentStatus[toolName];
    }

    clearAll() {
        this.container.innerHTML = '';
        this.currentStatus = {};
    }
}

const statusIndicator = new StatusIndicator();

const toastStyles = document.createElement('style');
toastStyles.textContent = `
    @keyframes slideInRight { from { transform: translateX(100%); opacity: 0; } to { transform: translateX(0); opacity: 1; } }
    @keyframes slideOutRight { from { transform: translateX(0); opacity: 1; } to { transform: translateX(100%); opacity: 0; } }
    
    .toast-container {
        position: fixed; top: 24px; right: 24px; z-index: 10000;
        display: flex; flex-direction: column; gap: 10px; max-width: 400px;
        pointer-events: none;
    }
    
    .toast-notification {
        display: flex; align-items: flex-start; gap: 12px;
        padding: 14px 18px; border-radius: 10px;
        font-family: inherit; font-size: 13.5px; line-height: 1.5;
        box-shadow: 0 8px 30px rgba(0,0,0,0.35);
        animation: slideInRight 0.35s cubic-bezier(0.22, 1, 0.36, 1);
        pointer-events: auto; cursor: default;
        border-left: 4px solid;
    }
    
    .toast-success { background: linear-gradient(135deg, rgba(0,212,170,0.95), rgba(0,184,148,0.95)); border-color: #00b894; color: #0a1628; }
    .toast-error { background: linear-gradient(135deg, rgba(255,107,107,0.95), rgba(255,82,82,0.95)); border-color: #ff5252; color: #0a1628; }
    .toast-warning { background: linear-gradient(135deg, rgba(255,217,61,0.95), rgba(255,193,7,0.95)); border-color: #ffc107; color: #0a1628; }
    .toast-info { background: linear-gradient(135deg, rgba(52,152,219,0.95), rgba(41,128,185,0.95)); border-color: #2980b9; color: #fff; }
    
    .toast-icon { font-size: 18px; margin-top: 1px; flex-shrink: 0; }
    .toast-content { flex: 1; min-width: 0; }
    .toast-title { font-weight: 700; font-size: 14px; margin-bottom: 3px; }
    .toast-message { opacity: 0.9; word-break: break-word; }
    .toast-close { background: none; border: none; cursor: pointer; font-size: 18px; padding: 0 2px; opacity: 0.7; transition: opacity 0.2s; flex-shrink: 0; }
    .toast-close:hover { opacity: 1; }
    .toast-progress { height: 3px; border-radius: 2px; margin-top: 8px; overflow: hidden; background: rgba(255,255,255,0.3); }
    .toast-progress-bar { height: 100%; border-radius: 2px; background: rgba(255,255,255,0.8); transition: width linear; }
`;
document.head.appendChild(toastStyles);

class ToastNotification {
    constructor() {
        this.container = null;
        this.queue = [];
        this.maxVisible = 5;
        this.visibleCount = 0;
        this._ensureContainer();
    }

    _ensureContainer() {
        this.container = document.querySelector('.toast-container');
        if (!this.container) {
            this.container = document.createElement('div');
            this.container.className = 'toast-container';
            document.body.appendChild(this.container);
        }
    }

    show(message, type = 'success', title = '', duration = 4000, options = {}) {
        const icons = {
            success: 'fa-check-circle',
            error: 'fa-times-circle',
            warning: 'fa-exclamation-triangle',
            info: 'fa-info-circle'
        };

        const toast = document.createElement('div');
        toast.className = `toast-notification toast-${type}`;

        const progressDuration = duration > 0 ? duration + 300 : 0;

        toast.innerHTML = `
            <i class="fas ${icons[type] || icons.info} toast-icon"></i>
            <div class="toast-content">
                ${title ? `<div class="toast-title">${title}</div>` : ''}
                <div class="toast-message">${message}</div>
                ${duration > 0 ? `<div class="toast-progress"><div class="toast-progress-bar" style="width:100%;animation:shrink ${duration}ms linear forwards;"></div></div>` : ''}
            </div>
            <button class="toast-close" aria-label="关闭">&times;</button>
        `;

        const closeBtn = toast.querySelector('.toast-close');
        closeBtn.onclick = () => this._dismiss(toast);

        this.container.appendChild(toast);
        this.visibleCount++;

        if (duration > 0) {
            setTimeout(() => this._dismiss(toast), duration);
        }

        return toast;
    }

    _dismiss(toast) {
        if (!toast.parentNode) return;
        toast.style.animation = 'slideOutRight 0.3s ease forwards';
        setTimeout(() => {
            if (toast.parentNode) {
                toast.remove();
                this.visibleCount--;
            }
        }, 300);
    }

    success(message, title = '') { return this.show(message, 'success', title); }
    error(message, title = '') { return this.show(message, 'error', title, 6000); }
    warning(message, title = '') { return this.show(message, 'warning', title, 5000); }
    info(message, title = '') { return this.show(message, 'info', title); }
}

const toast = new ToastNotification();

function showToast(msg, type = 'success') {
    if (typeof window !== 'undefined' && window.toastNotification) {
        window.toastNotification.show(msg, type);
    } else {
        toast.show(msg, type);
    }
}

class InlineDiffViewer {
    static render(oldText, newText, container) {
        if (!container) return;

        const oldLines = oldText.split('\n');
        const newLines = newText.split('\n');

        const diffHtml = [];

        for (let i = 0; i < Math.max(oldLines.length, newLines.length); i++) {
            const oldLine = oldLines[i] ?? '';
            const newLine = newLines[i] ?? '';

            if (oldLine === newLine) {
                diffHtml.push(`<div style="padding:2px 8px;font-family:'Consolas','Monaco',monospace;font-size:12px;color:#8b9cb5;">
                    <span style="color:#555;width:30px;display:inline-block;text-align:right;margin-right:12px;">${i+1}</span>${this._escapeHtml(oldLine)}</div>`);
            } else if (i >= oldLines.length) {
                diffHtml.push(`<div style="padding:2px 8px;background:rgba(0,212,170,0.08);border-left:3px solid #00d4aa;font-family:'Consolas','Monaco',monospace;font-size:12px;">
                    <span style="color:#00d4aa;width:30px;display:inline-block;text-align:right;margin-right:12px;">+</span>+ ${this._escapeHtml(newLine)}</div>`);
            } else if (i >= newLines.length) {
                diffHtml.push(`<div style="padding:2px 8px;background:rgba(255,107,107,0.08);border-left:3px solid #ff6b6b;font-family:'Consolas','Monaco',monospace;font-size:12px;text-decoration:line-through;">
                    <span style="color:#ff6b6b;width:30px;display:inline-block;text-align:right;margin-right:12px;">-</span>- ${this._escapeHtml(oldLine)}</div>`);
            } else {
                diffHtml.push(`<div style="padding:2px 8px;background:rgba(255,107,107,0.05);border-left:3px solid #ff6b6b;font-family:'Consolas','Monaco',monospace;font-size:12px;text-decoration:line-through;">
                    <span style="color:#ff6b6b;width:30px;display:inline-block;text-align:right;margin-right:12px;">-</span>- ${this._escapeHtml(oldLine)}</div>`);
                diffHtml.push(`<div style="padding:2px 8px;background:rgba(0,212,170,0.05);border-left:3px solid #00d4aa;font-family:'Consolas','Monaco',monospace;font-size:12px;">
                    <span style="color:#00d4aa;width:30px;display:inline-block;text-align:right;margin-right:12px;">+</span>+ ${this._escapeHtml(newLine)}</div>`);
            }
        }

        container.innerHTML = `
            <style>
                .diff-header{display:flex;gap:16px;padding:10px 16px;background:var(--bg-input,#242f3d);border-bottom:1px solid var(--border-color,#2d3e50);font-size:12px;color:var(--text-secondary,#8b9cb5);}
                .diff-stats-add{color:#00d4aa;}
                .diff-stats-remove{color:#ff6b6b;}
            </style>
            <div class="diff-header">
                <span><span class="diff-stats-add">+${newLines.filter((l,i)=>l!==(oldLines[i]??'')).length}</span> 行新增</span>
                <span><span class="diff-stats-remove">-${oldLines.filter((l,i)=>l!==(newLines[i]??'')).length}</span> 行删除</span>
            </div>
            <div style="max-height:400px;overflow-y:auto;background:var(--bg-card,#1a2332);border:1px solid var(--border-color,#2d3e50);border-radius:8px;">
                ${diffHtml.join('')}
            </div>
        `;
    }

    static _escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
}

class UndoManager {
    constructor(maxHistory = 50) {
        this.undoStack = [];
        this.redoStack = [];
        this.maxHistory = maxHistory;
    }

    save(state, description = '') {
        this.undoStack.push({
            state: JSON.parse(JSON.stringify(state)),
            description,
            timestamp: Date.now()
        });
        if (this.undoStack.length > this.maxHistory) {
            this.undoStack.shift();
        }
        this.redoStack = [];
    }

    undo() {
        if (this.undoStack.length === 0) return null;
        const current = this.undoStack.pop();
        this.redoStack.push(current);
        return current.state;
    }

    redo() {
        if (this.redoStack.length === 0) return null;
        const current = this.redoStack.pop();
        this.undoStack.push(current);
        return current.state;
    }

    canUndo() { return this.undoStack.length > 0; }

    canRedo() { return this.redoStack.length > 0; }

    clear() {
        this.undoStack = [];
        this.redoStack = [];
    }

    getHistory() {
        return this.undoStack.map((item, idx) => ({
            index: idx,
            description: item.description,
            timestamp: new Date(item.timestamp).toLocaleTimeString()
        }));
    }
}

const undoManager = new UndoManager();

if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        KeyboardShortcutManager,
        keyboardManager,
        StatusIndicator,
        statusIndicator,
        ToastNotification,
        toast,
        showToast,
        InlineDiffViewer,
        UndoManager,
        undoManager
    };
} else {
    window.KeyboardShortcutManager = KeyboardShortcutManager;
    window.keyboardManager = keyboardManager;
    window.StatusIndicator = StatusIndicator;
    window.statusIndicator = statusIndicator;
    window.ToastNotification = ToastNotification;
    window.toast = toast;
    window.showToast = showToast;
    window.InlineDiffViewer = InlineDiffViewer;
    window.UndoManager = UndoManager;
    window.undoManager = undoManager;
}
