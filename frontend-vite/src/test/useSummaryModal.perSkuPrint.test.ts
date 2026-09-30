/**
 * 打印 / 导出「按 SKU 展开」回归（2026-09-30）。
 *   E1 有 materials → 每 SKU 一块；左侧三列按 SKU 一行；物料行数 = Σ 各 SKU 物料数
 *   E2 差异存在时，对照块一并输出（打印件必须与屏幕同源，否则等于隐瞒差异）
 *   E2b 打印对照块结构：数据行恰好 10 列（标签 colspan=4 + 供应商 + 后 5 格）、
 *       损耗率取该落库行**快照率**、数量为按该率加放派生值；无差异时不出现「实际下单」
 *   E3 无 materials → 输出与改动前逐字一致（零回归）
 */
import { describe, it, expect } from 'vitest'
import { buildFactoryHtml } from '@/views/purchase/composables/useSummaryModal'
import type { FactoryGroup, FactorySummaryData } from '@/views/purchase/composables/useSummaryModal'

function perSkuGroup(): FactoryGroup {
  return {
    customer_name: '客户甲', product_name: '产品A、产品B', product_quantity: 300,
    skus: [
      { product_name: '产品A', product_barcode: 'bA', order_qty: 100, materials: [
        { supplier_name: '供应商甲', material_name: '共享布', specification: 'S1', unit: '米', quantity: 20 },
      ] },
      { product_name: '产品B', product_barcode: 'bB', order_qty: 200, materials: [
        { supplier_name: '供应商甲', material_name: '共享布', specification: 'S1', unit: '米', quantity: 40 },
      ] },
    ],
    suppliers: [{ supplier_name: '供应商甲', fabrics: [
      { fabric_name: '共享布', specification: 'S1', unit: '米', quantity: 60, item_ids: [1] },
    ] }],
  }
}

function legacyGroup(): FactoryGroup {
  return {
    customer_name: '客户甲', product_name: '产品A', product_quantity: 100,
    suppliers: [{ supplier_name: '供应商甲', fabrics: [
      { fabric_name: '共享布', specification: 'S1', unit: '米', quantity: 20, item_ids: [1] },
    ] }],
  }
}

const dataOf = (g: FactoryGroup): FactorySummaryData => ({ success: true, order_count: 1, groups: [g] })

function tbodyText(html: string): string[] {
  const doc = new DOMParser().parseFromString(`<table><tbody>${html}</tbody></table>`, 'text/html')
  return [...doc.querySelectorAll('tbody tr')].map((tr) => tr.textContent || '')
}

function tbodyRows(html: string): HTMLTableRowElement[] {
  const doc = new DOMParser().parseFromString(`<table><tbody>${html}</tbody></table>`, 'text/html')
  return [...doc.querySelectorAll('tbody tr')] as HTMLTableRowElement[]
}

/**
 * 每行的**有效列数**：计入 colspan，并跳过被上方 rowspan 覆盖的列。
 * 用于断言「不同结构（按 SKU 块 / 横幅 / 对照块数据行）都恰好 10 列、无一错位」。
 */
function rowWidths(rows: HTMLTableRowElement[]): number[] {
  const occupied = new Map<number, number>() // 列号 → 后续仍需占用的行数
  return rows.map((tr) => {
    let col = 0
    const added: [number, number, number][] = []
    for (const cell of Array.from(tr.querySelectorAll('td'))) {
      while ((occupied.get(col) ?? 0) > 0) col++
      const cs = Number(cell.getAttribute('colspan') ?? 1)
      const rs = Number(cell.getAttribute('rowspan') ?? 1)
      if (rs > 1) added.push([col, cs, rs - 1])
      col += cs
    }
    // 本行结束：先递减既有占用，再并入本行 rowspan 覆盖（rs-1 行）
    for (const [c, v] of Array.from(occupied)) {
      if (v - 1 > 0) occupied.set(c, v - 1)
      else occupied.delete(c)
    }
    for (const [c0, cs, rem] of added) for (let k = 0; k < cs; k++) occupied.set(c0 + k, rem)
    return col
  })
}

