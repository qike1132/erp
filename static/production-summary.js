/**
 * 生产计划模块 - 前端交互逻辑
 *
 * 三个Tab：手工部、包装部、汇总动态报表
 */
(function () {
    'use strict';

    // ==================== 工具函数 ====================

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

    function notify(message, type) {
        if (typeof GlobalNotification !== 'undefined' && GlobalNotification.show) {
            const typeMap = { success: 'success', error: 'error', warning: 'warning', info: 'info' };
            GlobalNotification.show(typeMap[type] || 'info', message);
        } else {
            alert(message);
        }
    }

    const now = new Date();
    const currentYear = now.getFullYear();
    const currentMonth = now.getMonth() + 1;

    // ==================== Tab 1: 手工部 ====================

    const craftYear = document.getElementById('craftYear');
    const craftMonth = document.getElementById('craftMonth');
    if (craftYear) craftYear.value = currentYear;
    if (craftMonth) craftMonth.value = currentMonth;

    document.getElementById('craftSearchBtn').addEventListener('click', loadCraftData);
    document.getElementById('craftAddSubmit').addEventListener('click', createCraftWork);
    document.getElementById('craftEditSubmit').addEventListener('click', saveCraftEdit);
    document.getElementById('craftExportBtn').addEventListener('click', function () {
        new bootstrap.Modal(document.getElementById('craftExportModal')).show();
    });
    document.getElementById('craftExportSubmit').addEventListener('click', doCraftExport);

    // 默认加载当月数据
    loadCraftData();

    function loadCraftData() {
        const year = parseInt(craftYear.value, 10);
        const month = parseInt(craftMonth.value, 10);
        if (!year || !month) return;

        apiFetch(`/api/v1/production-summary/craft/list?year=${year}&month=${month}`)
            .then(result => {
                renderCraftDaily(result.daily_summary);
                renderCraftTable(result.data);
                document.getElementById('craftRecordCount').textContent = `共 ${result.total} 条`;
            })
            .catch(err => notify('加载手工部数据失败: ' + err.message, 'error'));
    }

    function renderCraftDaily(dailySummary) {
        const tbody = document.getElementById('craftDailyBody');
        if (!dailySummary || Object.keys(dailySummary).length === 0) {
            tbody.innerHTML = '<tr><td colspan="3" class="text-center text-muted py-3">暂无数据</td></tr>';
            return;
        }

        const days = Object.values(dailySummary).sort((a, b) => a.day - b.day);
        tbody.innerHTML = days.map(d => {
            const hasData = d.craft_total > 0 || d.case_out_total > 0;
            const rowClass = hasData ? '' : 'text-muted';
            const dateClass = hasData ? 'date-has-data' : 'date-no-data';
            return `<tr class="${rowClass}">
                <td class="${dateClass}">${d.date}</td>
                <td class="text-center">${formatNumber(d.case_out_total)}</td>
                <td class="text-center fw-bold">${formatNumber(d.craft_total)}</td>
            </tr>`;
        }).join('');
    }

    function renderCraftTable(data) {
        const tbody = document.getElementById('craftTableBody');
        if (!data || data.length === 0) {
            tbody.innerHTML = '<tr><td colspan="5" class="text-center py-4 text-muted">当月暂无生产记录</td></tr>';
            return;
        }

        tbody.innerHTML = data.map(r => `<tr>
            <td><span class="fw-semibold">${_esc(r.worker_name)}</span></td>
            <td class="text-center fw-bold">${formatNumber(r.quantity)}</td>
            <td>${r.work_date}</td>
            <td><small class="text-muted">${_esc(r.remark)}</small></td>
            <td>
                <button onclick="window._editCraft(${r.id},'${_esc(r.worker_name)}',${r.quantity},'${r.work_date}','${_esc(r.remark)}')" class="btn btn-sm btn-outline-primary me-1"><i class="fas fa-edit"></i></button>
                <button onclick="window._deleteCraft(${r.id})" class="btn btn-sm btn-outline-danger"><i class="fas fa-trash"></i></button>
            </td>
        </tr>`).join('');
    }

    function createCraftWork() {
        const data = {
            worker_name: document.getElementById('craftWorkerName').value.trim(),
            quantity: parseInt(document.getElementById('craftQuantity').value, 10),
            work_date: document.getElementById('craftWorkDate').value,
            remark: document.getElementById('craftRemark').value.trim(),
        };
        if (!data.worker_name) { notify('请输入工人姓名', 'error'); return; }
        if (!data.quantity || data.quantity <= 0) { notify('生产数量必须为正数', 'error'); return; }
        if (!data.work_date) { notify('请选择生产日期', 'error'); return; }

        apiFetch('/api/v1/production-summary/craft/create', {
            method: 'POST',
            body: JSON.stringify(data),
        }).then(result => {
            if (result.success) {
                notify(result.message, 'success');
                bootstrap.Modal.getInstance(document.getElementById('craftAddModal')).hide();
                document.getElementById('craftAddForm').reset();
                loadCraftData();
            }
        }).catch(err => notify(err.message, 'error'));
    }

    window._editCraft = function (id, workerName, quantity, workDate, remark) {
        document.getElementById('craftEditId').value = id;
        document.getElementById('craftEditWorkerName').value = workerName;
        document.getElementById('craftEditQuantity').value = quantity;
        document.getElementById('craftEditWorkDate').value = workDate;
        document.getElementById('craftEditRemark').value = remark;
        new bootstrap.Modal(document.getElementById('craftEditModal')).show();
    };

    function saveCraftEdit() {
        const id = document.getElementById('craftEditId').value;
        const data = {
            worker_name: document.getElementById('craftEditWorkerName').value.trim(),
            quantity: parseInt(document.getElementById('craftEditQuantity').value, 10),
            work_date: document.getElementById('craftEditWorkDate').value,
            remark: document.getElementById('craftEditRemark').value.trim(),
        };
        apiFetch(`/api/v1/production-summary/craft/edit/${id}`, {
            method: 'PUT',
            body: JSON.stringify(data),
        }).then(result => {
            if (result.success) {
                notify(result.message, 'success');
                bootstrap.Modal.getInstance(document.getElementById('craftEditModal')).hide();
                loadCraftData();
            }
        }).catch(err => notify(err.message, 'error'));
    }

    window._deleteCraft = function (id) {
        if (!confirm('确认删除该记录？')) return;
        apiFetch(`/api/v1/production-summary/craft/delete/${id}`, { method: 'DELETE' })
            .then(result => {
                if (result.success) { notify(result.message, 'success'); loadCraftData(); }
            }).catch(err => notify(err.message, 'error'));
    };

    function doCraftExport() {
        const start = document.getElementById('craftExportStart').value;
        const end = document.getElementById('craftExportEnd').value;
        let url = '/api/v1/production-summary/craft/export?';
        if (start) url += `start_date=${start}&`;
        if (end) url += `end_date=${end}&`;

        // 直接下载
        window.location.href = url;
        bootstrap.Modal.getInstance(document.getElementById('craftExportModal')).hide();
    }

    // ==================== Tab 2: 包装部 ====================

    const packYear = document.getElementById('packYear');
    const packMonth = document.getElementById('packMonth');
    if (packYear) packYear.value = currentYear;
    if (packMonth) packMonth.value = currentMonth;

    document.getElementById('packSearchBtn').addEventListener('click', loadPackData);
    document.getElementById('packAddSubmit').addEventListener('click', createPackRecord);
    document.getElementById('packEditSubmit').addEventListener('click', savePackEdit);
    document.getElementById('packExportBtn').addEventListener('click', function () {
        window.location.href = '/api/v1/production-summary/packaging/export';
    });

    // 批量导入
    const packUploadZone = document.getElementById('packUploadZone');
    const packUploadFile = document.getElementById('packUploadFile');

    packUploadZone.addEventListener('click', () => packUploadFile.click());
    packUploadZone.addEventListener('dragover', e => { e.preventDefault(); packUploadZone.classList.add('dragover'); });
    packUploadZone.addEventListener('dragleave', () => packUploadZone.classList.remove('dragover'));
    packUploadZone.addEventListener('drop', e => {
        e.preventDefault();
        packUploadZone.classList.remove('dragover');
        if (e.dataTransfer.files.length) handlePackUpload(e.dataTransfer.files[0]);
    });
    packUploadFile.addEventListener('change', function () {
        if (this.files.length) handlePackUpload(this.files[0]);
    });

    function loadPackData() {
        const year = parseInt(packYear.value, 10);
        const month = parseInt(packMonth.value, 10);
        const customer = document.getElementById('packCustomer').value.trim();
        if (!year || !month) return;

        let url = `/api/v1/production-summary/packaging/list?year=${year}&month=${month}`;
        if (customer) url += `&customer=${encodeURIComponent(customer)}`;

        apiFetch(url)
            .then(result => {
                renderPackTable(result.data);
                document.getElementById('packRecordCount').textContent = `共 ${result.total} 条`;
            })
            .catch(err => notify('加载包装部数据失败: ' + err.message, 'error'));
    }

    function renderPackTable(data) {
        const tbody = document.getElementById('packTableBody');
        if (!data || data.length === 0) {
            tbody.innerHTML = '<tr><td colspan="7" class="text-center py-4 text-muted">当月暂无包装记录</td></tr>';
            return;
        }

        tbody.innerHTML = data.map(r => `<tr>
            <td><span class="fw-semibold">${_esc(r.customer)}</span></td>
            <td>${_esc(r.product_name)}</td>
            <td><code>${_esc(r.barcode)}</code></td>
            <td class="text-center fw-bold">${formatNumber(r.quantity)}</td>
            <td>${r.pack_date}</td>
            <td><small class="text-muted">${_esc(r.remark)}</small></td>
            <td>
                <button onclick="window._editPack(${r.id},'${_esc(r.customer)}','${_esc(r.product_name)}','${_esc(r.barcode)}',${r.quantity},'${r.pack_date}','${_esc(r.remark)}')" class="btn btn-sm btn-outline-primary me-1"><i class="fas fa-edit"></i></button>
                <button onclick="window._deletePack(${r.id})" class="btn btn-sm btn-outline-danger"><i class="fas fa-trash"></i></button>
            </td>
        </tr>`).join('');
    }

    function createPackRecord() {
        const data = {
            customer: document.getElementById('packAddCustomer').value.trim(),
            product_name: document.getElementById('packAddProductName').value.trim(),
            barcode: document.getElementById('packAddBarcode').value.trim(),
            quantity: parseInt(document.getElementById('packAddQuantity').value, 10),
            pack_date: document.getElementById('packAddDate').value,
            remark: document.getElementById('packAddRemark').value.trim(),
        };
        if (!data.customer) { notify('请输入客户', 'error'); return; }
        if (!data.product_name) { notify('请输入产品名称', 'error'); return; }
        if (!data.barcode) { notify('请输入69码', 'error'); return; }
        if (!data.quantity || data.quantity <= 0) { notify('数量必须为正数', 'error'); return; }
        if (!data.pack_date) { notify('请选择包装日期', 'error'); return; }

        apiFetch('/api/v1/production-summary/packaging/create', {
            method: 'POST',
            body: JSON.stringify(data),
        }).then(result => {
            if (result.success) {
                notify(result.message, 'success');
                bootstrap.Modal.getInstance(document.getElementById('packAddModal')).hide();
                document.getElementById('packAddForm').reset();
                loadPackData();
            }
        }).catch(err => notify(err.message, 'error'));
    }

    window._editPack = function (id, customer, productName, barcode, quantity, packDate, remark) {
        document.getElementById('packEditId').value = id;
        document.getElementById('packEditCustomer').value = customer;
        document.getElementById('packEditProductName').value = productName;
        document.getElementById('packEditBarcode').value = barcode;
        document.getElementById('packEditQuantity').value = quantity;
        document.getElementById('packEditDate').value = packDate;
        document.getElementById('packEditRemark').value = remark;
        new bootstrap.Modal(document.getElementById('packEditModal')).show();
    };

    function savePackEdit() {
        const id = document.getElementById('packEditId').value;
        const data = {
            customer: document.getElementById('packEditCustomer').value.trim(),
            product_name: document.getElementById('packEditProductName').value.trim(),
            barcode: document.getElementById('packEditBarcode').value.trim(),
            quantity: parseInt(document.getElementById('packEditQuantity').value, 10),
            pack_date: document.getElementById('packEditDate').value,
            remark: document.getElementById('packEditRemark').value.trim(),
        };
        apiFetch(`/api/v1/production-summary/packaging/edit/${id}`, {
            method: 'PUT',
            body: JSON.stringify(data),
        }).then(result => {
            if (result.success) {
                notify(result.message, 'success');
                bootstrap.Modal.getInstance(document.getElementById('packEditModal')).hide();
                loadPackData();
            }
        }).catch(err => notify(err.message, 'error'));
    }

    window._deletePack = function (id) {
        if (!confirm('确认删除该记录？')) return;
        apiFetch(`/api/v1/production-summary/packaging/delete/${id}`, { method: 'DELETE' })
            .then(result => {
                if (result.success) { notify(result.message, 'success'); loadPackData(); }
            }).catch(err => notify(err.message, 'error'));
    };

    function handlePackUpload(file) {
        if (!file.name.endsWith('.xlsx') && !file.name.endsWith('.xls')) {
            notify('仅支持 .xlsx / .xls 格式文件', 'error');
            return;
        }

        document.getElementById('packUploadProgress').style.display = 'block';
        document.getElementById('packPreviewArea').style.display = 'none';

        const formData = new FormData();
        formData.append('file', file);

        fetch('/api/v1/production-summary/packaging/upload', {
            method: 'POST',
            credentials: 'include',
            body: formData,
        })
        .then(r => {
            if (!r.ok) return r.json().then(e => { throw new Error(e.detail || '上传失败'); });
            return r.json();
        })
        .then(result => {
            document.getElementById('packUploadProgress').style.display = 'none';

            if (result.preview && result.preview.length > 0) {
                renderPackPreview(result);
            }

            if (result.created_count > 0) {
                notify(`成功导入 ${result.created_count} 条记录`, 'success');
                loadPackData();
            } else if (result.errors && result.errors.length > 0) {
                notify('导入失败，请检查数据格式', 'error');
            }
        })
        .catch(err => {
            document.getElementById('packUploadProgress').style.display = 'none';
            notify('上传失败: ' + err.message, 'error');
        });
    }

    function renderPackPreview(result) {
        const area = document.getElementById('packPreviewArea');
        area.style.display = 'block';

        document.getElementById('packPreviewStats').textContent =
            `总计 ${result.total} 条 | 有效 ${result.valid_count} 条 | 失败 ${result.error_count} 条`;

        const tbody = document.getElementById('packPreviewTableBody');
        let totalQty = 0;
        tbody.innerHTML = result.preview.map(item => {
            if (item.valid) totalQty += (item.quantity || 0);
            const statusBadge = item.valid
                ? '<span class="badge bg-success">有效</span>'
                : `<span class="badge bg-danger" title="${_esc(item.error)}">无效</span>`;
            return `<tr class="${item.valid ? '' : 'table-danger'}">
                <td>${_esc(item.customer)}</td>
                <td>${_esc(item.product_name)}</td>
                <td><code>${_esc(item.barcode)}</code></td>
                <td class="text-center">${item.quantity}</td>
                <td>${item.pack_date}</td>
                <td>${statusBadge}</td>
            </tr>`;
        }).join('');

        document.getElementById('packPreviewTotal').textContent = formatNumber(totalQty);
    }

    // ==================== Tab 3: 汇总动态报表 ====================

    const summaryYear = document.getElementById('summaryYear');
    const summaryMonth = document.getElementById('summaryMonth');
    if (summaryYear) summaryYear.value = currentYear;
    if (summaryMonth) summaryMonth.value = currentMonth;

    document.getElementById('summarySearchBtn').addEventListener('click', loadSummary);

    function loadSummary() {
        const year = parseInt(summaryYear.value, 10);
        const month = parseInt(summaryMonth.value, 10);
        if (!year || !month) return;

        apiFetch(`/api/v1/production-summary/summary?year=${year}&month=${month}`)
            .then(result => {
                renderSummaryStats(result.monthly_summary);
                renderSummaryTable(result.data);
            })
            .catch(err => notify('加载汇总报表失败: ' + err.message, 'error'));
    }

    function renderSummaryStats(summary) {
        if (!summary) return;
        document.getElementById('summaryStats').style.display = '';

        document.getElementById('sumCaseOut').textContent = formatNumber(summary.case_out_total);
        document.getElementById('sumCraft').textContent = formatNumber(summary.craft_total);
        document.getElementById('sumPack').textContent = formatNumber(summary.pack_total);

        const diffCraft = summary.diff_case_craft;
        const diffCraftEl = document.getElementById('sumDiffCraft');
        diffCraftEl.textContent = (diffCraft > 0 ? '+' : '') + formatNumber(diffCraft);
        diffCraftEl.className = diffCraft !== 0 ? 'text-warning' : 'text-success';

        const diffPack = summary.diff_craft_pack;
        const diffPackEl = document.getElementById('sumDiffPack');
        diffPackEl.textContent = (diffPack > 0 ? '+' : '') + formatNumber(diffPack);
        diffPackEl.className = diffPack !== 0 ? 'text-info' : 'text-success';
    }

    function renderSummaryTable(data) {
        const tbody = document.getElementById('summaryTableBody');
        if (!data || data.length === 0) {
            tbody.innerHTML = '<tr><td colspan="5" class="text-center py-4 text-muted">暂无数据</td></tr>';
            return;
        }

        // 只显示有数据的日期
        const activeDays = data.filter(d => d.case_out_total > 0 || d.craft_total > 0 || d.pack_total > 0);

        if (activeDays.length === 0) {
            tbody.innerHTML = '<tr><td colspan="5" class="text-center py-4 text-muted">当月暂无生产数据</td></tr>';
            return;
        }

        tbody.innerHTML = activeDays.map(d => {
            const productRows = (d.products || []).map(p => {
                // 流转链路: 客户-产品 -> 皮套出库 -> 手工部生产 -> 包装部进仓
                return `<div class="flow-chain mb-1">
                    <span class="fw-semibold">${_esc(p.customer)} ${_esc(p.product_name)}</span>
                    <span class="flow-arrow"><i class="fas fa-arrow-right"></i></span>
                    <span class="flow-item flow-case-out">出库 ${p.case_out_qty}</span>
                    <span class="flow-arrow"><i class="fas fa-arrow-right"></i></span>
                    <span class="flow-item flow-craft">手工 ${d.craft_total}</span>
                    <span class="flow-arrow"><i class="fas fa-arrow-right"></i></span>
                    <span class="flow-item flow-pack">包装 ${p.pack_qty}</span>
                </div>`;
            }).join('');

            return `<tr>
                <td class="fw-semibold">${d.date}</td>
                <td class="text-center">${formatNumber(d.case_out_total)}</td>
                <td class="text-center">${formatNumber(d.craft_total)}</td>
                <td class="text-center">${formatNumber(d.pack_total)}</td>
                <td>${productRows || '<small class="text-muted">-</small>'}</td>
            </tr>`;
        }).join('');
    }

    // ==================== 工具 ====================

    function _esc(str) {
        if (!str) return '';
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML.replace(/'/g, '&#39;');
    }

})();
