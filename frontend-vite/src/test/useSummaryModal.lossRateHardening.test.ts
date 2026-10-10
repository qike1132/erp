/**
 * 本轮加固（3 项遗留风险）新增护栏 —— 工程师自有测试文件（不复用旧语义断言）。
 *
 * 【任务 A】损耗率「放大数量列」改为纯展示派生
 *   A1 applyLossRate 不再就地放大 factoryData / supplierData
 *   A2 放大值不再被「保存修改」当作真实 edits 落库（edits 恒空）
 *   A3 无复利：多次改率后展示值只基于原始基数
 *   A4 输出保真（回归护栏）：buildFactoryHtml 的数量列口径不变
 *   A5 供应商「数量」与工厂「数量」列同源派生、且不写回原始数据
 *   A6 自定义编辑数量 / 逐行损耗率后，供应商页数量与工厂页实时一致（DOM 级）
 * 【任务 B】损耗率自动落库请求串行化
 *   B1 并发两次输入 → 任一时刻在途 ≤ 1，最后一次发出的率 = 最后输入
 *   B2 快速三个值 → 以最后一个值收尾（中间值允许合并跳过）
 *   B3 在途失败且有 pending → 抛错、lossRateTouched 保持 true、队列清空后可重试
 * 【任务 C】自动保存可见反馈
 *   C1 saving → saved；C2 error + toast 恰一次；C3 close() → idle；C4 无 orderIds 不改状态
 *
 * 注意：本文件刻意不修改既有断言。旧语义（就地放大）的既有断言保留在原文件中不动，
 * 已由报告「按新契约应更新但本轮不动的用例」单独列出。
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

import { buildFactoryHtml, useSummaryModal } from '@/views/purchase/composables/useSummaryModal'
import { usePurchaseActions } from '@/views/purchase/composables/usePurchaseActions'
import SummaryModal from '@/views/purchase/components/SummaryModal.vue'
import { showToast } from '@/composables/useToast'
import { purchaseApi } from '@/api'
import type { FactorySummaryData, SupplierSummaryData } from '@/views/purchase/composables/useSummaryModal'

// ---------------------------------------------------------------------------
// 工具
// ---------------------------------------------------------------------------

interface Deferred<T> {
  promise: Promise<T>
  resolve: (v: T) => void
  reject: (e: unknown) => void
}

/** 可手动控制结算时机的 promise（用于精确观察「在途」窗口） */
function deferred<T>(): Deferred<T> {
  let resolve!: (v: T) => void
  let reject!: (e: unknown) => void
  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

/** 让已排队的微任务 / 宏任务全部跑完（不依赖固定 sleep 时长做正确性判断） */
async function settle(rounds = 4) {
  for (let i = 0; i < rounds; i++) await new Promise((r) => setTimeout(r, 0))
}

const factoryOf = (fabricQty: number): FactorySummaryData => ({
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
          fabrics: [
            { fabric_name: '布料A', specification: 'S1', quantity: fabricQty, unit: '米', item_ids: [101] },
          ],
        },
      ],
    },
  ],
})

const SUPPLIER_RESPONSE: SupplierSummaryData = {
  success: true,
  materials: [
    { material_name: '布料A', specification: 'S1', total_quantity: 20, unit: '米', supplier_name: '供应商1' },
  ],
}

/** 串行化观测器：记录每次发送的率 / edits / 并发峰值 */
function trackSends() {
  const state = {
    inFlight: 0,
    maxInFlight: 0,
    rates: [] as number[],
    edits: [] as unknown[],
  }
  return state
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(purchaseApi.factorySummary).mockResolvedValue(factoryOf(10) as never)
  vi.mocked(purchaseApi.supplierSummary).mockResolvedValue(SUPPLIER_RESPONSE as never)
  vi.mocked(purchaseApi.saveFactoryEdits).mockResolvedValue({ success: true } as never)
})

