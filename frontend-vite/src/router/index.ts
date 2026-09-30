/**
 * 路由配置 - 响应式自适应
 * 根据设备类型（PC/移动端）自动加载对应路由集
 * 所有路由懒加载，确保每种设备只加载自己需要的代码
 */
import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { isMobileDevice } from '@/composables/useDevice'
import { devLog } from '@/utils/devLog'
import { resolveNavAccess } from './navAccess'

// ==================== PC 端路由====================
const pcRoutes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/login/LoginView.vue'),
    meta: { requiresAuth: false },
  },
  {
    path: '/',
    component: () => import('@/layouts/DefaultLayout.vue'),
    meta: { requiresAuth: true },
    children: [
      { path: '', redirect: '/dashboard' },
      { path: 'dashboard', name: 'Dashboard', component: () => import('@/views/dashboard/DashboardView.vue'), meta: { hideHeader: true, navExempt: true } },
      { path: 'order', redirect: '/customer-order' },
      { path: 'order/:id', redirect: '/customer-order' },
      { path: 'product', name: 'Product', component: () => import('@/views/product/ProductListView.vue'), meta: { hideHeader: true } },
      { path: 'stock', name: 'Stock', component: () => import('@/views/stock/StockView.vue'), meta: { hideHeader: true } },
      { path: 'stock-out', name: 'StockOut', component: () => import('@/views/stock/StockOutView.vue'), meta: { hideHeader: true } },
      // 湖北订单 / 外发工序 / 工序预设 拆分为三个独立路由页面：
      // /beile-order 湖北订单；/outsource 外发工序；/outsource/presets 工序预设
      { path: 'beile-order', name: 'BeileOrder', component: () => import('@/views/hubei/HubeiView.vue'), meta: { hideHeader: true } },
      { path: 'outsource', name: 'Outsource', component: () => import('@/views/outsource/OutsourceOrderView.vue'), meta: { hideHeader: true } },
      { path: 'outsource/shipments', name: 'OutsourceShipments', component: () => import('@/views/outsource/OutsourceShipmentView.vue'), meta: { hideHeader: true } },
      { path: 'outsource/presets', name: 'OutsourcePresets', component: () => import('@/views/outsource/OutsourcePresetView.vue'), meta: { hideHeader: true } },
      { path: 'customer', name: 'Customer', component: () => import('@/views/customer/CustomerView.vue'), meta: { hideHeader: true } },
      {
        path: 'customer-order',
        name: 'CustomerOrder',
        component: () => import('@/views/customer-order/CustomerOrderView.vue'),
        meta: { hideHeader: true },
      },
      { path: 'supplier', name: 'Supplier', component: () => import('@/views/supplier/SupplierView.vue'), meta: { hideHeader: true } },
      { path: 'approval', name: 'Approval', component: () => import('@/views/approval/ApprovalView.vue'), meta: { hideHeader: true } },
      { path: 'purchase', name: 'Purchase', component: () => import('@/views/purchase/PurchaseView.vue'), meta: { hideHeader: true } },
      {
        path: 'purchase-plan',
        name: 'PurchasePlan',
        component: () => import('@/views/purchase-plan/PurchasePlanView.vue'),
        meta: { hideHeader: true },
      },
      { path: 'material', name: 'Material', component: () => import('@/views/material/MaterialView.vue'), meta: { hideHeader: true } },
      {
        path: 'material-calculator',
        name: 'MaterialCalculator',
        component: () => import('@/views/material-calculator/MaterialCalculatorView.vue'),
        meta: { hideHeader: true },
      },
      { path: 'case', name: 'Case', component: () => import('@/views/case/CaseView.vue'), meta: { hideHeader: true } },
      { path: 'batch', name: 'Batch', component: () => import('@/views/batch/BatchView.vue'), meta: { hideHeader: true } },
      { path: 'production', name: 'Production', component: () => import('@/views/production/ProductionView.vue'), meta: { hideHeader: true } },
      { path: 'report', name: 'Report', component: () => import('@/views/report/ReportView.vue'), meta: { hideHeader: true } },
      { path: 'user', name: 'User', component: () => import('@/views/user/UserView.vue'), meta: { hideHeader: true } },
      { path: 'permission', name: 'Permission', component: () => import('@/views/permission/PermissionView.vue') },
      { path: 'settings', name: 'Settings', component: () => import('@/views/settings/SettingsView.vue') },
      { path: 'ocr-import', name: 'OcrImport', component: () => import('@/views/ocr-import/OcrImportView.vue') },
      { path: 'backup', name: 'Backup', component: () => import('@/views/backup/BackupView.vue'), meta: { hideHeader: true } },
      { path: 'pattern-room', name: 'PatternRoom', component: () => import('@/views/pattern-room/PatternRoomView.vue'), meta: { hideHeader: true } },
      { path: 'notifications', name: 'Notifications', component: () => import('@/views/notifications/NotificationCenterView.vue'), meta: { hideHeader: true, navExempt: true } },
    ],
  },
  { path: '/:pathMatch(.*)*', redirect: '/dashboard' },
]

