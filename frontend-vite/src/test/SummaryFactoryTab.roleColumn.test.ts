/**
 * 工厂内部订单「角色名称」列与**表格对齐**（2026-11-08）。
 *
 * 需求：一个产品名称下有多个角色时，表格按角色分类汇总——每个角色一块，
 * 块内列出该角色的 产品部位/供应商/布料名称/规格型号/损耗率/数量/单位。
 *
 * 对齐是本文件的核心断言（生产缺陷回归）：物料按角色排序后，**同一供应商会
 * 出现在多个角色段里（互不相邻）**。供应商格的 rowspan 若按「全 SKU 计数」，
 * 会把中间其它供应商的行也罩住 → 表头与数据错位。正确做法是角色段、供应商
 * 子段都按**连续段**计算 rowspan。
 *
 *   R1 屏幕表头 12 列：角色名称在「备品数量」之后、「产品部位」之前；
 *   R2 角色段首行渲染角色格（rowspan=段行数），段内其余行由 rowspan 覆盖；
 *   R3 供应商子段首行渲染供应商格（rowspan=子段行数）——同一供应商跨角色段
 *      出现时**每个子段各有一个供应商格**（不是只在首次出现时渲染）；
 *   R4 屏幕与打印的每一行有效列宽都恰好 12（计入 colspan、跳过被 rowspan
 *      覆盖的列）——任何 rowspan/colspan 算错都会在这里现形；
 *   R5 多角色共用同一物料：损耗率照常显示/编辑（一条明细一个率），数量编辑锁定
 *      并说明原因（明细是合并总量，角色行只显示分配量）；
 *   R6/R7 「订单数量」与「备品数量」列都按角色段拆格（role_quantities，与物料分配
 *      同源）：各角色数量格 rowspan=角色段行数、SKU 总量挪名称格副行（合计 N）、
 *      隐藏款带标记、备品 = ceil(该角色数量 × 订单级率‰) 逐段计算不合并；
 *      每行有效列宽仍恒 12（数量列从块级 rowspan 变段级后的核心对齐防线）。
 */
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import { headerLabels } from './headerLabels'
import SummaryPanel from '@/views/purchase/components/SummaryPanel.vue'
import {
  FACTORY_TABLE_HEAD,
  buildFactoryHtml,
} from '@/views/purchase/composables/useSummaryModal'
import type { FactoryGroup, FactorySummaryData } from '@/views/purchase/composables/useSummaryModal'

/**
 * 一个产品名、两个角色；供应商**跨角色交错**（对齐缺陷的最小复现）：
 * - 角色A：红布（供应商甲）、松紧带（供应商甲）
 * - 角色B：蓝布（供应商甲）、松紧带（供应商甲）、蓝扣（供应商乙）
 * 供应商甲在角色A、角色B 各出现一次（互不相邻）→ 全 SKU 计数的 rowspan 必错。
 */
