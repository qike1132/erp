/**
 * 财务统计页面 JavaScript
 */
const PER_PAGE = 20;

const requestLocks = {
    customer: false,
    daily: false
};

let dailyChart = null;

// ==================== 通用工具函数 ====================

function buildPagination(totalPages, currentPage, onPageClick) {
    if (totalPages <= 1) return '';

    let html = '';
    html += `<li class="page-item ${currentPage === 1 ? 'disabled' : ''}">
        <a class="page-link" href="#" onclick="${onPageClick}(${currentPage - 1}); return false;">上一页</a>
    </li>`;

    for (let i = 1; i <= totalPages; i++) {
        if (i === 1 || i === totalPages || (i >= currentPage - 2 && i <= currentPage + 2)) {
            html += `<li class="page-item ${i === currentPage ? 'active' : ''}">
                <a class="page-link" href="#" onclick="${onPageClick}(${i}); return false;">${i}</a>
            </li>`;
        } else if (i === currentPage - 3 || i === currentPage + 3) {
            html += `<li class="page-item disabled"><span class="page-link">...</span></li>`;
        }
    }

    html += `<li class="page-item ${currentPage === totalPages ? 'disabled' : ''}">
        <a class="page-link" href="#" onclick="${onPageClick}(${currentPage + 1}); return false;">下一页</a>
    </li>`;

    return html;
}

function showLoading(tbodyId, colspan) {
    document.getElementById(tbodyId).innerHTML = `
        <tr>
            <td colspan="${colspan}" class="text-center py-4">
                <div class="spinner-border text-primary" role="status">
                    <span class="visually-hidden">加载中...</span>
                </div>
                <p class="text-muted mt-2 mb-0">正在查询...</p>
            </td>
        </tr>
    `;
}

function showEmpty(tbodyId, colspan, message = '暂无数据') {
    document.getElementById(tbodyId).innerHTML = `
        <tr>
            <td colspan="${colspan}" class="text-center py-4">
                <i class="fas fa-inbox fa-3x mb-3 text-muted" style="opacity: 0.3;"></i>
                <p class="text-muted mb-0">${message}</p>
            </td>
        </tr>
    `;
}

function formatAmount(amount) {
    return '¥' + Number(amount).toLocaleString('zh-CN', {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
    });
}

// ==================== 客户列表加载 ====================

function loadCustomerOptions() {
    const customerSelects = ['customer_filter', 'daily_customer'];

    fetch('/api/v1/customers/active-names')
        .then(response => response.json())
        .then(customers => {
            customerSelects.forEach(selectId => {
                const select = document.getElementById(selectId);
                if (!select) return;

                const currentValue = select.value;
                select.innerHTML = '<option value="">全部客户</option>';

                customers.forEach(customer => {
                    const option = document.createElement('option');
                    option.value = customer.name;
                    option.textContent = customer.name;
                    select.appendChild(option);
                });

                if (currentValue) {
                    select.value = currentValue;
                }
            });
        })
        .catch(error => {
            console.error('加载客户列表失败:', error);
        });
}

// ==================== 客户出货汇总 ====================

function searchCustomerSummary(page = 1) {
    if (requestLocks.customer) return;
    requestLocks.customer = true;

    const customer = document.getElementById('customer_filter').value;
    const startDate = document.getElementById('customer_start_date').value;
    const endDate = document.getElementById('customer_end_date').value;

    const params = new URLSearchParams();
    params.append('page', page);
    params.append('per_page', PER_PAGE);
    if (customer) params.append('customer', customer);
    if (startDate) params.append('start_date', startDate);
    if (endDate) params.append('end_date', endDate);

    showLoading('customer-tbody', 4);

    fetch(`/api/v1/finance/customer-summary?${params.toString()}`)
        .then(response => {
            if (response.status === 429) {
                throw new Error('请求过于频繁，请稍后再试');
            }
            return response.json();
        })
        .then(data => {
            if (data.success) {
                renderCustomerSummary(data.logs, data.pagination, data.stats);
            } else {
                showEmpty('customer-tbody', 4, data.message || '查询失败');
            }
        })
        .catch(error => {
            const msg = error.message === '请求过于频繁，请稍后再试' ? error.message : '查询出错，请稍后重试';
            showEmpty('customer-tbody', 4, msg);
        })
        .finally(() => {
            requestLocks.customer = false;
        });
}

