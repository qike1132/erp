/**
 * usePatternRoomLayout — 打样间响应式布局 Hook
 *
 * 监听窄屏媒体查询（< 1024px），驱动左侧列表在「固定侧栏」与「抽屉」间切换。
 * 逻辑自 PatternRoomView.vue 原样搬移。
 */
import { ref, onMounted, onUnmounted } from 'vue'

export function usePatternRoomLayout() {
  /** 是否窄屏（< 1024px，左侧改为抽屉） */
  const isNarrow = ref(false)
  /** 窄屏抽屉展开状态 */
  const drawerOpen = ref(false)

  let _mediaQuery: MediaQueryList | null = null
  function updateNarrow() {
    isNarrow.value = _mediaQuery?.matches ?? false
  }

  onMounted(() => {
    if (typeof window !== 'undefined') {
      _mediaQuery = window.matchMedia('(max-width: 1023px)')
      updateNarrow()
      _mediaQuery.addEventListener('change', updateNarrow)
    }
  })

  onUnmounted(() => {
    _mediaQuery?.removeEventListener('change', updateNarrow)
  })

  return {
    isNarrow,
    drawerOpen,
  }
}
