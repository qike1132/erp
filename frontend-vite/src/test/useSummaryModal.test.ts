/**
 * 汇总下单「工厂内部订单」表格单元测试
 *
 * 覆盖：
 * 1. getGroupOrderQty 订单数量取数（product_quantity 优先 / order_quantity 回退 / 非法兜底 0）
 * 2. buildFactoryHtml 打印/导出共用 HTML：10 列表头 + 数据行第 4 列备品、第 8 列损耗率、第 9 列数量
 * 3. SummaryPanel 挂载后的数量口径：数据行「数量」列按损耗率派生取整，且工厂页签
 *    表格内的「合计」行已删除（tbody 只剩数据行）；含字符串 qty 的防御性 parseFloat 场景
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'

// 隔离外部依赖：useSummaryModal.ts 顶层 import purchaseApi from '@/api'，
// 测试不发起真实请求，用最小 stub 替换即可。
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

// 「close() 复位 + handleCompleteOrder 集成」用例需要引入 usePurchaseActions，
// 它依赖 useToast / useExport 两个 composable，这里最小打桩避免触碰真实 DOM/下载。
vi.mock('@/composables/useToast', () => ({
  showToast: vi.fn(),
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
}))

vi.mock('@/composables/useExport', async () => {
  const { ref: r } = await import('vue')
  return { useExport: () => ({ exporting: r(false), runExport: vi.fn() }) }
})

import { getGroupOrderQty, magnifyByLossRate, buildFactoryHtml, FACTORY_TABLE_HEAD, useSummaryModal } from '@/views/purchase/composables/useSummaryModal'
import { usePurchaseActions } from '@/views/purchase/composables/usePurchaseActions'
import SummaryPanel from '@/views/purchase/components/SummaryPanel.vue'
import { fmtQty } from '@/utils/formatQty'
import { purchaseApi } from '@/api'
import type { FactorySummaryData } from '@/views/purchase/composables/useSummaryModal'

// FontAwesomeIcon 已由 src/test/setup.ts 全局 stub。
// 2026-10-31 整页化：SummaryPanel 无 UiDialog 外壳，不再需要 Dialog stub。

/**
 * magnifyByLossRate —— 「损耗加放」的**唯一来源**（纯函数）。
 *
 * 语义 = Math.round((qty + qty × lossRate/1000) × 100) / 100，即
 * `qty × (1 + lossRate/1000)` 后四舍五入到 2 位小数。屏幕数量列、工厂/供应商合计、
 * 打印预览、Excel 导出共用此一处派生；它**绝不写回** factoryData / supplierData。
 *
 * 逐字等价保证：与原「applyLossRate 就地放大」使用的
 * `Math.round((v + v*(r/1000))*100)/100` 完全同式，故 rate=0 时也必须执行两位小数
 * 四舍五入（而非直接返回原值），以维持既有输出零回归。
 */