function renderCustomerSummary(logs, pagination, stats) {
    // 更新统计卡片
    document.getElementById('customer-total-count').textContent = stats.total_count || 0;
    document.getElementById('customer-total-quantity').textContent = (stats.total_quantity || 0).toLocaleString();
    document.getElementById('customer-total-amount').textContent = formatAmount(stats.total_amount || 0);

    document.getElementById('customer-count').textContent = `共 ${pagination.total} 条记录`;

    const paginationEl = document.getElementById('customer-pagination');
    if (logs.length === 0) {
        showEmpty('customer-tbody', 4);
        paginationEl.style.display = 'none';
        return;
    }

    const tbody = document.getElementById('customer-tbody');
    tbody.innerHTML = logs.map(log => `
        <tr>
            <td><i class="fas fa-building me-1"></i>${log.customer || '未知客户'}</td>
            <td class="text-center">${log.stockout_count}</td>
            <td class="text-center">${log.total_quantity.toLocaleString()}</td>
            <td class="text-end fw-bold">${formatAmount(log.total_amount)}</td>
        </tr>
    `).join('');

    if (pagination.pages > 1) {
        paginationEl.style.display = 'block';
        paginationEl.querySelector('ul').innerHTML = buildPagination(pagination.pages, pagination.page, 'searchCustomerSummary');
    } else {
        paginationEl.style.display = 'none';
    }
}

function resetCustomerSearch() {
    document.getElementById('customer_filter').value = '';
    document.getElementById('customer_start_date').value = '';
    document.getElementById('customer_end_date').value = '';
    document.getElementById('customer-pagination').style.display = 'none';
    showEmpty('customer-tbody', 4, '请点击查询按钮获取数据');
    document.getElementById('customer-count').textContent = '共 0 条记录';
    document.getElementById('customer-total-count').textContent = '0';
    document.getElementById('customer-total-quantity').textContent = '0';
    document.getElementById('customer-total-amount').textContent = '¥0.00';
}

// ==================== 每日出货金额 ====================

function searchDailyAmount(page = 1) {
    if (requestLocks.daily) return;
    requestLocks.daily = true;

    const customer = document.getElementById('daily_customer').value;
    const startDate = document.getElementById('daily_start_date').value;
    const endDate = document.getElementById('daily_end_date').value;

    const params = new URLSearchParams();
    params.append('page', page);
    params.append('per_page', PER_PAGE);
    if (customer) params.append('customer', customer);
    if (startDate) params.append('start_date', startDate);
    if (endDate) params.append('end_date', endDate);

    showLoading('daily-tbody', 5);

    fetch(`/api/v1/finance/daily-amount?${params.toString()}`)
        .then(response => {
            if (response.status === 429) {
                throw new Error('请求过于频繁，请稍后再试');
            }
            return response.json();
        })
        .then(data => {
            if (data.success) {
                renderDailyAmount(data.logs, data.pagination, data.stats);
            } else {
                showEmpty('daily-tbody', 5, data.message || '查询失败');
            }
        })
        .catch(error => {
            const msg = error.message === '请求过于频繁，请稍后再试' ? error.message : '查询出错，请稍后重试';
            showEmpty('daily-tbody', 5, msg);
        })
        .finally(() => {
            requestLocks.daily = false;
        });

    // 同时加载图表数据
    loadDailyChart(customer, startDate, endDate);
}

function renderDailyAmount(logs, pagination, stats) {
    // 更新统计卡片
    document.getElementById('daily-total-days').textContent = stats.total_count || 0;
    document.getElementById('daily-total-quantity').textContent = (stats.total_quantity || 0).toLocaleString();
    document.getElementById('daily-total-amount').textContent = formatAmount(stats.total_amount || 0);

    document.getElementById('daily-count').textContent = `共 ${pagination.total} 条记录`;

    const paginationEl = document.getElementById('daily-pagination');
    if (logs.length === 0) {
        showEmpty('daily-tbody', 5);
        paginationEl.style.display = 'none';
        return;
    }

    const tbody = document.getElementById('daily-tbody');
    tbody.innerHTML = logs.map(log => `
        <tr>
            <td><i class="fas fa-calendar me-1"></i>${log.date}</td>
            <td><i class="fas fa-building me-1"></i>${log.customer_names || '-'}</td>
            <td class="text-center">${log.stockout_count}</td>
            <td class="text-center">${log.total_quantity.toLocaleString()}</td>
            <td class="text-end fw-bold">${formatAmount(log.total_amount)}</td>
        </tr>
    `).join('');

    if (pagination.pages > 1) {
        paginationEl.style.display = 'block';
        paginationEl.querySelector('ul').innerHTML = buildPagination(pagination.pages, pagination.page, 'searchDailyAmount');
    } else {
        paginationEl.style.display = 'none';
    }
}

function loadDailyChart(customer, startDate, endDate) {
    const params = new URLSearchParams();
    if (customer) params.append('customer', customer);
    if (startDate) params.append('start_date', startDate);
    if (endDate) params.append('end_date', endDate);

    fetch(`/api/v1/finance/daily-amount-chart?${params.toString()}`)
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                renderDailyChart(data.chart);
            }
        })
        .catch(error => {
            console.error('加载图表数据失败:', error);
        });
}

