# Binfa ERP Dashboard Preview — 项目说明书

## 一、项目定位

本项目是 Binfa ERP 移动端数据看板的**原型开发环境**。采用单 HTML 文件快速迭代，UI/UX 定稿后迁移至 `frontend-vite` 的 Vue 3 项目。

**核心原则：先在这里把功能和设计做完善，再一次性迁移到 Vue 项目。**

---

## 二、技术栈

| 层 | 技术 | 说明 |
|----|------|------|
| 结构 | HTML5 | 语义化标签 |
| 样式 | 内联 CSS + CSS 变量 | Apple Human Interface 风格 |
| 逻辑 | 原生 JavaScript (ES2020+) | 无框架依赖 |
| HTTP | 原生 `fetch()` | 带 AbortController 超时 |
| 认证 | `localStorage` 存储 JWT | Bearer Token 模式 |

---

## 三、API 对接规范

### 3.1 后端地址

```
直连后端：http://192.168.0.95:5002/api/v1
```

> ⚠️ 不再使用 Vite 代理（3000 端口），改为直连后端 5002 端口，与 APK 实际运行环境一致。

### 3.2 认证流程

```
1. POST /api/v1/auth/login  { username, password, remember: true }
2. 响应 { access_token: "eyJ..." }
3. 存入 localStorage: token / access_token
4. 后续请求 Header: Authorization: Bearer <token>
5. CSRF Token: 从响应头 X-CSRF-Token 获取，存入 localStorage
6. 后续请求 Header: X-CSRF-Token: <token>
```

### 3.3 核心 API 端点

| 端点 | 方法 | 说明 | 响应格式 |
|------|------|------|---------|
| `/auth/login` | POST | 登录 | `{ access_token }` |
| `/auth/me` | GET | 当前用户 | `{ user_id, username, is_super, permissions }` |
| `/dashboard/stats` | GET | PC 端统计 | `{ success, data: { order_today, stockin_today, ... } }` |
| `/dashboard/mobile` | GET | 移动端统一数据 | `{ success, data: { stock, orders, production, warehouse } }` |
| `/dashboard/customer-out-details` | GET | 客户出库详情 | `{ success, data: [{ customer_name, total_quantity, total_amount }] }` |
| `/dashboard/customer-order-details` | GET | 客户订单详情 | `{ success, data: [{ customer_name, total_quantity, total_amount }] }` |
| `/plans/monthly` | GET | 月度出货计划 | `{ year, month, plans_by_date, customers }` |
| `/plans/shipment/records` | GET | 出货记录 | `{ records: [...] }` |

### 3.4 请求示例

```javascript
const API_BASE = 'http://192.168.0.95:5002/api/v1';

function authHeaders() {
  const token = localStorage.getItem('access_token') || '';
  const csrf = localStorage.getItem('csrf_token') || '';
  const h = { 'Content-Type': 'application/json' };
  if (token) h['Authorization'] = 'Bearer ' + token;
  if (csrf) h['X-CSRF-Token'] = csrf;
  return h;
}

async function fetchWithTimeout(url, timeout = 8000, headers = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  try {
    const merged = { ...headers, ...authHeaders(), 'Cache-Control': 'no-cache' };
    const res = await fetch(url, { signal: controller.signal, mode: 'cors', headers: merged });
    clearTimeout(timer);
    // 保存 CSRF Token
    const csrf = res.headers.get('X-CSRF-Token');
    if (csrf) localStorage.setItem('csrf_token', csrf);
    if (!res.ok) throw new Error('HTTP ' + res.status);
    return await res.json();
  } catch (e) {
    clearTimeout(timer);
    throw e;
  }
}
```

---

## 四、代码组织规范

### 4.1 JS 逻辑模块化

将代码按功能分块，便于后续 Vue 化迁移时一一对应：

