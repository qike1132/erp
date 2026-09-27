/**
 * QA(Edward) 独立对抗测试 —— 【上线前最高优先级】字符串数字导致的「整列归零」风险。
 *
 * 背景：后端 Decimal 序列化后 `quantity` / `total_quantity` / `product_quantity` 可能是**字符串**
 * （如 '10'）。`magnifyByLossRate` 用 `Number.isFinite(qty)` 做防御，而 `Number.isFinite('10')`
 * 恒为 **false** → 若任一调用点漏掉 parseFloat，整列会被算成 0（用户看到「数量列全 0」）。
 *
 * 本文件不复述工程师结论，直接以「字符串入参 + 真实渲染路径」硬验每个调用点，
 * 并显式量化漏 parseFloat 时的失败态（证明该护栏非恒真）。
 *
 * 覆盖调用点：
 *  - useSummaryModal.ts  buildFactoryHtml  : magnifyByLossRate(parseFloat(String(fabric.quantity))||0, ...)
 *  - useSummaryModal.ts  supplierGroups    : 与工厂「数量」列同源派生（无对应行时回退 magnifyByLossRate(parseFloat(String(m.total_quantity))||0, ...)）
 *  - SummaryFactoryTab.vue  displayFabricQty  : factoryQtyDisplayValue(parseFloat(String(fabric.quantity))||0, ...)
 *  - SummarySupplierTab.vue 数量列        : qtyDisplayText(parseFloat(String(m.total_quantity))||0)
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

import { magnifyByLossRate, buildFactoryHtml, useSummaryModal } from '@/views/purchase/composables/useSummaryModal'
import SummaryModal from '@/views/purchase/components/SummaryModal.vue'
import { fmtQty } from '@/utils/formatQty'
import { purchaseApi } from '@/api'
import type { FactorySummaryData, SupplierSummaryData } from '@/views/purchase/composables/useSummaryModal'

const stubs = {
  UiDialog: { template: '<div class="ui-dialog-stub"><slot name="title" /><slot /></div>' },
}

/** 后端 Decimal → 字符串 的模拟响应（quantity / total_quantity / product_quantity 全为字符串） */
const STRING_FACTORY: FactorySummaryData = {
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
          fabrics: [
            { fabric_name: '布料A', specification: 'S1', quantity: '10' as unknown as number, unit: '米', item_ids: [101] },
            { fabric_name: '布料B', specification: 'S2', quantity: '20' as unknown as number, unit: '米', item_ids: [102] },
          ],
        },
      ],
    },
  ],
}

const STRING_SUPPLIER: SupplierSummaryData = {
  success: true,
  materials: [
    { material_name: '布料A', specification: 'S1', total_quantity: '20' as unknown as number, unit: '米', supplier_name: '供应商1' },
    // 工厂侧无对应行的物料：走「原始值 × 损耗率」回退路径，用于覆盖字符串真值的解析
    { material_name: '布料C', specification: 'S3', total_quantity: '20' as unknown as number, unit: '米', supplier_name: '供应商1' },
  ],
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(purchaseApi.factorySummary).mockResolvedValue(STRING_FACTORY as never)
  vi.mocked(purchaseApi.supplierSummary).mockResolvedValue(STRING_SUPPLIER as never)
  vi.mocked(purchaseApi.saveFactoryEdits).mockResolvedValue({ success: true } as never)
})