// ==================== 移动端路由====================
// 所有路径与 PC 端一致（无前缀），通过设备检测路由级别二选一
const mobileRoutes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'MLogin',
    component: () => import('@/mobile/views/login/MLoginView.vue'),
    meta: { requiresAuth: false },
  },
  {
    path: '/',
    component: () => import('@/mobile/layouts/MobileLayout.vue'),
    meta: { requiresAuth: true },
    children: [
      { path: '', redirect: '/dashboard' },
      { path: 'dashboard', name: 'MDashboard', component: () => import('@/mobile/views/dashboard/DashboardMobile.vue'), meta: { navExempt: true } },
      { path: 'product', name: 'MProduct', component: () => import('@/mobile/views/product/MProductView.vue') },
      { path: 'stock', name: 'MStock', component: () => import('@/mobile/views/stock/MStockView.vue') },
      // 移动端 tab（出货 / 来料登记 / 我的）：入口由 MobileLayout 客户端定义，不在后端导航数据里，
      // 因此显式声明 navExempt，避免非超管用户被守卫重定向回 /dashboard
      { path: 'shipment', name: 'MShipment', component: () => import('@/mobile/views/shipment/MShipmentView.vue'), meta: { navExempt: true } },
      { path: 'customer-order', name: 'MOrders', component: () => import('@/mobile/views/customer-order/MCustomerOrderView.vue') },
      { path: 'profile', name: 'MProfile', component: () => import('@/mobile/views/profile/MProfileView.vue'), meta: { navExempt: true } },
      { path: 'purchase', name: 'MPurchase', component: () => import('@/mobile/views/purchase/MPurchaseView.vue') },
      { path: 'material-calculator', name: 'MMaterialCalculator', component: () => import('@/mobile/views/material-calculator/MMaterialCalculatorView.vue') },
      { path: 'incoming', name: 'MIncoming', component: () => import('@/mobile/views/incoming/MIncomingView.vue'), meta: { navExempt: true } },
      { path: 'production', name: 'MProduction', component: () => import('@/mobile/views/production/MProductionView.vue') },
      { path: 'batch', name: 'MBatch', component: () => import('@/mobile/views/batch/MBatchView.vue') },
      { path: 'case', name: 'MCase', component: () => import('@/mobile/views/case/MCaseView.vue') },
      { path: 'notifications', name: 'MNotifications', component: () => import('@/views/notifications/NotificationCenterView.vue'), meta: { navExempt: true } },
    ],
  },
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

// ==================== 设备自适应路由选择 ====================
const useMobile = isMobileDevice()
const routes: RouteRecordRaw[] = useMobile ? mobileRoutes : pcRoutes

if (import.meta.env.DEV) {
  devLog(`[Router] 设备类型: ${useMobile ? '移动端' : 'PC端'}`)
}

// ==================== 创建路由实例 ====================
const router = createRouter({
  history: createWebHistory(),
  routes,
})

// ==================== Chunk 加载失败自动重试 ====================
const CHUNK_LOAD_KEY = '__router_reload_count'
const CHUNK_LOAD_TS_KEY = '__router_reload_ts'
const MAX_RELOAD = 3
// 计数器有效期：超时后重置，避免服务端恢复后用户因历史计数被永久卡在 loading
const RESET_WINDOW_MS = 60_000

function isChunkLoadError(msg: string): boolean {
  return (
    msg.includes('Failed to fetch dynamically imported module') ||
    msg.includes('Importing a module script failed') ||
    msg.includes('error loading dynamically imported module')
  )
}

router.onError((error, to) => {
  if (!isChunkLoadError(error.message)) return
  const lastTs = Number(sessionStorage.getItem(CHUNK_LOAD_TS_KEY) || 0)
  let count = Number(sessionStorage.getItem(CHUNK_LOAD_KEY) || 0)
  if (!lastTs || Date.now() - lastTs > RESET_WINDOW_MS) count = 0
  count += 1
  if (count > MAX_RELOAD) {
    sessionStorage.removeItem(CHUNK_LOAD_KEY)
    sessionStorage.removeItem(CHUNK_LOAD_TS_KEY)
    console.error('[Router] 动态导入连续失败，请检查网络或服务状态后刷新页面', error)
    return
  }
  sessionStorage.setItem(CHUNK_LOAD_KEY, String(count))
  sessionStorage.setItem(CHUNK_LOAD_TS_KEY, String(Date.now()))
  window.location.href = to.fullPath
})

router.afterEach(() => {
  sessionStorage.removeItem(CHUNK_LOAD_KEY)
  sessionStorage.removeItem(CHUNK_LOAD_TS_KEY)
})

// ==================== 路由守卫：认证 + 权限检查====================
// 判定逻辑见 src/router/navAccess.ts（纯函数，可单测）；此处只负责取 store 并委托。
// 无权限语义的入口（/dashboard、移动端 tab 等）由路由表 meta.navExempt 显式声明。
router.beforeEach((to) => resolveNavAccess(to, useAuthStore()))

export default router
