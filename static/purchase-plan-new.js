/**
 * 出货计划管理 - 前端交互逻辑（重构版 v2）
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
        // silent 模式：跳过 api-client 的自动错误通知，由调用方自行处理
        if (window.api && !(options && options.silent)) {
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
        delete merged.silent;  // silent 不是 fetch 参数
        if (merged.body && typeof merged.body === 'object') merged.body = JSON.stringify(merged.body);
        return fetch(url, merged).then(function (r) {
            if (!r.ok) return r.json().then(function (e) { throw new Error(e.detail || '请求失败 (' + r.status + ')'); });
            return r.json();
        });
    }

    /**
     * 格式化错误详情为多行对齐的 HTML
     * 输入格式：后端返回的 "库存不足，无法添加出货计划：产品 SKU(name) 当前库存 X，不足合计计划数量 Y；库存不足 Z; 产品 ..."
     * 每条 SKU 错误单独一行，首字段 "产品" 左对齐
     */
    function _formatErrorDetails(messages) {
        // 从每条错误消息中单独提取"产品 SKU(...) 当前库存 X 库存不足 Y"项
        var allItems = [];
        messages.forEach(function (msg) {
            var stockMatch = msg.match(/^库存不足[^：]*：(.+)$/);
            if (stockMatch) {
                var items = stockMatch[1].split('; ').filter(function (s) { return s.startsWith('产品 '); });
                allItems = allItems.concat(items);
            } else if (msg.startsWith('产品 ')) {
                allItems.push(msg);
            }
        });
        if (allItems.length > 0) {
            var html = '<div style="margin-top:6px;padding:8px 10px;background:#fff5f5;border-radius:4px;border-left:3px solid #dc3545;font-size:12px;line-height:1.8;overflow-x:auto;">'
                + '<table style="border-collapse:collapse;"><colgroup>'
                + '<col style="width:42px;">'          /* 产品 */
                + '<col style="width:140px;">'         /* SKU */
                + '<col style="width:280px;">'         /* 名称 */
                + '<col style="width:70px;">'          /* 当前库存 标签 */
                + '<col style="width:60px;">'          /* 当前库存 数值 */
                + '<col style="width:70px;">'          /* 库存不足 标签 */
                + '<col style="width:60px;">'          /* 库存不足 数值 */
                + '</colgroup>';
            allItems.forEach(function (item) {
                var m = item.match(/^产品 (\S+)\((.+?)\) 当前库存 (\S+) 库存不足 (\S+)/);
                if (m) {
                    html += '<tr>'
                        + '<td style="white-space:nowrap;color:#dc3545;">产品</td>'
                        + '<td style="white-space:nowrap;font-family:monospace;">' + m[1] + '</td>'
                        + '<td style="white-space:nowrap;">(' + m[2] + ')</td>'
                        + '<td style="white-space:nowrap;">当前库存</td><td style="white-space:nowrap;font-family:monospace;text-align:right;"><b>' + m[3] + '</b></td>'
                        + '<td style="white-space:nowrap;">库存不足</td><td style="white-space:nowrap;font-family:monospace;text-align:right;"><b style="color:#dc3545;">' + m[4] + '</b></td>'
                        + '</tr>';
                } else {
                    html += '<tr><td colspan="7" style="white-space:nowrap;">' + item + '</td></tr>';
                }
            });
            html += '</table></div>';
            return html;
        }
        // 非库存不足错误，简单显示
        return '<div style="margin-top:4px;font-size:12px;color:#dc3545;">' + messages.join('; ') + '</div>';
    }

    function formatNumber(n) {
        if (n === null || n === undefined || n === '') return '0';
        return Number(n).toLocaleString();
    }

    // ==================== Detail Modal ====================

    var _statusLabels = { pending: '待确认', confirmed: '已确认', completed: '已完成', cancelled: '已取消' };
    var _stockStatusLabels = { sufficient: '库存充足', shortage: '库存紧张', no_stock: '无库存' };
    var _shipmentStatusLabels = { completed: '已出货', partial: '部分出货', pending: '未出货' };

    function openDetailModal(planId) {
        var modalEl = document.getElementById('detailModal');
        document.getElementById('detailPlanInfo').innerHTML = '<div class="text-center text-muted py-3"><i class="fas fa-spinner fa-spin"></i> 加载中...</div>';
        document.getElementById('detailPlanDetails').innerHTML = '';
        document.getElementById('detailShipmentRecords').innerHTML = '';
        new bootstrap.Modal(modalEl).show();

        // 并行获取计划详情 + 出货流水
        var detailPromise = apiFetch('/api/v1/plans/detail/' + planId);
        var shipmentPromise = apiFetch('/api/v1/plans/shipment/records?plan_id=' + planId);

        detailPromise.then(function (data) {
            var plan = data.plan;
            var details = data.details;

            // 基本信息
            var statusLabel = _statusLabels[plan.status] || plan.status;
            var statusCls = plan.status === 'completed' ? 'success' : plan.status === 'cancelled' ? 'danger' : 'warning';
            document.getElementById('detailPlanInfo').innerHTML =
                '<div class="detail-info-row">'
                + '<div class="info-item"><span class="info-label">计划编号：</span><span class="info-value">' + plan.plan_no + '</span></div>'
                + '<div class="info-item"><span class="info-label">客户：</span><span class="info-value">' + plan.customer_name + '</span></div>'
                + '<div class="info-item"><span class="info-label">月份：</span><span class="info-value">' + plan.plan_month + '</span></div>'
                + '<div class="info-item"><span class="info-label">状态：</span><span class="badge bg-' + statusCls + '">' + statusLabel + '</span></div>'
                + (plan.remark ? '<div class="info-item"><span class="info-label">备注：</span><span class="info-value">' + plan.remark + '</span></div>' : '')
                + '</div>';

            // 明细表
            var html = '<table class="detail-table"><thead><tr>'
                + '<th>产品编码</th><th>产品名称</th><th>计划数量</th><th>当前库存</th><th>库存状态</th><th>累计出货</th><th>剩余</th><th>出货进度</th>'
                + '</tr></thead><tbody>';
            if (details.length === 0) {
                html += '<tr><td colspan="8" style="text-align:center;color:#9ca3af;">暂无明细</td></tr>';
            } else {
                details.forEach(function (d) {
                    var remaining = Math.max(d.quantity - d.shipped_qty, 0);
                    var pct = d.quantity > 0 ? Math.round(d.shipped_qty / d.quantity * 100) : 0;
                    var stockLabel = _stockStatusLabels[d.stock_status] || d.stock_status;
                    var shipLabel = _shipmentStatusLabels[d.shipment_status] || d.shipment_status;
                    var barColor = pct >= 100 ? '#15803d' : pct >= 50 ? '#f59e0b' : '#dc2626';
                    html += '<tr>'
                        + '<td style="font-family:monospace;">' + (d.barcode || '') + '</td>'
                        + '<td>' + d.product_name + '</td>'
                        + '<td style="text-align:right;font-weight:600;">' + formatNumber(d.quantity) + '</td>'
                        + '<td style="text-align:right;font-weight:600;color:' + (d.inventory_qty >= d.quantity ? '#15803d' : '#b91c1c') + ';">' + formatNumber(d.inventory_qty) + '</td>'
                        + '<td>' + stockLabel + '</td>'
                        + '<td style="text-align:right;font-weight:600;">' + formatNumber(d.shipped_qty) + '</td>'
                        + '<td style="text-align:right;font-weight:600;color:' + (remaining > 0 ? '#92400e' : '#15803d') + ';">' + formatNumber(remaining) + '</td>'
                        + '<td style="min-width:100px;"><div style="display:flex;align-items:center;gap:4px;"><div style="flex:1;height:6px;background:#e5e7eb;border-radius:3px;overflow:hidden;"><div style="height:100%;width:' + pct + '%;background:' + barColor + ';border-radius:3px;"></div></div><span style="font-size:11px;font-weight:600;min-width:32px;">' + pct + '%</span></div></td>'
                        + '</tr>';
                });
            }
            html += '</tbody></table>';
            document.getElementById('detailPlanDetails').innerHTML = html;
        }).catch(function (e) {
            document.getElementById('detailPlanInfo').innerHTML = '<div class="text-danger">加载失败: ' + e.message + '</div>';
        });

        shipmentPromise.then(function (data) {
            var records = data.records || [];
            var html = '<table class="detail-table"><thead><tr>'
                + '<th>出货单号</th><th>产品名称</th><th>出货数量</th><th>出货日期</th><th>来源</th>'
                + '</tr></thead><tbody>';
            if (records.length === 0) {
                html += '<tr><td colspan="5" style="text-align:center;color:#9ca3af;">暂无出货记录</td></tr>';
            } else {
                records.forEach(function (r) {
                    html += '<tr>'
                        + '<td style="font-family:monospace;">' + (r.shipment_no || '') + '</td>'
                        + '<td>' + r.product_name + '</td>'
                        + '<td style="text-align:right;font-weight:600;">' + formatNumber(r.quantity) + '</td>'
                        + '<td>' + (r.shipment_date || '') + '</td>'
                        + '<td>' + (r.source_type === 'stockout' ? '直接出库' : '出货同步') + '</td>'
                        + '</tr>';
                });
            }
            html += '</tbody></table>';
            document.getElementById('detailShipmentRecords').innerHTML = html;
        }).catch(function () {
            document.getElementById('detailShipmentRecords').innerHTML = '<div style="text-align:center;color:#9ca3af;">暂无出货记录</div>';
        });
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

    // ==================== State ====================

    var selectedMonth = '';
    var searchQuery = '';
    var selectedCustomerIds = [];
    var allCalendarData = null;  // Raw data from /monthly
    var taskPollingTimer = null;
    var lastDetectedMonth = '';  // 上传时检测到的月份，用于确认后自动切换
    var customerOptionsHtml = '';  // 客户下拉选项模板，初始化时缓存
    var activeTab = 'timeline';   // 'timeline' | 'summary'

    // Initialize month
    var now = new Date();
    selectedMonth = now.getFullYear() + '-' + String(now.getMonth() + 1).padStart(2, '0');
    var monthInput = document.getElementById('filterMonthInput');
    if (monthInput) monthInput.value = selectedMonth;

    // Cache customer options from the initial row
    var _firstCustomerSelect = document.querySelector('#addDetailRows .add-customer');
    if (_firstCustomerSelect) {
        _firstCustomerSelect.querySelectorAll('option').forEach(function (opt) {
            customerOptionsHtml += '<option value="' + opt.value + '" data-name="' + (opt.dataset.name || '') + '">' + opt.textContent + '</option>';
        });
    }

    // ==================== Init ====================

    loadMonthlyData();

    // ==================== Event Bindings ====================

    // Tab switching
    function updateTabUI() {
        document.querySelectorAll('.view-tab').forEach(function (tab) {
            tab.classList.toggle('active', tab.dataset.tab === activeTab);
        });
    }
    document.querySelectorAll('.view-tab').forEach(function (tab) {
        tab.addEventListener('click', function () {
            activeTab = this.dataset.tab;
            updateTabUI();
            renderView();
        });
    });

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
        renderView();
    });

    document.getElementById('downloadTemplateBtn').addEventListener('click', function () {
        window.location.href = '/plans/template';
    });

    // Add plan
    document.getElementById('addSubmitBtn').addEventListener('click', createPlan);
    document.getElementById('addDetailRowBtn').addEventListener('click', addDetailRow);

    // 弹窗关闭时重置按钮和反馈状态
    document.getElementById('addModal').addEventListener('hidden.bs.modal', function () {
        var btn = document.getElementById('addSubmitBtn');
        btn.disabled = false;
        btn.innerHTML = '创建出货计划';
        var feedback = document.getElementById('addFormFeedback');
        if (feedback) { feedback.style.display = 'none'; feedback.innerHTML = ''; }
    });

    // Barcode validation removed - barcode auto-populated from product search

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
            renderView();
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

        var html = '<span class="bar-label">客户：</span>';
        html += '<button class="customer-chip' + (allSelected ? ' active' : '') + '" data-customer-id="0">' +
            '<i class="fas fa-globe chip-icon"></i>全部</button>';

        customers.forEach(function (c) {
            var isActive = selectedCustomerIds.length > 0 && selectedCustomerIds[0] === c.id;
            var iconHtml = c.icon_url
                ? '<img src="' + c.icon_url + '" alt="' + c.name + '">'
                : '<i class="fas fa-user-circle chip-icon"></i>';
            html += '<button class="customer-chip' + (isActive ? ' active' : '') + '" data-customer-id="' + c.id + '">' +
                iconHtml + ' ' + c.name + '</button>';
        });

        container.innerHTML = html;

        // Bind events — single-select mode
        container.querySelectorAll('.customer-chip').forEach(function (chip) {
            chip.addEventListener('click', function () {
                var cid = parseInt(this.dataset.customerId, 10);
                if (cid === 0) {
                    selectedCustomerIds = [];
                } else {
                    // Toggle: clicking the already-selected customer deselects back to "全部"
                    selectedCustomerIds = (selectedCustomerIds.length > 0 && selectedCustomerIds[0] === cid)
                        ? [] : [cid];
                }
                renderCustomerBar(customers);
                renderView();
            });
        });
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

    function groupByCustomerDate(items) {
        // Step 1: Build nested map customer_id → date_str → [items]
        var customerMap = {};
        items.forEach(function (item) {
            if (!customerMap[item.customer_id]) {
                customerMap[item.customer_id] = {
                    customer_id: item.customer_id,
                    customer_name: item.customer_name,
                    dateMap: {}
                };
            }
            var cust = customerMap[item.customer_id];
            if (!cust.dateMap[item._dateStr]) {
                cust.dateMap[item._dateStr] = [];
            }
            cust.dateMap[item._dateStr].push(item);
        });

        // Step 1.5: Aggregate same-product items within each (customer, date)
        Object.keys(customerMap).forEach(function (cid) {
            var cust = customerMap[cid];
            Object.keys(cust.dateMap).forEach(function (dateStr) {
                var rawItems = cust.dateMap[dateStr];
                var skuMap = {};
                rawItems.forEach(function (item) {
                    var key = item.product_id || item.barcode || item.product_name;
                    if (!skuMap[key]) {
                        // First occurrence — clone as base
                        skuMap[key] = {
                            customer_id: item.customer_id,
                            customer_name: item.customer_name,
                            product_id: item.product_id,
                            product_name: item.product_name,
                            barcode: item.barcode,
                            inventory_qty: item.inventory_qty,
                            quantity: 0,
                            shipped_qty: 0,
                            plan_ids: [],
                            _dateStr: item._dateStr
                        };
                    }
                    skuMap[key].quantity += item.quantity;
                    skuMap[key].shipped_qty += item.shipped_qty;
                    if (item.plan_id) skuMap[key].plan_ids.push(item.plan_id);
                });
                // Derive shipment_status from aggregated totals
                var aggregated = Object.keys(skuMap).map(function (key) {
                    var a = skuMap[key];
                    a.shipment_status = a.shipped_qty >= a.quantity ? 'completed' : (a.shipped_qty > 0 ? 'partial' : 'pending');
                    a.plan_id = a.plan_ids[0] || null;  // primary plan_id for detail button
                    return a;
                });
                cust.dateMap[dateStr] = aggregated;
            });
        });

        // Step 2: Convert to sorted array with span counts
        var result = [];
        var customerIds = Object.keys(customerMap).sort(function (a, b) {
            return customerMap[a].customer_name.localeCompare(customerMap[b].customer_name, 'zh-CN');
        });

        customerIds.forEach(function (cid) {
            var cust = customerMap[cid];
            var dateGroups = [];
            var customerSpan = 0;
            var dateKeys = Object.keys(cust.dateMap).sort();

            dateKeys.forEach(function (dateStr) {
                var dateItems = cust.dateMap[dateStr];
                dateGroups.push({
                    date_str: dateStr,
                    date_label: formatDateLabel(dateStr),
                    date_span: dateItems.length,
                    is_today: dateStr === new Date().toISOString().slice(0, 10),
                    items: dateItems
                });
                customerSpan += dateItems.length;
            });

            result.push({
                customer_id: cust.customer_id,
                customer_name: cust.customer_name,
                customer_span: customerSpan,
                dates: dateGroups
            });
        });

        return result;
    }

    function formatDateLabel(dateStr) {
        var d = new Date(dateStr + 'T00:00:00');
        var weekMap = ['日', '一', '二', '三', '四', '五', '六'];
        return String(d.getMonth() + 1).padStart(2, '0') + '月' + String(d.getDate()).padStart(2, '0') + '日 周' + weekMap[d.getDay()];
    }

    // ==================== Group by Customer + Product (monthly summary) ====================

    function groupByCustomerProduct(items) {
        var customerMap = {};
        items.forEach(function (item) {
            if (!customerMap[item.customer_id]) {
                customerMap[item.customer_id] = {
                    customer_id: item.customer_id,
                    customer_name: item.customer_name,
                    skuMap: {}
                };
            }
            var cust = customerMap[item.customer_id];
            var key = item.product_id || item.barcode || item.product_name;
            if (!cust.skuMap[key]) {
                cust.skuMap[key] = {
                    customer_id: item.customer_id,
                    product_id: item.product_id,
                    product_name: item.product_name,
                    barcode: item.barcode,
                    inventory_qty: item.inventory_qty,
                    quantity: 0,
                    shipped_qty: 0
                };
            }
            cust.skuMap[key].quantity += item.quantity;
            cust.skuMap[key].shipped_qty += item.shipped_qty;
        });

        var result = [];
        var customerIds = Object.keys(customerMap).sort(function (a, b) {
            return customerMap[a].customer_name.localeCompare(customerMap[b].customer_name, 'zh-CN');
        });

        customerIds.forEach(function (cid) {
            var cust = customerMap[cid];
            var products = [];
            Object.keys(cust.skuMap).sort().forEach(function (key) {
                var p = cust.skuMap[key];
                p.shipment_status = p.shipped_qty >= p.quantity ? 'completed' : (p.shipped_qty > 0 ? 'partial' : 'pending');
                products.push(p);
            });
            result.push({
                customer_id: cust.customer_id,
                customer_name: cust.customer_name,
                customer_span: products.length,
                products: products
            });
        });

        return result;
    }

    // ==================== Build Summary Table ====================

    function buildSummaryTable(grouped) {
        var html = '<table class="plan-table report-table"><thead><tr>' +
            '<th class="col-customer" style="text-align:center;">客户名称</th>' +
            '<th style="text-align:left;">产品名称</th>' +
            '<th style="text-align:right;min-width:120px;">计划总量</th>' +
            '<th style="text-align:right;min-width:90px;">累计出货</th>' +
            '<th style="text-align:right;min-width:70px;">剩余</th>' +
            '<th style="text-align:center;min-width:100px;">出货进度</th>' +
            '</tr></thead><tbody>';

        if (grouped.length === 0) {
            html += '<tr><td colspan="6" style="text-align:center;padding:2rem;color:#9ca3af;">暂无汇总数据</td></tr>';
        }

        grouped.forEach(function (customer) {
            customer.products.forEach(function (item, itemIdx) {
                var remaining = Math.max(item.quantity - item.shipped_qty, 0);
                var pct = item.quantity > 0 ? Math.round(item.shipped_qty / item.quantity * 100) : 0;
                var barColor = pct >= 100 ? '#10b981' : pct >= 50 ? '#f59e0b' : '#ef4444';
                var isVoid = item.shipment_status === 'completed';
                var rowClass = isVoid ? ' voided' : '';

                html += '<tr class="' + rowClass + '">';

                if (itemIdx === 0) {
                    html += '<td class="cell-customer cell-customer-clickable" rowspan="' + customer.customer_span + '" data-customer-id="' + customer.customer_id + '">' +
                        '<span class="customer-name-text">' + customer.customer_name + '</span>' +
                        '<span class="customer-count-badge">' + customer.customer_span + ' SKU</span>' +
                        '</td>';
                }

                html += '<td><div class="product-name" style="padding-left:19px;">' + item.product_name + '</div></td>';

                // 计划总量
                var invColor = item.inventory_qty >= item.quantity ? '#15803d' : '#b91c1c';
                html += '<td style="text-align:right;white-space:nowrap;"><span style="font-weight:600;">' + formatNumber(item.quantity) + '</span> <span style="color:#9ca3af;">/</span> <span style="font-weight:600;color:' + invColor + ';">' + formatNumber(item.inventory_qty) + '</span></td>';

                // 累计出货
                html += '<td style="text-align:right;font-weight:600;white-space:nowrap;">' +
                    formatNumber(item.shipped_qty) + ' <span style="font-size:11px;color:#6b7280;font-weight:400;">(' + pct + '%)</span></td>';

                // 剩余
                html += '<td style="text-align:right;font-weight:600;white-space:nowrap;color:' +
                    (remaining > 0 ? '#92400e' : '#15803d') + ';">' + formatNumber(remaining) + '</td>';

                // 出货进度
                html += '<td style="min-width:100px;"><div style="display:flex;align-items:center;gap:4px;">' +
                    '<div style="flex:1;height:6px;background:#e5e7eb;border-radius:3px;overflow:hidden;">' +
                    '<div style="height:100%;width:' + pct + '%;background:' + barColor + ';border-radius:3px;"></div></div>' +
                    '<span style="font-size:11px;font-weight:600;min-width:32px;">' + pct + '%</span></div></td>';

                html += '</tr>';
            });
        });

        html += '</tbody></table>';
        return html;
    }

    // ==================== Render (dispatch by active tab) ====================

    function renderView() {
        if (activeTab === 'summary') {
            renderSummary();
        } else {
            renderTimeline();
        }
    }

    function renderSummary() {
        var items = getFilteredItems();
        var grouped = groupByCustomerProduct(items);
        var container = document.getElementById('timelinePanels');

        var skuCount = 0;
        grouped.forEach(function (c) { skuCount += c.customer_span; });
        document.getElementById('activePlanCount').textContent = skuCount;

        // Update date counts from raw data (shared header subtitle)
        var dateSet = {};
        items.forEach(function (i) { dateSet[i._dateStr] = true; });
        document.getElementById('activeDateCount').textContent = Object.keys(dateSet).length;

        if (items.length === 0) {
            container.innerHTML =
                '<div class="empty-state">' +
                    '<i class="fas fa-layer-group empty-icon"></i>' +
                    '<p>当前条件下暂无汇总数据</p>' +
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
                    renderView();
                });
            }
            return;
        }

        container.innerHTML = '<div style="overflow-x:auto;">' + buildSummaryTable(grouped) + '</div>';

        // Bind customer name click → switch to timeline filtered by that customer
        container.querySelectorAll('.cell-customer-clickable').forEach(function (cell) {
            cell.style.cursor = 'pointer';
            cell.title = '点击查看该客户出货时序';
            cell.addEventListener('click', function () {
                var cid = parseInt(this.dataset.customerId, 10);
                selectedCustomerIds = [cid];
                activeTab = 'timeline';
                updateTabUI();
                if (allCalendarData) renderCustomerBar(allCalendarData.customers);
                renderView();
            });
        });
    }

    function renderTimeline() {
        var items = getFilteredItems();
        var grouped = groupByCustomerDate(items);
        var container = document.getElementById('timelinePanels');

        // Update counts — use grouped SKU count (after aggregation)
        var skuCount = 0;
        var dateSet = {};
        grouped.forEach(function (c) {
            c.dates.forEach(function (d) {
                skuCount += d.items.length;
                dateSet[d.date_str] = true;
            });
        });
        var dateCount = Object.keys(dateSet).length;
        document.getElementById('activePlanCount').textContent = skuCount;
        document.getElementById('activeDateCount').textContent = dateCount;
        document.getElementById('planDateCount').textContent = dateCount;

        if (items.length === 0) {
            container.innerHTML =
                '<div class="empty-state">' +
                    '<i class="fas fa-chart-bar empty-icon"></i>' +
                    '<p>当前条件下暂无出货计划数据</p>' +
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
                    renderView();
                });
            }
            return;
        }

        container.innerHTML = '<div style="overflow-x:auto;">' + buildReportTable(grouped) + '</div>';
    }

    // ==================== Build Report Table (merged cells) ====================

    function buildReportTable(grouped) {
        var html = '<table class="plan-table report-table"><thead><tr>' +
            '<th class="col-customer" style="text-align:center;">客户名称</th>' +
            '<th class="col-date" style="text-align:center;">交货日期</th>' +
            '<th style="text-align:left;">产品名称</th>' +
            '<th style="text-align:right;min-width:120px;">计划 / 库存</th>' +
            '<th style="text-align:right;min-width:90px;">累计出货</th>' +
            '<th style="text-align:right;min-width:70px;">剩余</th>' +
            '<th style="text-align:center;min-width:80px;">操作</th>' +
            '</tr></thead><tbody>';

        if (grouped.length === 0) {
            html += '<tr><td colspan="7" style="text-align:center;padding:2rem;color:#9ca3af;">暂无计划数据</td></tr>';
        }

        grouped.forEach(function (customer) {
            customer.dates.forEach(function (dateGroup, dateIdx) {
                dateGroup.items.forEach(function (item, itemIdx) {
                    var remaining = Math.max(item.quantity - item.shipped_qty, 0);
                    var isVoid = item.shipment_status === 'completed' && remaining <= 0 && item.shipped_qty >= item.quantity;
                    var pct = item.quantity > 0 ? Math.round(item.shipped_qty / item.quantity * 100) : 0;
                    var barColor = pct >= 100 ? '#10b981' : pct >= 50 ? '#f59e0b' : '#ef4444';
                    var rowClass = isVoid ? ' voided' : '';

                    html += '<tr class="' + rowClass + '">';

                    // Customer name cell — only first row of customer group
                    if (dateIdx === 0 && itemIdx === 0) {
                        html += '<td class="cell-customer" rowspan="' + customer.customer_span + '">' +
                            '<span class="customer-name-text">' + customer.customer_name + '</span>' +
                            '<span class="customer-count-badge">' + customer.customer_span + ' 条</span>' +
                            '</td>';
                    }

                    // Date cell — only first row of date group within customer
                    if (itemIdx === 0) {
                        var todayTag = dateGroup.is_today ? '<span class="date-today-tag">今日</span>' : '';
                        html += '<td class="cell-date" rowspan="' + dateGroup.date_span + '">' +
                            '<span class="date-text">' + dateGroup.date_label + '</span>' +
                            todayTag +
                            '</td>';
                    }

                    // Product
                    html += '<td><div class="product-name">' + item.product_name + '</div></td>';

                    // Plan / Inventory
                    var invColor = item.inventory_qty >= item.quantity ? '#15803d' : '#b91c1c';
                    html += '<td style="text-align:right;white-space:nowrap;">' +
                        '<span style="font-weight:600;">' + formatNumber(item.quantity) + '</span> ' +
                        '<span style="color:#9ca3af;">/</span> ' +
                        '<span style="font-weight:600;color:' + invColor + ';">' + formatNumber(item.inventory_qty) + '</span>' +
                        '<div style="height:4px;background:#e5e7eb;border-radius:2px;margin-top:3px;overflow:hidden;">' +
                        '<div style="height:100%;width:' + pct + '%;background:' + barColor + ';border-radius:2px;"></div></div>' +
                        '</td>';

                    // Shipped
                    html += '<td style="text-align:right;font-weight:600;white-space:nowrap;">' +
                        formatNumber(item.shipped_qty) + ' <span style="font-size:11px;color:#6b7280;font-weight:400;">(' + pct + '%)</span></td>';

                    // Remaining
                    html += '<td style="text-align:right;font-weight:600;white-space:nowrap;color:' +
                        (remaining > 0 ? '#92400e' : '#15803d') + ';">' + formatNumber(remaining) + '</td>';

                    // Action
                    html += '<td style="text-align:center;white-space:nowrap;">' +
                        '<button class="action-btn view" data-plan-id="' + item.plan_id + '"><i class="fas fa-eye"></i> 详情</button>' +
                        '</td></tr>';
                });
            });
        });

        html += '</tbody></table>';
        return html;
    }

    // ==================== Create Plan ====================

    function createPlan() {
        var btn = document.getElementById('addSubmitBtn');
        if (btn.disabled) return;  // 防止重复提交
        btn.disabled = true;
        btn.innerHTML = '<i class="fas fa-spinner fa-spin me-1"></i>提交中...';
        var feedback = document.getElementById('addFormFeedback');
        feedback.style.display = 'none';

        var allDetails = [];
        var incompleteCount = 0;
        document.querySelectorAll('#addDetailRows .detail-row').forEach(function (row, idx) {
            var customerSelect = row.querySelector('.add-customer');
            var customerId = parseInt(customerSelect.value, 10);
            var customerName = customerSelect.options[customerSelect.selectedIndex]
                ? customerSelect.options[customerSelect.selectedIndex].dataset.name || ''
                : '';
            var barcode = row.querySelector('.add-barcode').value.trim();
            var productName = row.querySelector('.add-product-name').value.trim();
            var productId = parseInt(row.querySelector('.add-product-id').value, 10);
            var quantity = parseInt(row.querySelector('.add-quantity').value, 10);
            var planDate = row.querySelector('.add-date').value;
            if (customerId && productName && quantity > 0 && planDate) {
                allDetails.push({
                    customer_id: customerId,
                    customer_name: customerName,
                    product_id: productId,
                    product_name: productName,
                    barcode: barcode,
                    quantity: quantity,
                    plan_date: planDate,
                });
            } else {
                incompleteCount++;
            }
        });
        if (allDetails.length === 0) {
            feedback.innerHTML = '<i class="fas fa-exclamation-triangle text-warning me-1"></i><span class="text-warning">请至少添加一条完整明细（客户、产品、数量、出货时间均不能为空）</span>';
            feedback.style.display = '';
            btn.disabled = false; btn.innerHTML = '创建出货计划';
            return;
        }

        // 按客户+月份分组，每组调用一次 API
        var groups = {};
        allDetails.forEach(function (d) {
            var planMonth = d.plan_date.substring(0, 7);
            var key = d.customer_id + '_' + planMonth;
            if (!groups[key]) groups[key] = { customer_id: d.customer_id, customer_name: d.customer_name, plan_month: planMonth, details: [] };
            groups[key].details.push(d);
        });

        var promises = [];
        Object.keys(groups).forEach(function (key) {
            var g = groups[key];
            var details = g.details.map(function (d) {
                return { product_id: d.product_id, product_name: d.product_name, barcode: d.barcode, quantity: d.quantity, plan_date: d.plan_date, remark: '' };
            });
            promises.push(apiFetch('/api/v1/plans/create', {
                method: 'POST',
                body: { customer_id: g.customer_id, customer_name: g.customer_name, plan_month: g.plan_month, details: details, remark: '' },
                silent: true,
            }));
        });

        Promise.allSettled(promises).then(function (results) {
            var successCount = results.filter(function (r) { return r.status === 'fulfilled' && r.value.success; }).length;
            var failResults = results.filter(function (r) { return r.status === 'rejected' });
            var skipNote = incompleteCount > 0 ? '（已跳过 ' + incompleteCount + ' 条不完整明细）' : '';
            if (successCount === results.length) {
                feedback.innerHTML = '<i class="fas fa-check-circle text-success me-2"></i><span class="text-success">出货计划创建成功' + skipNote + '</span>';
            } else if (successCount > 0) {
                var failMsgs = failResults.map(function (r) { return r.reason && r.reason.message ? r.reason.message : '未知错误'; });
                feedback.innerHTML = '<i class="fas fa-exclamation-triangle text-warning me-2"></i><span class="text-warning">部分创建成功（' + successCount + '/' + results.length + '）' + skipNote + '</span>'
                    + _formatErrorDetails(failMsgs);
            } else {
                var failMsgs = failResults.map(function (r) { return r.reason && r.reason.message ? r.reason.message : '未知错误'; });
                feedback.innerHTML = '<i class="fas fa-times-circle text-danger me-2"></i><span class="text-danger">创建失败</span>'
                    + _formatErrorDetails(failMsgs);
                feedback.style.display = '';
                btn.disabled = false; btn.innerHTML = '创建出货计划';
                return;
            }
            feedback.style.display = '';
            // 成功后短暂显示反馈，再关闭弹窗
            setTimeout(function () {
                bootstrap.Modal.getInstance(document.getElementById('addModal')).hide();
                var firstDate = allDetails[0].plan_date;
                var planMonth = firstDate.substring(0, 7);
                if (planMonth !== selectedMonth) {
                    selectedMonth = planMonth;
                    var monthInput = document.getElementById('filterMonthInput');
                    if (monthInput) monthInput.value = selectedMonth;
                }
                loadMonthlyData();
            }, 800);
        }).catch(function (e) {
            feedback.innerHTML = '<i class="fas fa-times-circle text-danger me-2"></i><span class="text-danger">创建失败</span>'
                + _formatErrorDetails([e.message]);
            feedback.style.display = '';
        }).finally(function () {
            btn.disabled = false;
            btn.innerHTML = '创建出货计划';
        });
    }

    function addDetailRow() {
        var container = document.getElementById('addDetailRows');
        var row = document.createElement('div');
        row.className = 'detail-row border rounded p-2 mb-2';
        row.innerHTML =
            '<div class="d-flex justify-content-between align-items-center mb-2"><span class="small fw-bold">明细</span><button type="button" class="btn btn-sm btn-outline-danger remove-row-btn"><i class="fas fa-times"></i></button></div>' +
            '<div class="row g-2">' +
            '<div class="col-3"><label class="form-label mb-1 small">客户名称 <span class="text-danger">*</span></label><select class="form-select form-select-sm add-customer" required>' + customerOptionsHtml + '</select></div>' +
            '<div class="col-3"><label class="form-label mb-1 small">出货时间 <span class="text-danger">*</span></label><input type="date" class="form-control form-control-sm add-date" required></div>' +
            '<div class="col-3"><label class="form-label mb-1 small">产品名称 <span class="text-danger">*</span></label><div class="position-relative"><input type="text" class="form-control form-control-sm add-product-name" required placeholder="输入关键字搜索" autocomplete="off"><div class="product-search-dropdown" style="display:none;"></div></div></div>' +
            '<div class="col-3"><label class="form-label mb-1 small">数量 <span class="text-danger">*</span></label><input type="number" class="form-control form-control-sm add-quantity" required min="1" max="999999"></div>' +
            '</div>' +
            '<input type="hidden" class="add-product-id" value="0">' +
            '<input type="hidden" class="add-barcode" value="">';
        container.appendChild(row);
        row.querySelector('.remove-row-btn').addEventListener('click', function () { row.remove(); });
    }

    // ==================== Edit ====================

    document.addEventListener('click', function (e) {
        var viewBtn = e.target.closest('.action-btn.view');
        if (viewBtn) {
            var planId = viewBtn.dataset.planId;
            openDetailModal(planId);
        }
    });

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
                    if (r.detected_month) lastDetectedMonth = r.detected_month;
                    if (r.is_async && r.task_id) { pollTaskStatus(r.task_id); return; }
                    // 自动验证后展示预览
                    autoValidateAndPreview();
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
                        autoValidateAndPreview();
                    } else if (r.status === 'FAILURE') {
                        clearInterval(taskPollingTimer);
                        document.getElementById('uploadProgress').style.display = 'none';
                        notify('批量处理失败', 'danger');
                    }
                }).catch(function () { clearInterval(taskPollingTimer); });
        }, 1000);
    }

    function autoValidateAndPreview() {
        apiFetch('/api/v1/plans/staging/validate', { method: 'POST' })
            .then(function (r) {
                if (r.success) {
                    notify('验证完成：' + r.valid_count + '有效，' + r.error_count + '无效', r.error_count > 0 ? 'warning' : 'success');
                }
                loadStagingPreview();
            }).catch(function () {
                loadStagingPreview();
            });
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
                        '<td>' + (d.is_validated ? '<span class="text-success"><i class="fas fa-check"></i></span>' : '<span class="text-danger"><i class="fas fa-exclamation-triangle"></i> ' + (d.validation_error || '') + '</span>') + '</td></tr>';
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
                // 自动切换到计划所属月份
                if (lastDetectedMonth && lastDetectedMonth !== selectedMonth) {
                    selectedMonth = lastDetectedMonth;
                    var monthInput = document.getElementById('filterMonthInput');
                    if (monthInput) monthInput.value = selectedMonth;
                }
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
