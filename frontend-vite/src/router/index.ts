import { createRouter, createWebHistory, type RouteRecordRaw, type RouteLocationNormalized } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const isCapacitor = !!import.meta.env.VITE_CAPACITOR

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
      { path: 'dashboard', name: 'Dashboard', component: () => import('@/views/dashboard/DashboardView.vue'), meta: { hideHeader: true } },
      { path: 'order', redirect: '/customer-order' },
      { path: 'order/:id', redirect: '/customer-order' },
      { path: 'product', name: 'Product', component: () => import('@/views/product/ProductListView.vue'), meta: { hideHeader: true } },
      { path: 'stock', name: 'Stock', component: () => import('@/views/stock/StockView.vue'), meta: { hideHeader: true } },
      { path: 'stock-out', name: 'StockOut', component: () => import('@/views/stock/StockOutView.vue'), meta: { hideHeader: true } },
      { path: 'beile-order', name: 'BeileOrder', component: () => import('@/views/beile-order/BeileOrderView.vue'), meta: { hideHeader: true } },
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
      { path: 'notifications', name: 'Notifications', component: () => import('@/views/notifications/NotificationCenterView.vue'), meta: { hideHeader: true } },
    ],
  },
  { path: '/:pathMatch(.*)*', redirect: '/dashboard' },
]

const mobileRoutes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/login/LoginView.vue'),
    meta: { requiresAuth: false },
  },
  {
    path: '/',
    component: () => import('@/mobile/layouts/MobileLayout.vue'),
    meta: { requiresAuth: true },
    children: [
      { path: '', name: 'MDashboard', component: () => import('@/mobile/views/dashboard/DashboardMobile.vue') },
      { path: 'shipment', name: 'MShipment', component: () => import('@/mobile/views/shipment/MShipmentView.vue') },
      { path: 'orders', name: 'MOrders', component: () => import('@/mobile/views/customer-order/MCustomerOrderView.vue') },
      { path: 'profile', name: 'MProfile', component: () => import('@/mobile/views/profile/MProfileView.vue') },
      { path: 'purchase', name: 'MPurchase', component: () => import('@/mobile/views/purchase/MPurchaseView.vue') },
      { path: 'material-calculator', name: 'MMaterialCalculator', component: () => import('@/mobile/views/material-calculator/MMaterialCalculatorView.vue') },
      { path: 'incoming', name: 'MIncoming', component: () => import('@/mobile/views/incoming/MIncomingView.vue') },
      { path: 'production', name: 'MProduction', component: () => import('@/mobile/views/production/MProductionView.vue') },
      { path: 'batch', name: 'MBatch', component: () => import('@/mobile/views/batch/MBatchView.vue') },
      { path: 'case', name: 'MCase', component: () => import('@/mobile/views/case/MCaseView.vue') },
      { path: 'customer-order', name: 'MCustomerOrder', component: () => import('@/mobile/views/customer-order/MCustomerOrderView.vue') },
      { path: 'notifications', name: 'MNotifications', component: () => import('@/views/notifications/NotificationCenterView.vue') },
    ],
  },
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

const routes: RouteRecordRaw[] = isCapacitor ? mobileRoutes : pcRoutes

const router = createRouter({
  history: createWebHistory(),
  routes,
})

// 处理动态导入失败：Vite dev server 连接中断/重启后，浏览器缓存的模块引用失效
// 自动刷新页面以重新获取所有模块（Vue Router 官方推荐方案）
// 增加防循环保护：连续刷新超过阈值后停止，避免服务持续不可达时无限刷新
const CHUNK_LOAD_KEY = '__router_reload_count'
const MAX_RELOAD = 3
function isChunkLoadError(msg: string): boolean {
  return (
    msg.includes('Failed to fetch dynamically imported module') ||
    msg.includes('Importing a module script failed') ||
    msg.includes('error loading dynamically imported module')
  )
}
router.onError((error, to) => {
  if (!isChunkLoadError(error.message)) return
  const count = Number(sessionStorage.getItem(CHUNK_LOAD_KEY) || 0) + 1
  if (count > MAX_RELOAD) {
    sessionStorage.removeItem(CHUNK_LOAD_KEY)
    console.error('[Router] 动态导入连续失败，请检查网络或服务状态后刷新页面', error)
    return
  }
  sessionStorage.setItem(CHUNK_LOAD_KEY, String(count))
  window.location.href = to.fullPath
})
// 导航成功时清零计数器
router.afterEach(() => {
  sessionStorage.removeItem(CHUNK_LOAD_KEY)
})

router.beforeEach(async (to: RouteLocationNormalized, _from: RouteLocationNormalized) => {
  const authStore = useAuthStore()

  if (to.meta.requiresAuth === false) {
    return true
  }

  if (!authStore.loaded) {
    try {
      await authStore.init()
      await authStore.fetchNavSections()
    } catch (error) {
      console.error('[Router] 用户初始化失败:', error)
      return `/login?redirect=${encodeURIComponent(to.fullPath)}`
    }
  }

  if (!authStore.isLoggedIn) {
    return `/login?redirect=${encodeURIComponent(to.fullPath)}`
  }

  // 权限检查：非超级用户只能访问 filteredNavSections 中可见的路径
  if (!isCapacitor && authStore.user && !authStore.user.is_super) {
    const targetPath = '/' + to.path.split('/').filter(Boolean)[0]
    const allowedPaths = authStore.filteredNavSections.flatMap((s) => s.items.map((i) => i.path))
    // dashboard 和 notifications 始终可访问（所有用户均有权查看自己的通知）
    if (targetPath !== '/dashboard' && targetPath !== '/notifications' && !allowedPaths.includes(targetPath)) {
      return '/dashboard'
    }
  }
})

export default router
