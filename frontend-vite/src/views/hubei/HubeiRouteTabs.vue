<template>
  <div class="hu-tabs-bar">
    <UiTabs :model-value="activeTab" @update:model-value="switchTab">
      <UiTabTrigger v-if="canOutsource" value="orders" :active="activeTab === 'orders'">
        <FontAwesomeIcon icon="clipboard-list" aria-hidden="true" /> 外发进度
      </UiTabTrigger>
      <UiTabTrigger v-if="canOutsource" value="shipments" :active="activeTab === 'shipments'">
        <FontAwesomeIcon icon="truck-fast" aria-hidden="true" /> 发货单
      </UiTabTrigger>
      <UiTabTrigger v-if="canManagePresets" value="presets" :active="activeTab === 'presets'">
        <FontAwesomeIcon icon="cogs" aria-hidden="true" /> 工序预设
      </UiTabTrigger>
    </UiTabs>
  </div>
</template>

<script setup lang="ts">
/**
 * HubeiRouteTabs.vue — 外发进度 / 发货单 / 工序预设 三个页面的 Tab 导航
 *
 * 湖北外发拆分为三个独立路由/页面，本组件作为页面顶部的 Tab 导航：
 * 切换 Tab 即跳转对应路由（湖北订单页 /beile-order 不渲染本组件）。
 * 方案B（docs/outsource/外发模块TAB重构方案.md）：TAB 顺序为
 * 外发进度 → 发货单 → 工序预设，裸路径 /outsource（侧边栏入口）落在首个 TAB 外发进度。
 *
 * - 路由：外发进度 → /outsource；发货单 → /outsource/shipments；工序预设 → /outsource/presets
 * - 「发货单」对全部角色同名（贝乐在此页确认收货，页面主体即发货单台账）
 * - 「工序预设」按细粒度权限码 outsource_preset_manage 显示（原先按用户名隐藏，见下方注释）
 * - 激活态：根据当前路由路径推导，不依赖内部状态（每个页面都渲染本组件）
 * - 权限：三个 Tab 均需 outsource_manage / outsource_view；无权限的 Tab 直接隐藏
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

/**
 * 工序预设维护：按新增的细粒度权限码 outsource_preset_manage 门控。
 *
 * 历史问题（缺陷 #5）：此处原先用 isBeileUser(username) 隐藏 Tab —— 因为贝乐本来就
 * 持有 outsource_manage（scripts/add_outsource_nav.py 按 beile_order_view 批量授予），
 * 而预设页写接口只认 outsource_manage，放开 Tab 就等于让贝乐增删工序预设。现在写接口
 * 已改认 outsource_preset_manage（不随 outsource_manage 继承），用户名门控下线。
 *
 * 仍需 canOutsource：预设页的**读**接口要 outsource_view，只给预设维护权的人打开
 * 本 Tab 也只会看到 403。
 */
const canManagePresets = computed(
  () => canOutsource.value && authStore.hasPermission('outsource_preset_manage'),
)

const TAB_PATHS: Record<string, string> = {
  orders: '/outsource',
  shipments: '/outsource/shipments',
  presets: '/outsource/presets',
}

/** 根据当前路由推导激活 Tab */
const activeTab = computed<string>(() => {
  if (route.path.startsWith('/outsource/shipments')) return 'shipments'
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
