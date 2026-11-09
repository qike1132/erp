/**
 * /material 来料进度改版的结构断言（整页网格表）。
 *
 * 设计（2026-11-09 用户定稿）：
 *  · 整页一张带边框的合并单元格网格表，外观对齐 /purchase「工厂汇总」表
 *  · 列：订单号/时间 · 客户 · 产品名称 · 订单数量 · 供应商（副行登记日期）
 *        · 物料名称 · 规格型号 · 已到数量 · 采购数量 · 单位 · 进度 · 操作
 *  · 合并：订单号/客户/产品名称/订单数量 按整单 rowspan；供应商按分组 rowspan
 *  · 进度：0 → 未到，100% → 到齐，其余 → 百分比；逾期物料红字 + 「逾期」标记
 *  · 数据仍来自 buildProgressOrderRows（后端零改动）；逾期 30 天口径不变
 */
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'

import {
  buildProgressOrderRows,
  filterProgressRows,
  type ProgressOrderRow,
} from '@/views/material/composables/useMaterialRegistrations'
import MaterialProgressGrid from '@/views/material/components/MaterialProgressGrid.vue'
import MaterialToolbar from '@/views/material/components/MaterialToolbar.vue'
import ProgressTab from '@/views/material/components/ProgressTab.vue'
import type { Registration } from '@/api/material'

/** 固定"今天"：cutoff = 2026-08-30（UTC），早于它且未收齐 → 逾期 */
const NOW = new Date('2026-09-29T12:00:00+08:00')

function reg(over: Partial<Registration>): Registration {
  return {
    id: 1,
    purchase_order_no: 'PO-1',
    supplier_name: '供应商A',
    customer_name: '客户X',
    product_name: '产品甲',
    product_quantity: 100,
    items: [],
    status: 'pending',
    progress: 0,
    total_ordered: 0,
    total_received: 0,
    ...over,
  }
}

const REG_OVERDUE = reg({
  id: 11,
  purchase_order_no: 'PO-OLD',
  supplier_name: '佳宝',
  registration_date: '2026-08-28', // < cutoff 08-30 → 逾期
  items: [
    { id: 1, material_name: '浓缩苹果汁', specification: '', material_category: 'main', ordered_quantity: 2000, received_quantity: 0, remaining_quantity: 2000, progress: 0, unit: 'kg' },
  ],
})
const REG_FRESH = reg({
  id: 12,
  purchase_order_no: 'PO-NEW',
  supplier_name: '华源',
  registration_date: '2026-08-31', // ≥ cutoff → 不逾期
  items: [
    { id: 2, material_name: '易拉盖', specification: '', material_category: 'main', ordered_quantity: 5000, received_quantity: 1500, remaining_quantity: 3500, progress: 30, unit: '只' },
  ],
})

