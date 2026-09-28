import { describe, it, expect, vi } from 'vitest'
import { mount, VueWrapper } from '@vue/test-utils'
import OrderInputPanel from '@/views/customer-order/components/OrderInputPanel.vue'
import type { FormState } from '@/views/customer-order/composables/types'

const form = reactive({
  id: 0,
  type: 'order',
  orderType: 'normal',
  date: '2026-09-28',
  customer: 'test-customer',
  productId: 1,
  productSearch: 'test-product',
  quantity: 5,
  note: '',
  country: '',
  deductStock: false,
  deductQuantity: 0,
} as FormState)

function mountPanel(): VueWrapper<InstanceType<typeof OrderInputPanel>> {
  return mount(OrderInputPanel, {
    global: {
      stubs: {
        UiAutocomplete: { template: '<input />' },
      },
    },
    props: {
      form,
      isOrder: true,
      isCustomOrder: false,
      orderTypeOptions: [],
      customerOptions: [],
      countryOptions: [],
      missingFields: [],
      availableStock: 0,
      deductInfoVisible: false,
      stockError: '',
      excelFile: null,
      importing: false,
      isDragOver: false,
      searchProducts: vi.fn(async () => []),
      productSearchFailed: false,
      selectProduct: vi.fn(),
      handleDeductPreview: vi.fn(),
      openDeductEdit: vi.fn(),
      openCountryDialog: vi.fn(),
      handleExcelSelect: vi.fn(),
      onDrop: vi.fn(),
      downloadTemplate: vi.fn(),
      handleImport: vi.fn(),
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
