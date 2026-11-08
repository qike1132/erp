/**
 * 「工厂内部订单」页签 —— 产品部位列 + 列位置对调回归测试（2026-11-05 生产缺陷）。
 *
 * 用户诉求（两条）：
 *   ① 「产品部位」列整列空白 → 根因是合并模式下后端把 part_name 清空（它是聚合键），
 *      前端拿同一个字段做展示 ⇒ 全空。修复口径：展示改用独立的 `part_display`；
 *   ② 「产品部位」与「供应商」显示位置对调，且**值必须落在对调后的正确列上**
 *      （不能只挪表头）。屏幕 / 前端打印导出 / 后端打印三处必须同序。
 *
 * 本文件锁三条：
 *   P1 列序：表头第 5 列 = 产品部位、第 6 列 = 供应商；打印表头与屏幕逐列一致；
 *   P2 不串列：每行的供应商值渲染在供应商格、部位值渲染在部位格（含 rowspan 跨行场景）；
 *   P3 不空白：合并模式（part_name 为空 + part_display 多部位）时部位仍逐行展示。
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

import SummaryPanel from '@/views/purchase/components/SummaryPanel.vue'
import {
  FACTORY_TABLE_HEAD,
  buildFactoryHtml,
} from '@/views/purchase/composables/useSummaryModal'
import type { FactoryGroup, FactorySummaryData } from '@/views/purchase/composables/useSummaryModal'

/** 屏幕列序的期望值（唯一真值，屏幕与打印都必须与它一致） */
const EXPECTED_HEADERS = [
  '客户', '产品名称', '订单数量', '备品数量', '角色名称', '产品部位', '供应商',
  '布料名称', '规格型号', '损耗率', '数量', '单位',
]

/**
 * 生产现场那一单的形态（截图对齐）：
 * 合并模式（采购明细无 part_name ⇒ 后端 split_parts=False），BOM 记录了部位。
 * 供应商跨行：坤成 2 行、年胜 1 行。
 */
function mergedGroup(): FactoryGroup {
  return {
    customer_name: 'MINISO国际',
    product_name: '23cm企鹅公仔(蓝色)',
    product_quantity: 25000,
    skus: [
      {
        product_name: '23cm企鹅公仔(蓝色)',
        product_barcode: 'BLUE-23',
        order_qty: 25000,
        materials: [
          {
            supplier_name: '坤成', material_name: '起柔', part_name: '', part_display: '身体/头部',
            specification: '321', unit: '码', quantity: 445,
          },
          {
            supplier_name: '坤成', material_name: '狗狗', part_name: '', part_display: '头部',
            specification: '34', unit: '码', quantity: 34,
          },
          {
            supplier_name: '年胜', material_name: '氣綸', part_name: '', part_display: '身体',
            specification: '32', unit: '码', quantity: 32,
          },
        ],
      },
    ],
    suppliers: [
      {
        supplier_name: '坤成',
        fabrics: [
          { fabric_name: '起柔', part_display: '身体/头部', specification: '321', unit: '码', quantity: 321, item_ids: [1] },
          { fabric_name: '狗狗', part_display: '头部', specification: '34', unit: '码', quantity: 34, item_ids: [2] },
        ],
      },
      {
        supplier_name: '年胜',
        fabrics: [
          { fabric_name: '氣綸', part_display: '身体', specification: '32', unit: '码', quantity: 32, item_ids: [3] },
        ],
      },
    ],
  }
}

/** 回退模式（无 skus 明细）：订单级单块 + 供应商 rowspan */
function fallbackGroup(): FactoryGroup {
  return {
    customer_name: 'MINISO国际',
    product_name: '23cm企鹅公仔(蓝色)',
    product_quantity: 25000,
    suppliers: [
      {
        supplier_name: '坤成',
        fabrics: [
          { fabric_name: '起柔', part_display: '身体/头部', specification: '321', unit: '码', quantity: 321, item_ids: [1] },
          { fabric_name: '狗狗', part_display: '头部', specification: '34', unit: '码', quantity: 34, item_ids: [2] },
        ],
      },
      {
        supplier_name: '美利达',
        fabrics: [
          { fabric_name: '猦貓', part_display: '身体', specification: '23', unit: '码', quantity: 23, item_ids: [3] },
        ],
      },
    ],
  }
}

function dataOf(group: FactoryGroup): FactorySummaryData {
  return { success: true, order_count: 1, spare_rate: 0, groups: [group] }
}

function mountModal(group: FactoryGroup) {
  return mount(SummaryPanel, {
    props: {
      factoryData: dataOf(group),
      supplierData: { success: true, order_count: 1, materials: [] },
      editMode: false,
      lossRate: 0,
      orderCount: 1,
      supplierGroups: [],
    },
    attachTo: document.body,
  })
}

function headerTexts(wrapper: ReturnType<typeof mountModal>): string[] {
  return wrapper.findAll('thead th').map((th) => th.text())
}

/**
 * 只取**主表数据行**：差异对照块（横幅 + 落库行）也住在 tbody 里，
 * 混进来会破坏列位断言（它们有自己的 colspan/rowspan 结构）。
 */
function dataRows(wrapper: ReturnType<typeof mountModal>) {
  return wrapper.findAll('tbody tr').filter((tr) => {
    const cls = tr.classes()
    return !cls.includes('sm-diff-banner') && !cls.includes('sm-diff-row')
  })
}

