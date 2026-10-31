import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { nextTick } from 'vue'

const mocks = vi.hoisted(() => ({
  orders: vi.fn(),
  unprocessed: vi.fn(),
  completed: vi.fn(),
  generate: vi.fn(),
  openBom: vi.fn(),
}))

vi.mock('@/api', () => ({
  purchaseApi: {
    orders: mocks.orders,
    unprocessedOrders: mocks.unprocessed,
    completed: mocks.completed,
    oneClickGenerate: mocks.generate,
    completeOrder: vi.fn(),
    batchComplete: vi.fn(),
    orderDetail: vi.fn(),
    deleteOrder: vi.fn(),
    batchDelete: vi.fn(),
    updateOrder: vi.fn(),
    exportCompleted: vi.fn(),
    quickFilters: vi.fn(),
    suggestions: vi.fn(),
    factorySummary: vi.fn(),
    supplierSummary: vi.fn(),
    saveFactoryEdits: vi.fn(),
    summaryPrint: vi.fn(),
    supplierSummaryExport: vi.fn(),
    products: vi.fn(),
    searchSuggestions: vi.fn(),
    calculate: vi.fn(),
  },
}))

vi.mock('@/views/product/components/BomEditor.vue', async () => {
  const { defineComponent, h } = await import('vue')
  return {
    default: defineComponent({
      name: 'BomEditorTestDouble',
      setup(_props, { expose, emit }) {
        expose({ open: mocks.openBom })
        return () => h('div', { class: 'bom-editor-test-double' }, [
          h('button', {
            class: 'bom-test-saved',
            onClick: () => emit('saved', { product_id: 5 }),
          }, 'saved'),
          h('button', {
            class: 'bom-test-closed',
            onClick: () => emit('closed', { product_id: 5 }),
          }, 'closed'),
        ])
      },
    }),
  }
})

vi.mock('@tanstack/vue-query', async () => {
  const { ref } = await import('vue')
  return {
    useQueryClient: () => ({
      invalidateQueries: vi.fn(),
      setQueryData: vi.fn(),
      prefetchQuery: vi.fn(),
    }),
    useQuery: (opts: { queryFn?: () => unknown }) => {
      const data = ref<unknown>(null)
      const refetch = vi.fn(() => Promise.resolve()
        .then(() => opts?.queryFn?.())
        .then((value) => { data.value = value }))
      void refetch()
      return {
        data,
        isLoading: ref(false),
        isFetching: ref(false),
        isError: ref(false),
        refetch,
      }
    },
    keepPreviousData: {},
  }
})

vi.mock('vue-router', () => ({
  onBeforeRouteLeave: () => {},
  useRoute: () => ({ query: {} }),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}))

vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({
    user: { id: 7 },
    hasPermission: (code: string) => code === 'product_manage',
  }),
}))

vi.mock('@/composables/useToast', () => ({
  showToast: vi.fn(),
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
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

import PurchaseView from '@/views/purchase/PurchaseView.vue'

const row = {
  id: 42,
  composite_id: 'order:42',
  record_type: 'order' as const,
  source_order_id: 42,
  order_no: 'PO-42',
  customer: '集成客户',
  product_id: 5,
  product_name: '产品五',
  quantity: 2,
  order_date: '2026-10-30',
  status: '待备货',
  has_bom: false,
  sku_count: 1,
  items: [{ id: 1, product_id: 5, product_name: '产品五', quantity: 2, has_bom: false }],
}

let wrapper: VueWrapper | null = null

async function mountView() {
  wrapper = mount(PurchaseView, {
    global: {
      stubs: {
        UiCheckbox: { template: '<span />' },
        UiPagination: { template: '<div />' },
        FontAwesomeIcon: { template: '<i />' },
        UiLoadingIcon: { template: '<i />' },
        OrderDetailModal: { template: '<div />' },
        SummaryPanel: { template: '<div />' },
        UiConfirmDialog: { template: '<div />' },
      },
    },
  })
  await flushPromises()
  await nextTick()
  return wrapper
}

async function startBom() {
  const cta = wrapper!.find('.pc-bom-cta')
  expect(cta.exists()).toBe(true)
  await cta.trigger('click')
  await flushPromises()
  await nextTick()
  expect(mocks.openBom).toHaveBeenCalledWith({ id: 5, name: '产品五' })
}

beforeEach(() => {
  sessionStorage.clear()
  vi.clearAllMocks()
  mocks.orders.mockResolvedValue({ orders: [], total: 0, pages: 1, current_page: 1 })
  mocks.unprocessed.mockResolvedValue({ orders: [row], total: 1, pages: 1, current_page: 1 })
  mocks.completed.mockResolvedValue({ orders: [], total: 0, pages: 1, current_page: 1 })
  mocks.generate.mockResolvedValue({
    success: true,
    code: 'OK',
    created_count: 1,
    idempotent: false,
    orders: [{ id: 88, order_no: 'PO-88' }],
    missing_bom: [],
  })
})

afterEach(() => {
  wrapper?.unmount()
  wrapper = null
  document.body.innerHTML = ''
})

describe('采购页 BOM 父组件事件串联', () => {
  it('入口点击打开正确 SKU，保存事件只触发一次同键续提', async () => {
    await mountView()
    await startBom()

    await wrapper!.find('.bom-test-saved').trigger('click')
    await flushPromises()
    await nextTick()

    expect(mocks.generate).toHaveBeenCalledTimes(1)
    expect(mocks.generate).toHaveBeenCalledWith(
      { composite_ids: ['order:42'] },
      { headers: { 'X-Idempotency-Key': expect.stringMatching(/^po-resume:/) } },
    )
    expect(wrapper!.find('.pc-resume-status').text()).toContain('PO-88')
  })

  it('关闭事件只取消尝试，不调用权威续提', async () => {
    await mountView()
    await startBom()

    await wrapper!.find('.bom-test-closed').trigger('click')
    await flushPromises()
    await nextTick()

    expect(mocks.generate).not.toHaveBeenCalled()
    expect(wrapper!.find('.pc-resume-status').text()).toContain('已取消')
  })
})
