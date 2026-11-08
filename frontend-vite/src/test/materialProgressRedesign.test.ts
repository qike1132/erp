/**
 * /material 来料进度（2026-11-08 二次改版）的结构断言。
 *
 * 这一版的前提是 owner 的一句话：**这个页面只是登记到货时间以及到货数量**。
 * 系统里只有 `material_registration.registration_date` 与明细 `received_quantity`，
 * 没有约定交期，所以本文件把「不许出现逾期/延期措辞」也当成结构事实来断言——
 * 上一版正是因为凭 30 天阈值讲「逾期」而被判定逻辑不成立。
 *
 * 断言分两层：
 *  1. progressRows.ts 纯函数：摊平（批次不合并）、账龄、久未收齐、分组统计、跨单位不给百分比；
 *  2. ProgressTable/ProgressTab：有表头、日期与数量各自成列、分组是视图模式、筛选按事实分档。
 */
import { describe, it, expect } from 'vitest'
import { nextTick } from 'vue'
import { mount } from '@vue/test-utils'
import PrimeVue from 'primevue/config'
import { plushCutePT } from '@/styles/primevue-pt'
import type { Registration, RegItem } from '@/api/material'
import { buildProgressOrderRows } from '@/views/material/composables/useMaterialRegistrations'
import {
  SLOW_DAYS,
  ageInDays,
  flattenProgressRows,
  groupProgressRows,
  productLabel,
  rowStatus,
  summarizeProgressRows,
} from '@/views/material/composables/progressRows'
import ProgressTab from '@/views/material/components/ProgressTab.vue'
import ProgressTable from '@/views/material/components/ProgressTable.vue'

/** 固定「今天」：2026-11-08（与截图同期，避免用系统时钟导致断言漂移） */
const NOW = new Date(Date.UTC(2026, 10, 8))

function item(over: Partial<RegItem> = {}): RegItem {
  return {
    id: 1,
    material_name: '1.0超柔',
    specification: 'A126#',
    material_category: 'main',
    ordered_quantity: 1200,
    received_quantity: 600,
    remaining_quantity: 600,
    progress: 50,
    unit: '码',
    ...over,
  }
}

function reg(over: Partial<Registration> = {}): Registration {
  return {
    id: 1,
    purchase_order_no: 'PO-1',
    supplier_name: '佳宝纺织',
    registration_date: '2026-10-01',
    customer_name: '华美玩具',
    product_name: '12 寸毛绒兔',
    product_quantity: 500,
    items: [item()],
    status: 'partial',
    progress: 50,
    total_ordered: 1200,
    total_received: 600,
    ...over,
  }
}

/** 登记 → 订单行 → 表格行（后续大多数断言都从这一步开始） */
function rowsOf(regs: Registration[]) {
  return flattenProgressRows(buildProgressOrderRows(regs, NOW), NOW)
}

function mountTab(regs: Registration[]) {
  const orderRows = buildProgressOrderRows(regs, NOW)
  return mount(ProgressTab, {
    props: {
      filteredRows: orderRows,
      progressOrderRows: orderRows,
      pIsLoading: false,
      pIsFetching: false,
      pPerPage: 20,
      pPages: 1,
      pCount: regs.length,
      pPage: 1,
      showSearchEmpty: false,
    },
    global: { plugins: [[PrimeVue, { unstyled: true, pt: plushCutePT }]] },
  })
}