function rowCells(wrapper: ReturnType<typeof mountModal>, index: number) {
  return dataRows(wrapper)[index]!.findAll('td')
}

describe('P1 列序：产品部位在供应商之前（屏幕 / 打印同序）', () => {
  it('屏幕表头 11 列，逐列等于期望列序', () => {
    const wrapper = mountModal(mergedGroup())
    expect(headerTexts(wrapper)).toEqual(EXPECTED_HEADERS)
    wrapper.unmount()
  })

  it('打印/导出表头与屏幕逐列一致（漏改一处 = 屏幕换了、打印没换）', () => {
    const wrapper = mountModal(mergedGroup())
    const screen = headerTexts(wrapper)
    wrapper.unmount()

    const doc = new DOMParser().parseFromString(
      `<table><thead>${FACTORY_TABLE_HEAD}</thead></table>`, 'text/html',
    )
    const printed = [...doc.querySelectorAll('th')].map((th) => th.textContent || '')
    expect(printed).toEqual(screen)
    expect(printed).toEqual(EXPECTED_HEADERS)
  })
})

describe('P2 不串列：值必须落在对调后的正确列上', () => {
  it('按 SKU 模式：部位值在第 5 格、供应商值在第 6 格（含 rowspan 跨行）', () => {
    const wrapper = mountModal(mergedGroup())
    const rows = dataRows(wrapper)
    expect(rows).toHaveLength(3)

    // 第 1 行：客户/产品名称/订单数量/备品数量 4 格（rowspan=3）+ 角色 + 部位 + 供应商(rowspan=2) + 布料…
    const first = rowCells(wrapper, 0)
    expect(first).toHaveLength(12)
    expect(first[4]!.text()).toBe('')
    expect(first[5]!.text()).toBe('身体/头部')
    expect(first[5]!.attributes('rowspan')).toBeUndefined()
    expect(first[6]!.text()).toBe('坤成')
    expect(first[6]!.attributes('rowspan')).toBe('2')
    expect(first[7]!.text()).toBe('起柔')

    // 第 2 行：角色与供应商都被上一行 rowspan 覆盖 → 只剩 部位 + 布料/规格/损耗率/数量/单位
    const second = rowCells(wrapper, 1)
    expect(second).toHaveLength(6)
    expect(second.map((td) => td.text())[0]).toBe('头部')
    expect(second.map((td) => td.text())[1]).toBe('狗狗')

    // 第 3 行：新供应商子段首行 → 部位 + 供应商(colspan 1) + 布料…（角色格仍被段 rowspan 覆盖）
    const third = rowCells(wrapper, 2)
    expect(third).toHaveLength(7)
    expect(third[0]!.text()).toBe('身体')
    expect(third[1]!.text()).toBe('年胜')
    expect(third[1]!.attributes('rowspan')).toBe('1')
    expect(third[2]!.text()).toBe('氣綸')
    wrapper.unmount()
  })

  it('回退模式（无 skus）：同样的列位，供应商 rowspan 仍挂在供应商格上', () => {
    const wrapper = mountModal(fallbackGroup())
    const rows = dataRows(wrapper)
    expect(rows).toHaveLength(3)

    const first = rowCells(wrapper, 0)
    expect(first).toHaveLength(12)
    expect(first[5]!.text()).toBe('身体/头部')
    expect(first[6]!.text()).toBe('坤成')
    expect(first[6]!.attributes('rowspan')).toBe('2')

    const second = rowCells(wrapper, 1)
    expect(second).toHaveLength(7)
    expect(second[1]!.text()).toBe('头部')
    expect(second[2]!.text()).toBe('狗狗')

    const third = rowCells(wrapper, 2)
    expect(third[1]!.text()).toBe('身体')
    expect(third[2]!.text()).toBe('美利达')
    wrapper.unmount()
  })

  it('打印数据行同序：部位格在供应商格之前', () => {
    const html = buildFactoryHtml(dataOf(mergedGroup()), 0)
    const doc = new DOMParser().parseFromString(`<table><tbody>${html}</tbody></table>`, 'text/html')
    const first = [...doc.querySelectorAll('tbody tr:first-child td')].map((td) => td.textContent || '')
    expect(first[4]).toBe('')
    expect(first[5]).toBe('身体/头部')
    expect(first[6]).toBe('坤成')
    expect(first[7]).toBe('起柔')
  })
})

describe('P3 不空白：合并模式下产品部位仍能展示', () => {
  it('屏幕：part_name 为空但 part_display 有值 → 每行都显示部位', () => {
    const wrapper = mountModal(mergedGroup())
    const shown = dataRows(wrapper).map((tr) => {
      const cells = tr.findAll('td')
      // 行内第 6 列（或供应商 rowspan 覆盖时行首第 2 格）就是部位格
      return cells.map((td) => td.text())
    })
    expect(shown[0]![5]).toBe('身体/头部')
    expect(shown[1]![0]).toBe('头部')
    expect(shown[2]![0]).toBe('身体')
    wrapper.unmount()
  })

  it('打印：同样逐行显示部位（与屏幕同源）', () => {
    const html = buildFactoryHtml(dataOf(fallbackGroup()), 0)
    expect(html).toContain('身体/头部')
    expect(html).toContain('<td>头部</td>')
    expect(html).toContain('<td>身体</td>')
  })
})
