/**
 * 统一 API 客户端
 *
 * 封装 fetch + CSRF + 错误处理 + 重试逻辑，替代各页面分散的 fetch 调用。
 * 用法：
 *   import api from '/static/js/api-client.js';
 *   const data = await api.get('/api/v1/stock/ins');
 *   const result = await api.post('/api/v1/stock/ins/create', { product_id: 1, quantity: 100 });
 *
 * 新增功能：
 * - 登录状态实时检测
 * - 未登录友好提示界面
 * - 登录后自动重试失败请求
 * - 请求队列管理
 * - 错误日志记录
 */
'use strict';

const API_BASE = '/api/v1';

class ApiClient {
    constructor(baseURL = API_BASE) {
        this.baseURL = baseURL;
        this._retryCount = 2;
        this._retryDelay = 1000; // ms
        this._pendingRequests = []; // 待重试的请求队列
        this._loginModal = null;
        this._isShowingLoginModal = false;
        this._loginCheckInterval = null;
        this._initLoginStatusCheck();
    }

    /**
     * 获取 CSRF Token（从 meta 标签或 cookie）
     */
    _getCSRFToken() {
        const meta = document.querySelector('meta[name="csrf-token"]');
        if (meta) return meta.getAttribute('content');
        // 降级：从 cookie 读取
        const match = document.cookie.match(/csrf_token=([^;]+)/);
        return match ? match[1] : '';
    }

    /**
     * 构建请求头
     */
    _buildHeaders(hasBody = false) {
        const headers = {};
        if (hasBody) {
            headers['Content-Type'] = 'application/json';
        }
        const csrf = this._getCSRFToken();
        if (csrf) {
            headers['X-CSRFToken'] = csrf;
        }
        return headers;
    }

    /**
     * 初始化登录状态检查（已禁用：登录永不过期）
     */
    _initLoginStatusCheck() {
        // 不再定时检查登录过期
    }

    /**
     * 检查登录状态
     */
    async _checkLoginStatus() {
        try {
            const response = await fetch('/api/v1/auth/check', {
                method: 'GET',
                credentials: 'same-origin',
                headers: this._buildHeaders()
            });
            if (response.status === 401) {
                this._handleUnauthorized();
            }
        } catch (err) {
            console.warn('[ApiClient] 登录状态检查失败:', err);
        }
    }

    /**
     * 记录错误日志
     */
    _logError(error, context = {}) {
        const logData = {
            timestamp: new Date().toISOString(),
            error: error.message,
            stack: error.stack,
            context: context,
            url: window.location.href,
            userAgent: navigator.userAgent
        };
        
        console.error('[ApiClient] 错误日志:', logData);
        
        // 尝试发送到后端（可选）
        try {
            fetch('/api/v1/logs/frontend-error', {
                method: 'POST',
                credentials: 'same-origin',
                headers: this._buildHeaders(true),
                body: JSON.stringify(logData)
            }).catch(() => {
                // 静默失败，避免循环错误
            });
        } catch (e) {
            // 静默失败
        }
    }

    /**
     * 创建或获取登录提示模态框
     */
    _getLoginModal() {
        if (this._loginModal) {
            return this._loginModal;
        }

        // 创建模态框HTML
        const modalHtml = `
            <div id="api-client-login-modal" class="modal fade" tabindex="-1" data-bs-backdrop="static" data-bs-keyboard="false">
                <div class="modal-dialog modal-dialog-centered">
                    <div class="modal-content">
                        <div class="modal-header" style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white;">
                            <h5 class="modal-title">
                                <i class="fas fa-user-lock me-2"></i>未登录
                            </h5>
                        </div>
                        <div class="modal-body text-center py-4">
                            <div class="mb-4">
                                <i class="fas fa-clock fa-4x text-warning"></i>
                            </div>
                            <h5 class="mb-2">您尚未登录</h5>
                            <p class="text-muted mb-4">为了继续使用系统功能，请先登录</p>
                            <div class="d-grid gap-2">
                                <button id="api-client-login-btn" class="btn btn-primary btn-lg">
                                    <i class="fas fa-sign-in-alt me-2"></i>立即登录
                                </button>
                                <button id="api-client-cancel-btn" class="btn btn-outline-secondary">
                                    取消
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        `;

        // 添加到DOM
        const div = document.createElement('div');
        div.innerHTML = modalHtml;
        document.body.appendChild(div.firstElementChild);

        // 初始化Bootstrap模态框
        this._loginModal = new bootstrap.Modal(document.getElementById('api-client-login-modal'));

        // 绑定事件
        document.getElementById('api-client-login-btn').addEventListener('click', () => {
            this._loginModal.hide();
            this._isShowingLoginModal = false;
            window.location.href = '/login';
        });

        document.getElementById('api-client-cancel-btn').addEventListener('click', () => {
            this._loginModal.hide();
            this._isShowingLoginModal = false;
            this._clearPendingRequests();
        });

        return this._loginModal;
    }

