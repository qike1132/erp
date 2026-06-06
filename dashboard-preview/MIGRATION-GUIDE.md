# dashboard-preview → frontend-vite 迁移项目说明文档

> **版本**: v1.0.0  
> **创建日期**: 2026-05-20  
> **适用范围**: 所有参与 ERP 系统移动端开发和迁移的团队成员  
> **状态**: 强制执行规范

---

## 一、迁移目标

### 1.1 项目定位

| 项目 | 定位 | 技术栈 | 用途 |
|------|------|--------|------|
| `dashboard-preview/` | 快速原型验证 | 单 HTML + 原生 JS | 验证移动端 UI/UX、交互逻辑、动画效果 |
| `frontend-vite/` | 生产级 APK | Vue 3 + TypeScript + Capacitor | 最终发布到移动设备的生产应用 |

### 1.2 迁移目标

1. **零功能缺失** — dashboard-preview 中的所有功能必须完整迁移
2. **代码质量提升** — 从原生 JS 转为 TypeScript + Vue 3 Composition API
3. **架构统一** — 复用 frontend-vite 已有的组件、API、Store
4. **性能优化** — 利用 Vue 响应式、虚拟 DOM、按需加载
5. **安全加固** — 保持 XSS 防护、401 自动跳转等已修复的安全措施

### 1.3 迁移范围

| dashboard-preview 功能模块 | frontend-vite 目标路径 |
|---------------------------|----------------------|
| 概览页（订单/出库/生产/仓储卡片） | `src/mobile/views/dashboard/DashboardMobile.vue` |
| 出货计划页（日卡片/汇总/抽屉） | `src/mobile/views/shipment/MShipmentView.vue` |
| 登录页 | 已存在 `src/views/login/LoginView.vue`（不迁移） |
| 底部导航 | 已存在 `src/mobile/layouts/MobileLayout.vue`（不迁移） |
| CSS 变量 | `src/styles/mobile-tokens.css`（已有，需补充） |
| API 调用 | `src/api/index.ts`（已有，需补充） |

---

## 二、技术栈对照

### 2.1 核心技术映射

| 功能 | dashboard-preview | frontend-vite |
|------|-------------------|---------------|
| **框架** | 无（原生 JS） | Vue 3.5 + Composition API |
| **语言** | JavaScript | TypeScript |
| **构建** | 无（浏览器直接打开） | Vite 8 |
| **样式** | `<style>` 内联 CSS | CSS Variables + Scoped CSS |
| **状态管理** | 全局变量 + localStorage | Pinia + `useAuthStore()` |
| **路由** | 手动切换 `.page` | Vue Router 5 |
| **HTTP 请求** | `fetchWithTimeout()` | Axios（已封装拦截器） |
| **实时同步** | 手动 `setInterval` + WebSocket | `@vueuse/core` composables |
| **动画** | 手动 DOM 操作 + CSS | Vue `<Transition>` + CSS |
| **格式化** | `fmtNum()` / `fmtMoney()` | `src/utils/format.ts` |
| **XSS 防护** | `escapeHtml()` | Vue 模板自动转义 |

### 2.2 依赖库对照

| 功能 | dashboard-preview | frontend-vite |
|------|-------------------|---------------|
| 实时轮询 | 手动实现 | `useIntervalFn()` from @vueuse/core |
| 页面可见性 | `document.visibilitychange` | `useDocumentVisibility()` |
| 事件防抖 | 手动 setTimeout | `useDebounceFn()` |
| 网络状态 | 无 | `useNetwork()` from @vueuse/core |
| 移动端适配 | 手动 CSS | Capacitor + CSS Variables |
| APK 打包 | 无 | Capacitor + Android SDK |

---

## 三、代码迁移映射规则

### 3.1 DOM 操作 → Vue 响应式

```javascript
// ❌ dashboard-preview (原生 JS)
let orderCount = 0;
document.getElementById('orderCount').textContent = orderCount;

// ✅ frontend-vite (Vue 3)
const orderCount = ref(0);
// 模板中直接使用 {{ orderCount }}
```

**规则**:
| 原生 JS | Vue 3 |
|---------|-------|
| `let x = value` | `const x = ref(value)` |
| `x = newValue` | `x.value = newValue` |
| `document.getElementById('el').textContent = x` | `{{ x }}` 模板绑定 |
| `document.getElementById('el').innerHTML = html` | `v-html="html"` 或 `v-for` |

