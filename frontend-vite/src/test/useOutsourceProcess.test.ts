/**
 * useOutsourceProcess 单测
 *
 * 1) 台账汇总口径：同一 SKU 可配置多道外发工序（每道工序各自按 SKU 数量发货）。
 *    修复前「未发货合计」= totalQty(SKU 件数) - shippedTotal(工序累计)，
 *    两种口径相减 → 多工序 SKU 下系统性偏小，甚至首道工序发满后就显示为 0。
 * 2) 一键发货/收货：改为单请求批量接口（单事务），不再逐条串行请求。
 * 3) 发货/收货权限：由 outsource_ship / outsource_receive 权限点决定，
 *    不再按用户名 == '贝乐' 硬编码。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ref } from 'vue'

/** 当前测试用户被授予的权限点（用例可改写） */
let grantedPermissions = new Set<string>()
/** 当前测试用户名（用于证明权限判定与用户名无关） */
let currentUsername = 'admin'

vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({
    hasPermission: (code: string) => grantedPermissions.has(code),
    user: { get username() { return currentUsername } },
  }),
}))
vi.mock('@/composables/useToast', () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() },
}))
vi.mock('@/api/outsource', () => ({
  outsourceApi: {
    orderProcesses: vi.fn(),
    orderFlows: vi.fn(),
    shipProcessesBatch: vi.fn(),
    receiveProcessesBatch: vi.fn(),
  },
}))

import { outsourceApi } from '@/api/outsource'
import type { OrderOutsourceProcess } from '@/api/outsource'
import { toast } from '@/composables/useToast'
import { useOutsourceProcess } from '@/views/outsource/composables/useOutsourceProcess'
import type { OutsourceOrderRow } from '@/views/outsource/composables/useOutsourceOrders'

/** 订单：1 个 SKU（数量 10），配置 2 道外发工序 */
const detail = {
  id: 1,
  record_type: 'order',
  quantity: 10,
  product_name: '产品A',
  items: [
    {
      id: 11,
      order_id: 1,
      product_id: 1,
      product_name: '产品A',
      product_barcode: null,
      quantity: 10,
      order_type: 'order',
      country: null,
      deduct_stock: false,
      deduct_quantity: 0,
      note: null,
    },
  ],
} as unknown as OutsourceOrderRow

function makeProcess(over: Partial<OrderOutsourceProcess>): OrderOutsourceProcess {
  return {
    id: 1,
    order_id: 1,
    order_item_id: 11,
    product_id: 1,
    process_type: '电绣',
    sort_order: 0,
    status: 'pending',
    shipped_quantity: null,
    received_quantity: null,
    ...over,
  } as OrderOutsourceProcess
}

async function setup(processes: OrderOutsourceProcess[]) {
  vi.mocked(outsourceApi.orderProcesses).mockResolvedValue({
    success: true,
    total: processes.length,
    data: processes,
  } as never)
  const hook = useOutsourceProcess(ref(detail), () => {})
  await hook.loadProcesses(1)
  return hook
}

/** 两道工序：电绣已发 4 已收 0；转印已发 2 已收 2 */
const twoShippable = [
  makeProcess({ id: 1, process_type: '电绣', status: 'shipped', shipped_quantity: 4, received_quantity: 0 }),
  makeProcess({ id: 2, process_type: '转印', sort_order: 1, status: 'received', shipped_quantity: 2, received_quantity: 2 }),
]

describe('useOutsourceProcess 台账汇总口径', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    grantedPermissions = new Set(['outsource_manage', 'outsource_ship', 'outsource_receive'])
    currentUsername = 'admin'
  })

  it('首道工序发满后，未发货合计仍反映其余工序的未发货数量', async () => {
    const hook = await setup([
      makeProcess({ id: 1, process_type: '电绣', status: 'received', shipped_quantity: 10, received_quantity: 10 }),
      makeProcess({ id: 2, process_type: '转印', sort_order: 1, shipped_quantity: 0, received_quantity: null }),
    ])

    expect(hook.totalQty.value).toBe(10) // 订单件数（SKU 口径）
    expect(hook.shippedTotal.value).toBe(10) // 工序累计
    expect(hook.receivedTotal.value).toBe(10) // 工序累计
    // 修复前 = max(0, 10 - 10) = 0，会把「转印 10 件未发货」吞掉
    expect(hook.remainingTotal.value).toBe(10)
  })

  it('未发货合计与「未发货清单」各行剩余之和一致', async () => {
    const hook = await setup([
      makeProcess({ id: 1, process_type: '电绣', status: 'received', shipped_quantity: 10, received_quantity: 10 }),
      makeProcess({ id: 2, process_type: '转印', sort_order: 1, status: 'shipped', shipped_quantity: 4, received_quantity: null }),
    ])

    const listSum = hook.remainingList.value.reduce((sum, item) => sum + item.remaining, 0)
    expect(hook.remainingList.value).toHaveLength(1)
    expect(listSum).toBe(6)
    expect(hook.remainingTotal.value).toBe(listSum)
  })

  it('单工序 SKU 全部收货时，未发货合计为 0', async () => {
    const hook = await setup([
      makeProcess({ id: 1, process_type: '电绣', status: 'received', shipped_quantity: 10, received_quantity: 10 }),
    ])

    expect(hook.totalQty.value).toBe(10)
    expect(hook.shippedTotal.value).toBe(10)
    expect(hook.remainingTotal.value).toBe(0)
  })
})

