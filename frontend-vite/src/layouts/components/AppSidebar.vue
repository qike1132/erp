<template>
  <aside :class="['sb-sidebar', { collapsed }]">
    <!-- Header -->
    <div class="sb-header">
      <router-link to="/dashboard" class="sb-logo">
        <img src="/logo_plush.png" alt="东莞玩具" width="70" height="70" />
        <div v-if="!collapsed" class="sb-logo-text">
          <div class="sb-logo-title">东莞协同系统</div>
          <div class="sb-logo-subtitle">供应链管理平台 v2.0</div>
        </div>
      </router-link>
    </div>

    <!-- Navigation -->
    <nav class="sb-nav">
      <div v-for="section in authStore.filteredNavSections" :key="section.title" class="sb-section">
        <div v-if="!collapsed" class="sb-section-title">
          {{ section.title }}
        </div>
        <router-link
          v-for="item in section.items"
          :key="item.path"
          :to="item.path"
          :class="['sb-nav-item', { active: isActive(item.path) }]"
          @pointerenter="prefetchRoute(item.path)"
        >
          <div class="sb-nav-icon" :class="{ 'sb-nav-icon-active': isActive(item.path) }">
            <i :class="resolveIcon(item.icon)" aria-hidden="true" />
          </div>
          <span v-if="!collapsed" class="sb-nav-label">{{ item.title }}</span>
        </router-link>
      </div>
    </nav>
  </aside>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

defineProps<{ collapsed: boolean }>()

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()

const activeBase = computed(() => '/' + route.path.split('/').filter(Boolean)[0])

function isActive(path: string) {
  return activeBase.value === path
}

// 悬停预取：触发目标路由的动态 import，点击时即可命中缓存
const prefetched = new Set<string>()
function prefetchRoute(path: string) {
  if (prefetched.has(path)) return
  prefetched.add(path)
  const { matched } = router.resolve(path)
  for (const r of matched) {
    const c = r.components?.default
    if (typeof c === 'function') {
      ;(c as () => Promise<unknown>)().catch(() => {})
    }
  }
}

import { iconMap } from '@/utils/iconMap'

function resolveIcon(icon: string | undefined): string {
  if (!icon) return 'fas fa-circle'
  if (iconMap[icon]) return iconMap[icon]
  if (icon.startsWith('fa-')) return `fas ${icon}`
  return 'fas fa-circle'
}
</script>

<style scoped>
/* ===== Sidebar Card ===== */
.sb-sidebar {
  width: 230px;
  min-width: 68px;
  flex-shrink: 0;
  background: white;
  border-radius: 18px;
  border: 1px solid var(--color-border-light);
  box-shadow: 0 1px 3px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.06);
  display: flex;
  flex-direction: column;
  transition: width 0.4s cubic-bezier(0.4, 0, 0.2, 1), box-shadow 0.4s cubic-bezier(0.4, 0, 0.2, 1), transform 0.4s cubic-bezier(0.4, 0, 0.2, 1);
  overflow: hidden;
  height: calc(100vh - 8px);
  margin: 4px 12px;
}

.sb-sidebar:hover {
  box-shadow: 0 4px 12px rgba(0,0,0,0.06);
  transform: translateY(-2px);
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
  width: 70px;
  height: 70px;
  border-radius: 13px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.06);
  flex-shrink: 0;
}

.sb-logo-text {
  min-width: 0;
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
  color: var(--color-heading);
  font-weight: 800;
  font-size: 14px;
  position: relative;
  background: white;
  border: 1px solid var(--color-border-light);
  box-shadow: 0 1px 3px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.06);
  transition: background 0.3s ease, border-color 0.3s ease, box-shadow 0.3s ease, transform 0.3s ease;
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
  transition: color 0.3s ease, background 0.3s ease;
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
