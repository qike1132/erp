/**
 * 录入弹窗 —— 键盘流（本次改版的核心）。
 *
 * 设计目标：产品 → 数量 → 提交 全程不碰鼠标。每一行快捷键单独一个用例钉死，
 * 因为这些行为最容易在后续重构里被悄悄改掉，而改掉之后数据录入员只会「感觉变卡了」。
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

vi.mock('@/api', () => ({
  dailyProductionApi: {
    records: (...a: unknown[]) => recordsMock(...a),
    createRecord: (...a: unknown[]) => createMock(...a),
    deleteRecord: (...a: unknown[]) => deleteMock(...a),
    productInfo: (...a: unknown[]) => productInfoMock(...a),
  },
  productApi: { search: (...a: unknown[]) => searchMock(...a) },
}))

vi.mock('@/composables/useToast', () => ({ showToast: vi.fn() }))

import ProductionEntryDialog from '@/views/production/components/ProductionEntryDialog.vue'

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

/** 输入关键词并等过 300ms 防抖，让下拉里真的有结果 */
async function typeSearch(w: VueWrapper, text: string) {
  searchMock.mockResolvedValue({ products: PRODUCTS })
  const input = w.find('[data-test="qe-search"]')
  await input.setValue(text)
  await new Promise((resolve) => setTimeout(resolve, 320))
  await flushPromises()
}

/** 键盘走完「搜索 → ↓ 选中第一条 → ⏎ 确认」 */
async function selectFirstProduct(w: VueWrapper) {
  await typeSearch(w, '白兔')
  const input = w.find('[data-test="qe-search"]')
  await input.trigger('keydown', { key: 'ArrowDown' })
  await input.trigger('keydown', { key: 'Enter' })
  await flushPromises()
}

/** 取第 index 个下拉项（显式断言存在，避免索引访问的类型空洞） */
function dropdownItemAt(w: VueWrapper, index: number) {
  const item = w.findAll('.pr-entry-dropdown-item')[index]
  if (!item) throw new Error(`下拉项缺失: index=${index}`)
  return item
}

/** 取第一次 createRecord 的入参（显式断言调用已发生） */
function firstCreatePayload(): Record<string, unknown> {
  const call = createMock.mock.calls[0]
  if (!call) throw new Error('createRecord 未被调用')
  return call[0] as Record<string, unknown>
}

beforeEach(() => {
  localStorage.clear()
  recordsMock.mockReset()
  createMock.mockReset()
  deleteMock.mockReset()
  productInfoMock.mockReset()
  searchMock.mockReset()
  recordsMock.mockResolvedValue({
    success: true, data: [], total: 3, page: 1, per_page: 50, pages: 1, stats: null,
  })
  createMock.mockResolvedValue({ success: true, message: 'ok', id: 42 })
  deleteMock.mockResolvedValue({ success: true, message: 'ok' })
  productInfoMock.mockResolvedValue({
    success: true, data: { id: 1, name: '白兔公仔 40cm', barcode: '6901234', price: 7 },
  })
})

afterEach(() => {
  wrapper?.unmount()
  wrapper = null
})

