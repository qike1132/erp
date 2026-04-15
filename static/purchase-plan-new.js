/**
 * 采购计划管理 - 前端交互逻辑（重构版）
 *
 * 功能：CSS Grid 日历、客户筛选（含图标）、库存状态 badge、
 *       出货进度条、批量上传预览+勾选+内联编辑、69码联动验证、CRUD
 *
 * 已更新：使用统一的 api-client.js 进行请求，
 * 支持登录状态检测、未登录友好提示、登录后自动重试
 */
(function () {
    'use strict';

    // ==================== 工具函数 ====================

    // 使用统一的 api-client 替代自定义 apiFetch
    function apiFetch(url, options) {
        // 将旧格式转换为 api-client 格式
        var method = (options && options.method) || 'GET';
        var data = null;
        
        if (options && options.body) {
            data = typeof options.body === 'string' ? JSON.parse(options.body) : options.body;
        }
        
        // 移除 /api/v1 前缀（api-client 已经包含）
        var path = url.replace('/api/v1', '');
        
        // 使用全局 api 对象
        if (window.api) {
            switch (method.toUpperCase()) {
                case 'GET':
                    return window.api.get(path);
                case 'POST':
                    return window.api.post(path, data);
                case 'PUT':
                    return window.api.put(path, data);
                case 'DELETE':
                    return window.api.delete(path);
                default:
                    return window.api.get(path);
            }
        }
        
        // 降级到原始 fetch
        var defaults = { credentials: 'include', headers: { 'Content-Type': 'application/json' } };
        options = options || {};
        var merged = Object.assign({}, defaults, options);
        if (merged.body && typeof merged.body === 'object') {
            merged.body = JSON.stringify(merged.body);
        }
        return fetch(url, merged).then(function (r) {
            if (!r.ok) return r.json().then(function (e) { throw new Error(e.detail || '请求失败 (' + r.status + ')'); });
            return r.json();
        });
    }

    function formatNumber(n) {
        if (n === null || n === undefined || n === '') return '0';
        return Number(n).toLocaleString();
    }

    function notify(msg, type) {
        if (typeof window.showGlobalNotification === 'function') {
            window.showGlobalNotification(msg, type);
        } else {
            alert(msg);
        }
    }

    // ==================== 状态 ====================

    var currentCustomerId = 0;
    var currentYear, currentMonth;
    var calendarData = null;
    var taskPollingTimer = null;

    var filterYear = document.getElementById('filterYear');
    var filterMonth = document.getElementById('filterMonth');
    var now = new Date();
    currentYear = now.getFullYear();
    currentMonth = now.getMonth() + 1;
    if (filterYear) filterYear.value = currentYear;
    if (filterMonth) filterMonth.value = currentMonth;

    // ==================== 初始化 ====================

    loadMonthlyData();

    // ==================== 事件绑定 ====================

    document.getElementById('searchBtn').addEventListener('click', function () {
        currentYear = parseInt(filterYear.value, 10);
        currentMonth = parseInt(filterMonth.value, 10);
        loadMonthlyData();
    });

    // 下载模板
    document.getElementById('downloadTemplateBtn').addEventListener('click', function () {
        window.location.href = '/plans/template';
    });

    // 手动添加
    document.getElementById('addSubmitBtn').addEventListener('click', createPlan);
    document.getElementById('addDetailRowBtn').addEventListener('click', addDetailRow);

    // 69码联动（添加弹窗）
    document.getElementById('addDetailRows').addEventListener('input', function (e) {
        if (e.target.classList.contains('add-barcode')) {
            var row = e.target.closest('.detail-row');
            var val = e.target.value.trim();
            var hint = row.querySelector('.barcode-hint');
            if (!val) { hint.textContent = ''; row.querySelector('.add-product-name').value = ''; row.querySelector('.add-product-id').value = '0'; return; }
            hint.textContent = '验证中...'; hint.className = 'form-text barcode-checking';
            clearTimeout(e.target._timer);
            e.target._timer = setTimeout(function () {
                apiFetch('/api/v1/plans/validate-barcode?q=' + encodeURIComponent(val))
                    .then(function (r) {
                        if (r.valid) {
                            hint.textContent = '验证通过'; hint.className = 'form-text barcode-valid';
                            row.querySelector('.add-product-name').value = r.product_name;
                            row.querySelector('.add-product-id').value = r.product_id || 0;
                        } else {
                            hint.textContent = r.message; hint.className = 'form-text barcode-invalid';
                        }
                    }).catch(function () { hint.textContent = '验证失败'; hint.className = 'form-text barcode-invalid'; });
            }, 300);
        }
    });

    // 批量上传
    var uploadZone = document.getElementById('uploadZone');
    var uploadFile = document.getElementById('uploadFile');
    uploadZone.addEventListener('click', function () { uploadFile.click(); });
    uploadZone.addEventListener('dragover', function (e) { e.preventDefault(); uploadZone.classList.add('dragover'); });
    uploadZone.addEventListener('dragleave', function () { uploadZone.classList.remove('dragover'); });
    uploadZone.addEventListener('drop', function (e) {
        e.preventDefault(); uploadZone.classList.remove('dragover');
        if (e.dataTransfer.files.length) handleUpload(e.dataTransfer.files[0]);
    });
    uploadFile.addEventListener('change', function () { if (this.files.length) handleUpload(this.files[0]); });
    document.getElementById('validateBtn').addEventListener('click', validateStaging);
    document.getElementById('confirmUploadBtn').addEventListener('click', confirmStaging);
    document.getElementById('discardBtn').addEventListener('click', discardStaging);
    document.getElementById('selectAllRows').addEventListener('change', function () {
        var checked = this.checked;
        document.querySelectorAll('.staging-row-check').forEach(function (cb) { cb.checked = checked; });
    });

    // 编辑
    document.getElementById('saveEditBtn').addEventListener('click', saveEdit);

    // ==================== 月度日历 ====================

    function loadMonthlyData() {
        apiFetch('/api/v1/plans/monthly?year=' + currentYear + '&month=' + currentMonth + (currentCustomerId ? '&customer_id=' + currentCustomerId : ''))
            .then(function (data) {
                calendarData = data;
                renderCustomerBar(data.customers);
                renderCalendar(data);
                loadPlanList();
                loadSummary();
            })
            .catch(function (e) { notify('加载数据失败: ' + e.message, 'danger'); });
    }

    function renderCustomerBar(customers) {
        var container = document.getElementById('customerFilter');
        container.innerHTML = '<span class="customer-chip' + (currentCustomerId === 0 ? ' active' : '') + '" data-customer-id="0">' +
            '<i class="fas fa-globe chip-icon"></i>全部</span>';

        customers.forEach(function (c) {
            var iconHtml = c.icon_url
                ? '<img src="' + c.icon_url + '" alt="' + c.name + '">'
                : '<i class="fas fa-user-circle chip-icon"></i>';
            var chip = document.createElement('span');
            chip.className = 'customer-chip' + (currentCustomerId === c.id ? ' active' : '');
            chip.dataset.customerId = c.id;
            chip.innerHTML = iconHtml + ' ' + c.name;
            chip.addEventListener('click', function () {
                currentCustomerId = c.id;
                loadMonthlyData();
            });
            container.appendChild(chip);
        });

        // "全部"按钮事件
        container.querySelector('[data-customer-id="0"]').addEventListener('click', function () {
            currentCustomerId = 0;
            loadMonthlyData();
        });
    }

    function renderCalendar(data) {
        var grid = document.getElementById('calendarGrid');
        // 保留7个header
        var headers = Array.from(grid.querySelectorAll('.calendar-header'));
        grid.innerHTML = '';
        headers.forEach(function (h) { grid.appendChild(h); });

        var year = data.year, month = data.month, daysInMonth = data.days_in_month;
        var firstDay = new Date(year, month - 1, 1).getDay(); // 0=Sun
        var startOffset = firstDay === 0 ? 6 : firstDay - 1; // 周一=0

        // 填充空白格
        for (var i = 0; i < startOffset; i++) {
            var empty = document.createElement('div');
            empty.className = 'calendar-cell empty';
            grid.appendChild(empty);
        }

        var today = new Date();
        var todayStr = today.getFullYear() + '-' + String(today.getMonth() + 1).padStart(2, '0') + '-' + String(today.getDate()).padStart(2, '0');

        for (var day = 1; day <= daysInMonth; day++) {
            var dateStr = year + '-' + String(month).padStart(2, '0') + '-' + String(day).padStart(2, '0');
            var cell = document.createElement('div');
            cell.className = 'calendar-cell';
            if (dateStr === todayStr) cell.classList.add('today');

            var plans = data.plans_by_date[dateStr] || [];
            var hasWarning = plans.some(function (p) { return p.stock_status !== 'sufficient'; });
            if (hasWarning) cell.classList.add('has-warning');

            var html = '<div class="cell-date">' + day + '</div>';

            var maxShow = 3;
            plans.slice(0, maxShow).forEach(function (p) {
                var dotClass = p.stock_status === 'sufficient' ? 'sufficient' : (p.stock_status === 'no_stock' ? 'no_stock' : 'shortage');
                html += '<div class="cell-item"><span class="stock-dot ' + dotClass + '"></span>' + p.product_name + ' ×' + p.quantity + '</div>';
            });
            if (plans.length > maxShow) {
                html += '<div class="cell-more">...+' + (plans.length - maxShow) + '更多</div>';
            }

            cell.innerHTML = html;

            // Popover（悬停显示完整列表）
            if (plans.length > 0) {
                cell.setAttribute('data-bs-toggle', 'popover');
                cell.setAttribute('data-bs-trigger', 'hover');
                cell.setAttribute('data-bs-html', 'true');
                cell.setAttribute('data-bs-placement', 'top');
                var popContent = plans.map(function (p) {
                    var statusBadge = p.stock_status === 'sufficient' ? '<span class="badge badge-sufficient">充足</span>'
                        : (p.stock_status === 'no_stock' ? '<span class="badge badge-no_stock">无库存</span>'
                        : '<span class="badge badge-shortage">紧张</span>');
                    return '<div>' + p.customer_name + ' | ' + p.product_name + ' | 计划:' + p.quantity + ' 库存:' + p.inventory_qty + ' ' + statusBadge + '</div>';
                }).join('');
                cell.setAttribute('data-bs-content', popContent);
                cell.setAttribute('title', dateStr);
            }

            // 点击日期 -> 展开当日明细
            (function (ds) {
                cell.addEventListener('click', function () {
                    showDayDetails(ds);
                });
            })(dateStr);

            grid.appendChild(cell);
        }

        // 初始化 popovers
        if (typeof bootstrap !== 'undefined') {
            grid.querySelectorAll('[data-bs-toggle="popover"]').forEach(function (el) {
                new bootstrap.Popover(el);
            });
        }
    }

    function showDayDetails(dateStr) {
        // 从 calendarData 中获取该日明细，渲染到表格
        if (!calendarData || !calendarData.plans_by_date) return;
        var plans = calendarData.plans_by_date[dateStr] || [];
        renderPlanTable(plans);
    }

    // ==================== 计划列表 ====================

    function loadPlanList() {
        apiFetch('/api/v1/plans/list?year=' + currentYear + '&month=' + currentMonth + (currentCustomerId ? '&customer_id=' + currentCustomerId : ''))
            .then(function (data) {
                // 获取每个主单的详情
                var planIds = data.plans.map(function (p) { return p.id; });
                if (planIds.length === 0) {
                    renderPlanTable([]);
                    return;
                }
                // 用明细数据填充表格
                var detailPromises = planIds.map(function (pid) {
                    return apiFetch('/api/v1/plans/detail/' + pid);
                });
                Promise.all(detailPromises).then(function (results) {
                    var allDetails = [];
                    results.forEach(function (r) {
                        r.details.forEach(function (d) {
                            d.plan_no = r.plan.plan_no;
                            d.customer_name = r.plan.customer_name;
                            d.status = r.plan.status;
                            allDetails.push(d);
                        });
                    });
                    renderPlanTable(allDetails);
                });
            })
            .catch(function (e) { notify('加载计划列表失败: ' + e.message, 'danger'); });
    }

    function renderPlanTable(details) {
        var tbody = document.getElementById('planTableBody');
        document.getElementById('recordCount').textContent = '共 ' + details.length + ' 条记录';

        if (details.length === 0) {
            tbody.innerHTML = '<tr><td colspan="11" class="text-center py-4"><i class="fas fa-inbox fa-3x mb-3 text-muted" style="opacity:0.3;"></i><p class="text-muted mb-0">暂无数据</p></td></tr>';
            return;
        }

        var html = '';
        details.forEach(function (d) {
            var rowClass = '';
            if (d.stock_status === 'no_stock' || d.stock_status === 'shortage') rowClass = 'table-row-warning';
            if (d.shipment_status === 'completed') rowClass = 'table-row-completed';

            var stockBadge = '<span class="badge badge-' + d.stock_status + '">' +
                (d.stock_status === 'sufficient' ? '充足' : (d.stock_status === 'no_stock' ? '无库存' : '紧张')) + '</span>';

            var percent = d.quantity > 0 ? Math.round(d.shipped_qty / d.quantity * 100) : 0;
            var barClass = d.shipment_status === 'completed' ? 'progress-bar-completed' : (d.shipment_status === 'partial' ? 'progress-bar-partial' : 'progress-bar-pending');

            html += '<tr class="' + rowClass + '">' +
                '<td>' + (d.plan_no || '') + '</td>' +
                '<td>' + d.customer_name + '</td>' +
                '<td>' + d.product_name + '</td>' +
                '<td>' + d.barcode + '</td>' +
                '<td class="text-center">' + formatNumber(d.quantity) + '</td>' +
                '<td class="text-center">' + formatNumber(d.inventory_qty) + '</td>' +
                '<td class="text-center">' + formatNumber(d.shipped_qty) + '</td>' +
                '<td class="text-center">' + formatNumber(d.remaining_qty) + '</td>' +
                '<td>' + stockBadge + '</td>' +
                '<td style="min-width:120px"><div class="progress"><div class="progress-bar ' + barClass + '" style="width:' + percent + '%"></div></div><small>已出货: ' + d.shipped_qty + ' | 剩余: ' + d.remaining_qty + '</small></td>' +
                '<td><button class="btn btn-sm btn-outline-primary edit-btn" data-id="' + d.plan_id + '">编辑</button></td>' +
                '</tr>';
        });
        tbody.innerHTML = html;

        // 编辑按钮事件
        tbody.querySelectorAll('.edit-btn').forEach(function (btn) {
            btn.addEventListener('click', function () {
                var planId = this.dataset.id;
                apiFetch('/api/v1/plans/detail/' + planId).then(function (data) {
                    document.getElementById('editId').value = data.plan.id;
                    document.getElementById('editStatus').value = data.plan.status;
                    document.getElementById('editRemark').value = data.plan.remark;
                    var modal = new bootstrap.Modal(document.getElementById('editModal'));
                    modal.show();
                });
            });
        });
    }

    // ==================== 汇总 ====================

    function loadSummary() {
        apiFetch('/api/v1/plans/customer-summary?year=' + currentYear + '&month=' + currentMonth)
            .then(function (data) {
                document.getElementById('summaryPanel').style.display = '';
                document.getElementById('totalPlanQty').textContent = formatNumber(data.total_plan_qty);
                document.getElementById('totalInventoryQty').textContent = formatNumber(data.total_inventory_qty);
                document.getElementById('totalShippedQty').textContent = formatNumber(data.total_shipped_qty);
                document.getElementById('totalRemainingQty').textContent = formatNumber(data.total_remaining_qty);
                document.getElementById('warningCount').textContent = data.warning_count;
            })
            .catch(function () { /* silently fail */ });
    }

    // ==================== 创建计划 ====================

    function createPlan() {
        var customerSelect = document.getElementById('addCustomer');
        var customerId = parseInt(customerSelect.value, 10);
        var customerName = customerSelect.options[customerSelect.selectedIndex].dataset.name;
        var planMonth = document.getElementById('addPlanMonth').value;
        var remark = document.getElementById('addRemark').value;

        if (!customerId) { notify('请选择客户', 'warning'); return; }
        if (!planMonth) { notify('请选择计划月份', 'warning'); return; }

        var details = [];
        var rows = document.querySelectorAll('#addDetailRows .detail-row');
        rows.forEach(function (row) {
            var barcode = row.querySelector('.add-barcode').value.trim();
            var productName = row.querySelector('.add-product-name').value.trim();
            var productId = parseInt(row.querySelector('.add-product-id').value, 10);
            var quantity = parseInt(row.querySelector('.add-quantity').value, 10);
            var planDate = row.querySelector('.add-date').value;

            if (barcode && quantity > 0 && planDate) {
                details.push({
                    product_id: productId,
                    product_name: productName,
                    barcode: barcode,
                    quantity: quantity,
                    plan_date: planDate,
                    remark: '',
                });
            }
        });

        if (details.length === 0) { notify('请至少添加一条明细', 'warning'); return; }

        apiFetch('/api/v1/plans/create', {
            method: 'POST',
            body: {
                customer_id: customerId,
                customer_name: customerName,
                plan_month: planMonth,
                details: details,
                remark: remark,
            },
        }).then(function (r) {
            if (r.success) {
                notify('采购计划创建成功', 'success');
                bootstrap.Modal.getInstance(document.getElementById('addModal')).hide();
                loadMonthlyData();
            }
        }).catch(function (e) { notify('创建失败: ' + e.message, 'danger'); });
    }

    function addDetailRow() {
        var container = document.getElementById('addDetailRows');
        var row = document.createElement('div');
        row.className = 'detail-row border rounded p-2 mb-2';
        row.innerHTML =
            '<div class="d-flex justify-content-between align-items-center mb-2"><span class="small fw-bold">明细</span><button type="button" class="btn btn-sm btn-outline-danger remove-row-btn"><i class="fas fa-times"></i></button></div>' +
            '<div class="mb-2"><label class="form-label mb-1 small">69码 <span class="text-danger">*</span></label><div class="position-relative"><input type="text" class="form-control form-control-sm add-barcode" required placeholder="输入69码" autocomplete="off"><div class="autocomplete-dropdown" style="display:none;"></div></div><small class="form-text barcode-hint"></small></div>' +
            '<div class="row g-2"><div class="col-6"><label class="form-label mb-1 small">产品名称</label><input type="text" class="form-control form-control-sm add-product-name" required placeholder="自动填充" readonly></div><div class="col-3"><label class="form-label mb-1 small">数量</label><input type="number" class="form-control form-control-sm add-quantity" required min="1" max="999999"></div><div class="col-3"><label class="form-label mb-1 small">日期</label><input type="date" class="form-control form-control-sm add-date" required></div></div>' +
            '<input type="hidden" class="add-product-id" value="0">';
        container.appendChild(row);

        row.querySelector('.remove-row-btn').addEventListener('click', function () {
            row.remove();
        });
    }

    // ==================== 编辑 ====================

    function saveEdit() {
        var planId = document.getElementById('editId').value;
        var status = document.getElementById('editStatus').value;
        var remark = document.getElementById('editRemark').value;

        apiFetch('/api/v1/plans/edit/' + planId, {
            method: 'PUT',
            body: { status: status, remark: remark },
        }).then(function (r) {
            if (r.success) {
                notify('更新成功', 'success');
                bootstrap.Modal.getInstance(document.getElementById('editModal')).hide();
                loadMonthlyData();
            }
        }).catch(function (e) { notify('更新失败: ' + e.message, 'danger'); });
    }

    // ==================== 批量上传 ====================

    function handleUpload(file) {
        document.getElementById('uploadProgress').style.display = '';
        document.getElementById('uploadProgressText').textContent = '正在上传...';

        var formData = new FormData();
        formData.append('file', file);

        fetch('/api/v1/plans/upload', { method: 'POST', credentials: 'include', body: formData })
            .then(function (r) { return r.json(); })
            .then(function (r) {
                document.getElementById('uploadProgress').style.display = 'none';
                if (r.success) {
                    notify('上传成功：' + r.total + '行', 'success');
                    // 如果需要异步处理
                    if (r.is_async && r.task_id) {
                        pollTaskStatus(r.task_id);
                        return;
                    }
                    loadStagingPreview();
                } else {
                    notify('上传失败: ' + (r.detail || '未知错误'), 'danger');
                }
            })
            .catch(function (e) {
                document.getElementById('uploadProgress').style.display = 'none';
                notify('上传失败: ' + e.message, 'danger');
            });
    }

    function pollTaskStatus(taskId) {
        document.getElementById('uploadProgress').style.display = '';
        document.getElementById('uploadProgressText').textContent = '正在处理...';

        if (taskPollingTimer) clearInterval(taskPollingTimer);
        taskPollingTimer = setInterval(function () {
            apiFetch('/api/v1/tasks/status/' + taskId)
                .then(function (r) {
                    if (r.status === 'SUCCESS') {
                        clearInterval(taskPollingTimer);
                        document.getElementById('uploadProgress').style.display = 'none';
                        notify('批量处理完成', 'success');
                        loadStagingPreview();
                    } else if (r.status === 'FAILURE') {
                        clearInterval(taskPollingTimer);
                        document.getElementById('uploadProgress').style.display = 'none';
                        notify('批量处理失败', 'danger');
                    }
                })
                .catch(function () { clearInterval(taskPollingTimer); });
        }, 1000);
    }

    function loadStagingPreview() {
        apiFetch('/api/v1/plans/staging/list')
            .then(function (r) {
                var data = r.data || [];
                if (data.length === 0) return;

                document.getElementById('previewArea').style.display = '';
                document.getElementById('confirmUploadBtn').style.display = '';
                document.getElementById('discardBtn').style.display = '';

                var valid = data.filter(function (d) { return d.is_validated; }).length;
                var invalid = data.length - valid;
                document.getElementById('previewStats').innerHTML =
                    '<span class="text-success">' + valid + ' 有效</span> / <span class="text-danger">' + invalid + ' 无效</span>';

                var html = '';
                data.forEach(function (d) {
                    var cls = d.is_validated ? '' : 'staging-invalid';
                    html += '<tr class="' + cls + '">' +
                        '<td><input type="checkbox" class="staging-row-check" data-id="' + d.id + '" checked></td>' +
                        '<td contenteditable="true" data-field="customer_name">' + d.customer_name + '</td>' +
                        '<td>' + d.product_name + '</td>' +
                        '<td>' + d.barcode + '</td>' +
                        '<td contenteditable="true" data-field="quantity">' + d.quantity + '</td>' +
                        '<td contenteditable="true" data-field="plan_date">' + d.plan_date + '</td>' +
                        '<td contenteditable="true" data-field="remark">' + (d.remark || '') + '</td>' +
                        '<td>' + (d.is_validated ? '<span class="text-success"><i class="fas fa-check"></i></span>' : '<span class="text-danger" title="' + (d.validation_error || '') + '"><i class="fas fa-exclamation-triangle"></i></span>') + '</td>' +
                        '</tr>';
                });
                document.getElementById('previewTableBody').innerHTML = html;
            });
    }

    function validateStaging() {
        apiFetch('/api/v1/plans/staging/validate', { method: 'POST' })
            .then(function (r) {
                if (r.success) {
                    notify('验证完成：' + r.valid_count + '有效，' + r.error_count + '无效', r.error_count > 0 ? 'warning' : 'success');
                    loadStagingPreview();
                }
            })
            .catch(function (e) { notify('验证失败: ' + e.message, 'danger'); });
    }

    function confirmStaging() {
        var selectedIds = [];
        document.querySelectorAll('.staging-row-check:checked').forEach(function (cb) {
            selectedIds.push(parseInt(cb.dataset.id, 10));
        });

        apiFetch('/api/v1/plans/staging/confirm', {
            method: 'POST',
            body: { batch_id: '', selected_ids: selectedIds },
        }).then(function (r) {
            if (r.success) {
                notify('保存成功：' + r.created_count + '条明细', 'success');
                document.getElementById('previewArea').style.display = 'none';
                document.getElementById('confirmUploadBtn').style.display = 'none';
                document.getElementById('discardBtn').style.display = 'none';
                loadMonthlyData();
            }
        }).catch(function (e) { notify('保存失败: ' + e.message, 'danger'); });
    }

    function discardStaging() {
        apiFetch('/api/v1/plans/staging/clear', { method: 'DELETE' })
            .then(function () {
                notify('暂存区已清空', 'info');
                document.getElementById('previewArea').style.display = 'none';
                document.getElementById('confirmUploadBtn').style.display = 'none';
                document.getElementById('discardBtn').style.display = 'none';
            });
    }

})();
