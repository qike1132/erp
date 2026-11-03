/**
 * 录入弹窗（方向 A）—— 布局、合计与「少录错 / 不重复建单」护栏。
 *
 * 核心契约：一张单 = 多行 SKU，底部一次提交；部分失败只保留失败的行；
 * 整批撤销必须先确认（物理删除不可恢复）。
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
  customerApi: {
    activeNames: (...a: unknown[]) => customerActiveNamesMock(...a),
  },
  productApi: {
    search: (...a: unknown[]) => searchMock(...a),
    list: (...a: unknown[]) => productListMock(...a),
  },
}))

vi.mock('@/composables/useToast', () => ({ showToast: vi.fn() }))

import ProductionEntryPanel from '@/views/production/components/ProductionEntryPanel.vue'
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

/** 客户是必填项：提交前统一选一个客户 */
async function pickCustomerForSubmit(w: VueWrapper) {
  await flushPromises()
  w.findComponent(CustomerSelect).vm.$emit('update:modelValue', 5)
  await nextTick()
}

function mountDialog() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  wrapper = mount(ProductionEntryPanel, {
    props: { open: true, selectedDate: '2026-09-30' },
    attachTo: document.body,
    global: { plugins: [[VueQueryPlugin, { queryClient }]], stubs },
  })
  return wrapper
}

/** 不 stub UiConfirmDialog 的挂载：层级断言只有挂真组件才有意义 */
function mountDialogRealConfirm() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  wrapper = mount(ProductionEntryPanel, {
    props: { open: true, selectedDate: '2026-09-30' },
    attachTo: document.body,
    global: { plugins: [[VueQueryPlugin, { queryClient }]] },
  })
  return wrapper
}

async function typeSearch(w: VueWrapper, text: string) {
  searchMock.mockResolvedValue({ products: PRODUCTS })
  // 选了客户后搜索走 /products/list —— 两个入口都要给数据，否则「先选客户再加行」会静默空转
  productListMock.mockResolvedValue({ items: PRODUCTS, total: PRODUCTS.length })
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
  productListMock.mockReset()
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
  })

  it('打开时按选中日期取当日记录总数', async () => {
    mountDialog()
    await flushPromises()

    expect(recordsMock).toHaveBeenCalledWith(expect.objectContaining({ production_date: '2026-09-30' }))
  })

  it('多行的件数与货值按行汇总进提交 payload', async () => {
    const w = mountDialog()
    await selectProductAt(w, 0)
    await qtyAt(w, 0).setValue('10')
    await selectProductAt(w, 1)
    await qtyAt(w, 1).setValue('20')

    await pickCustomerForSubmit(w)
    await w.find('[data-test="qe-submit"]').trigger('click')
    await flushPromises()

    expect(createMock).toHaveBeenCalledTimes(2)
    expect(createMock.mock.calls[0]?.[0]).toMatchObject({ quantity: 10, production_value: 70 })
    expect(createMock.mock.calls[1]?.[0]).toMatchObject({ quantity: 20, production_value: 140 })
  })

  it('删行后清单同步减少', async () => {
    const w = mountDialog()
    await selectProductAt(w, 0)
    await qtyAt(w, 0).setValue('10')
    await selectProductAt(w, 1)
    await qtyAt(w, 1).setValue('20')

    await w.findAll('[data-test="qe-remove"]')[0]!.trigger('click')

    expect(w.findAll('[data-test="qe-row"]').length).toBe(1)
    expect(w.find('[data-test="qe-row"]').text()).toContain('白兔公仔 60cm')
  })

  it('单价还没回来时不允许提交（否则 unit_price=0 会静默入库）', async () => {
    productInfoMock.mockReturnValue(new Promise(() => {}))
    const w = mountDialog()
    await pickCustomerForSubmit(w)
    await selectProductAt(w, 0)
    await qtyAt(w, 0).setValue('10')

    expect(submitDisabled(w)).toBe(true)
  })

  it('单价自动带出且不再行内显示（随行上报，货值照算）', async () => {
    const w = mountDialog()
    await selectProductAt(w, 0)

    expect(w.find('[data-test="qe-price"]').exists()).toBe(false)

    await qtyAt(w, 0).setValue('10')
    await pickCustomerForSubmit(w)
    await w.find('[data-test="qe-submit"]').trigger('click')
    await flushPromises()

    expect(createMock).toHaveBeenCalledTimes(1)
    expect(createMock.mock.calls[0]?.[0]).toMatchObject({ unit_price: 7, quantity: 10 })
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
    await pickCustomerForSubmit(w)
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
    await pickCustomerForSubmit(w)
    await selectProductAt(w, 0)
    await qtyAt(w, 0).setValue('10')

    let release!: (v: unknown) => void
    createMock.mockImplementation(() => new Promise((resolve) => { release = resolve }))

    const modal = w.find('.pr-qe-page')
    modal.element.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', ctrlKey: true, bubbles: true }))
    modal.element.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', ctrlKey: true, bubbles: true }))
    await nextTick()

    expect(createMock).toHaveBeenCalledTimes(1)
    expect(submitDisabled(w)).toBe(true)

    release({ success: true, message: 'ok', id: 42 })
    await flushPromises()
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

    await pickCustomerForSubmit(w)
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

    await pickCustomerForSubmit(w)
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

    await pickCustomerForSubmit(w)
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

  it('撤销确认框在整页面板下用默认层级即可（页面没有 z-modal 竞争，无需再抬层）', async () => {
    const w = mountDialogRealConfirm()
    await selectProductAt(w, 0)
    await qtyAt(w, 0).setValue('620')
    await pickCustomerForSubmit(w)
    await w.find('[data-test="qe-submit"]').trigger('click')
    await flushPromises()

    await w.find('[data-test="qe-undo"]').trigger('click')
    await nextTick()

    const confirm = w.findComponent(UiConfirmDialog)
    expect(confirm.props('open')).toBe(true)
    expect(confirm.props('overlayZClass')).toBeUndefined()
    expect(confirm.props('contentZClass')).toBeUndefined()
  })

  it('撤销失败时透出后端的 detail（物理删除失败的原因必须可见）', async () => {
    const w = mountDialog()
    await selectProductAt(w, 0)
    await qtyAt(w, 0).setValue('620')
    await pickCustomerForSubmit(w)
    await w.find('[data-test="qe-submit"]').trigger('click')
    await flushPromises()

    deleteMock.mockRejectedValueOnce({ response: { data: { detail: '记录已被他人删除' } } })
    await w.find('[data-test="qe-undo"]').trigger('click')
    await w.find('[data-test="undo-confirm-yes"]').trigger('click')
    await flushPromises()

    expect(showToast).toHaveBeenCalledWith('记录已被他人删除', 'error')
  })
})