describe('useOutsourceProcess 一键发货/收货（单请求批量）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    grantedPermissions = new Set(['outsource_manage', 'outsource_ship', 'outsource_receive'])
    currentUsername = 'admin'
  })

  it('一键发货只发 1 个批量请求，携带全部待发工序与数量', async () => {
    vi.mocked(outsourceApi.shipProcessesBatch).mockResolvedValue({ success: true, total: 2, data: [] } as never)
    const hook = await setup(twoShippable)

    await hook.handleBulkShip()

    // 「电绣」剩余 10-4=6；「转印」已收 2 但目标 10、已发 2，剩余 8 仍可发下一批
    expect(outsourceApi.shipProcessesBatch).toHaveBeenCalledTimes(1)
    expect(outsourceApi.shipProcessesBatch).toHaveBeenCalledWith(1, [
      { process_id: 1, quantity: 6 },
      { process_id: 2, quantity: 8 },
    ])
    expect(toast.success).toHaveBeenCalled()
  })

  it('回归：已部分收货但未发满的工序仍可继续发货', async () => {
    // 「王者荣耀」场景：目标 10、已发 4 已收 4 → 剩余 6 必须仍可发
    const partiallyReceived = [
      makeProcess({ id: 1, process_type: '电绣', status: 'shipped', shipped_quantity: 4, received_quantity: 4 }),
    ]
    vi.mocked(outsourceApi.shipProcessesBatch).mockResolvedValue({ success: true, total: 1, data: [] } as never)
    const hook = await setup(partiallyReceived)

    expect(hook.pendingCount.value).toBe(1)

    await hook.handleBulkShip()

    expect(outsourceApi.shipProcessesBatch).toHaveBeenCalledWith(1, [{ process_id: 1, quantity: 6 }])
  })

  it('已发满目标的工序不再参与一键发货', async () => {
    const fullyShipped = [
      makeProcess({ id: 1, process_type: '电绣', status: 'received', shipped_quantity: 10, received_quantity: 10 }),
    ]
    const hook = await setup(fullyShipped)

    expect(hook.pendingCount.value).toBe(0)

    await hook.handleBulkShip()

    expect(outsourceApi.shipProcessesBatch).not.toHaveBeenCalled()
    expect(toast.info).toHaveBeenCalledWith('没有待发货的工序')
  })

  it('一键收货只发 1 个批量请求', async () => {
    vi.mocked(outsourceApi.receiveProcessesBatch).mockResolvedValue({ success: true, total: 1, data: [] } as never)
    const hook = await setup(twoShippable)

    await hook.handleBulkReceive()

    // 仅「电绣」已发 4 未收 0 有待收剩余
    expect(outsourceApi.receiveProcessesBatch).toHaveBeenCalledTimes(1)
    expect(outsourceApi.receiveProcessesBatch).toHaveBeenCalledWith(1, [{ process_id: 1, quantity: 4 }])
  })

  it('批量失败时提示整批已回滚，且保留输入草稿', async () => {
    vi.mocked(outsourceApi.shipProcessesBatch).mockRejectedValue({
      response: { data: { detail: '外发工序 2：发货数量超过剩余数量（剩余 8）' } },
    })
    const hook = await setup(twoShippable)

    await hook.handleBulkShip()

    expect(toast.error).toHaveBeenCalledWith('外发工序 2：发货数量超过剩余数量（剩余 8）')
    expect(toast.success).not.toHaveBeenCalled()
  })
})