// ============================================================
// 一、摊平：一行 = 一条登记里的一行物料
// ============================================================
describe('progressRows —— 摊平与事实口径', () => {
  it('一行 = 登记里的一行物料，带「到货日期 + 到货数量」两个事实', () => {
    const rows = rowsOf([reg({ items: [item(), item({ id: 2, material_name: '2mm吉荣', ordered_quantity: 800, received_quantity: 800, remaining_quantity: 0, unit: '码' })] })])

    expect(rows).toHaveLength(2)
    expect(rows[0]?.arrivedDate).toBe('2026-10-01')
    expect(rows[0]?.received).toBe(600)
    expect(rows[0]?.ordered).toBe(1200)
    expect(rows[0]?.materialName).toBe('1.0超柔')
  })

  it('同一供应商的两批登记不合并：到货日期不同就是两行（合并会抹掉哪一批没到齐）', () => {
    const rows = rowsOf([
      reg({ registration_date: '2026-10-01', items: [item({ id: 1, received_quantity: 600 })] }),
      reg({ id: 2, registration_date: '2026-11-05', items: [item({ id: 2, received_quantity: 300 })] }),
    ])

    expect(rows).toHaveLength(2)
    expect(rows.map((r) => r.arrivedDate).sort()).toEqual(['2026-10-01', '2026-11-05'])
    expect(rows.every((r) => r.supplierName === '佳宝纺织')).toBe(true)
  })

  it('账龄按自然日算：当天 0 天、前一天 1 天、未来为负、非法日期 null', () => {
    expect(ageInDays('2026-11-08', NOW)).toBe(0)
    expect(ageInDays('2026-11-07', NOW)).toBe(1)
    expect(ageInDays('2026-11-10', NOW)).toBe(-2)
    expect(ageInDays('', NOW)).toBeNull()
    expect(ageInDays('2026-13-40', NOW)).toBeNull()
  })

  it('久未收齐 = 登记满 30 天且仍未收齐；已到齐的老批次不算', () => {
    const rows = rowsOf([
      reg({ registration_date: '2026-10-01', items: [item({ id: 1, received_quantity: 600 })] }),
      reg({ id: 2, registration_date: '2026-11-05', items: [item({ id: 2, received_quantity: 600 })] }),
      reg({ id: 3, registration_date: '2026-09-01', items: [item({ id: 3, received_quantity: 1200, remaining_quantity: 0 })] }),
    ])

    const old = rows.find((r) => r.arrivedDate === '2026-10-01')!
    const fresh = rows.find((r) => r.arrivedDate === '2026-11-05')!
    const doneOld = rows.find((r) => r.arrivedDate === '2026-09-01')!

    expect(old.ageDays).toBe(38)
    expect(old.isSlow).toBe(true)
    expect(fresh.isSlow).toBe(false)
    expect(doneOld.isSlow).toBe(false)
  })

  it('行状态只表达数量事实：未到 / 部分 / 到齐', () => {
    const rows = rowsOf([
      reg({ registration_date: '2026-10-01', items: [item({ id: 1, received_quantity: 0 })] }),
      reg({ id: 2, registration_date: '2026-10-02', items: [item({ id: 2, received_quantity: 600 })] }),
      reg({ id: 3, registration_date: '2026-10-03', items: [item({ id: 3, received_quantity: 1200, remaining_quantity: 0 })] }),
    ])

    expect(rowStatus(rows.find((r) => r.arrivedDate === '2026-10-01')!)).toBe('todo')
    expect(rowStatus(rows.find((r) => r.arrivedDate === '2026-10-02')!)).toBe('partial')
    expect(rowStatus(rows.find((r) => r.arrivedDate === '2026-10-03')!)).toBe('done')
  })

  it('统计四档：total / todo / partial / done / slow', () => {
    const rows = rowsOf([
      reg({ registration_date: '2026-10-01', items: [item({ id: 1, received_quantity: 0 })] }),
      reg({ id: 2, registration_date: '2026-10-02', items: [item({ id: 2, received_quantity: 600 })] }),
      reg({ id: 3, registration_date: '2026-10-03', items: [item({ id: 3, received_quantity: 1200, remaining_quantity: 0 })] }),
    ])

    // 10-01 未到、10-02 部分到货：两者登记都超过 30 天且未收齐 → slow 2
    expect(summarizeProgressRows(rows)).toEqual({ total: 3, todo: 1, partial: 1, done: 1, slow: 2 })
  })

  it('多 SKU 订单的产品名超过两个时收口为「等 N 个」', () => {
    const order = buildProgressOrderRows([reg({
      sku_items: [
        { product_name: '甲', barcode: 'A', quantity: 1 },
        { product_name: '乙', barcode: 'B', quantity: 1 },
        { product_name: '丙', barcode: 'C', quantity: 1 },
      ],
    })], NOW)[0]!

    expect(productLabel(order)).toBe('甲 · 乙 等 3 个')
  })
})

