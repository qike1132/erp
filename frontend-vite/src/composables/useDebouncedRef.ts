import { refDebounced } from '@vueuse/core'
import { isRef, ref, watch, type Ref } from 'vue'

/**
 * 防抖 ref composable（基于 VueUse refDebounced）
 * 延迟更新目标值，避免频繁触发 API 请求。
 *
 * 支持两种入参：
 * - `Ref` / `ComputedRef`：**持续跟随**源变化，变化后经 delay 反映到返回值
 * - 普通对象 `{ value: T }`：仅取初始值快照（无响应式来源，无法持续跟随）
 *
 * 历史缺陷（2026-09-14 修复）：原实现无条件执行 `ref(source.value)`，
 * 即使传入的是 ComputedRef 也只读取一次当前值，导致返回值恒等于初始值。
 * 受影响调用点 `src/views/stock/InventoryTab.vue`：
 *   `useDebouncedRef(computed(() => filters.product), 300)`
 * 的结果恒为空串，产品筛选条件完全失效。现改为对传入的 Ref 直接建立
 * 响应式监听，普通对象仍保留快照语义（并给出开发期告警）。
 */
export function useDebouncedRef<T>(source: { value: T }, delay = 300) {
  // 传入的是 Ref/ComputedRef：跟随其变化，避免取值快照导致契约失效
  if (isRef(source)) {
    return refDebounced(source as Ref<T>, delay)
  }

  // 普通对象只能取快照：显式提示调用方改用 ref 以获得持续跟随能力
  if (import.meta.env.DEV) {
    console.warn(
      '[useDebouncedRef] 传入的 source 不是 ref，将只取初始值快照，' +
      '后续变更不会生效。如需跟随变化，请传入 ref/computed。',
    )
  }
  return refDebounced(ref(source.value) as Ref<T>, delay)
}

/**
 * 保持对源持续跟随的变体。
 *
 * 与 `useDebouncedRef` 的区别：内部用 watch 同步源值到中间 ref。
 * 注意：watch 只能追踪**响应式**来源，因此：
 * - `Ref` / `ComputedRef` / `reactive` 对象的属性：可持续跟随
 * - 普通对象 `{ value }`：无法被追踪（Vue 无法感知其属性变化），
 *   仍退化为快照语义。需要跟随请改用 `ref` / `reactive`。
 */
export function useDebouncedRefReactive<T>(source: { value: T }, delay = 300) {
  const inner = ref(source.value) as Ref<T>
  watch(
    // getter 本身若读取的是非响应式对象属性，则不会建立依赖（Vue 语义如此）
    () => source.value,
    (v) => {
      inner.value = v
    },
  )
  return refDebounced(inner, delay)
}