describe('ProductionEntryDialog 键盘流', () => {
  it('打开时焦点自动落在产品搜索框', async () => {
    const w = mountDialog()
    await nextTick()
    await flushPromises()

    expect(document.activeElement).toBe(w.find('[data-test="qe-search"]').element)
  })

  it('Alt+1 / Alt+2 / Alt+3 切换生产部门', async () => {
    const w = mountDialog()
    const modal = w.find('.pr-qe-modal')

    await modal.trigger('keydown', { key: '2', altKey: true })
    expect(w.find('[data-test="qe-dept"]').text()).toContain('手工部')

    await modal.trigger('keydown', { key: '3', altKey: true })
    expect(w.find('[data-test="qe-dept"]').text()).toContain('包装部')

    await modal.trigger('keydown', { key: '1', altKey: true })
    expect(w.find('[data-test="qe-dept"]').text()).toContain('充棉部')
  })

  it('搜索框 ↑/↓ 在产品结果间移动高亮', async () => {
    const w = mountDialog()
    await typeSearch(w, '白兔')
    const input = w.find('[data-test="qe-search"]')

    await input.trigger('keydown', { key: 'ArrowDown' })
    expect(dropdownItemAt(w, 0).classes()).toContain('active')

    await input.trigger('keydown', { key: 'ArrowDown' })
    expect(dropdownItemAt(w, 1).classes()).toContain('active')

    await input.trigger('keydown', { key: 'ArrowUp' })
    expect(dropdownItemAt(w, 0).classes()).toContain('active')
  })

  it('搜索框按 ⏎ 选中产品并把焦点移到数量输入', async () => {
    const w = mountDialog()
    await selectFirstProduct(w)

    expect((w.find('[data-test="qe-search"]').element as HTMLInputElement).value).toBe('白兔公仔 40cm')
    expect(document.activeElement).toBe(w.find('[data-test="qe-quantity"]').element)
  })

  it('数量输入 ↑/↓ 让数量 ∓1', async () => {
    const w = mountDialog()
    await selectFirstProduct(w)
    const qty = w.find('[data-test="qe-quantity"]')

    await qty.trigger('keydown', { key: 'ArrowUp' })
    await qty.trigger('keydown', { key: 'ArrowUp' })
    expect((qty.element as HTMLInputElement).value).toBe('2')

    await qty.trigger('keydown', { key: 'ArrowDown' })
    expect((qty.element as HTMLInputElement).value).toBe('1')
  })

  it('数量输入 Shift+↑/↓ 让数量 ∓10', async () => {
    const w = mountDialog()
    await selectFirstProduct(w)
    const qty = w.find('[data-test="qe-quantity"]')

    await qty.trigger('keydown', { key: 'ArrowUp', shiftKey: true })
    expect((qty.element as HTMLInputElement).value).toBe('10')

    await qty.trigger('keydown', { key: 'ArrowDown', shiftKey: true })
    expect((qty.element as HTMLInputElement).value).toBe('0')

    // 不能退化成负库存：到底后再按 ↓ 仍是 0
    await qty.trigger('keydown', { key: 'ArrowDown', shiftKey: true })
    expect((qty.element as HTMLInputElement).value).toBe('0')
  })

  it('数量输入按 ⏎ 提交；成功后清空表单并把焦点送回搜索框', async () => {
    const w = mountDialog()
    await selectFirstProduct(w)
    await w.find('[data-test="qe-quantity"]').setValue('620')

    await w.find('[data-test="qe-quantity"]').trigger('keydown', { key: 'Enter' })
    await flushPromises()

    expect(createMock).toHaveBeenCalledTimes(1)
    expect(firstCreatePayload()).toMatchObject({ quantity: 620, product_name: '白兔公仔 40cm' })
    // 表单已清空：搜索框为空、数量归零
    expect((w.find('[data-test="qe-search"]').element as HTMLInputElement).value).toBe('')
    expect((w.find('[data-test="qe-quantity"]').element as HTMLInputElement).value).toBe('0')
    // 焦点回到搜索框，下一条可以立刻继续录
    expect(document.activeElement).toBe(w.find('[data-test="qe-search"]').element)
  })

  it('Ctrl+⏎ 在弹窗内任意位置都能提交', async () => {
    const w = mountDialog()
    await selectFirstProduct(w)
    await w.find('[data-test="qe-quantity"]').setValue('5')

    await w.find('.pr-qe-modal').trigger('keydown', { key: 'Enter', ctrlKey: true })
    await flushPromises()

    expect(createMock).toHaveBeenCalledTimes(1)
  })

  it('Esc 关闭弹窗', async () => {
    const w = mountDialog()

    await w.find('.pr-qe-modal').trigger('keydown', { key: 'Escape' })

    expect(w.emitted('update:open')).toEqual([[false]])
  })
})
