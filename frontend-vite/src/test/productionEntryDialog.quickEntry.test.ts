/**
 * 录入弹窗（方向 A）—— 布局、合计与「少录错 / 不重复建单」护栏。
 *
 * 核心契约：一张单 = 多行 SKU，底部一次提交；部分失败只保留失败的行；
 * 整批撤销必须先确认，且确认框要抬到嵌套层级。
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
const customerActiveNamesMock = vi.fn()

vi.mock('@/api', () => ({
  dailyProductionApi: {
    records: (...a: unknown[]) => recordsMock(...a),
    createRecord: (...a: unknown[]) => createMock(...a),
    deleteRecord: (...a: unknown[]) => deleteMock(...a),
    productInfo: (...a: unknown[]) => productInfoMock(...a),
  },
  customerApi: {
    activeNames: (...a: unknown[]) => customerActiveNamesMock(...a),
  },
  productApi: { search: (...a: unknown[]) => searchMock(...a) },
}))

vi.mock('@/composables/useToast', () => ({ showToast: vi.fn() }))

import ProductionEntryDialog from '@/views/production/components/ProductionEntryDialog.vue'
import CustomerSelect from '@/views/production/components/CustomerSelect.vue'
import UiConfirmDialog from '@/components/ui/UiConfirmDialog.vue'
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
    template:
      '<div v-if="open" data-test="undo-confirm">{{ text }}'
      + '<button data-test="undo-confirm-yes" @click="$emit(\'confirm\')">确认</button></div>',
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

/** 不 stub UiConfirmDialog 的挂载：层级断言只有挂真组件才有意义 */
function mountDialogRealConfirm() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  wrapper = mount(ProductionEntryDialog, {
    props: { open: true, selectedDate: '2026-09-30' },
    attachTo: document.body,
    global: { plugins: [[VueQueryPlugin, { queryClient }]] },
  })
  return wrapper
}

async function typeSearch(w: VueWrapper, text: string) {
  searchMock.mockResolvedValue({ products: PRODUCTS })
  const input = w.find('[data-test="qe-search"]')
  await input.setValue(text)
  await new Promise((resolve) => setTimeout(resolve, 320))
  await flushPromises()
}

