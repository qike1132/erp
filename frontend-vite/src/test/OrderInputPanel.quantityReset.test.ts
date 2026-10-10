import { describe, it, expect, vi } from 'vitest'
import { mount, VueWrapper } from '@vue/test-utils'
import OrderInputPanel from '@/views/customer-order/components/OrderInputPanel.vue'
import type { FormState } from '@/views/customer-order/composables/types'

const form = reactive({
  id: 0,
  type: 'order',
  date: '2026-09-28',
  customer: 'test-customer',
  productId: 1,
  productSearch: 'test-product',
  quantity: 5,
  note: '',
  deductStock: false,
  deductQuantity: 0,
  shipmentPlans: [],
} as FormState)

function mountPanel(): VueWrapper<InstanceType<typeof OrderInputPanel>> {
  return mount(OrderInputPanel, {
    global: {
      stubs: {
        ProductPickerDialog: { template: '<div class="stub-picker" />' },
      },
    },
    props: {
      form,
      isOrder: true,
      customerOptions: [],
      missingFields: [],
      availableStock: 0,
      deductInfoVisible: false,
      stockError: '',
      excelFile: null,
      importing: false,
      isDragOver: false,
      searchProducts: vi.fn(async () => []),
      productSearchFailed: false,
      fetchSkuList: vi.fn(async () => []),
      skuListError: '',
      selectProduct: vi.fn(),
      handleDeductPreview: vi.fn(),
      openDeductEdit: vi.fn(),
      handleExcelSelect: vi.fn(),
      onDrop: vi.fn(),
      downloadTemplate: vi.fn(),
      handleImport: vi.fn(),
      addStagedItems: vi.fn(),
    },
  })
}

describe('OrderInputPanel quantity validation', () => {
  it('does not flag the reset quantity after a successful add', async () => {
    const wrapper = mountPanel()
    const quantity = wrapper.find('#co-quantity')

    await quantity.setValue(10_000_000)
    expect(quantity.classes()).toContain('form-input-invalid')
    expect(wrapper.text()).toContain('数量必须介于 1 到 9,999,999 之间')

    form.quantity = 0
    wrapper.vm.resetQuantityValidation()
    await nextTick()

    expect(quantity.classes()).not.toContain('form-input-invalid')
    expect(wrapper.find('#co-quantity-error').exists()).toBe(false)
  })
})

describe('OrderInputPanel OCR 热区显隐', () => {
  function mountWith(isOrder: boolean) {
    return mount(OrderInputPanel, {
      global: {
        stubs: {
          ProductPickerDialog: { template: '<div class="stub-picker" />' },
          OcrPasteImport: { template: '<div class="stub-ocr" />' },
        },
      },
      props: {
        form: { ...form, type: isOrder ? 'order' : 'stockin' } as FormState,
        isOrder,
        customerOptions: [],
        missingFields: [],
        availableStock: 0,
        deductInfoVisible: false,
        stockError: '',
        excelFile: null,
        importing: false,
        isDragOver: false,
        searchProducts: vi.fn(async () => []),
        productSearchFailed: false,
        fetchSkuList: vi.fn(async () => []),
        skuListError: '',
        selectProduct: vi.fn(),
        handleDeductPreview: vi.fn(),
        openDeductEdit: vi.fn(),
        handleExcelSelect: vi.fn(),
        onDrop: vi.fn(),
        downloadTemplate: vi.fn(),
        handleImport: vi.fn(),
        addStagedItems: vi.fn(),
      },
    })
  }

  it('订单模式下显示粘贴识别热区', () => {
    expect(mountWith(true).find('.stub-ocr').exists()).toBe(true)
  })

  it('备货模式下不显示（本链路产出的一律是订单条目）', () => {
    // 回归：热区曾无条件渲染，而 OCR 条目硬编码 type='order'，
    // 于是备货模式下粘贴会造出订单记录
    expect(mountWith(false).find('.stub-ocr').exists()).toBe(false)
  })
})
