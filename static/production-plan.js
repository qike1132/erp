/**
 * 排产计划管理 - 前端交互逻辑
 *
 * 功能：69码联动验证、库存对比状态渲染、CRUD操作
 */
(function () {
    'use strict';

    // ==================== 工具函数 ====================

    function getCookie(name) {
        const match = document.cookie.match(new RegExp('(^| )' + name + '=([^;]+)'));
        return match ? decodeURIComponent(match[2]) : null;
    }

    function apiFetch(url, options = {}) {
        const defaults = {
            credentials: 'include',
            headers: { 'Content-Type': 'application/json' },
        };
        return fetch(url, { ...defaults, ...options })
            .then(r => {
                if (!r.ok) return r.json().then(e => { throw new Error(e.detail || `请求失败 (${r.status})`); });
                return r.json();
            });
    }

    function formatNumber(n) {
        if (n === null || n === undefined || n === '') return '0';
        return Number(n).toLocaleString();
    }

    // ==================== 初始化 ====================

    const now = new Date();
    const filterYear = document.getElementById('filterYear');
    const filterMonth = document.getElementById('filterMonth');

    if (filterYear) filterYear.value = now.getFullYear();
    if (filterMonth) filterMonth.value = now.getMonth() + 1;

    // 默认加载当月数据
    loadPlans();

    // ==================== 事件绑定 ====================

    // 查询按钮
    document.getElementById('searchBtn').addEventListener('click', loadPlans);

    // 表单提交
    document.getElementById('planForm').addEventListener('submit', function (e) {
        e.preventDefault();
        createPlan();
    });

    // 重置按钮
    document.getElementById('resetBtn').addEventListener('click', function () {
        document.getElementById('barcodeHint').textContent = '';
        document.getElementById('barcodeHint').className = 'form-text';
    });

    // 69码输入联动（防抖）
    let barcodeTimer = null;
    document.getElementById('barcode').addEventListener('input', function () {
        clearTimeout(barcodeTimer);
        const val = this.value.trim();
        const hint = document.getElementById('barcodeHint');

        if (!val) {
            hint.textContent = '';
            hint.className = 'form-text';
            document.getElementById('product_name').value = '';
            return;
        }

        hint.textContent = '验证中...';
        hint.className = 'form-text barcode-checking';

        barcodeTimer = setTimeout(() => validateBarcode(val), 300);
    });

    // 69码自动补全下拉
    document.getElementById('barcode').addEventListener('focus', function () {
        if (this.value.trim().length >= 2) {
            searchProducts(this.value.trim());
        }
    });

    // 点击外部关闭下拉
    document.addEventListener('click', function (e) {
        const dropdown = document.getElementById('barcodeDropdown');
        if (dropdown && !dropdown.contains(e.target) && e.target.id !== 'barcode') {
            dropdown.style.display = 'none';
        }
    });

    // 编辑保存
    document.getElementById('saveEditBtn').addEventListener('click', saveEdit);

    // ==================== 69码联动 ====================

    function validateBarcode(barcode) {
        const hint = document.getElementById('barcodeHint');
        const productNameInput = document.getElementById('product_name');

        apiFetch(`/api/v1/production-plans/validate-barcode?q=${encodeURIComponent(barcode)}`)
            .then(data => {
                if (data.valid) {
                    hint.textContent = '验证通过';
                    hint.className = 'form-text barcode-valid';
                    if (data.product_name && !productNameInput.value) {
                        productNameInput.value = data.product_name;
                    }
                } else {
                    hint.textContent = data.message || '未找到对应产品';
                    hint.className = 'form-text barcode-invalid';
                }
            })
            .catch(err => {
                hint.textContent = '验证失败: ' + err.message;
                hint.className = 'form-text barcode-invalid';
            });
    }

    function searchProducts(query) {
        const dropdown = document.getElementById('barcodeDropdown');
        apiFetch(`/api/v1/aux/product-search?q=${encodeURIComponent(query)}`)
            .then(products => {
                if (!products || products.length === 0) {
                    dropdown.style.display = 'none';
                    return;
                }
                dropdown.innerHTML = products.map(p =>
                    `<div class="autocomplete-item" data-barcode="${p.barcode || ''}" data-name="${p.name}">` +
                    `<span class="fw-semibold">${p.name}</span>` +
                    `<small class="text-muted ms-2">${p.barcode || ''}</small>` +
                    `</div>`
                ).join('');
                dropdown.style.display = 'block';

                // 绑定点击
                dropdown.querySelectorAll('.autocomplete-item').forEach(item => {
                    item.addEventListener('click', function () {
                        document.getElementById('barcode').value = this.dataset.barcode;
                        document.getElementById('product_name').value = this.dataset.name;
                        dropdown.style.display = 'none';

                        // 触发验证
                        const hint = document.getElementById('barcodeHint');
                        hint.textContent = '验证通过';
                        hint.className = 'form-text barcode-valid';
                    });
                });
            })
            .catch(() => {
                dropdown.style.display = 'none';
            });
    }

    // ==================== CRUD ====================

    function createPlan() {
        const data = {
            customer_name: document.getElementById('customer_name').value.trim(),
            product_name: document.getElementById('product_name').value.trim(),
            barcode: document.getElementById('barcode').value.trim(),
            quantity: parseInt(document.getElementById('quantity').value, 10),
            plan_date: document.getElementById('plan_date').value,
            remark: document.getElementById('remark').value.trim(),
        };

        if (!data.customer_name) { showNotification('请选择客户名称', 'error'); return; }
        if (!data.barcode) { showNotification('请输入69码', 'error'); return; }
        if (!data.product_name) { showNotification('请输入产品名称', 'error'); return; }
        if (!data.quantity || data.quantity <= 0) { showNotification('数量必须为正整数', 'error'); return; }
        if (!data.plan_date) { showNotification('请选择计划日期', 'error'); return; }

        apiFetch('/api/v1/production-plans/create', {
            method: 'POST',
            body: JSON.stringify(data),
        })
            .then(result => {
                if (result.success) {
                    showNotification(result.message, 'success');
                    document.getElementById('planForm').reset();
                    document.getElementById('barcodeHint').textContent = '';
                    // 自动刷新当月数据
                    loadPlans();
                }
            })
            .catch(err => showNotification(err.message, 'error'));
    }

    // ==================== 加载排产计划列表 ====================

    function loadPlans() {
        const year = parseInt(filterYear.value, 10);
        const month = parseInt(filterMonth.value, 10);

        if (!year || !month) return;

        apiFetch(`/api/v1/production-plans/list?year=${year}&month=${month}`)
            .then(result => {
                renderSummary(result.monthly_summary);
                renderPlanTable(result.plans);
                document.getElementById('recordCount').textContent = `共 ${result.total} 条记录`;
            })
            .catch(err => showNotification('加载排产计划失败: ' + err.message, 'error'));
    }

    // ==================== 渲染汇总面板 ====================

    function renderSummary(summary) {
        if (!summary) return;

        const panel = document.getElementById('summaryPanel');
        panel.style.display = 'block';

        document.getElementById('totalPlanQty').textContent = formatNumber(summary.total_plan_qty);
        document.getElementById('totalInventoryQty').textContent = formatNumber(summary.total_inventory_qty);
        document.getElementById('warningCount').textContent = summary.warning_count;

        const diffEl = document.getElementById('totalDiff');
        const diff = summary.total_diff;
        diffEl.textContent = (diff > 0 ? '+' : '') + formatNumber(diff);
        diffEl.className = diff > 0 ? 'mb-0 text-danger' : 'mb-0 text-success';

        // 客户汇总
        const csContainer = document.getElementById('customerSummaryContainer');
        const csEl = document.getElementById('customerSummary');
        if (summary.customer_summary && Object.keys(summary.customer_summary).length > 0) {
            csContainer.style.display = 'block';
            csEl.innerHTML = Object.entries(summary.customer_summary).map(([name, data]) => {
                const isWarning = data.warning_count > 0;
                const statusClass = isWarning ? 'text-danger' : 'text-success';
                const statusIcon = isWarning
                    ? '<i class="fas fa-exclamation-triangle me-1"></i>库存不足'
                    : '<i class="fas fa-check-circle me-1"></i>库存充足';
                const diffVal = data.plan_qty - data.inventory_qty;
                const diffStr = diffVal > 0 ? `缺口 ${formatNumber(diffVal)}` : '充足';

                return `<div class="customer-summary-item d-flex justify-content-between align-items-center">
                    <div>
                        <span class="fw-semibold"><i class="fas fa-building text-primary me-1"></i>${name}</span>
                        <small class="ms-3 text-muted">排产: ${formatNumber(data.plan_qty)} | 库存: ${formatNumber(data.inventory_qty)}</small>
                    </div>
                    <div class="${statusClass}">
                        ${statusIcon} <small>${diffStr}</small>
                    </div>
                </div>`;
            }).join('');
        } else {
            csContainer.style.display = 'none';
        }
    }

    // ==================== 渲染明细表格 ====================

    function renderPlanTable(plans) {
        const tbody = document.getElementById('planTableBody');

        if (!plans || plans.length === 0) {
            tbody.innerHTML = `<tr>
                <td colspan="8" class="text-center py-4">
                    <i class="fas fa-inbox fa-3x mb-3 text-muted" style="opacity: 0.3;"></i>
                    <p class="text-muted mb-0">当月暂无排产计划数据</p>
                </td>
            </tr>`;
            return;
        }

        tbody.innerHTML = plans.map(p => {
            const isWarning = p.stock_status === 'warning';
            const rowClass = isWarning ? 'table-row-warning' : '';
            const diffStr = p.diff > 0 ? `+${formatNumber(p.diff)}` : formatNumber(p.diff);
            const diffClass = isWarning ? 'text-danger fw-bold' : 'text-success';

            const statusBadge = isWarning
                ? '<span class="badge bg-warning text-dark"><i class="fas fa-exclamation-triangle me-1"></i>库存不足</span>'
                : '<span class="badge bg-success"><i class="fas fa-check-circle me-1"></i>库存充足</span>';

            const statusLabel = { pending: '待确认', confirmed: '已确认', completed: '已完成' };

            return `<tr class="${rowClass}">
                <td><span class="fw-semibold"><i class="fas fa-building text-primary me-1"></i>${p.customer_name}</span></td>
                <td><div class="d-flex align-items-center"><i class="fas fa-cube text-secondary me-2"></i><div class="fw-semibold">${p.product_name}</div></div></td>
                <td><code>${p.barcode}</code></td>
                <td class="text-center fw-bold">${formatNumber(p.quantity)}</td>
                <td class="text-center">${formatNumber(p.inventory_qty)}</td>
                <td class="text-center ${diffClass}">${diffStr}</td>
                <td>${statusBadge}<br><small class="text-muted">${statusLabel[p.status] || p.status}</small></td>
                <td>
                    <button onclick="window._editPlan(${p.id}, '${p.customer_name.replace(/'/g, "\\'")}', '${p.product_name.replace(/'/g, "\\'")}', '${p.barcode}', ${p.quantity}, '${p.plan_date}', '${p.status}', '${(p.remark || '').replace(/'/g, "\\'")}')" class="btn btn-sm btn-outline-primary me-1">
                        <i class="fas fa-edit"></i>
                    </button>
                    <button onclick="window._deletePlan(${p.id})" class="btn btn-sm btn-outline-danger">
                        <i class="fas fa-trash"></i>
                    </button>
                </td>
            </tr>`;
        }).join('');
    }

    // ==================== 编辑 ====================

    window._editPlan = function (id, customerName, productName, barcode, quantity, planDate, status, remark) {
        document.getElementById('editId').value = id;
        document.getElementById('editCustomerName').value = customerName;
        document.getElementById('editProductName').value = productName;
        document.getElementById('editBarcode').value = barcode;
        document.getElementById('editQuantity').value = quantity;
        document.getElementById('editPlanDate').value = planDate;
        document.getElementById('editStatus').value = status;
        document.getElementById('editRemark').value = remark;

        new bootstrap.Modal(document.getElementById('editModal')).show();
    };

    function saveEdit() {
        const id = document.getElementById('editId').value;
        const data = {
            customer_name: document.getElementById('editCustomerName').value.trim(),
            product_name: document.getElementById('editProductName').value.trim(),
            barcode: document.getElementById('editBarcode').value.trim(),
            quantity: parseInt(document.getElementById('editQuantity').value, 10),
            plan_date: document.getElementById('editPlanDate').value,
            status: document.getElementById('editStatus').value,
            remark: document.getElementById('editRemark').value.trim(),
        };

        apiFetch(`/api/v1/production-plans/edit/${id}`, {
            method: 'PUT',
            body: JSON.stringify(data),
        })
            .then(result => {
                if (result.success) {
                    showNotification(result.message, 'success');
                    bootstrap.Modal.getInstance(document.getElementById('editModal')).hide();
                    loadPlans();
                }
            })
            .catch(err => showNotification(err.message, 'error'));
    }

    // ==================== 删除 ====================

    window._deletePlan = function (id) {
        if (!confirm('确认删除该排产计划？此操作不可恢复。')) return;

        apiFetch(`/api/v1/production-plans/delete/${id}`, { method: 'DELETE' })
            .then(result => {
                if (result.success) {
                    showNotification(result.message, 'success');
                    loadPlans();
                }
            })
            .catch(err => showNotification(err.message, 'error'));
    }

    // ==================== 通知（复用全局通知系统）====================

    function showNotification(message, type) {
        // 优先使用全局通知系统
        if (typeof GlobalNotification !== 'undefined' && GlobalNotification.show) {
            GlobalNotification.show(type || 'info', message);
            return;
        }
        if (typeof window.showGlobalNotification === 'function') {
            window.showGlobalNotification(message, type);
            return;
        }

        // 降级：使用 alert
        alert(message);
    }

})();
