/**
 * 路由配置 - 响应式自适应
 * 根据设备类型（PC/移动端/Capacitor）自动加载对应路由集
 * 所有路由懒加载，确保每种设备只加载自己需要的代码
 */
import { createRouter, createWebHistory, type RouteRecordRaw, type RouteLocationNormalized } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { isMobileDevice, isCapacitor } from '@/composables/useDevice'

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
      { path: 'dashboard', name: 'Dashboard', component: () => import('@/views/dashboard/DashboardView.vue'), meta: { hideHeader: true } },
      { path: 'order', redirect: '/customer-order' },
      { path: 'order/:id', redirect: '/customer-order' },
      { path: 'product', name: 'Product', component: () => import('@/views/product/ProductListView.vue'), meta: { hideHeader: true } },
      { path: 'stock', name: 'Stock', component: () => import('@/views/stock/StockView.vue'), meta: { hideHeader: true } },
      { path: 'stock-out', name: 'StockOut', component: () => import('@/views/stock/StockOutView.vue'), meta: { hideHeader: true } },
      // 湖北订单 / 外发工序 / 工序预设 拆分为三个独立路由页面：
      // /beile-order 湖北订单；/outsource 外发工序；/outsource/presets 工序预设
      { path: 'beile-order', name: 'BeileOrder', component: () => import('@/views/hubei/HubeiView.vue'), meta: { hideHeader: true } },
      { path: 'outsource', name: 'Outsource', component: () => import('@/views/outsource/OutsourceOrderView.vue'), meta: { hideHeader: true } },
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
      { path: 'notifications', name: 'Notifications', component: () => import('@/views/notifications/NotificationCenterView.vue'), meta: { hideHeader: true } },
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
      { path: 'dashboard', name: 'MDashboard', component: () => import('@/mobile/views/dashboard/DashboardMobile.vue') },
      { path: 'product', name: 'MProduct', component: () => import('@/mobile/views/product/MProductView.vue') },
      { path: 'stock', name: 'MStock', component: () => import('@/mobile/views/stock/MStockView.vue') },
      { path: 'shipment', name: 'MShipment', component: () => import('@/mobile/views/shipment/MShipmentView.vue') },
      { path: 'customer-order', name: 'MOrders', component: () => import('@/mobile/views/customer-order/MCustomerOrderView.vue') },
      { path: 'profile', name: 'MProfile', component: () => import('@/mobile/views/profile/MProfileView.vue') },
      { path: 'purchase', name: 'MPurchase', component: () => import('@/mobile/views/purchase/MPurchaseView.vue') },
      { path: 'material-calculator', name: 'MMaterialCalculator', component: () => import('@/mobile/views/material-calculator/MMaterialCalculatorView.vue') },
      { path: 'incoming', name: 'MIncoming', component: () => import('@/mobile/views/incoming/MIncomingView.vue') },
      { path: 'production', name: 'MProduction', component: () => import('@/mobile/views/production/MProductionView.vue') },
      { path: 'batch', name: 'MBatch', component: () => import('@/mobile/views/batch/MBatchView.vue') },
      { path: 'case', name: 'MCase', component: () => import('@/mobile/views/case/MCaseView.vue') },
      { path: 'notifications', name: 'MNotifications', component: () => import('@/views/notifications/NotificationCenterView.vue') },
    ],
  },
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

// ==================== 设备自适应路由选择 ====================
// 使用 typeof 安全检测 __CAPACITOR_BUILD__，兜底 Vite define 因缓存等原因未正确替换的场景
const _isCapBuild = typeof __CAPACITOR_BUILD__ !== 'undefined' && __CAPACITOR_BUILD__
const useMobile = _isCapBuild || isMobileDevice()
const routes: RouteRecordRaw[] = useMobile ? mobileRoutes : pcRoutes

if (import.meta.env.DEV) {
  console.log(`[Router] 设备类型: ${useMobile ? '移动端' : 'PC端'}${_isCapBuild ? ' (Capacitor)' : ''}`)
}

// ==================== 创建路由实例 ====================
const router = createRouter({
  history: createWebHistory(),
  routes,
})

// ==================== Chunk 加载失败自动重试 ====================
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

router.afterEach(() => {
  sessionStorage.removeItem(CHUNK_LOAD_KEY)
})

// ==================== 路由守卫：认证 + 权限检查====================
router.beforeEach(async (to: RouteLocationNormalized, _from: RouteLocationNormalized) => {
  const authStore = useAuthStore()

  if (to.meta.requiresAuth === false) {
    return true
  }

  if (!authStore.loaded) {
    try {
      // init() 内部已并行加载 fetchUser + fetchNavSections，无需重复调用
      await authStore.init()
    } catch (error) {
      console.error('[Router] 用户初始化失败', error)
      return `/login?redirect=${encodeURIComponent(to.fullPath)}`
    }
  }

  if (!authStore.isLoggedIn) {
    return `/login?redirect=${encodeURIComponent(to.fullPath)}`
  }

  // 权限检查：非超级用户只能访问 filteredNavSections 中可见的路径
  // navSections 未加载时放行（非阻塞门），导航加载完成后侧边栏自然过滤不可见项
  if (authStore.user && !authStore.user.is_super && authStore.navSections.length > 0) {
    const targetPath = '/' + to.path.split('/').filter(Boolean)[0]
    const allowedPaths = authStore.filteredNavSections.flatMap((s) => s.items.map((i) => i.path))
    if (targetPath !== '/dashboard' && targetPath !== '/notifications' && targetPath !== '/' && !allowedPaths.includes(targetPath)) {
      return '/dashboard'
    }
  }

  return true
})

export default router