```javascript
// ===== 认证模块 =====
function getAuthToken() { ... }
function authHeaders() { ... }
function isLoggedIn() { ... }
async function doLogin() { ... }
function onLoginSuccess() { ... }

// ===== 概览数据模块 =====
async function loadOverviewData(date) { ... }
function renderStockCard(data) { ... }
function renderOrdersCard(data) { ... }
function renderProductionCard(data) { ... }
function renderWarehouseCard(data) { ... }

// ===== 出货计划模块 =====
async function loadShipmentPlans(year, month) { ... }
function renderDayGrid(data) { ... }
function renderSummaryView(data) { ... }
function handleDayCardClick(dateStr) { ... }
function handleSortChange(field) { ... }

// ===== 抽屉/弹窗模块 =====
function openDrawer(dateStr) { ... }
function closeDrawer() { ... }
function openCustomerDetail(period) { ... }
function closeCustomerDetail() { ... }

// ===== 工具函数 =====
function fmtNum(n) { ... }
function fmtMoney(n) { ... }
function formatDateParam(date) { ... }
function animateCounter(el, target, formatter, duration) { ... }
```

### 4.2 CSS 变量对齐

本项目使用的 CSS 变量与 `frontend-vite` 的 `mobile-tokens.css` 保持一致：

| 本项目变量 | frontend-vite 对应 | 值 |
|-----------|-------------------|-----|
| `--bg-deep` | `--m-bg-deep` | `#F5F5F7` |
| `--bg-surface` | `--m-bg-surface` | `#FFFFFF` |
| `--text-primary` | `--m-text-primary` | `#1D1D1F` |
| `--text-secondary` | `--m-text-secondary` | `#86868B` |
| `--accent-primary` | `--m-accent` | `#0071E3` |
| `--accent-emerald` | `--m-accent-emerald` | `#30D158` |
| `--radius-sm/md/lg` | `--m-radius-sm/md/lg` | `12/16/22px` |
| `--shadow-card` | `--m-shadow-card` | 同值 |

> 迁移时只需将 CSS 变量名统一加 `--m-` 前缀即可。

---

## 五、页面结构

### 5.1 概览页 (page-overview)

```
┌─────────────────────────┐
│ 状态栏 + 日期选择        │
├─────────────────────────┤
│ 📋 订单总览卡片          │
│   总订单数量 | 总订单金额 │
├─────────────────────────┤
│ 📦 出库总览卡片          │
│   当日已出库 | 当月已出库 │
├─────────────────────────┤
│ 🖥 生产数据卡片          │
│   今日总产值 + 部门排名   │
├─────────────────────────┤
│ 🏭 皮套仓储卡片          │
│   进仓 | 出仓 数量/金额   │
├─────────────────────────┤
│ 📊 库存预警卡片（待开发） │
├─────────────────────────┤
│ ↓ 继续滑动查看更多       │
└─────────────────────────┘
```

### 5.2 出货计划页 (page-plans)

```
┌─────────────────────────┐
│ [每日] [汇总] 标签切换    │
│ KPI: 总计划 | 已出 | 剩余 │
├─────────────────────────┤
│ 每日视图：               │
│ ┌───┬──────────────────┐│
│ │日期│ 客户标签 + 状态   ││
│ │ 15 │ 500件 · 3家客户  ││
│ ├───┼──────────────────┤│
│ │ 16 │ 300件 · 2家客户  ││
│ └───┴──────────────────┘│
├─────────────────────────┤
│ 汇总视图：               │
│ 客户筛选标签             │
│ ┌──────────────────────┐│
│ │客户|产品|计划|已出|待出││
│ └──────────────────────┘│
└─────────────────────────┘

点击日卡片 → 底部抽屉
┌─────────────────────────┐
│ ═══ (拖拽条)             │
│ 5月15日 周四             │
│ [计划明细] [出货记录]     │
│ ████████░░ 75%          │
│                         │
│ 客户A  计划500 已出300   │
│   ├ 产品1  300  200  100 │
│   └ 产品2  200  100  100 │
│ 客户B  计划200 已出200   │
│   └ 产品3  200  200  0   │
└─────────────────────────┘
```

---

## 六、待完善功能清单

### 6.1 必须完成（迁移前）

- [ ] API 地址改为直连后端 `http://192.168.0.95:5002/api/v1`
- [ ] CSRF Token 从响应头获取并存储
- [ ] 登录失败时的错误提示优化
- [x] Token 过期自动跳转登录页
- [ ] 网络断开时的错误状态展示
- [ ] 下拉刷新功能
- [ ] 数据加载骨架屏（Skeleton）