function renderDailyChart(chartData) {
    const container = document.getElementById('dailyChartContainer');
    const emptyEl = document.getElementById('dailyChartEmpty');
    const canvas = document.getElementById('dailyAmountChart');

    if (!chartData.dates || chartData.dates.length === 0) {
        container.style.display = 'none';
        emptyEl.style.display = 'block';
        if (dailyChart) {
            dailyChart.destroy();
            dailyChart = null;
        }
        return;
    }

    container.style.display = 'block';
    emptyEl.style.display = 'none';

    if (dailyChart) {
        dailyChart.destroy();
    }

    const ctx = canvas.getContext('2d');
    dailyChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: chartData.dates,
            datasets: [{
                label: '出货金额',
                data: chartData.amounts,
                borderColor: 'rgb(135, 206, 235)',
                backgroundColor: 'rgba(135, 206, 235, 0.12)',
                borderWidth: 2.5,
                fill: true,
                tension: 0.35,
                pointRadius: 4,
                pointHoverRadius: 7,
                pointBackgroundColor: 'rgb(135, 206, 235)',
                pointBorderColor: '#fff',
                pointBorderWidth: 2,
                yAxisID: 'y',
            }, {
                label: '出货数量',
                data: chartData.quantities,
                borderColor: 'rgb(46, 125, 50)',
                backgroundColor: 'rgba(46, 125, 50, 0.08)',
                borderWidth: 2,
                fill: false,
                tension: 0.35,
                pointRadius: 3,
                pointHoverRadius: 6,
                pointBackgroundColor: 'rgb(46, 125, 50)',
                pointBorderColor: '#fff',
                pointBorderWidth: 2,
                yAxisID: 'y1',
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: {
                mode: 'index',
                intersect: false,
            },
            plugins: {
                tooltip: {
                    backgroundColor: 'rgba(90, 74, 74, 0.9)',
                    titleFont: { weight: '600' },
                    bodyFont: { size: 13 },
                    padding: 12,
                    cornerRadius: 8,
                    callbacks: {
                        label: function(context) {
                            let label = context.dataset.label || '';
                            if (label) label += ': ';
                            if (context.datasetIndex === 0) {
                                label += formatAmount(context.parsed.y);
                            } else {
                                label += context.parsed.y;
                            }
                            return label;
                        }
                    }
                }
            },
            scales: {
                x: {
                    grid: {
                        display: false,
                    },
                    ticks: { font: { size: 11 } }
                },
                y: {
                    type: 'linear',
                    display: true,
                    position: 'left',
                    title: {
                        display: true,
                        text: '金额 (¥)',
                        font: { size: 12, weight: '600' },
                        color: 'rgb(135, 206, 235)',
                    },
                    grid: { color: 'rgba(176, 224, 230, 0.3)' },
                    ticks: {
                        callback: function(value) {
                            return '¥' + value.toLocaleString();
                        },
                        font: { size: 11 }
                    }
                },
                y1: {
                    type: 'linear',
                    display: true,
                    position: 'right',
                    title: {
                        display: true,
                        text: '数量',
                        font: { size: 12, weight: '600' },
                        color: 'rgb(46, 125, 50)',
                    },
                    grid: {
                        drawOnChartArea: false,
                    },
                    ticks: { font: { size: 11 } }
                }
            }
        }
    });
}

function resetDailySearch() {
    document.getElementById('daily_customer').value = '';
    document.getElementById('daily_start_date').value = '';
    document.getElementById('daily_end_date').value = '';
    document.getElementById('daily-pagination').style.display = 'none';
    showEmpty('daily-tbody', 5, '请点击查询按钮获取数据');
    document.getElementById('daily-count').textContent = '共 0 条记录';
    document.getElementById('daily-total-days').textContent = '0';
    document.getElementById('daily-total-quantity').textContent = '0';
    document.getElementById('daily-total-amount').textContent = '¥0.00';
    // 清除图表
    if (dailyChart) {
        dailyChart.destroy();
        dailyChart = null;
    }
    document.getElementById('dailyChartContainer').style.display = 'none';
    document.getElementById('dailyChartEmpty').style.display = 'block';
}

// ==================== 页面初始化 ====================

window.addEventListener('load', function() {
    loadCustomerOptions();

    // 自动加载客户出货汇总数据
    searchCustomerSummary(1);

    // Tab切换时自动加载数据
    document.querySelectorAll('button[data-bs-toggle="tab"]').forEach(tab => {
        tab.addEventListener('shown.bs.tab', function(e) {
            const targetId = e.target.getAttribute('data-bs-target');
            if (targetId === '#daily-panel') {
                searchDailyAmount(1);
            }
        });
    });
});