// ---------------------------------------------------------------------------
// A. 损耗率放大改为纯展示派生
// ---------------------------------------------------------------------------
describe('A. 损耗率放大改为纯展示派生（不再就地改写数据）', () => {
  it('A1 applyLossRate(5) 后 factoryData/supplierData 保持原始值（不再被就地放大）', async () => {
    const m = useSummaryModal()
    await m.openSummary([7, 8])

    m.applyLossRate(5)

    // 原始真值必须原封不动（旧实现会变成 10.05 / 20.1）
    expect(m.factoryData!.groups[0]!.suppliers[0]!.fabrics[0]!.quantity).toBe(10)
    expect(m.supplierData!.materials[0]!.total_quantity).toBe(20)
    // 只有「率」与「已交互」标记被记录
    expect(m.lossRate).toBe(5)
    expect(m.lossRateTouched).toBe(true)
  })

  it('A2 输入损耗率 → 进编辑态 → 保存修改：edits 不含放大派生的伪编辑（恒为空）', async () => {
    const m = useSummaryModal()
    await m.openSummary([7, 8])

    m.applyLossRate(5)
    m.toggleEditMode(true)
    await m.saveFactoryEdits()

    expect(purchaseApi.saveFactoryEdits).toHaveBeenCalledTimes(1)
    const [editsArg, rateArg, idsArg] = vi.mocked(purchaseApi.saveFactoryEdits).mock.calls[0]!
    // 旧实现在此处会提交 [{ item_ids: [101], quantity: 10.05 }]（放大值被当真实数量落库）
    expect(editsArg).toEqual([])
    expect(rateArg).toBe(5)
    expect(idsArg).toEqual([7, 8])
  })

  it('A2 对照：编辑态真实改过的数量仍会作为 edits 提交（diff 逻辑未被削弱）', async () => {
    const m = useSummaryModal()
    await m.openSummary([7, 8])

    m.applyLossRate(5)
    m.toggleEditMode(true)
    m.updateFactoryQty(0, 0, 0, 12)
    await m.saveFactoryEdits()

    const [editsArg, rateArg] = vi.mocked(purchaseApi.saveFactoryEdits).mock.calls[0]!
    expect(editsArg).toEqual([{ item_ids: [101], quantity: 11.94 }])
    expect(rateArg).toBe(5)
  })

  it('A3 幂等/无复利：save(5) 后再输入 8‰，展示值基于原始基数而非放大值', async () => {
    vi.mocked(purchaseApi.factorySummary).mockResolvedValue(factoryOf(100) as never)
    const m = useSummaryModal()
    await m.openSummary([7, 8])

    await m.applyLossRateAndSave(5)
    // 原始基数没有被放大值覆盖（旧实现此处会变成 100.5）
    expect(m.factoryData!.groups[0]!.suppliers[0]!.fabrics[0]!.quantity).toBe(100)

    m.applyLossRate(8)

    // 展示加放 = 100 × 1.008 = 100.8 → 向上取整显示 101（旧实现 = 100.5 × 1.008 = 101.3，即复利）
    const wrapper = mount(SummaryModal, {
      props: {
        open: true,
        factoryData: m.factoryData,
        supplierData: m.supplierData,
        editMode: false,
        lossRate: m.lossRate,
        orderCount: 1,
        supplierGroups: m.supplierGroups,
      },
      global: { stubs: { UiDialog: { template: '<div><slot name="title" /><slot /></div>' } } },
    })
    const firstDataRow = wrapper.findAll('tbody tr')[0]!
    expect(firstDataRow.findAll('td')[8]!.text()).toBe('101')
    wrapper.unmount()
  })

  it('A4 输出保真（回归护栏）：buildFactoryHtml 的「数量」列 = 放大值；rate=0 时 = 原值', () => {
    const data = factoryOf(10)
    const cellOf = (html: string) => {
      const doc = new DOMParser().parseFromString(`<table>${html}</table>`, 'text/html')
      const cells = [...doc.querySelectorAll('tbody tr td')]
      return cells[8]!.textContent // 第 9 列 = 数量（第 4 列已新增备品数量）
    }

    // 10 × 1.005 = 10.05 → 向上取整为 11
    expect(cellOf(buildFactoryHtml(data, 5))).toBe('11')
    // rate=0 时仍等于原值（10 取整仍为 10）
    expect(cellOf(buildFactoryHtml(data, 0))).toBe('10')
    // 打印 / 导出的 HTML 不因展示派生而被写回：源数据保持原值
    expect(data.groups[0]!.suppliers[0]!.fabrics[0]!.quantity).toBe(10)
  })

  it('A5 供应商「数量」与工厂「数量」列同源派生、原始数据不被写回', async () => {
    // 供应商汇总与工厂汇总在后端同源（同一 (供应商,物料,规格,单位)），故真实数据两侧基数相同。
    vi.mocked(purchaseApi.factorySummary).mockResolvedValue(factoryOf(20) as never)
    const m = useSummaryModal()
    await m.openSummary([7, 8])

    m.applyLossRate(5)

    // 供应商展示值与工厂「数量」列同源：ceil(20 × 1.005) = 21
    expect(m.supplierGroups).toHaveLength(1)
    expect(m.supplierGroups[0]!.materials[0]!.total_quantity).toBe(21)
    // 原始数据未被写回（旧实现会变成 20.1）
    expect(m.supplierData!.materials[0]!.total_quantity).toBe(20)
    expect(m.factoryData!.groups[0]!.suppliers[0]!.fabrics[0]!.quantity).toBe(20)
  })

  it('A6 工厂自定义编辑数量 / 逐行损耗率后，供应商页「数量」实时一致（DOM 级）', async () => {
    vi.mocked(purchaseApi.factorySummary).mockResolvedValue(factoryOf(20) as never)
    vi.mocked(purchaseApi.supplierSummary).mockResolvedValue({
      success: true,
      materials: [
        { material_name: '布料A', specification: 'S1', total_quantity: 20, unit: '米', supplier_name: '供应商1' },
      ],
    } as never)

    const m = useSummaryModal()
    await m.openSummary([7, 8])
    // 逐行损耗率 100‰：工厂 20 × 1.1 = 22
    await m.applyFabricLossRateAndSave(0, 0, 0, 100)

    // 每次按 m 的**当前**状态重新挂载，等价于真实页面中 prop 随响应式状态重渲染。
    const mountModal = () =>
      mount(SummaryModal, {
        props: {
          open: true,
          factoryData: m.factoryData,
          supplierData: m.supplierData,
          editMode: m.editMode,
          lossRate: m.lossRate,
          fabricLossRates: m.fabricLossRates,
          orderCount: 1,
          supplierGroups: m.supplierGroups,
        },
        global: { stubs: { UiDialog: { template: '<div><slot name="title" /><slot /></div>' } } },
      })
    const supplierRowQty = (w: ReturnType<typeof mountModal>) => {
      const rows = w.findAll('tbody tr').filter((r) => r.findAll('td').length >= 4)
      return rows[0]!.findAll('td')[3]!.text()
    }

    // 非编辑态：工厂「数量」列与供应商页「数量」逐字一致（22）
    const before = mountModal()
    const factoryCell = before.findAll('tbody tr')[0]!.findAll('td')[8]!.text()
    expect(factoryCell).toBe('22')
    await before.findAll('.sm-tab-btn')[1]!.trigger('click')
    expect(supplierRowQty(before)).toBe(factoryCell)
    before.unmount()

    // 自定义编辑：把该行数量改成 33（真值 30）
    m.toggleEditMode(true)
    m.updateFactoryQty(0, 0, 0, 33)
    expect(m.factoryData!.groups[0]!.suppliers[0]!.fabrics[0]!.quantity).toBe(30)

    const after = mountModal()
    // 编辑态输入框加载 33（= 30 × 1.1）
    const inputValue = (after.find('input[type="number"]').element as HTMLInputElement).value
    expect(inputValue).toBe('33')
    // 切到供应商页签：立即同步为编辑中的 33（实时且逐字一致）
    await after.findAll('.sm-tab-btn')[1]!.trigger('click')
    expect(supplierRowQty(after)).toBe(inputValue)
    after.unmount()
  })
})