### 3.2 事件处理

```javascript
// ❌ dashboard-preview
<button onclick="doRefresh()">刷新</button>

// ✅ frontend-vite
<button @click="doRefresh">刷新</button>
```

**规则**:
| 原生 JS | Vue 3 |
|---------|-------|
| `onclick="fn()"` | `@click="fn"` |
| `oninput="fn(this.value)"` | `@input="fn($event.target.value)"` 或 `v-model` |
| `addEventListener('click', fn)` | `@click="fn"` |

### 3.3 条件渲染

```javascript
// ❌ dashboard-preview
if (loading) {
  document.getElementById('loadingSpinner').style.display = 'block';
  document.getElementById('content').style.display = 'none';
} else {
  document.getElementById('loadingSpinner').style.display = 'none';
  document.getElementById('content').style.display = 'block';
}

// ✅ frontend-vite
<template v-if="loading">
  <MSpinner />
</template>
<template v-else>
  <!-- 内容 -->
</template>
```

### 3.4 列表渲染

```javascript
// ❌ dashboard-preview
var html = '';
customers.forEach(function(c) {
  html += '<div class="customer">' + c.name + '</div>';
});
container.innerHTML = html;

// ✅ frontend-vite
<div v-for="c in customers" :key="c.id" class="customer">
  {{ c.name }}
</div>
```

### 3.5 API 调用

```javascript
// ❌ dashboard-preview
async function loadOrders() {
  const data = await fetchWithTimeout(API_V1 + '/dashboard/orders', 6000, authHeaders());
  return data.orders;
}

// ✅ frontend-vite
import { dashboardApi } from '@/api';

async function loadOrders() {
  const data = await dashboardApi.orders();  // axios 拦截器已处理 401
  return data.orders;
}
```

**关键差异**:
- dashboard-preview 需手动调用 `authHeaders()`
- frontend-vite 的 axios 拦截器自动附加 `Authorization` 和 `X-CSRF-Token`
- frontend-vite 自动处理 401 跳转登录页（见 `src/api/request.ts:52-61`）

### 3.6 格式化函数

```javascript
// ❌ dashboard-preview
function fmtNum(n) {
  if (n === null || n === undefined) return '—';
  if (typeof n === 'number') return n.toLocaleString('zh-CN');
  return String(n);
}

// ✅ frontend-vite
import { formatNumber, formatCurrency } from '@/utils/format';

// formatNumber(12345) → '12,345'
// formatCurrency(12345) → '¥12,345.00'
```

### 3.7 XSS 防护

```javascript
// ❌ dashboard-preview (需手动转义)
div.innerHTML = '<span>' + escapeHtml(customerName) + '</span>';

// ✅ frontend-vite (Vue 自动转义)
<span>{{ customerName }}</span>  <!-- 自动 HTML 转义，无需 escapeHtml() -->
```

**重要**: Vue 模板的 `{{ }}` 插值自动转义 HTML，只有 `v-html` 才需要手动确保安全。

### 3.8 实时同步

```javascript
// ❌ dashboard-preview
setInterval(function() {
  if (isPageVisible) refreshData();
}, 30000);

// ✅ frontend-vite
import { useIntervalFn, useDocumentVisibility } from '@vueuse/core';

const visibility = useDocumentVisibility();
const { pause, resume } = useIntervalFn(
  () => { if (visibility.value === 'visible') refreshData(); },
  30000,
  { immediate: true }
);
```

---

## 四、组件拆分规范

### 4.1 概览页拆分

```
src/mobile/views/dashboard/
├── DashboardMobile.vue              # 主视图容器
├── components/
│   ├── DashHeader.vue               # 问候语 + 用户头像
│   ├── DashOrderCard.vue            # 今日订单卡片
│   ├── DashStockCard.vue            # 今日出库卡片
│   ├── DashProductionCard.vue       # 生产数据卡片
│   ├── DashWarehouseCard.vue        # 皮套仓储卡片
│   └── DashQuickEntry.vue           # 快捷入口网格
└── composables/
    └── useDashboardData.ts          # 数据加载 + 轮询 + WebSocket
```

### 4.2 出货计划页拆分

