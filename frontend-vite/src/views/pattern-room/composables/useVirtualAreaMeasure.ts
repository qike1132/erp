/**
 * useVirtualAreaMeasure — 虚拟滚动容器高度测量 Hook
 *
 * 容器高度初始为 0，模板靠 `v-else-if="height > 0"` 守卫 VirtualList 渲染。
 * 容器元素本身是条件渲染的（未选中版师 / 无项目时不渲染），因此测高必须
 * **跟随元素生命周期**，而不是只在组件挂载那一刻做一次：
 *   1. 元素出现 → 同步测量 + nextTick/rAF 补测
 *   2. 元素出现 → 监听自身 + 父级尺寸变化（ResizeObserver）
 *   3. 元素摘除 → 断开监听；再次出现 → 重新测量
 *   4. 监听 window resize（视口变化）
 * 性能优化：ResizeObserver / window resize 回调通过 rAF 去抖，
 * 避免高频触发导致连续重排。
 *
 * 历史缺陷（2026-10-23）：只在 onMounted 挂监听。切状态筛选后原选中版师不在
 * 新分组里时容器不存在，用户再点版师使容器「后出现」——此时既没有 onMounted
 * 也没有 groups 变化，height 永远停在 0，模板恒显「加载中…」。
 */
import { ref, onMounted, onUnmounted, nextTick, watch } from 'vue'

export function useVirtualAreaMeasure() {
  /** 被测量的容器元素引用 */
  const areaRef = ref<HTMLElement | null>(null)
  /** 测量得到的容器高度（初始 0，模板据此守卫 VirtualList 渲染） */
  const height = ref(0)

  let areaResizeObserver: ResizeObserver | null = null
  let parentResizeObserver: ResizeObserver | null = null
  let windowResizeHandler: (() => void) | null = null
  let _rafId: number | null = null

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

  /** rAF 去抖测量：高频回调（ResizeObserver / resize）合并到单帧 */
  function measureRaf() {
    if (_rafId !== null) return
    _rafId = requestAnimationFrame(() => {
      _rafId = null
      measure()
    })
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

  function disconnectObservers() {
    areaResizeObserver?.disconnect()
    areaResizeObserver = null
    parentResizeObserver?.disconnect()
    parentResizeObserver = null
  }

  function observeElement(el: HTMLElement) {
    disconnectObservers()
    tryMeasureWithRetry()
    if (typeof ResizeObserver === 'undefined') return
    areaResizeObserver = new ResizeObserver(measureRaf)
    areaResizeObserver.observe(el)
    // 同时监听父级（cgl-body / pr-left-pane）尺寸变化，
    // 解决父级从 0 → 有数据时自身尺寸可能不变导致漏触发的问题
    const parent = el.parentElement
    if (parent) {
      parentResizeObserver = new ResizeObserver(measureRaf)
      parentResizeObserver.observe(parent)
    }
  }

  // flush: 'post' —— 回调在元素插入 DOM 之后执行，此时才拿得到真实高度。
  // 模板 ref 从 null 变为元素发生在挂载/切换的那次 patch 里，因此首次挂载
  // 与「元素后出现」都由这里驱动，无需再在 onMounted 里补一次。
  watch(areaRef, (el) => {
    if (el) {
      observeElement(el)
      return
    }
    disconnectObservers()
    // 摘除时归零：否则消费方会拿旧高度先渲染虚拟列表；且 tryMeasureWithRetry
    // 会因 height > 0 早退，跳过 nextTick/rAF 补测 —— 新容器此刻量得 0 时
    // （正是父级 flex 链尚未完成布局的场景）会一直沿用上一个容器的高度。
    height.value = 0
  }, { flush: 'post' })

  onMounted(() => {
    // 监听 window resize（窄屏/宽屏切换、抽屉展开/收起等场景）
    windowResizeHandler = measureRaf
    window.addEventListener('resize', windowResizeHandler)
  })

  onUnmounted(() => {
    disconnectObservers()
    if (windowResizeHandler) {
      window.removeEventListener('resize', windowResizeHandler)
      windowResizeHandler = null
    }
    if (_rafId !== null) {
      cancelAnimationFrame(_rafId)
      _rafId = null
    }
  })

  return {
    areaRef,
    height,
    measure,
  }
}