describe('按客户带出产品', () => {
  async function pickCustomer(w: VueWrapper, id: number) {
    await flushPromises()
    w.findComponent(CustomerSelect).vm.$emit('update:modelValue', id)
    await nextTick()
  }

  it('没选客户时聚焦搜索框不会主动拉列表', async () => {
    const w = mountDialog()
    await flushPromises()

    await w.find('[data-test="qe-search"]').trigger('focus')
    await flushPromises()

    expect(productListMock).not.toHaveBeenCalled()
  })

  it('选了客户后点击搜索框，直接列出该客户可见的产品', async () => {
    const w = mountDialog()
    await pickCustomer(w, 5)
    productListMock.mockResolvedValue({ items: PRODUCTS, total: 2 })

    await w.find('[data-test="qe-search"]').trigger('click')
    await flushPromises()

    expect(productListMock).toHaveBeenCalledWith(expect.objectContaining({ customer_id: 5, page: 1 }))
    expect(w.findAll('.pr-entry-dropdown-item').length).toBe(2)
    expect(w.find('.pr-entry-dropdown-hint').text()).toContain('客户A')
  })

  it('输入关键字后按客户过滤查询，不再走全库搜索', async () => {
    const w = mountDialog()
    await pickCustomer(w, 5)
    productListMock.mockResolvedValue({ items: PRODUCTS, total: 2 })

    const input = w.find('[data-test="qe-search"]')
    await input.setValue('白兔')
    await new Promise((resolve) => setTimeout(resolve, 320))
    await flushPromises()

    expect(productListMock).toHaveBeenCalledWith(expect.objectContaining({ customer_id: 5, search: '白兔' }))
    expect(searchMock).not.toHaveBeenCalled()
  })

  it('换客户后立刻改查新客户的产品，不留上一个客户的结果', async () => {
    const w = mountDialog()
    await pickCustomer(w, 5)
    productListMock.mockResolvedValue({ items: PRODUCTS, total: 2 })
    await w.find('[data-test="qe-search"]').trigger('click')
    await flushPromises()

    productListMock.mockResolvedValue({ items: [PRODUCTS[0]!], total: 1 })
    await pickCustomer(w, 6)
    await flushPromises()

    expect(productListMock).toHaveBeenLastCalledWith(expect.objectContaining({ customer_id: 6 }))
    expect(w.findAll('.pr-entry-dropdown-item').length).toBe(1)
  })
})

