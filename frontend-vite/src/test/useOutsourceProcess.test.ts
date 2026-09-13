/**
 * useOutsourceProcess 台账汇总口径 单元测试
 *
 * 回归背景：同一 SKU 可配置多道外发工序（每道工序各自按 SKU 数量发货）。
 * 修复前「未发货合计」= totalQty(SKU 件数) - shippedTotal(工序累计)，
 * 两种口径相减 → 多工序 SKU 下系统性偏小，甚至首道工序发满后就显示为 0。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ref } from 'vue'

// 隔离外部依赖：鉴权 store（避免引入 pinia 与整条 api/queryClient 依赖链）
vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({ hasPermission: () => true, user: { username: 'admin' } }),
}))
vi.mock('@/composables/useToast', () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() },
}))
vi.mock('@/api/outsource', () => ({
  outsourceApi: {
    orderProcesses: vi.fn(),
    orderFlows: vi.fn(),
    shipProcess: vi.fn(),
    receiveProcess: vi.fn(),
  },
}))

import { outsourceApi } from '@/api/outsource'
import type { OrderOutsourceProcess } from '@/api/outsource'
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

describe('useOutsourceProcess 台账汇总口径', () => {
  beforeEach(() => {
    vi.clearAllMocks()
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
