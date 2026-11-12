/**
 * 「数量」单元格就地编辑（2026-11-12）交互回归。
 *
 * 覆盖用户验收 a/b/c/d/e/f/g：
 *  a) 点击进入编辑，Enter 保存后退出且保留自定义值；
 *  b) Esc 取消并还原；
 *  c) 保存后供应商页签 = 自定义值；
 *  d) 重开汇总后两页仍显示自定义值；
 *  e) 多 SKU 共用物料：各 SKU 行相加 = 自定义总量；
 *  f) readonlyReason（BOM 重复配置）行点击不进入编辑；
 *  g) 409 时还原并提示「BOM 已更新」。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { defineComponent, h, onMounted } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'

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

import SummaryPanel from '@/views/purchase/components/SummaryPanel.vue'
import { useSummaryModal } from '@/views/purchase/composables/useSummaryModal'
import { purchaseApi } from '@/api'
import { toast } from '@/composables/useToast'
import type { FactorySummaryData, SupplierSummaryData } from '@/views/purchase/composables/useSummaryModal'

const RATE = 100 // 10%，便于区分「落库值 → 展示值」

/** 两个 SKU 共用「共享布」；「A专有布」仅 SKU-A 使用。落库与 BOM 一致（非手工）。 */
function factoryData(): FactorySummaryData {
  return {
    success: true,
    order_count: 1,
    spare_rate: 0,
    groups: [{
      customer_name: '客户甲',
      product_name: '产品',
      product_quantity: 100,
      suppliers: [{
        supplier_name: '供应商甲',
        fabrics: [
          {
            fabric_name: '共享布', specification: 'S1', unit: '米',
            quantity: 60, item_ids: [1], loss_rate: RATE,
          },
          {
            fabric_name: 'A专有布', specification: 'S2', unit: '米',
            quantity: 20, item_ids: [2], loss_rate: RATE,
          },
        ],
      }],
      skus: [
        {
          product_name: 'SKU-A', order_qty: 100,
          materials: [
            { supplier_name: '供应商甲', material_name: '共享布', specification: 'S1', unit: '米', quantity: 20, part_name: '' },
            { supplier_name: '供应商甲', material_name: 'A专有布', specification: 'S2', unit: '米', quantity: 20, part_name: '' },
          ],
        },
        {
          product_name: 'SKU-B', order_qty: 100,
          materials: [
            { supplier_name: '供应商甲', material_name: '共享布', specification: 'S1', unit: '米', quantity: 40, part_name: '' },
          ],
        },
      ],
    }],
  }
}

/** 同一 SKU 内 BOM 重复配置同一物料 → 合并到同一采购明细行 → readonlyReason。 */
function readonlyFactory(): FactorySummaryData {
  const data = factoryData()
  const sku = data.groups[0]!.skus![0]!
  sku.materials = [
    { supplier_name: '供应商甲', material_name: '共享布', specification: 'S1', unit: '米', quantity: 20, part_name: '' },
    { supplier_name: '供应商甲', material_name: '共享布', specification: 'S1', unit: '米', quantity: 20, part_name: '' },
  ]
  data.groups[0]!.skus = [sku]
  return data
}

/** ceil 预载会产生反推漂移的夹具：落库 50、率 30‰ → 预载 52，52/1.03 = 50.49。 */
function roundingFactory(): FactorySummaryData {
  return {
    success: true,
    order_count: 1,
    spare_rate: 0,
    groups: [{
      customer_name: '客户甲',
      product_name: '产品',
      product_quantity: 100,
      suppliers: [{
        supplier_name: '供应商甲',
        fabrics: [{
          fabric_name: '宝乐绒', specification: 'S1', unit: '米',
          quantity: 50, item_ids: [9], loss_rate: 30,
        }],
      }],
      skus: [{
        product_name: 'SKU-A', order_qty: 100,
        materials: [{
          supplier_name: '供应商甲', material_name: '宝乐绒', specification: 'S1',
          unit: '米', quantity: 50, part_name: '',
        }],
      }],
    }],
  }
}

function supplierData(): SupplierSummaryData {
  return {
    success: true,
    materials: [
      { material_name: '共享布', specification: 'S1', unit: '米', total_quantity: 60, supplier_name: '供应商甲' },
      { material_name: 'A专有布', specification: 'S2', unit: '米', total_quantity: 20, supplier_name: '供应商甲' },
    ],
  }
}

let m!: ReturnType<typeof useSummaryModal>