### 6.2 建议完成（提升体验）

- [ ] 库存预警卡片（低库存物料列表）
- [ ] 数据趋势图表（近 7 天订单/出库趋势）
- [ ] 搜索功能（客户/产品搜索）
- [ ] 暗黑模式支持
- [ ] 手势操作（左滑删除、下拉刷新）
- [ ] 离线缓存（Service Worker）

### 6.3 可选（后续迭代）

- [ ] 推送通知（WebSocket 实时数据）
- [ ] 语音搜索
- [ ] 分享数据截图

---

## 七、迁移映射表

完成开发后，按以下映射关系迁移到 frontend-vite：

### 7.1 文件映射

| dashboard-preview | frontend-vite |
|-------------------|---------------|
| `index.html` 整体 | 拆分为多个 Vue 组件 |
| CSS 变量 | `src/styles/mobile-tokens.css` |
| 概览页 HTML/CSS/JS | `src/mobile/views/dashboard/DashboardMobile.vue` |
| 出货计划页 HTML/CSS/JS | `src/mobile/views/shipment/MShipmentView.vue` |
| 登录页 | `src/views/login/LoginView.vue`（已有，不迁移） |
| 底部导航 | `src/mobile/layouts/MobileLayout.vue`（已有，不迁移） |

### 7.2 逻辑映射

| 原生 JS | Vue 3 对应 |
|---------|-----------|
| `document.getElementById('xxx')` | `const xxx = ref()` |
| `el.textContent = value` | `{{ xxx }}` 模板绑定 |
| `el.innerHTML = html` | `v-html` 或 `v-for` 模板 |
| `onclick="fn()"` | `@click="fn"` |
| `localStorage.getItem('token')` | `authStore.token` (Pinia) |
| `fetch(url, headers)` | `dashboardApi.xxx()` (Axios) |
| `setInterval(fn, 60000)` | `useIntervalFn(fn, 60000)` |
| 手动 DOM 动画 | Vue `<Transition>` |
| 全局变量 `let spData` | `const spData = ref()` |

### 7.3 组件拆分建议

```
DashboardMobile.vue (概览页)
├── DashHeader.vue          (问候语 + 日期)
├── DashOrderCard.vue       (订单总览卡片)
├── DashStockCard.vue       (出库总览卡片)
├── DashProductionCard.vue  (生产数据卡片)
├── DashWarehouseCard.vue   (皮套仓储卡片)
└── useDashboardData.ts     (composable: 数据加载)

MShipmentView.vue (出货计划页)
├── ShipmentDayCard.vue     (日卡片)
├── ShipmentSummaryTable.vue(汇总表格)
├── ShipmentDrawer.vue      (底部抽屉)
├── ShipmentSkuDrawer.vue   (SKU 详情抽屉)
├── CustomerDetailModal.vue (客户详情弹窗)
└── useShipmentData.ts      (composable: 数据加载+排序)
```

---

## 八、开发注意事项

1. **不要引入任何框架或构建工具** — 保持单 HTML 文件，浏览器直接打开即可
2. **API 调用必须使用 `authHeaders()`** — 确保认证和 CSRF Token 一致
3. **新增功能先写函数再绑定事件** — 便于迁移时识别逻辑边界
4. **CSS 类名避免与 frontend-vite 冲突** — 使用 `dp-` 前缀或保持现有命名
5. **测试时确保后端服务运行** — Redis + FastAPI 都需要启动
6. **手机测试时确认同一局域网** — 后端 IP: `192.168.0.95:5002`

---

## 九、快速启动

```bash
# 1. 启动 Redis（带密码）
redis-server --requirepass "$REDIS_PASSWORD"

# 2. 启动后端 API
cd D:\erp_system
python -m fastapi_app.main

# 3. 浏览器打开
start D:\erp_system\dashboard-preview\index.html
# 或用 Live Server 等工具热重载
```

---

## 十、版本记录

| 日期 | 版本 | 变更 |
|------|------|------|
| 2026-05-17 | v0.1 | 初始版本：概览页 + 出货计划页 + 登录 |
| - | v1.0 | 功能完善，准备迁移（待定） |
