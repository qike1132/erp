/**
 * 统一搜索防抖 composable
 *
 * 封装各视图重复的 searchTimer 声明 + clearTimeout + onUnmounted 清理样板。
 * 防抖到期后执行调用方传入的回调（通常是更新防抖关键词并重置页码，
 * 或直接触发搜索/建议请求）。
 */
import { onUnmounted } from 'vue'

/**
 * @param delay 防抖延迟（毫秒），默认 300
 * @returns debounceSearch 防抖触发函数（重复调用会重置计时器）
 */
export function useDebouncedSearch(delay = 300) {
  let searchTimer: ReturnType<typeof setTimeout> | null = null

  /** 防抖触发搜索回调 */
  function debounceSearch(callback: () => void) {
    if (searchTimer) clearTimeout(searchTimer)
    searchTimer = setTimeout(callback, delay)
  }

  // 组件卸载时清理未触发的防抖任务
  onUnmounted(() => {
    if (searchTimer) clearTimeout(searchTimer)
  })

  return { debounceSearch }
}
