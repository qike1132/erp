/**
 * P1-26 / P1-30 回归：来料移动端搜索框是死 UI、记录固定 50 条无分页、失败静默空白。
 *
 * 修复后：搜索框显式提交（回车）才请求，keyword 进入 records 请求；分页下发
 * page/per_page；失败/403 渲染可理解错误态并可从重试按钮恢复。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { nextTick } from 'vue'
import { createRouter, createMemoryHistory } from 'vue-router'

const mocks = vi.hoisted(() => ({
  materialApi: { overview: vi.fn(), registrations: vi.fn() },
}))

vi.mock('@/api', () => ({ materialApi: mocks.materialApi }))

import MIncomingView from '@/mobile/views/incoming/MIncomingView.vue'
import MSearchBar from '@/mobile/components/MSearchBar.vue'
import MStatCard from '@/mobile/components/MStatCard.vue'

function makeRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/', component: { template: '<div />' } }],
  })
}

const opts = () => ({ global: { plugins: [makeRouter()] } })

function registration(id: number, orderNo: string) {
  return {
    id,
    purchase_order_no: orderNo,
    supplier_name: '供应商A',
    product_quantity: 10,
    status: 'pending',
  }
}

/** 搜索/记录/分页都在「记录」tab 下，默认 tab 是概览 */
async function mountOnRecordsTab() {
  const wrapper = mount(MIncomingView, opts())
  await flushPromises()
  const vm = wrapper.vm as unknown as { activeTab: string }
  vm.activeTab = 'records'
  await nextTick()
  return wrapper
}

describe('P1-26/P1-30 来料移动端搜索与分页', () => {
  it('概览 KPI 读取响应信封内层 overview（P1-08）', async () => {
    const wrapper = mount(MIncomingView, opts())
    await flushPromises()
    const cards = wrapper.findAllComponents(MStatCard)
    expect(cards).toHaveLength(2)
    expect(cards[0]!.props('value')).toBe(1)
    expect(cards[1]!.props('value')).toBe(1)
  })
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.materialApi.overview.mockResolvedValue({ success: true, overview: { total: 1, pending: 1 } })
    mocks.materialApi.registrations.mockResolvedValue({
      registrations: [registration(1, 'PO-1')],
      total: 1,
      pages: 1,
    })
  })

  it('逐字符输入不请求，显式提交后 keyword 进入 records 请求', async () => {
    const wrapper = await mountOnRecordsTab()

    expect(mocks.materialApi.registrations).toHaveBeenCalledWith({
      page: 1,
      per_page: 50,
      keyword: undefined,
    })

    mocks.materialApi.registrations.mockClear()
    const bar = wrapper.findComponent(MSearchBar)
    bar.vm.$emit('update:modelValue', 'PP棉')
    await flushPromises()
    expect(mocks.materialApi.registrations).not.toHaveBeenCalled()

    bar.vm.$emit('search', 'PP棉')
    await flushPromises()
    expect(mocks.materialApi.registrations).toHaveBeenCalledWith({
      page: 1,
      per_page: 50,
      keyword: 'PP棉',
    })
  })

  it('翻页时下发对应页码（服务端分页）', async () => {
    mocks.materialApi.registrations.mockResolvedValue({
      registrations: [registration(1, 'PO-1')],
      total: 120,
      pages: 3,
    })
    const wrapper = await mountOnRecordsTab()

    wrapper.findComponent({ name: 'UiPagination' }).vm.$emit('update:currentPage', 2)
    await flushPromises()

    expect(mocks.materialApi.registrations).toHaveBeenLastCalledWith({
      page: 2,
      per_page: 50,
      keyword: undefined,
    })
  })

  it('加载失败渲染错误态，重试可恢复列表', async () => {
    mocks.materialApi.registrations.mockRejectedValueOnce({ response: { status: 500 } })
    const wrapper = await mountOnRecordsTab()

    expect(wrapper.text()).toContain('记录加载失败，请点击重试')
    const retry = wrapper.find('.m-retry-btn')
    expect(retry.exists()).toBe(true)

    mocks.materialApi.registrations.mockResolvedValueOnce({
      registrations: [registration(2, 'PO-RETRY')],
      total: 1,
      pages: 1,
    })
    await retry.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('PO-RETRY')
    expect(wrapper.text()).not.toContain('记录加载失败')
  })

  it('403 时全局 toast 之外页面仍有可理解状态', async () => {
    mocks.materialApi.registrations.mockRejectedValueOnce({ response: { status: 403 } })
    const wrapper = await mountOnRecordsTab()

    expect(wrapper.text()).toContain('无查看权限')
  })
})