```
src/mobile/views/shipment/
├── MShipmentView.vue                # 主视图容器
├── components/
│   ├── ShipmentDayGrid.vue          # 日卡片网格视图
│   ├── ShipmentDayCard.vue          # 单个日卡片
│   ├── ShipmentSummaryTable.vue     # 汇总表格视图
│   ├── ShipmentDrawer.vue           # 底部抽屉（计划/记录）
│   ├── ShipmentSkuDrawer.vue        # SKU 详情抽屉
│   └── ShipmentDateNav.vue          # 日期导航条
└── composables/
    └── useShipmentData.ts           # 数据加载 + 排序 + 过滤
```

### 4.3 组件命名规范

| 类型 | 命名规则 | 示例 |
|------|----------|------|
| 页面视图 | `XxxView.vue` 或 `MXxxView.vue` | `DashboardMobile.vue`, `MShipmentView.vue` |
| 业务组件 | `功能名+类型.vue` | `DashOrderCard.vue`, `ShipmentDrawer.vue` |
| 通用组件 | `M+类型.vue` | `MCard.vue`, `MButton.vue`, `MList.vue` |
| Composable | `use+功能名.ts` | `useDashboardData.ts`, `useShipmentData.ts` |

---

## 五、API 接口补充

### 5.1 需新增的 API 接口

在 `src/api/index.ts` 中补充：

```typescript
// ===== Dashboard Mobile =====
export const dashboardMobileApi = {
  // 概览数据
  overview: (date?: string) => get('/dashboard/mobile/overview', { date }),
  
  // 部门生产排行
  departmentRanking: (date?: string) => get('/dashboard/mobile/department-ranking', { date }),
  
  // 客户明细
  customerDetail: (params: { mode: string; period: string; date?: string }) => 
    get('/dashboard/mobile/customer-detail', params),
  
  // 生产数据
  productionStats: (date?: string) => get('/dashboard/mobile/production', { date }),
  
  // 仓储数据
  warehouseStats: () => get('/dashboard/mobile/warehouse'),
}

// ===== Shipment Mobile =====
export const shipmentMobileApi = {
  // 月度计划列表
  monthlyPlans: (params: { year: number; month: number }) => 
    get('/plans/monthly', params),
  
  // 日计划详情
  dayPlans: (date: string) => get('/plans/list', { date }),
  
  // 出货记录（批量）
  shipmentRecordsBatch: (planIds: number[]) => 
    post('/plans/shipment/records/batch', { plan_ids: planIds }),
  
  // SKU 详情
  skuDetail: (params: { barcode?: string; product_name: string }) => 
    get('/plans/sku-detail', params),
}
```

### 5.2 API 基地址配置

**Capacitor 环境** (`VITE_CAPACITOR=true`):
```env
VITE_API_BASE_URL=http://192.168.0.95:5002/api/v1
VITE_STATIC_ORIGIN=http://192.168.0.95:5002
```

**Web 开发环境**:
```env
VITE_API_BASE_URL=/api/v1
```

---

## 六、CSS 迁移规范

### 6.1 CSS 变量映射

| dashboard-preview | frontend-vite | 说明 |
|-------------------|---------------|------|
| `--accent-primary` | `--m-accent` | 主题色 |
| `--text-primary` | `--m-text-primary` | 主文本色 |
| `--text-secondary` | `--m-text-secondary` | 次要文本色 |
| `--bg-card` | `--m-bg-card` | 卡片背景 |
| `--radius-md` | `--m-radius-md` | 圆角 |
| `--shadow-card` | `--m-shadow-card` | 卡片阴影 |

### 6.2 补充 CSS 变量

在 `src/styles/mobile-tokens.css` 末尾补充：

```css
/* dashboard-preview 迁移补充 */
:root {
  /* 状态色 */
  --m-status-success: #30D158;
  --m-status-warning: #FF9500;
  --m-status-error: #FF2D55;
  --m-status-info: #0071E3;
  
  /* 卡片渐变（概览页用） */
  --m-gradient-blue: linear-gradient(135deg, #0071E3 0%, #5AC8FA 100%);
  --m-gradient-green: linear-gradient(135deg, #30D158 0%, #34C759 100%);
  --m-gradient-orange: linear-gradient(135deg, #FF9500 0%, #FFCC00 100%);
  --m-gradient-purple: linear-gradient(135deg, #AF52DE 0%, #BF5AF2 100%);
  
  /* 日期导航 */
  --m-date-nav-height: 44px;
  
  /* 抽屉 */
  --m-drawer-height: 70vh;
  --m-drawer-radius: 20px;
}
```

