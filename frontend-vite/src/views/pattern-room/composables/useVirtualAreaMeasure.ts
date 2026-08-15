/**
 * useVirtualAreaMeasure — 虚拟滚动容器高度测量 Hook
 *
 * 容器高度初始为 0，模板靠 `v-else-if="height > 0"` 守卫 VirtualList 渲染。
 * 由于父级 flex 链可能在数据加载后才完成布局，单次 onMounted 测量经常得到 0，
 * 这里采用多策略保证最终能拿到正确高度：
 *   1. onMounted 同步测量（best-effort）
 *   2. nextTick 后再次测量（父级 v-if/v-else 切换后）
 *   3. requestAnimationFrame 后测量（最终布局稳定）
 *   4. 监听自身 + 父级尺寸变化（ResizeObserver，仅在变化时触发）
 *   5. 监听 window resize（视口变化）
 * 逻辑自 CustomerGroupList.vue 原样搬移。
 */
import { ref, onMounted, onUnmounted, nextTick } from 'vue'

export function useVirtualAreaMeasure() {
  /** 被测量的容器元素引用 */
  const areaRef = ref<HTMLElement | null>(null)
  /** 测量得到的容器高度（初始 0，模板据此守卫 VirtualList 渲染） */
  const height = ref(0)

  let areaResizeObserver: ResizeObserver | null = null
  let parentResizeObserver: ResizeObserver | null = null
  let windowResizeHandler: (() => void) | null = null

  function measure() {
    if (!areaRef.value) return
    // getBoundingClientRect 比 clientHeight 更可靠：不受 box-sizing 影响
    const rect = areaRef.value.getBoundingClientRect()
    // 使用 offsetHeight 优先（已包含 padding），若为 0 则降级到 rect.height
    const h = areaRef.value.offsetHeight || Math.round(rect.height)
    if (h > 0 && h !== height.value) {
      height.value = h
    }
  }

  function tryMeasureWithRetry() {
    // 同步测量（此时通常 onMounted 刚执行）
    measure()
    if (height.value > 0) return
    // nextTick 后再试（父级 v-if/v-else 切换可能影响布局）
    nextTick(() => {
      measure()
      if (height.value > 0) return
      // rAF 后再试（最终布局稳定阶段）
      requestAnimationFrame(() => {
        measure()
      })
    })
  }

  onMounted(() => {
    tryMeasureWithRetry()
    if (areaRef.value && typeof ResizeObserver !== 'undefined') {
      areaResizeObserver = new ResizeObserver(measure)
      areaResizeObserver.observe(areaRef.value)
      // 同时监听父级（cgl-body / pr-left-pane）尺寸变化，
      // 解决父级从 0 → 有数据时自身尺寸可能不变导致漏触发的问题
      // 只需追踪最近一层 flex 父级即可，过深会增加无意义的回调
      const parent = areaRef.value.parentElement
      if (parent) {
        parentResizeObserver = new ResizeObserver(measure)
        parentResizeObserver.observe(parent)
      }
    }
    // 监听 window resize（窄屏/宽屏切换、抽屉展开/收起等场景）
    windowResizeHandler = () => {
      // rAF 延迟，避免 resize 期间反复触发
      requestAnimationFrame(measure)
    }
    window.addEventListener('resize', windowResizeHandler)
  })

  onUnmounted(() => {
    areaResizeObserver?.disconnect()
    parentResizeObserver?.disconnect()
    if (windowResizeHandler) {
      window.removeEventListener('resize', windowResizeHandler)
      windowResizeHandler = null
    }
  })

  return {
    areaRef,
    height,
    measure,
  }
}
