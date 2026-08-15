import { type Ref } from 'vue'
import { useEventListener, useThrottleFn, useIntersectionObserver } from '@vueuse/core'

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
  useEventListener(containerRef, event, handleClick)
  return { handleDelegatedClick: handleClick }
}

/**
 * 节流滚动 (基于 VueUse useThrottleFn)
 */
export function useThrottledScroll(
  containerRef: Ref<HTMLElement | null>,
  callback: (scrollTop: number) => void,
) {
  const throttled = useThrottleFn(() => {
    if (containerRef.value) callback(containerRef.value.scrollTop)
  }, 16, true)
  useEventListener(containerRef, 'scroll', throttled, { passive: true })
}

/**
 * IntersectionObserver 惰性加载 (基于 VueUse useIntersectionObserver)
 * 注意：需在模板中放置 sentinel 元素：<div ref="sentinelRef" style="height:1px">
 */
export function useLazyLoad(
  sentinelRef: Ref<HTMLElement | null>,
  loadCallback: () => void,
  rootMargin = '200px',
) {
  useIntersectionObserver(
    sentinelRef,
    (entries) => { for (const e of entries) if (e.isIntersecting) loadCallback() },
    { threshold: 0.1, rootMargin },
  )
}
