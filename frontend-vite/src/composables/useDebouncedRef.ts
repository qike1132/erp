import { refDebounced } from '@vueuse/core'
import { ref, type Ref } from 'vue'

/**
 * 防抖 ref composable（基于 VueUse refDebounced）
 * 延迟更新目标值，避免频繁触发 API 请求
 */
export function useDebouncedRef<T>(source: { value: T }, delay = 300) {
  return refDebounced(ref(source.value) as Ref<T>, delay)
}
