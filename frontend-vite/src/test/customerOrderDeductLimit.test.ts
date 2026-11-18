/**
 * 抵扣备货数量不得超订单数量（2026-10-17 审计 P1-17 / 报告内 FE-DESK-A P1-1）
 *
 * 缺陷：「抵扣量 ≤ 订单数量」只在**开启抵扣那一刻**用 `Math.min(数量, 可用)` 算过一次，
 * 之后没有任何回收：
 *   1) 开启抵扣（数量 10、可用 10 ⇒ 抵扣 10）后把订单数量改成 3，抵扣量仍是 10；
 *   2) 「编辑暂存」弹窗里手打一个超过数量的抵扣值——`max` 属性只挡住箭头，不挡键入。
 * 两条提交路径都只比对「可用备货」，后端 `process_order_deduction` 又只按
 * `min(请求, 可用)` 收口（不按订单数量），于是「3 件的订单扣 10 件备货」能一路走通：
 * 生成 quantity=3 的订单 + quantity=10 的 StockOut（订单抵扣），备货被多扣 7 件。
 *
 * 本用例把三处入口的规则钉在同一份 `deductRules` 上：
 *   - `deductLimit`：抵扣量上限 = min(订单数量, 可用备货)；
 *   - `useOrderForm`：订单数量改小后抵扣量随之回收（只回收不放大）；
 *   - `useStagedEdit.saveEditStaged`：抵扣量 > 订单数量时拒绝保存。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ref, nextTick } from 'vue'
import { setActivePinia, createPinia } from 'pinia'

const mocks = vi.hoisted(() => ({
  availableStockinsMock: vi.fn(),
  productSearchMock: vi.fn(async () => [] as unknown[]),
  activeNamesMock: vi.fn(async () => [] as unknown[]),
  productListMock: vi.fn(async () => ({ items: [], total: 0 })),
  supplierListMock: vi.fn(async () => ({ suppliers: [], total: 0 })),
  showToastMock: vi.fn(),
}))

vi.mock('@/api', () => ({
  auxApi: {
    productSearch: mocks.productSearchMock,
    availableStockins: mocks.availableStockinsMock,
  },
  customerApi: { activeNames: mocks.activeNamesMock },
  productApi: { list: mocks.productListMock },
  supplierApi: { list: mocks.supplierListMock },
}))

vi.mock('@/composables/useToast', () => ({
  showToast: mocks.showToastMock,
}))

import { useOrderForm } from '@/views/customer-order/composables/useOrderForm'
import { useStagedEdit } from '@/views/customer-order/composables/useStagedEdit'
import { deductLimit, deductOverOrderMessage } from '@/views/customer-order/composables/deductRules'
import type { StagedItem, AvailableStockinItem } from '@/views/customer-order/composables/types'

// 源码原文用 Vite 的 ?raw 导入（与 backupRestoreConfirmFlow.test.ts 同款），
// 用于锁定「整页挂载成本过高」的调用点顺序契约。
import customerOrderViewSource from '../views/customer-order/CustomerOrderView.vue?raw'

function stockin(available: number): AvailableStockinItem[] {
  return [{ id: 1, quantity: available, deducted: 0, available }]
}

function staged(over: Partial<StagedItem> = {}): StagedItem {
  return {
    uid: 'u1',
    type: 'order',
    customer: '贝乐',
    productId: 1,
    productName: '产品A',
    quantity: 10,
    date: '2026-11-18',
    note: '',
    deductStock: false,
    deductQuantity: 0,
    shipmentPlans: [],
    ...over,
  }
}

/** 让已 resolve 的 promise 的 then/catch 回调跑完 */
async function flush() {
  await Promise.resolve()
  await Promise.resolve()
  await nextTick()
}

describe('deductRules 口径', () => {
  it('抵扣上限 = min(订单数量, 可用备货)，且不为负数', () => {
    expect(deductLimit(10, 10)).toBe(10)
    expect(deductLimit(3, 10)).toBe(3)
    expect(deductLimit(10, 3)).toBe(3)
    expect(deductLimit(0, 10)).toBe(0)
    expect(deductLimit(10, 0)).toBe(0)
    // 脏输入（负数 / 小数 / NaN）一律收到 0，别把 NaN 写进表单
    expect(deductLimit(-5, 10)).toBe(0)
    expect(deductLimit(8.7, 10)).toBe(8)
    expect(deductLimit(Number.NaN, 10)).toBe(0)
  })

  it('超订单数量的提示同时给出两个数字与动作词', () => {
    expect(deductOverOrderMessage(10, 3, '添加')).toContain('超过订单数量')
    expect(deductOverOrderMessage(10, 3, '添加')).toContain('10')
    expect(deductOverOrderMessage(10, 3, '添加')).toContain('3')
    expect(deductOverOrderMessage(10, 3, '添加')).toContain('添加')
  })
})