// ============================================================
// 二、分组：视图模式，不是层级
// ============================================================
describe('progressRows —— 分组统计（视图模式）', () => {
  const threeRows = [
    reg({ registration_date: '2026-10-01', items: [item({ id: 1, received_quantity: 0 })] }),
    reg({ id: 2, registration_date: '2026-10-02', items: [item({ id: 2, received_quantity: 600 })] }),
    reg({ id: 3, registration_date: '2026-11-06', supplier_name: '华源', purchase_order_no: 'PO-2', items: [item({ id: 3, received_quantity: 1200, remaining_quantity: 0 })] }),
  ]

  it('按供应商分组：组头给「x/y 项到齐」与最近到货', () => {
    const first = groupProgressRows(rowsOf(threeRows), 'supplier')[0]!

    expect(first.label).toBe('佳宝纺织')
    expect(first.rows).toHaveLength(2)
    expect(first.doneCount).toBe(0)
    expect(first.latestDate).toBe('2026-10-02')
  })

  it('组按「最久已等天数」倒序：最该处理的排最前', () => {
    const groups = groupProgressRows(rowsOf(threeRows), 'supplier')

    expect(groups.map((g) => g.label)).toEqual(['佳宝纺织', '华源'])
    expect(groups[0]?.oldestAgeDays).toBe(38)
    expect(groups[1]?.oldestAgeDays).toBe(2)
  })

  it('组内单位一致才给数量进度；跨单位只报项数', () => {
    const sameUnit = groupProgressRows(rowsOf([
      reg({ registration_date: '2026-10-01', items: [item({ id: 1, ordered_quantity: 1000, received_quantity: 500 })] }),
      reg({ id: 2, registration_date: '2026-10-02', items: [item({ id: 2, ordered_quantity: 1000, received_quantity: 1000, remaining_quantity: 0 })] }),
    ]), 'supplier')[0]!

    expect(sameUnit.unit).toBe('码')
    expect(sameUnit.progressPct).toBe(75)

    const mixedUnit = groupProgressRows(rowsOf([
      reg({ registration_date: '2026-10-01', items: [item({ id: 1, unit: '码' })] }),
      reg({ id: 2, registration_date: '2026-10-02', items: [item({ id: 2, unit: '只' })] }),
    ]), 'supplier')[0]!

    expect(mixedUnit.unit).toBeNull()
    expect(mixedUnit.progressPct).toBeNull()
    expect(mixedUnit.orderedTotal).toBeNull()
  })

  it('按订单分组以订单号为准；不分组只有一个无标题组', () => {
    const byOrder = groupProgressRows(rowsOf(threeRows), 'order')
    expect(byOrder.map((g) => g.label).sort()).toEqual(['PO-1', 'PO-2'])

    const flat = groupProgressRows(rowsOf(threeRows), 'none')
    expect(flat).toHaveLength(1)
    expect(flat[0]?.label).toBe('')
    expect(flat[0]?.rows).toHaveLength(3)
  })

  it('空输入不产出空组', () => {
    expect(groupProgressRows([], 'supplier')).toEqual([])
    expect(groupProgressRows([], 'none')).toEqual([])
  })
})

// ============================================================
// 三、表格：有表头，日期与数量各自成列
// ============================================================
describe('ProgressTable —— 扁平行列表', () => {
  const orderRows = buildProgressOrderRows([reg({
    items: [
      item({ id: 1, material_name: '1.0超柔', received_quantity: 600 }),
      item({ id: 2, material_name: '2mm吉荣', ordered_quantity: 800, received_quantity: 800, remaining_quantity: 0 }),
      item({ id: 3, material_name: '塑料眼珠', unit: '只', ordered_quantity: 24000, received_quantity: 0, remaining_quantity: 24000 }),
    ],
  })], NOW)

  function mountTable() {
    const rows = flattenProgressRows(orderRows, NOW)
    return mount(ProgressTable, {
      props: { groups: groupProgressRows(rows, 'supplier'), mode: 'supplier', rowCount: rows.length },
    })
  }

  it('有表头：到货日期 / 已到·采购 / 进度（上一版没有表头，用户靠猜列义）', () => {
    const w = mountTable()

    expect(w.find('.mrt-head').text()).toContain('到货日期')
    expect(w.find('.mrt-head').text()).toContain('已到 / 采购')
    expect(w.find('.mrt-head').text()).toContain('进度')
  })

  it('日期列给「MM-DD + 已等 N 天」，数量列给「已到 / 采购 + 单位」', () => {
    const first = mountTable().findAll('.mrt-row')[0]!

    expect(first.find('.mrt-date').text()).toBe('10-01')
    expect(first.find('.mrt-age').text()).toBe('38 天')
    expect(first.find('.c-qty').text()).toContain('600')
    expect(first.find('.c-qty').text()).toContain('1,200')
    expect(first.find('.c-qty').text()).toContain('码')
  })

  it('全表不出现「逾期 / 延期」措辞（系统没有约定交期，说「逾期」是虚构）', () => {
    const text = mountTable().text()

    expect(text).not.toContain('逾期')
    expect(text).not.toContain('延期')
  })

  it('0 到货写「未到」、收齐写「到齐」，不写 0% / 100%', () => {
    const labels = mountTable().findAll('.mrt-row').map((r) => r.find('.mrt-pct').text())

    expect(labels).toContain('未到')
    expect(labels).toContain('到齐')
    expect(labels).toContain('50%')
  })

  it('久未收齐的行整行淡红底，其余不染色', () => {
    const rows = mountTable().findAll('.mrt-row')

    expect(rows[0]?.classes()).toContain('is-slow')
    expect(rows.some((r) => !r.classes().includes('is-slow'))).toBe(true)
  })

  it('按供应商分组时供应商列不占位（与组标题重复）；按订单时显示', async () => {
    const w = mountTable()
    expect(w.classes()).toContain('is-suphide')

    await w.setProps({ mode: 'order' })
    expect(w.classes()).not.toContain('is-suphide')
  })

  it('组头给「x/y 项到齐」，并在跨单位时不给数量百分比', () => {
    const w = mountTable()

    expect(w.find('.mrt-group').text()).toContain('佳宝纺织')
    expect(w.find('.mrt-group').text()).toContain('1/3 项到齐')
    expect(w.find('.mrt-g-meter').exists()).toBe(false) // 码 / 只 混单位
  })

  it('明细按钮把供应商与订单抛给父级', async () => {
    const w = mountTable()

    await w.findAll('.mrt-btn')[0]!.trigger('click')

    expect(w.emitted('view-detail')?.[0]).toEqual(['佳宝纺织', 'PO-1'])
  })
})

