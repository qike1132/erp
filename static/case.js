"use strict";

// ==================== 全局变量 ====================
let stagedStockins = [];
let stagedStockouts = [];
let inventoryData = [];
let currentCaseId = null;
let currentLogPage = 1;
let expandedCaseId = null;
let stockinCurrentPage = 1;
let stockoutCurrentPage = 1;
let stockinFilters = {};
let stockoutFilters = {};
let stockoutCurrentProductStock = 0;

// ==================== 入库/出库模块配置 ====================
// 通过配置对象驱动通用函数，消除两套几乎相同的代码
const stockinCfg = {
    type: 'stockin', label: '入库',
    // 状态访问器
    getStaged: () => stagedStockins, setStaged: v => stagedStockins = v,
    getPage: () => stockinCurrentPage, setPage: v => stockinCurrentPage = v,
    getFilters: () => stockinFilters, setFilters: v => stockinFilters = v,
    // API
    listApi: '/api/v1/cases/in/list', detailApi: '/api/v1/cases/in/',
    submitApi: '/api/v1/cases/in/batch', submitKey: 'stockins', listKey: 'stockins',
    // 行为
    requiresCustomer: true, lazyLoad: false,
    // 元素 ID 映射
    el: {
        search: 'stockin_product_search', datalist: 'stockin_product_list',
        productId: 'stockin_product_id', customer: 'stockin_customer',
        date: 'stockin_date', quantity: 'stockin_quantity', note: 'stockin_note',
        addBtn: 'addStockinBtn', stagedList: 'stagedStockinsList',
        countBadge: 'stagedCountBadge', totalCount: 'stockinTotalCount',
        submitBtn: 'submitAllStockinsBtn', submitBtnText: 'submitStockinBtnText',
        submitBtnSpinner: 'submitStockinBtnSpinner',
        searchForm: 'stockinSearchForm', searchCustomer: 'searchStockinCustomer',
        searchStartDate: 'searchStockinStartDate', searchEndDate: 'searchStockinEndDate',
        listTable: 'stockinListTable', pagination: 'stockinPagination',
        editModal: 'editStockinModal', editId: 'editStockinId',
        editCustomer: 'editStockinCustomer', editDate: 'editStockinDate',
        editProductName: 'editStockinProductName', editQuantity: 'editStockinQuantity',
        editNote: 'editStockinNote', saveEditBtn: 'saveEditStockinBtn',
    },
    // 表单 -> 暂存对象
    buildStagedItem() {
        return {
            productId: document.getElementById(this.el.productId).value,
            productName: document.getElementById(this.el.search).value,
            customer: document.getElementById(this.el.customer).value,
            date: document.getElementById(this.el.date).value,
            quantity: parseInt(document.getElementById(this.el.quantity).value) || 1,
            note: document.getElementById(this.el.note).value,
            id: Date.now()
        };
    },
    // 暂存对象 -> 提交载荷
    buildSubmitItem(s) {
        return { productId: s.productId, customer: s.customer, quantity: s.quantity, stockinDate: s.date, note: s.note };
    },
    // 编辑弹窗 -> 保存载荷
    buildEditPayload() {
        return {
            customer: document.getElementById(this.el.editCustomer).value,
            stockin_date: document.getElementById(this.el.editDate).value,
            quantity: parseInt(document.getElementById(this.el.editQuantity).value),
            note: document.getElementById(this.el.editNote).value
        };
    },
    // 搜索选中回调
    onSearchSelect(option) {
        document.getElementById(this.el.productId).value = option.getAttribute('data-id');
    },
    // 添加按钮校验（stockin 仅检查必填）
    validateAdd() { return true; },
    // 添加后/清空后钩子
    postAdd() {}, postClear() {},
    // 暂存卡片渲染
    renderStagedCard(item, index) {
        return `<div class="card mb-2" style="border: 2px solid var(--plush-blue-light);">
            <div class="card-body py-2"><div class="d-flex justify-content-between align-items-start"><div>
                <h6 class="mb-1"><i class="fas fa-cubes text-primary me-1"></i>${escapeHtml(item.productName)}</h6>
                <p class="mb-1 text-muted small"><i class="fas fa-user me-1"></i>${escapeHtml(item.customer)}</p>
                <p class="mb-0 small">
                    <span class="badge bg-info me-1">数量: ${item.quantity}</span>
                    <span class="badge bg-secondary">${escapeHtml(item.date)}</span>
                </p>
            </div><button class="btn btn-sm btn-outline-danger" onclick="deleteStagedStockin(${index})"><i class="fas fa-trash"></i></button></div></div></div>`;
    },
    // 列表行渲染
    renderRow(item) {
        return `<tr>
            <td>${escapeHtml(item.stockin_date)}</td>
            <td>${escapeHtml(item.customer || '-')}</td>
            <td>${escapeHtml(item.case_name)}</td>
            <td><small>${escapeHtml(item.case_barcode || '-')}</small></td>
            <td><strong>${item.quantity}</strong></td>
            <td><small>${escapeHtml(item.note || '-')}</small></td>
            <td>
                <button class="btn btn-sm btn-outline-warning me-1" onclick="openEditStockinModal(${item.id})"><i class="fas fa-edit"></i></button>
                <button class="btn btn-sm btn-outline-danger" onclick="deleteStockin(${item.id})"><i class="fas fa-trash"></i></button>
            </td></tr>`;
    },
    // 文案与图标
    tableHeaders: '<tr><th>入库日期</th><th>客户</th><th>产品名称</th><th>69码</th><th>数量</th><th>备注</th><th>操作</th></tr>',
    emptyIcon: 'fas fa-box-open', listEmptyText: '暂无入库记录',
    stagedEmptyText: '暂无暂存入库', confirmDeleteStaged: '确定要删除这个暂存入库吗？',
    confirmDelete: '确定要删除这条入库记录吗？', submitLabel: '提交入库',
    // 批量导入配置
    batch: {
        importApi: '/api/v1/batch/import-case-stockins',
        templateName: '皮套入库模板.xlsx',
        prefix: 'stockin',
    },
};

