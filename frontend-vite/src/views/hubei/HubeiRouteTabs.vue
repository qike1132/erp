<template>
  <div class="hu-tabs-bar">
    <UiTabs :model-value="activeTab" @update:model-value="switchTab">
      <UiTabTrigger v-if="canOutsource" value="orders" :active="activeTab === 'orders'">
        <FontAwesomeIcon icon="clipboard-list" aria-hidden="true" /> 外发工序
      </UiTabTrigger>
      <UiTabTrigger v-if="canOutsource" value="presets" :active="activeTab === 'presets'">
        <FontAwesomeIcon icon="cogs" aria-hidden="true" /> 工序预设
      </UiTabTrigger>
    </UiTabs>
  </div>
</template>

<script setup lang="ts">
/**
 * HubeiRouteTabs.vue — 外发工序 / 工序预设 两个页面的 Tab 导航
 *
 * 湖北外发拆分为两个独立路由/页面，本组件作为页面顶部的 Tab 导航：
 * 切换 Tab 即跳转对应路由（湖北订单页 /beile-order 不渲染本组件）。
 *
 * - 路由：外发工序 → /outsource；工序预设 → /outsource/presets
 * - 激活态：根据当前路由路径推导，不依赖内部状态（每个页面都渲染本组件）
 * - 权限：两个 Tab 均需 outsource_manage / outsource_view；无权限的 Tab 直接隐藏
 */
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import UiTabs from '@/components/ui/UiTabs.vue'
import UiTabTrigger from '@/components/ui/UiTabTrigger.vue'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()

const canOutsource = computed(() => authStore.hasAnyPermission(['outsource_manage', 'outsource_view']))

const TAB_PATHS: Record<string, string> = {
  orders: '/outsource',
  presets: '/outsource/presets',
}

/** 根据当前路由推导激活 Tab */
const activeTab = computed<string>(() => {
  if (route.path.startsWith('/outsource/presets')) return 'presets'
  return 'orders'
})

function switchTab(value: string) {
  const path = TAB_PATHS[value]
  if (path && path !== route.path) {
    router.push(path)
  }
}
</script>

<style scoped>
.hu-tabs-bar {
  padding: 4px 16px 0;
  display: flex;
  align-items: center;
}
.hu-tabs-bar :deep(.ui-tab-group) {
  margin-bottom: 0;
}
</style>