describe('magnifyByLossRate 纯函数（损耗加放的唯一来源）', () => {
  it('rate=0 → 仍执行「两位小数四舍五入」（与旧就地放大实现逐字等价）', () => {
    // 旧实现：Math.round((v + v*0/1000)*100)/100 === Math.round(v*100)/100
    expect(magnifyByLossRate(10, 0)).toBe(10)
    expect(magnifyByLossRate(3.14159, 0)).toBe(3.14) // round(314.159)/100
    expect(magnifyByLossRate(2.005, 0)).toBe(2.01) // round(200.5)/100 = 201/100
  })

  it('rate=5 → ×1.005（四舍五入到 2 位小数）', () => {
    expect(magnifyByLossRate(10, 5)).toBe(10.05) // 10×1.005=10.05
    expect(magnifyByLossRate(20, 5)).toBe(20.1) // 20×1.005=20.1
    expect(magnifyByLossRate(5, 5)).toBe(5.03) // 5×1.005=5.025 → round(502.5)/100
  })

  it('rate=1000 → ×2', () => {
    expect(magnifyByLossRate(7, 1000)).toBe(14)
  })

  it('非有限 rate（NaN/±Infinity）→ 按 0 兜底（等价于不放大）', () => {
    expect(magnifyByLossRate(10, NaN)).toBe(10)
    expect(magnifyByLossRate(10, Infinity)).toBe(10)
    expect(magnifyByLossRate(10, -Infinity)).toBe(10)
  })

  it('非法 qty（NaN/Infinity/null/字符串数字）→ 兜底 0（Number.isFinite 语义）', () => {
    // Number.isFinite 对非 number 类型一律 false → 计为 0。
    // 三个调用点（SummaryModal.displayFabricQty / buildFactoryHtml / supplierGroups）
    // 均在传入前执行 parseFloat，故真实渲染路径不会命中此兜底。
    expect(magnifyByLossRate(NaN, 5)).toBe(0)
    expect(magnifyByLossRate(Infinity, 5)).toBe(0)
    expect(magnifyByLossRate(null as unknown as number, 5)).toBe(0)
    expect(magnifyByLossRate(undefined as unknown as number, 5)).toBe(0)
    expect(magnifyByLossRate('10' as unknown as number, 5)).toBe(0)
  })
})