describe('useOutsourceProcess 发货/收货权限点', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    grantedPermissions = new Set()
    currentUsername = 'admin'
  })

  it('用户名不是「贝乐」但持有发货权限 → 可发货', async () => {
    grantedPermissions = new Set(['outsource_ship'])
    currentUsername = 'zhangsan'
    const hook = await setup([])

    expect(hook.canShip.value).toBe(true)
    expect(hook.canReceive.value).toBe(false)
  })

  it('用户名是「贝乐」且持有收货权限 → 可收货（不再被用户名挡住）', async () => {
    grantedPermissions = new Set(['outsource_receive'])
    currentUsername = '贝乐'
    const hook = await setup([])

    expect(hook.canReceive.value).toBe(true)
    expect(hook.canShip.value).toBe(false)
  })

  it('无权限点则既不可发货也不可收货', async () => {
    const hook = await setup([])

    expect(hook.canShip.value).toBe(false)
    expect(hook.canReceive.value).toBe(false)
  })
})
describe('useOutsourceProcess 一键发货/收货数量草稿三分支（P1-21 显式 0 回退）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    grantedPermissions = new Set(['outsource_manage', 'outsource_ship', 'outsource_receive'])
    currentUsername = 'admin'
  })

  it('发货草稿显式输入 0：拒绝整批并提示，不得静默回退为全部剩余量', async () => {
    vi.mocked(outsourceApi.shipProcessesBatch).mockResolvedValue({ success: true, total: 2, data: [] } as never)
    const hook = await setup(twoShippable)
    hook.setShipQty(1, '0') // 电绣剩余 6：显式 0 ≠ 未填
    await hook.handleBulkShip()

    // 修复前 Number('0') || 6 → 6：以「全部剩余量」静默发货，实际发货量大于用户意图
    expect(outsourceApi.shipProcessesBatch).not.toHaveBeenCalled()
    expect(toast.error).toHaveBeenCalledWith(expect.stringContaining('数量输入无效'))
  })

  it('发货草稿清空输入：拒绝整批并提示（OCR-3 M7：显示为空 ≠ 视为满额，防「实际发货量大于用户意图」）', async () => {
    vi.mocked(outsourceApi.shipProcessesBatch).mockResolvedValue({ success: true, total: 2, data: [] } as never)
    const hook = await setup(twoShippable)
    hook.setShipQty(1, '5')
    hook.setShipQty(1, '') // 清空：输入框显示为空，若静默回退满额则是「显示空=发全部」的认知落差
    await hook.handleBulkShip()

    // 修复前空串被判「未填」→ 按全部剩余量 6 发货；M7 起清空即无效，须显式填写
    expect(outsourceApi.shipProcessesBatch).not.toHaveBeenCalled()
    expect(toast.error).toHaveBeenCalledWith(expect.stringContaining('数量输入无效'))
  })

  it('发货草稿从未输入（undefined）：默认剩余量——「留空」语义仅保留给从未输入过', async () => {
    vi.mocked(outsourceApi.shipProcessesBatch).mockResolvedValue({ success: true, total: 2, data: [] } as never)
    const hook = await setup(twoShippable)
    await hook.handleBulkShip() // 全程未 setShipQty

    expect(outsourceApi.shipProcessesBatch).toHaveBeenCalledWith(1, [
      { process_id: 1, quantity: 6 },
      { process_id: 2, quantity: 8 },
    ])
  })

  it('发货草稿负数：拒绝整批并提示', async () => {
    const hook = await setup(twoShippable)
    hook.setShipQty(1, '-3')
    await hook.handleBulkShip()

    expect(outsourceApi.shipProcessesBatch).not.toHaveBeenCalled()
    expect(toast.error).toHaveBeenCalledWith(expect.stringContaining('数量输入无效'))
  })

  it('发货草稿非整数：拒绝整批并提示', async () => {
    const hook = await setup(twoShippable)
    hook.setShipQty(1, '2.5')
    await hook.handleBulkShip()

    expect(outsourceApi.shipProcessesBatch).not.toHaveBeenCalled()
    expect(toast.error).toHaveBeenCalledWith(expect.stringContaining('数量输入无效'))
  })

  it('发货草稿正整数：原样使用（不替换为剩余量）', async () => {
    vi.mocked(outsourceApi.shipProcessesBatch).mockResolvedValue({ success: true, total: 2, data: [] } as never)
    const hook = await setup(twoShippable)
    hook.setShipQty(1, '5')
    await hook.handleBulkShip()

    expect(outsourceApi.shipProcessesBatch).toHaveBeenCalledWith(1, [
      { process_id: 1, quantity: 5 },
      { process_id: 2, quantity: 8 },
    ])
  })

  it('收货草稿显式输入 0：拒绝整批；清空同样拒绝（M7 语义与发货一致）', async () => {
    vi.mocked(outsourceApi.receiveProcessesBatch).mockResolvedValue({ success: true, total: 1, data: [] } as never)
    const hook = await setup(twoShippable)
    hook.setReceiveQty(1, '0') // 电绣已发 4 未收 0：显式 0 ≠ 未填
    await hook.handleBulkReceive()

    expect(outsourceApi.receiveProcessesBatch).not.toHaveBeenCalled()
    expect(toast.error).toHaveBeenCalledWith(expect.stringContaining('数量输入无效'))

    hook.setReceiveQty(1, '') // 清空 → 同样拒绝（修复前默认剩余待收 4，M7 起须显式填写）
    await hook.handleBulkReceive()
    expect(outsourceApi.receiveProcessesBatch).not.toHaveBeenCalled()
    expect(toast.error).toHaveBeenCalledWith(expect.stringContaining('数量输入无效'))
  })

  it('收货草稿正整数：原样使用', async () => {
    vi.mocked(outsourceApi.receiveProcessesBatch).mockResolvedValue({ success: true, total: 1, data: [] } as never)
    const hook = await setup(twoShippable)
    hook.setReceiveQty(1, '3') // 剩余待收 4，显式收 3
    await hook.handleBulkReceive()

    expect(outsourceApi.receiveProcessesBatch).toHaveBeenCalledWith(1, [{ process_id: 1, quantity: 3 }])
  })
})
