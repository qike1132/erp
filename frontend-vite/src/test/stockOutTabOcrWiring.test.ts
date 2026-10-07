/**
 * 出货页「粘贴识别 → 暂存列表」接线集成测试（P3-2 审核建议）。
 *
 * 映射函数（buildStockoutStagedItems）与闸门（useOcrPaste）各自有单测；
 * 这里锁的是事件链：OcrPasteImport 的 buildStaged 回调 → Section 发 ocr-staged
 * → StockOutInputForm 转发 → StockOutTab.addOcrStaged 入列（staged 增长）。
 * 中间任何一环把事件名/转发接错，本测试都会红。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { defineComponent } from 'vue'

const mocks = vi.hoisted(() => ({
  invalidateDerived: vi.fn(),
}))

vi.mock('@/api/request', () => ({
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
  del: vi.fn(),
  upload: vi.fn(),
  download: vi.fn(),
}))

vi.mock('@tanstack/vue-query', () => ({
  useQueryClient: () => ({ invalidateQueries: vi.fn() }),
}))

vi.mock('@/stores/catalog', () => ({
  useCatalogStore: () => ({
    activeCustomerNames: [],
    ensureActiveCustomerNames: vi.fn(async () => {}),
  }),
}))

vi.mock('@/utils/queryKeys', () => ({
  invalidateOrderDerivedQueries: mocks.invalidateDerived,
}))

import StockOutTab from '@/views/stock/StockOutTab.vue'

/** OcrPasteImport 替身：点击时以测试草稿调用注入的 buildStaged 回调（走真实映射链） */
const OcrPasteImportStub = defineComponent({
  props: {
    buildStaged: { type: Function, required: true },
    defaultCustomer: { type: String, default: '' },
    defaultDate: { type: String, default: '' },
    searchProducts: { type: Function, default: null },
    downloadTemplate: { type: Function, default: null },
  },
  data() {
    return {
      drafts: [
        { product_id: 7, product_name: '儿童保温杯 500ml', quantity: 5, customer: '', note: '' },
      ],
      ctx: { date: '2026-10-06', fallbackCustomer: '表单客户' },
    }
  },
  template: '<button class="fire-ocr" @click="buildStaged(drafts, ctx)">fire</button>',
})

/** StockOutStagingList 替身：把 staged 透出来供断言 */
const StagingListStub = defineComponent({
  props: { staged: { type: Array, required: true }, stagedTotalQty: { type: Number, default: 0 } },
  template: '<div class="staging-list">{{ staged.length }}</div>',
})

function mountTab() {
  return mount(StockOutTab, {
    global: {
      stubs: {
        StockOutInputForm: false, // 真件——要测它的一跳转发
        StockOutImportSection: false, // 真件——要测它把 buildStaged 结果发成 ocr-staged
        StockOutStagingList: StagingListStub,
        StockOutEditStagedDialog: true,
        UiConfirmDialog: true,
        OcrPasteImport: OcrPasteImportStub,
        UiButton: { template: '<button><slot /></button>' },
        UiSelect: { template: '<select />' },
        UiDatePicker: { template: '<input />' },
        UiAutocomplete: { template: '<input />' },
        UiBadge: { template: '<span><slot /></span>' },
        FontAwesomeIcon: { template: '<i />' },
        UiLoadingIcon: { template: '<i />' },
      },
    },
  })
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('StockOutTab — OCR 接线', () => {
  it('buildStaged 回调一路转发，条目进入暂存列表', async () => {
    const wrapper = mountTab()
    expect(wrapper.findComponent(StagingListStub).props('staged')).toHaveLength(0)

    await wrapper.find('.fire-ocr').trigger('click')

    const staged = wrapper.findComponent(StagingListStub).props('staged') as Array<Record<string, unknown>>
    expect(staged).toHaveLength(1)
    expect(staged[0]).toMatchObject({
      product_id: '7',
      customer: '表单客户', // 图上无客户 → 表单兜底
      quantity: 5,
      date: '2026-10-06',
    })
  })

  it('连续识别两批：追加而非替换', async () => {
    const wrapper = mountTab()
    await wrapper.find('.fire-ocr').trigger('click')
    await wrapper.find('.fire-ocr').trigger('click')

    expect(wrapper.findComponent(StagingListStub).props('staged')).toHaveLength(2)
  })
})