### 6.3 Scoped CSS 规范

每个 Vue 组件使用 `<style scoped>`，遵循 BEM 命名：

```vue
<style scoped>
/* 容器 */
.dash-order-card { }

/* 元素 */
.dash-order-card__header { }
.dash-order-card__value { }
.dash-order-card__trend { }

/* 修饰符 */
.dash-order-card--positive { }
.dash-order-card--negative { }
</style>
```

---

## 七、迁移步骤

### 7.1 准备阶段

1. **验证原型完整性**
   - 在 `dashboard-preview/index.html` 中测试所有功能
   - 确认后端 API 可用（`http://192.168.0.95:5002`）
   - 记录所有交互细节和边界情况

2. **阅读已有代码**
   - 熟悉 `frontend-vite/src/mobile/` 目录结构
   - 学习已有组件 API：`MCard`, `MStatCard`, `MList`, `MBottomSheet` 等
   - 理解 `authStore`、`router`、`api` 的使用方式

### 7.2 迁移概览页

**步骤**:

```
1. 创建 composable: useDashboardData.ts
   - 数据定义: overviewData, departmentRanking, customerDetail, loading
   - 数据加载: loadOverview(), loadDepartmentRanking(), loadCustomerDetail()
   - 实时同步: useIntervalFn + useDocumentVisibility
   - 返回: { data refs, load functions, loading, refresh }

2. 创建子组件:
   - DashHeader.vue (问候语 + 用户名 + 头像)
   - DashOrderCard.vue (订单数量 + 趋势 + 点击展开)
   - DashStockCard.vue (出库数量 + 趋势)
   - DashProductionCard.vue (部门排行列表)
   - DashWarehouseCard.vue (皮套库存统计)

3. 组装主视图 DashboardMobile.vue:
   - import 所有子组件 + useDashboardData
   - 模板布局: header -> cards -> sections
   - 响应式: v-if loading, v-else content

4. 测试验证:
   - npm run dev，访问移动端路由
   - 对比 dashboard-preview 原型，确认 UI 一致
   - 测试所有交互：点击、刷新、日期切换
```

### 7.3 迁移出货计划页

**步骤**:

```
1. 创建 composable: useShipmentData.ts
   - 数据定义: plans, selectedDate, activeTab, drawerState
   - 数据加载: loadMonthlyPlans(), loadDayPlans()
   - 排序过滤: sortPlans(), filterByCustomer()
   - 返回: { plans, selectedDate, load, sort, filter }

2. 创建子组件:
   - ShipmentDayGrid.vue (日卡片网格)
   - ShipmentDayCard.vue (单个日卡片，显示客户标签)
   - ShipmentSummaryTable.vue (汇总表格，支持排序)
   - ShipmentDrawer.vue (底部抽屉，显示计划/记录)
   - ShipmentSkuDrawer.vue (SKU 详情抽屉)

3. 组装主视图 MShipmentView.vue:
   - import 所有子组件 + useShipmentData
   - 顶部: MFilterChips (日视图/汇总)
   - 中部: DayGrid 或 SummaryTable
   - 底部: Drawer 组件

4. 测试验证:
   - 测试日期导航（前一天/后一天/今天）
   - 测试日卡片点击打开抽屉
   - 测试客户筛选、排序
   - 测试 SKU 详情抽屉
```

### 7.4 补充 API 接口

1. 在 `src/api/index.ts` 中添加 `dashboardMobileApi` 和 `shipmentMobileApi`
2. 在后端 FastAPI 中实现对应端点（如尚未实现）
3. 前后端联调测试

### 7.5 最终验证

```
1. 功能完整性检查
   □ 所有 dashboard-preview 功能已实现
   □ 所有交互逻辑正确
   □ 所有动画效果一致

2. 性能检查
   □ 首屏加载 < 2s
   □ API 响应 < 1s
   □ 无内存泄漏

3. 安全检查
   □ XSS 防护（Vue 自动转义）
   □ 401 自动跳转（axios 拦截器）
   □ CSRF Token 自动附加

4. 移动端检查
   □ 响应式布局正确
   □ 触摸交互流畅
   □ 安全区域适配（刘海屏）
```

