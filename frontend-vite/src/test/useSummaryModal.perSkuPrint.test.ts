/**
 * 打印 / 导出「按 SKU 展开」回归（2026-09-30）。
 *   E1 有 materials → 每 SKU 一块；左侧三列按 SKU 一行；物料行数 = Σ 各 SKU 物料数
 *   E2 差异存在时，对照块一并输出（打印件必须与屏幕同源，否则等于隐瞒差异）
 *   E2b 打印对照块结构：数据行恰好 10 列（标签 colspan=4 + 供应商 + 后 5 格）、
 *       损耗率取该落库行**快照率**、数量为按该率加放派生值；无差异时不出现「实际下单」
 *   E3 无 materials → 输出与改动前逐字一致（零回归）
 *   E4 无落库坐标的行（BOM 生成后新增）→ 打印与屏幕同源：率 '—'、数量取基准量（不加放）
 */
import { describe, it, expect } from 'vitest'
import { buildFactoryHtml, buildFactoryTable } from '@/views/purchase/composables/useSummaryModal'
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
  it('数据行与主表同列；率取快照率、数量为加放派生值', () => {
    const g = perSkuGroup()
    g.suppliers![0]!.fabrics[0]!.quantity = 65      // 落库 65 ≠ 推算 60 → 有差异
    g.suppliers![0]!.fabrics[0]!.loss_rate = 500    // 快照率 500‰（传入的实时率是 200‰）
    const html = buildFactoryHtml(dataOf(g), 10, [[[200]]], [10])
    const rows = tbodyRows(html)

    // 每行（按 SKU 块 / 横幅 / 对照块数据行）有效列数都必须恰好 11（本文件夹具无角色名 → 隐藏角色列）
    expect(rowWidths(rows)).toEqual(rows.map(() => 11))

    // 横幅：单格跨 11 列，点名物料与两个数值（文案与数字格式须与屏幕逐字一致：
    // 屏幕是「以下物料含手工调整：上方「数量」已按实际下单值显示」，数字走 formatQty ⇒ '60.0' / '65.0'）
    const banner = rows.find((tr) => (tr.textContent || '').includes('手工调整'))!
    expect(banner).toBeDefined()
    expect(banner.querySelector('td')!.getAttribute('colspan')).toBe('11')
    expect(banner.textContent).toContain('以下物料含手工调整')
    expect(banner.textContent).toContain('上方「数量」已按实际下单值显示')
    expect(banner.textContent).toContain('共享布')
    expect(banner.textContent).toContain('60.0')
    expect(banner.textContent).toContain('65.0')

    // 数据行首行：标签 colspan=2（跨本块全部行：客户/产品名称）+ 订单(空) + 备品(空)
    // + 部位(空) + 供应商(rowspan) + 后 5 格 = 10 个 td / 有效 11 列（本夹具无角色名 → 隐藏角色列）
    const dataRow = rows.find((tr) => tr.querySelector('td[colspan="2"]'))!
    const cells = Array.from(dataRow.querySelectorAll('td'))
    expect(cells).toHaveLength(10)
    expect(cells[0]!.getAttribute('colspan')).toBe('2')
    expect(cells[0]!.textContent).toContain('实际下单')
    expect(cells[0]!.getAttribute('rowspan')).toBe('1')   // 本组仅 1 条落库行
    // 列序与主表一致：订单数量（空）→ 备品数量（空）→ 产品部位（空）→ 供应商
    expect(cells[1]!.textContent).toBe('')
    expect(cells[2]!.textContent).toBe('')
    expect(cells[3]!.textContent).toBe('')
    expect(cells[4]!.textContent).toBe('供应商甲')
    // 后 5 格列序与主表一致；损耗率=快照率 500（不是传入的实时率 200）、数量=ceil(65×1.5)=98
    expect(cells.slice(5).map((td) => td.textContent)).toEqual(['共享布', 'S1', '500.0', '98', '米'])
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

describe('E4 无落库坐标行：打印必须与屏幕同源', () => {
  it('BOM 生成后新增的物料 → 率渲染 —、数量取基准量（与屏幕一致，不加放）', () => {
    const g = perSkuGroup()
    // 给产品B 增加一条落库明细里没有的物料 ⇒ coord = null（只读行）
    g.skus![1]!.materials!.push({
      supplier_name: '供应商甲', material_name: '新加布', specification: 'S9', unit: '米', quantity: 5,
    })
    const rows = tbodyRows(buildFactoryHtml(dataOf(g), 10))

    const newRow = rows.find((tr) => (tr.textContent || '').includes('新加布'))!
    expect(newRow).toBeDefined()
    const cells = Array.from(newRow.querySelectorAll('td'))
    // 该行非块首行（角色与供应商格都被 rowspan 覆盖）⇒ 恰好后 6 格（部位 + 5 格）。
    // 无坐标行**不加放**：率 '—'、数量 = 基准量 5。
    // （曾误为回退 lossRate 10 并 ceil(5 × 1.01) = 6 → 屏幕「— / 5」而打印「10 / 6」。）
    expect(cells.map((td) => td.textContent)).toEqual(['', '新加布', 'S9', '—', '5', '米'])
  })
})

/**
 * E6 表头与表体必须由**同一次**列形态判定产出（2026-11-15 评审 A2）。
 *
 * 原实现里表体在 `buildFactoryHtml` 内部算 `anyGroupMultiRole(data)`、表头由调用处
 * 再算一遍——两次独立判定。现在 `buildFactoryTable` 一次判定并成对返回，本用例锁住
 * 「head 的 th 数 === 每个数据行的有效列数」，任何一侧被单独改动都会变红。
 */
describe('E6 表头/表体同源', () => {
  /** 把表头 + 表体包成完整表格，返回表头 th 数与每行有效列数。 */
  function headAndRowWidths(head: string, body: string) {
    const doc = new DOMParser().parseFromString(
      `<table><thead>${head}</thead><tbody>${body}</tbody></table>`, 'text/html',
    )
    return {
      thCount: doc.querySelectorAll('thead th').length,
      widths: rowWidths([...doc.querySelectorAll('tbody tr')] as HTMLTableRowElement[]),
    }
  }

  it('单角色/无角色 → 表头 11 列，每行也恰好 11 列', () => {
    const { head, body } = buildFactoryTable(dataOf(perSkuGroup()), 10)
    const { thCount, widths } = headAndRowWidths(head, body)
    expect(thCount).toBe(11)
    expect(widths.every((w) => w === 11)).toBe(true)
  })

  it('多角色 → 表头 12 列，每行也恰好 12 列（角色列由同一个判定打开）', () => {
    const g = perSkuGroup()
    g.skus![0]!.materials = [
      { supplier_name: '供应商甲', material_name: '布A', specification: 'S1', unit: '米', quantity: 10, role_display: '角色A', role_id: 1 },
      { supplier_name: '供应商甲', material_name: '布B', specification: 'S1', unit: '米', quantity: 10, role_display: '角色B', role_id: 2 },
    ]
    g.suppliers![0]!.fabrics = [
      { fabric_name: '布A', specification: 'S1', unit: '米', quantity: 10, item_ids: [1], role_display: '角色A', role_id: 1 },
      { fabric_name: '布B', specification: 'S1', unit: '米', quantity: 10, item_ids: [2], role_display: '角色B', role_id: 2 },
    ]
    const { head, body } = buildFactoryTable(dataOf(g), 10)
    const { thCount, widths } = headAndRowWidths(head, body)

    expect(thCount).toBe(12)
    expect(widths.every((w) => w === 12)).toBe(true)
  })
})

/**
 * E7 打印必须读「屏幕那份差异快照」，不得实时重算（2026-11-15 评审 A1）。
 *
 * 场景（生产可复现）：打开汇总 → 在表格里手改某行数量并保存（落库值变、快照不变）
 * → 立刻点打印。旧实现打印实时重算，于是「屏幕没有横幅、打印件却出现对照块」。
 * 修复后两侧同读 `diffSnapshot`，本用例从两个方向钉死该行为。
 */
describe('E7 打印读快照而非实时计算', () => {
  /** 构造「落库 65 ≠ 推算 60」的真实差异（实时算会命中）。 */
  function groupWithLiveDiff(): FactoryGroup {
    const g = perSkuGroup()
    g.suppliers![0]!.fabrics[0]!.quantity = 65
    return g
  }

  it('快照为空（屏幕无横幅）→ 即使实时算有差异，打印也不得出现对照块', () => {
    const rows = tbodyText(buildFactoryHtml(dataOf(groupWithLiveDiff()), 10, undefined, undefined, { 0: [] }))

    expect(rows.some((t) => t.includes('实际下单'))).toBe(false)
    expect(rows.some((t) => t.includes('手工调整'))).toBe(false)
  })

  it('快照有差异（屏幕有横幅）→ 即使实时算没有差异，打印也照常输出对照块', () => {
    const snapshot = { 0: [{ materialName: '共享布', partName: '', perSku: 60, stored: 65 }] }
    const rows = tbodyText(buildFactoryHtml(dataOf(perSkuGroup()), 10, undefined, undefined, snapshot))

    expect(rows.some((t) => t.includes('实际下单'))).toBe(true)
    expect(rows.some((t) => t.includes('手工调整'))).toBe(true)
  })

  it('不传快照（既有调用路径）→ 维持实时计算，零回归', () => {
    const rows = tbodyText(buildFactoryHtml(dataOf(groupWithLiveDiff()), 10))

    expect(rows.some((t) => t.includes('实际下单'))).toBe(true)
  })
})

/**
 * E5 无 BOM 占位行的 colspan 必须补齐列数（2026-11-15 OCR 评审发现的真实错列）。
 *
 * 原写法 `colspan = showRoleColumn ? 7 : 8`：隐藏角色列时表头是 11 列，而占位行已渲染
 * 「客户 + 产品名称 + 订单数量 + 备品数量」= 4 格，再 colspan=8 得到 12 列 → 宽出一列，
 * A4 打印/导出出现错位。缺口恒为 7（角色列显示时本行多渲染角色格，表头也同步 +1）。
 */
describe('E5 无 BOM 占位行的列数', () => {
  it('隐藏角色列（表头 11 列）→ 占位行 colspan=7，全表有效列数恒为 11', () => {
    const g = perSkuGroup()
    g.skus![0]!.materials = []           // 首块无 BOM → 占位行
    const rows = tbodyRows(buildFactoryHtml(dataOf(g), 10))

    const noBomRow = rows.find((tr) => (tr.textContent || '').includes('无 BOM 明细'))!
    expect(noBomRow).toBeDefined()
    // 占位格不是行内首格（前面还有客户/名称/数量格），按文本定位
    const noBomCell = [...noBomRow.querySelectorAll('td')].find((td) => td.textContent === '无 BOM 明细')!
    expect(noBomCell.getAttribute('colspan')).toBe('7')
    expect(rowWidths(rows)).toEqual(rows.map(() => 11))
  })

  it('显示角色列（表头 12 列）且非首块无 BOM → 占位行 colspan 仍为 7，全表有效列数恒为 12', () => {
    const g = perSkuGroup()
    g.skus![0]!.materials = [
      { supplier_name: '供应商甲', material_name: '布A', specification: 'S1', unit: '米', quantity: 10, role_display: '角色A' },
      { supplier_name: '供应商甲', material_name: '布B', specification: 'S1', unit: '米', quantity: 10, role_display: '角色B' },
    ]
    g.skus![1]!.materials = []           // 非首块无 BOM → 占位行
    const rows = tbodyRows(buildFactoryHtml(dataOf(g), 10))

    const noBomRow = rows.find((tr) => (tr.textContent || '').includes('无 BOM 明细'))!
    expect(noBomRow).toBeDefined()
    const noBomCell = [...noBomRow.querySelectorAll('td')].find((td) => td.textContent === '无 BOM 明细')!
    expect(noBomCell.getAttribute('colspan')).toBe('7')
    expect(rowWidths(rows)).toEqual(rows.map(() => 12))
  })
})