describe('useOrderForm：订单数量改小后抵扣量随之回收', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    mocks.availableStockinsMock.mockResolvedValue(stockin(10))
  })

  it('改数量不静默改写抵扣量（实时输入中间态不能把抵扣压成 1/0）', async () => {
    // 数量是 number 输入框的实时值：10 → 12 会先经过 1（清空编辑还会经过空串）。
    // 任何 watch 都会在那一帧把抵扣量压成 1/0 且只缩不放 → 用户以为扣 10 件、实际扣 0~1 件。
    // 因此「抵扣量 ≤ 订单数量」只在提交边界拦（见下一条源码顺序守卫 + useStagedEdit 用例）。
    const { form, handleDeductPreview } = useOrderForm()
    form.customer = '贝乐'
    await nextTick()
    form.productId = 1
    form.quantity = 10

    await handleDeductPreview()
    expect(form.deductQuantity).toBe(10)

    form.quantity = 1
    await nextTick()
    expect(form.deductQuantity).toBe(10) // 中间态不动

    form.quantity = 12
    await nextTick()
    expect(form.deductQuantity).toBe(10) // 改大也不放大
  })

  it('未开启抵扣时改数量不动抵扣量（不凭空造抵扣）', async () => {
    const { form } = useOrderForm()
    form.customer = '贝乐'
    await nextTick()
    form.productId = 1
    form.deductQuantity = 0

    form.quantity = 3
    await nextTick()

    expect(form.deductQuantity).toBe(0)
  })
})

describe('useStagedEdit：编辑暂存时抵扣量不得超订单数量', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('抵扣量 ≤ 可用备货但 > 订单数量 → 保存被拦，暂存条目不被改写', async () => {
    mocks.availableStockinsMock.mockResolvedValue(stockin(10))
    // 订单数量 3，可用备货 10：旧实现只比对可用量，5 件抵扣会被放行
    const items = ref<StagedItem[]>([staged({ uid: 'a', quantity: 3, deductStock: true })])
    const hook = useStagedEdit(items)

    hook.openEditStaged('a')
    await flush()
    expect(hook.editStockState.value).toBe('ready')

    hook.editStagedData.value!.deductQuantity = 5
    hook.saveEditStaged()

    expect(mocks.showToastMock).toHaveBeenCalledWith(
      expect.stringContaining('超过订单数量'),
      'warning',
    )
    expect(items.value[0]!.deductQuantity).toBe(0)
    expect(hook.editStagedVisible.value).toBe(true)
  })

  it('抵扣量 ≤ 订单数量且 ≤ 可用备货 → 正常保存（防矫枉过正）', async () => {
    mocks.availableStockinsMock.mockResolvedValue(stockin(10))
    const items = ref<StagedItem[]>([staged({ uid: 'a', quantity: 3, deductStock: true })])
    const hook = useStagedEdit(items)

    hook.openEditStaged('a')
    await flush()

    hook.editStagedData.value!.deductQuantity = 2
    hook.saveEditStaged()

    expect(mocks.showToastMock).not.toHaveBeenCalled()
    expect(items.value[0]!.deductQuantity).toBe(2)
    expect(hook.editStagedVisible.value).toBe(false)
  })
})

/**
 * 录入页「添加」入口的守卫（2026-10-17 审计 P1-17）。
 *
 * 整页挂载 CustomerOrderView 的成本极高（十余个子组件 + 多个 onMounted 请求 + 轮询组合式），
 * 因此按本仓既有取舍（见 `backupRestoreConfirmFlow.test.ts` 的同款说明）用**源码顺序守卫**
 * 锁住「入暂存区前按订单数量复核抵扣量」这一结构性契约；行为侧的纯函数与保存拦截
 * 已由上面的用例覆盖。
 */
describe('CustomerOrderView.addStaged 抵扣量复核（源码顺序守卫）', () => {
  const source = customerOrderViewSource

  it('入暂存区之前必须按订单数量拦一次抵扣量', () => {
    const fnStart = source.indexOf('async function addStaged')
    expect(fnStart).toBeGreaterThan(-1)
    const pushAt = source.indexOf('stagedItems.value.push(', fnStart)
    expect(pushAt).toBeGreaterThan(fnStart)

    const gate = source.slice(fnStart, pushAt)
    expect(gate).toMatch(/if \(form\.deductQuantity > form\.quantity\)/)
    expect(gate).toContain('deductOverOrderMessage(')
    expect(gate).toContain("'添加'")
  })
})
