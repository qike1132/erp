/**
 * StockOutTab 编辑暂存条目路径的批次可用量闸门（2026-10-19 审计 P1-20）。
 *
 * 缺陷：addStaged 暂存成功后 batchOptions 被清空（新增路径的收尾），而
 * saveEditStaged 的批次闸门 checkBatchAvailability 里 `if (!opt) return true`
 * ——批次查不到即放行。于是编辑路径把数量改超批次可用量时无任何警告，
 * 提交时才被后端拒（「部分出货成功」体验）。
 *
 * 修复：saveEditStaged 保存前按被编辑条目的 product_id 无条件重拉批次
 * （带 batchReqSeq 序号守卫，与产品级闸门的无条件重拉同口径），用重拉结果
 * 做批次校验；拉取失败/被在途请求顶掉时闸门放行，由后端做最终校验。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'

const mocks = vi.hoisted(() => ({
  getMock: vi.fn(),
  showToast: vi.fn(),
}))

vi.mock('@/api/request', () => ({
  get: mocks.getMock,
  post: vi.fn(),
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

/**
 * '/finished-stock/batches' 每次被调用的返回队列（队尾兜底重复）。
 * 用例可改写以模拟「编辑重拉时批次可用量已变化」。
 */
let batchResponses: Array<Array<{ batch_no: string; available_quantity: number }>> = []
/** '/finished-stock/batches' 被调用的次数（含新增路径带出与编辑路径重拉） */
let batchesCalls = 0

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
  openEditStaged: (idx: number) => void
  saveEditStaged: () => Promise<void>
  editStagedForm: { customer: string; date: string; productName: string; quantity: number; note: string }
  editStagedOpen: boolean
  staged: StagedStockout[]
}

/** 走真实 addStaged 链路暂存一条 B1 批次条目（闸门产品级给足，不干扰本组用例） */
async function stageOneB1Item(vm: StockOutTabVm, quantity: number) {
  vm.form.customer = '客户甲'
  vm.form.productId = '7'
  vm.form.search = '产品A'
  vm.form.quantity = quantity
  vm.form.batchNo = 'B1'
  await vm.addStaged()
  expect(vm.staged.at(-1)?.batch_no).toBe('B1')
}

beforeEach(() => {
  vi.clearAllMocks()
  batchesCalls = 0
  batchResponses = [[{ batch_no: 'B1', available_quantity: 10 }]]
  mocks.getMock.mockImplementation(async (url: string) => {
    if (url === '/finished-stock/batches') {
      const list = batchResponses[Math.min(batchesCalls, batchResponses.length - 1)]
      batchesCalls += 1
      return { success: true, data: list }
    }
    if (url === '/aux/available-shipment') {
      // 产品级可出货量给足，产品闸门放行，聚焦批次闸门
      return { success: true, data: { order_quantity: 1000, shipped_quantity: 0, available_quantity: 1000 } }
    }
    return { success: true, data: [] }
  })
})

describe('StockOutTab — 编辑暂存条目的批次可用量闸门（P1-20）', () => {
  it('暂存后 batchOptions 已清空：编辑把数量改超批次可用量，须重拉批次拦截而非放行', async () => {
    const wrapper = mountTab()
    const vm = wrapper.vm as unknown as StockOutTabVm
    await stageOneB1Item(vm, 2)
    expect(vm.staged).toHaveLength(1)

    // 编辑该条目：数量 15 > B1 可用 10（此刻 batchOptions 已被 addStaged 清空）
    vm.openEditStaged(0)
    vm.editStagedForm.quantity = 15
    await vm.saveEditStaged()

    // 保存前必须按 product_id 重拉批次（第 2 次 '/finished-stock/batches'）
    expect(batchesCalls).toBeGreaterThanOrEqual(2)
    // 拦截：错误提示 + 数量不落暂存 + 弹窗保持打开
    expect(mocks.showToast).toHaveBeenCalledWith(expect.stringContaining('B1'), 'error')
    expect(vm.staged[0]!.quantity).toBe(2)
    expect(vm.editStagedOpen).toBe(true)
  })

  it('闸门用的是重拉后的最新可用量，不是暂存时的快照', async () => {
    // 暂存时 B1 可用 10；编辑重拉时库存已收紧为 1 —— 数量 5 对快照合法、对最新值超额
    batchResponses = [
      [{ batch_no: 'B1', available_quantity: 10 }],
      [{ batch_no: 'B1', available_quantity: 1 }],
    ]
    const wrapper = mountTab()
    const vm = wrapper.vm as unknown as StockOutTabVm
    await stageOneB1Item(vm, 2)

    vm.openEditStaged(0)
    vm.editStagedForm.quantity = 5
    await vm.saveEditStaged()

    expect(mocks.showToast).toHaveBeenCalledWith(expect.stringContaining('B1'), 'error')
    expect(vm.staged[0]!.quantity).toBe(2)
  })

  it('编辑后数量仍在批次可用量内：正常保存（不矫枉过正）', async () => {
    const wrapper = mountTab()
    const vm = wrapper.vm as unknown as StockOutTabVm
    await stageOneB1Item(vm, 2)

    vm.openEditStaged(0)
    vm.editStagedForm.quantity = 8 // ≤ B1 可用 10
    await vm.saveEditStaged()

    expect(mocks.showToast).not.toHaveBeenCalledWith(expect.any(String), 'error')
    expect(vm.staged[0]!.quantity).toBe(8)
    expect(vm.editStagedOpen).toBe(false)
  })

  it('同批次多条暂存的累计口径：编辑后「其余暂存 + 本次」不得超过批次可用量', async () => {
    // B1 可用 10，先暂存两条各 4（累计 8）
    const wrapper = mountTab()
    const vm = wrapper.vm as unknown as StockOutTabVm
    await stageOneB1Item(vm, 4)
    await stageOneB1Item(vm, 4)

    // 编辑第 1 条改 5：排除自身后其余暂存 4，4+5=9 ≤ 10 应放行
    vm.openEditStaged(0)
    vm.editStagedForm.quantity = 5
    await vm.saveEditStaged()
    expect(vm.staged[0]!.quantity).toBe(5)

    // 编辑第 1 条改 7：其余暂存 4，4+7=11 > 10 应拦截
    vm.openEditStaged(0)
    vm.editStagedForm.quantity = 7
    await vm.saveEditStaged()
    expect(mocks.showToast).toHaveBeenCalledWith(expect.stringContaining('B1'), 'error')
    expect(vm.staged[0]!.quantity).toBe(5)
  })
})