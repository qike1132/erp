<template>
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
            <FontAwesomeIcon :icon="resolveIcon(item.icon)" aria-hidden="true" />
          </div>
        </router-link>
      </div>
    </template>

    <!-- 展开态：搜索框 + 手风琴折叠菜单 -->
    <template v-else>
      <div class="sb-search">
        <span class="sb-search-icon" aria-hidden="true" />
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
          <span class="sb-chevron" aria-hidden="true" />
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
              <FontAwesomeIcon :icon="resolveIcon(item.icon)" aria-hidden="true" />
            </div>
            <span class="sb-nav-label">{{ item.title }}</span>
          </router-link>
        </div>
      </div>
    </template>
  </nav>
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

const searchQuery = ref('')

const filteredSections = computed(() => {
  const q = searchQuery.value.trim().toLowerCase()
  if (!q) return authStore.filteredNavSections
  return authStore.filteredNavSections
    .map((s) => ({ ...s, items: s.items.filter((i) => i.title.toLowerCase().includes(q)) }))
    .filter((s) => s.items.length > 0)
})

const openSections = ref<Set<string>>(new Set())
const isSearching = computed(() => searchQuery.value.trim().length > 0)

function toggleSection(title: string) {
  const next = new Set(openSections.value)
  if (next.has(title)) {
    next.delete(title)
  } else {
    next.add(title)
  }
  // 整体替换而非原地 mutate，确保依赖 openSections.value 的渲染可靠更新
  openSections.value = next
}

function sectionIsOpen(title: string) {
  if (isSearching.value) return true
  return openSections.value.has(title)
}

watch(
  () => [route.path, authStore.filteredNavSections],
  () => {
    if (isSearching.value) return
    for (const s of authStore.filteredNavSections) {
      if (s.items.some((i) => isActive(i.path))) {
        // 多开模式：只补开当前分组，不关闭用户已手动展开的其它分组
        if (!openSections.value.has(s.title)) {
          const next = new Set(openSections.value)
          next.add(s.title)
          openSections.value = next
        }
        return
      }
    }
  },
  { immediate: true },
)
</script>

<style scoped>
.sb-nav {
  flex: 1;
  padding: 14px 12px;
  overflow-y: auto;
  scrollbar-width: none;
  -ms-overflow-style: none;
}
.sb-nav::-webkit-scrollbar { display: none; }
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
.sb-search-input::placeholder { color: var(--color-text-tertiary); }
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
.sb-section { margin-bottom: 8px; }
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
  transform: rotate(-45deg);
  transition: transform 0.25s ease;
}
.sb-section-header.open .sb-chevron { transform: rotate(45deg); }
.sb-section-body { padding-left: 4px; }
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
.sb-nav-item.active {
  background: linear-gradient(135deg, var(--color-primary-50), var(--color-primary-100));
  border-color: var(--color-primary-300);
  box-shadow: 0 4px 12px rgba(0,0,0,0.08), 0 12px 32px rgba(0,0,0,0.1);
}
.sb-nav-item.active .sb-nav-label { color: var(--color-primary-700); }
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
.sb-nav-label { transition: color 0.3s ease; }
</style>