describe('右侧「最近客户添加」', () => {
  const RECORDS = [
    {
      id: 1, department: 'filling', product_id: 1, customer_id: 5, customer_name: '客户A',
      product_name: '白兔公仔 40cm', barcode: '6901234', unit_price: 7, quantity: 120,
      production_value: 840, production_date: '2026-09-28',
    },
    {
      id: 2, department: 'filling', product_id: 2, customer_id: 6, customer_name: '客户B',
      product_name: '白兔公仔 60cm', barcode: '6901235', unit_price: 7, quantity: 80,
      production_value: 560, production_date: '2026-09-28',
    },
    {
      id: 3, department: 'filling', product_id: 3, customer_id: 5, customer_name: '客户A',
      product_name: '熊猫抱枕', barcode: '699', unit_price: 12, quantity: 60,
      production_value: 720, production_date: '2026-09-27',
    },
  ]

  function mockRecentRecords() {
    recordsMock.mockImplementation(async (params: { start_date?: string; keyword?: string }) => {
      if (params.start_date) {
        return { success: true, data: RECORDS, total: 3, page: 1, per_page: 200, pages: 1, stats: null }
      }
      if (params.keyword) {
        return { success: true, data: [], total: 1, page: 1, per_page: 50, pages: 1, stats: { total_quantity: 0, total_value: 0, total_sku: 0 } }
      }
      return { success: true, data: [], total: 3, page: 1, per_page: 50, pages: 1, stats: null }
    })
  }

  it('右栏是固定区域：没选客户时也显示，只给引导不给空态按钮', async () => {
    const w = mountDialog()
    await flushPromises()

    const rail = w.find('[data-test="qe-recent"]')
    expect(rail.exists()).toBe(true)
    expect(rail.text()).toContain('最近客户添加')
    expect(rail.text()).toContain('先选择客户')
    expect(rail.find('.browse').exists()).toBe(false)
  })

  it('选了客户后列出该客户最近录入的 SKU，别的客户不混进来', async () => {
    mockRecentRecords()
    const w = mountDialog()
    await flushPromises()

    w.findComponent(CustomerSelect).vm.$emit('update:modelValue', 5)
    await flushPromises()

    const rail = w.find('[data-test="qe-recent"]')
    expect(rail.exists()).toBe(true)
    expect(rail.text()).toContain('最近客户添加')
    expect(rail.text()).toContain('白兔公仔 40cm')
    expect(rail.text()).toContain('熊猫抱枕')
    expect(rail.text()).not.toContain('60cm')
    expect(recordsMock).toHaveBeenCalledWith(expect.objectContaining({ start_date: '2026-07-02', end_date: '2026-09-30' }))
  })

  it('点右侧条目直接加一行（和搜索选中同一条路径）', async () => {
    mockRecentRecords()
    const w = mountDialog()
    await flushPromises()
    w.findComponent(CustomerSelect).vm.$emit('update:modelValue', 5)
    await flushPromises()

    await w.findAll('[data-test="qe-recent"] .pr-recent-item')[0]!.trigger('click')
    await flushPromises()

    expect(w.findAll('[data-test="qe-row"]').length).toBe(1)
    expect(w.find('[data-test="qe-row"]').text()).toContain('白兔公仔 40cm')
    expect(document.activeElement).toBe(w.find('[data-test="qe-qty"]').element)
  })

  it('该客户近 90 天没有记录时给空态与「浏览该客户的产品」入口', async () => {
    recordsMock.mockImplementation(async (params: { start_date?: string }) => {
      if (params.start_date) return { success: true, data: [], total: 0, page: 1, per_page: 200, pages: 1, stats: null }
      return { success: true, data: [], total: 0, page: 1, per_page: 50, pages: 1, stats: null }
    })
    productListMock.mockResolvedValue({ items: PRODUCTS, total: 2 })
    const w = mountDialog()
    await flushPromises()
    w.findComponent(CustomerSelect).vm.$emit('update:modelValue', 5)
    await flushPromises()

    const rail = w.find('[data-test="qe-recent"]')
    
    expect(rail.text()).toContain('没有录入记录')

    await rail.find('.browse').trigger('click')
    await flushPromises()
    expect(w.findAll('.pr-entry-dropdown-item').length).toBe(2)
  })
})

describe('下拉连续添加', () => {
  it('点下拉条目加一行后下拉不收起，可以接着点第二个', async () => {
    const w = mountDialog()
    await typeSearch(w, '白兔')
    await flushPromises()

    expect(w.findAll('.pr-entry-dropdown-item').length).toBe(2)

    await w.findAll('.pr-entry-dropdown-item')[0]!.trigger('mousedown')
    await flushPromises()

    expect(w.findAll('[data-test="qe-row"]').length).toBe(1)
    // 关键：下拉与结果都还在，焦点回到搜索框
    expect(w.find('.pr-entry-dropdown').exists()).toBe(true)
    expect(w.findAll('.pr-entry-dropdown-item').length).toBe(2)

    await w.findAll('.pr-entry-dropdown-item')[1]!.trigger('mousedown')
    await flushPromises()

    expect(w.findAll('[data-test="qe-row"]').length).toBe(2)
  })

  it('回车加行仍走原逻辑：清空搜索并收起下拉', async () => {
    const w = mountDialog()
    await typeSearch(w, '白兔')
    await flushPromises()

    await w.find('[data-test="qe-search"]').trigger('keydown', { key: 'Enter' })
    await flushPromises()

    expect(w.findAll('[data-test="qe-row"]').length).toBe(1)
    expect(w.find('.pr-entry-dropdown').exists()).toBe(false)
    expect((w.find('[data-test="qe-search"]').element as HTMLInputElement).value).toBe('')
  })
})
