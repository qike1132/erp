<template>
  <div v-if="tabStore.tabs.length > 1" class="ht-bar">
    <router-link
      v-for="tab in tabStore.tabs"
      :key="tab.path"
      :to="tab.path"
      :class="['ht-tab', { active: tab.path === tabStore.activePath }]"
    >
      <i v-if="iconMap[tab.icon]" :class="iconMap[tab.icon]" class="ht-tab-icon" />
      <span class="ht-tab-label">{{ tab.title }}</span>
      <button
        class="ht-tab-close"
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
.ht-bar {
  display: flex;
  align-items: center;
  gap: 4px;
  overflow-x: auto;
  flex-shrink: 0;
  width: 100%;
  margin-bottom: 6px;
  margin-top: -10px;
}

.ht-bar::-webkit-scrollbar {
  height: 0;
}

.ht-tab {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 4px 8px;
  border-radius: 7px;
  background: white;
  border: 1px solid var(--color-border-light);
  box-shadow: 0 1px 3px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.06);
  text-decoration: none;
  color: var(--color-text);
  font-size: 12px;
  font-weight: 600;
  white-space: nowrap;
  transition: all 0.3s ease;
  flex-shrink: 0;
}

.ht-tab:hover {
  box-shadow: 0 4px 12px rgba(0,0,0,0.08), 0 12px 32px rgba(0,0,0,0.1);
  transform: translateY(-1px);
  border-color: var(--color-primary-200);
  color: var(--color-primary-600);
}

.ht-tab.active {
  background: linear-gradient(135deg, var(--color-primary-50), var(--color-primary-100));
  border-color: var(--color-primary-300);
  box-shadow: 0 4px 12px rgba(0,0,0,0.08), 0 12px 32px rgba(0,0,0,0.1);
  color: var(--color-primary-700);
}

.ht-tab-icon {
  font-size: 11px;
  flex-shrink: 0;
}

.ht-tab-label {
  max-width: 100px;
  overflow: hidden;
  text-overflow: ellipsis;
}

.ht-tab-close {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  border: none;
  background: transparent;
  color: var(--color-text-muted);
  cursor: pointer;
  font-size: 9px;
  transition: all 0.2s ease;
  flex-shrink: 0;
  padding: 0;
}

.ht-tab-close:hover {
  background: var(--color-danger-50);
  color: var(--color-danger-500);
}
</style>
