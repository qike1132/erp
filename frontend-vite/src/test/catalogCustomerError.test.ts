/**
 * 客户下拉的错误态（2026-10-30 审计 A-M34）
 *
 * 现场：下单页与出库页都用 `ensureActiveCustomerNames().catch(() => {})` 拉客户下拉，
 * 失败被静默吞掉。客户是必填项，加载失败时下拉是空的、选不出任何值，界面却与
 * 「系统里没有客户」完全同形 —— 用户零提示，也不知道可以重试。
 * 这里锁三件事：store 记录失败、成功后清除、两个入口据此暴露可重试的错误态。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { reactive } from 'vue'
import { mount } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'

const mocks = vi.hoisted(() => ({
  activeNamesMock: vi.fn(),
  productSearchMock: vi.fn(async () => [] as unknown[]),
  productListMock: vi.fn(async () => ({ items: [], total: 0 })),
  supplierListMock: vi.fn(async () => ({ suppliers: [], total: 0 })),
}))

vi.mock('@/api', () => ({
  auxApi: { productSearch: mocks.productSearchMock },
  customerApi: { activeNames: mocks.activeNamesMock },
  productApi: { list: mocks.productListMock },
  supplierApi: { list: mocks.supplierListMock },
}))

import { useCatalogStore } from '@/stores/catalog'
import { useOrderForm } from '@/views/customer-order/composables/useOrderForm'
import OrderInputPanel from '@/views/customer-order/components/OrderInputPanel.vue'
import type { FormState } from '@/views/customer-order/composables/types'

describe('catalog store 客户下拉错误态', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('加载失败置 error，成功后清除', async () => {
    mocks.activeNamesMock.mockRejectedValueOnce(new Error('500'))
    const store = useCatalogStore()

    await store.ensureActiveCustomerNames().catch(() => {})
    expect(store.activeCustomerNamesError).toBe(true)
    expect(store.activeCustomerNames).toEqual([])

    mocks.activeNamesMock.mockResolvedValueOnce([{ id: 1, name: '贝乐' }])
    await store.ensureActiveCustomerNames(true)

    expect(store.activeCustomerNamesError).toBe(false)
    expect(store.activeCustomerNames).toEqual([{ id: 1, name: '贝乐' }])
  })

  it('失败仍然向上抛出，调用方原有的 catch 语义不变', async () => {
    mocks.activeNamesMock.mockRejectedValueOnce(new Error('500'))
    const store = useCatalogStore()

    await expect(store.ensureActiveCustomerNames()).rejects.toThrow('500')
  })

  it('clear() 一并清除错误态（登出后不把上一次会话的失败带给下一个用户）', async () => {
    mocks.activeNamesMock.mockRejectedValueOnce(new Error('500'))
    const store = useCatalogStore()
    await store.ensureActiveCustomerNames().catch(() => {})
    expect(store.activeCustomerNamesError).toBe(true)

    store.clear()

    expect(store.activeCustomerNamesError).toBe(false)
    expect(store.activeCustomerNames).toEqual([])
  })

  it('TTL 内的成功结果不会重新请求，错误态保持清除', async () => {
    mocks.activeNamesMock.mockResolvedValueOnce([{ id: 1, name: '贝乐' }])
    const store = useCatalogStore()

    await store.ensureActiveCustomerNames()
    await store.ensureActiveCustomerNames()

    expect(mocks.activeNamesMock).toHaveBeenCalledTimes(1)
    expect(store.activeCustomerNamesError).toBe(false)
  })
})

describe('useOrderForm 客户下拉错误态', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  /** 首屏加载是 fire-and-forget：用一个宏任务把整条 promise 链跑干净 */
  const flush = () => new Promise((resolve) => setTimeout(resolve, 0))

  it('store 加载失败时暴露 customerOptionsError，retryCustomers 成功后清除', async () => {
    mocks.activeNamesMock.mockRejectedValueOnce(new Error('500'))
    mocks.activeNamesMock.mockResolvedValueOnce([{ id: 1, name: '贝乐' }])

    const { customerOptionsError, customerOptions, retryCustomers } = useOrderForm()
    await flush()

    expect(customerOptionsError.value).toBe(true)
    expect(customerOptions.value).toEqual([])

    await retryCustomers()

    expect(customerOptionsError.value).toBe(false)
    expect(customerOptions.value).toEqual([{ value: '贝乐', label: '贝乐' }])
  })

  it('加载成功时不显示错误态', async () => {
    mocks.activeNamesMock.mockResolvedValueOnce([{ id: 1, name: '贝乐' }])

    const { customerOptionsError } = useOrderForm()
    await flush()

    expect(customerOptionsError.value).toBe(false)
  })
})

describe('下单面板的客户下拉错误提示（渲染）', () => {
  const form = reactive({
    type: 'order',
    date: '2026-10-30',
    customer: '',
    productId: 0,
    productSearch: '',
    quantity: 0,
    deductStock: false,
    deductQuantity: 0,
    note: '',
    shipmentPlans: [],
  } as FormState)

  function mountPanel(customerOptionsError: boolean) {
    return mount(OrderInputPanel, {
      global: { stubs: { UiAutocomplete: { template: '<input />' } } },
      props: {
        form,
        isOrder: true,
        customerOptions: [],
        customerOptionsError,
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

  it('加载失败时给出可读提示与重试按钮，点击后发出重试事件', async () => {
    const wrapper = mountPanel(true)

    const alert = wrapper.find('[role="alert"]')
    expect(alert.exists()).toBe(true)
    expect(alert.text()).toContain('客户列表加载失败')

    await alert.find('button').trigger('click')
    expect(wrapper.emitted('retry-customers')).toHaveLength(1)
  })

  it('加载正常时不显示任何告警', () => {
    const wrapper = mountPanel(false)

    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
  })
})