---

## 八、注意事项

### 8.1 严禁事项

| 禁止行为 | 原因 | 正确做法 |
|----------|------|----------|
| 在 Vue 中使用 `document.getElementById()` | 破坏响应式 | 使用 `ref()` + 模板引用 |
| 使用 `innerHTML` 拼接 HTML | XSS 风险 | 使用 `v-for` 或 `{{ }}` 插值 |
| 直接操作 DOM 样式 | 违反 Vue 原则 | 使用 `:class` / `:style` 绑定 |
| 在组件内定义全局变量 | 状态污染 | 使用 `ref()` / Pinia Store |
| 硬编码 API 地址 | 环境不一致 | 使用 `import.meta.env.VITE_API_BASE_URL` |
| 忽略 TypeScript 类型 | 类型安全丧失 | 定义 interface / type |

### 8.2 最佳实践

**Composable 设计**:
```typescript
// ✅ 推荐：返回响应式数据 + 方法
export function useDashboardData() {
  const overview = ref<OverviewData | null>(null);
  const loading = ref(false);
  
  async function load() {
    loading.value = true;
    try {
      overview.value = await dashboardMobileApi.overview();
    } finally {
      loading.value = false;
    }
  }
  
  return { overview, loading, load };
}
```

**组件通信**:
```typescript
// ✅ 父子通信：props + emits
// Parent
<ShipmentDrawer :date="selectedDate" @close="drawerOpen = false" />

// Child
const props = defineProps<{ date: string }>();
const emit = defineEmits<{ close: [] }>();
```

**状态共享**:
```typescript
// ✅ 跨组件状态：Pinia Store
import { useAuthStore } from '@/stores/auth';
const authStore = useAuthStore();
console.log(authStore.user?.username);
```

### 8.3 常见问题

**Q1: 如何处理 dashboard-preview 的全局变量？**

A: 转为 `ref()` 或 Pinia Store：
```javascript
// dashboard-preview
let spData = null;

// frontend-vite
const spData = ref<ShipmentData | null>(null);
// 或 Pinia Store
export const useShipmentStore = defineStore('shipment', () => {
  const data = ref<ShipmentData | null>(null);
  return { data };
});
```

**Q2: 如何迁移 `escapeHtml()`？**

A: 不需要迁移。Vue 模板的 `{{ }}` 自动转义 HTML：
```vue
<!-- 自动转义，等同于 escapeHtml(customerName) -->
<span>{{ customerName }}</span>
```

**Q3: 如何处理 `onclick` 中的动态参数？**

A: 使用 `@click` + 箭头函数：
```vue
<!-- dashboard-preview -->
<button onclick="spSelectCustomer('客户名')">选择</button>

<!-- frontend-vite -->
<button @click="spSelectCustomer('客户名')">选择</button>
```

**Q4: 如何迁移 `setInterval` 轮询？**

A: 使用 `@vueuse/core` 的 `useIntervalFn`：
```typescript
import { useIntervalFn } from '@vueuse/core';

const { pause, resume } = useIntervalFn(
  () => refreshData(),
  30000,  // 30秒
  { immediate: true }
);

// 可手动 pause() / resume() 控制轮询
```

**Q5: 如何处理 401 自动跳转？**

A: 已由 axios 拦截器处理，无需手动代码：
```typescript
// src/api/request.ts:52-61 已实现
if (error.response?.status === 401) {
  router.push(`/login?redirect=${encodeURIComponent(current)}`);
}
```

---

## 九、验证清单

### 9.1 功能验证

