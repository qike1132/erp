<template>
  <div class="m-page">
    <MobileNavBar title="我的" />
    <div class="m-page-body">
      <div class="m-profile-header">
        <div class="m-profile-avatar">
          {{ (authStore.user?.username || 'U').charAt(0).toUpperCase() }}
        </div>
        <div class="m-profile-info">
          <div class="m-profile-name">{{ authStore.user?.username || '用户' }}</div>
          <div class="m-profile-role">{{ authStore.user?.is_super ? '超级管理员' : '普通用户' }}</div>
        </div>
      </div>

      <MList header="设置" style="margin-bottom: 16px">
        <!-- 2026-11-23：移动端通知中心路由已下线，「通知中心」入口同步移除，
             避免点击后被通配路由兜回同页面。 -->
        <MListItem title="网络状态" :subtitle="networkInfo">
          <template #icon><div class="m-menu-icon" :style="{ background: networkConnected ? 'rgba(48,209,88,0.08)' : 'rgba(255,45,85,0.08)' }"><svg viewBox="0 0 24 24" fill="none" :stroke="networkConnected ? '#30D158' : '#FF2D55'" stroke-width="2" width="16" height="16"><path d="M5 12.55a11 11 0 0 1 14.08 0" /><path d="M1.42 9a16 16 0 0 1 21.16 0" /><path d="M8.53 16.11a6 6 0 0 1 6.95 0" /><line x1="12" y1="20" x2="12.01" y2="20" /></svg></div></template>
        </MListItem>
      </MList>

      <MList>
        <MListItem title="退出登录" subtitle="退出当前账号" clickable @click="onLogout">
          <template #icon><div class="m-menu-icon" style="background:rgba(255,45,85,0.08)"><svg viewBox="0 0 24 24" fill="none" stroke="#FF2D55" stroke-width="2" width="16" height="16"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" /><polyline points="16 17 21 12 16 7" /><line x1="21" y1="12" x2="9" y2="12" /></svg></div></template>
          <template #accessory><span /></template>
        </MListItem>
      </MList>

      <div class="m-app-info">
        <span>{{ APP_NAME }} {{ APP_VERSION }}</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { APP_NAME, APP_VERSION } from '@/constants/brand'
import { authApi } from '@/api'
import { useAuthStore } from '@/stores/auth'
import MobileNavBar from '@/mobile/layouts/components/MobileNavBar.vue'
import MList from '@/mobile/components/MList.vue'
import MListItem from '@/mobile/components/MListItem.vue'

const authStore = useAuthStore()
const router = useRouter()

// F-FE-MOBILE-09：computed(()=>navigator.onLine) 的来源非响应式，首渲染后
// 永久缓存——离线仍显示「已连接」。改由 online/offline 事件驱动响应式 ref。
const networkConnected = ref(navigator.onLine)
const networkInfo = computed(() => networkConnected.value ? '已连接' : '离线')
const _updateNet = () => { networkConnected.value = navigator.onLine }
window.addEventListener('online', _updateNet)
window.addEventListener('offline', _updateNet)
onUnmounted(() => {
  window.removeEventListener('online', _updateNet)
  window.removeEventListener('offline', _updateNet)
})

// 原「退出登录」项既无 `to` 也无 `@click`，而 MListItem 只处理 `to`，
// 点击什么都不发生 —— **移动端根本没法登出**（共用终端下用户以为已退出、会话仍在）。
// 与桌面端 DashboardView.handleLogout 同款：接口失败也照样清本地态并跳登录页。
// N-30（2026-11-21 审计）：防重入——连点两次会并发两个 /auth/logout 且重复 router.replace
let _loggingOut = false
async function onLogout() {
  if (_loggingOut) return
  _loggingOut = true
  try {
    await authApi.logout()
  } catch {
    // 接口失败也要清本地态并跳登录页；这里显式吞掉，避免 unhandledrejection
    // 冒到全局监控（本地会话已在 finally 清干净）。
  } finally {
    authStore.logout()
    router.replace('/login')
    _loggingOut = false
  }
}
</script>

<style scoped>
.m-page { display: flex; flex-direction: column; height: 100%; background: var(--m-bg-deep); }
.m-page-body { flex: 1; min-height: 0; overflow-y: auto; padding: var(--m-gap-md); padding-bottom: calc(var(--m-gap-lg) + var(--m-tabbar-safe)); -webkit-overflow-scrolling: touch; }
.m-profile-header { display: flex; align-items: center; gap: 16px; padding: calc(var(--m-safe-top) + 8px) 0 24px; }
.m-profile-avatar { width: 60px; height: 60px; border-radius: 18px; background: var(--m-accent); display: flex; align-items: center; justify-content: center; color: white; font-size: var(--fs-heading-2); font-weight: 700; flex-shrink: 0; }
.m-profile-name { font-size: var(--fs-heading-3); font-weight: 700; color: var(--m-text-primary); }
.m-profile-role { font-size: var(--fs-body-sm); color: var(--m-text-secondary); margin-top: 2px; }
.m-menu-icon { width: 100%; height: 100%; border-radius: 8px; display: flex; align-items: center; justify-content: center; }
.m-app-info { text-align: center; padding: 24px 0 8px; font-size: 13px; color: var(--m-text-tertiary); }
</style>