const stockoutCfg = {
    type: 'stockout', label: '出库',
    getStaged: () => stagedStockouts, setStaged: v => stagedStockouts = v,
    getPage: () => stockoutCurrentPage, setPage: v => stockoutCurrentPage = v,
    getFilters: () => stockoutFilters, setFilters: v => stockoutFilters = v,
    listApi: '/api/v1/cases/out/list', detailApi: '/api/v1/cases/out/',
    submitApi: '/api/v1/cases/out/batch', submitKey: 'stockouts', listKey: 'stockouts',
    requiresCustomer: false, lazyLoad: true,
    el: {
        search: 'stockout_product_search', datalist: 'stockout_product_list',
        productId: 'stockout_product_id', customer: 'stockout_customer',
        date: 'stockout_date', quantity: 'stockout_quantity', note: 'stockout_note',
        addBtn: 'addStockoutBtn', stagedList: 'stagedStockoutsList',
        countBadge: 'stockoutStagedCountBadge', totalCount: 'stockoutTotalCount',
        submitBtn: 'submitAllStockoutsBtn', submitBtnText: 'submitStockoutBtnText',
        submitBtnSpinner: 'submitStockoutBtnSpinner',
        searchForm: 'stockoutSearchForm', searchCustomer: 'searchStockoutCustomer',
        searchStartDate: 'searchStockoutStartDate', searchEndDate: 'searchStockoutEndDate',
        listTable: 'stockoutListTable', pagination: 'stockoutPagination',
        editModal: 'editStockoutModal', editId: 'editStockoutId',
        editCustomer: 'editStockoutCustomer', editDate: 'editStockoutDate',
        editProductName: 'editStockoutProductName', editQuantity: 'editStockoutQuantity',
        editNote: 'editStockoutNote', saveEditBtn: 'saveEditStockoutBtn',
    },
    buildStagedItem() {
        const quantity = parseInt(document.getElementById(this.el.quantity).value) || 1;
        if (quantity > stockoutCurrentProductStock) {
            GlobalNotification.error(`库存不足，当前库存: ${stockoutCurrentProductStock}`);
            return null;
        }
        return {
            productId: document.getElementById(this.el.productId).value,
            productName: document.getElementById(this.el.search).value,
            customer: document.getElementById(this.el.customer).value,
            date: document.getElementById(this.el.date).value,
            quantity, note: document.getElementById(this.el.note).value, id: Date.now()
        };
    },
    buildSubmitItem(s) {
        return { productId: s.productId, customer: s.customer, quantity: s.quantity, stockout_date: s.date, note: s.note };
    },
    buildEditPayload() {
        return {
            customer: document.getElementById(this.el.editCustomer).value,
            stockout_date: document.getElementById(this.el.editDate).value,
            quantity: parseInt(document.getElementById(this.el.editQuantity).value),
            note: document.getElementById(this.el.editNote).value
        };
    },
    onSearchSelect(option) {
        document.getElementById(this.el.productId).value = option.getAttribute('data-id');
        stockoutCurrentProductStock = parseInt(option.getAttribute('data-stock')) || 0;
        document.getElementById('stockoutCurrentStock').textContent = `当前库存: ${stockoutCurrentProductStock}`;
    },
    validateAdd() {
        const qty = parseInt(document.getElementById(this.el.quantity).value) || 0;
        return qty <= stockoutCurrentProductStock;
    },
    postAdd() {
        const qty = parseInt(document.getElementById(this.el.quantity).value) || 1;
        stockoutCurrentProductStock -= qty;
        document.getElementById('stockoutCurrentStock').textContent = `当前库存: ${stockoutCurrentProductStock}`;
    },
    postClear() {
        document.getElementById('stockoutCurrentStock').textContent = '当前库存: -';
        stockoutCurrentProductStock = 0;
    },
    renderStagedCard(item, index) {
        return `<div class="card mb-2" style="border: 2px solid #f8d7da;">
            <div class="card-body py-2"><div class="d-flex justify-content-between align-items-start"><div>
                <h6 class="mb-1"><i class="fas fa-cubes text-danger me-1"></i>${escapeHtml(item.productName)}</h6>
                <p class="mb-1 text-muted small"><i class="fas fa-user me-1"></i>${escapeHtml(item.customer || '无客户')}</p>
                <p class="mb-0 small">
                    <span class="badge bg-danger me-1">数量: ${item.quantity}</span>
                    <span class="badge bg-secondary">${escapeHtml(item.date)}</span>
                </p>
            </div><button class="btn btn-sm btn-outline-danger" onclick="deleteStagedStockout(${index})"><i class="fas fa-trash"></i></button></div></div></div>`;
    },
    renderRow(item) {
        return `<tr>
            <td>${escapeHtml(item.stockout_date)}</td>
            <td>${escapeHtml(item.customer || '-')}</td>
            <td>${escapeHtml(item.case_name)}</td>
            <td><small>${escapeHtml(item.case_barcode || '-')}</small></td>
            <td><strong class="text-danger">${item.quantity}</strong></td>
            <td><small>${escapeHtml(item.note || '-')}</small></td>
            <td>
                <button class="btn btn-sm btn-outline-warning me-1" onclick="openEditStockoutModal(${item.id})"><i class="fas fa-edit"></i></button>
                <button class="btn btn-sm btn-outline-danger" onclick="deleteStockout(${item.id})"><i class="fas fa-trash"></i></button>
            </td></tr>`;
    },
    tableHeaders: '<tr><th>出库日期</th><th>客户</th><th>产品名称</th><th>69码</th><th>数量</th><th>备注</th><th>操作</th></tr>',
    emptyIcon: 'fas fa-shipping-fast', listEmptyText: '暂无出库记录',
    stagedEmptyText: '暂无暂存出库', confirmDeleteStaged: '确定要删除这个暂存出库吗？',
    confirmDelete: '确定要删除这条出库记录吗？', submitLabel: '提交出库',
    // 批量导入配置
    batch: {
        importApi: '/api/v1/batch/import-case-stockouts',
        templateName: '皮套出库模板.xlsx',
        prefix: 'stockout',
    },
};