    /**
     * 处理401未授权错误
     */
    _handleUnauthorized(requestInfo = null) {
        // 记录错误
        this._logError(new Error('未登录'), {
            type: 'unauthorized',
            requestInfo: requestInfo
        });

        // 如果已经在显示登录模态框，将请求加入队列
        if (this._isShowingLoginModal) {
            if (requestInfo) {
                this._pendingRequests.push(requestInfo);
            }
            return;
        }

        this._isShowingLoginModal = true;

        // 显示友好提示
        if (typeof GlobalNotification !== 'undefined') {
            GlobalNotification.warning('未登录，请先登录', '提示', 5000);
        }

        // 显示登录模态框
        const modal = this._getLoginModal();
        modal.show();

        // 监听模态框隐藏事件
        const modalElement = document.getElementById('api-client-login-modal');
        modalElement.addEventListener('hidden.bs.modal', () => {
            this._isShowingLoginModal = false;
        }, { once: true });
    }

    /**
     * 添加待重试请求到队列
     */
    _addPendingRequest(requestInfo) {
        this._pendingRequests.push(requestInfo);
    }

    /**
     * 清空待重试请求队列
     */
    _clearPendingRequests() {
        this._pendingRequests = [];
    }

    /**
     * 重试所有待处理的请求
     */
    async _retryPendingRequests() {
        const requests = [...this._pendingRequests];
        this._pendingRequests = [];
        
        for (const requestInfo of requests) {
            try {
                await this._request(
                    requestInfo.method,
                    requestInfo.path,
                    requestInfo.data,
                    requestInfo.options,
                    true // 跳过未授权处理，避免循环
                );
            } catch (err) {
                console.error(`[ApiClient] 请求重试失败: ${requestInfo.method} ${requestInfo.path}`, err);
            }
        }
    }

    /**
     * 统一请求方法
     */
    async _request(method, path, data = null, options = {}, skipUnauthorizedHandle = false) {
        const url = path.startsWith('http') ? path : `${this.baseURL}${path}`;
        const hasBody = data !== null && method !== 'GET';
        const config = {
            method,
            headers: this._buildHeaders(hasBody),
            credentials: 'same-origin', // 自动携带 cookie
        };

        if (hasBody) {
            config.body = JSON.stringify(data);
        }

        const requestInfo = { method, path, data, options };
        let lastError = null;
        
        for (let attempt = 0; attempt <= this._retryCount; attempt++) {
            try {
                const response = await fetch(url, config);

                // 401 未认证处理
                if (response.status === 401) {
                    if (!skipUnauthorizedHandle) {
                        this._addPendingRequest(requestInfo);
                        this._handleUnauthorized(requestInfo);
                    }
                    const errMsg = '未登录';
                    throw new Error(errMsg);
                }

                // 解析 JSON
                const result = await response.json();

                if (!response.ok) {
                    const errMsg = result.detail || result.error || `请求失败 (${response.status})`;
                    throw new Error(errMsg);
                }

                return result;
            } catch (err) {
                lastError = err;
                
                // 记录错误
                this._logError(err, {
                    method,
                    path,
                    attempt: attempt + 1,
                    maxAttempts: this._retryCount + 1
                });
                
                // 仅对网络错误和服务端 5xx 重试
                const isRetryable = err.message.includes('Failed to fetch') ||
                                    err.message.includes('500') ||
                                    err.message.includes('502') ||
                                    err.message.includes('503');
                                    
                if (!isRetryable || attempt === this._retryCount) {
                    break;
                }
                
                // 等待后重试
                await new Promise(r => setTimeout(r, this._retryDelay * (attempt + 1)));
            }
        }

        // 通知用户
        if (typeof GlobalNotification !== 'undefined' && !skipUnauthorizedHandle) {
            GlobalNotification.error(lastError.message || '网络请求失败');
        }
        throw lastError;
    }

    async get(path, params = null) {
        let url = path;
        if (params) {
            const qs = new URLSearchParams(params).toString();
            url += (url.includes('?') ? '&' : '?') + qs;
        }
        return this._request('GET', url);
    }

    async post(path, data) {
        return this._request('POST', path, data);
    }

    async put(path, data) {
        return this._request('PUT', path, data);
    }

    async delete(path) {
        return this._request('DELETE', path);
    }

    /**
     * 手动触发登录状态检查
     */
    async checkLoginStatus() {
        await this._checkLoginStatus();
    }

    /**
     * 清理资源
     */
    destroy() {
        if (this._loginCheckInterval) {
            clearInterval(this._loginCheckInterval);
        }
        if (this._loginSuccessListener) {
            window.removeEventListener('loginSuccess', this._loginSuccessListener);
        }
        this._clearPendingRequests();
    }
}

// 单例导出（IIFE 模式，兼容普通 script 标签加载）
(function() {
    const api = new ApiClient();
    window.ApiClient = ApiClient;
    window.api = api;

    // 监听登录成功事件（如果登录页有这个事件）
    api._loginSuccessListener = () => {
        api._retryPendingRequests();
    };
    window.addEventListener('loginSuccess', api._loginSuccessListener);
})();
