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
import { mount, flushPromises } from '@vue/test-utils'

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
  clearShipmentSelection: () => void
  fetchBatchOptions: () => Promise<void>
  editStagedForm: { customer: string; date: string; productName: string; quantity: number; note: string }
  editStagedOpen: boolean
  staged: StagedStockout[]
  batchOptions: { batch_no: string; available_quantity: number }[]
}

/** 挂起第 N 次 '/finished-stock/batches' 调用直至手动放行（制造在途窗口） */
function mockBatchesWithHold(holdAt: number) {
  let release!: () => void
  const held = new Promise<void>((r) => { release = r })
  mocks.getMock.mockImplementation(async (url: string) => {
    if (url === '/finished-stock/batches') {
      batchesCalls += 1
      if (batchesCalls === holdAt) await held
      return { success: true, data: [{ batch_no: 'B1', available_quantity: 10 }] }
    }
    if (url === '/aux/available-shipment') {
      return { success: true, data: { order_quantity: 1000, shipped_quantity: 0, available_quantity: 1000 } }
    }
    return { success: true, data: [] }
  })
  return () => release()
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
describe('StockOutTab — OCR-2 四项修复（双击守卫/批次缺失拦截/seq 隔离/无批次短路）', () => {

  it('保存链路在途时双击不重入：编辑保存只执行一次（M1）', async () => {
    const release = mockBatchesWithHold(2) // 挂住编辑路径的批次拉取，制造「保存未完成」窗口
    const wrapper = mountTab()
    const vm = wrapper.vm as unknown as StockOutTabVm
    await stageOneB1Item(vm, 2)

    vm.openEditStaged(0)
    vm.editStagedForm.quantity = 5
    const first = vm.saveEditStaged() // 第一次点击：挂起在编辑批次拉取（editSaving 已置位）
    await vm.saveEditStaged()         // 双击的第二次：必须被在途守卫同步挡下
    release()
    await first

    // addStaged 的 1 次 + 编辑的 1 次；无守卫时第二次调用会顶掉并重发（第 3 次）
    expect(batchesCalls).toBe(2)
    expect(vm.staged[0]!.quantity).toBe(5)
    expect(vm.editStagedOpen).toBe(false)
  })

  it('权威列表里找不到批次（如入库被删）：警告并拦截，而非静默放行（M2）', async () => {
    batchResponses = [
      [{ batch_no: 'B1', available_quantity: 10 }], // addStaged：B1 正常
      [{ batch_no: 'B9', available_quantity: 5 }],  // 编辑重拉：B1 已不在权威列表
    ]
    const wrapper = mountTab()
    const vm = wrapper.vm as unknown as StockOutTabVm
    await stageOneB1Item(vm, 2)

    vm.openEditStaged(0)
    vm.editStagedForm.quantity = 3 // 数量本身合法，但批次已不存在
    await vm.saveEditStaged()

    expect(mocks.showToast).toHaveBeenCalledWith(expect.stringContaining('B1'), 'warning')
    expect(vm.staged[0]!.quantity).toBe(2) // 未落值
    expect(vm.editStagedOpen).toBe(true)   // 弹窗保持打开
  })

  it('批次数据拉取失败（数据不可得）仍放行保存，由后端兜底（M2 护栏，防矫枉过正）', async () => {
    mocks.getMock.mockImplementation(async (url: string) => {
      if (url === '/finished-stock/batches') {
        batchesCalls += 1
        if (batchesCalls >= 2) throw new Error('network down') // 编辑重拉失败
        return { success: true, data: [{ batch_no: 'B1', available_quantity: 10 }] }
      }
      if (url === '/aux/available-shipment') {
        return { success: true, data: { order_quantity: 1000, shipped_quantity: 0, available_quantity: 1000 } }
      }
      return { success: true, data: [] }
    })
    const wrapper = mountTab()
    const vm = wrapper.vm as unknown as StockOutTabVm
    await stageOneB1Item(vm, 2)

    vm.openEditStaged(0)
    vm.editStagedForm.quantity = 5
    await vm.saveEditStaged()

    expect(mocks.showToast).not.toHaveBeenCalledWith(expect.stringContaining('已不存在'), 'warning')
    expect(vm.staged[0]!.quantity).toBe(5)
    expect(vm.editStagedOpen).toBe(false)
  })

  it('无 batch_no 的条目（OCR 暂存均属此类）编辑保存：不发批次请求（L4）', async () => {
    const wrapper = mountTab()
    const vm = wrapper.vm as unknown as StockOutTabVm
    // 暂存一条无批次条目（OCR 粘贴路径的典型形态：不带 batch_no）
    vm.form.customer = '客户甲'
    vm.form.productId = '7'
    vm.form.search = '产品A'
    vm.form.quantity = 2
    vm.form.batchNo = ''
    await vm.addStaged()
    expect(vm.staged.at(-1)?.batch_no).toBeUndefined()
    const callsAfterStaging = batchesCalls

    vm.openEditStaged(0)
    vm.editStagedForm.quantity = 5
    await vm.saveEditStaged()

    expect(batchesCalls).toBe(callsAfterStaging) // 短路：保存链路零批次请求
    expect(vm.staged[0]!.quantity).toBe(5)
    expect(vm.editStagedOpen).toBe(false)
  })

  it('编辑保存的批次请求不顶掉页面级在途请求：批次下拉数据仍落地（L3）', async () => {
    const release = mockBatchesWithHold(1) // 挂住页面级首次拉取
    const wrapper = mountTab()
    const vm = wrapper.vm as unknown as StockOutTabVm
    vm.form.productId = '7' // fetchBatchOptions 的 productId 早退守卫要求非空
    const pageFetch = vm.fetchBatchOptions() // 页面级第 1 次调用，挂起中
    await flushPromises()
    // 直接注入暂存条目：不经 addStaged——其收尾的 clearPageBatches 会作废页面级
    // 在途请求（OCR-3 Low 新语义），与本用例要证明的「编辑/页面级 seq 隔离」正交。
    vm.staged.push({ id: 111, product_id: '7', product_name: '产品A', customer: '客户甲', date: '2026-10-19', quantity: 2, note: '', batch_no: 'B1' })

    vm.openEditStaged(0)
    vm.editStagedForm.quantity = 5
    await vm.saveEditStaged() // 编辑路径用独立序号池：第 2 次调用正常完成
    expect(vm.staged[0]!.quantity).toBe(5)

    release() // 页面级在途请求此时才返回
    await pageFetch
    await flushPromises()
    // 共享 seq 时编辑请求会顶掉页面级（返回 null 被丢弃，batchOptions 保持空）
    expect(vm.batchOptions.some((b) => b.batch_no === 'B1')).toBe(true)
  })
})
describe('StockOutTab — OCR-3 修复（输入快照 M1 / null 不降级 M2 / 空值守卫 M3 / Low×3）', () => {
  it('M1: 保存期间另开另一行编辑：在途保存落「点击时的快照」，不得写入新行草稿或关掉新弹窗', async () => {
    const release = mockBatchesWithHold(2) // 挂住编辑路径的批次拉取，制造「保存未完成」窗口
    const wrapper = mountTab()
    const vm = wrapper.vm as unknown as StockOutTabVm
    await stageOneB1Item(vm, 2)
    await stageOneB1Item(vm, 3) // 第二条（customer 同值不触发 watch，无额外 batches 请求）
    expect(vm.staged).toHaveLength(2)

    vm.openEditStaged(0)
    vm.editStagedForm.quantity = 5
    const pending = vm.saveEditStaged() // 挂起在编辑批次拉取
    await flushPromises()
    // 在途期间用户从列表打开第 2 行并改成 9（openEditStaged 无守卫，列表入口不经弹窗）
    vm.openEditStaged(1)
    vm.editStagedForm.quantity = 9
    expect(vm.editStagedOpen).toBe(true)

    release()
    await pending
    // 落值必须是「点击保存时」的快照（第 1 行=5），不是新弹窗草稿（9）
    expect(vm.staged[0]!.quantity).toBe(5)
    expect(vm.staged[1]!.quantity).toBe(3)
    // 用户刚打开的第 2 行弹窗不得被在途保存关掉
    expect(vm.editStagedOpen).toBe(true)
  })

  it('M1: 保存期间该行被删除：await 后放弃应用，不得复活条目', async () => {
    const release = mockBatchesWithHold(2)
    const wrapper = mountTab()
    const vm = wrapper.vm as unknown as StockOutTabVm
    await stageOneB1Item(vm, 2)

    vm.openEditStaged(0)
    vm.editStagedForm.quantity = 5
    const pending = vm.saveEditStaged()
    await flushPromises()
    // 在途期间该行被删除（确认框已确认后的等价操作）
    vm.staged.splice(0, 1)
    expect(vm.staged).toHaveLength(0)

    release()
    await pending
    expect(vm.staged).toHaveLength(0) // 不得把快照写到「补位」的其他条目上或复活
  })

  it('M2: 编辑路径批次「数据不可得」（null）不得降级为页面级批次误判：放行保存', async () => {
    // 编辑重拉失败返回 null（数据不可得），而页面级 batchOptions 残留着
    // 「当前 form.productId」的批次（B1 可用 0）——那是别的产品的口径
    mocks.getMock.mockImplementation(async (url: string) => {
      if (url === '/finished-stock/batches') {
        batchesCalls += 1
        if (batchesCalls >= 2) throw new Error('network down') // 编辑重拉失败 → null
        return { success: true, data: [{ batch_no: 'B1', available_quantity: 10 }] }
      }
      if (url === '/aux/available-shipment') {
        return { success: true, data: { order_quantity: 1000, shipped_quantity: 0, available_quantity: 1000 } }
      }
      return { success: true, data: [] }
    })
    const wrapper = mountTab()
    const vm = wrapper.vm as unknown as StockOutTabVm
    await stageOneB1Item(vm, 2)
    vm.batchOptions = [{ batch_no: 'B1', available_quantity: 0 }] // 页面级残留（另一产品口径）

    vm.openEditStaged(0)
    vm.editStagedForm.quantity = 5
    await vm.saveEditStaged()

    // null=放行后端兜底；当前实现 `null ?? batchOptions` 降级误判 → 拦截 → 不落值（Red）
    expect(vm.staged[0]!.quantity).toBe(5)
    expect(vm.editStagedOpen).toBe(false)
    expect(mocks.showToast).not.toHaveBeenCalledWith(expect.stringContaining('可用不足'), 'error')
  })

  it('M2 对照: 新增路径缺省 batches 仍回落页面级列表闸门（防矫枉过正）', async () => {
    const wrapper = mountTab()
    const vm = wrapper.vm as unknown as StockOutTabVm
    await stageOneB1Item(vm, 2)
    // 页面级列表说 B1 可用 0：新增路径（不传 batches）仍须用它拦截
    vm.batchOptions = [{ batch_no: 'B1', available_quantity: 0 }]
    vm.form.customer = '客户甲'
    vm.form.productId = '7'
    vm.form.search = '产品A'
    vm.form.quantity = 5
    vm.form.batchNo = 'B1'
    await vm.addStaged()

    expect(mocks.showToast).toHaveBeenCalledWith(expect.stringContaining('可用不足'), 'error')
    expect(vm.staged).toHaveLength(1) // 第二条未暂存
  })

  it('M3: 编辑弹窗清空客户/出货时间后保存：空值守卫拦截（对齐新增路径 canAdd 口径）', async () => {
    const wrapper = mountTab()
    const vm = wrapper.vm as unknown as StockOutTabVm
    await stageOneB1Item(vm, 2)

    vm.openEditStaged(0)
    vm.editStagedForm.customer = ''
    await vm.saveEditStaged()
    expect(mocks.showToast).toHaveBeenCalledWith(expect.stringContaining('客户'), 'warning')
    expect(vm.staged[0]!.customer).toBe('客户甲') // 不得落成 customer='' 的无法提交形态
    expect(vm.editStagedOpen).toBe(true)

    vm.editStagedForm.customer = '客户甲'
    vm.editStagedForm.date = '' // date 输入框可被清空
    await vm.saveEditStaged()
    expect(mocks.showToast).toHaveBeenCalledWith(expect.stringContaining('出货时间'), 'warning')
    expect(vm.staged[0]!.date).not.toBe('')
    expect(vm.editStagedOpen).toBe(true)
  })

  it('Low: 编辑路径批次缺失提示「删除该行重新添加」——编辑弹窗无批次控件，「清除批次」不可操作', async () => {
    batchResponses = [
      [{ batch_no: 'B1', available_quantity: 10 }], // addStaged：B1 正常
      [{ batch_no: 'B9', available_quantity: 5 }],  // 编辑重拉：B1 已不在权威列表
    ]
    const wrapper = mountTab()
    const vm = wrapper.vm as unknown as StockOutTabVm
    await stageOneB1Item(vm, 2)

    vm.openEditStaged(0)
    vm.editStagedForm.quantity = 3
    await vm.saveEditStaged()

    expect(mocks.showToast).toHaveBeenCalledWith(expect.stringContaining('删除该行'), 'warning')
    expect(vm.staged[0]!.quantity).toBe(2) // 未落值
  })

  it('Low: 清空批次下拉推进序号：在途的旧产品批次请求迟到不得写回', async () => {
    const release = mockBatchesWithHold(1) // 挂住页面级首次拉取（watch customer 触发）
    const wrapper = mountTab()
    const vm = wrapper.vm as unknown as StockOutTabVm
    vm.form.productId = '7'
    vm.form.customer = '客户甲' // 触发 watch → fetchBatchOptions（第 1 次调用挂起中）
    await flushPromises()

    vm.clearShipmentSelection() // 用户点「清除产品」：批次下拉一并清空
    release() // 在途的旧产品批次请求此时返回
    await flushPromises()

    // 只清数组不推进序号时，迟到响应通过 seq 校验把旧批次写回下拉（Red）
    expect(vm.batchOptions).toHaveLength(0)
  })

  it('Low: 暂存成功后的收尾清空同样作废页面级在途批次请求（addStaged 路径）', async () => {
    const release = mockBatchesWithHold(1) // 挂住页面级首次拉取（watch customer 触发）
    const wrapper = mountTab()
    const vm = wrapper.vm as unknown as StockOutTabVm
    await stageOneB1Item(vm, 2) // addStaged 收尾 clearPageBatches()：作废挂起中的页面级请求

    release()
    await flushPromises()
    // 迟到的旧请求不得写回（表单已重置，下拉残留旧产品批次是 bug）
    expect(vm.batchOptions).toHaveLength(0)
  })
})