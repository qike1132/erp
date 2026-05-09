import { onMounted, onUnmounted, type Ref } from 'vue'

/**
 * 事件委托 - 列表/表格中用单个容器监听替代N个子元素监听
 * 模板中: <button data-action="edit" :data-id="row.id">编辑</button>
 * const { handleDelegatedClick } = useEventDelegation(containerRef, { edit: (id) => ... })
 */
export function useEventDelegation(
  containerRef: Ref<HTMLElement | null>,
  handlers: Record<string, (id: string | number, event: Event) => void>,
  actionAttr = 'data-action', idAttr = 'data-id', event = 'click',
) {
  function handleClick(e: Event) {
    const el = (e.target as HTMLElement).closest(`[${actionAttr}]`) as HTMLElement | null
    if (!el) return
    const action = el.getAttribute(actionAttr)
    const id = el.getAttribute(idAttr)
    if (action && handlers[action]) { e.stopPropagation(); handlers[action](id ?? '', e) }
  }
  onMounted(() => containerRef.value?.addEventListener(event, handleClick))
  onUnmounted(() => containerRef.value?.removeEventListener(event, handleClick))
  return { handleDelegatedClick: handleClick }
}

/**
 * 节流滚动 (requestAnimationFrame)
 */
export function useThrottledScroll(
  containerRef: Ref<HTMLElement | null>,
  callback: (scrollTop: number) => void,
) {
  let rafId: number | null = null
  function onScroll() {
    if (rafId !== null) return
    rafId = requestAnimationFrame(() => { if (containerRef.value) callback(containerRef.value.scrollTop); rafId = null })
  }
  onMounted(() => containerRef.value?.addEventListener('scroll', onScroll, { passive: true }))
  onUnmounted(() => { containerRef.value?.removeEventListener('scroll', onScroll); if (rafId !== null) cancelAnimationFrame(rafId) })
}

/**
 * IntersectionObserver 惰性加载 (滚动到底部触发加载更多)
 */
export function useLazyLoad(
  containerRef: Ref<HTMLElement | null>,
  loadCallback: () => void,
  rootMargin = '200px',
) {
  let observer: IntersectionObserver | null = null
  let sentinel: HTMLElement | null = null
  onMounted(() => {
    if (!containerRef.value) return
    sentinel = document.createElement('div')
    sentinel.style.height = '1px'
    containerRef.value.appendChild(sentinel)
    observer = new IntersectionObserver(
      (entries) => { for (const e of entries) if (e.isIntersecting) loadCallback() },
      { root: containerRef.value, threshold: 0.1, rootMargin },
    )
    observer.observe(sentinel)
  })
  onUnmounted(() => { observer?.disconnect(); sentinel?.remove() })
}