describe('SummaryPanel 数量口径（数据行）', () => {
  const factoryData: FactorySummaryData = {
    success: true,
    order_count: 2,
    groups: [
      {
        customer_name: '客户A',
        product_name: '产品1',
        product_quantity: 100,
        suppliers: [
          {
            supplier_name: '供应商1',
            fabrics: [
              { fabric_name: '布料A', specification: 'S1', quantity: 10, unit: '米' },
              { fabric_name: '布料B', specification: 'S2', quantity: 20, unit: '米' },
            ],
          },
        ],
      },
      {
        customer_name: '客户B',
        product_name: '产品2',
        order_quantity: 50,
        suppliers: [
          {
            supplier_name: '供应商2',
            fabrics: [{ fabric_name: '布料C', specification: 'S3', quantity: 5, unit: '米' }],
          },
        ],
      },
    ],
  }

  function mountModal(lossRate: number, data: FactorySummaryData = factoryData, editMode = false) {
    return mount(SummaryPanel, {
      props: {
        factoryData: data,
        supplierData: null,
        editMode,
        lossRate,
        orderCount: 2,
        supplierGroups: [],
      },

    })
  }

  it('工厂表格表头含 10 列：第 4 列为「备品数量」、第 8 列为「损耗率」', () => {
    const wrapper = mountModal(0)
    const headers = wrapper.findAll('thead th').map((th) => th.text())
    expect(headers).toHaveLength(10)
    expect(headers[3]).toBe('备品数量')
    expect(headers[7]).toBe('损耗率')
  })

  it('已删除表格内的「合计」行：tbody 只剩数据行', () => {
    const wrapper = mountModal(5)
    const rows = wrapper.findAll('tbody tr')
    expect(rows).toHaveLength(3) // 布料A / 布料B / 布料C
    // 任何一行都不再是「合计」行（首格文本不再是 合计）
    expect(rows.some((r) => r.findAll('td')[0]!.text() === '合计')).toBe(false)
  })

  it('数据行「数量」列按损耗率派生取整（lossRate=5：10.05→11、20.1→21、5.03→6）', () => {
    const wrapper = mountModal(5)
    const rows = wrapper.findAll('tbody tr')
    expect(rows[0]!.findAll('td')[8]!.text()).toBe('11')
    // 同供应商第二行只有 5 个 td（订单级/供应商单元格均被 rowspan 合并），数量仍在第 4 位
    expect(rows[1]!.findAll('td')[3]!.text()).toBe('21')
    expect(rows[2]!.findAll('td')[8]!.text()).toBe('6')
  })

  it('【真实用户路径】openSummary → applyLossRate(5) → 数据行数量按派生值（与 prop 注入同源，而非仅覆盖 prop）', async () => {
    vi.mocked(purchaseApi.factorySummary).mockResolvedValue(factoryData as never)
    vi.mocked(purchaseApi.supplierSummary).mockResolvedValue({ success: true, materials: [] } as never)
    const m = useSummaryModal()
    await m.openSummary([7, 8])

    const mountWithSummary = () =>
      mount(SummaryPanel, {
        props: {

          factoryData: m.factoryData,
          supplierData: m.supplierData,
          editMode: m.editMode,
          lossRate: m.lossRate,
          orderCount: 2,
          supplierGroups: m.supplierGroups,
        },
      })

    // 数量列逐行读数：第 2 行被 rowspan 合并（仅 5 个 td），数量仍在其第 4 位
    const qtyCells = (w: ReturnType<typeof mountWithSummary>) => {
      const rows = w.findAll('tbody tr')
      return [rows[0]!.findAll('td')[8]!.text(), rows[1]!.findAll('td')[3]!.text(), rows[2]!.findAll('td')[8]!.text()]
    }

    // 未交互损耗率（rate=0）→ 数量为原始值
    const before = mountWithSummary()
    expect(qtyCells(before)).toEqual(['10', '20', '5'])
    before.unmount()

    // 用户输入损耗率（真实动作路径）→ 仅率状态变化，展示派生随之放大
    m.applyLossRate(5)
    const after = mountWithSummary()
    expect(qtyCells(after)).toEqual(['11', '21', '6']) // 与 mountModal(5) 的 prop 注入结果一致
    // 原始数量不被就地改写（落库真值保持 10/20/5）
    expect(m.factoryData!.groups[0]!.suppliers[0]!.fabrics[0]!.quantity).toBe(10)
    after.unmount()
  })

  it('【UX 一致性】非编辑态数量列向上取整为整数，编辑态输入框保留精确加放值', () => {
    // 非编辑态：数量列逐行向上取整
    const view = mountModal(5, factoryData, false)
    const viewRows = view.findAll('tbody tr')
    expect(viewRows[0]!.findAll('td')[8]!.text()).toBe('11')
    // 同供应商第二行只有 5 个 td，数量仍在第 4 位
    expect(viewRows[1]!.findAll('td')[3]!.text()).toBe('21')
    expect(viewRows[2]!.findAll('td')[8]!.text()).toBe('6')

    // 编辑态：数量输入框加载 10.05/20.1/5.03 精确加放值，保存反推不因展示取整而失真
    const edit = mountModal(5, factoryData, true)
    expect(edit.findAll('input[type="number"]').map((i) => (i.element as HTMLInputElement).value)).toEqual(['10.05', '20.1', '5.03'])
  })

  it('数据行数量（lossRate=0 → 不改变数量）', () => {
    const wrapper = mountModal(0)
    const rows = wrapper.findAll('tbody tr')
    // 首行客户×产品行的数量单元格（第 9 列）为原值
    expect(rows[0]!.findAll('td')[8]!.text()).toBe('10')
    expect(rows[1]!.findAll('td')[3]!.text()).toBe('20')
    expect(rows[2]!.findAll('td')[8]!.text()).toBe('5')
  })

  it('字符串 qty 也能正确计算（防御性 parseFloat，回归 QA 发现的行内显示 0 问题）', () => {
    const data: FactorySummaryData = {
      success: true,
      order_count: 1,
      groups: [
        {
          customer_name: '客户A',
          product_name: '产品1',
          product_quantity: '100' as unknown as number,
          suppliers: [
            {
              supplier_name: '供应商1',
              fabrics: [{ fabric_name: '布料A', specification: 'S1', quantity: 10, unit: '米' }],
            },
          ],
        },
      ],
    }
    const wrapper = mountModal(5, data)
    const rows = wrapper.findAll('tbody tr')
    const firstRowCells = rows[0]!.findAll('td')
    // 客户/产品名称/订单数量 → 第 3 列应正确解析字符串 product_quantity '100'
    expect(firstRowCells[2]!.text()).toBe(fmtQty(100))
    // 备品数量（第 4 列）= ceil(100 × 5‰) = 1
    expect(firstRowCells[3]!.text()).toBe('1.0')
    // 数量列按该行损耗率放大取整：10×1.005=10.05 → 11，而非 0
    expect(firstRowCells[8]!.text()).toBe('11')
  })
})

