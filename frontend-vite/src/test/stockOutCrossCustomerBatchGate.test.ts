/**
 * StockOutTab 批次闸门的累计口径：按 (产品, 批次)，**不含客户**（2026-11-16 上线前审计 Medium）。
 *
 * 缺陷：checkBatchAvailability 的累计过滤条件里带了 `s.customer === opts.customer`，
 * 而后端 get_batch_available 的判据只有 (产品, 批次)——批次可用量是跨客户共享的存量。
 * 于是客户A、客户B 各自暂存同一批次都能单独过闸门，累计超卖的那几行要等提交才被
 * 后端逐行拒，结果是「部分出货成功」：先出的已扣库存，其余行要人工重做。
 *
 * 修复：累计口径改 `product_id + batch_no`（客户维度删除）。本用例锁三件事：
 *   1) 两客户合计超可用量 → 第二行被闸门拦住（提示 + 不入暂存 + 不发提交请求）；
 *   2) 合计仍在可用量内 → 照常暂存（防矫枉过正，别把跨客户一律拦死）；
 *   3) 不同批次互不占用（口径只认批次，不是「同产品全批次合计」）。
 *
 * 注：views/stock/composables/useStockOutBatches.ts 里另有一份同口径实现，但全仓零 import，
 * 本用例覆盖的是 StockOutTab 里真正生效的那一份（任务明确不接那个 composable）。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'

const mocks = vi.hoisted(() => ({
  getMock: vi.fn(),
  postMock: vi.fn(),
  showToast: vi.fn(),
}))

vi.mock('@/api/request', () => ({
  get: mocks.getMock,
  post: mocks.postMock,
  put: vi.fn(),
  del: vi.fn(),
  upload: vi.fn(),
  download: vi.fn(),
}))

vi.mock('@tanstack/vue-query', () => ({
  useQueryClient: () => ({ invalidateQueries: vi.fn() }),
}))

vi.mock('@/stores/catalog', () => ({
  useCatalogStore: () => ({
    activeCustomerNames: [],
    ensureActiveCustomerNames: vi.fn(async () => {}),
  }),
}))

vi.mock('@/composables/useToast', () => ({
  showToast: mocks.showToast,
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() },
}))

import StockOutTab from '@/views/stock/StockOutTab.vue'
import type { StagedStockout } from '@/types'

/** 页面级批次列表：B1/B2 各可用 10（两客户共用同一批次存量，正是本缺陷的前提） */
const BATCHES = [
  { batch_no: 'B1', available_quantity: 10 },
  { batch_no: 'B2', available_quantity: 10 },
]

function mountTab() {
  return mount(StockOutTab, {
    global: {
      stubs: {
        StockOutInputForm: true,
        StockOutStagingList: true,
        StockOutEditStagedDialog: true,
        UiConfirmDialog: true,
        UiButton: { template: '<button><slot /></button>' },
      },
    },
  })
}

/** StockOutTab（script setup）经 wrapper.vm 暴露给测试的最小绑定面 */
interface StockOutTabVm {
  form: { customer: string; date: string; search: string; productId: string; quantity: number; note: string; batchNo: string }
  addStaged: () => Promise<void>
  staged: StagedStockout[]
  batchOptions: { batch_no: string; available_quantity: number }[]
}

interface StageInput {
  customer: string
  quantity: number
  batchNo: string
}

/**
 * 走真实 addStaged 链路暂存一行。
 *
 * 页面级批次列表显式注入：addStaged 成功收尾会 clearPageBatches()（表单重置的一部分），
 * 不注入的话第二次暂存时闸门拿到的是空列表 → 「参数缺省即放行」分支，测不到累计逻辑。
 */
async function stageOne(vm: StockOutTabVm, input: StageInput) {
  vm.batchOptions = [...BATCHES]
  vm.form.productId = '7'
  vm.form.search = '产品A'
  vm.form.customer = input.customer
  vm.form.quantity = input.quantity
  vm.form.batchNo = input.batchNo
  await vm.addStaged()
}

beforeEach(() => {
  vi.clearAllMocks()
  mocks.getMock.mockImplementation(async (url: string) => {
    if (url === '/finished-stock/batches') return { success: true, data: BATCHES }
    if (url === '/aux/available-shipment') {
      // 产品级可出货量给足：聚焦批次闸门，别让产品闸门抢先拦住
      // 真实形状：扁平对象（无 {success,data} 信封）。写成信封形状会让产品级闸门 fail-open，
      // 于是「产品闸门没生效」这件事被 mock 掩盖（2026-10-17 审计 P1-16）
      return { order_quantity: 1000, shipped_quantity: 0, available_quantity: 1000 }
    }
    return { success: true, data: [] }
  })
})

describe('StockOutTab — 批次闸门累计口径按 (产品, 批次)，不含客户', () => {
  it('客户A 与客户B 各暂存同批次：合计超可用量时第二行被闸门拦住，不发提交请求', async () => {
    const wrapper = mountTab()
    const vm = wrapper.vm as unknown as StockOutTabVm

    await stageOne(vm, { customer: '客户A', quantity: 6, batchNo: 'B1' })
    expect(vm.staged).toHaveLength(1)
    expect(vm.staged[0]!.customer).toBe('客户A')

    // 客户B 与客户A 无任何订单关系，但 B1 的可用量是同一个 10 件存量
    await stageOne(vm, { customer: '客户B', quantity: 6, batchNo: 'B1' })

    // 6 + 6 = 12 > 10：拦在暂存区，而不是留到提交时被后端拒（部分出货成功）
    expect(mocks.showToast).toHaveBeenCalledWith(expect.stringContaining('可用不足'), 'error')
    expect(vm.staged).toHaveLength(1)
    expect(vm.staged[0]!.customer).toBe('客户A')
    // 闸门是纯前端拦截：整批提交请求一次都不该发出
    expect(mocks.postMock).not.toHaveBeenCalled()
  })

  it('跨客户但合计仍在可用量内：照常暂存（防矫枉过正）', async () => {
    const wrapper = mountTab()
    const vm = wrapper.vm as unknown as StockOutTabVm

    await stageOne(vm, { customer: '客户A', quantity: 6, batchNo: 'B1' })
    await stageOne(vm, { customer: '客户B', quantity: 3, batchNo: 'B1' }) // 6 + 3 = 9 ≤ 10

    expect(mocks.showToast).not.toHaveBeenCalledWith(expect.stringContaining('可用不足'), 'error')
    expect(vm.staged).toHaveLength(2)
    expect(vm.staged[1]!.customer).toBe('客户B')
  })

  it('不同批次互不占用：口径只认 product_id + batch_no 组合', async () => {
    const wrapper = mountTab()
    const vm = wrapper.vm as unknown as StockOutTabVm

    await stageOne(vm, { customer: '客户A', quantity: 6, batchNo: 'B1' })
    await stageOne(vm, { customer: '客户B', quantity: 6, batchNo: 'B2' }) // B2 自己的 10 件额度

    expect(mocks.showToast).not.toHaveBeenCalledWith(expect.stringContaining('可用不足'), 'error')
    expect(vm.staged).toHaveLength(2)
    expect(vm.staged.map((s) => s.batch_no)).toEqual(['B1', 'B2'])
  })
})
