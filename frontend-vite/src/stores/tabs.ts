import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { useAuthStore } from './auth'

export interface TabItem {
  path: string
  title: string
  icon: string
}

const MAX_TABS = 15

export const useTabStore = defineStore('tabs', () => {
  const tabs = ref<TabItem[]>([])
  const activePath = ref('/dashboard')

  const activeTab = computed(() => tabs.value.find(t => t.path === activePath.value))

  /** 从侧边栏 navSections 中查找标题和图标 */
  function findNavInfo(path: string): { title: string; icon: string } {
    const authStore = useAuthStore()
    for (const section of authStore.navSections) {
      const item = section.items.find(i => i.path === path)
      if (item) {
        return { title: item.title, icon: item.icon ?? '' }
      }
    }
    return { title: path.split('/').filter(Boolean).pop() ?? path, icon: '' }
  }

  /** 路由切换时调用：添加或激活 tab */
  function addOrActivate(path: string) {
    if (!path || path === '/login') return

    // 返回首页时清空所有标签
    if (path === '/dashboard') {
      tabs.value = []
      activePath.value = path
      return
    }

    activePath.value = path

    const exists = tabs.value.some(t => t.path === path)
    if (exists) return

    const { title, icon } = findNavInfo(path)
    tabs.value.push({ path, title, icon })

    // 超出上限时移除最早的 tab
    if (tabs.value.length > MAX_TABS) {
      tabs.value.shift()
    }
  }

  /** 关闭 tab，返回下一个应激活的路径 */
  function close(path: string): string | null {
    const idx = tabs.value.findIndex(t => t.path === path)
    if (idx === -1) return null

    tabs.value.splice(idx, 1)

    // 如果关闭的是当前激活的 tab，切换到相邻 tab
    if (activePath.value === path) {
      if (tabs.value.length === 0) return '/dashboard'
      const next = tabs.value[Math.min(idx, tabs.value.length - 1)]
      return next.path
    }
    return null
  }

  /** 关闭其他 tab */
  function closeOthers(path: string) {
    tabs.value = tabs.value.filter(t => t.path === path)
  }

  /** 登出时清空 */
  function clear() {
    tabs.value = []
    activePath.value = '/dashboard'
  }

  return { tabs, activePath, activeTab, addOrActivate, close, closeOthers, clear }
})
