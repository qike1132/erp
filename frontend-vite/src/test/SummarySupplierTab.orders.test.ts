/**
 * 供应商采购订单页签「来源订单」列（2026-11-09 需求）。
 *
 * 契约：
 * 1. 表头含「来源订单」，每行逐单平铺全部采购单号 + 该单数量；
 * 2. 不折叠（没有 N 单 的展开按钮）；
 * 3. 旧后端不返回 orders 时显示 —，不抛错。
 */
import { describe, it, expect, vi } from 'vitest'
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

import SummarySupplierTab from '@/views/purchase/components/SummarySupplierTab.vue'
import type { MaterialItem, SupplierSummaryData } from '@/views/purchase/composables/useSummaryModal'

const MATERIALS: MaterialItem[] = [
  {
    material_name: '涤纶布', specification: '150D / 白色', total_quantity: 120,
    unit: '米', supplier_name: '鑫盛布业',
    orders: [
      { order_no: 'PO-20261108-0001', quantity: 30 },
      { order_no: 'PO-20261108-0005', quantity: 50 },
      { order_no: 'PO-20261108-0009', quantity: 40 },
    ],
  },
  {
    material_name: '尼龙拉链', specification: '3# / 白色', total_quantity: 200,
    unit: '条', supplier_name: '恒美辅料',
    orders: [{ order_no: 'PO-20261108-0003', quantity: 200 }],
  },
  {
    material_name: '树脂纽扣', specification: '12mm / 黑色', total_quantity: 500,
    unit: '颗', supplier_name: '恒美辅料',
    // 旧后端 / 异常数据：无来源订单
  },
]

const SUPPLIER_DATA: SupplierSummaryData = {
  success: true, order_count: 4, materials: MATERIALS,
}

const GROUPS = [
  { supplierName: '鑫盛布业', materials: [MATERIALS[0]!] },
  { supplierName: '恒美辅料', materials: [MATERIALS[1]!, MATERIALS[2]!] },
]

function mountTab() {
  return mount(SummarySupplierTab, {
    props: { supplierData: SUPPLIER_DATA, orderCount: 4, supplierGroups: GROUPS },
  })
}

describe('供应商采购订单：来源订单列', () => {
  it('表头含「来源订单」', () => {
    const w = mountTab()
    const headers = w.findAll('th').map((th) => th.text())
    expect(headers).toContain('来源订单')
    w.unmount()
  })

  it('多单合并时逐单平铺单号与数量，不折叠', () => {
    const w = mountTab()
    const text = w.text()
    for (const no of ['PO-20261108-0001', 'PO-20261108-0005', 'PO-20261108-0009']) {
      expect(text).toContain(no)
    }
    expect(text).toContain('30 米')
    expect(text).toContain('50 米')
    expect(text).toContain('40 米')
    // 不折叠：页签内没有展开按钮
    expect(w.findAll('button')).toHaveLength(0)
    w.unmount()
  })

  it('单一张单同样平铺显示', () => {
    const w = mountTab()
    const row = w.findAll('tbody tr')[1]!
    expect(row.text()).toContain('PO-20261108-0003')
    expect(row.text()).toContain('200 条')
    w.unmount()
  })

  it('无来源订单时显示 — 而不是空白或报错', () => {
    const w = mountTab()
    const row = w.findAll('tbody tr')[2]!
    expect(row.find('.src-empty').text()).toBe('—')
    w.unmount()
  })
})
