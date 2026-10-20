/**
 * Z04-R3 回归：仪表盘卡片入场动画的多个 setTimeout 必须统一收集并在卸载时清理；
 * 原实现每次覆盖 animTimer，卸载后仍有 3 个回调存活；另有 currentTime 10s 空转定时器。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { defineComponent, h } from 'vue'
import { mount, flushPromises } from '@vue/test-utils'

const mocks = vi.hoisted(() => ({
  mobile: vi.fn(async () => ({
    production: { departments: [] },
  })),
}))

vi.mock('@/api', () => ({ dashboardApi: { mobile: mocks.mobile } }))

import { useDashboardMobileData } from '@/mobile/views/dashboard/composables/useDashboardMobileData'

const Host = defineComponent({
  setup() {
    useDashboardMobileData()
    return () => h('div')
  },
})

describe('useDashboardMobileData 定时器生命周期', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.clearAllMocks()
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it('挂载后 4 个入场定时器，卸载后全部清理', async () => {
    const wrapper = mount(Host)
    await flushPromises()
    expect(vi.getTimerCount()).toBe(4)

    wrapper.unmount()
    expect(vi.getTimerCount()).toBe(0)
  })
})
