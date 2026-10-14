/**
 * 录入弹窗 —— 单行快捷录入的布局与三条「少录错」护栏。
 *
 * 1) 未选产品 / 数量 ≤ 0 → 录入按钮禁用
 * 2) 提交中 → 禁用（防双击/连按 Ctrl+⏎ 重复建单）
 * 3) 今日同部门同产品已有记录 → 提示，但**绝不阻断**（一天两批同产品是合法的）
 * 4) 撤销 → 先确认再物理删除
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

const PRODUCTS = [{ id: 1, name: '白兔公仔 40cm', barcode: '6901234', specification: '40cm' }]

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

/**
 * 不 stub UiConfirmDialog 的挂载。
 * 撤销确认框的层级问题只有挂真组件才看得见 —— stub 掉之后它是个普通 div，
 * 有没有 z-class 都一样，这正是当初漏掉这个 bug 的原因。
 */
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

async function selectFirstProduct(w: VueWrapper) {
  await typeSearch(w, '白兔')
  const input = w.find('[data-test="qe-search"]')
  await input.trigger('keydown', { key: 'ArrowDown' })
  await input.trigger('keydown', { key: 'Enter' })
  await flushPromises()
}

function submitDisabled(w: VueWrapper) {
  return w.find('[data-test="qe-submit"]').attributes('disabled') !== undefined
}

/** 取第 index 个部门菜单项（显式断言存在，避免索引访问的类型空洞） */
function deptOptionAt(w: VueWrapper, index: number) {
  const option = w.findAll('.pr-qe-dept-option')[index]
  if (!option) throw new Error(`部门选项缺失: index=${index}`)
  return option
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
  // 无 keyword 的查询 = 头部「今天已录 N 条」；带 keyword 的 = 重复校验
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
  productInfoMock.mockResolvedValue({
    success: true, data: { id: 1, name: '白兔公仔 40cm', barcode: '6901234', price: 7 },
  })
})

afterEach(() => {
  wrapper?.unmount()
  wrapper = null
  // 真 UiConfirmDialog 经 reka-ui 传送进 body，卸载后再清一次，避免串到下一个用例
  document.body.innerHTML = ''
})

