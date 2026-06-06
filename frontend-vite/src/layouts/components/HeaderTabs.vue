<template>
  <div v-if="tabStore.tabs.length > 1" class="ht-bar">
    <router-link
      v-for="tab in tabStore.tabs"
      :key="tab.path"
      :to="tab.path"
      :class="['ht-tab', { active: tab.path === tabStore.activePath }]"
    >
      <i v-if="resolveIcon(tab.icon)" :class="resolveIcon(tab.icon)" class="ht-tab-icon" aria-hidden="true" />
      <span class="ht-tab-label">{{ tab.title }}</span>
      <button
        class="ht-tab-close"
        aria-label="关闭"
        @click.prevent.stop="handleClose(tab.path)"
      >
        <i class="fas fa-xmark" aria-hidden="true" />
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
  'fa-shield-alt': 'fas fa-shield-halved',
  'fa-shopping-cart': 'fas fa-cart-shopping',
}

function resolveIcon(icon: string | undefined): string | null {
  if (!icon) return null
  if (iconMap[icon]) return iconMap[icon]
  if (icon.startsWith('fa-')) return `fas ${icon}`
  return null
}
</script>

<style scoped>
.ht-bar {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px;
  border-radius: 12px;
  background: white;
  border: 1px solid var(--color-border-light);
  box-shadow: 0 1px 3px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.06);
  overflow-x: auto;
  flex-shrink: 0;
}

.ht-bar::-webkit-scrollbar {
  height: 0;
}

.ht-tab {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 8px 14px;
  border: none;
  border-radius: 9px;
  background: transparent;
  text-decoration: none;
  color: var(--color-text-secondary);
  font-size: 13px;
  font-weight: 600;
  white-space: nowrap;
  transition: background 0.3s ease, color 0.3s ease, box-shadow 0.3s ease, transform 0.3s ease;
  flex-shrink: 0;
  cursor: pointer;
}

.ht-tab:hover {
  background: var(--color-primary-50);
  color: var(--color-primary-600);
  box-shadow: 0 4px 12px rgba(0,0,0,0.08);
  transform: translateY(-1px);
}

.ht-tab.active {
  background: linear-gradient(135deg, var(--color-primary-50), var(--color-primary-100));
  color: var(--color-primary-700);
  box-shadow: 0 4px 12px rgba(0,0,0,0.08), 0 2px 8px rgba(91, 141, 239, 0.2);
  transform: translateY(-1px);
}

.ht-tab-icon {
  font-size: 11px;
  flex-shrink: 0;
}

.ht-tab-label {
  min-width: 0;
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
  transition: background 0.2s ease, color 0.2s ease, opacity 0.2s ease;
  flex-shrink: 0;
  padding: 0;
  opacity: 0.6;
}

.ht-tab-close:hover {
  background: var(--color-danger-50);
  color: var(--color-danger-500);
  opacity: 1;
}
</style>