const Harness = defineComponent({
  setup() {
    m = useSummaryModal()
    onMounted(async () => { await m.openSummary([1]) })
    return () => h(SummaryPanel, {
      factoryData: m.factoryData,
      supplierData: m.supplierData,
      lossRate: m.lossRate,
      lossRateSaveState: m.lossRateSaveState,
      lossRateMixed: m.lossRateMixed,
      fabricLossRates: m.fabricLossRates,
      fabricLossRateMixed: m.fabricLossRateMixed,
      groupSpareRates: m.groupSpareRates,
      qtyDrafts: m.qtyDrafts,
      qtySavingKey: m.qtySavingKey,
      hasUnsavedQtyEdits: m.hasUnsavedQtyEdits,
      orderCount: 1,
      supplierGroups: m.supplierGroups,
      onBeginQtyEdit: m.beginQtyEdit,
      onQtyDraftInput: m.setQtyDraft,
      onCancelQtyEdit: m.cancelQtyEdit,
      onSaveQtyRow: (gi: number, si: number, fi: number) => { void m.saveQtyRow(gi, si, fi).catch(() => {}) },
      onApplyLossRate: () => {},
      onApplyFabricLossRate: () => {},
      onExportFactory: () => {},
      onExportSupplier: () => {},
      onPrintFactory: () => {},
      onPrintSupplier: () => {},
      onClose: () => {},
    })
  },
})

async function setup(factory: FactorySummaryData = factoryData()) {
  vi.mocked(purchaseApi.factorySummary).mockResolvedValue(factory as never)
  vi.mocked(purchaseApi.supplierSummary).mockResolvedValue(supplierData() as never)
  vi.mocked(purchaseApi.saveFactoryEdits).mockResolvedValue({ success: true } as never)
  const wrapper = mount(Harness)
  await flushPromises()
  return wrapper
}

function dataRows(wrapper: Awaited<ReturnType<typeof setup>>) {
  // 排除差异对照块（.sm-diff-*）：它复用 tbody，但不属于主数据行
  return wrapper.findAll('.smf-scroll tbody tr:not(.sm-diff-banner):not(.sm-diff-row)')
}

function rowOf(wrapper: Awaited<ReturnType<typeof setup>>, material: string, index = 0) {
  return dataRows(wrapper).filter((tr) => tr.text().includes(material))[index]!
}

function qtyCellOf(wrapper: Awaited<ReturnType<typeof setup>>, material: string, index = 0) {
  return rowOf(wrapper, material, index).find('.sm-qty-cell')
}

async function beginEdit(wrapper: Awaited<ReturnType<typeof setup>>, material: string, index = 0) {
  await qtyCellOf(wrapper, material, index).trigger('click')
  const input = wrapper.find('.sm-qty-input')
  expect(input.exists()).toBe(true)
  return input
}