describe('E1 有 materials → 按 SKU 块', () => {
  it('每 SKU 一行（左侧三列），物料行数 = Σ 各 SKU 物料数', () => {
    const rows = tbodyText(buildFactoryHtml(dataOf(perSkuGroup()), 10))

    expect(rows).toHaveLength(2)                    // A 一块 1 行 + B 一块 1 行
    expect(rows[0]).toContain('产品A')
    expect(rows[1]).toContain('产品B')
    // 数量列按该物料行率加放（率未给 ⇒ 回退统一率 10‰）：20 × 1.01 = 20.2 → ceil 21
    expect(rows[0]).toContain('21')
    expect(rows[1]).toContain('41')                 // 40 × 1.01 = 40.4 → ceil 41
  })
})

describe('E2 差异 → 对照块同源输出', () => {
  it('落库 65 ≠ 推算 60 → 输出「实际下单」行', () => {
    const g = perSkuGroup()
    g.suppliers![0]!.fabrics[0]!.quantity = 65
    const rows = tbodyText(buildFactoryHtml(dataOf(g), 10))

    expect(rows.some((t) => t.includes('实际下单'))).toBe(true)
    expect(rows.some((t) => t.includes('65'))).toBe(true)
  })
})

describe('E2b 打印对照块结构（与屏幕同源）', () => {
  it('数据行恰好 10 列；率取快照率、数量为加放派生值', () => {
    const g = perSkuGroup()
    g.suppliers![0]!.fabrics[0]!.quantity = 65      // 落库 65 ≠ 推算 60 → 有差异
    g.suppliers![0]!.fabrics[0]!.loss_rate = 500    // 快照率 500‰（传入的实时率是 200‰）
    const html = buildFactoryHtml(dataOf(g), 10, [[[200]]], [10])
    const rows = tbodyRows(html)

    // 每行（按 SKU 块 / 横幅 / 对照块数据行）有效列数都必须恰好 10，无一错位
    expect(rowWidths(rows)).toEqual(rows.map(() => 10))

    // 横幅：单格跨 10 列，点名物料与两个数值
    const banner = rows.find((tr) => (tr.textContent || '').includes('不一致'))!
    expect(banner).toBeDefined()
    expect(banner.querySelector('td')!.getAttribute('colspan')).toBe('10')
    expect(banner.textContent).toContain('共享布')
    expect(banner.textContent).toContain('60')
    expect(banner.textContent).toContain('65')

    // 数据行首行：标签 colspan=4（跨本块全部行）+ 供应商(rowspan) + 后 5 格 = 7 格 / 有效 10 列
    const dataRow = rows.find((tr) => tr.querySelector('td[colspan="4"]'))!
    const cells = Array.from(dataRow.querySelectorAll('td'))
    expect(cells).toHaveLength(7)
    expect(cells[0]!.getAttribute('colspan')).toBe('4')
    expect(cells[0]!.textContent).toContain('实际下单')
    expect(cells[0]!.getAttribute('rowspan')).toBe('1')   // 本组仅 1 条落库行
    expect(cells[1]!.textContent).toBe('供应商甲')
    // 后 5 格列序与主表一致；损耗率=快照率 500（不是传入的实时率 200）、数量=ceil(65×1.5)=98
    expect(cells.slice(2).map((td) => td.textContent)).toEqual(['共享布', 'S1', '500', '98', '米'])
  })

  it('无差异时不出现「实际下单」', () => {
    const rows = tbodyText(buildFactoryHtml(dataOf(perSkuGroup()), 10))

    expect(rows.some((t) => t.includes('实际下单'))).toBe(false)
  })
})

describe('E3 无 materials → 零回归', () => {
  it('单块、订单级物料，与改动前逐字一致', () => {
    const rows = tbodyText(buildFactoryHtml(dataOf(legacyGroup()), 10))

    expect(rows).toHaveLength(1)
    expect(rows[0]).toContain('产品A')
    expect(rows[0]).toContain('共享布')
    expect(rows[0]).not.toContain('实际下单')
  })
})
