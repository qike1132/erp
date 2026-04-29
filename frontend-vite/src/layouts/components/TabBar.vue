<template>
  <div v-if="tabStore.tabs.length > 0" class="tb-bar">
    <router-link
      v-for="tab in tabStore.tabs"
      :key="tab.path"
      :to="tab.path"
      :class="['tb-tab', { active: tab.path === tabStore.activePath }]"
    >
      <i v-if="iconMap[tab.icon]" :class="iconMap[tab.icon]" class="tb-tab-icon" />
      <span class="tb-tab-label">{{ tab.title }}</span>
      <button
        class="tb-tab-close"
        @click.prevent.stop="handleClose(tab.path)"
      >
        <i class="fas fa-xmark" />
      </button>
    </router-link>
  </div>
</template>

<script setup lang="ts">
import { useRouter } from 'vue-router'
import { useTabStore } from '@/stores/tabs'

const tabStore = useTabStore()
const router = useRouter()

function handleClose(path: string) {
  const next = tabStore.close(path)
  if (next) router.push(next)
}

const iconMap: Record<string, string> = {
  'fa-store': 'fas fa-store',
  'fa-truck': 'fas fa-truck',
  'fa-calculator': 'fas fa-calculator',
  'fa-box': 'fas fa-box',
  'fa-box-open': 'fas fa-box-open',
  'fa-file-invoice': 'fas fa-file-invoice',
  'fa-shipping-fast': 'fas fa-shipping-fast',
  'fa-yen-sign': 'fas fa-yen-sign',
  'fa-warehouse': 'fas fa-warehouse',
  'fa-chart-bar': 'fas fa-chart-bar',
  'fa-industry': 'fas fa-industry',
  'fa-users-cog': 'fas fa-users-cog',
  'fa-building': 'fas fa-building',
  'fa-clipboard-check': 'fas fa-clipboard-check',
  dashboard: 'fas fa-gauge',
  order: 'fas fa-cart-shopping',
  product: 'fas fa-box',
  stock: 'fas fa-warehouse',
  customer: 'fas fa-user',
  supplier: 'fas fa-truck',
  approval: 'fas fa-clipboard-check',
  purchase: 'fas fa-store',
  material: 'fas fa-cubes',
  batch: 'fas fa-table-cells',
  production: 'fas fa-industry',
  report: 'fas fa-chart-bar',
  user: 'fas fa-user',
  permission: 'fas fa-ticket',
  settings: 'fas fa-gear',
  'ocr-import': 'fas fa-upload',
  case: 'fas fa-box',
  'material-calculator': 'fas fa-list',
}
</script>

<style scoped>
.tb-bar {
  display: flex;
  align-items: center;
  padding: 6px 12px;
  border-bottom: 1px solid var(--color-border-light);
  background: rgba(255, 255, 255, 0.7);
  backdrop-filter: blur(8px);
  flex-shrink: 0;
  gap: 4px;
  overflow-x: auto;
}

.tb-bar::-webkit-scrollbar {
  height: 0;
}

.tb-tab {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 5px 10px;
  border-radius: 9px;
  background: white;
  border: 1px solid var(--color-border-light);
  box-shadow: 0 1px 3px rgba(0,0,0,0.04);
  text-decoration: none;
  color: var(--color-text);
  font-size: 13px;
  font-weight: 600;
  white-space: nowrap;
  transition: all 0.2s ease;
  flex-shrink: 0;
}

.tb-tab:hover {
  border-color: var(--color-primary-200);
  box-shadow: 0 2px 6px rgba(0,0,0,0.06);
  transform: translateY(-1px);
}

.tb-tab.active {
  background: var(--color-primary-50);
  border-color: var(--color-primary-400);
  color: var(--color-primary-700);
  box-shadow: 0 2px 6px rgba(0,0,0,0.06);
}

.tb-tab-icon {
  font-size: 12px;
  flex-shrink: 0;
}

.tb-tab.active .tb-tab-icon {
  color: var(--color-primary-600);
}

.tb-tab-label {
  max-width: 120px;
  overflow: hidden;
  text-overflow: ellipsis;
}

.tb-tab-close {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  border: none;
  background: transparent;
  color: var(--color-text-secondary);
  cursor: pointer;
  font-size: 10px;
  transition: all 0.2s ease;
  flex-shrink: 0;
  padding: 0;
}

.tb-tab-close:hover {
  background: var(--color-danger-50);
  color: var(--color-danger-500);
}

.tb-tab.active .tb-tab-close:hover {
  background: var(--color-danger-100);
}
</style>
