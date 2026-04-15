// ERP桌面应用主逻辑
class ERPApp {
    constructor() {
        this.currentPage = 'dashboard';
        this.backendUrl = 'http://localhost:5003';
        this.init();
    }

    async init() {
        this.setupWindowControls();
        await this.loadVersion();
        this.renderDashboard();
        this.setupNavigation();
    }

    setupWindowControls() {
        document.getElementById('minimizeBtn').addEventListener('click', () => {
            window.erpAPI.minimizeWindow();
        });

        document.getElementById('maximizeBtn').addEventListener('click', () => {
            window.erpAPI.maximizeWindow();
        });

        document.getElementById('closeBtn').addEventListener('click', () => {
            window.erpAPI.closeWindow();
        });
    }

    async loadVersion() {
        try {
            const version = window.erpAPI.getVersion();
            document.getElementById('versionDisplay').textContent = `v${version}`;
        } catch (error) {
            console.log('非Electron环境，使用Web模式');
        }
    }

    async fetchAPI(endpoint, options = {}) {
        try {
            const response = await fetch(`${this.backendUrl}${endpoint}`, {
                ...options,
                headers: {
                    'Content-Type': 'application/json',
                    ...options.headers
                }
            });
            return await response.json();
        } catch (error) {
            console.error('API请求失败:', error);
            this.showError('请求失败，请检查网络连接');
            return null;
        }
    }

    showError(message) {
        alert(message);
    }

    setupNavigation() {
        document.querySelectorAll('[data-page]').forEach(link => {
            link.addEventListener('click', (e) => {
                e.preventDefault();
                const page = link.getAttribute('data-page');
                this.navigate(page);
            });
        });
    }

    navigate(page) {
        this.currentPage = page;
        
        document.querySelectorAll('.nav-link').forEach(link => {
            link.classList.remove('active');
            if (link.getAttribute('data-page') === page) {
                link.classList.add('active');
            }
        });

        this.renderPage(page);
    }

    async renderPage(page) {
        const content = document.getElementById('mainContent');
        content.innerHTML = '<div class="text-center py-5"><div class="spinner-border text-primary"></div><p class="mt-2">加载中...</p></div>';

        switch (page) {
            case 'dashboard':
                await this.renderDashboard();
                break;
            case 'products':
                await this.renderProducts();
                break;
            case 'orders':
                await this.renderOrders();
                break;
            case 'stock':
                await this.renderStock();
                break;
            case 'reports':
                await this.renderReports();
                break;
        }
    }

    async renderDashboard() {
        const content = document.getElementById('mainContent');
        content.innerHTML = `
            <div class="d-flex justify-content-between align-items-center mb-4">
                <h2 class="fw-bold">仪表盘</h2>
                <button class="btn btn-primary" onclick="app.navigate('orders')">
                    <i class="fas fa-plus me-1"></i>新建订单
                </button>
            </div>

            <div class="row g-4 mb-4">
                <div class="col-md-3">
                    <div class="stat-card">
                        <i class="fas fa-box fa-2x text-primary mb-2"></i>
                        <h3 id="totalProducts">0</h3>
                        <small>产品总数</small>
                    </div>
                </div>
                <div class="col-md-3">
                    <div class="stat-card">
                        <i class="fas fa-file-invoice fa-2x text-success mb-2"></i>
                        <h3 id="totalOrders">0</h3>
                        <small>订单总数</small>
                    </div>
                </div>
                <div class="col-md-3">
                    <div class="stat-card">
                        <i class="fas fa-warehouse fa-2x text-info mb-2"></i>
                        <h3 id="totalStock">0</h3>
                        <small>总库存</small>
                    </div>
                </div>
                <div class="col-md-3">
                    <div class="stat-card">
                        <i class="fas fa-chart-line fa-2x text-warning mb-2"></i>
                        <h3 id="pendingOrders">0</h3>
                        <small>待处理订单</small>
                    </div>
                </div>
            </div>

            <div class="row">
                <div class="col-lg-6">
                    <div class="card">
                        <div class="card-header">
                            <h5>最近订单</h5>
                        </div>
                        <div class="card-body" id="recentOrders">
                            <p class="text-center text-muted">加载中...</p>
                        </div>
                    </div>
                </div>
                <div class="col-lg-6">
                    <div class="card">
                        <div class="card-header">
                            <h5>库存预警</h5>
                        </div>
                        <div class="card-body" id="stockAlerts">
                            <p class="text-center text-muted">暂无预警</p>
                        </div>
                    </div>
                </div>
            </div>
        `;

        await this.loadDashboardData();
    }

