/**
 * CustomerOrderView 结构守卫（2026-10-06 记录查询 tab 移除后改写）。
 *
 * 本文件前身是「记录列表合并 + 搜索栏」混排测试（F2）：订单/备货混排表、
 * 类型徽章、搜索框、备货行编辑删除等。记录查询 tab 收敛至 /report 后，
 * 被测界面已从本页删除，相关行为由以下文件承接：
 *   - 混排表与行内操作 → test/reportViewRedesign.test.ts（/report 操作列）
 *   - 编辑订单弹窗 SKU 表格 → test/CustomerOrderView.skuExpand.test.ts
 *   - 备货编辑/删除动作域 → test/customerOrderCrossPageInvalidation.test.ts
 *
 * 现职责：锁「单 tab 新现实」——页头只剩一个静态「录入」按钮，
 * 记录查询的痕迹（搜索框 / 类型徽章 / 记录列表）不得回潮。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'

const mocks = vi.hoisted(() => ({
  customerActiveNamesMock: vi.fn(),
}))

vi.mock('@/api', () => ({
  orderApi: {
    create: vi.fn(),
    staging: {
      add: vi.fn(),
      list: vi.fn(),
      delete: vi.fn(),
      confirm: vi.fn(),
    },
  },
  stockApi: {
    stockins: vi.fn().mockResolvedValue({ data: [], total: 0 }),
  },
  customerApi: {
    activeNames: mocks.customerActiveNamesMock,
  },
  auxApi: {
    availableStockins: vi.fn(async () => []),
  },
}))

vi.mock('@/api/request', () => ({
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
  del: vi.fn(),
}))

vi.mock('@tanstack/vue-query', () => ({
  useQuery: () => ({ data: { value: { names: [] } } }),
  useQueryClient: () => ({ invalidateQueries: vi.fn() }),
}))

vi.mock('@/composables/useToast', () => ({
  showToast: vi.fn(),
}))

vi.mock('@/composables/useConfirmDialog', () => ({
  useConfirmDialog: () => ({
    open: false,
    text: '',
    sub: '',
    type: 'warning',
    onConfirm: vi.fn(),
    onCancel: vi.fn(),
    confirm: vi.fn(async () => true),
  }),
}))

import { mount, flushPromises } from '@vue/test-utils'
import { nextTick } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import CustomerOrderView from '@/views/customer-order/CustomerOrderView.vue'

const stubs = {
  UiInput: { template: '<input />' },
  UiDatePicker: { template: '<input />' },
  UiButton: { template: '<button><slot /></button>' },
  UiDialog: {
    template: '<div v-if="open" class="ui-dialog-stub"><slot /><slot name="footer" /></div>',
    props: ['open', 'title', 'maxWidthClass'],
  },
  UiSelect: { template: '<div class="ui-select-stub" />' },
  UiPagination: { template: '<div />' },
  UiConfirmDialog: { template: '<div />' },
  UiAutocomplete: { template: '<input />' },
}

describe('CustomerOrderView 单 tab 结构守卫（2026-10-06 记录查询 tab 移除）', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    mocks.customerActiveNamesMock.mockReset()
    mocks.customerActiveNamesMock.mockResolvedValue({ names: [] })
  })

  it('页头只有「录入」一个 tab 按钮，且恒为选中态', async () => {
    const wrapper = mount(CustomerOrderView, { global: { stubs } })
    await flushPromises()

    const tabBtns = wrapper.findAll('button.co-tab-btn')
    expect(tabBtns.length).toBe(1)
    expect(tabBtns[0]!.text()).toBe('录入')
    expect(tabBtns[0]!.classes()).toContain('active')
  })

  it('「记录查询」按钮不得回潮', async () => {
    const wrapper = mount(CustomerOrderView, { global: { stubs } })
    await flushPromises()
    await nextTick()

    expect(wrapper.text()).not.toContain('记录查询')
    expect(wrapper.find('input.co-record-search').exists()).toBe(false)
  })

  it('记录查询的混排痕迹（类型徽章）不回潮', () => {
    const wrapper = mount(CustomerOrderView, { global: { stubs } })

    expect(wrapper.find('.co-type-badge').exists()).toBe(false)
  })

  it('EditStagedModal 链路仍在（录入侧暂存编辑不被误删）', () => {
    const wrapper = mount(CustomerOrderView, { global: { stubs } })

    // 暂存编辑弹窗挂在模板里（v-model:open），组件存在即结构未断
    expect(wrapper.findComponent({ name: 'EditStagedModal' }).exists()).toBe(true)
  })
})
