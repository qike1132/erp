import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { iconMap } from '@/utils/iconMap'

export interface NavItem {
  path: string
  title: string
  icon?: string
}

export interface NavSection {
  title: string
  items: NavItem[]
}

export function useSidebarNav() {
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

  // 多开分组集合：允许「湖北订单」「采购中心」「核心业务」等分组同时展开，
  // 不再互斥（历史实现用单个 string 记录当前分组，点开一个必然收起另一个）。
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

  return {
    searchQuery,
    filteredSections,
    isActive,
    prefetchRoute,
    resolveIcon,
    toggleSection,
    sectionIsOpen,
  }
}