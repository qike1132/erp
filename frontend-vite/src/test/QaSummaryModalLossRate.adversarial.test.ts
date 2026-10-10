/**
 * QA 独立对抗性验证（严过关）— /purchase 汇总下单弹窗「损耗率自动落库 + 遮罩不关闭」修复。
 *
 * 本文件不复述工程师结论，只补工程师测试未覆盖的独立证据面：
 *  A. API 层真实请求体（工程师测试 mock 掉 purchaseApi，未触及 post() 组装）；
 *  B. usePurchaseActions.handleApplyLossRate 的失败 toast（工程师测试未覆盖）；
 *  C. 集成：落库成功复位 lossRateTouched 后，handleCompleteOrder/BatchComplete 不再夹带 spare_rate；
 *  D. 遗留风险 #1 已消除：落库失败 → 关闭弹窗 → 完成「另一张」订单不再夹带陈旧 spare_rate
 *     （close() 已复位 lossRate/lossRateTouched；本用例由「证明可达」反转为「证明已消除」）。
 *  E. 相邻遗留风险已消除（QA 反转）：applyLossRate 不再就地放大 factoryData，
 *     故「保存修改」的 edits 恒为空 —— 展示放大值 10.05 绝不再被当作真实数量落库。
 *     （原 E 用例断言的是**已被移除的缺陷**，本轮反转为新契约护栏，只收紧不放宽。）
 *
 * 若 C/D/E 出现失败，恰为「源码缺陷」信号，须阻断放行。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { nextTick } from 'vue'

// ---- hoisted mocks --------------------------------------------------------
const api = vi.hoisted(() => ({
  factorySummary: vi.fn(),
  supplierSummary: vi.fn(),
  saveFactoryEdits: vi.fn(),
}))
const req = vi.hoisted(() => ({ post: vi.fn() }))
const toastMocks = vi.hoisted(() => ({ showToast: vi.fn() }))

// 供 useSummaryModal / usePurchaseActions 使用的 purchaseApi（避免真实网络）
vi.mock('@/api', () => ({
  purchaseApi: {
    orders: vi.fn(),
    unprocessedOrders: vi.fn(),
    factorySummary: api.factorySummary,
    supplierSummary: api.supplierSummary,
    saveFactoryEdits: api.saveFactoryEdits,
    supplierSummaryExport: vi.fn(),
  },
}))

// 供 A 组直接验证 API 层 post() 请求体（purchase.ts 真实实现 + 打桩底层 request）
vi.mock('@/api/request', () => ({
  get: vi.fn(),
  put: vi.fn(),
  del: vi.fn(),
  postDownload: vi.fn(),
  post: req.post,
}))

vi.mock('@/composables/useToast', () => ({
  showToast: toastMocks.showToast,
  toast: { info: vi.fn(), success: vi.fn(), error: vi.fn(), warning: vi.fn() },
}))

vi.mock('@/composables/useExport', async () => {
  const { ref: r } = await import('vue')
  return { useExport: () => ({ exporting: r(false), runExport: vi.fn() }) }
})

import { useSummaryModal, magnifyByLossRate } from '@/views/purchase/composables/useSummaryModal'
import { usePurchaseActions } from '@/views/purchase/composables/usePurchaseActions'
import { purchaseApi as realPurchaseApi } from '@/api/purchase'
import type { FactorySummaryData } from '@/views/purchase/composables/useSummaryModal'

const factorySummaryResponse: FactorySummaryData = {
  success: true,
  order_count: 1,
  groups: [
    {
      customer_name: '客户A',
      product_name: '产品1',
      product_quantity: 100,
      suppliers: [
        {
          supplier_name: '供应商1',
          fabrics: [{ fabric_name: '布料A', specification: 'S1', quantity: 10, unit: '米', item_ids: [101] }],
        },
      ],
    },
  ],
}

// ---------------------------------------------------------------------------
// A. API 层真实请求体
// ---------------------------------------------------------------------------
describe('A. API 层：saveFactoryEdits/completeOrder/batchComplete 真实请求体', () => {
  beforeEach(() => {
    req.post.mockReset()
    req.post.mockResolvedValue({ success: true })
  })

  it('saveFactoryEdits([], rate, ids) → body 精确含 edits:[] / spare_rate / order_ids', async () => {
    await realPurchaseApi.saveFactoryEdits([], 5, [7, 8])
    expect(req.post).toHaveBeenCalledTimes(1)
    const [url, body] = req.post.mock.calls[0]!
    expect(url).toBe('/purchase-center/orders/factory-summary/save')
    // 精确相等：不允许夹带其它字段
    expect(body).toEqual({ edits: [], spare_rate: 5, order_ids: [7, 8] })
  })

  it('saveFactoryEdits(edits, undefined, []) → 不含 spare_rate、不含 order_ids 键（避免用 0 覆盖已存率 / 空 ids）', async () => {
    const edits = [{ item_ids: [101], quantity: 12 }]
    await realPurchaseApi.saveFactoryEdits(edits, undefined, [])
    const [, body] = req.post.mock.calls[0]!
    expect(body).toEqual({ edits })
    expect('spare_rate' in (body as object)).toBe(false)
    expect('order_ids' in (body as object)).toBe(false)
  })

  it('saveFactoryEdits([], 0, ids) → spare_rate=0 必须显式进入 body（0 不能被当作「未提供」丢掉）', async () => {
    await realPurchaseApi.saveFactoryEdits([], 0, [7, 8])
    const [, body] = req.post.mock.calls[0]!
    expect(body).toEqual({ edits: [], spare_rate: 0, order_ids: [7, 8] })
  })

  it('completeOrder(id) → 无 spare_rate 键；completeOrder(id, 5) → 带 spare_rate', async () => {
    await realPurchaseApi.completeOrder(1)
    await realPurchaseApi.completeOrder(1, 5)
    const [first, second] = req.post.mock.calls
    expect(first![1]).toEqual({ order_id: 1 })
    expect(second![1]).toEqual({ order_id: 1, spare_rate: 5 })
  })

  it('batchComplete(ids) 与 batchComplete(ids, 0) 区分：仅后者带 spare_rate', async () => {
    await realPurchaseApi.batchComplete([1, 2])
    await realPurchaseApi.batchComplete([1, 2], 0)
    const [first, second] = req.post.mock.calls
    expect(first![1]).toEqual({ ids: [1, 2] })
    expect(second![1]).toEqual({ ids: [1, 2], spare_rate: 0 })
  })
})

// ---------------------------------------------------------------------------
// B/C/D. usePurchaseActions 集成（真实 useSummaryModal + 打桩 purchaseOrders）
// ---------------------------------------------------------------------------
function buildActions(summary: ReturnType<typeof useSummaryModal>) {
  const purchaseOrders = {
    completeOrder: vi.fn().mockResolvedValue(true),
    batchComplete: vi.fn().mockResolvedValue(2),
    selectedIds: [1, 2],
  }
  const confirm = { confirm: vi.fn().mockResolvedValue(true) }
  const queryClient = { invalidateQueries: vi.fn() }
  const actions = usePurchaseActions({
    purchaseOrders: purchaseOrders as never,
    completed: {} as never,
    summary,
    confirm: confirm as never,
    queryClient: queryClient as never,
  })
  return { actions, purchaseOrders, confirm, queryClient }
}

describe('B/C/D. 损耗率自动落库与完成下单的集成语义', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.factorySummary.mockResolvedValue(factorySummaryResponse as never)
    api.supplierSummary.mockResolvedValue({ success: true, materials: [] } as never)
    api.saveFactoryEdits.mockResolvedValue({ success: true } as never)
    toastMocks.showToast.mockReset()
  })

  it('B. handleApplyLossRate 失败 → 捕获并 toast(error)，不向上抛出', async () => {
    api.saveFactoryEdits.mockRejectedValueOnce(new Error('网络错误'))
    const summary = useSummaryModal()
    await summary.openSummary([7, 8])
    const { actions } = buildActions(summary)

    await expect(actions.handleApplyLossRate(5)).resolves.toBeUndefined()

    expect(toastMocks.showToast).toHaveBeenCalledTimes(1)
    const [msg, type] = toastMocks.showToast.mock.calls[0]!
    expect(String(msg)).toContain('网络错误')
    expect(type).toBe('error')
    // 失败后状态保留：仍标记为「已交互未落库」
    expect(summary.lossRateTouched).toBe(true)
  })

  it('B. handleApplyLossRate 成功 → 不产生 error toast', async () => {
    const summary = useSummaryModal()
    await summary.openSummary([7, 8])
    const { actions } = buildActions(summary)

    await actions.handleApplyLossRate(5)

    expect(toastMocks.showToast).not.toHaveBeenCalled()
    expect(summary.lossRateTouched).toBe(false)
  })

  it('C. 落库成功（lossRateTouched 复位）→ 完成下单不再夹带 spare_rate', async () => {
    const summary = useSummaryModal()
    await summary.openSummary([7, 8])
    await summary.applyLossRateAndSave(5)
    expect(summary.lossRateTouched).toBe(false)

    const { actions, purchaseOrders } = buildActions(summary)
    await actions.handleCompleteOrder(111)
    await nextTick()
    // 第二参必须为 undefined（api 层据此不进 body）
    expect(purchaseOrders.completeOrder).toHaveBeenCalledWith(111, undefined)

    purchaseOrders.selectedIds = [1, 2]
    await actions.handleBatchComplete()
    expect(purchaseOrders.batchComplete).toHaveBeenCalledWith(undefined)
  })

  it('C 对照. lossRateTouched=true 时完成下单会夹带 spare_rate（证明接线有效，非恒 undefined）', async () => {
    const summary = useSummaryModal()
    await summary.openSummary([7, 8])
    // 直接 applyLossRate（仅本地，不落库）→ touched=true
    summary.applyLossRate(9)
    const { actions, purchaseOrders } = buildActions(summary)

    await actions.handleCompleteOrder(222)

    expect(purchaseOrders.completeOrder).toHaveBeenCalledWith(222, 9)
  })

  it('D. 【遗留风险已消除】落库失败 → 关闭弹窗 → 完成另一张订单，不再夹带陈旧 spare_rate', async () => {
    api.saveFactoryEdits.mockRejectedValueOnce(new Error('网络错误'))
    const summary = useSummaryModal()
    await summary.openSummary([7, 8])
    await expect(summary.applyLossRateAndSave(5)).rejects.toThrow('网络错误')
    // 失败态在关闭前保留（语义正确：尚未落库）
    expect(summary.lossRateTouched).toBe(true)

    // 用户关闭弹窗：close() 丢弃「尚未落库的损耗率交互」
    summary.close()
    expect(summary.lossRateTouched).toBe(false)
    expect(summary.lossRate).toBe(0)

    // 随后完成另一张订单 #999（与本次汇总无关）
    const { actions, purchaseOrders } = buildActions(summary)
    await actions.handleCompleteOrder(999)

    // 结论：陈旧 5‰ 不再被推给 #999 —— 泄漏已消除
    expect(purchaseOrders.completeOrder).toHaveBeenCalledWith(999, undefined)
  })

  it('D 对照. 落库成功后再关闭并完成另一张订单 → 不夹带（证明泄漏仅由失败态触发）', async () => {
    const summary = useSummaryModal()
    await summary.openSummary([7, 8])
    await summary.applyLossRateAndSave(5)
    summary.close()

    const { actions, purchaseOrders } = buildActions(summary)
    await actions.handleCompleteOrder(999)

    expect(purchaseOrders.completeOrder).toHaveBeenCalledWith(999, undefined)
  })
})

// ---------------------------------------------------------------------------
// E. 相邻遗留风险（反转护栏）：applyLossRate 不再就地放大 → 展示值绝不误落库
// ---------------------------------------------------------------------------
describe('E. applyLossRate 不再就地放大 → 展示放大值绝不作为 edits 落库（新契约护栏）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.factorySummary.mockResolvedValue(factorySummaryResponse as never)
    api.supplierSummary.mockResolvedValue({ success: true, materials: [] } as never)
    api.saveFactoryEdits.mockResolvedValue({ success: true } as never)
  })

  it('非编辑态输入损耗率 → 进入编辑态 → 保存修改：原始数量保持 10，edits 恒为空', async () => {
    const summary = useSummaryModal()
    await summary.openSummary([7, 8])

    // 非编辑态输入损耗率
    summary.applyLossRate(5)

    // 【失败态前置断言（已反转）】旧实现此处为 10.05（applyLossRate 就地放大）；
    // 新契约：applyLossRate 只记录「率」，原始数量保持落库真值 10。收紧：精确等于 10。
    expect(summary.factoryData!.groups[0]!.suppliers[0]!.fabrics[0]!.quantity).toBe(10)
    expect(summary.lossRate).toBe(5)
    expect(summary.lossRateTouched).toBe(true)
    // 展示派生仍会放大（10×1.005=10.05），但只是渲染派生、不写回 state
    expect(magnifyByLossRate(summary.factoryData!.groups[0]!.suppliers[0]!.fabrics[0]!.quantity, summary.lossRate)).toBeCloseTo(10.05, 5)

    // 用户随后点「自定义编辑」再点「保存修改」
    summary.toggleEditMode(true)
    await summary.saveFactoryEdits()

    const [editsArg] = vi.mocked(api.saveFactoryEdits).mock.calls[0]!
    // 新契约护栏（收紧）：edits 必须恒为空 —— 放大的展示值绝不作为真实数量提交。
    expect(editsArg).toEqual([])
    // 显式排除旧缺陷的提交形态，防止未来回归为「10.05 落库」：
    expect(editsArg).not.toContainEqual({ item_ids: [101], quantity: 10.05 })
    expect(editsArg).not.toEqual([{ item_ids: [101], quantity: 10.05 }])
  })
})