// ==================== 通用入库/出库函数 ====================

function initHandlers(cfg) {
    const searchInput = document.getElementById(cfg.el.search);
    let searchTimeout;
    let requestId = 0;
    const searchCache = new Map();
    const MAX_CACHE_SIZE = 50;

    // 产品搜索（带防抖、并发控制、缓存）
    searchInput.addEventListener('input', function(e) {
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(async () => {
            const query = e.target.value.trim();
            if (query.length >= 1) {
                if (searchCache.has(query)) {
                    displaySearchResults(cfg, searchCache.get(query));
                    return;
                }
                const currentRequestId = ++requestId;
                try {
                    const res = await fetch(`/api/v1/cases/search?q=${encodeURIComponent(query)}`);
                    if (currentRequestId !== requestId) return;
                    const data = await res.json();
                    if (currentRequestId !== requestId) return;
                    if (searchCache.size >= MAX_CACHE_SIZE) {
                        searchCache.delete(searchCache.keys().next().value);
                    }
                    searchCache.set(query, data);
                    displaySearchResults(cfg, data);
                } catch (error) {
                    if (currentRequestId === requestId) {
                        GlobalNotification.error('搜索产品失败，请稍后重试');
                    }
                }
            }
        }, 300);
        updateAddBtn(cfg);
    });

    // 选中搜索结果
    searchInput.addEventListener('change', function() {
        const datalist = document.getElementById(cfg.el.datalist);
        const selected = Array.from(datalist.options).find(opt => opt.value === this.value);
        if (selected) cfg.onSearchSelect(selected);
        updateAddBtn(cfg);
    });

    // 表单字段变更 → 更新添加按钮状态
    [cfg.el.customer, cfg.el.quantity, cfg.el.date].forEach(id => {
        document.getElementById(id).addEventListener('change', () => updateAddBtn(cfg));
        document.getElementById(id).addEventListener('input', () => updateAddBtn(cfg));
    });

    // 按钮事件
    document.getElementById(cfg.el.addBtn).addEventListener('click', () => addStaged(cfg));
    document.getElementById(cfg.el.submitBtn).addEventListener('click', () => submitAll(cfg));
    document.getElementById(cfg.el.saveEditBtn).addEventListener('click', () => saveEdit(cfg));

    // 搜索表单
    document.getElementById(cfg.el.searchForm).addEventListener('submit', function(e) {
        e.preventDefault();
        cfg.setFilters({
            customer: document.getElementById(cfg.el.searchCustomer).value,
            start_date: document.getElementById(cfg.el.searchStartDate).value,
            end_date: document.getElementById(cfg.el.searchEndDate).value
        });
        cfg.setPage(1);
        loadList(cfg);
    });

    // 标签页切换时延迟加载（出库）
    if (cfg.lazyLoad) {
        document.getElementById(cfg.type + '-tab').addEventListener('shown.bs.tab', function() {
            if (document.getElementById(cfg.el.listTable).children.length <= 1) loadList(cfg);
        });
    }
}