describe('getGroupOrderQty 订单数量取数', () => {
  const baseGroup: FactorySummaryData['groups'][number] = { customer_name: '客户A', product_name: '产品1', suppliers: [] }

  it('product_quantity 优先', () => {
    expect(getGroupOrderQty({ ...baseGroup, product_quantity: 100 })).toBe(100)
  })

  it('缺 product_quantity 时回退 order_quantity', () => {
    expect(getGroupOrderQty({ ...baseGroup, order_quantity: 50 })).toBe(50)
  })

  it('字符串 qty 也能解析（防御性 parseFloat）', () => {
    expect(getGroupOrderQty({ ...baseGroup, product_quantity: '100' as unknown as number })).toBe(100)
  })

  it('非法/缺失 → 0', () => {
    expect(getGroupOrderQty({ ...baseGroup, product_quantity: 'abc' as unknown as number })).toBe(0)
    expect(getGroupOrderQty({ ...baseGroup })).toBe(0)
  })
})

describe('buildFactoryHtml 打印/导出共用 HTML', () => {
  const minimalData: FactorySummaryData = {
    success: true,
    order_count: 1,
    groups: [
      {
        customer_name: '客户X',
        product_name: '产品X',
        product_quantity: 100,
        suppliers: [
          {
            supplier_name: '供应商X',
            fabrics: [{ fabric_name: '布料X', specification: 'SX', quantity: 10, unit: '米' }],
          },
        ],
      },
    ],
  }

  // buildFactoryHtml 只输出 tbody 行，表头由 printFactory/exportFactory 按同一 10 列拼装；测试按相同方式包裹。
  function wrapFactoryHtml(data: FactorySummaryData, lossRate: number): string {
    return `<table><thead>${FACTORY_TABLE_HEAD}</thead><tbody>${buildFactoryHtml(data, lossRate)}</tbody></table>`
  }

  it('表头含 10 个 th：第 4 个为「备品数量」、第 8 个为「损耗率」；数据行第 4 列 = 备品、第 8 列 = 损耗率、第 9 列 = 数量、第 10 列 = 单位', () => {
    const doc = new DOMParser().parseFromString(wrapFactoryHtml(minimalData, 5), 'text/html')
    const headers = [...doc.querySelectorAll('thead th')].map((th) => th.textContent || '')
    expect(headers).toHaveLength(10)
    expect(headers[3]).toBe('备品数量')
    expect(headers[7]).toBe('损耗率')

    const firstRow = doc.querySelector('tbody tr')!
    const cells = [...firstRow.querySelectorAll('td')]
    // 1客户/2产品名称/3订单数量/4备品数量/5供应商/6布料名称/7规格型号/8损耗率/9数量/10单位
    expect(cells[3]!.textContent).toBe('1.0') // 备品 = ceil(100 × 5‰)
    expect(cells[7]!.textContent).toBe('5') // 损耗率
    // 「数量」列 = 损耗加放的展示派生值向上取整：10×1.005=10.05 → '11'。
    expect(cells[8]!.textContent).toBe('11')
    expect(cells[9]!.textContent).toBe('米') // 单位
  })

  it('lossRate=0 时数量列为原值、备品为 0（口径与屏幕表格一致）', () => {
    const doc = new DOMParser().parseFromString(wrapFactoryHtml(minimalData, 0), 'text/html')
    const row = doc.querySelector('tbody tr')!
    const cells = [...row.querySelectorAll('td')]
    expect(cells[3]!.textContent).toBe('0.0')
    expect(cells[8]!.textContent).toBe('10')
  })
})

