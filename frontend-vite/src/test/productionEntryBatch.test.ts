/**
 * 录入弹窗（方向 A）—— 批次号列、按客户记住批次要求、粘贴导入、草稿。
 *
 * 批次规则：
 *  - 包装部：批次列自动出现，但保持旧行为「选填」
 *  - 其它部门：默认没有批次列；用户打开开关 = 这单要批次 → 必填，并按客户记住
 */
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import { nextTick } from 'vue'
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'

const recordsMock = vi.fn()
const createMock = vi.fn()
const deleteMock = vi.fn()
const productInfoMock = vi.fn()
const searchMock = vi.fn()
const productListMock = vi.fn()
const customerActiveNamesMock = vi.fn()

vi.mock('@/api', () => ({
  dailyProductionApi: {
    records: (...a: unknown[]) => recordsMock(...a),
    createRecord: (...a: unknown[]) => createMock(...a),
    deleteRecord: (...a: unknown[]) => deleteMock(...a),
    productInfo: (...a: unknown[]) => productInfoMock(...a),
  },
  customerApi: { activeNames: (...a: unknown[]) => customerActiveNamesMock(...a) },
  productApi: {
    search: (...a: unknown[]) => searchMock(...a),
    list: (...a: unknown[]) => productListMock(...a),
  },
}))

vi.mock('@/composables/useToast', () => ({ showToast: vi.fn() }))

import ProductionEntryDialog from '@/views/production/components/ProductionEntryDialog.vue'
import CustomerSelect from '@/views/production/components/CustomerSelect.vue'
import { showToast } from '@/composables/useToast'

const PRODUCTS = [
  { id: 1, name: '白兔公仔 40cm', barcode: '6901234', specification: '40cm' },
  { id: 2, name: '白兔公仔 60cm', barcode: '6901235', specification: '60cm' },
]

const stubs = {
  UiConfirmDialog: {
    name: 'UiConfirmDialog',
    props: ['open', 'text'],
    emits: ['confirm', 'cancel'],
    template: '<div v-if="open" data-test="undo-confirm">{{ text }}</div>',
  },
}

let wrapper: VueWrapper | null = null

function mountDialog() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  wrapper = mount(ProductionEntryDialog, {
    props: { open: true, selectedDate: '2026-09-30' },
    attachTo: document.body,
    global: { plugins: [[VueQueryPlugin, { queryClient }]], stubs },
  })
  return wrapper
}

async function selectProductAt(w: VueWrapper, index = 0) {
  searchMock.mockResolvedValue({ products: PRODUCTS })
  productListMock.mockResolvedValue({ items: PRODUCTS, total: PRODUCTS.length })
  const input = w.find('[data-test="qe-search"]')
  await input.setValue('白兔')
  await new Promise((resolve) => setTimeout(resolve, 320))
  await flushPromises()
  for (let i = 0; i <= index; i += 1) {
    await input.trigger('keydown', { key: 'ArrowDown' })
  }
  await input.trigger('keydown', { key: 'Enter' })
  await flushPromises()
}

function qtyAt(w: VueWrapper, index: number) {
  const input = w.findAll('[data-test="qe-qty"]')[index]
  if (!input) throw new Error(`数量输入缺失: index=${index}`)
  return input
}

function batchAt(w: VueWrapper, index: number) {
  const input = w.findAll('[data-test="qe-batch"]')[index]
  if (!input) throw new Error(`批次输入缺失: index=${index}`)
  return input
}

beforeEach(() => {
  localStorage.clear()
  recordsMock.mockReset()
  createMock.mockReset()
  deleteMock.mockReset()
  productInfoMock.mockReset()
  searchMock.mockReset()
  productListMock.mockReset()
  customerActiveNamesMock.mockReset()
  customerActiveNamesMock.mockResolvedValue([
    { id: 5, name: '客户A' },
    { id: 6, name: '客户B' },
  ])
  recordsMock.mockResolvedValue({ success: true, data: [], total: 3, page: 1, per_page: 50, pages: 1, stats: null })
  createMock.mockResolvedValue({ success: true, message: 'ok', id: 42 })
  deleteMock.mockResolvedValue({ success: true, message: 'ok' })
  productInfoMock.mockResolvedValue({ success: true, data: { id: 1, name: '白兔公仔 40cm', barcode: '6901234', price: 7 } })
})