function roleGroup(): FactoryGroup {
  return {
    customer_name: '客户甲',
    product_name: '陈列样盲盒',
    product_quantity: 100,
    skus: [
      {
        product_name: '陈列样盲盒',
        product_barcode: 'B-1',
        order_qty: 100,
        materials: [
          {
            supplier_name: '供应商甲', material_name: '红布', part_name: '',
            part_display: '身体', role_display: '角色A', role_id: 1,
            specification: 'S1', unit: '米', quantity: 10,
          },
          {
            supplier_name: '供应商甲', material_name: '松紧带', part_name: '',
            part_display: '身体', role_display: '角色A', role_id: 1,
            specification: 'S3', unit: '米', quantity: 3,
          },
          {
            supplier_name: '供应商甲', material_name: '蓝布', part_name: '',
            part_display: '头部', role_display: '角色B', role_id: 2,
            specification: 'S2', unit: '米', quantity: 20,
          },
          {
            supplier_name: '供应商甲', material_name: '松紧带', part_name: '',
            part_display: '头部', role_display: '角色B', role_id: 2,
            specification: 'S3', unit: '米', quantity: 2,
          },
          {
            supplier_name: '供应商乙', material_name: '蓝扣', part_name: '',
            part_display: '头部', role_display: '角色B', role_id: 2,
            specification: 'S4', unit: '个', quantity: 2,
          },
        ],
      },
    ],
    suppliers: [
      {
        supplier_name: '供应商甲',
        fabrics: [
          { fabric_name: '红布', part_display: '身体', role_display: '角色A', role_id: 1, specification: 'S1', unit: '米', quantity: 10, item_ids: [1] },
          { fabric_name: '松紧带', part_display: '身体', role_display: '角色A', role_id: 1, specification: 'S3', unit: '米', quantity: 3, item_ids: [2] },
          { fabric_name: '松紧带', part_display: '头部', role_display: '角色B', role_id: 2, specification: 'S3', unit: '米', quantity: 2, item_ids: [5] },
          { fabric_name: '蓝布', part_display: '头部', role_display: '角色B', role_id: 2, specification: 'S2', unit: '米', quantity: 20, item_ids: [3] },
        ],
      },
      {
        supplier_name: '供应商乙',
        fabrics: [
          { fabric_name: '蓝扣', part_display: '头部', role_display: '角色B', role_id: 2, specification: 'S4', unit: '个', quantity: 2, item_ids: [4] },
        ],
      },
    ],
  }
}

/**
 * 带按角色数量（role_quantities）的夹具：R6/R7 验证「订单数量」列按角色段拆格。
 * 角色A（常规，60）+ 角色B（隐藏款，40）；物料行按 role_display 绑 role_id，
 * 与后端「materials.role_id ↔ role_quantities.role_id 同源匹配」的口径一致。
 */
function roleQtyGroup(): FactoryGroup {
  const base = roleGroup()
  const sku = base.skus![0]!
  return {
    ...base,
    skus: [{
      ...sku,
      role_quantities: [
        { role_id: 1, role_name: '角色A', quantity: 60, is_hidden: false },
        { role_id: 2, role_name: '角色B', quantity: 40, is_hidden: true },
      ],
      materials: (sku.materials || []).map((m) => ({
        ...m,
        role_id: m.role_display === '角色A' ? 1 : 2,
      })),
    }],
  }
}

function dataOf(group: FactoryGroup): FactorySummaryData {
  return { success: true, order_count: 1, spare_rate: 0, groups: [group] }
}

function mountModal(group: FactoryGroup, qtyDrafts: Record<string, string> = {}, lossRate = 0) {
  return mount(SummaryPanel, {
    props: {
      factoryData: dataOf(group),
      supplierData: { success: true, order_count: 1, materials: [] },
      qtyDrafts,
      lossRate,
      orderCount: 1,
      supplierGroups: [],
    },
    attachTo: document.body,
  })
}

/**
 * 每行的**有效列宽**：计入 colspan，并跳过被上方 rowspan 覆盖的列。
 * 与 useSummaryModal.perSkuPrint.test.ts 的 rowWidths 同一算法（DOM 版）。
 * 任何 rowspan/colspan 算错（罩住别的段、漏渲染格）都会让某行 ≠ 12 而现形。
 */
function rowWidthsOf(trs: HTMLTableRowElement[]): number[] {
  const occupied = new Map<number, number>()
  return trs.map((tr) => {
    let col = 0
    const added: [number, number, number][] = []
    for (const cell of Array.from(tr.querySelectorAll('td'))) {
      while ((occupied.get(col) ?? 0) > 0) col++
      const cs = Number(cell.getAttribute('colspan') ?? 1)
      const rs = Number(cell.getAttribute('rowspan') ?? 1)
      if (rs > 1) added.push([col, cs, rs - 1])
      col += cs
    }
    for (const [c, v] of Array.from(occupied)) {
      if (v - 1 > 0) occupied.set(c, v - 1)
      else occupied.delete(c)
    }
    for (const [c0, cs, rem] of added) for (let k = 0; k < cs; k++) occupied.set(c0 + k, rem)
    return col
  })
}

