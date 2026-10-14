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
      // 媒体类型必须显式限定 screen：打印时文档媒体类型切换为 print，Chrome 会按
      // 纸张宽度（A4 约 794px）重新求值 (max-width: 1023px) 并派发 change，
      // isNarrow 于是在整个打印预览期间翻转为 true —— PatternRoomSplitBody 的
      // v-if="!isNarrow" 会卸载左侧列表（CustomerGroupList / CustomerProjectArea /
      // VirtualList），打印结束后重新挂载，分组选中、分页、滚动位置全部回到初始值。
      // 线上现象：选中非首个 SKU → 打印打样单 → 取消 → 列表跳回第一个 SKU。
      _mediaQuery = window.matchMedia('screen and (max-width: 1023px)')
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
