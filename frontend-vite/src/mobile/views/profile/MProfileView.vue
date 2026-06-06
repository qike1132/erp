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
        <MListItem title="账号信息" subtitle="查看个人资料">
          <template #icon><div class="m-menu-icon" style="background:rgba(0,113,227,0.08)"><svg viewBox="0 0 24 24" fill="none" stroke="#0071E3" stroke-width="2" width="16" height="16"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg></div></template>
        </MListItem>
        <MListItem title="权限管理" subtitle="查看权限列表" to="/settings">
          <template #icon><div class="m-menu-icon" style="background:rgba(175,82,222,0.08)"><svg viewBox="0 0 24 24" fill="none" stroke="#AF52DE" stroke-width="2" width="16" height="16"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg></div></template>
        </MListItem>
        <MListItem title="网络状态" :subtitle="networkInfo">
          <template #icon><div class="m-menu-icon" :style="{ background: networkConnected ? 'rgba(48,209,88,0.08)' : 'rgba(255,45,85,0.08)' }"><svg viewBox="0 0 24 24" fill="none" :stroke="networkConnected ? '#30D158' : '#FF2D55'" stroke-width="2" width="16" height="16"><path d="M5 12.55a11 11 0 0 1 14.08 0"/><path d="M1.42 9a16 16 0 0 1 21.16 0"/><path d="M8.53 16.11a6 6 0 0 1 6.95 0"/><line x1="12" y1="20" x2="12.01" y2="20"/></svg></div></template>
        </MListItem>
      </MList>

      <MList>
        <MListItem title="退出登录" subtitle="退出当前账号">
          <template #icon><div class="m-menu-icon" style="background:rgba(255,45,85,0.08)"><svg viewBox="0 0 24 24" fill="none" stroke="#FF2D55" stroke-width="2" width="16" height="16"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg></div></template>
          <template #accessory><span /></template>
        </MListItem>
      </MList>

      <div class="m-app-info">
        <span>滨发ERP v2.0</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useAuthStore } from '@/stores/auth'
import MobileNavBar from '@/mobile/layouts/components/MobileNavBar.vue'
import MList from '@/mobile/components/MList.vue'
import MListItem from '@/mobile/components/MListItem.vue'

const authStore = useAuthStore()

const networkConnected = computed(() => navigator.onLine)
const networkInfo = computed(() => networkConnected.value ? '已连接' : '离线')
</script>

<style scoped>
.m-page { display: flex; flex-direction: column; height: 100%; background: var(--m-bg-deep); }
.m-page-body { flex: 1; min-height: 0; overflow-y: auto; padding: var(--m-gap-md); padding-bottom: calc(var(--m-gap-lg) + var(--m-tabbar-safe)); -webkit-overflow-scrolling: touch; }
.m-profile-header { display: flex; align-items: center; gap: 16px; padding: calc(var(--m-safe-top) + 8px) 0 24px; }
.m-profile-avatar { width: 60px; height: 60px; border-radius: 18px; background: var(--m-accent); display: flex; align-items: center; justify-content: center; color: white; font-size: 24px; font-weight: 700; flex-shrink: 0; }
.m-profile-name { font-size: 20px; font-weight: 700; color: var(--m-text-primary); }
.m-profile-role { font-size: 14px; color: var(--m-text-secondary); margin-top: 2px; }
.m-menu-icon { width: 100%; height: 100%; border-radius: 8px; display: flex; align-items: center; justify-content: center; }
.m-app-info { text-align: center; padding: 24px 0 8px; font-size: 13px; color: var(--m-text-tertiary); }
</style>