function displaySearchResults(cfg, data) {
    const datalist = document.getElementById(cfg.el.datalist);
    datalist.innerHTML = '';
    data.forEach(product => {
        const option = document.createElement('option');
        option.value = product.name;
        option.setAttribute('data-id', product.id);
        if (product.current_stock !== undefined) {
            option.setAttribute('data-stock', product.current_stock);
        }
        datalist.appendChild(option);
    });
}

// ==================== 输入验证器 ====================
const InputValidator = {
    quantity(value, options = {}) {
        const num = parseInt(value);
        const { min = 1, max = Infinity } = options;
        if (!value || isNaN(num)) return { valid: false, message: '数量不能为空' };
        if (num < min) return { valid: false, message: `数量不能小于${min}` };
        if (num > max) return { valid: false, message: `数量不能大于${max}` };
        return { valid: true, message: '' };
    },
    date(value, options = {}) {
        if (!value) {
            return options.required
                ? { valid: false, message: '日期不能为空' }
                : { valid: true, message: '' };
        }
        const dateObj = new Date(value);
        if (isNaN(dateObj.getTime())) return { valid: false, message: '日期格式不合法' };
        return { valid: true, message: '' };
    }
};

function updateAddBtn(cfg) {
    const customer = cfg.requiresCustomer ? document.getElementById(cfg.el.customer).value : true;
    const productId = document.getElementById(cfg.el.productId).value;
    const quantityVal = document.getElementById(cfg.el.quantity).value;
    const dateVal = document.getElementById(cfg.el.date).value;
    const addBtn = document.getElementById(cfg.el.addBtn);

    const qtyResult = InputValidator.quantity(quantityVal, {
        min: 1,
        max: cfg.type === 'stockout' ? stockoutCurrentProductStock : Infinity
    });
    const dateResult = InputValidator.date(dateVal, { required: true });

    const allValid = customer && productId && qtyResult.valid && dateResult.valid && cfg.validateAdd();

    if (allValid) {
        addBtn.disabled = false;
        addBtn.classList.add('btn-primary');
        addBtn.classList.remove('btn-secondary');
    } else {
        addBtn.disabled = true;
        addBtn.classList.remove('btn-primary');
        addBtn.classList.add('btn-secondary');
    }
}

function addStaged(cfg) {
    const item = cfg.buildStagedItem();
    if (!item) return;
    cfg.getStaged().push(item);
    cfg.postAdd();
    updateStagedList(cfg);
    clearForm(cfg);
}

function updateStagedList(cfg) {
    const container = document.getElementById(cfg.el.stagedList);
    const countBadge = document.getElementById(cfg.el.countBadge);
    const totalCount = document.getElementById(cfg.el.totalCount);
    const submitBtn = document.getElementById(cfg.el.submitBtn);
    const staged = cfg.getStaged();

    if (staged.length === 0) {
        container.innerHTML = `
            <div class="text-center text-muted py-4">
                <i class="${cfg.emptyIcon} fa-3x mb-3" style="opacity: 0.3;"></i>
                <p>${cfg.stagedEmptyText}</p>
            </div>`;
        countBadge.style.display = 'none';
        totalCount.textContent = '共 0 个';
        submitBtn.disabled = true;
    } else {
        countBadge.style.display = 'inline-block';
        countBadge.textContent = `已暂存: ${staged.length}`;
        totalCount.textContent = `共 ${staged.length} 个`;
        submitBtn.disabled = false;
        container.innerHTML = staged.map((item, i) => cfg.renderStagedCard(item, i)).join('');
    }
}

function deleteStaged(cfg, index) {
    if (confirm(cfg.confirmDeleteStaged)) {
        cfg.getStaged().splice(index, 1);
        updateStagedList(cfg);
    }
}

function clearForm(cfg) {
    document.getElementById(cfg.el.customer).value = '';
    document.getElementById(cfg.el.search).value = '';
    document.getElementById(cfg.el.productId).value = '';
    document.getElementById(cfg.el.quantity).value = '1';
    document.getElementById(cfg.el.note).value = '';
    document.getElementById(cfg.el.date).value = new Date().toISOString().split('T')[0];
    cfg.postClear();
    updateAddBtn(cfg);
}

async function submitAll(cfg) {
    if (cfg.getStaged().length === 0) return;

    const btn = document.getElementById(cfg.el.submitBtn);
    const btnText = document.getElementById(cfg.el.submitBtnText);
    const btnSpinner = document.getElementById(cfg.el.submitBtnSpinner);

    btn.disabled = true;
    btnText.textContent = '提交中...';
    btnSpinner.style.display = 'inline-block';

    try {
        const response = await fetch(cfg.submitApi, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                [cfg.submitKey]: cfg.getStaged().map(cfg.buildSubmitItem)
            })
        });
        const result = await response.json();
        if (result.success) {
            GlobalNotification.success(cfg.submitLabel + '成功');
            cfg.setStaged([]);
            updateStagedList(cfg);
            loadList(cfg);
        } else {
            GlobalNotification.error(result.message || result.error || '提交失败');
        }
    } catch (error) {
        GlobalNotification.error('提交失败: ' + error.message);
    } finally {
        btn.disabled = false;
        btnText.textContent = cfg.submitLabel;
        btnSpinner.style.display = 'none';
    }
}