// ---------------------------------------------------------------------------
// B. 自动落库串行化
// ---------------------------------------------------------------------------
describe('B. 损耗率自动落库请求串行化', () => {
  it('B1 并发两次输入：任一时刻在途 ≤ 1，且最后一次发出的 rate = 最后输入', async () => {
    const state = trackSends()
    const gates: Deferred<{ success: boolean }>[] = []
    vi.mocked(purchaseApi.saveFactoryEdits).mockImplementation(((
      editsArg: unknown,
      rate?: number,
    ) => {
      state.inFlight++
      state.maxInFlight = Math.max(state.maxInFlight, state.inFlight)
      state.rates.push(rate as number)
      state.edits.push(editsArg)
      const g = deferred<{ success: boolean }>()
      gates.push(g)
      return g.promise.finally(() => {
        state.inFlight--
      })
    }) as never)

    const m = useSummaryModal()
    await m.openSummary([7, 8])

    const p1 = m.applyLossRateAndSave(5)
    const p2 = m.applyLossRateAndSave(50) // 刻意不 await 第一个
    await settle()

    // 串行化：第一个在途时第二个尚未发出
    expect(state.maxInFlight).toBe(1)
    expect(state.rates).toEqual([5])

    gates[0]!.resolve({ success: true })
    await settle()

    // 第一个完成后才发第二个，且值为用户最后一次输入 50
    expect(state.rates).toEqual([5, 50])
    expect(state.maxInFlight).toBe(1)

    gates[1]!.resolve({ success: true })
    await p1
    await p2

    expect(state.maxInFlight).toBe(1)
    expect(state.rates[state.rates.length - 1]).toBe(50)
    // 自动落库恒不提交 edits
    expect(state.edits.every((e) => Array.isArray(e) && e.length === 0)).toBe(true)
    expect(m.lossRate).toBe(50)
    expect(m.lossRateTouched).toBe(false)
    expect(m.lossRateSaveState).toBe('saved')
  })

  it('B2 快速三个值：以最后一个值收尾（中间值合并跳过）', async () => {
    const state = trackSends()
    vi.mocked(purchaseApi.saveFactoryEdits).mockImplementation(((
      editsArg: unknown,
      rate?: number,
    ) => {
      state.inFlight++
      state.maxInFlight = Math.max(state.maxInFlight, state.inFlight)
      state.rates.push(rate as number)
      state.edits.push(editsArg)
      return new Promise<{ success: boolean }>((resolve) => {
        setTimeout(() => {
          state.inFlight--
          resolve({ success: true })
        }, 0)
      })
    }) as never)

    const m = useSummaryModal()
    await m.openSummary([7, 8])

    const p1 = m.applyLossRateAndSave(5)
    const p2 = m.applyLossRateAndSave(20)
    const p3 = m.applyLossRateAndSave(50)
    await settle(6)
    await Promise.all([p1, p2, p3])

    expect(state.maxInFlight).toBe(1)
    expect(state.rates[state.rates.length - 1]).toBe(50)
    expect(state.rates).not.toContain(20) // 中间值允许合并跳过
    expect(m.lossRate).toBe(50)
    expect(m.lossRateTouched).toBe(false)
    expect(m.lossRateSaveState).toBe('saved')
  })

  it('B3 在途失败且有 pending：抛错、lossRateTouched 保持 true、队列清空后可重试', async () => {
    const gate = deferred<{ success: boolean }>()
    const rates: number[] = []
    vi.mocked(purchaseApi.saveFactoryEdits).mockImplementation(((editsArg: unknown, rate?: number) => {
      rates.push(rate as number)
      return gate.promise
    }) as never)

    const m = useSummaryModal()
    await m.openSummary([7, 8])

    const p1 = m.applyLossRateAndSave(5)
    const p2 = m.applyLossRateAndSave(50) // pending
    gate.reject(new Error('网络错误'))

    await expect(p1).rejects.toThrow('网络错误')
    await expect(p2).rejects.toThrow('网络错误')

    expect(m.lossRateTouched).toBe(true) // 失败态保留
    expect(m.lossRateSaveState).toBe('error')
    expect(rates).toEqual([5]) // 待发队列被清空：50 从未发出

    // 用户重新输入即重试
    vi.mocked(purchaseApi.saveFactoryEdits).mockResolvedValue({ success: true } as never)
    await m.applyLossRateAndSave(50)

    expect(m.lossRateTouched).toBe(false)
    expect(m.lossRateSaveState).toBe('saved')
  })

  it('B4 串行状态是实例闭包私有：两个实例互不干扰', async () => {
    const state = trackSends()
    vi.mocked(purchaseApi.saveFactoryEdits).mockImplementation(((editsArg: unknown, rate?: number) => {
      state.inFlight++
      state.maxInFlight = Math.max(state.maxInFlight, state.inFlight)
      state.rates.push(rate as number)
      return new Promise<{ success: boolean }>((resolve) => {
        setTimeout(() => {
          state.inFlight--
          resolve({ success: true })
        }, 0)
      })
    }) as never)

    const a = useSummaryModal()
    const b = useSummaryModal()
    await a.openSummary([1])
    await b.openSummary([2])

    // 两个实例各自一个在途请求 → 并发峰值为 2（若串行状态是模块级全局则会被串成 1）
    await Promise.all([a.applyLossRateAndSave(5), b.applyLossRateAndSave(50)])
    await settle(4)

    expect(state.maxInFlight).toBe(2)
    expect(a.lossRate).toBe(5)
    expect(b.lossRate).toBe(50)
  })
})