describe('工厂内部订单 · 角色分类汇总与表格对齐', () => {
  it('R1 屏幕表头 12 列：角色名称在「产品名称」与「订单数量」之间', () => {
    const wrapper = mountModal(roleGroup())
    const headers = headerLabels(wrapper.findAll('thead th'))
    expect(headers).toEqual([
      '客户', '产品名称', '角色名称', '订单数量', '备品数量', '产品部位', '供应商',
      '布料名称', '规格型号', '损耗率', '数量', '单位',
    ])
    wrapper.unmount()
  })

  it('R2/R3 角色段与供应商子段都按连续段渲染 rowspan（跨段供应商各有一格）', () => {
    const wrapper = mountModal(roleGroup())
    const rows = wrapper.findAll('.smf-scroll tbody tr')
    expect(rows).toHaveLength(5)

    // 第 1 行：角色A 段首（rowspan=2）+ 供应商甲 子段首（rowspan=2）
    // 列序：客户0 产品1 角色2 订单3 备品4 部位5 供应商6 物料7
    const r0 = rows[0]!.findAll('td')
    expect(r0[2]!.text()).toBe('角色A')
    expect(r0[2]!.attributes('rowspan')).toBe('2')
    expect(r0[5]!.text()).toBe('身体')
    expect(r0[6]!.text()).toBe('供应商甲')
    expect(r0[6]!.attributes('rowspan')).toBe('2')
    expect(r0[7]!.text()).toBe('红布')

    // 第 2 行（角色A 段内、同供应商子段内）：角色与供应商都被 rowspan 覆盖；
    // 松紧带被两个角色共用 → 数量编辑锁定（显示该角色分配量），损耗率照常显示（输入框）
    const r1 = rows[1]!.findAll('td')
    expect(r1.map((td) => td.text())).toEqual(['身体', '松紧带', 'S3', '', '3', '米'])
    const r1Rate = r1[3]!.find('input[type="number"]')
    expect(r1Rate).toBeDefined()
    expect((r1Rate!.element as HTMLInputElement).value).toBe('0')

    // 第 3 行（角色B 段首）：**再次**渲染供应商甲（新的连续子段，跨段不能复用旧格）
    const r2 = rows[2]!.findAll('td')
    expect(r2[0]!.text()).toBe('角色B')
    expect(r2[0]!.attributes('rowspan')).toBe('3')
    expect(r2[1]!.text()).toBe('头部')
    expect(r2[2]!.text()).toBe('供应商甲')
    expect(r2[2]!.attributes('rowspan')).toBe('2')
    expect(r2[3]!.text()).toBe('蓝布')

    // 第 4 行（角色B 段内、同供应商子段）：只剩 部位 + 后 5 格；率格同上（共用行显示率）
    const r3 = rows[3]!.findAll('td')
    expect(r3.map((td) => td.text())).toEqual(['头部', '松紧带', 'S3', '', '2', '米'])

    // 第 5 行（供应商乙 子段首）
    const r4 = rows[4]!.findAll('td')
    expect(r4[0]!.text()).toBe('头部')
    expect(r4[1]!.text()).toBe('供应商乙')
    expect(r4[1]!.attributes('rowspan')).toBe('1')
    expect(r4[2]!.text()).toBe('蓝扣')
    wrapper.unmount()
  })

  it('R4 屏幕：每行有效列宽恰好 12（rowspan/colspan 全对齐）', () => {
    const wrapper = mountModal(roleGroup())
    const trs = Array.from(
      wrapper.element.querySelectorAll('.smf-scroll tbody tr'),
    ) as HTMLTableRowElement[]
    const widths = rowWidthsOf(trs)
    expect(widths).toHaveLength(5)
    expect(widths.every((w) => w === 12)).toBe(true)
    wrapper.unmount()
  })

  it('R4 打印/导出：与屏幕同一套行模型，每行有效列宽恰好 12', () => {
    const html = buildFactoryHtml(dataOf(roleGroup()), 0)
    const doc = new DOMParser().parseFromString(`<table><tbody>${html}</tbody></table>`, 'text/html')
    const widths = rowWidthsOf(Array.from(doc.querySelectorAll('tbody tr')) as HTMLTableRowElement[])
    expect(widths.length).toBeGreaterThan(0)
    expect(widths.every((w) => w === 12)).toBe(true)
    // 共享常量列序与屏幕一致
    expect(FACTORY_TABLE_HEAD).toContain('<th>角色名称</th><th>订单数量</th><th>备品数量</th><th>产品部位</th><th>供应商</th>')
  })

  it('R5 拆行口径：多角色共用的同一物料各自成行，损耗率与数量都可编辑（键含 role_id）', () => {
    // 2026-11-11 拆行后：松紧带在角色 A、B 各有一条落库明细（role_id 1/2），
    // 每行有自己的坐标与 item_ids —— 数量单元格正常进入编辑，不再因「多角色共用」锁定。
    // 非编辑态：损耗率是可编辑输入框（各自独立），数量为可点击的展示值
    const view = mountModal(roleGroup())
    const viewRows = view.findAll('.smf-scroll tbody tr').filter((tr) => tr.text().includes('松紧带'))
    expect(viewRows).toHaveLength(2)
    for (const tr of viewRows) {
      const tds = tr.findAll('td')
      expect(tds[3]!.find('input[type="number"]').exists()).toBe(true)
      expect(tds[4]!.find('.sm-qty-cell').exists()).toBe(true)
    }
    view.unmount()

    // 进入编辑：率与数量都是输入框（各自独立，编辑互不串行）
    const wrapper = mountModal(roleGroup(), { '0-0-1': '3', '0-0-2': '2' })
    const rows = wrapper.findAll('.smf-scroll tbody tr').filter((tr) => tr.text().includes('松紧带'))
    expect(rows).toHaveLength(2)
    const qtyTexts: string[] = []
    for (const tr of rows) {
      const tds = tr.findAll('td')
      expect(tds[3]!.find('input[type="number"]').exists()).toBe(true)
      expect(tds[4]!.find('.sm-qty-input').exists()).toBe(true)
      qtyTexts.push((tds[4]!.find('.sm-qty-input').element as HTMLInputElement).value)
    }
    expect(qtyTexts).toEqual(['3', '2'])
    wrapper.unmount()
  })

  it('R6 订单数量与备品都按角色段拆格：各角色数量/备品 + 名称格合计副行 + 隐藏款标记；列宽恒 12', () => {
    // rate=50‰：角色A 备品 = ceil(60×50/1000)=3，角色B（隐藏款）= ceil(40×50/1000)=2
    const wrapper = mountModal(roleQtyGroup(), {}, 50)
    const rows = wrapper.findAll('.smf-scroll tbody tr')
    expect(rows).toHaveLength(5)

    // 首行：名称格（SKU 名 + 合计副行）+ 角色A 格 + 角色A 订单数量格（60.0）+ 角色A 备品格（3.0），均 rowspan=2
    // 列序：客户0 产品1 角色2 订单3 备品4
    const r0 = rows[0]!.findAll('td')
    expect(r0[1]!.text()).toContain('合计 100.0')
    expect(r0[2]!.text()).toBe('角色A')
    expect(r0[2]!.attributes('rowspan')).toBe('2')
    expect(r0[3]!.text()).toBe('60.0')
    expect(r0[3]!.attributes('rowspan')).toBe('2')
    expect(r0[4]!.text()).toBe('3.0')
    expect(r0[4]!.attributes('rowspan')).toBe('2')

    // 第 2 行（角色A 段内）：订单数量/备品格都被段 rowspan 覆盖
    const r1 = rows[1]!.findAll('td')
    expect(r1.map((td) => td.text()).slice(0, 2)).toEqual(['身体', '松紧带'])

    // 第 3 行（角色B 段首）：角色格 角色B +（隐藏款）标记、订单数量格 40.0、备品格 2.0，均 rowspan=3
    const r2 = rows[2]!.findAll('td')
    expect(r2[0]!.text()).toContain('角色B')
    expect(r2[0]!.text()).toContain('（隐藏款）')
    expect(r2[0]!.attributes('rowspan')).toBe('3')
    expect(r2[1]!.text()).toBe('40.0')
    expect(r2[1]!.attributes('rowspan')).toBe('3')
    expect(r2[2]!.text()).toBe('2.0')
    expect(r2[2]!.attributes('rowspan')).toBe('3')

    // 对齐护栏：每行有效列宽恰好 12（订单数量/备品列从块级 rowspan 变段级后的核心回归防线）
    const trs = Array.from(
      wrapper.element.querySelectorAll('.smf-scroll tbody tr'),
    ) as HTMLTableRowElement[]
    const widths = rowWidthsOf(trs)
    expect(widths).toHaveLength(5)
    expect(widths.every((w) => w === 12)).toBe(true)
    wrapper.unmount()
  })

  it('R8 单角色/无角色产品：整表隐藏「角色名称」列（11 列）；多角色才显示（12 列）', () => {
    // 单角色夹具：所有物料行同一个角色名 → 隐藏列（2026-11-08 用户要求）
    const single = roleGroup()
    single.skus![0]!.materials = (single.skus![0]!.materials || []).map((m) => ({
      ...m, role_display: '角色A',
    }))
    const wrapper = mountModal(single)
    const headers = headerLabels(wrapper.findAll('thead th'))
    expect(headers).toHaveLength(11)
    expect(headers).not.toContain('角色名称')
    // 屏幕每行有效列宽 11（隐藏角色列后仍全对齐）
    const trs = Array.from(
      wrapper.element.querySelectorAll('.smf-scroll tbody tr'),
    ) as HTMLTableRowElement[]
    expect(rowWidthsOf(trs).every((w) => w === 11)).toBe(true)
    wrapper.unmount()

    // 打印同一判定：11 列、无角色表头
    const html = buildFactoryHtml(dataOf(single), 0)
    expect(html).not.toContain('<th>角色名称</th>')
    const doc = new DOMParser().parseFromString(`<table><tbody>${html}</tbody></table>`, 'text/html')
    const widths = rowWidthsOf(Array.from(doc.querySelectorAll('tbody tr')) as HTMLTableRowElement[])
    expect(widths.length).toBeGreaterThan(0)
    expect(widths.every((w) => w === 11)).toBe(true)

    // 多角色夹具（roleGroup）：列显示、12 列（回归：别把多角色也隐藏了）
    const multi = mountModal(roleGroup())
    expect(headerLabels(multi.findAll('thead th'))).toContain('角色名称')
    expect(multi.findAll('thead th')).toHaveLength(12)
    multi.unmount()
  })

  it('R7 打印/导出与屏幕同一套拆分：列宽恒 12，合计与隐藏款标记齐全', () => {
    const html = buildFactoryHtml(dataOf(roleQtyGroup()), 50)
    const doc = new DOMParser().parseFromString(`<table><tbody>${html}</tbody></table>`, 'text/html')
    const widths = rowWidthsOf(Array.from(doc.querySelectorAll('tbody tr')) as HTMLTableRowElement[])
    expect(widths.length).toBeGreaterThan(0)
    expect(widths.every((w) => w === 12)).toBe(true)
    expect(html).toContain('合计')
    expect(html).toContain('（隐藏款）')
    // 隐藏款标记挂在角色名称格（角色名后紧跟小字），不是订单数量格
    expect(html).toMatch(/角色B<div style="font-size:10px;color:#8e8e93;">（隐藏款）<\/div>/)
    expect(html).toContain('60.0')
    expect(html).toContain('40.0')
    // 备品也按角色逐段打印（同一 spareRate 口径：ceil(角色数量 × 率‰)）
    expect(html).toContain('3.0')
    expect(html).toContain('2.0')
  })
})