afterEach(() => {
  wrapper?.unmount()
  wrapper = null
  document.body.innerHTML = ''
})

describe('批次号列', () => {
  it('包装部自动出现批次列，但仍是选填（不填也能提交）', async () => {
    const w = mountDialog()
    await w.find('[data-dept="packaging"]').trigger('click')
    await selectProductAt(w, 0)
    await qtyAt(w, 0).setValue('10')

    expect(w.find('[data-test="qe-batch"]').exists()).toBe(true)
    expect(w.find('[data-test="qe-banner"]').exists()).toBe(true)

    await w.find('[data-test="qe-submit"]').trigger('click')
    await flushPromises()

    expect(createMock).toHaveBeenCalledTimes(1)
    expect(createMock.mock.calls[0]?.[0]).toMatchObject({ department: 'packaging', batch_no: null })
  })

  it('充棉部默认没有批次列；打开开关后出现并要求必填，空批次会被拦下', async () => {
    const w = mountDialog()
    await selectProductAt(w, 0)
    await qtyAt(w, 0).setValue('10')
    expect(w.find('[data-test="qe-batch"]').exists()).toBe(false)

    await w.find('[data-test="qe-batch-switch"]').setValue(true)
    expect(w.find('[data-test="qe-batch"]').exists()).toBe(true)

    await w.find('[data-test="qe-submit"]').trigger('click')
    await flushPromises()

    expect(createMock).not.toHaveBeenCalled()
    expect(w.find('[data-test="qe-row-error"]').text()).toContain('批次号')

    await batchAt(w, 0).setValue('B20261101')
    await w.find('[data-test="qe-submit"]').trigger('click')
    await flushPromises()

    expect(createMock).toHaveBeenCalledTimes(1)
    expect(createMock.mock.calls[0]?.[0]).toMatchObject({ batch_no: 'B20261101' })
  })

  it('「铺满空行」把第一行的批次号铺到其它空行', async () => {
    const w = mountDialog()
    await w.find('[data-test="qe-batch-switch"]').setValue(true)
    await selectProductAt(w, 0)
    await selectProductAt(w, 1)
    await batchAt(w, 0).setValue('B001')

    await w.find('[data-test="qe-fill-batch"]').trigger('click')

    expect((batchAt(w, 0).element as HTMLInputElement).value).toBe('B001')
    expect((batchAt(w, 1).element as HTMLInputElement).value).toBe('B001')
    // 填满后状态标签自己消失，不再白占一行
    expect(w.find('[data-test="qe-banner"]').exists()).toBe(false)
  })

  it('批次状态是行内小标签：填满即消失，也不再单独占一行放「铺满空行」', async () => {
    const w = mountDialog()
    await w.find('[data-test="qe-batch-switch"]').setValue(true)
    await selectProductAt(w, 0)
    await selectProductAt(w, 1)

    expect(w.find('[data-test="qe-banner"]').text()).toContain('批次 0/2')
    expect(w.find('[data-test="qe-banner-fill"]').exists()).toBe(false)

    await batchAt(w, 0).setValue('B001')
    expect(w.find('[data-test="qe-banner"]').text()).toContain('批次 1/2')

    await batchAt(w, 1).setValue('B001')
    expect(w.find('[data-test="qe-banner"]').exists()).toBe(false)
  })

  it('批次开关按客户记住：客户A 打开后，换到客户B 不带上，回来自动恢复', async () => {
    const w = mountDialog()
    await flushPromises()

    w.findComponent(CustomerSelect).vm.$emit('update:modelValue', 5)
    await nextTick()
    await w.find('[data-test="qe-batch-switch"]').setValue(true)
    expect(localStorage.getItem('production.batchCustomers')).toContain('"5":true')

    w.findComponent(CustomerSelect).vm.$emit('update:modelValue', 6)
    await nextTick()
    expect((w.find('[data-test="qe-batch-switch"]').element as HTMLInputElement).checked).toBe(false)

    w.findComponent(CustomerSelect).vm.$emit('update:modelValue', 5)
    await nextTick()
    expect((w.find('[data-test="qe-batch-switch"]').element as HTMLInputElement).checked).toBe(true)
  })

  it('无客户时打开的开关不会泄漏到没记住的客户身上', async () => {
    const w = mountDialog()
    await w.find('[data-test="qe-batch-switch"]').setValue(true)
    expect((w.find('[data-test="qe-batch-switch"]').element as HTMLInputElement).checked).toBe(true)

    await flushPromises()
    w.findComponent(CustomerSelect).vm.$emit('update:modelValue', 6)
    await nextTick()

    // 客户B 没有批次要求：回到部门默认（充棉部 = 不显示），不能沿用上一个临时开关
    expect((w.find('[data-test="qe-batch-switch"]').element as HTMLInputElement).checked).toBe(false)
  })

  it('重新打开弹窗后，该客户的批次要求仍然生效', async () => {
    localStorage.setItem('production.batchCustomers', JSON.stringify({ 5: true }))
    const w = mountDialog()
    await flushPromises()

    w.findComponent(CustomerSelect).vm.$emit('update:modelValue', 5)
    await nextTick()
    await selectProductAt(w, 0)

    expect(w.find('[data-test="qe-batch"]').exists()).toBe(true)
    expect(w.find('[data-test="qe-banner"]').text()).toContain('必填')
  })

  it('包装部标了定制就必须填定制国家（与后端同口径）', async () => {
    const w = mountDialog()
    await w.find('[data-dept="packaging"]').trigger('click')
    await selectProductAt(w, 0)
    await qtyAt(w, 0).setValue('10')
    await w.find('[data-test="qe-custom"]').setValue(true)

    await w.find('[data-test="qe-submit"]').trigger('click')
    await flushPromises()
    expect(createMock).not.toHaveBeenCalled()
    expect(w.find('[data-test="qe-row-error"]').text()).toContain('定制国家')

    await w.find('[data-test="qe-country"]').setValue('美国')
    await w.find('[data-test="qe-submit"]').trigger('click')
    await flushPromises()
    expect(createMock.mock.calls[0]?.[0]).toMatchObject({ is_custom: true, custom_country: '美国' })
  })
})

