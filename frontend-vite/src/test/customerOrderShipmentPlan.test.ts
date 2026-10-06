/**
 * 分批出货计划（2026-10-06 v2）前端行为守卫：
 * 1) 分批校验规则：排满口径（总和=订单量）、行完整性、空数组=无计划恒合法
 * 2) payload：shipment_plans 逐批 plan_date/quantity/note，不再发 v1 旧字段
 * 3) 控件交互：勾选自动生成首行、增删行、剩余统计、取消清空
 * 4) 暂存卡片：每批一枚 chip，超 2 批折叠 +N批
 * 5) 编辑弹窗：排满拦截（useStagedEdit.saveEditStaged）
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { ref } from 'vue'

const mocks = vi.hoisted(() => ({
  postMock: vi.fn(),
  getMock: vi.fn(async () => []),
}))

vi.mock('@/api/request', () => ({
  get: mocks.getMock,
  post: mocks.postMock,
  put: vi.fn(),
  del: vi.fn(),
  upload: mocks.postMock,
  download: vi.fn(),
}))

vi.mock('@/composables/useToast', () => ({ showToast: vi.fn() }))
vi.mock('@tanstack/vue-query', () => ({
  useQueryClient: () => ({ invalidateQueries: vi.fn() }),
  useQuery: () => ({ data: { value: undefined } }),
}))
vi.mock('@/composables/useConfirmDialog', () => ({
  useConfirmDialog: () => ({
    open: false, text: '', sub: '', type: 'warning',
    onConfirm: vi.fn(), onCancel: vi.fn(), confirm: vi.fn(async () => true),
  }),
}))
vi.mock('@/stores/catalog', () => ({
  useCatalogStore: () => ({
    activeCustomerNames: [],
    ensureActiveCustomerNames: vi.fn(async () => {}),
  }),
}))

import { showToast } from '@/composables/useToast'
import { useOrderForm } from '@/views/customer-order/composables/useOrderForm'
import { useStagedItems } from '@/views/customer-order/composables/useStagedItems'
import { useStagedEdit } from '@/views/customer-order/composables/useStagedEdit'
import type { FormState, ShipmentPlanSplit, StagedItem } from '@/views/customer-order/composables/types'
import ShipmentPlanControl from '@/views/customer-order/components/ShipmentPlanControl.vue'
import StagingArea from '@/views/customer-order/components/StagingArea.vue'

const ORDERS_URL = '/aux/batch-submit-orders'

function toastTexts() {
  return vi.mocked(showToast).mock.calls.map((c) => String(c[0]))
}

function split(date: string, quantity: number, note = ''): ShipmentPlanSplit {
  return { date, quantity, note }
}

function stagedItem(overrides: Partial<StagedItem> = {}): StagedItem {
  return {
    uid: 'o1',
    origin: 'manual',
    type: 'order',
    customer: '客户A',
    productId: 1,
    productName: '产品A',
    quantity: 500,
    date: '2026-10-06',
    note: '',
    deductStock: false,
    deductQuantity: 0,
    shipmentPlans: [],
    ...overrides,
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  mocks.postMock.mockReset()
})

describe('分批校验规则（排满口径）', () => {
  it('两批 200+300 排满 500 → planSplitsInvalid 为空', () => {
    const { form, planSplitsInvalid } = useOrderForm()
    form.quantity = 500
    form.shipmentPlans = [split('2026-10-10', 200), split('2026-10-20', 300)]
    expect(planSplitsInvalid.value).toBe('')
  })

  it('未排满 / 超出 / 缺日期 / 零数量 → 各自给出违规文案', () => {
    const { form, planSplitsInvalid } = useOrderForm()
    form.quantity = 500

    form.shipmentPlans = [split('2026-10-10', 200), split('2026-10-20', 200)]
    expect(planSplitsInvalid.value).toContain('未排满订单数量(500)')
    expect(planSplitsInvalid.value).toContain('还差 100')

    form.shipmentPlans = [split('2026-10-10', 300), split('2026-10-20', 300)]
    expect(planSplitsInvalid.value).toContain('超出订单数量(500)')

    form.shipmentPlans = [split('2026-10-10', 250), split('', 250)]
    expect(planSplitsInvalid.value).toContain('未选择出货日期')

    form.shipmentPlans = [split('2026-10-10', 0), split('2026-10-20', 500)]
    expect(planSplitsInvalid.value).toContain('分批数量必须为大于 0 的整数')

    form.shipmentPlans = []
    expect(planSplitsInvalid.value).toBe('')
  })

  it('备货类型不参与分批校验（控件隐藏时状态残留无害）', () => {
    const { form, planSplitsInvalid } = useOrderForm()
    form.type = 'stockin'
    form.quantity = 500
    form.shipmentPlans = [split('2026-10-10', 100)]
    expect(planSplitsInvalid.value).toBe('')
  })
})

describe('useStagedItems payload 与播报', () => {
  it('payload 逐批发送 plan_date/quantity/note，且不含 v1 旧字段', async () => {
    mocks.postMock.mockResolvedValue({ success: true, created_count: 1, results: [{ success: true }] })
    const api = useStagedItems()
    api.stagedItems.value = [stagedItem({
      shipmentPlans: [split('2026-10-10', 200, '首批急发'), split('2026-10-20', 300)],
    })]

    await api.submitAll()

    const call = mocks.postMock.mock.calls.find((c) => c[0] === ORDERS_URL)
    expect(call).toBeTruthy()
    const order = (call![1].orders as Record<string, unknown>[])[0]!
    expect(order.shipment_plans).toEqual([
      { plan_date: '2026-10-10', quantity: 200, note: '首批急发' },
      { plan_date: '2026-10-20', quantity: 300, note: '' },
    ])
    expect(order.has_shipment_plan).toBeUndefined()
    expect(order.shipment_plan_date).toBeUndefined()
  })

  it('无计划条目 → shipment_plans 为空数组（原流程零改动）', async () => {
    mocks.postMock.mockResolvedValue({ success: true, created_count: 1, results: [{ success: true }] })
    const api = useStagedItems()
    api.stagedItems.value = [stagedItem()]

    await api.submitAll()

    const call = mocks.postMock.mock.calls.find((c) => c[0] === ORDERS_URL)
    expect((call![1].orders as Record<string, unknown>[])[0]!.shipment_plans).toEqual([])
  })

  it('提交成功且含计划条目 → 播报「其中 1 条已同步出货计划」', async () => {
    mocks.postMock.mockResolvedValue({ success: true, created_count: 1, results: [{ success: true }] })
    const api = useStagedItems()
    api.stagedItems.value = [stagedItem({ shipmentPlans: [split('2026-10-10', 500)] })]

    await api.submitAll()

    expect(toastTexts().some((t) => t.includes('其中 1 条已同步出货计划'))).toBe(true)
  })
})

describe('ShipmentPlanControl 多行编辑器', () => {
  function mountControl() {
    const form: FormState = {
      type: 'order', date: '', customer: '', productSearch: '', productId: 0,
      quantity: 500, deductStock: false, deductQuantity: 0, note: '', shipmentPlans: [],
    }
    const wrapper = mount(ShipmentPlanControl, {
      props: { form },
      global: {
        stubs: {
          UiDatePicker: {
            template: `<input data-stub="date" :value="modelValue" @input="$emit('update:modelValue', $event.target.value)" />`,
            props: ['modelValue', 'label'],
            emits: ['update:modelValue'],
          },
          FontAwesomeIcon: { template: '<i />' },
        },
      },
    })
    return { wrapper, form }
  }

  const checkbox = (w: ReturnType<typeof mount>) => w.find('[role="checkbox"]')

  it('默认未勾选：无批次行；勾选后自动生成首行（数量=订单全量）', async () => {
    const { wrapper, form } = mountControl()
    expect(wrapper.findAll('.plan-split-row')).toHaveLength(0)

    await checkbox(wrapper).trigger('click')
    expect(form.shipmentPlans).toEqual([{ date: '', quantity: 500, note: '' }])
    const rows = wrapper.findAll('.plan-split-row')
    expect(rows).toHaveLength(1)
    const qtyInput = rows[0]!.findAll('input')[1]!
    expect((qtyInput.element as HTMLInputElement).value).toBe('500')
  })

  it('加行默认填剩余数量；删行后统计回满；取消勾选清空全部批次', async () => {
    const { wrapper, form } = mountControl()
    await checkbox(wrapper).trigger('click')
    // 首行改成 200，剩余 300
    await wrapper.findAll('.plan-split-row')[0]!.findAll('input')[1]!.setValue('200')
    expect(form.shipmentPlans[0]!.quantity).toBe(200)

    await wrapper.find('.plan-add-btn').trigger('click')
    expect(form.shipmentPlans).toHaveLength(2)
    expect(form.shipmentPlans[1]!.quantity).toBe(300)
    // 加行默认填满剩余 → 分配自动回到排满
    expect(wrapper.text()).toContain('已分配 500 / 订单量 500')

    // 补满后统计合法（无红色提示文案）
    await wrapper.findAll('.plan-split-row')[1]!.findAll('input')[0]!.setValue('2026-10-20')
    expect(wrapper.text()).not.toContain('未排满')

    // 删到只剩一行后删除按钮禁用
    await wrapper.findAll('.plan-split-row')[1]!.find('.plan-remove-btn').trigger('click')
    expect(form.shipmentPlans).toHaveLength(1)
    expect(wrapper.findAll('.plan-split-row')[0]!.find('.plan-remove-btn').attributes('disabled')).toBeDefined()

    // 取消勾选清空
    await checkbox(wrapper).trigger('click')
    expect(form.shipmentPlans).toEqual([])
    expect(wrapper.findAll('.plan-split-row')).toHaveLength(0)
  })

  it('未排满时底部统计给出违规文案', async () => {
    const { wrapper } = mountControl()
    await checkbox(wrapper).trigger('click')
    // 行完整性优先于排满口径：先补日期，再改数量触发「未排满」
    await wrapper.findAll('.plan-split-row')[0]!.findAll('input')[0]!.setValue('2026-10-10')
    await wrapper.findAll('.plan-split-row')[0]!.findAll('input')[1]!.setValue('200')
    expect(wrapper.text()).toContain('未排满订单数量(500)')
  })
})

describe('StagingArea 分批徽标', () => {
  function mountArea(items: StagedItem[]) {
    return mount(StagingArea, {
      props: { stagedItems: items, submitting: false },
      global: { stubs: { FontAwesomeIcon: { template: '<i />' } } },
    })
  }

  it('两批各渲染一枚 chip（日期×数量）', () => {
    const wrapper = mountArea([stagedItem({
      shipmentPlans: [split('2026-10-10', 200), split('2026-10-20', 300)],
    })])
    expect(wrapper.text()).toContain('出货: 10-10×200')
    expect(wrapper.text()).toContain('出货: 10-20×300')
  })

  it('超 2 批折叠为 +N批', () => {
    const wrapper = mountArea([stagedItem({
      shipmentPlans: [split('2026-10-10', 100), split('2026-10-20', 200), split('2026-10-25', 200)],
    })])
    expect(wrapper.text()).toContain('出货: 10-10×100')
    expect(wrapper.text()).toContain('出货: 10-20×200')
    expect(wrapper.text()).not.toContain('10-25')
    expect(wrapper.text()).toContain('+1批')
  })

  it('无计划/备货条目不渲染出货 chip', () => {
    const wrapper = mountArea([stagedItem(), stagedItem({ uid: 's1', type: 'stockin', shipmentPlans: [split('2026-10-10', 5)] })])
    expect(wrapper.text()).not.toContain('出货: 10-10')
  })
})

describe('编辑弹窗排满拦截（useStagedEdit）', () => {
  function setupEdit(item: StagedItem) {
    const items = ref<StagedItem[]>([item])
    const edit = useStagedEdit(items)
    edit.openEditStaged(item.uid)
    return edit
  }

  it('未排满 → showToast 拦截且弹窗不关闭', () => {
    const edit = setupEdit(stagedItem({ shipmentPlans: [split('2026-10-10', 200)] }))
    edit.saveEditStaged()
    expect(toastTexts().some((t) => t.includes('未排满订单数量(500)'))).toBe(true)
    expect(edit.editStagedVisible.value).toBe(true)
  })

  it('排满 → 保存成功并关闭弹窗', () => {
    const item = stagedItem({ shipmentPlans: [split('2026-10-10', 200), split('2026-10-20', 300)] })
    const edit = setupEdit(item)
    edit.saveEditStaged()
    expect(edit.editStagedVisible.value).toBe(false)
  })

  it('取消编辑不污染暂存数据（评审 BLOCK：深拷贝守卫）', () => {
    const item = stagedItem({ shipmentPlans: [split('2026-10-10', 500)] })
    const items = ref<StagedItem[]>([item])
    const edit = useStagedEdit(items)
    edit.openEditStaged(item.uid)
    // 模拟弹窗内删行（对 editStagedData 的原地操作）
    edit.editStagedData.value!.shipmentPlans.splice(0, 1)
    // 用户「取消」（不调用 saveEditStaged）→ 原暂存数据必须原封不动
    expect(items.value[0]!.shipmentPlans).toHaveLength(1)
    expect(items.value[0]!.shipmentPlans[0]!.quantity).toBe(500)
  })

  it('保存后释放编辑副本且落回独立（排查 INV-2：落回深拷贝）', () => {
    const item = stagedItem({ shipmentPlans: [split('2026-10-10', 200), split('2026-10-20', 300)] })
    const items = ref<StagedItem[]>([item])
    const edit = useStagedEdit(items)
    edit.openEditStaged(item.uid)
    // 编辑副本上加第三批并补满（100×5）
    edit.editStagedData.value!.shipmentPlans = [
      split('2026-10-10', 100), split('2026-10-20', 200), split('2026-10-25', 200),
    ]
    edit.saveEditStaged()
    // 编辑副本被释放：弹窗关闭后不存在持数组引用的存活对象
    expect(edit.editStagedData.value).toBeNull()
    // 暂存条目拿到独立副本（3 批），后续任何编辑会话从暂存重新深拷贝
    expect(items.value[0]!.shipmentPlans).toHaveLength(3)
    expect(items.value[0]!.shipmentPlans.map((p) => p.quantity)).toEqual([100, 200, 200])
  })
})
