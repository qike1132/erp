<template>
  <aside :class="['sb-sidebar', { collapsed }]">
    <!-- Header -->
    <div class="sb-header">
      <router-link to="/dashboard" class="sb-logo">
        <img src="/logo_plush.png" alt="滨发玩具" />
        <div v-if="!collapsed" class="sb-logo-text">
          <div class="sb-logo-title">滨发协同系统</div>
          <div class="sb-logo-subtitle">供应链管理平台 v2.0</div>
        </div>
      </router-link>
    </div>

    <!-- Navigation -->
    <nav class="sb-nav">
      <div v-for="section in authStore.navSections" :key="section.title" class="sb-section">
        <div v-if="!collapsed" class="sb-section-title">
          {{ section.title }}
        </div>
        <router-link
          v-for="item in section.items"
          :key="item.path"
          :to="item.path"
          :class="['sb-nav-item', { active: isActive(item.path) }]"
        >
          <div class="sb-nav-icon" :class="{ 'sb-nav-icon-active': isActive(item.path) }">
            <i :class="iconMap[item.icon ?? ''] ?? 'fas fa-file'" />
          </div>
          <span v-if="!collapsed" class="sb-nav-label">{{ item.title }}</span>
        </router-link>
      </div>
    </nav>
  </aside>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

defineProps<{ collapsed: boolean }>()

const route = useRoute()
const authStore = useAuthStore()

const activeBase = computed(() => '/' + route.path.split('/').filter(Boolean)[0])

function isActive(path: string) {
  return activeBase.value === path
}

const iconMap: Record<string, string> = {
  'fa-store': 'fas fa-store',
  'fa-truck': 'fas fa-truck',
  'fa-truck-loading': 'fas fa-truck-loading',
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
/* ===== Sidebar Card ===== */
.sb-sidebar {
  width: 280px;
  min-width: 68px;
  flex-shrink: 0;
  background: white;
  border-radius: 18px;
  border: 1px solid var(--color-border-light);
  box-shadow: 0 1px 3px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.06);
  display: flex;
  flex-direction: column;
  transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);
  overflow: hidden;
  height: calc(100vh - 24px);
  margin: 12px;
}

.sb-sidebar:hover {
  box-shadow: 0 12px 36px rgba(0,0,0,0.08), 0 48px 144px rgba(0,0,0,0.12);
  transform: translateY(-6px);
}

.sb-sidebar.collapsed {
  width: 68px;
}

.sb-sidebar.collapsed .sb-header {
  padding: 16px 12px;
}

.sb-sidebar.collapsed .sb-logo {
  justify-content: center;
  gap: 0;
}

.sb-sidebar.collapsed .sb-logo img {
  width: 40px;
  height: 40px;
}

.sb-sidebar.collapsed .sb-nav-item {
  justify-content: center;
  padding: 10px;
  gap: 0;
}

.sb-sidebar.collapsed .sb-nav-icon {
  width: 36px;
  height: 36px;
  border-radius: 10px;
}

.sb-sidebar.collapsed .sb-section {
  margin-bottom: 8px;
}

/* ===== Header ===== */
.sb-header {
  padding: 24px 20px 18px;
  border-bottom: 1px solid var(--color-border-light);
  flex-shrink: 0;
}

.sb-logo {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 0;
  text-decoration: none;
  cursor: pointer;
  transition: opacity 0.2s ease;
}

.sb-logo:hover {
  opacity: 0.8;
}

.sb-logo img {
  width: 48px;
  height: 48px;
  border-radius: 13px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.06);
  flex-shrink: 0;
}

.sb-logo-title {
  font-size: 17px;
  font-weight: 700;
  color: var(--color-text);
  line-height: 1.3;
}

.sb-logo-subtitle {
  font-size: 11px;
  color: var(--color-text-secondary);
  font-weight: 500;
  line-height: 1.4;
}

/* ===== Navigation ===== */
.sb-nav {
  flex: 1;
  padding: 14px 12px;
  overflow-y: auto;
  scrollbar-width: none;
  -ms-overflow-style: none;
}
.sb-nav::-webkit-scrollbar {
  display: none;
}

.sb-section {
  margin-bottom: 16px;
}

.sb-section-title {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.05em;
  color: var(--color-text-secondary);
  padding: 0 8px 6px;
  margin-bottom: 4px;
}

.sb-nav-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 10px;
  margin-bottom: 4px;
  border-radius: 12px;
  text-decoration: none;
  color: var(--color-text);
  font-weight: 600;
  font-size: 14px;
  position: relative;
  background: white;
  border: 1px solid var(--color-border-light);
  box-shadow: 0 1px 3px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.06);
  transition: all 0.3s ease;
}

.sb-nav-item:hover {
  box-shadow: 0 4px 12px rgba(0,0,0,0.08), 0 12px 32px rgba(0,0,0,0.1);
  transform: translateY(-1px);
  border-color: var(--color-primary-200);
}

.sb-nav-item:hover .sb-nav-icon {
  color: var(--color-primary-500);
  background: var(--color-primary-50);
}

.sb-nav-item:hover .sb-nav-label {
  color: var(--color-primary-600);
}

.sb-nav-item.active {
  background: linear-gradient(135deg, var(--color-primary-50), var(--color-primary-100));
  border-color: var(--color-primary-300);
  box-shadow: 0 4px 12px rgba(0,0,0,0.08), 0 12px 32px rgba(0,0,0,0.1);
}

.sb-nav-item.active .sb-nav-label {
  color: var(--color-primary-700);
}

.sb-nav-icon {
  width: 32px;
  height: 32px;
  border-radius: 9px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  color: var(--color-text-secondary);
  background: var(--color-surface);
  flex-shrink: 0;
  transition: all 0.3s ease;
}

.sb-nav-icon-active {
  background: linear-gradient(135deg, var(--color-primary-100), var(--color-primary-200));
  color: var(--color-primary-600);
}

.sb-nav-label {
  transition: color 0.3s ease;
}

/* ===== Mobile Responsive ===== */
@media (max-width: 767px) {
  .sb-sidebar {
    position: fixed;
    top: 0;
    left: 0;
    z-index: 300;
    height: 100vh;
    margin: 0;
    border-radius: 0;
  }

  .sb-sidebar.collapsed {
    width: 0;
    min-width: 0;
    overflow: hidden;
    border-radius: 0;
    box-shadow: none;
  }
}
</style>