/**
 * saveFactoryEdits 提交语义（PRD Q1 / AC-7）：
 * - 损耗率**未交互**时不得发送 spare_rate（否则用 0 覆盖已存率）；
 * - 损耗率**已交互**（即使无布料改动、即使值恰为 0）时必须携带 spare_rate，
 *   并把本次涉及的 order_ids 一并提交，供后端定位写入备品的目标采购单。
 */
describe('saveFactoryEdits 提交语义（spare_rate 只在交互后提交）', () => {
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
  const supplierSummaryResponse = { success: true, materials: [] as unknown[] }

  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(purchaseApi.factorySummary).mockResolvedValue(factorySummaryResponse as never)
    vi.mocked(purchaseApi.supplierSummary).mockResolvedValue(supplierSummaryResponse as never)
    vi.mocked(purchaseApi.saveFactoryEdits).mockResolvedValue({ success: true } as never)
  })

  it('损耗率未交互且无布料改动 → 不发起请求（保持原直接退出行为）', async () => {
    const m = useSummaryModal()
    await m.openSummary([7, 8])

    const res = await m.saveFactoryEdits()

    expect(res).toBeUndefined()
    expect(purchaseApi.saveFactoryEdits).not.toHaveBeenCalled()
    expect(m.editMode).toBe(false)
  })

  it('交互损耗率（无手动改布料）→ 必须提交，且携带 spare_rate 与 order_ids', async () => {
    const m = useSummaryModal()
    await m.openSummary([7, 8])
    m.applyLossRate(5)

    await m.saveFactoryEdits()

    expect(purchaseApi.saveFactoryEdits).toHaveBeenCalledTimes(1)
    const [editsArg, rateArg, idsArg] = vi.mocked(purchaseApi.saveFactoryEdits).mock.calls[0]!
    // spare_rate 与 order_ids 必须随请求提交
    expect(rateArg).toBe(5)
    expect(idsArg).toEqual([7, 8])
    // 新契约：applyLossRate 只记录「率」，不改写任何数量；放大值仅是展示派生值。
    // 故「保存修改」的 diff 天然为空 —— 绝不把 10.05 这类展示值当作真实数量落库。
    expect(editsArg).toEqual([])
  })

  it('仅交互损耗率且值为 0（无任何布料改动）→ 仍须提交 spare_rate=0 与 order_ids', async () => {
    const m = useSummaryModal()
    await m.openSummary([7, 8])
    m.applyLossRate(0)

    await m.saveFactoryEdits()

    // rate=0 不改变布料数量（无编辑明细），但「已交互」必须提交，否则无法只改损耗率保存
    expect(purchaseApi.saveFactoryEdits).toHaveBeenCalledTimes(1)
    expect(purchaseApi.saveFactoryEdits).toHaveBeenCalledWith([], 0, [7, 8])
  })

  it('有布料改动但损耗率未交互 → 提交 edits，且不携带 spare_rate（第二参为 undefined）', async () => {
    const m = useSummaryModal()
    await m.openSummary([7, 8])
    m.updateFactoryQty(0, 0, 0, 12)

    await m.saveFactoryEdits()

    expect(purchaseApi.saveFactoryEdits).toHaveBeenCalledTimes(1)
    expect(purchaseApi.saveFactoryEdits).toHaveBeenCalledWith(
      [{ item_ids: [101], quantity: 12 }],
      undefined,
      [7, 8],
    )
  })
})

/**
 * applyLossRateAndSave 损耗率自动落库（BUG-1 修复）：
 * 非编辑态输入损耗率（组件层 300ms 防抖后）必须自动把 spare_rate 落库到本次汇总
 * 涉及的全部采购单，形成「输入框 → 数据库」的持久化路径。断言点：
 *  1. 以空 edits 调用 purchaseApi.saveFactoryEdits，参数为 ([], <rate>, <orderIds>)；
 *  2. orderIds 为空时不发请求（且此时 lossRateTouched 仍为 true，说明已交互未落库）；
 *  3. 落库成功后 lossRateTouched 复位为 false（避免后续完成下单重复提交）；
 *  4. 失败（reject 或 success:false）时抛出供上层 toast，不静默吞掉，本地展示保持可用。
 */