async function loadList(cfg, page) {
    page = page || cfg.getPage();
    cfg.setPage(page);
    const container = document.getElementById(cfg.el.listTable);
    container.innerHTML = '<div class="text-center text-muted py-4"><i class="fas fa-spinner fa-spin fa-2x mb-3"></i><p>加载中...</p></div>';

    const params = new URLSearchParams({ page, per_page: 10, ...cfg.getFilters() });

    try {
        const response = await fetch(`${cfg.listApi}?${params}`);
        const data = await response.json();
        const items = data[cfg.listKey];

        if (items && items.length > 0) {
            container.innerHTML = `
                <table class="table table-striped table-hover">
                    <thead>${cfg.tableHeaders}</thead>
                    <tbody>${items.map(cfg.renderRow).join('')}</tbody>
                </table>`;
            renderPagination(cfg, data.current_page, data.pages);
        } else {
            container.innerHTML = `
                <div class="text-center text-muted py-4">
                    <i class="${cfg.emptyIcon} fa-3x mb-3" style="opacity: 0.3;"></i>
                    <p>${cfg.listEmptyText}</p>
                </div>`;
        }
    } catch (error) {
        container.innerHTML = `<div class="alert alert-danger">加载失败: ${escapeHtml(error.message)}</div>`;
    }
}

function renderPagination(cfg, current, total) {
    const pagination = document.querySelector(`#${cfg.el.pagination} ul`);
    if (!pagination || total <= 1) { if (pagination) pagination.innerHTML = ''; return; }

    const fnName = cfg === stockinCfg ? 'loadStockinList' : 'loadStockoutList';
    let html = `<li class="page-item ${current === 1 ? 'disabled' : ''}">
        <a class="page-link" href="#" onclick="${fnName}(${current - 1}); return false;">上一页</a></li>`;
    for (let i = 1; i <= total; i++) {
        if (i === 1 || i === total || (i >= current - 2 && i <= current + 2)) {
            html += `<li class="page-item ${i === current ? 'active' : ''}">
                <a class="page-link" href="#" onclick="${fnName}(${i}); return false;">${i}</a></li>`;
        }
    }
    html += `<li class="page-item ${current === total ? 'disabled' : ''}">
        <a class="page-link" href="#" onclick="${fnName}(${current + 1}); return false;">下一页</a></li>`;
    pagination.innerHTML = html;
}

async function openEditModal(cfg, id) {
    try {
        const response = await fetch(`${cfg.detailApi}${id}`);
        const data = await response.json();
        document.getElementById(cfg.el.editId).value = id;
        document.getElementById(cfg.el.editCustomer).value = data.customer || '';
        document.getElementById(cfg.el.editDate).value = data.stockin_date || data.stockout_date;
        document.getElementById(cfg.el.editProductName).value = data.case_name;
        document.getElementById(cfg.el.editQuantity).value = data.quantity;
        document.getElementById(cfg.el.editNote).value = data.note || '';
        new bootstrap.Modal(document.getElementById(cfg.el.editModal)).show();
    } catch (error) {
        GlobalNotification.error('获取数据失败');
    }
}

