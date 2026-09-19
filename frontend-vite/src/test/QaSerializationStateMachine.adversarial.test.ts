/**
 * QA(Edward) 独立对抗测试 —— 损耗率自动落库【任务 B 串行化】与【任务 C 状态机】。
 *
 * 不依赖工程师自有测试；自行用可控 deferred 门控观察「在途窗口」，逐条核实：
 *  B1 并发两次输入：任一时刻在途请求 ≤ 1，最后一次发送 = 最后一次输入；
 *  B2 快速三值：以最后一个值收尾（中间值允许合并跳过）；
 *  B3 实例隔离：两个 useSummaryModal 的串行状态互不干扰（证明状态是实例闭包、非模块级全局）；
 *  C1 saving → saved；
 *  C2 失败 → error，且 lossRateTouched 保持 true（未落库）；
 *  C3 orderIds 为空 → 不发请求、状态不被改（保持 idle）；
 *  C4 close() → idle；
 *  C5 组件层真实挂载：内联提示文案随状态变化（idle 不渲染）。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'

vi.mock('@/api', () => ({
  purchaseApi: {
    orders: vi.fn(),
    unprocessedOrders: vi.fn(),
    factorySummary: vi.fn(),
    supplierSummary: vi.fn(),
    saveFactoryEdits: vi.fn(),
    supplierSummaryExport: vi.fn(),
  },
}))

vi.mock('@/composables/useToast', () => ({
  showToast: vi.fn(),
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
}))

vi.mock('@/composables/useExport', async () => {
  const { ref: r } = await import('vue')
  return { useExport: () => ({ exporting: r(false), runExport: vi.fn() }) }
})

import { purchaseApi } from '@/api'
import { useSummaryModal } from '@/views/purchase/composables/useSummaryModal'
import SummaryModal from '@/views/purchase/components/SummaryModal.vue'
import type { FactorySummaryData } from '@/views/purchase/composables/useSummaryModal'

interface Deferred<T> {
  promise: Promise<T>
  resolve: (v: T) => void
  reject: (e: unknown) => void
}
function deferred<T>(): Deferred<T> {
  let resolve!: (v: T) => void
  let reject!: (e: unknown) => void
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej })
  return { promise, resolve, reject }
}
async function settle(rounds = 5) {
  for (let i = 0; i < rounds; i++) await new Promise((r) => setTimeout(r, 0))
}

const FACTORY: FactorySummaryData = {
  success: true,
  order_count: 1,
  groups: [
    {
      customer_name: '客户A',
      product_name: '产品1',
      product_quantity: 100,
      suppliers: [
        { supplier_name: '供应商1', fabrics: [{ fabric_name: '布料A', specification: 'S1', quantity: 10, unit: '米', item_ids: [101] }] },
      ],
    },
  ],
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(purchaseApi.factorySummary).mockResolvedValue(FACTORY as never)
  vi.mocked(purchaseApi.supplierSummary).mockResolvedValue({ success: true, materials: [] } as never)
  vi.mocked(purchaseApi.saveFactoryEdits).mockResolvedValue({ success: true } as never)
})

describe('B. 串行化（独立复核）', () => {
  it('B1 并发 (5)、(50)：在途峰值=1，且最终发送 = 最后输入 50', async () => {
    const gates: Deferred<{ success: boolean }>[] = []
    const rates: number[] = []
    let inFlight = 0
    let maxInFlight = 0
    vi.mocked(purchaseApi.saveFactoryEdits).mockImplementation(((editsArg: unknown, rate?: number) => {
      inFlight++
      maxInFlight = Math.max(maxInFlight, inFlight)
      rates.push(rate as number)
      expect(editsArg).toEqual([]) // 自动落库恒不提交 edits
      const g = deferred<{ success: boolean }>()
      gates.push(g)
      return g.promise.finally(() => { inFlight-- })
    }) as never)

    const m = useSummaryModal()
    await m.openSummary([7, 8])

    const p1 = m.applyLossRateAndSave(5)
    const p2 = m.applyLossRateAndSave(50) // 不 await 第一个
    await settle()
    expect(maxInFlight).toBe(1)
    expect(rates).toEqual([5])

    gates[0]!.resolve({ success: true })
    await settle()
    expect(rates).toEqual([5, 50])
    expect(maxInFlight).toBe(1)

    gates[1]!.resolve({ success: true })
    await Promise.all([p1, p2])

    expect(maxInFlight).toBe(1)
    expect(rates[rates.length - 1]).toBe(50)
    expect(m.lossRate).toBe(50)
    expect(m.lossRateTouched).toBe(false)
    expect(m.lossRateSaveState).toBe('saved')
  })

  it('B2 快速 (5)、(20)、(50)：以 50 收尾，中间值 20 被合并跳过', async () => {
    const rates: number[] = []
    let inFlight = 0
    let maxInFlight = 0
    vi.mocked(purchaseApi.saveFactoryEdits).mockImplementation(((editsArg: unknown, rate?: number) => {
      inFlight++
      maxInFlight = Math.max(maxInFlight, inFlight)
      rates.push(rate as number)
      return new Promise<{ success: boolean }>((resolve) => {
        setTimeout(() => { inFlight--; resolve({ success: true }) }, 0)
      })
    }) as never)

    const m = useSummaryModal()
    await m.openSummary([7, 8])

    const p1 = m.applyLossRateAndSave(5)
    const p2 = m.applyLossRateAndSave(20)
    const p3 = m.applyLossRateAndSave(50)
    await settle(8)
    await Promise.all([p1, p2, p3])

    expect(maxInFlight).toBe(1)
    expect(rates[rates.length - 1]).toBe(50)
    expect(rates).not.toContain(20)
    expect(m.lossRate).toBe(50)
    expect(m.lossRateSaveState).toBe('saved')
  })

  it('B3 实例隔离：两个实例各自独立在途（峰值=2）→ 串行状态非模块级全局', async () => {
    let inFlight = 0
    let maxInFlight = 0
    vi.mocked(purchaseApi.saveFactoryEdits).mockImplementation((() => {
      inFlight++
      maxInFlight = Math.max(maxInFlight, inFlight)
      return new Promise<{ success: boolean }>((resolve) => {
        setTimeout(() => { inFlight--; resolve({ success: true }) }, 0)
      })
    }) as never)

    const a = useSummaryModal()
    const b = useSummaryModal()
    await a.openSummary([1])
    await b.openSummary([2])

    await Promise.all([a.applyLossRateAndSave(5), b.applyLossRateAndSave(50)])
    await settle(5)

    expect(maxInFlight).toBe(2)
    expect(a.lossRate).toBe(5)
    expect(b.lossRate).toBe(50)
    expect(a.lossRateSaveState).toBe('saved')
    expect(b.lossRateSaveState).toBe('saved')
  })
})

describe('C. 状态机（独立复核）', () => {
  it('C1 saving → saved', async () => {
    const gate = deferred<{ success: boolean }>()
    vi.mocked(purchaseApi.saveFactoryEdits).mockReturnValueOnce(gate.promise as never)

    const m = useSummaryModal()
    await m.openSummary([7, 8])
    const p = m.applyLossRateAndSave(5)
    expect(m.lossRateSaveState).toBe('saving')

    gate.resolve({ success: true })
    await p
    expect(m.lossRateSaveState).toBe('saved')
  })

  it('C2 失败 → error，lossRateTouched 保持 true', async () => {
    vi.mocked(purchaseApi.saveFactoryEdits).mockRejectedValueOnce(new Error('boom'))
    const m = useSummaryModal()
    await m.openSummary([7, 8])

    await expect(m.applyLossRateAndSave(5)).rejects.toThrow('boom')

    expect(m.lossRateSaveState).toBe('error')
    expect(m.lossRateTouched).toBe(true)
    expect(m.lossRate).toBe(5) // 本地展示保持可用
  })

  it('C3 orderIds 为空 → 不发请求、状态保持 idle', async () => {
    const m = useSummaryModal()
    await m.applyLossRateAndSave(5)

    expect(purchaseApi.saveFactoryEdits).not.toHaveBeenCalled()
    expect(m.lossRateSaveState).toBe('idle')
    expect(m.lossRateTouched).toBe(true)
  })

  it('C4 close() → idle（成功态 / 失败态两条路径）', async () => {
    const ok = useSummaryModal()
    await ok.openSummary([7, 8])
    await ok.applyLossRateAndSave(5)
    expect(ok.lossRateSaveState).toBe('saved')
    ok.close()
    expect(ok.lossRateSaveState).toBe('idle')

    vi.mocked(purchaseApi.saveFactoryEdits).mockRejectedValueOnce(new Error('boom'))
    const bad = useSummaryModal()
    await bad.openSummary([7, 8])
    await expect(bad.applyLossRateAndSave(5)).rejects.toThrow('boom')
    expect(bad.lossRateSaveState).toBe('error')
    bad.close()
    expect(bad.lossRateSaveState).toBe('idle')
  })

  it('C5 组件层真实挂载：内联提示随状态变化，idle 不渲染', () => {
    const cases: { state: 'idle' | 'saving' | 'saved' | 'error'; text: string | null }[] = [
      { state: 'saving', text: '保存中…' },
      { state: 'saved', text: '已保存' },
      { state: 'error', text: '保存失败' },
      { state: 'idle', text: null },
    ]
    const known = ['保存中…', '已保存', '保存失败']
    for (const c of cases) {
      const w = mount(SummaryModal, {
        props: {
          open: true,
          factoryData: FACTORY,
          supplierData: null,
          editMode: false,
          lossRate: 5,
          orderCount: 1,
          supplierGroups: [],
          lossRateSaveState: c.state,
        },
        global: { stubs: { UiDialog: { template: '<div><slot name="title" /><slot /></div>' } } },
      })
      const hint = w.findAll('span').find((s) => known.includes(s.text()))
      if (c.text === null) expect(hint).toBeUndefined()
      else expect(hint?.text()).toBe(c.text)
      w.unmount()
    }
  })
})
