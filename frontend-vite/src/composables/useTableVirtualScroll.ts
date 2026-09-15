/**
 * useTableVirtualScroll — 表格虚拟滚动的尺寸测量 composable
 *
 * 背景：
 *   UiDataTable 使用 PrimeVue DataTable 渲染表头，但表格主体在虚拟滚动模式下
 *   需要交给自研 VirtualList 渲染，以便把 DOM 节点数从 O(n) 降到 O(可视区)。
 *
 * 职责：
 *   1. 测量表头高度（虚拟列表的可用高度 = 容器高度 - 表头高度）
 *   2. 用 ResizeObserver 跟踪容器与表头尺寸变化，保证窗口缩放/侧边栏折叠后
 *      虚拟区高度仍然正确
 *   3. 暴露 rowHeight，允许调用方按业务设置行高（默认 48px）
 *
 * 为什么不用 PrimeVue VirtualScroller：
 *   1) 项目未安装该组件；2) 自研 VirtualList 已实现动态高度测量与前缀和缓存，
 *   且已被 8 个页面验证；复用它可避免引入新的运行时依赖与样式冲突。
 */
import { ref, onMounted, onUnmounted, nextTick, type Ref } from 'vue'

interface Options {
  /** 行高（px），需与实际 CSS 行高一致，否则会出现滚动跳动 */
  rowHeight?: number
  /** 额外的上下留白（px），如容器内边距 */
  padding?: number
}

export function useTableVirtualScroll(
  containerRef: Ref<HTMLElement | null>,
  headerRef: Ref<HTMLElement | null>,
  opts: Options = {},
) {
  const { rowHeight = 48, padding = 0 } = opts

  /** 虚拟区可用高度（容器高度 - 表头高度 - 留白） */
  const bodyHeight = ref(0)
  let ro: ResizeObserver | null = null

  function measure() {
    const container = containerRef.value
    if (!container) return

    const containerH = container.clientHeight
    const headerH = headerRef.value?.offsetHeight ?? 0
    const next = Math.max(0, containerH - headerH - padding)

    // 仅在变化超过 1px 时更新，避免 ResizeObserver 抖动导致的无限循环
    if (Math.abs(next - bodyHeight.value) > 1) {
      bodyHeight.value = next
    }
  }

  onMounted(async () => {
    await nextTick()
    measure()

    if (typeof ResizeObserver !== 'undefined') {
      ro = new ResizeObserver(() => measure())
      if (containerRef.value) ro.observe(containerRef.value)
      if (headerRef.value) ro.observe(headerRef.value)
    }
  })

  onUnmounted(() => {
    ro?.disconnect()
    ro = null
  })

  return {
    bodyHeight,
    rowHeight,
    /** 供外部在数据/布局变化后手动触发重测（如展开筛选栏） */
    remeasure: measure,
  }
}