// ---------------------------------------------------------------------------
// C. 自动保存可见反馈
// ---------------------------------------------------------------------------
function buildActions(summary: ReturnType<typeof useSummaryModal>) {
  return usePurchaseActions({
    purchaseOrders: { completeOrder: vi.fn(), batchComplete: vi.fn(), selectedIds: [1] } as never,
    completed: {} as never,
    summary,
    confirm: { confirm: vi.fn().mockResolvedValue(true) } as never,
    queryClient: { invalidateQueries: vi.fn() } as never,
  })
}

describe('C. 自动保存可见反馈（lossRateSaveState）', () => {
  it('C1 成功路径：调用中 saving，await 后 saved', async () => {
    const gate = deferred<{ success: boolean }>()
    vi.mocked(purchaseApi.saveFactoryEdits).mockReturnValue(gate.promise as never)

    const m = useSummaryModal()
    await m.openSummary([7, 8])

    const p = m.applyLossRateAndSave(5)
    expect(m.lossRateSaveState).toBe('saving')

    gate.resolve({ success: true })
    await p
    expect(m.lossRateSaveState).toBe('saved')
  })

  it('C2 失败路径：状态 error，且 showToast(msg, "error") 恰好一次', async () => {
    vi.mocked(purchaseApi.saveFactoryEdits).mockResolvedValueOnce({
      success: false,
      message: '保存失败',
    } as never)

    const m = useSummaryModal()
    await m.openSummary([7, 8])
    const actions = buildActions(m)

    await actions.handleApplyLossRate(5)

    expect(m.lossRateSaveState).toBe('error')
    const errorCalls = vi.mocked(showToast).mock.calls.filter((c) => c[1] === 'error')
    expect(errorCalls).toHaveLength(1)
    expect(String(errorCalls[0]![0])).toContain('保存失败')
    expect(m.lossRateTouched).toBe(true)
  })

  it('C3 close() 后状态复位为 idle（成功态与失败态两条路径）', async () => {
    const ok = useSummaryModal()
    await ok.openSummary([7, 8])
    await ok.applyLossRateAndSave(5)
    expect(ok.lossRateSaveState).toBe('saved')
    ok.close()
    expect(ok.lossRateSaveState).toBe('idle')

    vi.mocked(purchaseApi.saveFactoryEdits).mockRejectedValueOnce(new Error('网络错误'))
    const bad = useSummaryModal()
    await bad.openSummary([7, 8])
    await expect(bad.applyLossRateAndSave(5)).rejects.toThrow('网络错误')
    expect(bad.lossRateSaveState).toBe('error')
    bad.close()
    expect(bad.lossRateSaveState).toBe('idle')
  })

  it('C4 orderIds 为空：不发请求、状态保持 idle（未打网络）', async () => {
    const m = useSummaryModal()
    await m.applyLossRateAndSave(5)

    expect(purchaseApi.saveFactoryEdits).not.toHaveBeenCalled()
    expect(m.lossRateSaveState).toBe('idle')
    expect(m.lossRateTouched).toBe(true)
  })

  it('C5 openSummary 后状态复位为 idle', async () => {
    const m = useSummaryModal()
    await m.openSummary([7, 8])
    await m.applyLossRateAndSave(5)
    expect(m.lossRateSaveState).toBe('saved')

    await m.openSummary([9])
    expect(m.lossRateSaveState).toBe('idle')
  })

  it('C6 组件按状态渲染内联提示（saving/error/mixed 显示，saved/idle 不渲染）', () => {
    const cases: { state: 'idle' | 'saving' | 'saved' | 'error'; mixed?: boolean; text: string | null }[] = [
      { state: 'saving', text: '保存中…' },
      { state: 'saved', text: null },
      { state: 'error', text: '保存失败' },
      { state: 'idle', mixed: true, text: '各订单损耗率不一致' },
      { state: 'idle', text: null },
    ]
    const known = ['保存中…', '保存失败', '各订单损耗率不一致']

    for (const c of cases) {
      const wrapper = mount(SummaryModal, {
        props: {
          open: true,
          factoryData: factoryOf(10),
          supplierData: null,
          editMode: false,
          lossRate: 5,
          orderCount: 1,
          supplierGroups: [],
          lossRateSaveState: c.state,
          lossRateMixed: c.mixed ?? false,
        },
        global: { stubs: { UiDialog: { template: '<div><slot name="title" /><slot /></div>' } } },
      })
      // 提示位必须始终存在且承载文案；且必须是绝对定位（不参与布局）：
      // 内联在输入框后会推挤行宽（输入抖动），在列内占一行高度会让列比按钮高、
      // items-center 居中导致输入框与按钮上下错位。两种回退都会被下面断言拦下。
      const slot = wrapper.find('.sm-loss-hint')
      expect(slot.exists()).toBe(true)
      expect(slot.classes()).toContain('absolute')
      expect(slot.text()).toBe(c.text ?? '')

      const status = wrapper.findAll('span').find((s) => known.includes(s.text()))
      if (c.text === null) expect(status).toBeUndefined()
      else expect(status?.text()).toBe(c.text)
      wrapper.unmount()
    }
  })
})