| 功能 | dashboard-preview | frontend-vite | 状态 |
|------|-------------------|---------------|------|
| 概览页 - 今日订单卡片 | ✅ | □ | 待迁移 |
| 概览页 - 今日出库卡片 | ✅ | □ | 待迁移 |
| 概览页 - 生产数据卡片 | ✅ | □ | 待迁移 |
| 概览页 - 皮套仓储卡片 | ✅ | □ | 待迁移 |
| 概览页 - 日期选择器 | ✅ | □ | 待迁移 |
| 概览页 - 客户明细弹窗 | ✅ | □ | 待迁移 |
| 概览页 - 下拉刷新 | ✅ | □ | 待迁移 |
| 出货计划 - 日视图 | ✅ | □ | 待迁移 |
| 出货计划 - 汇总视图 | ✅ | □ | 待迁移 |
| 出货计划 - 日期导航 | ✅ | □ | 待迁移 |
| 出货计划 - 日卡片点击 | ✅ | □ | 待迁移 |
| 出货计划 - 底部抽屉 | ✅ | □ | 待迁移 |
| 出货计划 - 客户筛选 | ✅ | □ | 待迁移 |
| 出货计划 - 排序功能 | ✅ | □ | 待迁移 |
| 出货计划 - SKU 详情 | ✅ | □ | 待迁移 |
| 登录页 | ✅ | ✅ | 已存在 |
| 底部导航 | ✅ | ✅ | 已存在 |
| 实时轮询 | ✅ | □ | 待迁移 |
| 页面可见性检测 | ✅ | □ | 待迁移 |
| 401 自动跳转 | ✅ | ✅ | axios 拦截器已实现 |

### 9.2 安全验证

| 安全项 | dashboard-preview | frontend-vite | 状态 |
|--------|-------------------|---------------|------|
| XSS 防护 - innerHTML 转义 | ✅ (escapeHtml) | ✅ (Vue 自动) | 已实现 |
| 401/403 自动跳转 | ✅ | ✅ (axios) | 已实现 |
| CSRF Token 自动附加 | ✅ | ✅ (axios) | 已实现 |
| 密码 HTTPS 传输 | ⚠️ HTTP (内网) | ⚠️ HTTP (内网) | 生产需 HTTPS |
| Redis 密码明文 | ❌ 已修复 | N/A | 已移除明文 |

### 9.3 性能验证

| 性能指标 | 目标值 | 测试方法 |
|----------|--------|----------|
| 首屏加载时间 | < 2s | Chrome DevTools Lighthouse |
| API 响应时间 | < 1s | Network 面板 |
| 出货记录并行请求 | 并发执行 | 对比串行时间 |
| 内存泄漏 | 无 | 长时间运行监控 |
| APK 包体积 | < 10MB | `npm run cap:build` 后检查 |

---

## 十、附录

### 10.1 文件路径对照表

| dashboard-preview | frontend-vite |
|-------------------|---------------|
| `index.html` (全部) | 拆分为多个 Vue 组件 |
| CSS 变量 | `src/styles/mobile-tokens.css` |
| `fetchWithTimeout()` | `src/api/request.ts` (axios) |
| `authHeaders()` | axios 拦截器自动附加 |
| `fmtNum()` / `fmtMoney()` | `src/utils/format.ts` |
| `escapeHtml()` | Vue 模板自动转义，无需迁移 |
| 登录逻辑 | `src/stores/auth.ts` + `src/views/login/LoginView.vue` |
| 路由逻辑 | `src/router/index.ts` (mobileRoutes) |
| 底部导航 | `src/mobile/layouts/MobileLayout.vue` |

### 10.2 环境变量

```env
# frontend-vite/.env.capacitor
VITE_CAPACITOR=true
VITE_API_BASE_URL=http://192.168.0.95:5002/api/v1
VITE_STATIC_ORIGIN=http://192.168.0.95:5002

# frontend-vite/.env.development
VITE_API_BASE_URL=/api/v1

# frontend-vite/.env.production
VITE_API_BASE_URL=/api/v1
```

### 10.3 构建命令

```bash
# 开发调试
npm run dev

# 类型检查
npm run type-check

# 代码检查
npm run lint

# 构建 Web 版本
npm run build

# 构建 Capacitor APK
npm run cap:build

# 同步 Capacitor
npm run cap:sync

# 打开 Android Studio
npm run cap:open
```

### 10.4 参考文档

- [Vue 3 Composition API](https://vuejs.org/guide/extras/composition-api-faq.html)
- [@vueuse/core 文档](https://vueuse.org/)
- [Capacitor 官方文档](https://capacitorjs.com/docs)
- [TypeScript 官方文档](https://www.typescriptlang.org/docs/)
- [Vite 官方文档](https://vitejs.dev/guide/)

---

**文档维护**: 本文档应随迁移进度持续更新，每完成一个模块后在验证清单中标记状态。

**最后更新**: 2026-05-20