// ============================================================
// 预处理纯函数：同单合并 · 分组 · 逾期 · 状态
// ============================================================
describe('buildProgressOrderRows —— 同单合并与供应商分组', () => {
  it('同一订单的多条登记合并为一行，每条登记一个供应商块', () => {
    const rows = buildProgressOrderRows([
      { ...REG_FRESH, purchase_order_no: 'PO-M', supplier_name: '佳宝', registration_date: '2026-09-01' },
      { ...REG_OVERDUE, purchase_order_no: 'PO-M', supplier_name: '华源', registration_date: '2026-09-02' },
    ], NOW)

    expect(rows).toHaveLength(1)
    expect(rows[0]?.groups.map((g) => g.supplierName)).toEqual(['佳宝', '华源'])
  })

  it('一条登记内按明细供应商拆块：同供应商物料合并，缺字段回退登记级', () => {
    const rows = buildProgressOrderRows([reg({
      purchase_order_no: 'PO-S',
      supplier_name: '三虎',
      items: [
        { id: 1, material_name: '7毛精兔绒', specification: '1214#', material_category: 'fabric', ordered_quantity: 270, received_quantity: 0, remaining_quantity: 270, progress: 0, unit: '码', supplier_name: '三虎' },
        { id: 2, material_name: '1.0超柔', specification: 'A126#', material_category: 'fabric', ordered_quantity: 12, received_quantity: 0, remaining_quantity: 12, progress: 0, unit: '码', supplier_name: '美利达' },
        { id: 3, material_name: '1.0超柔', specification: 'A50#', material_category: 'fabric', ordered_quantity: 39, received_quantity: 0, remaining_quantity: 39, progress: 0, unit: '码', supplier_name: '美利达' },
        { id: 4, material_name: '2mm吉荣', specification: 'B016#', material_category: 'fabric', ordered_quantity: 11, received_quantity: 0, remaining_quantity: 11, progress: 0, unit: '码' },
      ],
    })], NOW)

    const groups = rows[0]!.groups
    expect(groups.map((g) => g.supplierName)).toEqual(['三虎', '美利达'])
    // 缺明细供应商 → 回退登记级（三虎）
    expect(groups[0]?.items.map((i) => i.material_name)).toEqual(['7毛精兔绒', '2mm吉荣'])
    // 同供应商同名物料合并
    expect(groups[1]?.items).toHaveLength(1)
    expect(groups[1]?.items[0]?.ordered_quantity).toBe(51)
    expect(rows[0]?.groups.length).toBe(2)
  })

  it('filling 类物料不进入进度块（与旧实现口径一致）', () => {
    const rows = buildProgressOrderRows([reg({
      items: [
        { id: 1, material_name: '主料', specification: '', material_category: 'main', ordered_quantity: 10, received_quantity: 0, remaining_quantity: 10, progress: 0, unit: 'kg' },
        { id: 2, material_name: '填充料', specification: '', material_category: 'filling', ordered_quantity: 99, received_quantity: 99, remaining_quantity: 0, progress: 100, unit: 'kg' },
      ],
    })], NOW)

    expect(rows[0]?.groups[0]?.items.map((i) => i.material_name)).toEqual(['主料'])
  })

  it('同组同名物料合并数量、进度取合并后的比值', () => {
    const rows = buildProgressOrderRows([reg({
      items: [
        { id: 1, material_name: '易拉盖', specification: '', material_category: 'main', ordered_quantity: 3000, received_quantity: 1000, remaining_quantity: 2000, progress: 33, unit: '只' },
        { id: 2, material_name: '易拉盖', specification: '', material_category: 'main', ordered_quantity: 2000, received_quantity: 1000, remaining_quantity: 1000, progress: 50, unit: '只' },
      ],
    })], NOW)

    const item = rows[0]?.groups[0]?.items[0]
    expect(item?.ordered_quantity).toBe(5000)
    expect(item?.received_quantity).toBe(2000)
    expect(item?.progress).toBe(40)
  })

  it('行进度 = 各组已收 / 各组采购（数量加权，非简单平均）', () => {
    const rows = buildProgressOrderRows([REG_OVERDUE, REG_FRESH], NOW)
    // 两单未合并（不同订单），各查一行
    const old = rows.find((r) => r.orderNo === 'PO-OLD')
    expect(old?.progress).toBe(0)
    const fresh = rows.find((r) => r.orderNo === 'PO-NEW')
    expect(fresh?.progress).toBe(30)
  })

  it('组状态：有任何收货 → partial，完全没有 → pending', () => {
    const rows = buildProgressOrderRows([REG_OVERDUE, REG_FRESH], NOW)
    expect(rows.find((r) => r.orderNo === 'PO-OLD')?.groups[0]?.status).toBe('pending')
    expect(rows.find((r) => r.orderNo === 'PO-NEW')?.groups[0]?.status).toBe('partial')
  })
})

describe('buildProgressOrderRows —— 逾期判定（后端 30 天口径）', () => {
  it('登记日期早于今天-30 且未收齐 → 组与物料都标逾期', () => {
    const rows = buildProgressOrderRows([REG_OVERDUE], NOW)
    const g = rows[0]?.groups[0]

    expect(g?.overdue).toBe(true)
    expect(g?.items[0]?.overdue).toBe(true)
    expect(rows[0]?.hasOverdue).toBe(true)
  })

  it('29 天前登记 → 不逾期（边界：cutoff 当天与之后都算新）', () => {
    const rows = buildProgressOrderRows([REG_FRESH], NOW)

    expect(rows[0]?.groups[0]?.overdue).toBe(false)
    expect(rows[0]?.hasOverdue).toBe(false)
  })

  it('超 30 天但已收齐 → 不逾期', () => {
    const done = reg({
      purchase_order_no: 'PO-DONE',
      registration_date: '2026-07-01',
      items: [
        { id: 3, material_name: '罐体', specification: '', material_category: 'main', ordered_quantity: 100, received_quantity: 100, remaining_quantity: 0, progress: 100, unit: '只' },
      ],
    })
    const rows = buildProgressOrderRows([done], NOW)

    expect(rows[0]?.groups[0]?.overdue).toBe(false)
  })

  it('超 30 天且部分到货 → 未收齐的物料仍逾期（收到的不标）', () => {
    const partial = reg({
      purchase_order_no: 'PO-PART',
      registration_date: '2026-08-01',
      items: [
        { id: 4, material_name: '罐体', specification: '', material_category: 'main', ordered_quantity: 100, received_quantity: 100, remaining_quantity: 0, progress: 100, unit: '只' },
        { id: 5, material_name: '易拉盖', specification: '', material_category: 'main', ordered_quantity: 100, received_quantity: 20, remaining_quantity: 80, progress: 20, unit: '只' },
      ],
    })
    const rows = buildProgressOrderRows([partial], NOW)

    expect(rows[0]?.groups[0]?.overdue).toBe(true)
    expect(rows[0]?.groups[0]?.items[0]?.overdue).toBe(false)
    expect(rows[0]?.groups[0]?.items[1]?.overdue).toBe(true)
  })
})

