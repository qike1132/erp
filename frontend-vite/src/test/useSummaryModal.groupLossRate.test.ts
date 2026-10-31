/**
 * 逐布料行（表格中每一行布料）差异化损耗率回归测试。
 *
 * 覆盖：
 * - openSummary 按 fabric.loss_rate（回退分组 spare_rate）播种逐布料行损耗率；
 * - applyFabricLossRateAndSave 仅把该行损耗率保存到该行对应的明细 item_ids；
 * - 自定义编辑加载的是按该行损耗率加放后的「订单用量」，保存时反推原始真值；
 * - 取消编辑恢复该行已落库的损耗率基线；
 * - buildFactoryHtml 按逐布料行损耗率分别计算放大数量。
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

import { purchaseApi } from '@/api'
import {
  buildFactoryHtml,
  useSummaryModal,
  unmagnifyByLossRate,
} from '@/views/purchase/composables/useSummaryModal'
import type { FactorySummaryData } from '@/views/purchase/composables/useSummaryModal'
import SummaryPanel from '@/views/purchase/components/SummaryPanel.vue'

function factorySummary(): FactorySummaryData {
  return {
    success: true,
    order_count: 2,
    spare_rate: null,
    spare_rate_mixed: true,
    groups: [
      {
        customer_name: '客户A',
        product_name: '漂白边伦',
        product_quantity: 100,
        order_quantity: 100,
        order_ids: [7],
        spare_rate: 100,
        spare_rate_mixed: false,
        suppliers: [
          {
            supplier_name: '供应商甲',
            fabrics: [{
              fabric_name: '布料A',
              specification: 'S1',
              quantity: 100,
              unit: '米',
              item_ids: [101],
              loss_rate: 100,
              loss_rate_mixed: false,
            }],
          },
        ],
      },
      {
        customer_name: '客户B',
        product_name: '产品2',
        product_quantity: 50,
        order_quantity: 50,
        order_ids: [8],
        spare_rate: 50,
        spare_rate_mixed: false,
        suppliers: [
          {
            supplier_name: '供应商乙',
            fabrics: [{
              fabric_name: '布料B',
              specification: 'S2',
              quantity: 50,
              unit: '米',
              item_ids: [102],
              loss_rate: 50,
              loss_rate_mixed: false,
            }],
          },
        ],
      },
    ],
  }
}

describe('逐布料行差异化损耗率', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(purchaseApi.factorySummary).mockResolvedValue(factorySummary() as never)
    vi.mocked(purchaseApi.supplierSummary).mockResolvedValue({ success: true, materials: [] } as never)
    vi.mocked(purchaseApi.saveFactoryEdits).mockResolvedValue({ success: true } as never)
  })

  it('openSummary 按 fabric.loss_rate 播种逐布料行损耗率', async () => {
    const m = useSummaryModal()
    await m.openSummary([7, 8])

    expect(m.fabricLossRates).toEqual([[[100]], [[50]]])
    expect(m.fabricLossRateMixed).toEqual([[[false]], [[false]]])
    expect(m.lossRateMixed).toBe(true)
  })

  it('applyFabricLossRateAndSave 仅把该行损耗率保存到该行明细', async () => {
    const m = useSummaryModal()
    await m.openSummary([7, 8])

    await m.applyFabricLossRateAndSave(0, 0, 0, 120)

    expect(purchaseApi.saveFactoryEdits).toHaveBeenCalledTimes(1)
    expect(purchaseApi.saveFactoryEdits).toHaveBeenCalledWith([{ item_ids: [101], loss_rate: 120 }])
    expect(m.fabricLossRates).toEqual([[[120]], [[50]]])
    expect(m.fabricLossRateMixed[0]![0]![0]).toBe(false)
  })

  it('自定义编辑按该行损耗率加载展示值，保存时反推原始真值（100‰：110 → 100）', async () => {
    expect(unmagnifyByLossRate(110, 100)).toBe(100)

    const m = useSummaryModal()
    await m.openSummary([7, 8])

    m.updateFactoryQty(0, 0, 0, 110)
    m.updateFactoryQty(1, 0, 0, 52.5)

    expect(m.factoryData!.groups[0]!.suppliers[0]!.fabrics[0]!.quantity).toBe(100)
    expect(m.factoryData!.groups[1]!.suppliers[0]!.fabrics[0]!.quantity).toBe(50)
  })

  it('取消编辑恢复各布料行已落库的损耗率基线', async () => {
    const m = useSummaryModal()
    await m.openSummary([7, 8])
    await m.applyFabricLossRateAndSave(0, 0, 0, 120)

    m.toggleEditMode(true)
    m.toggleEditMode(false)

    expect(m.fabricLossRates).toEqual([[[120]], [[50]]])
  })

  it('取消编辑同时恢复顶部统一损耗率与 mixed 基线（AUD-13）', async () => {
    const m = useSummaryModal()
    await m.openSummary([7, 8]) // spare_rate=null → 持久基线 0

    m.toggleEditMode(true)
    m.lossRate = 80
    m.fabricLossRateMixed[0]![0]![0] = true

    m.toggleEditMode(false)

    expect(m.lossRate).toBe(0)
    expect(m.fabricLossRateMixed[0]![0]![0]).toBe(false)
  })

  it('打印/导出 HTML 按逐布料行损耗率分别计算数量', () => {
    const html = buildFactoryHtml(factorySummary(), 0, [[[100]], [[50]]])

    // 行0：数量 100×1.1=110 → 110，损耗率 100
    expect(html).toContain('>110<')
    expect(html).toContain('>100<')
    // 行1：数量 50×1.05=52.5 → 53，损耗率 50
    expect(html).toContain('>53<')
    expect(html).toContain('>50<')
  })

  it('组件逐布料行输入经防抖后向上层发出 applyFabricLossRate(gi,si,fi,rate)', async () => {
    const wrapper = mount(SummaryPanel, {
      props: {
        factoryData: factorySummary(),
        supplierData: null,
        editMode: false,
        lossRate: 0,
        fabricLossRates: [[[100]], [[50]]],
        fabricLossRateMixed: [[[false]], [[false]]],
        orderCount: 2,
        supplierGroups: [],
      },
    })

    // 第 1 个 input 是统一损耗率；第 2 个是布料行 0 的独立输入。
    const inputs = wrapper.findAll('input[type="number"]')
    await inputs[1]!.setValue('120')
    await new Promise((resolve) => setTimeout(resolve, 450))

    const emitted = wrapper.emitted('applyFabricLossRate')
    expect(emitted).toBeTruthy()
    expect(emitted![0]).toEqual([0, 0, 0, 120])

    wrapper.unmount()
  })

  it('自定义编辑输入框按该布料行损耗率加载最新订单用量（100‰ → 110）', async () => {
    const wrapper = mount(SummaryPanel, {
      props: {
        factoryData: factorySummary(),
        supplierData: null,
        editMode: true,
        lossRate: 100,
        fabricLossRates: [[[100]], [[50]]],
        fabricLossRateMixed: [[[false]], [[false]]],
        orderCount: 2,
        supplierGroups: [],
      },
    })

    const inputs = wrapper.findAll('input[type="number"]')
    expect((inputs[0]!.element as HTMLInputElement).value).toBe('110')
    expect((inputs[1]!.element as HTMLInputElement).value).toBe('52.5')

    wrapper.unmount()
  })
})