describe('applyLossRateAndSave 损耗率自动落库', () => {
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

  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(purchaseApi.factorySummary).mockResolvedValue(factorySummaryResponse as never)
    vi.mocked(purchaseApi.supplierSummary).mockResolvedValue({ success: true, materials: [] } as never)
    vi.mocked(purchaseApi.saveFactoryEdits).mockResolvedValue({ success: true } as never)
  })

  it('交互损耗率 → 自动以空 edits 提交 ([], rate, orderIds)，并同步更新本地展示', async () => {
    const m = useSummaryModal()
    await m.openSummary([7, 8])

    await m.applyLossRateAndSave(5)

    // edits 恒为空：绝不把放大的展示数量当作 edits 提交
    expect(purchaseApi.saveFactoryEdits).toHaveBeenCalledTimes(1)
    expect(purchaseApi.saveFactoryEdits).toHaveBeenCalledWith([], 5, [7, 8])
    // 新契约：applyLossRate 不再就地改写数据 —— 原始数量保持 10（落库唯一真值）
    expect(m.factoryData!.groups[0]!.suppliers[0]!.fabrics[0]!.quantity).toBe(10)
    // 展示派生值仍按率放大（保留原意图）：10×1.005=10.05，只是不再写回 state
    expect(magnifyByLossRate(m.factoryData!.groups[0]!.suppliers[0]!.fabrics[0]!.quantity, m.lossRate)).toBeCloseTo(10.05, 5)
  })

  it('orderIds 为空 → 不发请求（lossRateTouched 仍为 true，表示已交互未落库）', async () => {
    const m = useSummaryModal()
    // 未 openSummary：orderIds 仍为空数组
    await m.applyLossRateAndSave(5)

    expect(purchaseApi.saveFactoryEdits).not.toHaveBeenCalled()
    expect(m.lossRateTouched).toBe(true)
  })

  it('落库成功 → lossRateTouched 复位为 false（后续完成下单无需重复提交）', async () => {
    const m = useSummaryModal()
    await m.openSummary([7, 8])

    await m.applyLossRateAndSave(5)

    expect(m.lossRateTouched).toBe(false)
  })

  it('请求 reject → 抛出供上层 toast，lossRateTouched 保留 true，本地展示保持可用', async () => {
    vi.mocked(purchaseApi.saveFactoryEdits).mockRejectedValueOnce(new Error('网络错误'))
    const m = useSummaryModal()
    await m.openSummary([7, 8])

    await expect(m.applyLossRateAndSave(5)).rejects.toThrow('网络错误')

    expect(m.lossRateTouched).toBe(true)
    expect(m.lossRate).toBe(5)
    // 新契约：失败态下原始数量同样不被就地改写（本地展示仍可用，派生值由渲染层计算）
    expect(m.factoryData!.groups[0]!.suppliers[0]!.fabrics[0]!.quantity).toBe(10)
  })

  it('后端返回 success:false → 同样抛出，不静默吞掉', async () => {
    vi.mocked(purchaseApi.saveFactoryEdits).mockResolvedValueOnce({ success: false, message: '保存失败' } as never)
    const m = useSummaryModal()
    await m.openSummary([7, 8])

    await expect(m.applyLossRateAndSave(5)).rejects.toThrow('保存失败')
    expect(m.lossRateTouched).toBe(true)
  })
})