// ============================================================
// 客户端搜索（当前页过滤）
// ============================================================
describe('filterProgressRows —— 客户端搜索', () => {
  const rows = buildProgressOrderRows([REG_OVERDUE, REG_FRESH], NOW)

  it('匹配订单号 / 客户 / 产品 / 供应商 / 物料名（大小写不敏感）', () => {
    expect(filterProgressRows(rows, 'po-old')).toHaveLength(1)
    expect(filterProgressRows(rows, '客户X')).toHaveLength(2)
    expect(filterProgressRows(rows, '产品甲')).toHaveLength(2)
    expect(filterProgressRows(rows, '华源')).toHaveLength(1)
    expect(filterProgressRows(rows, '易拉盖')).toHaveLength(1)
  })

  it('空关键词 = 不过滤；无命中 = 空（调用方渲染"当前页无匹配"）', () => {
    expect(filterProgressRows(rows, '')).toHaveLength(2)
    expect(filterProgressRows(rows, '不存在的料')).toHaveLength(0)
  })
})

// ============================================================
// MaterialProgressGrid —— 整页网格表
// ============================================================
function mountGrid(rows: ProgressOrderRow[]) {
  return mount(MaterialProgressGrid, { props: { rows } })
}

/** 一个订单、两家供应商：三虎 1 项 / 美利达 2 项 */
function multiGroupRows(): ProgressOrderRow[] {
  return buildProgressOrderRows([reg({
    purchase_order_no: 'PO-G',
    customer_name: 'MINISO国内',
    product_name: 'Dundun系列-猫头鹰挂件',
    product_quantity: 10000,
    supplier_name: '三虎',
    registration_date: '2026-09-01',
    items: [
      { id: 1, material_name: '7毛精兔绒', specification: '1214#', material_category: 'fabric', ordered_quantity: 310, received_quantity: 0, remaining_quantity: 310, progress: 0, unit: '码', supplier_name: '三虎' },
      { id: 2, material_name: '1.0超柔', specification: 'A126#', material_category: 'fabric', ordered_quantity: 12, received_quantity: 6, remaining_quantity: 6, progress: 50, unit: '码', supplier_name: '美利达' },
      { id: 3, material_name: '2mm吉荣', specification: 'B016#', material_category: 'fabric', ordered_quantity: 11, received_quantity: 11, remaining_quantity: 0, progress: 100, unit: '码', supplier_name: '美利达' },
    ],
  })], NOW)
}

