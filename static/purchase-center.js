const API_BASE = '/api/v1/purchase-center';
const FASTAPI_BASE = '/api/v1/purchase-center';
let confirmCallback = null;
let orderCurrentPage = 1;
let orderSelectedIds = new Set();
let historyCurrentPage = 1;
let savedQueriesVisible = false;

// 自动刷新机制
let autoRefreshInterval = null;
let lastOrderCount = 0;
let isAutoRefreshEnabled = true;
let isPageVisible = true;

document.addEventListener('visibilitychange', () => {
    isPageVisible = !document.hidden;
    if (isPageVisible && isAutoRefreshEnabled) {
        startAutoRefresh();
    } else {
        if (autoRefreshInterval) {
            clearInterval(autoRefreshInterval);
            autoRefreshInterval = null;
        }
    }
});

async function loadOrdersSilently(page = 1) {
    const params = new URLSearchParams({page, per_page: 15});
    const res = await apiGet(`/orders?${params}`);
    if (res.success) {
        lastOrderCount = res.total;
        document.getElementById('orderTotalBadge').textContent = `${res.total} 个订单`;
        const list = document.getElementById('orderList');

        if (res.orders.length === 0) {
            list.innerHTML = '<div class="pc-empty-state"><i class="fas fa-inbox"></i><p>暂无采购订单</p></div>';
        } else {
            // 保持选中状态
            list.innerHTML = `
                <div style="margin-bottom:12px;padding:12px 16px;background:var(--pc-primary-lighter);border-radius:var(--pc-radius-md);display:flex;align-items:center;gap:12px;flex-wrap:wrap;">
                    <label style="display:flex;align-items:center;gap:6px;cursor:pointer;font-size:13px;font-weight:500;color:var(--pc-primary-dark);">
                        <input type="checkbox" id="selectAllPurchaseOrders" onchange="toggleSelectAllPurchaseOrders(this.checked)" style="width:18px;height:18px;accent-color:var(--pc-primary);cursor:pointer;">
                        <span>全选</span>
                    </label>
                    <span style="font-size:12px;color:var(--pc-text-secondary);">已选择 <strong id="selectedPurchaseCount" style="color:var(--pc-primary);">0</strong> 个订单</span>
                </div>
                <table class="pc-table" style="width:100%;border-collapse:collapse;margin-top:12px;font-family:'Microsoft YaHei','Segoe UI',sans-serif;">
                    <thead>
                        <tr style="background:var(--pc-primary-lighter);">
                            <th style="padding:12px 8px;text-align:center;font-size:14px;font-weight:600;color:var(--plush-text);width:40px;"><input type="checkbox" id="selectAllPurchaseOrdersHeader" onchange="toggleSelectAllPurchaseOrders(this.checked)" style="width:16px;height:16px;accent-color:var(--pc-primary);cursor:pointer;"></th>
                            <th style="padding:12px 8px;text-align:left;font-size:14px;font-weight:600;color:var(--plush-text);width:14%;">下单时间</th>
                            <th style="padding:12px 8px;text-align:left;font-size:14px;font-weight:600;color:var(--plush-text);width:14%;">订单号</th>
                            <th style="padding:12px 8px;text-align:left;font-size:14px;font-weight:600;color:var(--plush-text);width:12%;">客户名称</th>
                            <th style="padding:12px 8px;text-align:left;font-size:14px;font-weight:600;color:var(--plush-text);width:34%;">产品名称</th>
                            <th style="padding:12px 8px;text-align:right;font-size:14px;font-weight:600;color:var(--plush-text);width:10%;white-space:nowrap;">订单数量</th>
                            <th style="padding:12px 8px;text-align:center;font-size:14px;font-weight:600;color:var(--plush-text);width:auto;">操作</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${res.orders.map(o => `
                            <tr class="pc-purchase-row ${orderSelectedIds.has(o.id) ? 'selected' : ''}" data-order-id="${o.id}" onclick="togglePurchaseOrderSelection(${o.id}, event)" style="border-bottom:1px solid var(--pc-border);cursor:pointer;transition:background 0.2s;">
                                <td style="padding:12px 8px;text-align:center;">
                                    <input type="checkbox" ${orderSelectedIds.has(o.id) ? 'checked' : ''} onclick="event.stopPropagation();togglePurchaseOrderSelection(${o.id}, event)" style="width:16px;height:16px;accent-color:var(--pc-primary);cursor:pointer;">
                                </td>
                                <td style="padding:12px 8px;font-family:'Microsoft YaHei','Segoe UI',sans-serif;font-size:14px;font-weight:600;color:var(--plush-text);">${escapeHtml(o.order_date || '')}</td>
                                <td style="padding:12px 8px;font-family:'Microsoft YaHei','Segoe UI',sans-serif;font-size:14px;font-weight:600;color:var(--plush-text);">${escapeHtml(o.order_no)}</td>
                                <td style="padding:12px 8px;font-family:'Microsoft YaHei','Segoe UI',sans-serif;font-size:14px;font-weight:600;color:var(--plush-text);">${escapeHtml(o.customer_name || '-')}</td>
                                <td style="padding:12px 8px;font-family:'Microsoft YaHei','Segoe UI',sans-serif;font-size:14px;font-weight:600;color:var(--plush-text);">${escapeHtml(o.product_name || '-')}</td>
                                <td style="padding:12px 8px;font-family:'Microsoft YaHei','Segoe UI',sans-serif;font-size:14px;font-weight:600;color:var(--plush-text);text-align:right;white-space:nowrap;">${o.quantity ? o.quantity.toLocaleString() : '-'}</td>
                                <td style="padding:12px 8px;text-align:center;">
                                    <button class="pc-btn pc-btn-success pc-btn-sm" onclick="event.stopPropagation();completeOrder(${o.id})"><i class="fas fa-check"></i> 下单完成</button>
                                </td>
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
            `;
        }
        updateBatchButtons();
    }
}

function showConfirm(text, sub, type='danger') {
    return new Promise(resolve => {
        confirmCallback = resolve;
        document.getElementById('confirmText').textContent = text;
        document.getElementById('confirmSub').textContent = sub || '';
        const icon = document.getElementById('confirmIcon');
        icon.className = `pc-confirm-icon ${type}`;
        icon.innerHTML = type === 'danger' ? '<i class="fas fa-trash-alt"></i>' : '<i class="fas fa-exclamation-triangle"></i>';
        document.getElementById('confirmModal').classList.add('show');
    });
}

function closeConfirm(confirmed) {
    document.getElementById('confirmModal').classList.remove('show');
    if (confirmCallback) { confirmCallback(confirmed); confirmCallback = null; }
}

function closeModal(id) { document.getElementById(id).classList.remove('show'); }

let historyPanelInitialized = false;

function switchTab(tab) {
    document.querySelectorAll('.pc-tab').forEach(t => t.classList.remove('active'));
    const tabBtn = document.querySelector(`.pc-tab[data-tab="${tab}"]`);
    if (tabBtn) tabBtn.classList.add('active');
    document.querySelectorAll('.pc-panel').forEach(p => p.classList.remove('active'));
    const panel = document.getElementById(`panel-${tab}`);
    if (panel) panel.classList.add('active');

    if (tab === 'orders') {
        loadUnprocessedOrders();
        loadOrders();
    } else if (tab === 'history') {
        if (!historyPanelInitialized) {
            initHistoryPanel();
            historyPanelInitialized = true;
        } else {
            loadCompletedOrders(1);
        }
    }
}

function _handleAuthError(status) {
    if (status === 401) {
        showToast('未登录，请先登录', 'error');
        setTimeout(() => { window.location.href = '/login'; }, 1500);
        return true;
    }
    return false;
}

async function apiGet(url) {
    try {
        const r = await fetch(API_BASE + url, {credentials: 'same-origin'});
        if (_handleAuthError(r.status)) return {success:false, message:'未登录'};
        if (!r.ok) {
            return {success:false, message: `请求失败: ${r.status} ${r.statusText}`};
        }
        const contentType = r.headers.get('content-type');
        if (!contentType || !contentType.includes('application/json')) {
            return {success:false, message: '服务器响应格式错误'};
        }
        return await r.json();
    } catch(e) {
        return {success:false, message:e.message};
    }
}

async function apiPost(url, data) {
    try {
        const r = await fetch(API_BASE + url, {
            method:'POST',
            headers:{'Content-Type':'application/json'},
            credentials: 'same-origin',
            body: JSON.stringify(data)
        });
        if (_handleAuthError(r.status)) return {success:false, message:'未登录'};
        if (!r.ok) {
            return {success:false, message: `请求失败: ${r.status} ${r.statusText}`};
        }
        const contentType = r.headers.get('content-type');
        if (!contentType || !contentType.includes('application/json')) {
            return {success:false, message: '服务器响应格式错误'};
        }
        return await r.json();
    } catch(e) { return {success:false,message:e.message}; }
}

async function apiPut(url, data) {
    try {
        const r = await fetch(API_BASE + url, {
            method:'PUT',
            headers:{'Content-Type':'application/json'},
            credentials: 'same-origin',
            body: JSON.stringify(data)
        });
        if (_handleAuthError(r.status)) return {success:false, message:'未登录'};
        if (!r.ok) {
            return {success:false, message: `请求失败: ${r.status} ${r.statusText}`};
        }
        const contentType = r.headers.get('content-type');
        if (!contentType || !contentType.includes('application/json')) {
            return {success:false, message: '服务器响应格式错误'};
        }
        return await r.json();
    } catch(e) { return {success:false,message:e.message}; }
}

async function apiDelete(url) {
    try {
        const r = await fetch(API_BASE + url, {method:'DELETE'});
        if (!r.ok) {
            return {success:false, message: `请求失败: ${r.status} ${r.statusText}`};
        }
        const contentType = r.headers.get('content-type');
        if (!contentType || !contentType.includes('application/json')) {
            return {success:false, message: '服务器响应格式错误'};
        }
        return await r.json();
    } catch(e) { console.error(e); return {success:false,message:e.message}; }
}

function getStatusBadge(status) {
    if (!status) return '';
    const map = {
        pending: ['待处理','pc-badge-pending'],
        completed: ['已完成','pc-badge-completed'],
        cancelled: ['已取消','pc-badge-cancelled'],
        unprocessed: ['未处理','pc-badge-unprocessed'],
        processing: ['处理中','pc-badge-processing'],
        processed: ['已处理','pc-badge-completed'],
        ignored: ['已忽略','pc-badge-cancelled'],
    };
    const [label, cls] = map[status] || [status, 'pc-badge-pending'];
    return `<span class="pc-badge ${cls}">${escapeHtml(label)}</span>`;
}

function formatDateTime(dt) {
    if (!dt) return '-';
    return dt;
}

// ============ Orders ============
async function loadOrders(page=1) {
    orderCurrentPage = page;
    const params = new URLSearchParams({page, per_page: 15});

    const res = await apiGet(`/orders?${params}`);
    if (res.success) {
        document.getElementById('orderTotalBadge').textContent = `${res.total} 个订单`;
        const list = document.getElementById('orderList');

        if (res.orders.length === 0) {
            list.innerHTML = '<div class="pc-empty-state"><i class="fas fa-inbox"></i><p>暂无采购订单</p></div>';
        } else {
            list.innerHTML = `
                <div style="margin-bottom:12px;padding:12px 16px;background:var(--pc-primary-lighter);border-radius:var(--pc-radius-md);display:flex;align-items:center;gap:12px;flex-wrap:wrap;">
                    <label style="display:flex;align-items:center;gap:6px;cursor:pointer;font-size:13px;font-weight:500;color:var(--pc-primary-dark);">
                        <input type="checkbox" id="selectAllPurchaseOrders" onchange="toggleSelectAllPurchaseOrders(this.checked)" style="width:18px;height:18px;accent-color:var(--pc-primary);cursor:pointer;">
                        <span>全选</span>
                    </label>
                    <span style="font-size:12px;color:var(--pc-text-secondary);">已选择 <strong id="selectedPurchaseCount" style="color:var(--pc-primary);">0</strong> 个订单</span>
                </div>
                <table class="pc-table" style="width:100%;border-collapse:collapse;margin-top:12px;font-family:'Microsoft YaHei','Segoe UI',sans-serif;">
                    <thead>
                        <tr style="background:var(--pc-primary-lighter);">
                            <th style="padding:12px 8px;text-align:center;font-size:14px;font-weight:600;color:var(--plush-text);width:40px;"><input type="checkbox" id="selectAllPurchaseOrdersHeader" onchange="toggleSelectAllPurchaseOrders(this.checked)" style="width:16px;height:16px;accent-color:var(--pc-primary);cursor:pointer;"></th>
                            <th style="padding:12px 8px;text-align:left;font-size:14px;font-weight:600;color:var(--plush-text);width:14%;">下单时间</th>
                            <th style="padding:12px 8px;text-align:left;font-size:14px;font-weight:600;color:var(--plush-text);width:14%;">订单号</th>
                            <th style="padding:12px 8px;text-align:left;font-size:14px;font-weight:600;color:var(--plush-text);width:12%;">客户名称</th>
                            <th style="padding:12px 8px;text-align:left;font-size:14px;font-weight:600;color:var(--plush-text);width:34%;">产品名称</th>
                            <th style="padding:12px 8px;text-align:right;font-size:14px;font-weight:600;color:var(--plush-text);width:10%;white-space:nowrap;">订单数量</th>
                            <th style="padding:12px 8px;text-align:center;font-size:14px;font-weight:600;color:var(--plush-text);width:auto;">操作</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${res.orders.map(o => `
                            <tr class="pc-purchase-row ${orderSelectedIds.has(o.id) ? 'selected' : ''}" data-order-id="${o.id}" onclick="togglePurchaseOrderSelection(${o.id}, event)" style="border-bottom:1px solid var(--pc-border);cursor:pointer;transition:background 0.2s;">
                                <td style="padding:12px 8px;text-align:center;">
                                    <input type="checkbox" ${orderSelectedIds.has(o.id) ? 'checked' : ''} onclick="event.stopPropagation();togglePurchaseOrderSelection(${o.id}, event)" style="width:16px;height:16px;accent-color:var(--pc-primary);cursor:pointer;">
                                </td>
                                <td style="padding:12px 8px;font-family:'Microsoft YaHei','Segoe UI',sans-serif;font-size:14px;font-weight:600;color:var(--plush-text);">${escapeHtml(o.order_date || '')}</td>
                                <td style="padding:12px 8px;font-family:'Microsoft YaHei','Segoe UI',sans-serif;font-size:14px;font-weight:600;color:var(--plush-text);">${escapeHtml(o.order_no)}</td>
                                <td style="padding:12px 8px;font-family:'Microsoft YaHei','Segoe UI',sans-serif;font-size:14px;font-weight:600;color:var(--plush-text);">${escapeHtml(o.customer_name || '-')}</td>
                                <td style="padding:12px 8px;font-family:'Microsoft YaHei','Segoe UI',sans-serif;font-size:14px;font-weight:600;color:var(--plush-text);">${escapeHtml(o.product_name || '-')}</td>
                                <td style="padding:12px 8px;font-family:'Microsoft YaHei','Segoe UI',sans-serif;font-size:14px;font-weight:600;color:var(--plush-text);text-align:right;white-space:nowrap;">${o.quantity ? o.quantity.toLocaleString() : '-'}</td>
                                <td style="padding:12px 8px;text-align:center;">
                                    <button class="pc-btn pc-btn-success pc-btn-sm" onclick="event.stopPropagation();completeOrder(${o.id})"><i class="fas fa-check"></i> 下单完成</button>
                                </td>
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
            `;
        }

        renderPagination('orderPagination', res.pages, res.current_page, loadOrders);
        updatePurchaseSelectionUI();
    }
}

function togglePurchaseOrderSelection(orderId, event) {
    if (orderSelectedIds.has(orderId)) {
        orderSelectedIds.delete(orderId);
    } else {
        orderSelectedIds.add(orderId);
    }
    updatePurchaseSelectionUI();
    updateBatchButtons();
}

function toggleSelectAllPurchaseOrders(checked) {
    if (checked) {
        document.querySelectorAll('.pc-purchase-row').forEach(row => {
            const orderId = parseInt(row.dataset.orderId);
            orderSelectedIds.add(orderId);
        });
    } else {
        orderSelectedIds.clear();
    }
    updatePurchaseSelectionUI();
    updateBatchButtons();
}

function updatePurchaseSelectionUI() {
    document.querySelectorAll('.pc-purchase-row').forEach(row => {
        const orderId = parseInt(row.dataset.orderId);
        const checkbox = row.querySelector('input[type="checkbox"]');
        if (orderSelectedIds.has(orderId)) {
            row.classList.add('selected');
            row.style.background = 'rgba(91,141,239,0.08)';
            if (checkbox) checkbox.checked = true;
        } else {
            row.classList.remove('selected');
            row.style.background = '';
            if (checkbox) checkbox.checked = false;
        }
    });

    const selectAllCheckbox = document.getElementById('selectAllPurchaseOrders');
    const selectAllHeaderCheckbox = document.getElementById('selectAllPurchaseOrdersHeader');
    const visibleRows = document.querySelectorAll('.pc-purchase-row');
    const totalVisible = visibleRows.length;
    const selectedCount = orderSelectedIds.size;
    
    if (selectAllCheckbox) {
        selectAllCheckbox.checked = totalVisible > 0 && selectedCount >= totalVisible;
    }
    if (selectAllHeaderCheckbox) {
        selectAllHeaderCheckbox.checked = totalVisible > 0 && selectedCount >= totalVisible;
    }
    
    const selectedCountEl = document.getElementById('selectedPurchaseCount');
    if (selectedCountEl) selectedCountEl.textContent = selectedCount;
}

function updateBatchButtons() {
    const count = orderSelectedIds.size;
    const summaryEl = document.getElementById('summaryOrderCount');
    const batchEl = document.getElementById('batchCompleteCount');
    const btnSummary = document.getElementById('btnSummaryOrder');
    const btnBatch = document.getElementById('btnBatchComplete');
    if (summaryEl) summaryEl.textContent = `(${count})`;
    if (batchEl) batchEl.textContent = `(${count})`;
    if (btnSummary) btnSummary.disabled = count === 0;
    if (btnBatch) btnBatch.disabled = count === 0;
}

function openModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) {
        modal.classList.add('show');
    }
}

function closeModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) {
        modal.classList.remove('show');
    }
}

async function showOrderDetail(id) {
    const res = await apiGet(`/orders/${id}`);
    if (res.success) {
        const o = res.order;
        document.getElementById('orderDetailContent').innerHTML = `
            <div class="pc-grid pc-grid-2" style="margin-bottom:16px;">
                <div><strong>订单编号：</strong>${escapeHtml(o.order_no)}</div>
                <div><strong>状态：</strong>${getStatusBadge(o.status)}</div>
                <div><strong>供应商：</strong>${escapeHtml(o.supplier_name||'')}</div>
                <div><strong>客户：</strong>${escapeHtml(o.customer_name||'-')}</div>
                <div><strong>下单日期：</strong>${escapeHtml(o.order_date||'-')}</div>
                <div><strong>创建时间：</strong>${escapeHtml(formatDateTime(o.create_time))}</div>
            </div>
            ${o.remark ? `<div style="margin-bottom:16px;"><strong>备注：</strong>${escapeHtml(o.remark)}</div>` : ''}
            <h4 style="margin:0 0 10px;font-size:14px;"><i class="fas fa-list" style="color:var(--pc-primary);"></i> 物料清单</h4>
            <table class="pc-table">
                <thead><tr><th>物料编码</th><th>物料名称</th><th>规格</th><th>数量</th><th>单位</th><th>单SKU用量</th><th>分类</th></tr></thead>
                <tbody>${(o.items||[]).map(i => `<tr><td>${escapeHtml(i.material_code||'-')}</td><td>${escapeHtml(i.material_name)}</td><td>${escapeHtml(i.specification||'-')}</td><td>${i.quantity}</td><td>${escapeHtml(i.unit||'-')}</td><td>${i.unit_usage}</td><td>${escapeHtml(i.material_category||'-')}</td></tr>`).join('')}</tbody>
            </table>
        `;
        document.getElementById('orderDetailModal').classList.add('show');
    }
}

async function deleteOrder(id) {
    const confirmed = await showConfirm('确定要删除此采购订单吗？', '此操作不可恢复', 'danger');
    if (!confirmed) return;
    const res = await apiDelete(`/orders/${id}`);
    if (res.success) { 
        showToast(res.message, 'success'); 
        loadOrders(); 
        // 删除后同时刷新待采购列表（源订单会回滚到待备货）
        loadUnprocessedOrders();
    }
    else showToast(res.message, 'error');
}

async function updateOrderStatus(id, status) {
    const res = await apiPut(`/orders/${id}`, {status});
    if (res.success) { showToast('状态更新成功', 'success'); loadOrders(); }
    else showToast(res.message, 'error');
}

async function printOrder(id) {
    const res = await apiGet(`/orders/${id}/print`);
    if (res.success) {
        const o = res.order;
        const w = window.open('', '_blank');
        w.document.write(`<html><head><title>采购订单 - ${escapeHtml(o.order_no)}</title><style>body{font-family:'Microsoft YaHei',sans-serif;padding:30px;}table{width:100%;border-collapse:collapse;margin-top:16px;}th,td{border:1px solid #ddd;padding:8px;text-align:left;font-size:13px;}th{background:#f5f5f5;}.header{text-align:center;margin-bottom:20px;}.header h2{margin:0;}</style></head><body><div class="header"><h2>东莞市滨发玩具有限公司</h2><h3>采购订单</h3></div><p><strong>订单编号：</strong>${escapeHtml(o.order_no)} &nbsp;&nbsp; <strong>供应商：</strong>${escapeHtml(o.supplier_name||'-')} &nbsp;&nbsp; <strong>客户：</strong>${escapeHtml(o.customer_name||'-')} &nbsp;&nbsp; <strong>日期：</strong>${escapeHtml(o.order_date||'-')}</p><table><thead><tr><th>物料编码</th><th>物料名称</th><th>规格</th><th>数量</th><th>单位</th></tr></thead><tbody>${(o.items||[]).map(i=>`<tr><td>${escapeHtml(i.material_code||'-')}</td><td>${escapeHtml(i.material_name)}</td><td>${escapeHtml(i.specification||'-')}</td><td>${i.quantity}</td><td>${escapeHtml(i.unit||'-')}</td></tr>`).join('')}</tbody></table>${o.remark?`<p style="margin-top:16px;"><strong>备注：</strong>${escapeHtml(o.remark)}</p>`:''}</body></html>`);
        w.document.close();
        w.print();
    }
}

async function batchPrint() {
    if (orderSelectedIds.size === 0) return;
    const res = await apiPost('/orders/batch-print', {ids: Array.from(orderSelectedIds)});
    if (res.success && res.orders) {
        const w = window.open('', '_blank');
        let html = `<html><head><title>批量打印采购订单</title><style>body{font-family:'Microsoft YaHei',sans-serif;padding:30px;}table{width:100%;border-collapse:collapse;margin-top:10px;}th,td{border:1px solid #ddd;padding:6px;text-align:left;font-size:12px;}th{background:#f5f5f5;}.order-section{page-break-after:always;margin-bottom:30px;}.header{text-align:center;margin-bottom:15px;}</style></head><body>`;
        res.orders.forEach(o => {
            html += `<div class="order-section"><div class="header"><h2>东莞市滨发玩具有限公司</h2><h3>采购订单 - ${escapeHtml(o.order_no)}</h3></div><p><strong>供应商：</strong>${escapeHtml(o.supplier_name||'-')} | <strong>客户：</strong>${escapeHtml(o.customer_name||'-')} | <strong>日期：</strong>${escapeHtml(o.order_date||'-')}</p><table><thead><tr><th>物料名称</th><th>规格</th><th>数量</th><th>单位</th></tr></thead><tbody>${(o.items||[]).map(i=>`<tr><td>${escapeHtml(i.material_name)}</td><td>${escapeHtml(i.specification||'-')}</td><td>${i.quantity}</td><td>${escapeHtml(i.unit||'-')}</td></tr>`).join('')}</tbody></table></div>`;
        });
        html += '</body></html>';
        w.document.write(html);
        w.document.close();
        w.print();
    }
}

// ============ Unprocessed Orders ============
let selectedOrders = new Set();
let allOrdersData = [];