describe('【上线阻断项】字符串 quantity 不得导致「数量列/合计 归零」', () => {
  it('前提量化：magnifyByLossRate 本身对字符串会归零（证明「调用点必须 parseFloat」非空谈）', () => {
    // Number.isFinite('10') === false → 直接传字符串 → 0（这就是整列归零的根因）
    expect(magnifyByLossRate('10' as unknown as number, 5)).toBe(0)
    // 正确做法（调用点已 parseFloat）：
    expect(magnifyByLossRate(parseFloat('10'), 5)).toBe(10.05)
  })

  it('buildFactoryHtml：字符串 quantity → 「数量」列 = 派生值（非 0.0）', () => {
    const html = buildFactoryHtml(STRING_FACTORY, 5)
    const doc = new DOMParser().parseFromString(`<table>${html}</table>`, 'text/html')
    const rows = [...doc.querySelectorAll('tbody tr')]
    // 每行末两格恒为 [数量, 单位]（rowspan 压缩使前几行 td 数变少，不能用固定下标 7）
    const qtyOf = (i: number) => {
      const tds = [...rows[i]!.querySelectorAll('td')]
      return tds[tds.length - 2]!.textContent
    }
    expect(qtyOf(0)).toBe('11') // ceil(10.05)
    expect(qtyOf(1)).toBe('21') // ceil(20.1)
    expect(qtyOf(0)).not.toBe(fmtQty(0))
    expect(qtyOf(1)).not.toBe(fmtQty(0))
  })

  it('supplierGroups（真实 openSummary 路径）：与工厂数量同源；字符串真值解析不归零', async () => {
    const m = useSummaryModal()
    await m.openSummary([7, 8])
    m.applyLossRate(5)

    expect(m.supplierGroups).toHaveLength(1)
    // 布料A 与工厂布料行同键 → 取工厂「数量」列派生值（'10' × 1.005 → 11）
    expect(m.supplierGroups[0]!.materials[0]!.total_quantity).toBe(11)
    expect(m.supplierGroups[0]!.materials[0]!.total_quantity).not.toBe(0)
    // 布料C 工厂侧无对应行 → 回退：字符串真值 '20' × 1.005 = 20.1（同样不得归零）
    expect(m.supplierGroups[0]!.materials[1]!.total_quantity).toBe(20.1)
    expect(m.supplierGroups[0]!.materials[1]!.total_quantity).not.toBe(0)
    // 原始数据（字符串）不被写回
    expect(m.supplierData!.materials[0]!.total_quantity).toBe('20')
    expect(m.supplierData!.materials[1]!.total_quantity).toBe('20')
  })

  it('组件渲染（真实路径，非编辑态）：工厂「数量」列按派生值，绝不为 0', async () => {
    const m = useSummaryModal()
    await m.openSummary([7, 8])
    m.applyLossRate(5)

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
      global: { stubs },
    })

    const dataRows = wrapper.findAll('tbody tr').slice(0, 2)
    // 每行末两格恒为 [数量, 单位]（rowspan 压缩使第 2 行 td 数变少，不能用固定下标 7）
    const qtyOf = (row: (typeof dataRows)[number]) => {
      const tds = row.findAll('td')
      return tds[tds.length - 2]!.text()
    }
    const qty0 = qtyOf(dataRows[0]!)
    const qty1 = qtyOf(dataRows[1]!)
    expect(qty0).toBe('11')
    expect(qty1).toBe('21')
    expect(qty0).not.toBe(fmtQty(0))
    expect(qty1).not.toBe(fmtQty(0))

    // 表格内已无「合计」行：tbody 只剩数据行（布料A / 布料B）
    expect(wrapper.findAll('tbody tr')).toHaveLength(2)

    wrapper.unmount()
  })

  it('组件渲染（真实路径）：供应商页「数量」列 = 派生值，绝不为 0', async () => {
    const m = useSummaryModal()
    await m.openSummary([7, 8])
    m.applyLossRate(5)

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
      global: { stubs },
    })
    // 切到供应商 Tab
    await wrapper.findAll('.sm-tab-btn')[1]!.trigger('click')

    const rows = wrapper.findAll('tbody tr')
    const qtyOf = (row: (typeof rows)[number]) => {
      const tds = row.findAll('td')
      return tds[tds.length - 2]!.text()
    }
    expect(rows).toHaveLength(2) // 布料A + 布料C（表格内已无「合计」行）
    // 与工厂数量同源的 11（布料A）+ 回退派生的 20.1（布料C）
    expect(qtyOf(rows[0]!)).toBe('11')
    expect(qtyOf(rows[1]!)).toBe('20.1')
    expect(qtyOf(rows[0]!)).not.toBe(fmtQty(0))
    wrapper.unmount()
  })

  it('编辑态：输入框绑定当前工序损耗率加放后的订单用量，绝不为 0', async () => {
    const m = useSummaryModal()
    await m.openSummary([7, 8])
    m.applyLossRate(5)

    const wrapper = mount(SummaryModal, {
      props: {
        open: true,
        factoryData: m.factoryData,
        supplierData: m.supplierData,
        editMode: true,
        lossRate: m.lossRate,
        orderCount: 1,
        supplierGroups: m.supplierGroups,
      },
      global: { stubs },
    })
    const inputs = wrapper.findAll('input[type="number"]')
    expect((inputs[0]!.element as HTMLInputElement).value).toBe('10.05')
    expect((inputs[1]!.element as HTMLInputElement).value).toBe('20.1')

    // 表格内已无「合计」行：编辑态同样只剩数据行
    expect(wrapper.findAll('tbody tr')).toHaveLength(2)
    wrapper.unmount()
  })
})