describe('MaterialProgressGrid —— 列与合并单元格', () => {
  it('表头 12 列：订单号/时间 · 客户 · 产品名称 · 订单数量 · 供应商 · 物料名称 · 规格型号 · 已到数量 · 采购数量 · 单位 · 进度 · 操作', () => {
    const heads = mountGrid(multiGroupRows()).findAll('th').map((th) => th.text())

    expect(heads).toEqual([
      '订单号 / 时间', '客户', '产品名称', '订单数量', '供应商', '物料名称',
      '规格型号', '已到数量', '采购数量', '单位', '进度', '操作',
    ])
  })

  it('一行 = 一项物料；订单级四列 rowspan = 该单物料行数', () => {
    const w = mountGrid(multiGroupRows())

    const bodyRows = w.findAll('tbody tr')
    expect(bodyRows).toHaveLength(3)
    // 订单号 / 客户 / 产品名称 / 订单数量 四格共用 rowspan=3
    expect(w.findAll('td[rowspan="3"]')).toHaveLength(4)
  })

  it('供应商按分组合并：rowspan = 组内物料数；「明细」每组一个，点击上抛供应商与订单号', async () => {
    const w = mountGrid(multiGroupRows())

    const supplierCells = w.findAll('td.mp-supplier')
    expect(supplierCells).toHaveLength(2)
    expect(supplierCells[0]?.attributes('rowspan')).toBe('1')
    expect(supplierCells[1]?.attributes('rowspan')).toBe('2')

    const detailBtns = w.findAll('button.mp-detail')
    expect(detailBtns).toHaveLength(2)
    await detailBtns[1]!.trigger('click')
    expect(w.emitted('view-supplier')?.[0]).toEqual(['美利达', 'PO-G'])
  })

  it('登记日期显示在供应商单元格副行（现有数据只有登记级日期）', () => {
    const w = mountGrid(multiGroupRows())

    expect(w.find('td.mp-supplier').text()).toContain('三虎')
    expect(w.find('td.mp-supplier').text()).toContain('2026-09-01')
  })

  it('订单数量 / 已到 / 采购千分位与单位分列展示', () => {
    const w = mountGrid(multiGroupRows())

    expect(w.text()).toContain('10,000')
    expect(w.text()).toContain('310')
    expect(w.findAll('td.mp-unit').map((td) => td.text())).toEqual(['码', '码', '码'])
  })

  it('多 SKU 订单：产品名称在合并格内逐行列出', () => {
    const rows = buildProgressOrderRows([reg({
      purchase_order_no: 'PO-SKU',
      sku_items: [
        { product_name: '产品甲', barcode: 'B1', quantity: 100 },
        { product_name: '产品乙', barcode: 'B2', quantity: 200 },
      ],
      items: [
        { id: 1, material_name: '主料', specification: '', material_category: 'main', ordered_quantity: 10, received_quantity: 0, remaining_quantity: 10, progress: 0, unit: 'kg' },
      ],
    })], NOW)
    const w = mountGrid(rows)

    const product = w.find('td.mp-product')
    expect(product.findAll('div').map((d) => d.text())).toEqual(['产品甲', '产品乙'])
  })
})

describe('MaterialProgressGrid —— 进度列口径', () => {
  function progressRows(): ProgressOrderRow[] {
    return buildProgressOrderRows([reg({
      purchase_order_no: 'PO-P',
      registration_date: '2026-08-01', // 全部未收齐的项都逾期（30 天口径）
      items: [
        { id: 1, material_name: '未到料', specification: '', material_category: 'main', ordered_quantity: 100, received_quantity: 0, remaining_quantity: 100, progress: 0, unit: 'kg' },
        { id: 2, material_name: '部分料', specification: '', material_category: 'main', ordered_quantity: 100, received_quantity: 30, remaining_quantity: 70, progress: 30, unit: 'kg' },
        { id: 3, material_name: '到齐料', specification: '', material_category: 'main', ordered_quantity: 100, received_quantity: 100, remaining_quantity: 0, progress: 100, unit: 'kg' },
      ],
    })], NOW)
  }

  it('0% → 未到；部分 → 百分比；100% → 到齐', () => {
    const cells = mountGrid(progressRows()).findAll('td.mp-pct').map((td) => td.text())

    expect(cells[0]).toContain('未到')
    expect(cells[1]).toContain('30%')
    expect(cells[2]).toContain('到齐')
  })

  it('未逾期的进行中百分比用蓝色（与图例「进行中」一致）', () => {
    const w = mountGrid(buildProgressOrderRows([REG_FRESH], NOW))

    expect(w.find('td.mp-pct').classes()).toContain('is-ongoing')
  })

  it('逾期物料带「逾期」文字标记与 is-overdue 类（不依赖颜色单独传达）', () => {
    const w = mountGrid(progressRows())
    const overdueCells = w.findAll('td.mp-pct.is-overdue')

    expect(overdueCells).toHaveLength(2) // 未到料 + 部分料；到齐料不逾期
    expect(overdueCells[0]?.find('.mp-overdue-tag').text()).toBe('逾期')
  })
})

// ============================================================
// ProgressTab：图例 · 空态 · 分页契约
// ============================================================
function mountTab(rows: ProgressOrderRow[]) {
  return mount(ProgressTab, {
    props: {
      filteredRows: rows,
      progressOrderRows: rows,
      pIsLoading: false,
      pIsFetching: false,
      pPerPage: 20,
      pPages: 1,
      pCount: rows.length,
      pPage: 1,
      showSearchEmpty: false,
    },
  })
}