    async loadDashboardData() {
        const [products, orders, stock] = await Promise.all([
            this.fetchAPI('/api/products'),
            this.fetchAPI('/api/orders'),
            this.fetchAPI('/api/stock')
        ]);

        if (products) {
            document.getElementById('totalProducts').textContent = products.length;
        }

        if (orders) {
            document.getElementById('totalOrders').textContent = orders.length;
            const pending = orders.filter(o => o.status === '待备货' || o.status === '部分备货').length;
            document.getElementById('pendingOrders').textContent = pending;
        }

        if (stock) {
            document.getElementById('totalStock').textContent = stock.total_total_qty || 0;
        }
    }

    async renderProducts() {
        const content = document.getElementById('mainContent');
        content.innerHTML = `
            <div class="d-flex justify-content-between align-items-center mb-4">
                <h2 class="fw-bold">产品管理</h2>
                <button class="btn btn-primary" onclick="alert('添加产品功能待实现')">
                    <i class="fas fa-plus me-1"></i>添加产品
                </button>
            </div>

            <div class="card">
                <div class="card-header">
                    <h5>产品列表</h5>
                </div>
                <div class="card-body">
                    <div class="table-responsive">
                        <table class="table table-hover">
                            <thead>
                                <tr>
                                    <th>产品图片</th>
                                    <th>产品名称</th>
                                    <th>69码</th>
                                    <th>当前库存</th>
                                    <th>状态</th>
                                    <th>操作</th>
                                </tr>
                            </thead>
                            <tbody id="productsTable">
                                <tr><td colspan="6" class="text-center">加载中...</td></tr>
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>
        `;

        const products = await this.fetchAPI('/api/products');
        const tbody = document.getElementById('productsTable');

        if (products && products.length > 0) {
            tbody.innerHTML = products.map(p => `
                <tr>
                    <td>
                        ${p.image ? `<img src="${p.image}" class="rounded" style="width:50px;height:50px;object-fit:cover">` : '<i class="fas fa-box text-muted"></i>'}
                    </td>
                    <td>${p.name}</td>
                    <td>${p.barcode || '-'}</td>
                    <td>${p.current_stock}</td>
                    <td>
                        <span class="badge ${p.status ? (p.status === '启用' ? 'bg-success' : 'bg-danger') : 'bg-secondary'}">
                            ${p.status || '启用'}
                        </span>
                    </td>
                    <td>
                        <button class="btn btn-sm btn-primary" onclick="alert('编辑产品功能待实现')">
                            <i class="fas fa-edit"></i>
                        </button>
                    </td>
                </tr>
            `).join('');
        } else {
            tbody.innerHTML = '<tr><td colspan="6" class="text-center text-muted">暂无产品数据</td></tr>';
        }
    }

    async renderOrders() {
        const content = document.getElementById('mainContent');
        content.innerHTML = `
            <div class="d-flex justify-content-between align-items-center mb-4">
                <h2 class="fw-bold">订单管理</h2>
                <button class="btn btn-primary" onclick="alert('新建订单功能待实现')">
                    <i class="fas fa-plus me-1"></i>新建订单
                </button>
            </div>

            <div class="card">
                <div class="card-header">
                    <h5>订单列表</h5>
                </div>
                <div class="card-body">
                    <div class="table-responsive">
                        <table class="table table-hover">
                            <thead>
                                <tr>
                                    <th>订单编号</th>
                                    <th>客户</th>
                                    <th>产品</th>
                                    <th>数量</th>
                                    <th>状态</th>
                                    <th>下单时间</th>
                                    <th>操作</th>
                                </tr>
                            </thead>
                            <tbody id="ordersTable">
                                <tr><td colspan="7" class="text-center">加载中...</td></tr>
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>
        `;

        const orders = await this.fetchAPI('/api/orders');
        const tbody = document.getElementById('ordersTable');

        if (orders && orders.length > 0) {
            tbody.innerHTML = orders.map(o => `
                <tr>
                    <td>${o.order_no || '-'}</td>
                    <td>${o.customer || '-'}</td>
                    <td>${o.product_name || '-'}</td>
                    <td>${o.quantity || 0}</td>
                    <td>
                        <span class="badge bg-${this.getStatusColor(o.status)}">
                            ${o.status || '待备货'}
                        </span>
                    </td>
                    <td>${o.order_date || '-'}</td>
                    <td>
                        <button class="btn btn-sm btn-info" onclick="alert('查看订单功能待实现')">
                            <i class="fas fa-eye"></i>
                        </button>
                    </td>
                </tr>
            `).join('');
        } else {
            tbody.innerHTML = '<tr><td colspan="7" class="text-center text-muted">暂无订单数据</td></tr>';
        }
    }

