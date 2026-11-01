/**
 * 录入弹窗 —— 键盘流（方向 A：一张单多行 SKU）。
 *
 * 目标：搜索 → 数量 → 下一条 全程不碰鼠标。
 * 与旧版的差别：⏎ 不再是「提交一条」，而是「追加一行」；提交统一走 Ctrl+⏎ / 批量提交按钮。
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

vi.mock('@/api', () => ({
  dailyProductionApi: {
    records: (...a: unknown[]) => recordsMock(...a),
    createRecord: (...a: unknown[]) => createMock(...a),
    deleteRecord: (...a: unknown[]) => deleteMock(...a),
    productInfo: (...a: unknown[]) => productInfoMock(...a),
  },
  productApi: { search: (...a: unknown[]) => searchMock(...a), list: (...a: unknown[]) => productListMock(...a) },
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

/** 键盘走完「搜索 → ↓ 选中第一条 → ⏎ 追加一行」 */
async function selectFirstProduct(w: VueWrapper) {
  await typeSearch(w, '白兔')
  const input = w.find('[data-test="qe-search"]')
  await input.trigger('keydown', { key: 'ArrowDown' })
  await input.trigger('keydown', { key: 'Enter' })
  await flushPromises()
}

function dropdownItemAt(w: VueWrapper, index: number) {
  const item = w.findAll('.pr-entry-dropdown-item')[index]
  if (!item) throw new Error(`下拉项缺失: index=${index}`)
  return item
}

function activeDeptText(w: VueWrapper) {
  const on = w.find('[data-test="qe-dept"] .pr-qe-seg-btn.on')
  return on.exists() ? on.text() : ''
}

beforeEach(() => {
  localStorage.clear()
  recordsMock.mockReset()
  createMock.mockReset()
  deleteMock.mockReset()
  productInfoMock.mockReset()
  searchMock.mockReset()
  productListMock.mockReset()
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
  document.body.innerHTML = ''
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
    expect(activeDeptText(w)).toContain('手工部')

    await modal.trigger('keydown', { key: '3', altKey: true })
    expect(activeDeptText(w)).toContain('包装部')

    await modal.trigger('keydown', { key: '1', altKey: true })
    expect(activeDeptText(w)).toContain('充棉部')
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

  it('搜索框按 ⏎ 追加一行、清空搜索框并把焦点移到该行数量', async () => {
    const w = mountDialog()
    await selectFirstProduct(w)

    expect(w.findAll('[data-test="qe-row"]').length).toBe(1)
    expect(w.find('[data-test="qe-row"]').text()).toContain('白兔公仔 40cm')
    expect((w.find('[data-test="qe-search"]').element as HTMLInputElement).value).toBe('')
    expect(document.activeElement).toBe(w.find('[data-test="qe-qty"]').element)
  })

  it('没按过 ↑↓ 直接 ⏎ 也能追加第一条（不能是静默无反应）', async () => {
    const w = mountDialog()
    await typeSearch(w, '白兔')
    const input = w.find('[data-test="qe-search"]')
    await input.trigger('keydown', { key: 'Enter' })
    await flushPromises()

    expect(w.findAll('[data-test="qe-row"]').length).toBe(1)
    expect(w.find('[data-test="qe-row"]').text()).toContain('白兔公仔 40cm')
    expect(document.activeElement).toBe(w.find('[data-test="qe-qty"]').element)
  })

  it('连续两次「搜索 + ⏎」得到两行 SKU', async () => {
    const w = mountDialog()
    await selectFirstProduct(w)
    await selectFirstProduct(w)

    expect(w.findAll('[data-test="qe-row"]').length).toBe(2)
    expect(w.find('[data-test="qe-total-sku"]').text()).toBe('2')
  })

  it('数量输入 ↑/↓ 让数量 ∓1', async () => {
    const w = mountDialog()
    await selectFirstProduct(w)
    const qty = w.find('[data-test="qe-qty"]')

    await qty.trigger('keydown', { key: 'ArrowUp' })
    await qty.trigger('keydown', { key: 'ArrowUp' })
    expect((qty.element as HTMLInputElement).value).toBe('2')

    await qty.trigger('keydown', { key: 'ArrowDown' })
    expect((qty.element as HTMLInputElement).value).toBe('1')
  })

  it('数量输入 Shift+↑/↓ 让数量 ∓10，且不会退成负数', async () => {
    const w = mountDialog()
    await selectFirstProduct(w)
    const qty = w.find('[data-test="qe-qty"]')

    await qty.trigger('keydown', { key: 'ArrowUp', shiftKey: true })
    expect((qty.element as HTMLInputElement).value).toBe('10')

    await qty.trigger('keydown', { key: 'ArrowDown', shiftKey: true })
    expect((qty.element as HTMLInputElement).value).toBe('0')

    await qty.trigger('keydown', { key: 'ArrowDown', shiftKey: true })
    expect((qty.element as HTMLInputElement).value).toBe('0')
  })

  it('数量框按 ⏎ 回到搜索框，继续加下一条', async () => {
    const w = mountDialog()
    await selectFirstProduct(w)
    await w.find('[data-test="qe-qty"]').setValue('620')

    await w.find('[data-test="qe-qty"]').trigger('keydown', { key: 'Enter' })
    await nextTick()

    expect(document.activeElement).toBe(w.find('[data-test="qe-search"]').element)
    // 回车只是移动焦点，不能顺手把这一批提交了
    expect(createMock).not.toHaveBeenCalled()
  })

  it('Ctrl+⏎ 在弹窗内任意位置批量提交', async () => {
    const w = mountDialog()
    await selectFirstProduct(w)
    await w.find('[data-test="qe-qty"]').setValue('620')

    await w.find('.pr-qe-modal').trigger('keydown', { key: 'Enter', ctrlKey: true })
    await flushPromises()

    expect(createMock).toHaveBeenCalledTimes(1)
    expect(createMock.mock.calls[0]?.[0]).toMatchObject({ quantity: 620, product_name: '白兔公仔 40cm' })
  })

  it('下拉已收起时 Esc 关闭弹窗', async () => {
    const w = mountDialog()
    expect(w.find('.pr-entry-dropdown').exists()).toBe(false)

    await w.find('.pr-qe-modal').trigger('keydown', { key: 'Escape' })

    expect(w.emitted('update:open')).toEqual([[false]])
  })

  it('Esc 分层：产品下拉打开时只收下拉，不关弹窗', async () => {
    const w = mountDialog()
    await typeSearch(w, '白兔')
    expect(w.find('.pr-entry-dropdown').exists()).toBe(true)

    await w.find('.pr-qe-modal').trigger('keydown', { key: 'Escape' })
    await nextTick()

    expect(w.find('.pr-entry-dropdown').exists()).toBe(false)
    expect(w.emitted('update:open')).toBeUndefined()
  })

  it('Esc 分层：粘贴层打开时只收粘贴层，不关弹窗', async () => {
    const w = mountDialog()
    await w.find('[data-test="qe-paste-open"]').trigger('click')
    expect(w.find('[data-test="qe-paste"]').exists()).toBe(true)

    await w.find('.pr-qe-modal').trigger('keydown', { key: 'Escape' })
    await nextTick()

    expect(w.find('[data-test="qe-paste"]').exists()).toBe(false)
    expect(w.emitted('update:open')).toBeUndefined()
  })
})