describe('ProgressTab —— 网格表容器', () => {
  it('图例四项：进行中 / 未开始 / 已到齐 / 逾期（≥2 状态色必带文字图例）', () => {
    const w = mountTab(buildProgressOrderRows([REG_FRESH], NOW))

    const legend = w.find('.mr-legend')
    expect(legend.text()).toContain('进行中')
    expect(legend.text()).toContain('未开始')
    expect(legend.text()).toContain('已到齐')
    expect(legend.text()).toContain('逾期')
  })

  it('挂载即渲染网格表（无折叠）', () => {
    const w = mountTab(buildProgressOrderRows([REG_FRESH], NOW))

    expect(w.find('table.mp-grid').exists()).toBe(true)
    expect(w.find('tbody tr').text()).toContain('易拉盖')
  })

  it('showSearchEmpty=true 时渲染"当前页无匹配"空态（搜索仅作用于当前页）', async () => {
    const w = mountTab([])
    await w.setProps({ showSearchEmpty: true })

    expect(w.text()).toContain('当前页无匹配')
  })

  it('首屏加载中显示加载态，不闪「暂无数据」空态', () => {
    const w = mount(ProgressTab, {
      props: {
        filteredRows: [],
        progressOrderRows: [],
        pIsLoading: true,
        pIsFetching: false,
        pPerPage: 20,
        pPages: 1,
        pCount: 0,
        pPage: 1,
        showSearchEmpty: false,
      },
    })

    expect(w.text()).toContain('加载中')
    expect(w.text()).not.toContain('暂无进行中的来料登记')
  })

  it('翻页事件沿用 0 基契约：点下一页 emit { page: 1, rows: 20 }', async () => {
    const w = mountTab(buildProgressOrderRows([REG_FRESH], NOW))
    await w.setProps({ pPages: 2 })

    const next = w.findAll('.ui-page-btn')[1]!
    await next.trigger('click')

    expect(w.emitted('page')?.[0]).toEqual([{ page: 1, rows: 20 }])
  })
})

// ============================================================
// MaterialToolbar：单行工具条（标题·搜索·KPI 四格·导出）
// ============================================================
const STATS = { inProgress: 6, notStarted: 4, overdueItems: 2, overallProgress: 54 }

function mountToolbar(over: Record<string, unknown> = {}) {
  return mount(MaterialToolbar, {
    props: { search: '', stats: STATS, hasData: true, canExport: true, ...over },
  })
}

describe('MaterialToolbar —— 单行工具条', () => {
  it('四格 KPI：进行中登记 / 待收货登记 / 超 30 天未收齐 / 总到货率', () => {
    const w = mountToolbar()
    const text = w.text()

    expect(text).toContain('进行中登记')
    expect(text).toContain('待收货登记')
    expect(text).toContain('超 30 天未收齐')
    expect(text).toContain('总到货率')
    expect(text).toContain('54%')
  })

  it('逾期格 >0 时数字标红，=0 时不标（重要异常才着色）', () => {
    expect(mountToolbar().find('.kpi-danger').exists()).toBe(true)
    expect(mountToolbar({ stats: { ...STATS, overdueItems: 0 } }).find('.kpi-danger').exists()).toBe(false)
  })

  it('搜索框受控：输入上抛 update:search，回车 emit search', async () => {
    const w = mountToolbar()
    const input = w.find('.mr-search-input')

    await input.setValue('易拉盖')
    expect(w.emitted('update:search')?.[0]).toEqual(['易拉盖'])

    await input.trigger('keyup.enter')
    expect(w.emitted('search')).toHaveLength(1)
  })

  it('导出按钮点击上抛 export；无数据或无权限时隐藏 KPI 行与导出', async () => {
    const w = mountToolbar()
    await w.find('.mr-export-btn').trigger('click')
    expect(w.emitted('export')).toHaveLength(1)

    expect(mountToolbar({ hasData: false }).find('.mr-export-btn').exists()).toBe(false)
    expect(mountToolbar({ canExport: false }).find('.mr-export-btn').exists()).toBe(false)
    expect(mountToolbar({ hasData: false }).find('.kpi-item').exists()).toBe(false)
  })

  it('KPI 数值千分位（12,840 量级一眼可辨）', () => {
    const w = mountToolbar({ stats: { inProgress: 12840, notStarted: 0, overdueItems: 0, overallProgress: 0 } })

    expect(w.text()).toContain('12,840')
  })
})
