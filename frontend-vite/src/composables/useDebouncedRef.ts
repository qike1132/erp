import { ref, watch } from 'vue'

/**
 * 防抖 ref composable
 * 延迟更新目标值，避免频繁触发 API 请求
 *
 * @param source 源 ref
 * @param delay 延迟毫秒数，默认 300ms
 */
export function useDebouncedRef<T>(source: { value: T }, delay = 300) {
  const debounced = ref(source.value) as { value: T }
  let timer: ReturnType<typeof setTimeout> | null = null

  watch(
    () => source.value,
    (val) => {
      if (timer) clearTimeout(timer)
      timer = setTimeout(() => {
        debounced.value = val
      }, delay)
    },
  )

  return debounced
}