/**
 * close() 复位损耗率（消除陈旧率跨单泄漏）：
 * 非编辑态输入损耗率后若落库失败，lossRate/lossRateTouched 会保留（语义正确）；
 * 但用户在关闭弹窗后可能直接对「另一张无关订单」点下单完成，此时
 * usePurchaseActions.handleCompleteOrder 会读 `lossRateTouched ? lossRate : undefined`
 * 把陈旧率推给该单。故 close() 必须丢弃「尚未落库的损耗率交互」。
 *
 * 断言点：
 *  a) close() 后 lossRate=0、lossRateTouched=false（成功落库后关闭 / 失败后关闭 两条路径）；
 *  b) 集成口径：失败 → close() → handleCompleteOrder(999) 实参为 (999, undefined) 不夹带 spare_rate；
 *     并给反向对照（close() 之前确实夹带 spare_rate=5），证明接线有效、断言非恒真。
 */
describe('close() 复位损耗率（消除陈旧率跨单泄漏）', () => {
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

  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(purchaseApi.factorySummary).mockResolvedValue(factorySummaryResponse as never)
    vi.mocked(purchaseApi.supplierSummary).mockResolvedValue({ success: true, materials: [] } as never)
    vi.mocked(purchaseApi.saveFactoryEdits).mockResolvedValue({ success: true } as never)
  })

  /** 引入真实 useSummaryModal + 打桩 purchaseOrders，走 handleCompleteOrder 真实接线 */
  function buildActions(summary: ReturnType<typeof useSummaryModal>) {
    const purchaseOrders = {
      completeOrder: vi.fn().mockResolvedValue(true),
      batchComplete: vi.fn().mockResolvedValue(2),
      selectedIds: [1, 2],
    }
    const actions = usePurchaseActions({
      purchaseOrders: purchaseOrders as never,
      completed: {} as never,
      summary,
      confirm: { confirm: vi.fn().mockResolvedValue(true) } as never,
      queryClient: { invalidateQueries: vi.fn() } as never,
    })
    return { actions, purchaseOrders }
  }

  it('成功落库后 close() → lossRate=0 且 lossRateTouched=false', async () => {
    const m = useSummaryModal()
    await m.openSummary([7, 8])
    await m.applyLossRateAndSave(5)
    expect(m.lossRateTouched).toBe(false)

    m.close()

    expect(m.lossRate).toBe(0)
    expect(m.lossRateTouched).toBe(false)
  })

  it('落库失败后 close() → lossRate=0 且 lossRateTouched=false（失败态在关闭时被丢弃）', async () => {
    vi.mocked(purchaseApi.saveFactoryEdits).mockRejectedValueOnce(new Error('网络错误'))
    const m = useSummaryModal()
    await m.openSummary([7, 8])
    await expect(m.applyLossRateAndSave(5)).rejects.toThrow('网络错误')
    // 失败当时仍保留（语义正确：尚未落库）
    expect(m.lossRateTouched).toBe(true)
    expect(m.lossRate).toBe(5)

    m.close()

    expect(m.lossRate).toBe(0)
    expect(m.lossRateTouched).toBe(false)
  })

  it('【集成】失败 → close() → 完成另一张订单不夹带 spare_rate；对照：close() 前会夹带', async () => {
    vi.mocked(purchaseApi.saveFactoryEdits).mockRejectedValueOnce(new Error('网络错误'))
    const m = useSummaryModal()
    await m.openSummary([7, 8])
    await expect(m.applyLossRateAndSave(5)).rejects.toThrow('网络错误')

    // 反向对照：close() 之前 lossRateTouched=true → handleCompleteOrder 确实夹带 spare_rate=5
    const pre = buildActions(m)
    await pre.actions.handleCompleteOrder(999)
    expect(pre.purchaseOrders.completeOrder).toHaveBeenCalledWith(999, 5)

    // 关闭弹窗 → 未落库的损耗率交互被丢弃
    m.close()
    const post = buildActions(m)
    await post.actions.handleCompleteOrder(999)
    // 实参第二项必须为 undefined（api 层据此不进 body）→ 不再泄漏陈旧率
    expect(post.purchaseOrders.completeOrder).toHaveBeenCalledWith(999, undefined)
  })
})