describe('ProductionEntryDialog 快捷行布局', () => {
  it('渲染部门 chip / 产品搜索框 / 数量 / 录入按钮；「详细」默认折叠', () => {
    const w = mountDialog()

    expect(w.find('[data-test="qe-dept"]').exists()).toBe(true)
    expect(w.find('[data-test="qe-search"]').exists()).toBe(true)
    expect(w.find('[data-test="qe-quantity"]').exists()).toBe(true)
    expect(w.find('[data-test="qe-submit"]').exists()).toBe(true)
    expect(w.find('[data-test="qe-detail"]').exists()).toBe(false)
  })

  it('提示行显示自动单价 / 备注 / 日期', async () => {
    const w = mountDialog()
    await selectFirstProduct(w)

    const hint = w.find('[data-test="qe-hint"]').text()
    expect(hint).toContain('¥7.00')
    expect(hint).toContain('备注（空）')
    expect(hint).toContain('2026-09-30')
  })

  it('选择客户后提交带 customer_id', async () => {
    const w = mountDialog()
    await flushPromises()

    w.findComponent(CustomerSelect).vm.$emit('update:modelValue', 5)
    await nextTick()
    await selectFirstProduct(w)
    await w.find('[data-test="qe-quantity"]').setValue('10')
    await w.find('[data-test="qe-submit"]').trigger('click')
    await flushPromises()

    expect(createMock).toHaveBeenCalledWith(expect.objectContaining({ customer_id: 5 }))
    expect(w.find('[data-test="qe-hint"]').text()).toContain('客户A')
  })

  it('头部显示「今天已录 N 条」（按选中日期取记录总数）', async () => {
    const w = mountDialog()
    await flushPromises()

    expect(w.find('.pr-qe-sub').text()).toContain('今天已录 3 条')
    expect(recordsMock).toHaveBeenCalledWith(
      expect.objectContaining({ production_date: '2026-09-30' }),
    )
  })

  it('点「详细」展开日期 / 单价 / 产值 / 备注', async () => {
    const w = mountDialog()

    await w.find('[data-test="qe-detail-toggle"]').trigger('click')

    const detail = w.find('[data-test="qe-detail"]')
    expect(detail.exists()).toBe(true)
    expect(detail.text()).toContain('日期')
    expect(detail.text()).toContain('单价')
    expect(detail.text()).toContain('产值')
    expect(detail.text()).toContain('备注')
  })

  it('「详细」里改备注会同步到提示行（慢路径与快捷行共用同一份状态）', async () => {
    const w = mountDialog()
    await w.find('[data-test="qe-detail-toggle"]').trigger('click')

    await w.find('[data-test="qe-detail"] input[aria-label="备注"]').setValue('第二批')

    expect(w.find('[data-test="qe-hint"]').text()).toContain('备注（第二批）')
  })

  it('「详细」里改日期会 emit update:selectedDate（对外契约不变）', async () => {
    const w = mountDialog()
    await w.find('[data-test="qe-detail-toggle"]').trigger('click')

    await w.find('[data-test="qe-detail"] input[aria-label="生产日期"]').setValue('2026-09-29')

    expect(w.emitted('update:selectedDate')).toEqual([['2026-09-29']])
  })

  it('不再有「保存后继续录入下一条」复选框（提交本身就是连续的）', () => {
    const w = mountDialog()

    expect(w.text()).not.toContain('保存后继续录入下一条')
  })

  it('点「最近使用」chip 带入该产品及其单价（鼠标捷径）', async () => {
    localStorage.setItem(
      'production.recentProducts',
      JSON.stringify([{ id: 9, name: '熊猫抱枕', barcode: '699' }]),
    )
    productInfoMock.mockResolvedValue({
      success: true, data: { id: 9, name: '熊猫抱枕', barcode: '699', price: 12 },
    })
    const w = mountDialog()

    await w.find('[data-test="qe-recent"]').trigger('click')
    await flushPromises()

    expect((w.find('[data-test="qe-search"]').element as HTMLInputElement).value).toBe('熊猫抱枕')
    expect(w.find('[data-test="qe-hint"]').text()).toContain('¥12.00')
  })
})

