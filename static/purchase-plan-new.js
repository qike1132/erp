/**
 * 采购计划管理 - 前端交互逻辑（重构版 v2）
 *
 * 架构对齐 React 参考设计：
 * - 日期分组折叠面板（DayPanel）替代 CSS Grid 日历
 * - 客户筛选 Chips + 搜索输入
 * - 统计卡片（计划总量/出货/剩余/充足率）
 * - 单次 /monthly API 获取全量数据，前端过滤，无 N+1 请求
 * - 进度条4色编码（low/mid/high/over）
 * - 库存状态 3 色 badge（sufficient/shortage/no_stock）
 */
(function () {
    'use strict';

    // ==================== API Helper ====================

    function apiFetch(url, options) {
        var method = (options && options.method) || 'GET';
        var data = null;
        if (options && options.body) {
            data = typeof options.body === 'string' ? JSON.parse(options.body) : options.body;
        }
        var path = url.replace('/api/v1', '');
        if (window.api) {
            switch (method.toUpperCase()) {
                case 'GET': return window.api.get(path);
                case 'POST': return window.api.post(path, data);
                case 'PUT': return window.api.put(path, data);
                case 'DELETE': return window.api.delete(path);
                default: return window.api.get(path);
            }
        }
        var defaults = { credentials: 'include', headers: { 'Content-Type': 'application/json' } };
        options = options || {};
        var merged = Object.assign({}, defaults, options);
        if (merged.body && typeof merged.body === 'object') merged.body = JSON.stringify(merged.body);
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
        if (typeof window.showGlobalNotification === 'function') window.showGlobalNotification(msg, type);
        else alert(msg);
    }

    // ==================== State ====================

    var selectedMonth = '';
    var searchQuery = '';
    var selectedCustomerIds = [];
    var allCalendarData = null;  // Raw data from /monthly
    var taskPollingTimer = null;

    // Initialize month
    var now = new Date();
    selectedMonth = now.getFullYear() + '-' + String(now.getMonth() + 1).padStart(2, '0');
    var monthInput = document.getElementById('filterMonthInput');
    if (monthInput) monthInput.value = selectedMonth;

    // ==================== Init ====================

    loadMonthlyData();

    // ==================== Event Bindings ====================

    monthInput.addEventListener('change', function () {
        if (this.value) {
            selectedMonth = this.value;
            selectedCustomerIds = [];
            loadMonthlyData();
        }
    });

    document.getElementById('refreshBtn').addEventListener('click', function () {
        var icon = document.getElementById('refreshIcon');
        icon.classList.add('fa-spin');
        loadMonthlyData().finally(function () { icon.classList.remove('fa-spin'); });
    });

    document.getElementById('searchInput').addEventListener('input', function () {
        searchQuery = this.value.trim();
        renderTimeline();
    });

    document.getElementById('downloadTemplateBtn').addEventListener('click', function () {
        window.location.href = '/plans/template';
    });

    // Add plan
    document.getElementById('addSubmitBtn').addEventListener('click', createPlan);
    document.getElementById('addDetailRowBtn').addEventListener('click', addDetailRow);

    // Barcode validation (add modal)
    document.getElementById('addDetailRows').addEventListener('input', function (e) {
        if (!e.target.classList.contains('add-barcode')) return;
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
    });

    // Product name search (add modal)
    document.getElementById('addDetailRows').addEventListener('input', function (e) {
        if (!e.target.classList.contains('add-product-name')) return;
        var row = e.target.closest('.detail-row');
        var dd = row.querySelector('.product-search-dropdown');
        var val = e.target.value.trim();
        if (!val || val.length < 1) { dd.style.display = 'none'; return; }
        clearTimeout(e.target._searchTimer);
        e.target._searchTimer = setTimeout(function () {
            apiFetch('/api/v1/aux/product-search?q=' + encodeURIComponent(val))
                .then(function (products) {
                    if (!products || !products.length) { dd.style.display = 'none'; return; }
                    dd.innerHTML = products.slice(0, 15).map(function (p) {
                        return '<div class="product-search-item" data-id="' + p.id + '" data-name="' + (p.name || '') + '" data-barcode="' + (p.barcode || '') + '">' +
                            '<span class="item-name">' + (p.name || '') + '</span><span class="item-barcode">' + (p.barcode || '') + '</span></div>';
                    }).join('');
                    dd.style.display = 'block';
                    dd.querySelectorAll('.product-search-item').forEach(function (item) {
                        item.addEventListener('mousedown', function (ev) {
                            ev.preventDefault();
                            row.querySelector('.add-product-name').value = this.dataset.name;
                            row.querySelector('.add-barcode').value = this.dataset.barcode;
                            row.querySelector('.add-product-id').value = this.dataset.id;
                            var hint = row.querySelector('.barcode-hint');
                            if (hint) { hint.textContent = '验证通过'; hint.className = 'form-text barcode-valid'; }
                            dd.style.display = 'none';
                        });
                    });
                }).catch(function () { dd.style.display = 'none'; });
        }, 300);
    });
    // Close product search dropdown on blur
    document.getElementById('addDetailRows').addEventListener('focusout', function (e) {
        if (!e.target.classList.contains('add-product-name')) return;
        var dd = e.target.closest('.detail-row').querySelector('.product-search-dropdown');
        setTimeout(function () { if (dd) dd.style.display = 'none'; }, 200);
    });

    // Upload
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

    // Edit
    document.getElementById('saveEditBtn').addEventListener('click', saveEdit);

    // ==================== Load Data (single API call) ====================

    function loadMonthlyData() {
        var parts = selectedMonth.split('-');
        var year = parseInt(parts[0], 10);
        var month = parseInt(parts[1], 10);
        var url = '/api/v1/plans/monthly?year=' + year + '&month=' + month;

        return apiFetch(url).then(function (data) {
            allCalendarData = data;
            // Also load summary
            loadSummary(year, month);
            renderCustomerBar(data.customers);
            renderTimeline();
            updateMonthDisplay(year, month, data.days_in_month);
        }).catch(function (e) { notify('加载数据失败: ' + e.message, 'danger'); });
    }

    function loadSummary(year, month) {
        apiFetch('/api/v1/plans/customer-summary?year=' + year + '&month=' + month)
            .then(function (data) {
                document.getElementById('totalPlanQty').textContent = formatNumber(data.total_plan_qty);
                document.getElementById('totalShippedQty').textContent = formatNumber(data.total_shipped_qty);
                document.getElementById('totalRemainingQty').textContent = formatNumber(data.total_remaining_qty);
                var rate = data.total_plan_qty > 0
                    ? Math.round((data.total_plan_qty - data.warning_count) / data.total_plan_qty * 100)
                    : 100;
                document.getElementById('stockRate').textContent = rate;
            }).catch(function () {});
    }

    function updateMonthDisplay(year, month, daysInMonth) {
        document.getElementById('monthDisplay').textContent = year + ' 年 ' + month + ' 月';
        document.getElementById('daysInMonthCount').textContent = daysInMonth;
    }

    // ==================== Customer Filter ====================

    function renderCustomerBar(customers) {
        var container = document.getElementById('customerFilter');
        var allSelected = selectedCustomerIds.length === 0;

        var html = '<span class="bar-label">客户筛选：</span>';
        html += '<button class="customer-chip' + (allSelected ? ' active' : '') + '" data-customer-id="0">' +
            '<i class="fas fa-globe chip-icon"></i>' + (allSelected ? '取消全选' : '全选') + '</button>';

        customers.forEach(function (c) {
            var isActive = selectedCustomerIds.includes(c.id);
            var iconHtml = c.icon_url
                ? '<img src="' + c.icon_url + '" alt="' + c.name + '">'
                : '<i class="fas fa-user-circle chip-icon"></i>';
            html += '<button class="customer-chip' + (isActive ? ' active' : '') + '" data-customer-id="' + c.id + '">' +
                iconHtml + ' ' + c.name + '</button>';
        });

        if (selectedCustomerIds.length > 0 && selectedCustomerIds.length < customers.length) {
            html += '<button class="clear-filter" id="clearFilterBtn">清除筛选</button>';
        }

        container.innerHTML = html;

        // Bind events
        container.querySelectorAll('.customer-chip').forEach(function (chip) {
            chip.addEventListener('click', function () {
                var cid = parseInt(this.dataset.customerId, 10);
                if (cid === 0) {
                    // "全选/取消全选" button
                    if (selectedCustomerIds.length === 0) {
                        selectedCustomerIds = customers.map(function (c) { return c.id; });
                    } else {
                        selectedCustomerIds = [];
                    }
                } else {
                    var idx = selectedCustomerIds.indexOf(cid);
                    if (idx >= 0) selectedCustomerIds.splice(idx, 1);
                    else selectedCustomerIds.push(cid);
                }
                renderCustomerBar(customers);
                renderTimeline();
            });
        });

        var clearBtn = document.getElementById('clearFilterBtn');
        if (clearBtn) {
            clearBtn.addEventListener('click', function () {
                selectedCustomerIds = [];
                renderCustomerBar(customers);
                renderTimeline();
            });
        }
    }

    // ==================== Filter Data ====================

    function getFilteredItems() {
        if (!allCalendarData || !allCalendarData.plans_by_date) return [];
        var items = [];
        var q = searchQuery.toLowerCase();

        Object.keys(allCalendarData.plans_by_date).sort().forEach(function (dateStr) {
            var plans = allCalendarData.plans_by_date[dateStr];
            plans.forEach(function (p) {
                // Customer filter
                if (selectedCustomerIds.length > 0 && !selectedCustomerIds.includes(p.customer_id)) return;
                // Search filter
                if (q) {
                    var match = (p.product_name || '').toLowerCase().includes(q) ||
                                (p.barcode || '').toLowerCase().includes(q) ||
                                (p.customer_name || '').toLowerCase().includes(q);
                    if (!match) return;
                }
                items.push(Object.assign({}, p, { _dateStr: dateStr }));
            });
        });
        return items;
    }

    function groupByDate(items) {
        var map = {};
        items.forEach(function (item) {
            if (!map[item._dateStr]) map[item._dateStr] = [];
            map[item._dateStr].push(item);
        });
        return map;
    }

    // ==================== Render Timeline ====================

    function renderTimeline() {
        var items = getFilteredItems();
        var grouped = groupByDate(items);
        var dates = Object.keys(grouped).sort();
        var container = document.getElementById('timelinePanels');

        // Update counts
        var activeItems = items.filter(function (p) { return p.shipment_status !== 'completed'; });
        document.getElementById('activePlanCount').textContent = items.length;
        document.getElementById('activeDateCount').textContent = dates.length;
        document.getElementById('planDateCount').textContent = dates.length;

        if (dates.length === 0) {
            container.innerHTML =
                '<div class="empty-state">' +
                    '<i class="fas fa-chart-bar empty-icon"></i>' +
                    '<p>当前条件下暂无采购计划数据</p>' +
                    (selectedCustomerIds.length > 0 || searchQuery
                        ? '<span class="clear-link" id="clearAllFilters">清除筛选条件</span>' : '') +
                '</div>';
            var clearAll = document.getElementById('clearAllFilters');
            if (clearAll) {
                clearAll.addEventListener('click', function () {
                    selectedCustomerIds = [];
                    searchQuery = '';
                    document.getElementById('searchInput').value = '';
                    if (allCalendarData) renderCustomerBar(allCalendarData.customers);
                    renderTimeline();
                });
            }
            return;
        }

        var today = new Date().toISOString().slice(0, 10);
        var html = '';

        dates.forEach(function (dateStr, idx) {
            var dayItems = grouped[dateStr];
            var totalPlan = dayItems.reduce(function (s, i) { return s + i.quantity; }, 0);
            var isToday = dateStr === today;
            var isPast = dateStr < today;

            // Format date label
            var d = new Date(dateStr + 'T00:00:00');
            var weekMap = ['日', '一', '二', '三', '四', '五', '六'];
            var dateLabel = String(d.getMonth() + 1).padStart(2, '0') + '月' + String(d.getDate()).padStart(2, '0') + '日 周' + weekMap[d.getDay()];

            var defaultOpen = idx < 3;

            html += '<div class="day-panel' + (isToday ? ' today' : '') + '" style="margin-bottom:0.75rem;">';
            html += '<button class="day-panel-header" data-date="' + dateStr + '">';
            html += '<i class="fas fa-chevron-down chevron' + (defaultOpen ? '' : ' collapsed') + '"></i>';
            html += '<i class="fas fa-calendar-alt" style="color:#2563eb;"></i>';
            html += '<span class="date-label">' + dateLabel + '</span>';
            if (isToday) html += '<span class="today-badge">今日</span>';
            html += '<span class="plan-count-badge">' + dayItems.length + ' 条计划</span>';
            html += '<span class="total-badge">合计 ' + formatNumber(totalPlan) + ' 件</span>';
            html += '<span class="expand-hint">' + (defaultOpen ? '收起' : '展开') + '</span>';
            html += '</button>';

            html += '<div class="day-panel-body' + (defaultOpen ? '' : ' collapsed') + '">';
            html += '<div style="overflow-x:auto;padding:0.5rem 0;">';
            html += buildPlanTable(dayItems);
            html += '</div></div></div>';
        });

        container.innerHTML = html;

        // Bind accordion
        container.querySelectorAll('.day-panel-header').forEach(function (header) {
            header.addEventListener('click', function () {
                var body = this.nextElementSibling;
                var chevron = this.querySelector('.chevron');
                var hint = this.querySelector('.expand-hint');
                var isCollapsed = body.classList.contains('collapsed');
                body.classList.toggle('collapsed');
                chevron.classList.toggle('collapsed');
                hint.textContent = isCollapsed ? '收起' : '展开';
            });
        });
    }

    // ==================== Build Plan Table ====================

    function buildPlanTable(items) {
        var html = '<table class="plan-table"><thead><tr>' +
            '<th style="text-align:left;">客户名称</th>' +
            '<th style="text-align:left;">产品编码 / 名称</th>' +
            '<th style="text-align:right;">计划数量</th>' +
            '<th style="text-align:right;">当前库存</th>' +
            '<th style="text-align:center;">库存状态</th>' +
            '<th style="text-align:right;">累计出货</th>' +
            '<th style="text-align:right;">剩余计划</th>' +
            '<th style="min-width:140px;">出货进度</th>' +
            '<th style="text-align:center;">操作</th>' +
            '</tr></thead><tbody>';

        if (items.length === 0) {
            html += '<tr><td colspan="9" style="text-align:center;padding:2rem;color:#9ca3af;">暂无计划数据</td></tr>';
        }

        items.forEach(function (item) {
            var remaining = Math.max(item.quantity - item.shipped_qty, 0);
            var isVoid = item.shipment_status === 'completed' && remaining <= 0 && item.shipped_qty >= item.quantity;

            // Stock badge
            var stockBadge = buildStockBadge(item.stock_status);

            // Progress bar
            var progressHtml = buildProgressBar(item.shipped_qty, item.quantity);

            // Row class
            var rowClass = isVoid ? ' voided' : '';

            html += '<tr class="' + rowClass + '">';
            html += '<td style="font-weight:500;white-space:nowrap;">' + item.customer_name + '</td>';
            html += '<td><div class="product-code">' + (item.barcode || '') + '</div><div class="product-name">' + item.product_name + '</div></td>';
            html += '<td style="text-align:right;font-weight:600;white-space:nowrap;">' + formatNumber(item.quantity) + '</td>';
            html += '<td style="text-align:right;font-weight:600;white-space:nowrap;color:' + (item.inventory_qty >= item.quantity ? '#15803d' : '#b91c1c') + ';">' + formatNumber(item.inventory_qty) + '</td>';
            html += '<td style="text-align:center;">' + stockBadge + '</td>';
            html += '<td style="text-align:right;font-weight:600;white-space:nowrap;">' + formatNumber(item.shipped_qty) + '</td>';
            html += '<td style="text-align:right;font-weight:600;white-space:nowrap;color:' + (remaining > 0 ? '#92400e' : '#15803d') + ';">' + formatNumber(remaining) + '</td>';
            html += '<td>' + progressHtml + '</td>';
            html += '<td style="text-align:center;white-space:nowrap;">';
            html += '<button class="action-btn view" data-plan-id="' + item.plan_id + '"><i class="fas fa-eye"></i> 详情</button> ';
            html += '<button class="action-btn edit" data-plan-id="' + item.plan_id + '"><i class="fas fa-pencil-alt"></i> 修改</button> ';
            html += '<button class="action-btn void" data-plan-id="' + item.plan_id + '"><i class="fas fa-ban"></i> 作废</button>';
            html += '</td></tr>';
        });

        html += '</tbody></table>';
        return html;
    }

    function buildStockBadge(status) {
        var map = {
            'sufficient': { label: '库存充足', icon: 'fa-check-circle', cls: 'sufficient' },
            'shortage':   { label: '库存紧张', icon: 'fa-exclamation-circle', cls: 'shortage' },
            'no_stock':   { label: '无库存', icon: 'fa-times-circle', cls: 'no_stock' },
        };
        var m = map[status] || map['sufficient'];
        return '<span class="stock-badge ' + m.cls + '"><i class="fas ' + m.icon + '"></i> ' + m.label + '</span>';
    }

    function buildProgressBar(shipped, plan) {
        var pct = plan > 0 ? Math.min(Math.round(shipped / plan * 100), 100) : 0;
        var isOver = shipped > plan && plan > 0;
        var remaining = Math.max(plan - shipped, 0);
        var colorCls = 'low';
        if (isOver) colorCls = 'over';
        else if (pct >= 100) colorCls = 'high';
        else if (pct >= 60) colorCls = 'mid';

        var html = '<div class="progress-wrap">';
        html += '<div class="progress-info"><span class="pct ' + colorCls + '">' + pct + '%' + (isOver ? ' 超量' : '') + '</span><span class="remaining">剩余 ' + remaining + '</span></div>';
        html += '<div class="progress-bar-track"><div class="progress-bar-fill ' + colorCls + '" style="width:' + pct + '%;"></div></div>';
        if (isOver) {
            html += '<div class="over-warning"><i class="fas fa-exclamation-circle"></i> 超量' + (shipped - plan) + '</div>';
        }
        html += '</div>';
        return html;
    }

    // ==================== Create Plan ====================

    function createPlan() {
        var customerSelect = document.getElementById('addCustomer');
        var customerId = parseInt(customerSelect.value, 10);
        var customerName = customerSelect.options[customerSelect.selectedIndex].dataset.name;
        var planMonth = document.getElementById('addPlanMonth').value;
        var remark = document.getElementById('addRemark').value;

        if (!customerId) { notify('请选择客户', 'warning'); return; }
        if (!planMonth) { notify('请选择计划月份', 'warning'); return; }

        var details = [];
        document.querySelectorAll('#addDetailRows .detail-row').forEach(function (row) {
            var barcode = row.querySelector('.add-barcode').value.trim();
            var productName = row.querySelector('.add-product-name').value.trim();
            var productId = parseInt(row.querySelector('.add-product-id').value, 10);
            var quantity = parseInt(row.querySelector('.add-quantity').value, 10);
            var planDate = row.querySelector('.add-date').value;
            if (barcode && quantity > 0 && planDate) {
                details.push({ product_id: productId, product_name: productName, barcode: barcode, quantity: quantity, plan_date: planDate, remark: '' });
            }
        });
        if (details.length === 0) { notify('请至少添加一条明细', 'warning'); return; }

        apiFetch('/api/v1/plans/create', {
            method: 'POST',
            body: { customer_id: customerId, customer_name: customerName, plan_month: planMonth, details: details, remark: remark },
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
             '<div class="row g-2"><div class="col-6"><label class="form-label mb-1 small">产品名称</label><div class="position-relative"><input type="text" class="form-control form-control-sm add-product-name" required placeholder="输入关键字搜索产品" autocomplete="off"><div class="product-search-dropdown" style="display:none;"></div></div></div><div class="col-3"><label class="form-label mb-1 small">数量</label><input type="number" class="form-control form-control-sm add-quantity" required min="1" max="999999"></div><div class="col-3"><label class="form-label mb-1 small">日期</label><input type="date" class="form-control form-control-sm add-date" required></div></div>' +
            '<input type="hidden" class="add-product-id" value="0">';
        container.appendChild(row);
        row.querySelector('.remove-row-btn').addEventListener('click', function () { row.remove(); });
    }

    // ==================== Edit ====================

    document.addEventListener('click', function (e) {
        var editBtn = e.target.closest('.action-btn.edit');
        if (editBtn) {
            var planId = editBtn.dataset.planId;
            apiFetch('/api/v1/plans/detail/' + planId).then(function (data) {
                document.getElementById('editId').value = data.plan.id;
                document.getElementById('editStatus').value = data.plan.status;
                document.getElementById('editRemark').value = data.plan.remark || '';
                new bootstrap.Modal(document.getElementById('editModal')).show();
            });
        }

        var viewBtn = e.target.closest('.action-btn.view');
        if (viewBtn) {
            var planId = viewBtn.dataset.planId;
            apiFetch('/api/v1/plans/detail/' + planId).then(function (data) {
                notify('计划详情: ' + data.plan.plan_no + ' - ' + data.plan.customer_name + ' (' + data.details.length + '条明细)', 'info');
            });
        }

        var voidBtn = e.target.closest('.action-btn.void');
        if (voidBtn) {
            var planId = voidBtn.dataset.planId;
            if (confirm('确定要作废此计划吗？')) {
                apiFetch('/api/v1/plans/edit/' + planId, {
                    method: 'PUT',
                    body: { status: 'cancelled' },
                }).then(function (r) {
                    if (r.success) { notify('计划已作废', 'success'); loadMonthlyData(); }
                }).catch(function (e) { notify('操作失败: ' + e.message, 'danger'); });
            }
        }
    });

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

    // ==================== Upload ====================

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
                    if (r.is_async && r.task_id) { pollTaskStatus(r.task_id); return; }
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
                }).catch(function () { clearInterval(taskPollingTimer); });
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
                        '<td>' + d.product_name + '</td><td>' + d.barcode + '</td>' +
                        '<td contenteditable="true" data-field="quantity">' + d.quantity + '</td>' +
                        '<td contenteditable="true" data-field="plan_date">' + d.plan_date + '</td>' +
                        '<td contenteditable="true" data-field="remark">' + (d.remark || '') + '</td>' +
                        '<td>' + (d.is_validated ? '<span class="text-success"><i class="fas fa-check"></i></span>' : '<span class="text-danger" title="' + (d.validation_error || '') + '"><i class="fas fa-exclamation-triangle"></i></span>') + '</td></tr>';
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
            }).catch(function (e) { notify('验证失败: ' + e.message, 'danger'); });
    }

    function confirmStaging() {
        var selectedIds = [];
        document.querySelectorAll('.staging-row-check:checked').forEach(function (cb) { selectedIds.push(parseInt(cb.dataset.id, 10)); });
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