async function loadUnprocessedOrders() {
    const res = await apiGet('/unprocessed-orders');
    if (res.success) {
        document.getElementById('unprocessedBadge').textContent = res.total;
        allOrdersData = res.orders || [];
        const list = document.getElementById('unprocessedList');
        if (res.orders.length === 0) {
            list.innerHTML = '<div class="pc-empty-state"><i class="fas fa-inbox"></i><p>暂无未处理订单</p></div>';
        } else {
            list.innerHTML = `
                <div style="margin-bottom:12px;padding:12px 16px;background:var(--pc-primary-lighter);border-radius:var(--pc-radius-md);display:flex;align-items:center;gap:12px;flex-wrap:wrap;">
                    <label style="display:flex;align-items:center;gap:6px;cursor:pointer;font-size:13px;font-weight:500;color:var(--pc-primary-dark);">
                        <input type="checkbox" id="selectAllOrders" onchange="toggleSelectAll(this.checked)" style="width:18px;height:18px;accent-color:var(--pc-primary);cursor:pointer;">
                        <span>全选</span>
                    </label>
                    <span style="font-size:12px;color:var(--pc-text-secondary);">已选择 <strong id="selectedCount" style="color:var(--pc-primary);">0</strong> 个订单</span>
                </div>
                <table class="pc-table" style="width:100%;border-collapse:collapse;margin-top:12px;font-family:'Microsoft YaHei','Segoe UI',sans-serif;">
                    <thead>
                        <tr style="background:var(--pc-primary-lighter);">
                            <th style="padding:12px 8px;text-align:center;font-size:14px;font-weight:600;color:var(--plush-text);width:40px;"><input type="checkbox" id="selectAllOrdersHeader" onchange="toggleSelectAll(this.checked)" style="width:16px;height:16px;accent-color:var(--pc-primary);cursor:pointer;"></th>
                            <th style="padding:12px 8px;text-align:left;font-size:14px;font-weight:600;color:var(--plush-text);width:15%;">下单时间</th>
                            <th style="padding:12px 8px;text-align:left;font-size:14px;font-weight:600;color:var(--plush-text);width:15%;">订单号</th>
                            <th style="padding:12px 8px;text-align:left;font-size:14px;font-weight:600;color:var(--plush-text);width:10%;">客户名称</th>
                            <th style="padding:12px 8px;text-align:left;font-size:14px;font-weight:600;color:var(--plush-text);width:30%;">产品名称</th>
                            <th style="padding:12px 8px;text-align:right;font-size:14px;font-weight:600;color:var(--plush-text);width:10%;">订单数量</th>
                            <th style="padding:12px 8px;text-align:center;font-size:14px;font-weight:600;color:var(--plush-text);width:auto;">操作</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${res.orders.map(o => `
                            <tr class="pc-unprocessed-row ${selectedOrders.has(o.id) ? 'selected' : ''}" data-order-id="${o.id}" onclick="toggleOrderSelection(${o.id}, event)" style="border-bottom:1px solid var(--pc-border);cursor:pointer;transition:background 0.2s;">
                                <td style="padding:12px 8px;text-align:center;">
                                    <input type="checkbox" ${selectedOrders.has(o.id) ? 'checked' : ''} onclick="event.stopPropagation();toggleOrderSelection(${o.id}, event)" style="width:16px;height:16px;accent-color:var(--pc-primary);cursor:pointer;">
                                </td>
                                <td style="padding:12px 8px;font-family:'Microsoft YaHei','Segoe UI',sans-serif;font-size:14px;font-weight:600;color:var(--plush-text);">${escapeHtml(formatDateTime(o.order_date))}</td>
                                <td style="padding:12px 8px;font-family:'Microsoft YaHei','Segoe UI',sans-serif;font-size:14px;font-weight:600;color:var(--plush-text);">${escapeHtml(o.order_no)}</td>
                                <td style="padding:12px 8px;font-family:'Microsoft YaHei','Segoe UI',sans-serif;font-size:14px;font-weight:600;color:var(--plush-text);">${escapeHtml(o.customer || '-')}</td>
                                <td style="padding:12px 8px;font-family:'Microsoft YaHei','Segoe UI',sans-serif;font-size:14px;font-weight:600;color:var(--plush-text);">${escapeHtml(o.product_name || '-')}</td>
                                <td style="padding:12px 8px;font-family:'Microsoft YaHei','Segoe UI',sans-serif;font-size:14px;font-weight:600;color:var(--plush-text);text-align:right;">${o.quantity.toLocaleString()}</td>
                                <td style="padding:12px 8px;text-align:center;">
                                    ${o.has_bom
                                        ? `<button class="pc-btn pc-btn-sm pc-btn-success" onclick="event.stopPropagation();quickGenerateSingleOrder(${o.id})" style="background: linear-gradient(135deg, #28C76F 0%, #1E9E55 100%); border: none; box-shadow: 0 2px 8px rgba(40,199,111,0.3);padding:8px 14px;font-size:14px;font-weight:600;"><i class="fas fa-magic"></i> 审核订单</button>`
                                        : `<button class="pc-btn pc-btn-sm pc-btn-outline" disabled title="该产品未配置BOM表，无法审核" style="padding:8px 14px;font-size:14px;font-weight:600;"><i class="fas fa-magic"></i> 审核订单</button>`
                                    }
                                </td>
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
            `;
        }
    } else {
        allOrdersData = [];
        const list = document.getElementById('unprocessedList');
        list.innerHTML = '<div class="pc-empty-state"><i class="fas fa-exclamation-triangle"></i><p>加载失败，请重试</p></div>';
    }
    updateOneClickButton();
}

function toggleOrderSelection(orderId, event) {
    if (selectedOrders.has(orderId)) {
        selectedOrders.delete(orderId);
    } else {
        selectedOrders.add(orderId);
    }
    updateSelectionUI();
}

function toggleSelectAll(checked) {
    if (checked) {
        allOrdersData.forEach(o => selectedOrders.add(o.id));
    } else {
        selectedOrders.clear();
    }
    updateSelectionUI();
}

function updateSelectionUI() {
    // 更新订单表格行的选中状态
    document.querySelectorAll('.pc-unprocessed-row').forEach(row => {
        const orderId = parseInt(row.dataset.orderId);
        const checkbox = row.querySelector('input[type="checkbox"]');
        if (selectedOrders.has(orderId)) {
            row.classList.add('selected');
            row.style.background = 'rgba(91,141,239,0.08)';
            if (checkbox) checkbox.checked = true;
        } else {
            row.classList.remove('selected');
            row.style.background = '';
            if (checkbox) checkbox.checked = false;
        }
    });

    // 更新全选复选框
    const selectAllCheckbox = document.getElementById('selectAllOrders');
    const selectAllHeaderCheckbox = document.getElementById('selectAllOrdersHeader');
    if (selectAllCheckbox) {
        selectAllCheckbox.checked = allOrdersData.length > 0 && selectedOrders.size === allOrdersData.length;
    }
    if (selectAllHeaderCheckbox) {
        selectAllHeaderCheckbox.checked = allOrdersData.length > 0 && selectedOrders.size === allOrdersData.length;
    }

    // 更新选中计数
    const selectedCountEl = document.getElementById('selectedCount');
    if (selectedCountEl) {
        selectedCountEl.textContent = selectedOrders.size;
    }

    // 更新一键生成按钮状态
    updateOneClickButton();
}

async function oneClickGenerateOrder() {
    const validOrders = Array.from(selectedOrders).filter(id => {
        const order = allOrdersData.find(o => o.id === id);
        return order && order.has_bom;
    });

    if (validOrders.length === 0) {
        showToast('请选择至少一个有BOM配置的订单', 'warning');
        return;
    }

    const confirmed = await showConfirm(
        `确定要审核 ${validOrders.length} 个订单吗？`,
        '审核通过后将自动计算物料用量并生成采购订单',
        'success'
    );
    
    if (!confirmed) return;

    const btn = document.getElementById('btnOneClickGenerate');
    const originalText = btn.innerHTML;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> 审核中...';
    btn.disabled = true;

    try {
        const res = await apiPost('/orders/one-click-generate', {
            order_ids: validOrders
        });

        if (res.success) {
            showToast(res.message, 'success');
            
            if (res.warnings && res.warnings.length > 0) {
                console.warn('部分订单处理失败:', res.warnings);
            }
            
            selectedOrders.clear();
            updateSelectionUI();
            loadUnprocessedOrders();
            loadOrders();
        } else {
            showToast(res.message || '审核失败', 'error');
        }
    } catch (error) {
        showToast('审核失败: ' + error.message, 'error');
    } finally {
        btn.innerHTML = originalText;
        updateOneClickButton();
    }
}

function updateOneClickButton() {
    const btn = document.getElementById('btnOneClickGenerate');
    const countEl = document.getElementById('oneClickCount');
    
    if (!btn) return;
    
    const validOrders = Array.from(selectedOrders).filter(id => {
        const order = allOrdersData.find(o => o.id === id);
        return order && order.has_bom;
    });

    btn.disabled = validOrders.length === 0;
    if (countEl) {
        countEl.textContent = `(${validOrders.length})`;
    }
}

async function quickGenerateSingleOrder(orderId) {
    const order = allOrdersData.find(o => o.id === orderId);
    if (!order || !order.has_bom) {
        showToast('该订单无法审核', 'warning');
        return;
    }

    const confirmed = await showConfirm(
        `确定要审核订单 ${order.order_no} 吗？`,
        '审核通过后将自动计算物料用量并生成采购订单',
        'success'
    );
    
    if (!confirmed) return;

    try {
        const res = await apiPost('/orders/one-click-generate', {
            order_ids: [orderId]
        });

        if (res.success) {
            showToast(res.message, 'success');
            loadUnprocessedOrders();
            loadOrders();
        } else {
            showToast(res.message || '审核失败', 'error');
        }
    } catch (error) {
        showToast('审核失败: ' + error.message, 'error');
    }
}

// syncOrders, processUnprocessedOrder, openStatusChangeModal, selectStatusAction,
// confirmStatusChange, showStatusHistory, getStatusLabel 已移除（未处理订单中间层废弃）

// showSyncStatistics, showRetryQueue, loadRetryQueueList, processRetryQueue, abandonRetryItem
// 已移除（未处理订单中间层废弃）

// ============ Pagination Helper ============
function renderPagination(containerId, totalPages, currentPage, callback) {
    const container = document.getElementById(containerId);
    if (totalPages <= 1) { container.innerHTML = ''; return; }
    let html = `<button ${currentPage<=1?'disabled':''} onclick="${callback.name}(${currentPage-1})"><i class="fas fa-chevron-left"></i></button>`;
    const maxShow = 5;
    let start = Math.max(1, currentPage - Math.floor(maxShow/2));
    let end = Math.min(totalPages, start + maxShow - 1);
    if (end - start < maxShow - 1) start = Math.max(1, end - maxShow + 1);
    for (let i = start; i <= end; i++) {
        html += `<button class="${i===currentPage?'active':''}" onclick="${callback.name}(${i})">${i}</button>`;
    }
    html += `<button ${currentPage>=totalPages?'disabled':''} onclick="${callback.name}(${currentPage+1})"><i class="fas fa-chevron-right"></i></button>`;
    container.innerHTML = html;
}

// ============ Init ============

async function initPurchaseCenter() {
    loadUnprocessedOrders();
    loadOrders();
    startAutoRefresh();
}

async function startAutoRefresh() {
    autoRefreshInterval = setInterval(async () => {
        if (!isAutoRefreshEnabled || !isPageVisible) return;

        try {
            const ordersPanel = document.getElementById('panel-orders');
            if (!ordersPanel || !ordersPanel.classList.contains('active')) return;

            // 静默刷新采购中订单
            const params = new URLSearchParams({page: orderCurrentPage, per_page: 15});
            const res = await apiGet(`/orders?${params}`);
            if (res.success && res.total !== lastOrderCount) {
                lastOrderCount = res.total;
                loadOrdersSilently(orderCurrentPage);
            }

            // 静默刷新待采购订单数量
            const unprocessedRes = await apiGet('/unprocessed-orders');
            if (unprocessedRes.success) {
                document.getElementById('unprocessedBadge').textContent = unprocessedRes.total;
            }
        } catch (err) {
            console.error('[自动刷新] 检查失败:', err);
        }
    }, 30000);
}

function stopAutoRefresh() {
    if (autoRefreshInterval) {
        clearInterval(autoRefreshInterval);
        autoRefreshInterval = null;
    }
}

function debounce(fn, delay) {
    let timer;
    return function(...args) { clearTimeout(timer); timer = setTimeout(() => fn.apply(this, args), delay); };
}

// ============ 下单完成功能 ============
let completedOrders = [];
let completedOrderPage = 1;
let completedOrderFilters = {};
let historyFilterPanelExpanded = false;
let currentQuickFilterId = null;

async function completeOrder(orderId) {
    if (!confirm('确认将此订单标记为下单完成？订单将从采购订单列表移至下单查询。')) {
        return;
    }
    
    const res = await apiPost('/orders/complete', {order_id: orderId});
    if (res.success) {
        showToast('订单已完成下单', 'success');
        orderSelectedIds.delete(orderId);
        loadOrdersSilently(orderCurrentPage);
        updateBatchButtons();
    } else {
        showToast(res.message || '操作失败', 'error');
    }
}

async function batchCompleteOrders() {
    if (orderSelectedIds.size === 0) {
        showToast('请先选择订单', 'error');
        return;
    }
    
    if (!confirm(`确认将选中的 ${orderSelectedIds.size} 个订单标记为下单完成？`)) {
        return;
    }
    
    const res = await apiPost('/orders/batch-complete', {ids: Array.from(orderSelectedIds)});
    if (res.success) {
        showToast(`成功完成 ${res.completed_count || orderSelectedIds.size} 个订单`, 'success');
        orderSelectedIds.clear();
        loadOrdersSilently(orderCurrentPage);
        updateBatchButtons();
    } else {
        showToast(res.message || '操作失败', 'error');
    }
}

async function loadCompletedOrders(page = 1) {
    completedOrderPage = page;
    const list = document.getElementById('completedOrderList');
    list.innerHTML = '<div class="pc-loading"><div class="spinner"></div> 加载中...</div>';
    
    let params = new URLSearchParams({page: page, per_page: 20});
    Object.keys(completedOrderFilters).forEach(key => {
        if (completedOrderFilters[key]) {
            params.set(key, completedOrderFilters[key]);
        }
    });
    
    const startTime = Date.now();
    const res = await apiGet(`/orders/completed?${params}`);
    const endTime = Date.now();
    
    if (res.success) {
        completedOrders = res.orders || [];
        renderCompletedOrders(res, endTime - startTime);
        renderCompletedOrderPagination(res);
    } else {
        list.innerHTML = '<div class="pc-empty-state"><i class="fas fa-exclamation-circle"></i><p>加载失败</p></div>';
    }
}

function renderCompletedOrders(res, queryTime) {
    const list = document.getElementById('completedOrderList');
    
    if (!res.orders || res.orders.length === 0) {
        list.innerHTML = '<div class="pc-empty-state"><i class="fas fa-check-circle"></i><p>暂无已完成的订单</p></div>';
        return;
    }
    
    list.innerHTML = `
        <div style="margin-bottom:12px;display:flex;justify-content:space-between;align-items:center;">
            <div class="pc-search-status">
                <i class="fas fa-info-circle"></i>
                共 <strong>${res.total}</strong> 条记录
                ${queryTime ? `<span style="margin-left:8px;color:var(--pc-success);">(${queryTime}ms)</span>` : ''}
            </div>
        </div>
        <div class="pc-table-wrapper">
            <table class="pc-table">
                <thead>
                    <tr>
                        <th style="width:15%;">下单时间</th>
                        <th style="width:15%;">订单号</th>
                        <th style="width:12%;">客户名称</th>
                        <th style="width:30%;">产品名称</th>
                        <th style="width:10%;text-align:right;">订单数量</th>
                        <th style="width:10%;">完成时间</th>
                        <th style="width:auto;">操作</th>
                    </tr>
                </thead>
                <tbody>
                    ${res.orders.map(o => `
                        <tr class="pc-purchase-row" style="border-bottom:1px solid var(--pc-border);">
                            <td style="padding:12px 8px;font-family:'Microsoft YaHei',sans-serif;font-size:14px;">${escapeHtml(o.order_date || '-')}</td>
                            <td style="padding:12px 8px;font-family:'Microsoft YaHei',sans-serif;font-size:14px;font-weight:600;">${escapeHtml(o.order_no)}</td>
                            <td style="padding:12px 8px;font-family:'Microsoft YaHei',sans-serif;font-size:14px;">${escapeHtml(o.customer_name || '-')}</td>
                            <td style="padding:12px 8px;font-family:'Microsoft YaHei',sans-serif;font-size:14px;">${escapeHtml(o.product_name || '-')}</td>
                            <td style="padding:12px 8px;font-family:'Microsoft YaHei',sans-serif;font-size:14px;text-align:right;font-weight:600;">${o.quantity ? o.quantity.toLocaleString() : '-'}</td>
                            <td style="padding:12px 8px;font-size:12px;color:var(--pc-text-muted);">${escapeHtml(o.completed_at || '-')}</td>
                            <td style="padding:12px 8px;text-align:center;">
                                <button class="pc-btn pc-btn-outline pc-btn-sm" onclick="viewCompletedOrder(${o.id})"><i class="fas fa-eye"></i> 查看</button>
                            </td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        </div>
    `;
}

function renderCompletedOrderPagination(res) {
    const pagination = document.getElementById('completedOrderPagination');
    if (!pagination || res.total_pages <= 1) {
        if (pagination) pagination.innerHTML = '';
        return;
    }
    
    let html = '';
    html += `<button ${res.page <= 1 ? 'disabled' : ''} onclick="loadCompletedOrders(${res.page - 1})"><i class="fas fa-chevron-left"></i></button>`;
    
    const maxShow = 5;
    let start = Math.max(1, res.page - Math.floor(maxShow / 2));
    let end = Math.min(res.total_pages, start + maxShow - 1);
    if (end - start < maxShow - 1) start = Math.max(1, end - maxShow + 1);
    
    for (let i = start; i <= end; i++) {
        html += `<button class="${i === res.page ? 'active' : ''}" onclick="loadCompletedOrders(${i})">${i}</button>`;
    }
    
    html += `<button ${res.page >= res.total_pages ? 'disabled' : ''} onclick="loadCompletedOrders(${res.page + 1})"><i class="fas fa-chevron-right"></i></button>`;
    
    pagination.innerHTML = html;
}

function toggleHistoryFilterPanel() {
    historyFilterPanelExpanded = !historyFilterPanelExpanded;
    const panel = document.getElementById('historyFilterPanel');
    const toggleText = document.getElementById('historyFilterToggleText');
    
    if (historyFilterPanelExpanded) {
        panel.style.display = 'block';
        toggleText.textContent = '收起筛选';
    } else {
        panel.style.display = 'none';
        toggleText.textContent = '展开筛选';
    }
}

function filterCompletedOrders() {
    completedOrderFilters = {
        order_no: document.getElementById('completedOrderNo')?.value || '',
        customer_name: document.getElementById('completedCustomer')?.value || '',
        product_name: document.getElementById('completedProduct')?.value || '',
        supplier_name: document.getElementById('completedSupplier')?.value || '',
        barcode: document.getElementById('completedBarcode')?.value || '',
        material_name: document.getElementById('completedMaterial')?.value || '',
        start_date: document.getElementById('completedStartDate')?.value || '',
        end_date: document.getElementById('completedEndDate')?.value || ''
    };
    
    currentQuickFilterId = null;
    updateQuickFilterButtons();
    loadCompletedOrders(1);
}

function resetCompletedFilters() {
    document.getElementById('completedOrderNo').value = '';
    document.getElementById('completedCustomer').value = '';
    document.getElementById('completedProduct').value = '';
    document.getElementById('completedSupplier').value = '';
    document.getElementById('completedBarcode').value = '';
    document.getElementById('completedMaterial').value = '';
    document.getElementById('completedStartDate').value = '';
    document.getElementById('completedEndDate').value = '';
    completedOrderFilters = {};
    currentQuickFilterId = null;
    updateQuickFilterButtons();
    loadCompletedOrders(1);
}

async function viewCompletedOrder(orderId) {
    const res = await apiGet(`/orders/${orderId}`);
    if (res.success) {
        const o = res.order;
        document.getElementById('orderDetailContent').innerHTML = `
            <div class="pc-grid pc-grid-2" style="margin-bottom:16px;">
                <div><strong>订单编号：</strong>${escapeHtml(o.order_no)}</div>
                <div><strong>状态：</strong><span class="pc-badge pc-badge-success">已完成</span></div>
                <div><strong>供应商：</strong>${escapeHtml(o.supplier_name||'')}</div>
                <div><strong>客户：</strong>${escapeHtml(o.customer_name||'-')}</div>
                <div><strong>下单日期：</strong>${escapeHtml(o.order_date||'-')}</div>
                <div><strong>完成时间：</strong>${escapeHtml(o.completed_at||'-')}</div>
            </div>
            ${o.remark ? `<div style="margin-bottom:16px;"><strong>备注：</strong>${escapeHtml(o.remark)}</div>` : ''}
            <h4 style="margin:0 0 10px;font-size:14px;"><i class="fas fa-list" style="color:var(--pc-primary);"></i> 物料清单</h4>
            <table class="pc-table">
                <thead><tr><th>物料编码</th><th>物料名称</th><th>规格</th><th>数量</th><th>单位</th><th>单SKU用量</th><th>分类</th></tr></thead>
                <tbody>
                    ${(o.items||[]).map(item => `
                        <tr>
                            <td>${escapeHtml(item.material_code||'-')}</td>
                            <td>${escapeHtml(item.material_name||'-')}</td>
                            <td>${escapeHtml(item.specification||'-')}</td>
                            <td>${item.quantity||0}</td>
                            <td>${escapeHtml(item.unit||'-')}</td>
                            <td>${item.unit_usage||'-'}</td>
                            <td>${escapeHtml(item.material_category||'-')}</td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        `;
        openModal('orderDetailModal');
    }
}

async function exportCompletedOrders() {
    showToast('正在导出...', 'info');
    const res = await apiPost('/orders/completed/export', completedOrderFilters);
    if (res.success && res.html) {
        downloadFile(res.html, '下单查询汇总.xls', 'application/vnd.ms-excel');
    } else {
        showToast(res.message || '导出失败', 'error');
    }
}

// ============ 快捷筛选功能 ============
async function loadHistoryQuickFilters() {
    try {
        const res = await apiGet('/orders/completed/quick-filters');
        if (res.success && res.quick_filters) {
            const container = document.getElementById('historyQuickFilters');
            container.innerHTML = res.quick_filters.map(filter => `
                <button class="pc-quick-filter-btn" data-id="${escapeHtml(filter.id)}" onclick="applyQuickFilter('${escapeHtml(filter.id)}')">
                    ${escapeHtml(filter.name)}
                </button>
            `).join('');
        }
    } catch (e) {
        console.error('加载快捷筛选失败:', e);
    }
}

async function applyQuickFilter(filterId) {
    try {
        const res = await apiGet('/orders/completed/quick-filters');
        if (res.success && res.quick_filters) {
            const filter = res.quick_filters.find(f => f.id === filterId);
            if (filter) {
                completedOrderFilters = filter.filters || {};
                
                document.getElementById('completedStartDate').value = filter.filters.start_date || '';
                document.getElementById('completedEndDate').value = filter.filters.end_date || '';
                document.getElementById('completedOrderNo').value = '';
                document.getElementById('completedCustomer').value = '';
                document.getElementById('completedProduct').value = '';
                document.getElementById('completedSupplier').value = '';
                document.getElementById('completedMaterial').value = '';
                
                currentQuickFilterId = filterId;
                updateQuickFilterButtons();
                loadCompletedOrders(1);
            }
        }
    } catch (e) {
        console.error('应用快捷筛选失败:', e);
    }
}

function updateQuickFilterButtons() {
    document.querySelectorAll('#historyQuickFilters .pc-quick-filter-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.id === currentQuickFilterId);
    });
}

// ============ 自动完成/智能联想功能 ============
const autocompleteDebounce = {};

function setupAutocomplete() {
    const fields = ['order_no', 'customer_name', 'product_name', 'supplier_name', 'material_name'];
    const ids = ['completedOrderNo', 'completedCustomer', 'completedProduct', 'completedSupplier', 'completedMaterial'];
    
    fields.forEach((field, index) => {
        const input = document.getElementById(ids[index]);
        if (!input) return;
        
        input.addEventListener('input', (e) => {
            clearTimeout(autocompleteDebounce[field]);
            autocompleteDebounce[field] = setTimeout(() => {
                fetchAutocomplete(field, e.target.value);
            }, 300);
        });
        
        input.addEventListener('blur', () => {
            setTimeout(() => {
                const dropdown = document.getElementById(`autocomplete-${field}`);
                if (dropdown) dropdown.style.display = 'none';
            }, 200);
        });
        
        input.addEventListener('focus', () => {
            if (input.value.length >= 1) {
                fetchAutocomplete(field, input.value);
            }
        });
    });
}

async function fetchAutocomplete(field, keyword) {
    const dropdown = document.getElementById(`autocomplete-${field}`);
    if (!dropdown) return;
    
    if (!keyword || keyword.length < 1) {
        dropdown.style.display = 'none';
        return;
    }
    
    try {
        const res = await apiGet(`/orders/completed/suggestions?field=${field}&q=${encodeURIComponent(keyword)}`);
        if (res.success && res.suggestions && res.suggestions.length > 0) {
            dropdown.innerHTML = res.suggestions.map(s => `
                <div class="autocomplete-item" data-field="${escapeHtml(field)}" data-value="${escapeHtml(s.value)}">
                    ${escapeHtml(s.value)}
                </div>
            `).join('');
            dropdown.querySelectorAll('.autocomplete-item').forEach(el => {
                el.addEventListener('click', function() {
                    selectAutocomplete(this.dataset.field, this.dataset.value);
                });
            });
            dropdown.style.display = 'block';
        } else {
            dropdown.style.display = 'none';
        }
    } catch (e) {
        console.error('获取联想建议失败:', e);
        dropdown.style.display = 'none';
    }
}

function selectAutocomplete(field, value) {
    const fieldToId = {
        'order_no': 'completedOrderNo',
        'customer_name': 'completedCustomer',
        'product_name': 'completedProduct',
        'supplier_name': 'completedSupplier',
        'material_name': 'completedMaterial'
    };
    
    const input = document.getElementById(fieldToId[field]);
    if (input) {
        input.value = value;
    }
    
    const dropdown = document.getElementById(`autocomplete-${field}`);
    if (dropdown) dropdown.style.display = 'none';
    
    filterCompletedOrders();
}

// ============ 下单查询初始化 ============
function initHistoryPanel() {
    loadHistoryQuickFilters();
    setupAutocomplete();
    loadCompletedOrders(1);
}

// ============ 汇总打印中心 ============
// ============================================================
// 汇总下单 - 合并工厂内部订单 + 供应商采购订单
// ============================================================

let currentFactorySummaryData = null;
let currentSupplierSummaryData = null;
let factorySummaryEditMode = false;
let factorySummaryOriginalData = null;
let factorySummaryEdits = [];
let activeSummaryTab = 'factory'; // 'factory' | 'supplier'

async function processSummaryOrder() {
    if (orderSelectedIds.size === 0) {
        showToast('请先选择订单', 'error');
        return;
    }

    showToast('正在汇总订单数据...', 'info');

    // 同时请求工厂和供应商汇总数据
    const [factoryRes, supplierRes] = await Promise.all([
        apiPost('/orders/factory-summary', {ids: Array.from(orderSelectedIds)}),
        apiPost('/orders/supplier-summary', {ids: Array.from(orderSelectedIds)})
    ]);

    if (!factoryRes.success || !supplierRes.success) {
        showToast(factoryRes.message || supplierRes.message || '汇总失败', 'error');
        return;
    }

    currentFactorySummaryData = JSON.parse(JSON.stringify(factoryRes));
    factorySummaryOriginalData = JSON.parse(JSON.stringify(factoryRes));
    currentSupplierSummaryData = JSON.parse(JSON.stringify(supplierRes));
    factorySummaryEditMode = false;
    factorySummaryEdits = [];
    activeSummaryTab = 'factory';

    renderSummaryModal();
    openModal('statusHistoryModal');
}

function switchSummaryTab(tab) {
    activeSummaryTab = tab;
    renderSummaryModal();
}

function renderSummaryModal() {
    const isFactory = activeSummaryTab === 'factory';

    // ── Tab 标签栏 ──
    const tabHtml = `
        <div style="display:flex;border-bottom:2px solid #e0e0e0;margin-bottom:0;">
            <div onclick="switchSummaryTab('factory')"
                 style="padding:10px 20px;cursor:pointer;font-size:14px;font-weight:600;border-bottom:3px solid ${isFactory ? '#667eea' : 'transparent'};color:${isFactory ? '#667eea' : '#999'};margin-bottom:-2px;transition:all 0.2s;">
                <i class="fas fa-industry"></i> 工厂内部订单
            </div>
            <div onclick="switchSummaryTab('supplier')"
                 style="padding:10px 20px;cursor:pointer;font-size:14px;font-weight:600;border-bottom:3px solid ${!isFactory ? '#f093fb' : 'transparent'};color:${!isFactory ? '#f093fb' : '#999'};margin-bottom:-2px;transition:all 0.2s;">
                <i class="fas fa-truck"></i> 供应商采购订单
            </div>
        </div>
    `;

    let contentHtml;
    if (isFactory) {
        contentHtml = renderFactoryTabContent();
    } else {
        contentHtml = renderSupplierTabContent();
    }

    const modalContent = `
        <div style="padding:0;">
            ${tabHtml}
            <div style="padding:15px;">
                ${contentHtml}
            </div>
        </div>
    `;

    document.getElementById('statusHistoryModal').querySelector('.pc-modal-header h3').innerHTML = '<i class="fas fa-clipboard-list"></i> 汇总下单';
    document.getElementById('statusHistoryContent').innerHTML = modalContent;
}

// ── 工厂内部订单 Tab 内容 ──
function renderFactoryTabContent() {
    const data = currentFactorySummaryData;
    let tableHtml = '';
    let grandTotal = 0;
    let rowIndex = 0;

    if (data.groups && data.groups.length > 0) {
        data.groups.forEach((group, groupIndex) => {
            const suppliers = group.suppliers || [];
            const totalFabricRows = suppliers.reduce((sum, s) => sum + (s.fabrics ? s.fabrics.length : 0), 0);

            let globalFabricIdx = 0;
            suppliers.forEach((supplier, supplierIndex) => {
                const fabrics = supplier.fabrics || [];
                const supplierFabricCount = fabrics.length;

                fabrics.forEach((fabric, fabricIndex) => {
                    tableHtml += '<tr>';
                    if (globalFabricIdx === 0) {
                        tableHtml += `<td style="border:1px solid #333;padding:8px;vertical-align:middle;text-align:center;font-weight:bold;" rowspan="${totalFabricRows}">${escapeHtml(group.customer_name)}</td>`;
                        tableHtml += `<td style="border:1px solid #333;padding:8px;vertical-align:middle;text-align:center;" rowspan="${totalFabricRows}">${escapeHtml(group.product_name)}</td>`;
                        tableHtml += `<td style="border:1px solid #333;padding:8px;vertical-align:middle;text-align:center;" rowspan="${totalFabricRows}">${parseFloat(group.product_quantity || group.order_quantity || 0) % 1 === 0 ? parseInt(group.product_quantity || group.order_quantity) : parseFloat(group.product_quantity || group.order_quantity).toFixed(2).replace(/\.?0+$/, '')}</td>`;
                    }
                    if (fabricIndex === 0) {
                        tableHtml += `<td style="border:1px solid #333;padding:8px;vertical-align:middle;text-align:center;" rowspan="${supplierFabricCount}">${escapeHtml(supplier.supplier_name)}</td>`;
                    }
                    tableHtml += `<td style="border:1px solid #333;padding:8px;vertical-align:middle;text-align:left;">${escapeHtml(fabric.fabric_name)}</td>`;
                    tableHtml += `<td style="border:1px solid #333;padding:8px;vertical-align:middle;text-align:left;">${escapeHtml(fabric.specification || '')}</td>`;

                    const isMerged = fabric.item_ids && fabric.item_ids.length > 1;
                    const mergeTag = isMerged ? '<span style="font-size:10px;color:#999;margin-left:4px;" title="此为合并项">(合)</span>' : '';

                    if (factorySummaryEditMode) {
                        tableHtml += `<td style="border:1px solid #333;padding:4px;vertical-align:middle;text-align:right;">
                            <input type="number"
                                   class="pc-form-input"
                                   style="width:80px;text-align:right;padding:4px 6px;font-size:13px;"
                                   value="${fabric.quantity}"
                                   data-item-id="${fabric.item_id || (fabric.item_ids ? fabric.item_ids[0] : '')}"
                                   data-item-ids="${fabric.item_ids ? fabric.item_ids.join(',') : (fabric.item_id || '')}"
                                   data-original-quantities="${fabric.original_quantities ? encodeURIComponent(JSON.stringify(fabric.original_quantities)) : ''}"
                                   data-group="${groupIndex}"
                                   data-supplier="${supplierIndex}"
                                   data-fabric="${fabricIndex}"
                                   data-unit="${fabric.unit || ''}"
                                   data-original="${fabric.quantity}"
                                   onchange="updateFactoryQuantity(${groupIndex}, ${supplierIndex}, ${fabricIndex}, this.value, this.dataset.itemId, this.dataset.itemIds, this.dataset.originalQuantities)"
                                   onfocus="this.select()"
                                   min="0">
                            <span style="font-size:12px;margin-left:2px;">${fabric.unit || ''}</span>
                            ${mergeTag}
                        </td>`;
                    } else {
                        tableHtml += `<td style="border:1px solid #333;padding:8px;vertical-align:middle;text-align:right;">${fabric.quantity} ${escapeHtml(fabric.unit)}${mergeTag}</td>`;
                    }
                    tableHtml += '</tr>';
                    grandTotal += parseFloat(fabric.quantity) || 0;
                    globalFabricIdx++;
                    rowIndex++;
                });
            });
        });

        tableHtml += '<tr style="background-color:#f0f0f0;font-weight:bold;">';
        tableHtml += '<td style="border:1px solid #333;padding:8px;text-align:center;" colspan="4">合计</td>';
        tableHtml += '<td style="border:1px solid #333;padding:8px;text-align:left;"></td>';
        tableHtml += '<td style="border:1px solid #333;padding:8px;text-align:left;"></td>';
        tableHtml += `<td style="border:1px solid #333;padding:8px;text-align:right;" id="factoryGrandTotal">${grandTotal}</td>`;
        tableHtml += '</tr>';
    }

    const editBtnHtml = factorySummaryEditMode
        ? `<button class="pc-btn pc-btn-sm pc-btn-warning" onclick="toggleFactoryEditMode(false)">
               <i class="fas fa-times"></i> 取消编辑
           </button>
           <button class="pc-btn pc-btn-sm pc-btn-success" onclick="saveFactoryEdits()">
               <i class="fas fa-save"></i> 保存修改
           </button>`
        : `<button class="pc-btn pc-btn-sm pc-btn-outline" onclick="toggleFactoryEditMode(true)">
               <i class="fas fa-edit"></i> 自定义编辑
           </button>`;

    return `
        <div style="margin-bottom:12px;padding:12px;background:linear-gradient(135deg,rgba(102,126,234,0.1) 0%,rgba(118,75,162,0.1) 100%);border-radius:8px;">
            <div style="display:flex;justify-content:space-between;align-items:center;">
                <div>
                    <div style="font-weight:600;margin-bottom:6px;font-size:14px;"><i class="fas fa-industry" style="color:#667eea;"></i> 工厂内部采购订单汇总</div>
                    <div style="font-size:12px;color:var(--pc-text-secondary);">
                        已选择 <strong style="color:#667eea;">${data.order_count||orderSelectedIds.size}</strong> 个订单
                        ${factorySummaryEditMode ? '<span style="margin-left:8px;color:var(--pc-warning);"><i class="fas fa-exclamation-triangle"></i> 编辑模式 — 修改数量将实时同步到供应商订单</span>' : ''}
                    </div>
                </div>
                <div style="display:flex;gap:8px;">
                    ${editBtnHtml}
                </div>
            </div>
        </div>

        <div style="max-height:calc(100vh - 320px);overflow:auto;">
            <table style="width:100%;border-collapse:collapse;font-family:SimSun,宋体;font-size:13px;background:#fff;">
                <thead>
                    <tr style="background-color:#e6e6e6;">
                        <th style="border:1px solid #333;padding:6px 8px;text-align:center;font-weight:bold;width:10%;">客户</th>
                        <th style="border:1px solid #333;padding:6px 8px;text-align:center;font-weight:bold;width:16%;">产品名称</th>
                        <th style="border:1px solid #333;padding:6px 8px;text-align:center;font-weight:bold;width:7%;">订单数量</th>
                        <th style="border:1px solid #333;padding:6px 8px;text-align:center;font-weight:bold;width:10%;">供应商</th>
                        <th style="border:1px solid #333;padding:6px 8px;text-align:center;font-weight:bold;width:25%;">布料名称</th>
                        <th style="border:1px solid #333;padding:6px 8px;text-align:center;font-weight:bold;width:17%;">规格型号</th>
                        <th style="border:1px solid #333;padding:6px 8px;text-align:center;font-weight:bold;width:15%;">数量</th>
                    </tr>
                </thead>
                <tbody>
                    ${tableHtml || '<tr><td style="border:1px solid #333;padding:20px;text-align:center;" colspan="7">暂无数据</td></tr>'}
                </tbody>
            </table>
        </div>

        <div style="margin-top:15px;padding-top:12px;border-top:1px solid var(--pc-border);display:flex;justify-content:space-between;align-items:center;">
            <div style="display:flex;gap:8px;">
                <button class="pc-btn pc-btn-sm pc-btn-success" onclick="exportFactorySummary()">
                    <i class="fas fa-file-excel"></i> 导出 Excel
                </button>
            </div>
            <div style="display:flex;gap:8px;">
                <button class="pc-btn pc-btn-outline pc-btn-sm" onclick="closeModal('statusHistoryModal')">关闭</button>
                <button class="pc-btn pc-btn-sm pc-btn-primary" onclick="printFactorySummary()">
                    <i class="fas fa-print"></i> 打印预览
                </button>
            </div>
        </div>
    `;
}

// ── 供应商采购订单 Tab 内容 ──
function renderSupplierTabContent() {
    const data = currentSupplierSummaryData;

    // 按 supplier_name 分组
    const supplierGroups = {};
    let supplierOrder = [];
    if (data.materials) {
        data.materials.forEach(m => {
            const supplier = m.supplier_name || '未指定供应商';
            if (!supplierGroups[supplier]) {
                supplierGroups[supplier] = [];
                supplierOrder.push(supplier);
            }
            supplierGroups[supplier].push(m);
        });
    }

    let tableHtml = '';
    let grandTotal = 0;

    if (supplierOrder.length > 0) {
        supplierOrder.forEach(supplierName => {
            const materials = supplierGroups[supplierName];
            const materialCount = materials.length;

            materials.forEach((m, mIndex) => {
                tableHtml += '<tr>';
                if (mIndex === 0) {
                    tableHtml += `<td style="border:1px solid #333;padding:8px;vertical-align:middle;text-align:center;font-weight:bold;" rowspan="${materialCount}">${escapeHtml(supplierName)}</td>`;
                }
                tableHtml += `<td style="border:1px solid #333;padding:8px;vertical-align:middle;text-align:left;">${escapeHtml(m.material_name)}</td>`;
                tableHtml += `<td style="border:1px solid #333;padding:8px;vertical-align:middle;text-align:left;">${escapeHtml(m.specification || '')}</td>`;
                tableHtml += `<td style="border:1px solid #333;padding:8px;vertical-align:middle;text-align:right;">${m.total_quantity} ${escapeHtml(m.unit || '')}</td>`;
                tableHtml += '</tr>';
                grandTotal += parseFloat(m.total_quantity) || 0;
            });
        });

        tableHtml += '<tr style="background-color:#f0f0f0;font-weight:bold;">';
        tableHtml += '<td style="border:1px solid #333;padding:8px;text-align:center;">合计</td>';
        tableHtml += '<td style="border:1px solid #333;padding:8px;text-align:left;"></td>';
        tableHtml += '<td style="border:1px solid #333;padding:8px;text-align:left;"></td>';
        tableHtml += `<td style="border:1px solid #333;padding:8px;text-align:right;">${grandTotal}</td>`;
        tableHtml += '</tr>';
    }

    return `
        <div style="margin-bottom:12px;padding:12px;background:linear-gradient(135deg,rgba(240,147,251,0.1) 0%,rgba(245,87,108,0.1) 100%);border-radius:8px;">
            <div style="display:flex;justify-content:space-between;align-items:center;">
                <div>
                    <div style="font-weight:600;margin-bottom:6px;font-size:14px;"><i class="fas fa-truck" style="color:#f093fb;"></i> 供应商采购订单汇总</div>
                    <div style="font-size:12px;color:var(--pc-text-secondary);">
                        已选择 <strong style="color:#f093fb;">${data.order_count||orderSelectedIds.size}</strong> 个订单，涵盖 <strong style="color:#f093fb;">${supplierOrder.length}</strong> 家供应商，共 <strong style="color:#f093fb;">${data.materials?.length||0}</strong> 种物料
                    </div>
                </div>
            </div>
        </div>

        <div style="max-height:calc(100vh - 320px);overflow:auto;">
            <table style="width:100%;border-collapse:collapse;font-family:SimSun,宋体;font-size:13px;background:#fff;">
                <thead>
                    <tr style="background-color:#e6e6e6;">
                        <th style="border:1px solid #333;padding:6px 8px;text-align:center;font-weight:bold;width:12%;">供应商</th>
                        <th style="border:1px solid #333;padding:6px 8px;text-align:center;font-weight:bold;width:30%;">物料名称</th>
                        <th style="border:1px solid #333;padding:6px 8px;text-align:center;font-weight:bold;width:28%;">规格型号</th>
                        <th style="border:1px solid #333;padding:6px 8px;text-align:center;font-weight:bold;width:30%;">数量</th>
                    </tr>
                </thead>
                <tbody>
                    ${tableHtml || '<tr><td style="border:1px solid #333;padding:20px;text-align:center;" colspan="4">暂无数据</td></tr>'}
                </tbody>
            </table>
        </div>

        <div style="margin-top:15px;padding-top:12px;border-top:1px solid var(--pc-border);display:flex;justify-content:space-between;align-items:center;">
            <div style="display:flex;gap:8px;">
                <button class="pc-btn pc-btn-sm pc-btn-success" onclick="exportSupplierSummary()">
                    <i class="fas fa-file-archive"></i> 导出汇总
                </button>
            </div>
            <div style="display:flex;gap:8px;">
                <button class="pc-btn pc-btn-outline pc-btn-sm" onclick="closeModal('statusHistoryModal')">关闭</button>
                <button class="pc-btn pc-btn-sm pc-btn-primary" onclick="printSupplierSummary()">
                    <i class="fas fa-print"></i> 打印预览
                </button>
            </div>
        </div>
    `;
}

function toggleFactoryEditMode(enable) {
    if (!enable) {
        currentFactorySummaryData = JSON.parse(JSON.stringify(factorySummaryOriginalData));
        factorySummaryEdits = [];
    }
    factorySummaryEditMode = enable;
    renderSummaryModal();
}

function updateFactoryQuantity(groupIndex, supplierIndex, fabricIndex, newValue, itemId, itemIdsStr, originalQuantitiesStr) {
    const value = parseFloat(newValue) || 0;
    if (value < 0) {
        showToast('数量不能为负数', 'error');
        return;
    }
    if (value > 99999999) {
        showToast('数量超出范围', 'error');
        return;
    }
    if (currentFactorySummaryData && currentFactorySummaryData.groups && currentFactorySummaryData.groups[groupIndex]) {
        const supplier = currentFactorySummaryData.groups[groupIndex].suppliers[supplierIndex];
        if (supplier && supplier.fabrics[fabricIndex]) {
            supplier.fabrics[fabricIndex].quantity = value;
        }
    }

    // 处理合并项：按原始比例分配新数量到各子项
    const itemIds = itemIdsStr ? itemIdsStr.split(',').map(id => parseInt(id)) : [];
    let originalQuantities = {};
    if (originalQuantitiesStr) {
        try {
            originalQuantities = JSON.parse(decodeURIComponent(originalQuantitiesStr));
        } catch(e) {
            // 解析失败，使用简单分配
        }
    }

    if (itemIds.length > 1 && Object.keys(originalQuantities).length > 0) {
        // 合并项：按原始比例分配
        const totalOriginal = Object.values(originalQuantities).reduce((a, b) => a + parseFloat(b), 0);
        if (totalOriginal > 0) {
            const ratio = value / totalOriginal;
            for (const id of itemIds) {
                const originalQty = parseFloat(originalQuantities[String(id)]) || 0;
                const newQty = Math.round(originalQty * ratio * 100) / 100;
                const existingEdit = factorySummaryEdits.find(e => e.item_id === parseInt(id));
                if (existingEdit) {
                    existingEdit.quantity = newQty;
                } else {
                    factorySummaryEdits.push({ item_id: parseInt(id), quantity: newQty });
                }
            }
        }
    } else if (itemId) {
        // 单项：直接更新
        const existingEdit = factorySummaryEdits.find(e => e.item_id === parseInt(itemId));
        if (existingEdit) {
            existingEdit.quantity = value;
        } else {
            factorySummaryEdits.push({ item_id: parseInt(itemId), quantity: value });
        }
    }

    // ── 实时同步到供应商汇总数据 ──
    syncFactoryToSupplier();

    recalculateFactoryTotal();
}

// ── 工厂订单数量变更 → 实时同步供应商汇总 ──
function syncFactoryToSupplier() {
    if (!currentSupplierSummaryData || !currentSupplierSummaryData.materials) return;

    // 构建 (material_name, specification, supplier_name) → 新数量 的映射
    // 从工厂数据中，按供应商+物料维度汇总编辑后的数量
    const materialQtyMap = {};
    if (currentFactorySummaryData && currentFactorySummaryData.groups) {
        currentFactorySummaryData.groups.forEach(group => {
            (group.suppliers || []).forEach(supplier => {
                (supplier.fabrics || []).forEach(fabric => {
                    // 查找此 fabric 对应的 edit
                    const itemIds = fabric.item_ids || (fabric.item_id ? [fabric.item_id] : []);
                    let newQty = 0;
                    let hasEdit = false;

                    if (itemIds.length > 0 && fabric.original_quantities) {
                        // 合并项：按子项逐个查找 edit
                        Object.entries(fabric.original_quantities).forEach(([id, origQty]) => {
                            const editEntry = factorySummaryEdits.find(e => e.item_id === parseInt(id));
                            if (editEntry) {
                                newQty += editEntry.quantity;
                                hasEdit = true;
                            } else {
                                newQty += parseFloat(origQty);
                            }
                        });
                    } else if (itemIds.length === 1) {
                        const editEntry = factorySummaryEdits.find(e => e.item_id === parseInt(itemIds[0]));
                        if (editEntry) {
                            newQty = editEntry.quantity;
                            hasEdit = true;
                        } else {
                            newQty = parseFloat(fabric.quantity);
                        }
                    }

                    if (hasEdit) {
                        const key = `${fabric.fabric_name}||${fabric.specification || ''}||${supplier.supplier_name}`;
                        if (!materialQtyMap[key]) {
                            materialQtyMap[key] = 0;
                        }
                        materialQtyMap[key] += newQty;
                    }
                });
            });
        });
    }

    // 更新供应商汇总数据中匹配的物料数量
    currentSupplierSummaryData.materials.forEach(m => {
        const key = `${m.material_name}||${m.specification || ''}||${m.supplier_name}`;
        if (materialQtyMap[key] !== undefined) {
            m.total_quantity = Math.round(materialQtyMap[key] * 100) / 100;
        }
    });
}

function recalculateFactoryTotal() {
    let grandTotal = 0;
    if (currentFactorySummaryData && currentFactorySummaryData.groups) {
        currentFactorySummaryData.groups.forEach(group => {
            (group.suppliers || []).forEach(supplier => {
                (supplier.fabrics || []).forEach(fabric => {
                    grandTotal += parseFloat(fabric.quantity) || 0;
                });
            });
        });
    }
    const totalEl = document.getElementById('factoryGrandTotal');
    if (totalEl) {
        totalEl.textContent = grandTotal.toFixed(2);
    }
}

function saveFactoryEdits() {
    if (factorySummaryEdits.length === 0) {
        showToast('没有检测到任何修改', 'warning');
        factorySummaryEditMode = false;
        renderSummaryModal();
        return;
    }
    
    const validEdits = factorySummaryEdits.filter(e => e.item_id && e.quantity >= 0);
    if (validEdits.length === 0) {
        showToast('没有有效的修改数据', 'error');
        return;
    }
    
    apiPost('/orders/factory-summary/save', { edits: validEdits }).then(res => {
        if (res.success) {
            showToast(res.message || '修改已保存', 'success');
            factorySummaryOriginalData = JSON.parse(JSON.stringify(currentFactorySummaryData));
            factorySummaryEdits = [];
            factorySummaryEditMode = false;
            renderSummaryModal();
            
            if (res.updated_count > 0) {
                refreshOrderList();
            }
        } else {
            showToast(res.message || '保存失败', 'error');
        }
    }).catch(err => {
        showToast('保存失败: ' + (err.message || '网络错误'), 'error');
    });
}

function refreshOrderList() {
    loadOrdersSilently(orderCurrentPage);
}




async function printFactorySummary() {
    if (!currentFactorySummaryData) {
        showToast('请先生成汇总数据', 'error');
        return;
    }
    
    let tableHtml = '';
    let grandTotal = 0;
    
    if (currentFactorySummaryData.groups && currentFactorySummaryData.groups.length > 0) {
        currentFactorySummaryData.groups.forEach(group => {
            const suppliers = group.suppliers || [];
            const totalFabricRows = suppliers.reduce((sum, s) => sum + (s.fabrics ? s.fabrics.length : 0), 0);
            
            let globalFabricIdx = 0;
            suppliers.forEach(supplier => {
                const fabrics = supplier.fabrics || [];
                fabrics.forEach((fabric, fabricIndex) => {
                    tableHtml += '<tr>';
                    if (globalFabricIdx === 0) {
                        tableHtml += `<td style="border:1px solid #333;padding:8px;vertical-align:middle;text-align:center;font-weight:bold;" rowspan="${totalFabricRows}">${escapeHtml(group.customer_name)}</td>`;
                        tableHtml += `<td style="border:1px solid #333;padding:8px;vertical-align:middle;text-align:center;" rowspan="${totalFabricRows}">${escapeHtml(group.product_name)}</td>`;
                        tableHtml += `<td style="border:1px solid #333;padding:8px;vertical-align:middle;text-align:center;" rowspan="${totalFabricRows}">${parseFloat(group.product_quantity || group.order_quantity || 0) % 1 === 0 ? parseInt(group.product_quantity || group.order_quantity) : parseFloat(group.product_quantity || group.order_quantity).toFixed(2).replace(/\.?0+$/, '')}</td>`;
                    }
                    if (fabricIndex === 0) {
                        tableHtml += `<td style="border:1px solid #333;padding:8px;vertical-align:middle;text-align:center;" rowspan="${fabrics.length}">${escapeHtml(supplier.supplier_name)}</td>`;
                    }
                    tableHtml += `<td style="border:1px solid #333;padding:8px;vertical-align:middle;text-align:left;">${escapeHtml(fabric.fabric_name)}</td>`;
                    tableHtml += `<td style="border:1px solid #333;padding:8px;vertical-align:middle;text-align:left;">${escapeHtml(fabric.specification || '')}</td>`;
                    tableHtml += `<td style="border:1px solid #333;padding:8px;vertical-align:middle;text-align:right;">${fabric.quantity} ${escapeHtml(fabric.unit)}</td>`;
                    tableHtml += '</tr>';
                    grandTotal += parseFloat(fabric.quantity) || 0;
                    globalFabricIdx++;
                });
            });
        });
        
        tableHtml += '<tr style="background-color:#f0f0f0;font-weight:bold;">';
        tableHtml += '<td style="border:1px solid #333;padding:8px;text-align:center;" colspan="4">合计</td>';
        tableHtml += '<td style="border:1px solid #333;padding:8px;text-align:left;"></td>';
        tableHtml += '<td style="border:1px solid #333;padding:8px;text-align:left;"></td>';
        tableHtml += `<td style="border:1px solid #333;padding:8px;text-align:right;">${grandTotal}</td>`;
        tableHtml += '</tr>';
    }
    
    const printHtml = `
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>工厂内部采购订单汇总</title>
    <style>
        body { font-family: SimSun, 宋体; font-size: 13px; padding: 20px; }
        table { width: 100%; border-collapse: collapse; }
        th, td { border: 1px solid #333; padding: 8px; }
        th { background-color: #e6e6e6; font-weight: bold; }
        .header { margin-bottom: 20px; padding-bottom: 10px; border-bottom: 2px solid #333; }
        .header h2 { margin: 0; padding: 0; }
        @media print {
            body { padding: 0; }
        }
    </style>
</head>
<body>
    <div class="header">
        <h2>工厂内部采购订单汇总</h2>
        <p>已选择 ${currentFactorySummaryData.order_count || orderSelectedIds.size} 个订单 | 打印时间: ${new Date().toLocaleString()}</p>
    </div>
    <table>
        <thead>
            <tr>
                <th style="width:10%;">客户</th>
                <th style="width:16%;">产品名称</th>
                <th style="width:7%;">订单数量</th>
                <th style="width:10%;">供应商</th>
                <th style="width:25%;">布料名称</th>
                <th style="width:17%;">规格型号</th>
                <th style="width:15%;">数量</th>
            </tr>
        </thead>
        <tbody>
            ${tableHtml || '<tr><td colspan="7" style="text-align:center;padding:20px;">暂无数据</td></tr>'}
        </tbody>
    </table>
</body>
</html>`;
    
    const w = window.open('', '_blank');
    w.document.write(printHtml);
    w.document.close();
    w.onafterprint = () => w.close();
    w.onload = () => setTimeout(() => w.print(), 500);
}

async function printSupplierSummary() {
    if (!currentSupplierSummaryData) {
        showToast('请先生成汇总数据', 'error');
        return;
    }

    const data = currentSupplierSummaryData;

    // 按 supplier_name 分组
    const supplierGroups = {};
    let supplierOrder = [];
    if (data.materials) {
        data.materials.forEach(m => {
            const supplier = m.supplier_name || '未指定供应商';
            if (!supplierGroups[supplier]) {
                supplierGroups[supplier] = [];
                supplierOrder.push(supplier);
            }
            supplierGroups[supplier].push(m);
        });
    }

    let tableHtml = '';
    let grandTotal = 0;

    if (supplierOrder.length > 0) {
        supplierOrder.forEach(supplierName => {
            const materials = supplierGroups[supplierName];
            const materialCount = materials.length;

            materials.forEach((m, mIndex) => {
                tableHtml += '<tr>';
                if (mIndex === 0) {
                    tableHtml += `<td style="border:1px solid #333;padding:8px;vertical-align:middle;text-align:center;font-weight:bold;" rowspan="${materialCount}">${escapeHtml(supplierName)}</td>`;
                }
                tableHtml += `<td style="border:1px solid #333;padding:8px;vertical-align:middle;text-align:left;">${escapeHtml(m.material_name)}</td>`;
                tableHtml += `<td style="border:1px solid #333;padding:8px;vertical-align:middle;text-align:left;">${escapeHtml(m.specification || '')}</td>`;
                tableHtml += `<td style="border:1px solid #333;padding:8px;vertical-align:middle;text-align:right;">${m.total_quantity} ${escapeHtml(m.unit || '')}</td>`;
                tableHtml += '</tr>';
                grandTotal += parseFloat(m.total_quantity) || 0;
            });
        });

        tableHtml += '<tr style="background-color:#f0f0f0;font-weight:bold;">';
        tableHtml += '<td style="border:1px solid #333;padding:8px;text-align:center;">合计</td>';
        tableHtml += '<td style="border:1px solid #333;padding:8px;text-align:left;"></td>';
        tableHtml += '<td style="border:1px solid #333;padding:8px;text-align:left;"></td>';
        tableHtml += `<td style="border:1px solid #333;padding:8px;text-align:right;">${grandTotal}</td>`;
        tableHtml += '</tr>';
    }

    const printHtml = `
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>供应商采购订单汇总</title>
    <style>
        body { font-family: SimSun, 宋体; font-size: 13px; padding: 20px; }
        table { width: 100%; border-collapse: collapse; }
        th, td { border: 1px solid #333; padding: 8px; }
        th { background-color: #e6e6e6; font-weight: bold; }
        .header { margin-bottom: 20px; padding-bottom: 10px; border-bottom: 2px solid #333; }
        .header h2 { margin: 0; padding: 0; }
        @media print {
            body { padding: 0; }
        }
    </style>
</head>
<body>
    <div class="header">
        <h2>供应商采购订单汇总</h2>
        <p>已选择 ${data.order_count || orderSelectedIds.size} 个订单 | 涵盖 ${supplierOrder.length} 家供应商 | 打印时间: ${new Date().toLocaleString()}</p>
    </div>
    <table>
        <thead>
            <tr>
                <th style="width:12%;">供应商</th>
                <th style="width:30%;">物料名称</th>
                <th style="width:28%;">规格型号</th>
                <th style="width:30%;">数量</th>
            </tr>
        </thead>
        <tbody>
            ${tableHtml || '<tr><td colspan="4" style="text-align:center;padding:20px;">暂无数据</td></tr>'}
        </tbody>
    </table>
</body>
</html>`;

    const w = window.open('', '_blank');
    w.document.write(printHtml);
    w.document.close();
    w.onafterprint = () => w.close();
    w.onload = () => setTimeout(() => w.print(), 500);
}

async function exportFactorySummary() {
    if (!currentFactorySummaryData) {
        showToast('请先生成汇总数据', 'error');
        return;
    }

    showToast('正在导出Excel...', 'info');

    const excelHtml = buildFactorySummaryExcelHtml();

    // Add UTF-8 BOM for Excel/WPS compatibility with Chinese characters
    const bom = '\uFEFF';
    downloadFile(bom + excelHtml, '工厂内部采购汇总.xls', 'application/vnd.ms-excel');
}

function showExportPreview() {
    const data = currentFactorySummaryData;
    const orderCount = data.order_count || orderSelectedIds.size;
    let groupCount = data.groups ? data.groups.length : 0;
    let fabricCount = 0;
    let grandTotal = 0;

    if (data.groups) {
        data.groups.forEach(group => {
            const suppliers = group.suppliers || [];
            suppliers.forEach(s => {
                fabricCount += (s.fabrics ? s.fabrics.length : 0);
                (s.fabrics || []).forEach(f => { grandTotal += parseFloat(f.quantity) || 0; });
            });
        });
    }

    // Build preview table matching the export format exactly
    let previewTableHtml = '';
    if (data.groups && data.groups.length > 0) {
        data.groups.forEach(group => {
            const suppliers = group.suppliers || [];
            const totalFabricRows = suppliers.reduce((sum, s) => sum + (s.fabrics ? s.fabrics.length : 0), 0);
            
            let globalFabricIdx = 0;
            suppliers.forEach(supplier => {
                const fabrics = supplier.fabrics || [];
                fabrics.forEach((fabric, fabricIndex) => {
                    previewTableHtml += '<tr>';
                    if (globalFabricIdx === 0) {
                        previewTableHtml += `<td style="border:1px solid #333;padding:6px 8px;vertical-align:middle;text-align:center;font-weight:bold;background:#f9f9f9;" rowspan="${totalFabricRows}">${escapeHtml(group.customer_name)}</td>`;
                        previewTableHtml += `<td style="border:1px solid #333;padding:6px 8px;vertical-align:middle;text-align:center;background:#f9f9f9;" rowspan="${totalFabricRows}">${escapeHtml(group.product_name)}</td>`;
                        previewTableHtml += `<td style="border:1px solid #333;padding:6px 8px;vertical-align:middle;text-align:center;background:#f9f9f9;" rowspan="${totalFabricRows}">${parseFloat(group.product_quantity || group.order_quantity || 0) % 1 === 0 ? parseInt(group.product_quantity || group.order_quantity) : parseFloat(group.product_quantity || group.order_quantity).toFixed(2).replace(/\.?0+$/, '')}</td>`;
                    }
                    if (fabricIndex === 0) {
                        previewTableHtml += `<td style="border:1px solid #333;padding:6px 8px;vertical-align:middle;text-align:center;background:#f9f9f9;" rowspan="${fabrics.length}">${escapeHtml(supplier.supplier_name)}</td>`;
                    }
                    previewTableHtml += `<td style="border:1px solid #333;padding:6px 8px;vertical-align:middle;text-align:left;">${escapeHtml(fabric.fabric_name)}</td>`;
                    previewTableHtml += `<td style="border:1px solid #333;padding:6px 8px;vertical-align:middle;text-align:left;">${escapeHtml(fabric.specification || '')}</td>`;
                    previewTableHtml += `<td style="border:1px solid #333;padding:6px 8px;vertical-align:middle;text-align:right;">${fabric.quantity} ${escapeHtml(fabric.unit || '')}</td>`;
                    previewTableHtml += '</tr>';
                    grandTotal += parseFloat(fabric.quantity) || 0;
                    globalFabricIdx++;
                });
            });
        });
        previewTableHtml += '<tr style="background-color:#f0f0f0;font-weight:bold;">';
        previewTableHtml += '<td style="border:1px solid #333;padding:6px 8px;text-align:center;" colspan="4">合计</td>';
        previewTableHtml += '<td style="border:1px solid #333;padding:6px 8px;"></td>';
        previewTableHtml += '<td style="border:1px solid #333;padding:6px 8px;"></td>';
        previewTableHtml += `<td style="border:1px solid #333;padding:6px 8px;text-align:right;">${grandTotal}</td>`;
        previewTableHtml += '</tr>';
    }

    const previewHtml = `
        <div style="padding:16px;">
            <!-- Export info summary -->
            <div style="margin-bottom:16px;padding:12px 16px;background:#f8f9fa;border-radius:8px;display:flex;gap:24px;flex-wrap:wrap;">
                <div><span style="color:var(--pc-text-secondary);font-size:12px;">导出格式</span><div style="font-weight:600;">Excel (.xls)</div></div>
                <div><span style="color:var(--pc-text-secondary);font-size:12px;">订单数量</span><div style="font-weight:600;">${orderCount} 个</div></div>
                <div><span style="color:var(--pc-text-secondary);font-size:12px;">产品分组</span><div style="font-weight:600;">${groupCount} 组</div></div>
                <div><span style="color:var(--pc-text-secondary);font-size:12px;">物料明细</span><div style="font-weight:600;">${fabricCount} 条</div></div>
                <div><span style="color:var(--pc-text-secondary);font-size:12px;">数量合计</span><div style="font-weight:600;">${grandTotal}</div></div>
            </div>

            <!-- Format description -->
            <div style="margin-bottom:12px;padding:10px 14px;background:linear-gradient(135deg,rgba(102,126,234,0.08) 0%,rgba(118,75,162,0.08) 100%);border-radius:6px;font-size:12px;color:var(--pc-text-secondary);">
                <strong>导出列说明：</strong>
                客户 (按客户分组合并) → 产品名称 (按产品合并) → 订单数量 → 供应商 → 布料名称 → 规格型号 → 数量（含单位）
            </div>

            <!-- Preview table -->
            <div style="max-height:400px;overflow:auto;border:1px solid #ddd;border-radius:6px;">
                <table style="width:100%;border-collapse:collapse;font-family:SimSun,宋体;font-size:12px;background:#fff;">
                    <thead>
                        <tr style="background-color:#e6e6e6;">
                            <th style="border:1px solid #333;padding:6px 8px;text-align:center;font-weight:bold;width:10%;">客户</th>
                            <th style="border:1px solid #333;padding:6px 8px;text-align:center;font-weight:bold;width:16%;">产品名称</th>
                            <th style="border:1px solid #333;padding:6px 8px;text-align:center;font-weight:bold;width:7%;">订单数量</th>
                            <th style="border:1px solid #333;padding:6px 8px;text-align:center;font-weight:bold;width:10%;">供应商</th>
                            <th style="border:1px solid #333;padding:6px 8px;text-align:center;font-weight:bold;width:25%;">布料名称</th>
                            <th style="border:1px solid #333;padding:6px 8px;text-align:center;font-weight:bold;width:17%;">规格型号</th>
                            <th style="border:1px solid #333;padding:6px 8px;text-align:center;font-weight:bold;width:15%;">数量</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${previewTableHtml || '<tr><td colspan="7" style="text-align:center;padding:20px;">暂无数据</td></tr>'}
                    </tbody>
                </table>
            </div>
        </div>
    `;

    document.getElementById('exportPreviewContent').innerHTML = previewHtml;
    openModal('exportPreviewModal');
}

function confirmExportFromPreview() {
    closeModal('exportPreviewModal');
    showToast('正在导出Excel...', 'info');

    const excelHtml = buildFactorySummaryExcelHtml();

    // Add UTF-8 BOM for Excel/WPS compatibility with Chinese characters
    const bom = '\uFEFF';
    downloadFile(bom + excelHtml, '工厂内部采购汇总.xls', 'application/vnd.ms-excel');
}

function buildFactorySummaryExcelHtml() {
    let tableBodyHtml = '';
    let grandTotal = 0;
    const data = currentFactorySummaryData;

    if (data.groups && data.groups.length > 0) {
        data.groups.forEach(group => {
            const suppliers = group.suppliers || [];
            const totalFabricRows = suppliers.reduce((sum, s) => sum + (s.fabrics ? s.fabrics.length : 0), 0);
            
            let globalFabricIdx = 0;
            suppliers.forEach(supplier => {
                const fabrics = supplier.fabrics || [];
                fabrics.forEach((fabric, fabricIndex) => {
                    tableBodyHtml += '<tr height="38" style="height:28.30pt;mso-height-source:userset;mso-height-alt:566;">';
                    if (globalFabricIdx === 0) {
                        tableBodyHtml += `<td style="font-weight:bold;text-align:center;vertical-align:middle;border:1.0pt solid #000000;border-right:1.0pt solid #000000;border-bottom:1.0pt solid #000000;" rowspan="${totalFabricRows}">${escapeXml(group.customer_name)}</td>`;
                        tableBodyHtml += `<td rowspan="${totalFabricRows}" style="text-align:center;vertical-align:middle;border-right:1.0pt solid #000000;border-bottom:1.0pt solid #000000;">${escapeXml(group.product_name)}</td>`;
                        tableBodyHtml += `<td rowspan="${totalFabricRows}" style="text-align:center;vertical-align:middle;border-right:1.0pt solid #000000;border-bottom:1.0pt solid #000000;">${parseFloat(group.product_quantity || group.order_quantity || 0) % 1 === 0 ? parseInt(group.product_quantity || group.order_quantity) : parseFloat(group.product_quantity || group.order_quantity).toFixed(2).replace(/\.?0+$/, '')}</td>`;
                    }
                    if (fabricIndex === 0) {
                        tableBodyHtml += `<td rowspan="${fabrics.length}" style="text-align:center;vertical-align:middle;border-right:1.0pt solid #000000;border-bottom:1.0pt solid #000000;">${escapeXml(supplier.supplier_name)}</td>`;
                    }
                    tableBodyHtml += `<td style="text-align:left;vertical-align:middle;border-right:1.0pt solid #000000;border-bottom:1.0pt solid #000000;">${escapeXml(fabric.fabric_name)}</td>`;
                    tableBodyHtml += `<td style="text-align:left;vertical-align:middle;border-right:1.0pt solid #000000;border-bottom:1.0pt solid #000000;">${escapeXml(fabric.specification || '')}</td>`;
                    tableBodyHtml += `<td style="text-align:right;vertical-align:middle;border-right:1.0pt solid #000000;border-bottom:1.0pt solid #000000;">${fabric.quantity} ${escapeXml(fabric.unit || '')}</td>`;
                    tableBodyHtml += '</tr>';
                    grandTotal += parseFloat(fabric.quantity) || 0;
                    globalFabricIdx++;
                });
            });
        });

        tableBodyHtml += `<tr class="total-row" height="38" style="height:28.30pt;mso-height-source:userset;mso-height-alt:566;background-color:#F0F0F0;font-weight:bold;">`;
        tableBodyHtml += '<td colspan="4" style="text-align:center;border:1.0pt solid #000000;">合计</td>';
        tableBodyHtml += '<td style="border:1.0pt solid #000000;"></td>';
        tableBodyHtml += '<td style="border:1.0pt solid #000000;"></td>';
        tableBodyHtml += `<td style="text-align:right;border:1.0pt solid #000000;">${grandTotal}</td>`;
        tableBodyHtml += '</tr>';
    }

    const now = new Date();
    const exportTime = `${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,'0')}-${String(now.getDate()).padStart(2,'0')} ${String(now.getHours()).padStart(2,'0')}:${String(now.getMinutes()).padStart(2,'0')}:${String(now.getSeconds()).padStart(2,'0')}`;
    const orderCount = data.order_count || orderSelectedIds.size;

    return `<html xmlns:o="urn:schemas-microsoft-com:office:office"
      xmlns:x="urn:schemas-microsoft-com:office:excel"
      xmlns="http://www.w3.org/TR/REC-html40">
<head>
    <meta charset="utf-8">
    <title>工厂内部采购订单汇总</title>
    <!--[if gte mso 9]><xml>
    <x:ExcelWorkbook>
        <x:ExcelWorksheets>
            <x:ExcelWorksheet>
                <x:Name>采购汇总</x:Name>
                <x:WorksheetOptions>
                    <x:DefaultRowHeight>270</x:DefaultRowHeight>
                    <x:DoNotDisplayGridlines/>
                    <x:FitToPage/>
                    <x:Zoom>84</x:Zoom>
                    <x:Print>
                        <x:ValidPrinterInfo/>
                        <x:Scale>72</x:Scale>
                    </x:Print>
                    <x:PageSetup>
                        <x:Layout x:Orientation="Landscape"/>
                        <x:PageMargins x:Bottom="0" x:Left="0" x:Right="0" x:Top="0"/>
                    </x:PageSetup>
                </x:WorksheetOptions>
            </x:ExcelWorksheet>
        </x:ExcelWorksheets>
    </x:ExcelWorkbook>
    </xml><![endif]-->
    <style>
        @page { margin: 0in; }
        body {
            font-family: 宋体, SimSun;
            margin: 0;
            padding: 0;
        }
        .header { text-align: center; margin-bottom: 10px; }
        .header h1 { margin: 0; color: #333; font-size: 24pt; font-weight: bold; }
        .header h2 { margin: 5px 0 0 0; color: #333; font-size: 18pt; font-weight: bold; }
        .meta { text-align: right; color: #666; font-size: 9pt; margin-bottom: 8px; }
        table {
            width: 850.15pt;
            border-collapse: collapse;
            table-layout: fixed;
        }
        th, td {
            border: 1.0pt solid #000000;
            padding: 1px;
            text-align: center;
            vertical-align: middle;
            font-size: 10.5pt;
            mso-number-format: "@";
            white-space: normal;
        }
        th { background: #E6E6E6; font-weight: bold; }
        .total-row { background-color: #F0F0F0; font-weight: bold; }
        col { mso-width-source: userset; }
    </style>
</head>
<body>
    <div class="header">
        <h1>东莞市滨发玩具有限公司</h1>
        <h2>工厂内部采购订单汇总</h2>
    </div>
    <div class="meta">已选择 ${orderCount} 个订单 | 导出时间: ${exportTime}</div>
    <table>
        <colgroup>
            <col width="113" style="mso-width-source:userset;mso-width-alt:3626;">
            <col width="378" style="mso-width-source:userset;mso-width-alt:12093;">
            <col width="113" style="mso-width-source:userset;mso-width-alt:3626;">
            <col width="113" style="mso-width-source:userset;mso-width-alt:3626;">
            <col width="151" style="mso-width-source:userset;mso-width-alt:4836;">
            <col width="151" style="mso-width-source:userset;mso-width-alt:4836;">
            <col width="113" style="mso-width-source:userset;mso-width-alt:3626;">
        </colgroup>
        <thead>
            <tr height="28" style="height:21.00pt;mso-height-source:userset;mso-height-alt:420;">
                <th>客户</th>
                <th>产品名称</th>
                <th>订单数量</th>
                <th>供应商</th>
                <th>布料名称</th>
                <th>规格型号</th>
                <th>数量</th>
            </tr>
        </thead>
        <tbody>
            ${tableBodyHtml || '<tr><td colspan="7" style="text-align:center;">暂无数据</td></tr>'}
        </tbody>
    </table>
</body>
</html>`;
}

function escapeXml(str) {
    if (!str) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

async function exportSupplierSummary() {
    if (orderSelectedIds.size === 0) {
        showToast('请先选择订单', 'error');
        return;
    }

    showToast('正在生成汇总文件，请稍候...', 'info');

    try {
        const response = await fetch(FASTAPI_BASE + '/orders/supplier-summary-export', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            credentials: 'same-origin',
            body: JSON.stringify({ ids: Array.from(orderSelectedIds) })
        });

        if (!response.ok) {
            const errData = await response.json().catch(() => ({}));
            showToast(errData.message || '导出失败', 'error');
            return;
        }

        const blob = await response.blob();
        const disposition = response.headers.get('Content-Disposition');
        let filename = '供应商采购订单汇总.zip';
        if (disposition) {
            const match = disposition.match(/filename\*?=(?:UTF-8'')?(.+)/i);
            if (match) {
                filename = decodeURIComponent(match[1].replace(/['"]/g, ''));
            }
        }

        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = filename;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        URL.revokeObjectURL(url);

        showToast('导出成功，已下载压缩包', 'success');
    } catch (err) {
        console.error('导出供应商汇总失败:', err);
        showToast('导出失败，请稍后重试', 'error');
    }
}

function downloadFile(content, filename, mimeType) {
    const blob = new Blob([content], { type: `${mimeType};charset=utf-8` });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
    showToast(`已导出 ${filename}`, 'success');
}

document.addEventListener('keydown', e => {
    if (e.altKey && e.key === '1') { e.preventDefault(); switchTab('orders'); }
    if (e.altKey && e.key === '2') { e.preventDefault(); switchTab('history'); }
});

initPurchaseCenter();