describe('粘贴导入', () => {
  it('精确匹配的行进入清单并带上数量与批次，匹配不上的不进单', async () => {
    searchMock.mockResolvedValue({ products: PRODUCTS })
    const w = mountDialog()
    await w.find('[data-test="qe-paste-open"]').trigger('click')
    await w.find('[data-test="qe-paste-text"]').setValue('白兔公仔 40cm\t120\tB001\n不存在的产品\t50')
    await w.find('[data-test="qe-paste-ok"]').trigger('click')
    await flushPromises()

    expect(w.findAll('[data-test="qe-row"]').length).toBe(1)
    expect((qtyAt(w, 0).element as HTMLInputElement).value).toBe('120')
    expect(w.find('[data-test="qe-paste"]').exists()).toBe(false)
    expect(showToast).toHaveBeenCalledWith(expect.stringContaining('未精确匹配'), 'warning')
  })
})

describe('草稿', () => {
  it('存草稿后重新打开弹窗能恢复未提交的 SKU', async () => {
    const w = mountDialog()
    await selectProductAt(w, 0)
    await qtyAt(w, 0).setValue('88')

    await w.find('[data-test="qe-draft"]').trigger('click')
    expect(localStorage.getItem('production.entryDraft')).toContain('白兔公仔 40cm')

    w.unmount()
    const again = mountDialog()
    await flushPromises()

    expect(again.findAll('[data-test="qe-row"]').length).toBe(1)
    expect((again.find('[data-test="qe-qty"]').element as HTMLInputElement).value).toBe('88')
  })

  it('跨日期的草稿不恢复（避免把昨天的数量记到今天）', async () => {
    localStorage.setItem('production.entryDraft', JSON.stringify({
      date: '2026-09-29',
      department: 'filling',
      customer_id: null,
      customer_name: '',
      rows: [{ product_id: 1, product_name: '白兔公仔 40cm', quantity: 50 }],
    }))
    const w = mountDialog()
    await flushPromises()

    expect(w.findAll('[data-test="qe-row"]').length).toBe(0)
    expect(showToast).toHaveBeenCalledWith(expect.stringContaining('未恢复'), 'info')
  })

  it('提交成功后清掉草稿，不会把上一批又恢复回来', async () => {
    const w = mountDialog()
    await selectProductAt(w, 0)
    await qtyAt(w, 0).setValue('10')
    await w.find('[data-test="qe-draft"]').trigger('click')

    await w.find('[data-test="qe-submit"]').trigger('click')
    await flushPromises()

    expect(localStorage.getItem('production.entryDraft')).toBeNull()
  })
})