/** 搜索后选中第 index 条（0 起），追加一行 */
async function selectProductAt(w: VueWrapper, index = 0) {
  await typeSearch(w, '白兔')
  const input = w.find('[data-test="qe-search"]')
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

function submitDisabled(w: VueWrapper) {
  return w.find('[data-test="qe-submit"]').attributes('disabled') !== undefined
}

beforeEach(() => {
  localStorage.clear()
  recordsMock.mockReset()
  createMock.mockReset()
  deleteMock.mockReset()
  productInfoMock.mockReset()
  searchMock.mockReset()
  customerActiveNamesMock.mockReset()
  customerActiveNamesMock.mockResolvedValue([{ id: 5, name: '客户A' }])
  // 无 keyword = 头部「今天已录 N 条」；带 keyword = 行级重复提示
  recordsMock.mockImplementation(async (params: { keyword?: string }) => {
    if (params?.keyword) {
      return {
        success: true, data: [], total: 1, page: 1, per_page: 50, pages: 1,
        stats: { total_quantity: 400, total_value: 0, total_sku: 1 },
      }
    }
    return { success: true, data: [], total: 3, page: 1, per_page: 50, pages: 1, stats: null }
  })
  createMock.mockResolvedValue({ success: true, message: 'ok', id: 42 })
  deleteMock.mockResolvedValue({ success: true, message: 'ok' })
  productInfoMock.mockImplementation(async (id: number) => ({
    success: true,
    data: { id, name: id === 2 ? '白兔公仔 60cm' : '白兔公仔 40cm', barcode: '6901234', price: 7 },
  }))
})

afterEach(() => {
  wrapper?.unmount()
  wrapper = null
  // 真 UiConfirmDialog 经 reka-ui 传送进 body，卸载后再清一次，避免串到下一个用例
  document.body.innerHTML = ''
})

describe('ProductionEntryDialog 布局与合计', () => {
  it('渲染部门分段 / 搜索 / 粘贴入口 / 合计 / 批量提交；空表有引导，默认无批次列', () => {
    const w = mountDialog()

    expect(w.find('[data-test="qe-dept"]').exists()).toBe(true)
    expect(w.find('[data-test="qe-search"]').exists()).toBe(true)
    expect(w.find('[data-test="qe-paste-open"]').exists()).toBe(true)
    expect(w.find('[data-test="qe-submit"]').exists()).toBe(true)
    expect(w.find('[data-test="qe-empty"]').exists()).toBe(true)
    expect(w.find('[data-test="qe-batch"]').exists()).toBe(false)
    expect(w.find('[data-test="qe-total-sku"]').text()).toBe('0')
  })

  it('头部显示「今天已录 N 条」（按选中日期取记录总数）', async () => {
    const w = mountDialog()
    await flushPromises()

    expect(w.find('.pr-qe-sub').text()).toContain('今天已录 3 条')
    expect(recordsMock).toHaveBeenCalledWith(expect.objectContaining({ production_date: '2026-09-30' }))
  })

  it('两行数量与单价汇总成合计件数与货值', async () => {
    const w = mountDialog()
    await selectProductAt(w, 0)
    await qtyAt(w, 0).setValue('10')
    await selectProductAt(w, 1)
    await qtyAt(w, 1).setValue('20')

    expect(w.find('[data-test="qe-total-sku"]').text()).toBe('2')
    expect(w.find('[data-test="qe-total-qty"]').text()).toBe('30')
    expect(w.find('[data-test="qe-total-value"]').text()).toBe('¥210.00')
  })

  it('删行后合计同步减少', async () => {
    const w = mountDialog()
    await selectProductAt(w, 0)
    await qtyAt(w, 0).setValue('10')
    await selectProductAt(w, 1)
    await qtyAt(w, 1).setValue('20')

    await w.findAll('[data-test="qe-remove"]')[0]!.trigger('click')

    expect(w.find('[data-test="qe-total-sku"]').text()).toBe('1')
    expect(w.find('[data-test="qe-total-qty"]').text()).toBe('20')
  })

  it('选品后单价自动带出到行内（可改）', async () => {
    const w = mountDialog()
    await selectProductAt(w, 0)

    const price = w.find('[data-test="qe-price"]').element as HTMLInputElement
    expect(price.value).toBe('7')
  })

  it('点「最近使用」chip 追加一行并带出单价', async () => {
    localStorage.setItem('production.recentProducts', JSON.stringify([{ id: 9, name: '熊猫抱枕', barcode: '699' }]))
    productInfoMock.mockResolvedValue({ success: true, data: { id: 9, name: '熊猫抱枕', barcode: '699', price: 12 } })
    const w = mountDialog()

    await w.find('[data-test="qe-recent"]').trigger('click')
    await flushPromises()

    expect(w.find('[data-test="qe-row"]').text()).toContain('熊猫抱枕')
    expect((w.find('[data-test="qe-price"]').element as HTMLInputElement).value).toBe('12')
  })

  it('改日期会 emit update:selectedDate（对外契约不变）', async () => {
    const w = mountDialog()
    await w.find('[data-test="qe-date"]').setValue('2026-09-29')

    expect(w.emitted('update:selectedDate')).toEqual([['2026-09-29']])
  })

  it('部门默认取上次使用的部门，点分段按钮后写回 localStorage', async () => {
    localStorage.setItem('production.lastDepartment', 'packaging')
    const w = mountDialog()
    expect(w.find('[data-test="qe-dept"] .pr-qe-seg-btn.on').text()).toContain('包装部')

    await w.find('[data-dept="handcraft"]').trigger('click')

    expect(localStorage.getItem('production.lastDepartment')).toBe('handcraft')
  })
})

describe('ProductionEntryDialog 提交护栏', () => {
  it('空表或有行数量为 0 时批量提交禁用', async () => {
    const w = mountDialog()
    expect(submitDisabled(w)).toBe(true)

    await selectProductAt(w, 0)
    expect(submitDisabled(w)).toBe(true) // 新行数量仍是 0

    await qtyAt(w, 0).setValue('5')
    expect(submitDisabled(w)).toBe(false)

    await selectProductAt(w, 1)
    expect(submitDisabled(w)).toBe(true) // 第二行还没填数量，整单不许提交
  })

  it('连按两次 Ctrl+⏎ 只提交一批，提交中按钮禁用', async () => {
    const w = mountDialog()
    await selectProductAt(w, 0)
    await qtyAt(w, 0).setValue('10')

    let release!: (v: unknown) => void
    createMock.mockImplementation(() => new Promise((resolve) => { release = resolve }))

    const modal = w.find('.pr-qe-modal')
    modal.element.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', ctrlKey: true, bubbles: true }))
    modal.element.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', ctrlKey: true, bubbles: true }))
    await nextTick()

    expect(createMock).toHaveBeenCalledTimes(1)
    expect(submitDisabled(w)).toBe(true)

    release({ success: true, message: 'ok', id: 42 })
    await flushPromises()
  })

  it('选中产品后查询今日同部门同产品已录数量，命中则在行内提示——只提示，不阻断', async () => {
    const w = mountDialog()
    await selectProductAt(w, 0)
    await flushPromises()

    expect(recordsMock).toHaveBeenCalledWith(expect.objectContaining({
      production_date: '2026-09-30',
      department: 'filling',
      keyword: '白兔公仔 40cm',
    }))
    expect(w.find('[data-test="qe-dup"]').text()).toContain('今日已录 400')

    await qtyAt(w, 0).setValue('10')
    expect(submitDisabled(w)).toBe(false)
  })

  it('两行一起提交：逐条创建、带上 customer_id，成功后进入完成态', async () => {
    const w = mountDialog()
    await flushPromises()
    w.findComponent(CustomerSelect).vm.$emit('update:modelValue', 5)
    await nextTick()

    await selectProductAt(w, 0)
    await qtyAt(w, 0).setValue('10')
    await selectProductAt(w, 1)
    await qtyAt(w, 1).setValue('20')

    await w.find('[data-test="qe-submit"]').trigger('click')
    await flushPromises()

    expect(createMock).toHaveBeenCalledTimes(2)
    const payloads = createMock.mock.calls.map((c) => c[0] as Record<string, unknown>)
    expect(payloads[0]).toMatchObject({ product_name: '白兔公仔 40cm', quantity: 10, customer_id: 5 })
    expect(payloads[1]).toMatchObject({ product_name: '白兔公仔 60cm', quantity: 20, customer_id: 5 })
    expect(w.find('[data-test="qe-done"]').exists()).toBe(true)
    expect(w.find('[data-test="qe-done"]').text()).toContain('已录入 2 条生产记录')
    expect(w.find('[data-test="qe-submit"]').exists()).toBe(false)
  })

  it('部分失败：成功的行不再重复建单，只把失败的行留在表里并透出后端原因', async () => {
    const w = mountDialog()
    await selectProductAt(w, 0)
    await qtyAt(w, 0).setValue('10')
    await selectProductAt(w, 1)
    await qtyAt(w, 1).setValue('20')

    createMock
      .mockResolvedValueOnce({ success: true, message: 'ok', id: 42 })
      .mockRejectedValueOnce({ response: { data: { detail: '数量超出当班上限' } } })

    await w.find('[data-test="qe-submit"]').trigger('click')
    await flushPromises()

    expect(createMock).toHaveBeenCalledTimes(2)
    expect(w.findAll('[data-test="qe-row"]').length).toBe(1)
    expect(w.find('[data-test="qe-row"]').text()).toContain('白兔公仔 60cm')
    expect(w.find('[data-test="qe-row-error"]').text()).toContain('数量超出当班上限')
    expect(w.find('[data-test="qe-done"]').exists()).toBe(false)
  })

  it('完成态撤销整批：先弹确认框，确认后逐条物理删除并回到录入态', async () => {
    const w = mountDialog()
    await selectProductAt(w, 0)
    await qtyAt(w, 0).setValue('620')
    createMock.mockResolvedValueOnce({ success: true, message: 'ok', id: 42 })

    await w.find('[data-test="qe-submit"]').trigger('click')
    await flushPromises()
    expect(w.find('[data-test="qe-done"]').exists()).toBe(true)

    await w.find('[data-test="qe-undo"]').trigger('click')
    await nextTick()
    expect(deleteMock).not.toHaveBeenCalled()

    const confirm = w.findComponent({ name: 'UiConfirmDialog' })
    expect(confirm.props('open')).toBe(true)
    expect(confirm.props('text')).toContain('白兔公仔 40cm')

    await w.find('[data-test="undo-confirm-yes"]').trigger('click')
    await flushPromises()

    expect(deleteMock).toHaveBeenCalledWith(42)
    expect(w.find('[data-test="qe-done"]').exists()).toBe(false)
    expect(w.find('[data-test="qe-submit"]').exists()).toBe(true)
  })

  it('撤销确认框被抬到嵌套层级——沿用默认层级会被录入弹窗盖住，点不到', async () => {
    const w = mountDialogRealConfirm()
    await selectProductAt(w, 0)
    await qtyAt(w, 0).setValue('620')
    await w.find('[data-test="qe-submit"]').trigger('click')
    await flushPromises()

    await w.find('[data-test="qe-undo"]').trigger('click')
    await nextTick()

    const confirm = w.findComponent(UiConfirmDialog)
    expect(confirm.props('open')).toBe(true)
    expect(confirm.props('overlayZClass')).toBe('z-[var(--z-overlay-nested)]')
    expect(confirm.props('contentZClass')).toBe('z-[var(--z-modal-nested)]')
  })

  it('撤销失败时透出后端的 detail（物理删除失败的原因必须可见）', async () => {
    const w = mountDialog()
    await selectProductAt(w, 0)
    await qtyAt(w, 0).setValue('620')
    await w.find('[data-test="qe-submit"]').trigger('click')
    await flushPromises()

    deleteMock.mockRejectedValueOnce({ response: { data: { detail: '记录已被他人删除' } } })
    await w.find('[data-test="qe-undo"]').trigger('click')
    await w.find('[data-test="undo-confirm-yes"]').trigger('click')
    await flushPromises()

    expect(showToast).toHaveBeenCalledWith('记录已被他人删除', 'error')
  })
})