async function saveEdit(cfg) {
    const id = document.getElementById(cfg.el.editId).value;
    try {
        const response = await fetch(`${cfg.detailApi}${id}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(cfg.buildEditPayload())
        });
        const result = await response.json();
        if (result.success) {
            GlobalNotification.success('更新成功');
            bootstrap.Modal.getInstance(document.getElementById(cfg.el.editModal)).hide();
            loadList(cfg);
        } else {
            GlobalNotification.error(result.message);
        }
    } catch (error) {
        GlobalNotification.error('更新失败');
    }
}

async function deleteRecord(cfg, id) {
    if (!confirm(cfg.confirmDelete)) return;
    try {
        const response = await fetch(`${cfg.detailApi}${id}`, { method: 'DELETE' });
        const result = await response.json();
        if (result.success) {
            GlobalNotification.success('删除成功');
            loadList(cfg);
        } else {
            GlobalNotification.error(result.message);
        }
    } catch (error) {
        GlobalNotification.error('删除失败');
    }
}

// ==================== HTML onclick 兼容的薄封装函数 ====================
function addStagedStockin() { addStaged(stockinCfg); }
function addStagedStockout() { addStaged(stockoutCfg); }
function deleteStagedStockin(i) { deleteStaged(stockinCfg, i); }
function deleteStagedStockout(i) { deleteStaged(stockoutCfg, i); }
function clearStockinForm() { clearForm(stockinCfg); }
function clearStockoutForm() { clearForm(stockoutCfg); }
function updateStockinAddBtn() { updateAddBtn(stockinCfg); }
function updateStockoutAddBtn() { updateAddBtn(stockoutCfg); }
function submitAllStockins() { submitAll(stockinCfg); }
function submitAllStockouts() { submitAll(stockoutCfg); }
function loadStockinList(page) { loadList(stockinCfg, page); }
function loadStockoutList(page) { loadList(stockoutCfg, page); }
function openEditStockinModal(id) { openEditModal(stockinCfg, id); }
function openEditStockoutModal(id) { openEditModal(stockoutCfg, id); }
function saveEditStockin() { saveEdit(stockinCfg); }
function saveEditStockout() { saveEdit(stockoutCfg); }
function deleteStockin(id) { deleteRecord(stockinCfg, id); }
function deleteStockout(id) { deleteRecord(stockoutCfg, id); }

// ==================== 初始化 ====================
document.addEventListener('DOMContentLoaded', function() {
    document.getElementById(stockinCfg.el.date).value = new Date().toISOString().split('T')[0];
    document.getElementById(stockoutCfg.el.date).value = new Date().toISOString().split('T')[0];

    initHandlers(stockinCfg);
    initHandlers(stockoutCfg);
    initBatchUpload(stockinCfg);
    initBatchUpload(stockoutCfg);
    initInventoryHandlers();
    loadList(stockinCfg);
});

// ==================== 库存查询 ====================
function initInventoryHandlers() {
    document.getElementById('refreshInventoryBtn').addEventListener('click', loadInventorySummary);

    document.getElementById('inventorySearchKeyword').addEventListener('input', function(e) {
        const keyword = e.target.value.toLowerCase().trim();
        const filtered = inventoryData.filter(item =>
            item.name.toLowerCase().includes(keyword) ||
            (item.barcode && item.barcode.toLowerCase().includes(keyword))
        );
        renderInventoryTable(filtered);
    });

    document.getElementById('logFilterForm').addEventListener('submit', function(e) {
        e.preventDefault();
        currentLogPage = 1;
        if (expandedCaseId) loadInventoryLogs(expandedCaseId);
    });

    document.getElementById('clearFilterBtn').addEventListener('click', function() {
        document.getElementById('filterLogType').value = '';
        document.getElementById('filterStartDate').value = '';
        document.getElementById('filterEndDate').value = '';
        currentLogPage = 1;
        if (expandedCaseId) loadInventoryLogs(expandedCaseId);
    });

    document.getElementById('inventory-tab').addEventListener('shown.bs.tab', function() {
        if (inventoryData.length === 0) loadInventorySummary();
    });
}

async function loadInventorySummary() {
    const container = document.getElementById('inventoryTable');
    container.innerHTML = '<div class="text-center text-muted py-4"><i class="fas fa-spinner fa-spin fa-2x mb-3"></i><p>加载中...</p></div>';

    try {
        const response = await fetch('/api/v1/cases/inventory-summary');
        inventoryData = await response.json();
        renderInventoryTable(inventoryData);
    } catch (error) {
        container.innerHTML = `<div class="alert alert-danger">加载失败: ${escapeHtml(error.message)}</div>`;
    }
}

function renderInventoryTable(data) {
    const container = document.getElementById('inventoryTable');

    if (!data || data.length === 0) {
        container.innerHTML = `
            <div class="text-center text-muted py-4">
                <i class="fas fa-box-open fa-3x mb-3" style="opacity: 0.3;"></i>
                <p>暂无库存数据</p>
            </div>`;
        return;
    }

    const totalStock = data.reduce((sum, item) => sum + item.current_stock, 0);
    const totalIn = data.reduce((sum, item) => sum + item.total_in, 0);
    const totalOut = data.reduce((sum, item) => sum + item.total_out, 0);

    container.innerHTML = `
        <div class="row mb-3">
            <div class="col-md-4">
                <div class="card bg-success bg-opacity-10 border-success">
                    <div class="card-body py-2 text-center">
                        <h5 class="mb-0 text-success">${totalStock}</h5>
                        <small class="text-muted">当前总库存</small>
                    </div>
                </div>
            </div>
            <div class="col-md-4">
                <div class="card bg-primary bg-opacity-10 border-primary">
                    <div class="card-body py-2 text-center">
                        <h5 class="mb-0 text-primary">${totalIn}</h5>
                        <small class="text-muted">累计入库</small>
                    </div>
                </div>
            </div>
            <div class="col-md-4">
                <div class="card bg-danger bg-opacity-10 border-danger">
                    <div class="card-body py-2 text-center">
                        <h5 class="mb-0 text-danger">${totalOut}</h5>
                        <small class="text-muted">累计出库</small>
                    </div>
                </div>
            </div>
        </div>

        <table class="table table-striped table-hover">
            <thead>
                <tr>
                    <th>产品名称</th>
                    <th>69码</th>
                    <th>初始库存</th>
                    <th>累计入库</th>
                    <th>累计出库</th>
                    <th>当前库存</th>
                    <th>操作</th>
                </tr>
            </thead>
            <tbody>
                ${data.map(item => `
                    <tr style="cursor: pointer;" onclick="selectCaseForLog(${item.id}, '${escapeHtml(item.name.replace(/'/g, "\\'"))}')">
                        <td><strong>${escapeHtml(item.name)}</strong></td>
                        <td><small>${escapeHtml(item.barcode || '-')}</small></td>
                        <td>${item.initial_stock}</td>
                        <td><span class="text-success">${item.total_in}</span></td>
                        <td><span class="text-danger">${item.total_out}</span></td>
                        <td><strong class="${item.current_stock < 0 ? 'text-danger' : 'text-primary'}">${item.current_stock}</strong></td>
                        <td>
                            <button class="btn btn-sm btn-outline-info" onclick="event.stopPropagation(); viewLogs(${item.id}, '${escapeHtml(item.name.replace(/'/g, "\\'"))}')">
                                <i class="fas fa-history me-1"></i>流水
                            </button>
                        </td>
                    </tr>
                    <tr id="log-container-${item.id}" style="display: none;">
                        <td colspan="7" style="padding: 0;">
                            <div id="log-panel-${item.id}" class="collapse" style="border-top: 1px solid #dee2e6;">
                                <div class="p-3 bg-light">
                                    <div class="d-flex justify-content-between align-items-center mb-2">
                                        <h6 class="mb-0"><i class="fas fa-history me-2"></i>库存流水记录 - ${escapeHtml(item.name)}</h6>
                                    </div>
                                    <div id="log-table-${item.id}">
                                        <div class="text-center text-muted py-3">
                                            <i class="fas fa-spinner fa-spin fa-2x mb-2"></i>
                                            <p>加载中...</p>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </td>
                    </tr>
                `).join('')}
            </tbody>
        </table>`;
}

function selectCaseForLog(caseId, caseName) {
    currentCaseId = caseId;
    document.getElementById('filterCaseId').value = caseId;
    document.getElementById('selectedCaseName').textContent = `- ${caseName}`;
    currentLogPage = 1;
    loadInventoryLogs(caseId);
}

function viewLogs(caseId, caseName) {
    const logContainer = document.getElementById(`log-container-${caseId}`);
    const logPanel = document.getElementById(`log-panel-${caseId}`);

    if (expandedCaseId === caseId) {
        expandedCaseId = null;
        logPanel.classList.remove('show');
        setTimeout(() => { logContainer.style.display = 'none'; }, 350);
    } else {
        if (expandedCaseId) {
            const prevContainer = document.getElementById(`log-container-${expandedCaseId}`);
            const prevPanel = document.getElementById(`log-panel-${expandedCaseId}`);
            prevPanel.classList.remove('show');
            setTimeout(() => { prevContainer.style.display = 'none'; }, 350);
        }

        expandedCaseId = caseId;
        currentCaseId = caseId;
        document.getElementById('filterCaseId').value = caseId;
        document.getElementById('selectedCaseName').textContent = `- ${caseName}`;
        currentLogPage = 1;

        logContainer.style.display = 'table-row';

        if (!logContainer.dataset.loaded) {
            logContainer.dataset.loaded = 'true';
            loadInventoryLogs(caseId);
        }

        setTimeout(() => { logPanel.classList.add('show'); }, 50);
    }
}

async function loadInventoryLogs(caseId, page) {
    page = page || 1;
    const container = document.getElementById(`log-table-${caseId}`);
    if (!container) return;

    container.innerHTML = '<div class="text-center text-muted py-3"><i class="fas fa-spinner fa-spin fa-2x mb-2"></i><p>加载中...</p></div>';

    const logType = document.getElementById('filterLogType').value;
    const startDate = document.getElementById('filterStartDate').value;
    const endDate = document.getElementById('filterEndDate').value;

    const params = new URLSearchParams({ page, per_page: 10 });
    if (logType) params.append('type', logType);
    if (startDate) params.append('start_date', startDate);
    if (endDate) params.append('end_date', endDate);

    try {
        const response = await fetch(`/api/v1/cases/inventory-logs/${caseId}?${params}`);
        const data = await response.json();

        if (data.success && data.logs && data.logs.length > 0) {
            container.innerHTML = `
                <table class="table table-sm table-striped">
                    <thead><tr>
                        <th>操作类型</th><th>变化数量</th><th>客户</th><th>时间</th>
                    </tr></thead>
                    <tbody>
                        ${data.logs.map(log => `
                            <tr>
                                <td><span class="badge ${getLogTypeBadgeClass(log.change_type)}">${escapeHtml(log.change_type)}</span></td>
                                <td><strong class="${log.change_quantity >= 0 ? 'text-success' : 'text-danger'}">${log.change_quantity >= 0 ? '+' : ''}${log.change_quantity}</strong></td>
                                <td>${escapeHtml(log.customer || '-')}</td>
                                <td><small>${escapeHtml(log.change_date)}</small></td>
                            </tr>
                        `).join('')}
                    </tbody>
                </table>`;

            if (data.pagination && data.pagination.pages > 1) {
                container.innerHTML += `
                    <nav class="mt-2"><ul class="pagination pagination-sm justify-content-center">
                        <li class="page-item ${data.pagination.page === 1 ? 'disabled' : ''}">
                            <a class="page-link" href="#" onclick="loadInventoryLogs(${caseId}, ${data.pagination.page - 1}); return false;">上一页</a>
                        </li>
                        ${Array.from({length: data.pagination.pages}, (_, i) => i + 1).map(p => `
                            <li class="page-item ${p === data.pagination.page ? 'active' : ''}">
                                <a class="page-link" href="#" onclick="loadInventoryLogs(${caseId}, ${p}); return false;">${p}</a>
                            </li>
                        `).join('')}
                        <li class="page-item ${data.pagination.page === data.pagination.pages ? 'disabled' : ''}">
                            <a class="page-link" href="#" onclick="loadInventoryLogs(${caseId}, ${data.pagination.page + 1}); return false;">下一页</a>
                        </li>
                    </ul></nav>`;
            }
        } else {
            container.innerHTML = `
                <div class="text-center text-muted py-3">
                    <i class="fas fa-history fa-2x mb-2" style="opacity: 0.3;"></i>
                    <p>暂无流水记录</p>
                </div>`;
        }
    } catch (error) {
        container.innerHTML = `<div class="alert alert-danger mb-0">加载失败: ${escapeHtml(error.message)}</div>`;
    }
}

function getLogTypeBadgeClass(type) {
    const classes = {
        '入库': 'bg-success', '出库': 'bg-danger',
        '入库调整': 'bg-warning text-dark', '出库调整': 'bg-warning text-dark',
        '删除入库': 'bg-secondary', '删除出库': 'bg-secondary'
    };
    return classes[type] || 'bg-info';
}

// ==================== 皮套批量导入（通用） ====================
function initBatchUpload(cfg) {
    const p = cfg.batch.prefix;
    const uploadArea = document.getElementById(`${p}-excel-upload-area`);
    const fileInput = document.getElementById(`${p}-excel-input`);
    const downloadBtn = document.getElementById(`${p}-download-template`);
    const importBtn = document.getElementById(`${p}-batch-import`);
    if (!uploadArea || !fileInput || !downloadBtn || !importBtn) return;

    let selectedFile = null;
    let isImporting = false;

    uploadArea.addEventListener('click', (e) => {
        if (e.target.tagName !== 'BUTTON' && !e.target.closest('button')) fileInput.click();
    });

    uploadArea.addEventListener('dragover', (e) => {
        e.preventDefault();
        uploadArea.classList.add('border-success', 'bg-success', 'bg-opacity-10');
    });

    uploadArea.addEventListener('dragleave', () => {
        uploadArea.classList.remove('border-success', 'bg-success', 'bg-opacity-10');
    });

    uploadArea.addEventListener('drop', (e) => {
        e.preventDefault();
        uploadArea.classList.remove('border-success', 'bg-success', 'bg-opacity-10');
        if (e.dataTransfer.files.length > 0) handleFile(e.dataTransfer.files[0]);
    });

    fileInput.addEventListener('change', (e) => {
        if (e.target.files.length > 0) handleFile(e.target.files[0]);
    });

    function handleFile(file) {
        if (!file.name.match(/\.(xlsx|xls)$/i)) {
            GlobalNotification.error('请选择Excel文件');
            return;
        }
        const maxSize = 10 * 1024 * 1024;
        if (file.size > maxSize) {
            GlobalNotification.error(`文件大小不能超过 10MB，当前文件 ${(file.size / 1024 / 1024).toFixed(1)}MB`);
            return;
        }
        selectedFile = file;
        document.getElementById(`${p}-excel-preview`).innerHTML = `
            <div class="alert alert-info py-2">
                <i class="fas fa-file-excel me-2"></i>${escapeHtml(file.name)}
            </div>`;
        importBtn.disabled = false;
    }

    downloadBtn.addEventListener('click', async (e) => {
        e.stopPropagation();
        downloadBtn.disabled = true;
        downloadBtn.innerHTML = '<i class="fas fa-spinner fa-spin me-1"></i>下载中...';

        try {
            const response = await fetch('/api/v1/batch/download-template');
            const blob = await response.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url; a.download = cfg.batch.templateName; a.click();
            window.URL.revokeObjectURL(url);
        } catch (error) {
            GlobalNotification.error('下载失败');
        } finally {
            downloadBtn.disabled = false;
            downloadBtn.innerHTML = '<i class="fas fa-file-excel me-1"></i>下载模板';
        }
    });

    importBtn.addEventListener('click', async () => {
        if (!selectedFile || isImporting) return;
        isImporting = true;
        importBtn.disabled = true;
        importBtn.innerHTML = '<i class="fas fa-spinner fa-spin me-1"></i>导入中...';

        const formData = new FormData();
        formData.append('file', selectedFile);

        try {
            const response = await fetch(cfg.batch.importApi, {
                method: 'POST', body: formData
            });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const result = await response.json();
            if (result.success) {
                GlobalNotification.success(`成功导入 ${result.imported} 条记录`);
                loadList(cfg);
            } else {
                GlobalNotification.error(result.message || '导入失败');
            }
        } catch (error) {
            GlobalNotification.error(`导入失败: ${error.message}`);
        } finally {
            isImporting = false;
            importBtn.disabled = false;
            importBtn.innerHTML = '<i class="fas fa-upload me-1"></i>开始导入';
        }
    });
}
