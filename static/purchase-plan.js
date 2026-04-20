/**
 * 采购计划管理 - 前端交互逻辑
 *
 * 功能：客户筛选、ECharts时间轴热力图、库存对比+出货进度渲染、
 *       批量上传预览、69码联动验证、CRUD操作
 */
(function () {
    'use strict';

    // ==================== 工具函数 ====================

    function apiFetch(url, options = {}) {
        const defaults = { credentials: 'include', headers: { 'Content-Type': 'application/json' } };
        return fetch(url, { ...defaults, ...options })
            .then(r => {
                if (!r.ok) return r.json().then(e => { throw new Error(e.detail || '请求失败 (' + r.status + ')'); });
                return r.json();
            });
    }

    function formatNumber(n) {
        if (n === null || n === undefined || n === '') return '0';
        return Number(n).toLocaleString();
    }

    function notify(msg, type) {
        if (typeof GlobalNotification !== 'undefined' && GlobalNotification.show) {
            GlobalNotification.show(type || 'info', msg);
        } else if (typeof window.showGlobalNotification === 'function') {
            window.showGlobalNotification(msg, type);
        } else {
            alert(msg);
        }
    }

    // ==================== 状态 ====================

    let currentCustomer = '';
    let currentYear, currentMonth;
    let timelineChart = null;
    let allPlans = [];

    const filterYear = document.getElementById('filterYear');
    const filterMonth = document.getElementById('filterMonth');
    const now = new Date();
    currentYear = now.getFullYear();
    currentMonth = now.getMonth() + 1;
    if (filterYear) filterYear.value = currentYear;
    if (filterMonth) filterMonth.value = currentMonth;

    // ==================== 初始化加载 ====================

    loadPlans();

    // ==================== 事件绑定 ====================

    document.getElementById('searchBtn').addEventListener('click', function () {
        currentYear = parseInt(filterYear.value, 10);
        currentMonth = parseInt(filterMonth.value, 10);
        loadPlans();
    });

    // 添加
    document.getElementById('addSubmitBtn').addEventListener('click', createPlan);

    // 69码联动（添加弹窗）
    let addBarcodeTimer = null;
    document.getElementById('addBarcode').addEventListener('input', function () {
        clearTimeout(addBarcodeTimer);
        var val = this.value.trim();
        var hint = document.getElementById('addBarcodeHint');
        if (!val) { hint.textContent = ''; document.getElementById('addProductName').value = ''; return; }
        hint.textContent = '验证中...'; hint.className = 'form-text barcode-checking';
        addBarcodeTimer = setTimeout(function () { validateBarcode(val, 'add'); }, 300);
    });

    document.getElementById('addBarcode').addEventListener('focus', function () {
        if (this.value.trim().length >= 2) searchProducts(this.value.trim(), 'add');
    });

    document.addEventListener('click', function (e) {
        var dd = document.getElementById('addBarcodeDropdown');
        if (dd && !dd.contains(e.target) && e.target.id !== 'addBarcode') dd.style.display = 'none';
    });

    // 编辑
    document.getElementById('saveEditBtn').addEventListener('click', saveEdit);

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

    // ==================== 69码联动 ====================

    function validateBarcode(barcode, prefix) {
        var hint = document.getElementById(prefix + 'BarcodeHint');
        var nameInput = document.getElementById(prefix + 'ProductName');
        apiFetch('/api/v1/production-plans/validate-barcode?q=' + encodeURIComponent(barcode))
            .then(function (data) {
                if (data.valid) {
                    hint.textContent = '验证通过'; hint.className = 'form-text barcode-valid';
                    if (data.product_name && !nameInput.value) nameInput.value = data.product_name;
                } else {
                    hint.textContent = data.message || '未找到产品'; hint.className = 'form-text barcode-invalid';
                }
            })
            .catch(function (err) { hint.textContent = '验证失败'; hint.className = 'form-text barcode-invalid'; });
    }

    function searchProducts(query, prefix) {
        var dd = document.getElementById(prefix + 'BarcodeDropdown');
        apiFetch('/api/v1/aux/product-search?q=' + encodeURIComponent(query))
            .then(function (products) {
                if (!products || !products.length) { dd.style.display = 'none'; return; }
                dd.innerHTML = products.map(function (p) {
                    return '<div class="autocomplete-item" data-barcode="' + (p.barcode || '') + '" data-name="' + p.name + '">' +
                        '<span class="fw-semibold">' + p.name + '</span><small class="text-muted ms-2">' + (p.barcode || '') + '</small></div>';
                }).join('');
                dd.style.display = 'block';
                dd.querySelectorAll('.autocomplete-item').forEach(function (item) {
                    item.addEventListener('click', function () {
                        document.getElementById(prefix + 'Barcode').value = this.dataset.barcode;
                        document.getElementById(prefix + 'ProductName').value = this.dataset.name;
                        dd.style.display = 'none';
                        var hint = document.getElementById(prefix + 'BarcodeHint');
                        hint.textContent = '验证通过'; hint.className = 'form-text barcode-valid';
                    });
                });
            })
            .catch(function () { dd.style.display = 'none'; });
    }

    // ==================== 加载计划列表 ====================

    function loadPlans() {
        currentYear = parseInt(filterYear.value, 10);
        currentMonth = parseInt(filterMonth.value, 10);
        if (!currentYear || !currentMonth) return;

        apiFetch('/api/v1/production-plans/list?year=' + currentYear + '&month=' + currentMonth + (currentCustomer ? '&customer=' + encodeURIComponent(currentCustomer) : ''))
            .then(function (result) {
                allPlans = result.plans || [];
                renderSummary(result.monthly_summary);
                renderPlanTable(allPlans);
                document.getElementById('recordCount').textContent = '共 ' + result.total + ' 条记录';
            })
            .then(function () { return loadTimeline(); })
            .catch(function (err) { notify('加载失败: ' + err.message, 'error'); });
    }

    function loadTimeline() {
        apiFetch('/api/v1/production-plans/timeline?year=' + currentYear + '&month=' + currentMonth + (currentCustomer ? '&customer=' + encodeURIComponent(currentCustomer) : ''))
            .then(function (data) {
                renderCustomerFilter(data.customers || []);
                renderTimelineChart(data);
            })
            .catch(function () {});
    }

    // ==================== 渲染汇总 ====================

    function renderSummary(s) {
        if (!s) return;
        document.getElementById('summaryPanel').style.display = 'block';
        document.getElementById('totalPlanQty').textContent = formatNumber(s.total_plan_qty);
        document.getElementById('totalInventoryQty').textContent = formatNumber(s.total_inventory_qty);
        document.getElementById('totalShippedQty').textContent = formatNumber(s.total_shipped_qty);
        document.getElementById('totalRemainingQty').textContent = formatNumber(s.total_remaining_qty);
        document.getElementById('warningCount').textContent = s.warning_count;

        var diffEl = document.getElementById('totalPlanQty');
        // 库存不足高亮
        if (s.total_diff > 0) {
            document.getElementById('totalInventoryQty').classList.add('text-danger');
        } else {
            document.getElementById('totalInventoryQty').classList.remove('text-danger');
        }
    }

    // ==================== 渲染客户筛选 ====================

    function renderCustomerFilter(customers) {
        var container = document.getElementById('customerFilter');
        var html = '<span class="customer-tag' + (!currentCustomer ? ' active' : '') + '" data-customer=""><i class="fas fa-globe me-1"></i>全部</span>';
        customers.forEach(function (name) {
            var colors = ['#0d6efd', '#198754', '#dc3545', '#ffc107', '#6610f2', '#fd7e14', '#20c997', '#6f42c1'];
            var color = colors[name.charCodeAt(0) % colors.length];
            html += '<span class="customer-tag' + (currentCustomer === name ? ' active' : '') + '" data-customer="' + name + '" style="' + (currentCustomer === name ? 'background:' + color + ';border-color:' + color + ';color:white' : '') + '">' +
                '<i class="fas fa-user me-1" style="color:' + color + '"></i>' + name + '</span>';
        });
        container.innerHTML = html;

        container.querySelectorAll('.customer-tag').forEach(function (tag) {
            tag.addEventListener('click', function () {
                currentCustomer = this.dataset.customer;
                loadPlans();
            });
        });
    }

    // ==================== 渲染时间轴 ====================

    function renderTimelineChart(data) {
        var chartDom = document.getElementById('timelineChart');
        if (!chartDom) return;

        if (!timelineChart) {
            timelineChart = echarts.init(chartDom);
        }

        var days = data.days_in_month || 30;
        var timeline = data.timeline || [];

        // 构建ECharts数据
        var chartData = [];
        timeline.forEach(function (d) {
            chartData.push({
                value: [d.day, d.total_plan_qty || 0],
                has_warning: d.has_warning,
                plan_count: d.plans ? d.plans.length : 0,
            });
        });

        var option = {
            tooltip: {
                trigger: 'item',
                formatter: function (p) {
                    var d = p.data;
                    var status = d.has_warning ? '<span style="color:#dc3545">库存不足</span>' : '<span style="color:#198754">库存充足</span>';
                    return currentMonth + '月' + d.value[0] + '日<br>计划量: ' + formatNumber(d.value[1]) + '<br>计划条数: ' + d.plan_count + '<br>' + status;
                }
            },
            grid: { top: 20, bottom: 30, left: 40, right: 20 },
            xAxis: {
                type: 'category',
                data: Array.from({ length: days }, function (_, i) { return (i + 1) + '日'; }),
                axisLabel: { fontSize: 10, interval: days > 20 ? 1 : 0 },
            },
            yAxis: { type: 'value', axisLabel: { formatter: function (v) { return v >= 10000 ? (v / 10000) + '万' : v; } } },
            series: [{
                type: 'bar',
                data: chartData.map(function (d) {
                    return {
                        value: d.value,
                        itemStyle: {
                            color: d.has_warning ? '#ffc107' : (d.value[1] > 0 ? '#198754' : '#e9ecef'),
                        },
                    };
                }),
                barMaxWidth: 20,
            }],
        };

        timelineChart.setOption(option, true);

        // 点击日历查看当日明细
        timelineChart.on('click', function (params) {
            var day = params.data.value[0];
            var dayPlans = allPlans.filter(function (p) {
                return p.plan_date === currentYear + '-' + String(currentMonth).padStart(2, '0') + '-' + String(day).padStart(2, '0');
            });
            if (dayPlans.length) {
                renderPlanTable(dayPlans);
                document.getElementById('recordCount').textContent = currentMonth + '月' + day + '日 - ' + dayPlans.length + ' 条';
            }
        });
    }

    // ==================== 渲染明细表 ====================

    function renderPlanTable(plans) {
        var tbody = document.getElementById('planTableBody');
        if (!plans || !plans.length) {
            tbody.innerHTML = '<tr><td colspan="9" class="text-center py-4"><i class="fas fa-inbox fa-3x mb-3 text-muted" style="opacity:0.3;"></i><p class="text-muted mb-0">暂无数据</p></td></tr>';
            return;
        }

        tbody.innerHTML = plans.map(function (p) {
            var isStockWarning = p.stock_status === 'warning';
            var isCompleted = p.shipment_status === 'completed';
            var rowClass = isStockWarning ? 'table-row-warning' : (isCompleted ? 'table-row-completed' : '');

            // 库存状态
            var stockBadge = isStockWarning
                ? '<span class="badge bg-warning text-dark"><i class="fas fa-exclamation-triangle me-1"></i>不足</span>'
                : '<span class="badge bg-success"><i class="fas fa-check me-1"></i>充足</span>';

            // 出货进度
            var shipPct = p.quantity > 0 ? Math.min(100, Math.round(p.shipped_qty / p.quantity * 100)) : 0;
            var shipColor = shipPct >= 100 ? '#198754' : (shipPct > 0 ? '#0d6efd' : '#dee2e6');
            var progressBar = '<div class="shipment-progress mt-1"><div class="shipment-progress-bar" style="width:' + shipPct + '%;background:' + shipColor + ';"></div></div>' +
                '<small class="text-muted">' + formatNumber(p.shipped_qty) + ' / ' + formatNumber(p.quantity) + ' (' + shipPct + '%)</small>';

            // 剩余
            var remainingClass = p.remaining_qty <= 0 ? 'text-success' : 'text-primary';

            return '<tr class="' + rowClass + '">' +
                '<td><span class="fw-semibold"><i class="fas fa-building text-primary me-1"></i>' + p.customer_name + '</span></td>' +
                '<td><i class="fas fa-cube text-secondary me-1"></i>' + p.product_name + '</td>' +
                '<td><code>' + p.barcode + '</code></td>' +
                '<td class="text-center fw-bold">' + formatNumber(p.quantity) + '</td>' +
                '<td class="text-center ' + (isStockWarning ? 'text-danger fw-bold' : 'text-success') + '">' + formatNumber(p.inventory_qty) + '</td>' +
                '<td class="text-center">' + progressBar + '</td>' +
                '<td class="text-center ' + remainingClass + ' fw-bold">' + formatNumber(p.remaining_qty) + '</td>' +
                '<td>' + stockBadge + '</td>' +
                '<td>' +
                    '<button onclick="window._editPlan(' + p.id + ',\'' + p.customer_name.replace(/\'/g, "\\'") + '\',\'' + p.product_name.replace(/\'/g, "\\'") + '\',\'' + p.barcode + '\',' + p.quantity + ',\'' + p.plan_date + '\',\'' + p.status + '\',\'' + (p.remark || '').replace(/\'/g, "\\'") + '\')" class="btn btn-sm btn-outline-primary me-1"><i class="fas fa-edit"></i></button>' +
                    '<button onclick="window._deletePlan(' + p.id + ')" class="btn btn-sm btn-outline-danger"><i class="fas fa-trash"></i></button>' +
                '</td></tr>';
        }).join('');
    }

    // ==================== CRUD ====================

    function createPlan() {
        var data = {
            customer_name: document.getElementById('addCustomer').value.trim(),
            product_name: document.getElementById('addProductName').value.trim(),
            barcode: document.getElementById('addBarcode').value.trim(),
            quantity: parseInt(document.getElementById('addQuantity').value, 10),
            plan_date: document.getElementById('addPlanDate').value,
            remark: document.getElementById('addRemark').value.trim(),
        };
        if (!data.customer_name || !data.barcode || !data.product_name || !data.quantity || !data.plan_date) {
            notify('请填写完整信息', 'error'); return;
        }
        apiFetch('/api/v1/production-plans/create', { method: 'POST', body: JSON.stringify(data) })
            .then(function (r) { if (r.success) { notify(r.message, 'success'); bootstrap.Modal.getInstance(document.getElementById('addModal')).hide(); document.getElementById('addForm').reset(); document.getElementById('addBarcodeHint').textContent = ''; loadPlans(); } })
            .catch(function (e) { notify(e.message, 'error'); });
    }

    window._editPlan = function (id, cn, pn, bc, qty, pd, st, rm) {
        document.getElementById('editId').value = id;
        document.getElementById('editCustomer').value = cn;
        document.getElementById('editProductName').value = pn;
        document.getElementById('editBarcode').value = bc;
        document.getElementById('editQuantity').value = qty;
        document.getElementById('editPlanDate').value = pd;
        document.getElementById('editStatus').value = st;
        document.getElementById('editRemark').value = rm;
        new bootstrap.Modal(document.getElementById('editModal')).show();
    };

    function saveEdit() {
        var id = document.getElementById('editId').value;
        var data = {
            customer_name: document.getElementById('editCustomer').value.trim(),
            product_name: document.getElementById('editProductName').value.trim(),
            barcode: document.getElementById('editBarcode').value.trim(),
            quantity: parseInt(document.getElementById('editQuantity').value, 10),
            plan_date: document.getElementById('editPlanDate').value,
            status: document.getElementById('editStatus').value,
            remark: document.getElementById('editRemark').value.trim(),
        };
        apiFetch('/api/v1/production-plans/edit/' + id, { method: 'PUT', body: JSON.stringify(data) })
            .then(function (r) { if (r.success) { notify(r.message, 'success'); bootstrap.Modal.getInstance(document.getElementById('editModal')).hide(); loadPlans(); } })
            .catch(function (e) { notify(e.message, 'error'); });
    }

    window._deletePlan = function (id) {
        if (!confirm('确认删除？')) return;
        apiFetch('/api/v1/production-plans/delete/' + id, { method: 'DELETE' })
            .then(function (r) { if (r.success) { notify(r.message, 'success'); loadPlans(); } })
            .catch(function (e) { notify(e.message, 'error'); });
    };

    // ==================== 批量上传 ====================

    function handleUpload(file) {
        var formData = new FormData();
        formData.append('file', file);

        document.getElementById('uploadProgress').style.display = 'block';
        document.getElementById('previewArea').style.display = 'none';
        document.getElementById('confirmUploadBtn').style.display = 'none';
        document.getElementById('discardBtn').style.display = 'none';

        fetch('/api/v1/production-plans/upload', { method: 'POST', body: formData, credentials: 'include' })
            .then(function (r) { return r.json(); })
            .then(function (result) {
                document.getElementById('uploadProgress').style.display = 'none';
                if (result.success) {
                    notify('解析成功: ' + result.total + ' 条', 'success');
                    loadStagingPreview();
                } else {
                    notify(result.detail || '上传失败', 'error');
                }
            })
            .catch(function (e) {
                document.getElementById('uploadProgress').style.display = 'none';
                notify('上传失败: ' + e.message, 'error');
            });
    }

    function loadStagingPreview() {
        apiFetch('/api/v1/production-plans/staging/list')
            .then(function (result) {
                var data = result.data || [];
                if (!data.length) {
                    document.getElementById('previewArea').style.display = 'none';
                    return;
                }
                document.getElementById('previewArea').style.display = 'block';
                document.getElementById('confirmUploadBtn').style.display = 'inline-block';
                document.getElementById('discardBtn').style.display = 'inline-block';

                var valid = data.filter(function (d) { return d.is_validated; }).length;
                var invalid = data.length - valid;
                document.getElementById('previewStats').innerHTML =
                    '<span class="text-success"><i class="fas fa-check-circle me-1"></i>' + valid + ' 有效</span>' +
                    (invalid > 0 ? ' <span class="text-danger ms-2"><i class="fas fa-times-circle me-1"></i>' + invalid + ' 待验证</span>' : '');

                document.getElementById('previewTableBody').innerHTML = data.map(function (d) {
                    var rowClass = d.is_validated ? '' : 'staging-invalid';
                    var statusIcon = d.is_validated
                        ? '<i class="fas fa-check-circle text-success"></i>'
                        : '<i class="fas fa-exclamation-circle text-danger" title="' + (d.validation_error || '') + '"></i>';
                    return '<tr class="' + rowClass + '"><td>' + d.customer_name + '</td><td>' + d.product_name + '</td><td>' + d.barcode + '</td><td>' + formatNumber(d.quantity) + '</td><td>' + d.plan_date + '</td><td>' + (d.remark || '') + '</td><td>' + statusIcon + '</td></tr>';
                }).join('');
            });
    }

    function validateStaging() {
        notify('正在验证...', 'info');
        apiFetch('/api/v1/production-plans/staging/validate', { method: 'POST' })
            .then(function (r) {
                notify('验证完成: ' + r.valid_count + ' 有效, ' + r.error_count + ' 错误', r.error_count > 0 ? 'warning' : 'success');
                loadStagingPreview();
            })
            .catch(function (e) { notify(e.message, 'error'); });
    }

    function confirmStaging() {
        if (!confirm('确认保存有效数据到排产计划？')) return;
        apiFetch('/api/v1/production-plans/staging/confirm', { method: 'POST' })
            .then(function (r) {
                notify('已保存 ' + r.created_count + ' 条，跳过 ' + r.skipped_count + ' 条', 'success');
                bootstrap.Modal.getInstance(document.getElementById('uploadModal')).hide();
                document.getElementById('previewArea').style.display = 'none';
                document.getElementById('confirmUploadBtn').style.display = 'none';
                document.getElementById('discardBtn').style.display = 'none';
                loadPlans();
            })
            .catch(function (e) { notify(e.message, 'error'); });
    }

    function discardStaging() {
        if (!confirm('确认丢弃所有暂存数据？')) return;
        apiFetch('/api/v1/production-plans/staging/clear', { method: 'DELETE' })
            .then(function () {
                notify('已清空', 'success');
                document.getElementById('previewArea').style.display = 'none';
                document.getElementById('confirmUploadBtn').style.display = 'none';
                document.getElementById('discardBtn').style.display = 'none';
            })
            .catch(function (e) { notify(e.message, 'error'); });
    }

    // ==================== 窗口大小自适应 ====================

    window.addEventListener('resize', function () {
        if (timelineChart) timelineChart.resize();
    });

})();
