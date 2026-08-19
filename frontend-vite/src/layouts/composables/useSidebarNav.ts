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

  const openSection = ref<string | null>(null)
  const isSearching = computed(() => searchQuery.value.trim().length > 0)

  function toggleSection(title: string) {
    openSection.value = openSection.value === title ? null : title
  }

  function sectionIsOpen(title: string) {
    if (isSearching.value) return true
    return openSection.value === title
  }

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