async function setAndSave(input: Awaited<ReturnType<typeof beginEdit>>, value: string) {
  await input.setValue(value)
  await input.trigger('keydown', { key: 'Enter' })
  await flushPromises()
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('数量单元格就地编辑（验收 a/b/f/g）', () => {
  it('a) 点击进入编辑，Enter 保存后该行退出编辑且保留自定义值', async () => {
    const wrapper = await setup()
    expect(qtyCellOf(wrapper, 'A专有布').text()).toBe('22')

    const input = await beginEdit(wrapper, 'A专有布')
    expect((input.element as HTMLInputElement).value).toBe('22')
    await setAndSave(input, '100')

    expect(wrapper.find('.sm-qty-input').exists()).toBe(false)
    expect(qtyCellOf(wrapper, 'A专有布').text()).toBe('100')
    // 100 / 1.1 = 90.91（按该行损耗率反推落库真值）
    expect(purchaseApi.saveFactoryEdits).toHaveBeenCalledWith(
      [{ item_ids: [2], quantity: 90.91 }], undefined, [1],
    )
    wrapper.unmount()
  })

  it('点开不改值直接 Enter：退出编辑且不发起保存（ceil 预载值不得反推成伪变更）', async () => {
    const wrapper = await setup(roundingFactory())
    const fabric = m.factoryData!.groups[0]!.suppliers[0]!.fabrics[0]!
    expect(qtyCellOf(wrapper, '宝乐绒').text()).toBe('52')

    const versions = { ...m.itemsVersions }
    const input = await beginEdit(wrapper, '宝乐绒')
    // 预载 ceil(50 × 1.03) = 52；若直接反推会得到 50.49（静默改写落库真值）
    expect((input.element as HTMLInputElement).value).toBe('52')
    await input.trigger('keydown', { key: 'Enter' })
    await flushPromises()

    expect(purchaseApi.saveFactoryEdits).not.toHaveBeenCalled()
    expect(wrapper.find('.sm-qty-input').exists()).toBe(false)
    expect(fabric.quantity).toBe(50)
    expect(m.itemsVersions).toEqual(versions)
    wrapper.unmount()
  })

  it('b) Esc 取消后恢复原值，且不发起保存', async () => {
    const wrapper = await setup()
    const input = await beginEdit(wrapper, 'A专有布')
    await input.setValue('50')
    await input.trigger('keydown', { key: 'Escape' })
    await flushPromises()

    expect(wrapper.find('.sm-qty-input').exists()).toBe(false)
    expect(qtyCellOf(wrapper, 'A专有布').text()).toBe('22')
    expect(purchaseApi.saveFactoryEdits).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('f) readonlyReason（同一 SKU 内 BOM 重复配置）行不可进入编辑，保留原因提示', async () => {
    const wrapper = await setup(readonlyFactory())
    const rows = dataRows(wrapper).filter((tr) => tr.text().includes('共享布'))
    expect(rows.length).toBeGreaterThan(0)
    for (const tr of rows) {
      expect(tr.find('.sm-qty-cell').exists()).toBe(false)
      expect(tr.html()).toContain('BOM 重复配置')
    }
    // 点击数量格不产生草稿
    await rows[0]!.findAll('td').at(-2)!.trigger('click')
    expect(m.qtyDrafts).toEqual({})
    wrapper.unmount()
  })

  it('g) 409 冲突：还原到保存前的值并提示「BOM 已更新」', async () => {
    const wrapper = await setup()
    vi.mocked(purchaseApi.saveFactoryEdits).mockRejectedValueOnce({ response: { status: 409 } })
    vi.mocked(purchaseApi.factorySummary)
      .mockResolvedValueOnce(factoryData() as never)
      .mockResolvedValueOnce(factoryData() as never)

    const input = await beginEdit(wrapper, 'A专有布')
    await setAndSave(input, '100')

    expect(toast.warning).toHaveBeenCalledWith(expect.stringContaining('BOM 已更新'))
    expect(wrapper.find('.sm-qty-input').exists()).toBe(false)
    expect(qtyCellOf(wrapper, 'A专有布').text()).toBe('22')
    expect(purchaseApi.factorySummary).toHaveBeenCalledTimes(2)
    expect(m.qtyDrafts).toEqual({})
    expect(m.qtySavingKey).toBeNull()
    wrapper.unmount()
  })
})

describe('保存后的跨页同源（验收 c/d/e）', () => {
  it('c) 保存后切到供应商页签：数量 = 自定义值', async () => {
    const wrapper = await setup()
    await setAndSave(await beginEdit(wrapper, 'A专有布'), '100')

    await wrapper.findAll('.sm-tab-btn')[1]!.trigger('click')
    const supplierRow = wrapper.findAll('tbody tr').find((tr) => tr.text().includes('A专有布'))!
    // 行尾三格恒为 [数量, 单位, 来源订单]（供应商格被 rowspan 合并时列偏移）
    const tds = supplierRow.findAll('td')
    expect(tds[tds.length - 3]!.text()).toBe('100')
    wrapper.unmount()
  })

  it('d) 重开汇总后：工厂页与供应商页仍显示自定义值（不回退 BOM 推算）', async () => {
    const wrapper = await setup()
    await setAndSave(await beginEdit(wrapper, 'A专有布'), '100')

    // 重开：后端返回已落库真值（90.91），BOM 仍是 20 → 仍判为手工调整
    const reopened = factoryData()
    reopened.groups[0]!.suppliers[0]!.fabrics[1]!.quantity = 90.91
    vi.mocked(purchaseApi.factorySummary).mockResolvedValue(reopened as never)
    const reopenedSupplier = supplierData()
    reopenedSupplier.materials[1]!.total_quantity = 90.91
    vi.mocked(purchaseApi.supplierSummary).mockResolvedValue(reopenedSupplier as never)
    await m.openSummary([1])
    await flushPromises()

    expect(qtyCellOf(wrapper, 'A专有布').text()).toBe('100')
    await wrapper.findAll('.sm-tab-btn')[1]!.trigger('click')
    const supplierRow = wrapper.findAll('tbody tr').find((tr) => tr.text().includes('A专有布'))!
    const tds = supplierRow.findAll('td')
    expect(tds[tds.length - 3]!.text()).toBe('100')
    wrapper.unmount()
  })

  it('e) 多 SKU 共用物料：各 SKU 行相加 = 自定义总量，供应商页同值', async () => {
    const wrapper = await setup()
    // 共享布落库 60（非手工）→ 两 SKU 行 22 / 44
    const rows = dataRows(wrapper).filter((tr) => tr.text().includes('共享布'))
    expect(rows.map((tr) => tr.find('.sm-qty-cell').text())).toEqual(['22', '44'])

    // 点第一块进入编辑（预载共享明细总量 66），改成 110 保存
    const input = await beginEdit(wrapper, '共享布', 0)
    expect((input.element as HTMLInputElement).value).toBe('66')
    await setAndSave(input, '110')

    // 落库 100（110/1.1）≠ ΣBOM 60 → 手工：总量 110 按 20:40 分摊为 37 / 73
    const after = dataRows(wrapper).filter((tr) => tr.text().includes('共享布'))
    const qtys = after.map((tr) => Number(tr.find('.sm-qty-cell').text()))
    expect(qtys).toEqual([37, 73])
    expect(qtys.reduce((s, v) => s + v, 0)).toBe(110)

    await wrapper.findAll('.sm-tab-btn')[1]!.trigger('click')
    const supplierRow = wrapper.findAll('tbody tr').find((tr) => tr.text().includes('共享布'))!
    const tds = supplierRow.findAll('td')
    expect(tds[tds.length - 3]!.text()).toBe('110')
    wrapper.unmount()
  })
})