// ============================================================
// 四、ProgressTab：筛选按事实分档 · 分组可切
// ============================================================
describe('ProgressTab —— 筛选与分组', () => {
  const regs = [
    reg({ registration_date: '2026-10-01', items: [item({ id: 1, received_quantity: 0 })] }),
    reg({ id: 2, registration_date: '2026-10-02', items: [item({ id: 2, received_quantity: 600 })] }),
    reg({ id: 3, registration_date: '2026-11-06', supplier_name: '华源', purchase_order_no: 'PO-2', items: [item({ id: 3, received_quantity: 1200, remaining_quantity: 0 })] }),
  ]

  it('默认按供应商分组，挂载即见表头与分组行', () => {
    const w = mountTab(regs)

    expect(w.find('.mrt-head').exists()).toBe(true)
    expect(w.findAll('.mrt-group')).toHaveLength(2)
    expect(w.findAll('.mrt-row')).toHaveLength(3)
  })

  it('筛选条只按到货事实分档：全部 / 未到 / 部分到货 / 已到齐 / ≥30 天', () => {
    const labels = mountTab(regs).findAll('.mr-chip').map((c) => c.text())

    expect(labels[0]).toContain('全部')
    expect(labels[1]).toContain('未到')
    expect(labels[2]).toContain('部分到货')
    expect(labels[3]).toContain('已到齐')
    expect(labels[4]).toContain('≥30 天')
  })

  it('分档计数与数据一致（10-01 与 10-02 两批都满 30 天未收齐 → ≥30 天 2 项）', () => {
    const chips = mountTab(regs).findAll('.mr-chip').map((c) => c.find('.mr-chip-n').text())

    expect(chips).toEqual(['3', '1', '1', '1', '2'])
  })

  it('点「未到」只剩未到的行；点「≥30 天」只剩久未收齐的行', async () => {
    const w = mountTab(regs)

    await w.findAll('.mr-chip')[1]!.trigger('click')
    expect(w.findAll('.mrt-row')).toHaveLength(1)
    expect(w.find('.mrt-pct').text()).toBe('未到')

    await w.findAll('.mr-chip')[4]!.trigger('click')
    expect(w.findAll('.mrt-row')).toHaveLength(2)
    expect(w.findAll('.mrt-row').every((r) => r.classes().includes('is-slow'))).toBe(true)
  })

  it('切「不分组」后没有分组行，行数不变', async () => {
    const w = mountTab(regs)

    await w.findAll('.mr-seg-btn')[2]!.trigger('click')
    await nextTick()

    expect(w.findAll('.mrt-group')).toHaveLength(0)
    expect(w.findAll('.mrt-row')).toHaveLength(3)
  })

  it('切「按订单」分组行变订单号', async () => {
    const w = mountTab(regs)

    await w.findAll('.mr-seg-btn')[1]!.trigger('click')
    await nextTick()

    const labels = w.findAll('.mrt-g-label').map((n) => n.text())
    expect(labels.sort()).toEqual(['PO-1', 'PO-2'])
  })

  it('明细按钮透传 view-supplier 给父级', async () => {
    const w = mountTab(regs)

    await w.findAll('.mrt-btn')[0]!.trigger('click')

    expect(w.emitted('view-supplier')?.[0]).toEqual(['佳宝纺织', 'PO-1'])
  })

  it('搜索无命中时给「当前页无匹配」，不冒充「暂无登记」', async () => {
    const w = mountTab([])

    await w.setProps({ showSearchEmpty: true })

    expect(w.text()).toContain('当前页无匹配')
  })

  it('筛选无命中时说明是本页无该类物料', async () => {
    const w = mountTab([reg({ registration_date: '2026-11-07' })])

    await w.findAll('.mr-chip')[3]!.trigger('click')

    expect(w.find('.mr-empty').text()).toContain('本页没有')
  })

  it('首次加载显示骨架，不显示表头（避免表头跳动）', async () => {
    const w = mountTab([])
    await w.setProps({ pIsLoading: true, progressOrderRows: [] })

    expect(w.find('.mr-skel').exists()).toBe(true)
    expect(w.find('.mrt-head').exists()).toBe(false)
  })

  it('30 天阈值是单一来源（SLOW_DAYS）', () => {
    expect(SLOW_DAYS).toBe(30)
  })
})
