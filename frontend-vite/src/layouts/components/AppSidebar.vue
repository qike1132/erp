<template>
  <aside :class="['sb-sidebar', { collapsed }]">
    <!-- Header -->
    <div class="sb-header">
      <router-link to="/dashboard" class="sb-logo">
        <img src="/logo_plush.png" alt="东莞玩具" width="70" height="70" />
        <div v-if="!collapsed" class="sb-logo-text">
          <div class="sb-logo-title">滨发协同系统</div>
          <div class="sb-logo-subtitle">供应链管理平台 v2.0</div>
        </div>
      </router-link>
    </div>

    <!-- Navigation -->
    <nav class="sb-nav">
      <!-- 折叠态：仅展示图标 -->
      <template v-if="collapsed">
        <div v-for="section in filteredSections" :key="'c' + section.title" class="sb-section">
          <router-link
            v-for="item in section.items"
            :key="item.path"
            :to="item.path"
            :class="['sb-nav-item', 'sb-nav-item-icon-only', { active: isActive(item.path) }]"
            @pointerenter="prefetchRoute(item.path)"
          >
            <div class="sb-nav-icon" :class="{ 'sb-nav-icon-active': isActive(item.path) }">
              <i :class="resolveIcon(item.icon)" aria-hidden="true" />
            </div>
          </router-link>
        </div>
      </template>

      <!-- 展开态：搜索框 + 手风琴折叠菜单 -->
      <template v-else>
        <div class="sb-search">
          <span class="sb-search-icon" aria-hidden="true"></span>
          <input
            v-model="searchQuery"
            type="text"
            class="sb-search-input"
            placeholder="搜索菜单..."
            aria-label="搜索菜单"
          />
        </div>

        <div v-for="section in filteredSections" :key="section.title" class="sb-section">
          <button
            type="button"
            class="sb-section-header"
            :class="{ open: sectionIsOpen(section.title) }"
            :aria-expanded="sectionIsOpen(section.title)"
            @click="toggleSection(section.title)"
          >
            <span class="sb-section-title">{{ section.title }}</span>
            <span class="sb-chevron" aria-hidden="true"></span>
          </button>
          <div v-show="sectionIsOpen(section.title)" class="sb-section-body">
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
              <span class="sb-nav-label">{{ item.title }}</span>
            </router-link>
          </div>
        </div>
      </template>
    </nav>
  </aside>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { iconMap } from '@/utils/iconMap'

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

function resolveIcon(icon: string | undefined): string {
  if (!icon) return 'fas fa-circle'
  if (iconMap[icon]) return iconMap[icon]
  if (icon.startsWith('fa-')) return `fas ${icon}`
  return 'fas fa-circle'
}

/* ===== 搜索 ===== */
const searchQuery = ref('')

const filteredSections = computed(() => {
  const q = searchQuery.value.trim().toLowerCase()
  if (!q) return authStore.filteredNavSections
  return authStore.filteredNavSections
    .map((s) => ({ ...s, items: s.items.filter((i) => i.title.toLowerCase().includes(q)) }))
    .filter((s) => s.items.length > 0)
})

/* ===== 手风琴折叠（同一时间仅展开一组） ===== */
const openSection = ref<string | null>(null)
const isSearching = computed(() => searchQuery.value.trim().length > 0)

function toggleSection(title: string) {
  openSection.value = openSection.value === title ? null : title
}

function sectionIsOpen(title: string) {
  if (isSearching.value) return true // 搜索时自动展开所有命中分组
  return openSection.value === title
}

// 路由变化 / 导航加载后，自动展开当前菜单所在分组
watch(
  () => [route.path, authStore.filteredNavSections],
  () => {
    if (isSearching.value) return
    for (const s of authStore.filteredNavSections) {
      if (s.items.some((i) => isActive(i.path))) {
        openSection.value = s.title
        return
      }
    }
  },
  { immediate: true },
)
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

/* ===== 搜索框 ===== */
.sb-search {
  position: relative;
  margin-bottom: 12px;
}

.sb-search-input {
  width: 100%;
  box-sizing: border-box;
  padding: 8px 12px 8px 34px;
  border: 1px solid var(--color-border-light);
  border-radius: 10px;
  font-size: 13px;
  color: var(--color-text);
  background: var(--color-surface);
  outline: none;
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
}

.sb-search-input::placeholder {
  color: var(--color-text-tertiary);
}

.sb-search-input:focus {
  border-color: var(--color-primary-300);
  box-shadow: 0 0 0 3px var(--color-primary-50);
}

.sb-search-icon {
  position: absolute;
  left: 12px;
  top: 50%;
  transform: translateY(-50%);
  width: 13px;
  height: 13px;
  border: 2px solid var(--color-text-secondary);
  border-radius: 50%;
  pointer-events: none;
}

.sb-search-icon::after {
  content: '';
  position: absolute;
  width: 7px;
  height: 2px;
  background: var(--color-text-secondary);
  right: -5px;
  bottom: -2px;
  transform: rotate(45deg);
  border-radius: 2px;
}

/* ===== 分组（手风琴） ===== */
.sb-section {
  margin-bottom: 8px;
}

.sb-section-header {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 10px;
  margin-bottom: 4px;
  border-radius: 12px;
  border: 1px solid var(--color-border-light);
  background: white;
  color: var(--color-text-secondary);
  font-weight: 700;
  font-size: 14px;
  letter-spacing: 0;
  cursor: pointer;
  transition: color 0.2s ease, border-color 0.2s ease, background 0.2s ease;
}

.sb-section-header:hover {
  color: var(--color-primary-600);
  border-color: var(--color-primary-200);
  background: var(--color-primary-50);
}

.sb-section-header.open {
  color: var(--color-primary-700);
  border-color: var(--color-primary-300);
  background: var(--color-primary-50);
}

.sb-section-title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sb-chevron {
  flex-shrink: 0;
  width: 8px;
  height: 8px;
  margin-right: 2px;
  border-right: 2px solid currentColor;
  border-bottom: 2px solid currentColor;
  transform: rotate(-45deg); /* 指向右，表示可展开 */
  transition: transform 0.25s ease;
}

.sb-section-header.open .sb-chevron {
  transform: rotate(45deg); /* 指向下，表示已展开 */
}

.sb-section-body {
  padding-left: 4px;
}

/* ===== 菜单项 ===== */
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