    async renderStock() {
        const content = document.getElementById('mainContent');
        content.innerHTML = `
            <div class="d-flex justify-content-between align-items-center mb-4">
                <h2 class="fw-bold">库存管理</h2>
                <button class="btn btn-primary" onclick="alert('入库操作功能待实现')">
                    <i class="fas fa-plus me-1"></i>入库
                </button>
            </div>

            <div class="card">
                <div class="card-header">
                    <h5>库存查询</h5>
                </div>
                <div class="card-body">
                    <div class="table-responsive">
                        <table class="table table-hover">
                            <thead>
                                <tr>
                                    <th>客户</th>
                                    <th>产品名称</th>
                                    <th>69码</th>
                                    <th>订单数量</th>
                                    <th>备货数量</th>
                                    <th>总库存</th>
                                </tr>
                            </thead>
                            <tbody id="stockTable">
                                <tr><td colspan="6" class="text-center">加载中...</td></tr>
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>
        `;

        const stock = await this.fetchAPI('/api/stock');
        const tbody = document.getElementById('stockTable');

        if (stock && stock.inventory_data && stock.inventory_data.length > 0) {
            tbody.innerHTML = stock.inventory_data.map(item => `
                <tr>
                    <td>${item.customer || '-'}</td>
                    <td>${item.product_name || '-'}</td>
                    <td>${item.product_barcode || '-'}</td>
                    <td>${item.order_quantity || 0}</td>
                    <td>${item.stockin_quantity || 0}</td>
                    <td class="fw-bold text-primary">${item.total_stock || 0}</td>
                </tr>
            `).join('');
        } else {
            tbody.innerHTML = '<tr><td colspan="6" class="text-center text-muted">暂无库存数据</td></tr>';
        }
    }

    async renderReports() {
        const content = document.getElementById('mainContent');
        content.innerHTML = `
            <div class="d-flex justify-content-between align-items-center mb-4">
                <h2 class="fw-bold">报表统计</h2>
                <div>
                    <button class="btn btn-primary me-2" onclick="alert('导出Excel功能待实现')">
                        <i class="fas fa-file-excel me-1"></i>导出Excel
                    </button>
                    <button class="btn btn-outline-primary" onclick="alert('刷新报表功能待实现')">
                        <i class="fas fa-sync"></i>
                    </button>
                </div>
            </div>

            <div class="row g-4 mb-4">
                <div class="col-md-4">
                    <div class="card">
                        <div class="card-header bg-primary text-white">
                            <h5 class="mb-0">订单统计</h5>
                        </div>
                        <div class="card-body">
                            <h3 class="text-primary" id="reportTotalOrders">0</h3>
                            <small class="text-muted">总订单数</small>
                        </div>
                    </div>
                </div>
                <div class="col-md-4">
                    <div class="card">
                        <div class="card-header bg-success text-white">
                            <h5 class="mb-0">出货统计</h5>
                        </div>
                        <div class="card-body">
                            <h3 class="text-success" id="reportTotalShipped">0</h3>
                            <small class="text-muted">总出货量</small>
                        </div>
                    </div>
                </div>
                <div class="col-md-4">
                    <div class="card">
                        <div class="card-header bg-info text-white">
                            <h5 class="mb-0">库存价值</h5>
                        </div>
                        <div class="card-body">
                            <h3 class="text-info" id="reportStockValue">¥0</h3>
                            <small class="text-muted">预估价值</small>
                        </div>
                    </div>
                </div>
            </div>

            <div class="card">
                <div class="card-header">
                    <h5>订单流水</h5>
                </div>
                <div class="card-body">
                    <div class="table-responsive">
                        <table class="table table-hover">
                            <thead>
                                <tr>
                                    <th>订单编号</th>
                                    <th>客户</th>
                                    <th>产品</th>
                                    <th>数量</th>
                                    <th>状态</th>
                                    <th>下单时间</th>
                                </tr>
                            </thead>
                            <tbody id="reportOrdersTable">
                                <tr><td colspan="6" class="text-center">加载中...</td></tr>
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>
        `;

        const orders = await this.fetchAPI('/api/orders');
        const tbody = document.getElementById('reportOrdersTable');

        if (orders && orders.length > 0) {
            document.getElementById('reportTotalOrders').textContent = orders.length;
            tbody.innerHTML = orders.slice(0, 10).map(o => `
                <tr>
                    <td>${o.order_no || '-'}</td>
                    <td>${o.customer || '-'}</td>
                    <td>${o.product_name || '-'}</td>
                    <td>${o.quantity || 0}</td>
                    <td>
                        <span class="badge bg-${this.getStatusColor(o.status)}">
                            ${o.status || '待备货'}
                        </span>
                    </td>
                    <td>${o.order_date || '-'}</td>
                </tr>
            `).join('');
        } else {
            document.getElementById('reportTotalOrders').textContent = 0;
            tbody.innerHTML = '<tr><td colspan="6" class="text-center text-muted">暂无数据</td></tr>';
        }
    }

    getStatusColor(status) {
        const colors = {
            '待备货': 'warning',
            '部分备货': 'info',
            '已备货': 'primary',
            '待出货': 'secondary',
            '已出货': 'success',
            '已取消': 'danger'
        };
        return colors[status] || 'secondary';
    }
}

// 初始化应用
const app = new ERPApp();
