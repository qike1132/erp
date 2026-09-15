import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { ref, nextTick } from 'vue'
import { mount } from '@vue/test-utils'
import { defineComponent, h } from 'vue'
import { useTableVirtualScroll } from '@/composables/useTableVirtualScroll'

type VTable = ReturnType<typeof useTableVirtualScroll>
let captured: VTable | null = null

/**
 * useTableVirtualScroll 单测
 *
 * 覆盖点：
 *  1. 正确计算 bodyHeight = 容器高 - 表头高 - padding
 *  2. ResizeObserver 触发后重新测量
 *  3. 容器或表头不存在时不抛错
 *  4. 变化小于 1px 时不触发更新（防抖动）
 *  5. 卸载时断开 ResizeObserver
 */
describe('useTableVirtualScroll', () => {
  let resizeCallback: ResizeObserverCallback | null = null
  const disconnectSpy = vi.fn()

  beforeEach(() => {
    resizeCallback = null
    disconnectSpy.mockClear()

    // jsdom 无 ResizeObserver，注入可控 stub
    class MockResizeObserver {
      constructor(cb: ResizeObserverCallback) {
        resizeCallback = cb
      }
      observe() {}
      unobserve() {}
      disconnect() {
        disconnectSpy()
      }
    }
    vi.stubGlobal('ResizeObserver', MockResizeObserver)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  /** 挂载一个宿主组件以便拿到真实 DOM ref */
  function mountHarness(opts: { containerH?: number; headerH?: number; padding?: number } = {}) {
    const { containerH = 600, headerH = 40, padding = 0 } = opts
    const containerRef = ref<HTMLElement | null>(null)
    const headerRef = ref<HTMLElement | null>(null)
    let exposed: ReturnType<typeof useTableVirtualScroll> | null = null

    const Host = defineComponent({
      setup() {
        exposed = useTableVirtualScroll(containerRef, headerRef, { padding })
        return () => h('div', { ref: containerRef }, [h('div', { ref: headerRef })])
      },
    })

    const wrapper = mount(Host)
    const containerEl = wrapper.element as HTMLElement
    const headerEl = containerEl.firstElementChild as HTMLElement

    // jsdom 中 clientHeight / offsetHeight 恒为 0，需显式打桩
    Object.defineProperty(containerEl, 'clientHeight', { value: containerH, configurable: true })
    Object.defineProperty(headerEl, 'offsetHeight', { value: headerH, configurable: true })

    return { wrapper, exposed: exposed!, containerRef, headerRef, containerEl, headerEl }
  }

  it('计算 bodyHeight = 容器高 - 表头高', async () => {
    const { exposed } = mountHarness({ containerH: 600, headerH: 40 })
    await nextTick()
    await nextTick()
    expect(exposed.bodyHeight.value).toBe(560)
  })

  it('扣除 padding', async () => {
    const { exposed } = mountHarness({ containerH: 600, headerH: 40, padding: 10 })
    await nextTick()
    await nextTick()
    expect(exposed.bodyHeight.value).toBe(550)
  })

  it('未挂载时 bodyHeight 为 0，不抛错', () => {
    // 用真实宿主组件承载 composable，保证 lifecycle hook 有实例可挂
    const Host = defineComponent({
      setup() {
        captured = useTableVirtualScroll(ref(null), ref(null))
        return () => h('div')
      },
    })
    mount(Host)
    expect(() => captured!.remeasure()).not.toThrow()
    expect(captured!.bodyHeight.value).toBe(0)
  })

  it('ResizeObserver 回调触发重新测量', async () => {
    const { exposed, containerEl } = mountHarness({ containerH: 600, headerH: 40 })
    await nextTick()
    await nextTick()
    expect(exposed.bodyHeight.value).toBe(560)

    // 模拟容器变高
    Object.defineProperty(containerEl, 'clientHeight', { value: 800, configurable: true })
    resizeCallback?.([], {} as ResizeObserver)
    await nextTick()
    expect(exposed.bodyHeight.value).toBe(760)
  })

  it('变化小于 1px 时不更新（防抖动）', async () => {
    const { exposed, containerEl } = mountHarness({ containerH: 600, headerH: 40 })
    await nextTick()
    await nextTick()
    expect(exposed.bodyHeight.value).toBe(560)

    // 仅变化 0.5px
    Object.defineProperty(containerEl, 'clientHeight', { value: 600.5, configurable: true })
    resizeCallback?.([], {} as ResizeObserver)
    await nextTick()
    expect(exposed.bodyHeight.value).toBe(560)
  })

  it('卸载时断开 ResizeObserver', async () => {
    const { wrapper } = mountHarness()
    await nextTick()
    wrapper.unmount()
    expect(disconnectSpy).toHaveBeenCalled()
  })

  it('返回 rowHeight 等于传入值', () => {
    const Host = defineComponent({
      setup() {
        captured = useTableVirtualScroll(ref(null), ref(null), { rowHeight: 36 })
        return () => h('div')
      },
    })
    mount(Host)
    expect(captured!.rowHeight).toBe(36)
  })
})