describe('ProductionEntryDialog 护栏', () => {
  it('未选产品或数量 ≤ 0 时录入按钮禁用', async () => {
    const w = mountDialog()
    expect(submitDisabled(w)).toBe(true)

    await selectFirstProduct(w)
    expect(submitDisabled(w)).toBe(true) // 数量仍为 0

    await w.find('[data-test="qe-quantity"]').setValue('0')
    expect(submitDisabled(w)).toBe(true)

    await w.find('[data-test="qe-quantity"]').setValue('5')
    expect(submitDisabled(w)).toBe(false)
  })

  it('快速连按两次 Ctrl+⏎ 只创建一条记录，且提交期间按钮禁用', async () => {
    const w = mountDialog()
    await selectFirstProduct(w)
    await w.find('[data-test="qe-quantity"]').setValue('10')

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

  it('选中产品后查询今日同部门同产品已录数量，命中则提示——只是提示，不阻断', async () => {
    const w = mountDialog()

    await selectFirstProduct(w)
    await flushPromises()

    expect(recordsMock).toHaveBeenCalledWith(
      expect.objectContaining({
        production_date: '2026-09-30',
        department: 'filling',
        keyword: '白兔公仔 40cm',
      }),
    )
    expect(w.find('[data-test="qe-dup"]').text()).toContain('今天已录 400 件 · 仍要录入')

    // 提示不阻断：数量填好后照样能提交
    await w.find('[data-test="qe-quantity"]').setValue('10')
    expect(submitDisabled(w)).toBe(false)
  })

  it('提交成功后显示「刚才录的」条，撤销先弹确认框，确认后才物理删除', async () => {
    const w = mountDialog()
    await selectFirstProduct(w)
    await w.find('[data-test="qe-quantity"]').setValue('620')

    await w.find('[data-test="qe-submit"]').trigger('click')
    await flushPromises()

    const strip = w.find('[data-test="qe-just"]')
    expect(strip.exists()).toBe(true)
    expect(strip.text()).toContain('白兔公仔 40cm')
    expect(strip.text()).toContain('620')

    // 点撤销：只弹确认框，不能删
    await w.find('[data-test="qe-undo"]').trigger('click')
    await nextTick()

    expect(deleteMock).not.toHaveBeenCalled()
    const confirm = w.findComponent({ name: 'UiConfirmDialog' })
    expect(confirm.props('open')).toBe(true)
    expect(confirm.props('text')).toContain('白兔公仔 40cm')

    await w.find('[data-test="undo-confirm-yes"]').trigger('click')
    await flushPromises()

    expect(deleteMock).toHaveBeenCalledWith(42)
    expect(w.find('[data-test="qe-just"]').exists()).toBe(false)
  })

  it('撤销确认框被抬到嵌套层级——沿用默认层级会被录入弹窗盖住，点不到', async () => {
    // 挂**真** UiConfirmDialog：stub 掉它之后它只是个普通 div，有没有 z-class 都一样，
    // 这个 bug 就是这么漏过去的。jsdom 验不了绘制，但能钉住「类名确实传下去了」。
    const w = mountDialogRealConfirm()
    await selectFirstProduct(w)
    await w.find('[data-test="qe-quantity"]').setValue('620')
    await w.find('[data-test="qe-submit"]').trigger('click')
    await flushPromises()

    await w.find('[data-test="qe-undo"]').trigger('click')
    await nextTick()

    const confirm = w.findComponent(UiConfirmDialog)
    expect(confirm.props('open')).toBe(true)
    // 遮罩与弹窗卡都是 var(--z-modal)=40，确认框必须抬到 60/70 才在它们之上
    expect(confirm.props('overlayZClass')).toBe('z-[var(--z-overlay-nested)]')
    expect(confirm.props('contentZClass')).toBe('z-[var(--z-modal-nested)]')
  })

  it('撤销失败时透出后端的 detail（物理删除失败的原因必须可见）', async () => {
    const w = mountDialog()
    await selectFirstProduct(w)
    await w.find('[data-test="qe-quantity"]').setValue('620')
    await w.find('[data-test="qe-submit"]').trigger('click')
    await flushPromises()

    deleteMock.mockRejectedValueOnce({ response: { data: { detail: '记录已被他人删除' } } })
    await w.find('[data-test="qe-undo"]').trigger('click')
    await w.find('[data-test="undo-confirm-yes"]').trigger('click')
    await flushPromises()

    expect(showToast).toHaveBeenCalledWith('记录已被他人删除', 'error')
  })

  it('点部门菜单以外的地方会收起菜单', async () => {
    const w = mountDialog()
    await w.find('[data-test="qe-dept"]').trigger('click')
    expect(w.find('.pr-qe-dept-menu').exists()).toBe(true)

    document.body.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await nextTick()

    expect(w.find('.pr-qe-dept-menu').exists()).toBe(false)
  })

  it('部门默认取上次使用的部门，切换后写回 localStorage', async () => {
    localStorage.setItem('production.lastDepartment', 'packaging')
    const w = mountDialog()
    expect(w.find('[data-test="qe-dept"]').text()).toContain('包装部')

    await w.find('[data-test="qe-dept"]').trigger('click')
    await deptOptionAt(w, 1).trigger('click')

    expect(localStorage.getItem('production.lastDepartment')).toBe('handcraft')
  })
})
