/**
 * /material 来料进度改版的结构断言（2026-11-08：表格 → 订单卡片）。
 *
 * 本机开不了浏览器预览，排版靠人眼实测；但「同单合并 / 供应商块默认展开 /
 * 三级层级 / 四档状态词 / 逾期 30 天口径 / 客户端搜索与本页筛选」是结构事实，在此固化。
 *
 * 设计要点：
 *  · 一行 = 一张订单卡（同单多条登记合并，登记内按明细供应商拆块）
 *  · 供应商块默认展开（collapse 语义反转：记"已收起"集合）
 *  · 订单头摘要 = 供应商数 / 待收项数 / 逾期项数 + 总进度（原独立"总进度"列已并入）
 *  · 供应商行与物料行共用列轨道，状态四档同时给色与词
 *  · 逾期口径与后端 stats/distribution 完全一致：登记日期 < 今天-30 且未收齐
 *  · KPI 四格：进行中登记 / 待收货登记 / 逾期物料 / 总到货率（全局 stats）
 *  · 搜索与本页筛选均为客户端过滤（订单号/客户/产品/供应商/物料名）
 */
import { describe, it, expect } from 'vitest'
import { nextTick } from 'vue'
import { mount } from '@vue/test-utils'

import {
  buildProgressOrderRows,
  filterProgressRows,
  type ProgressOrderRow,
} from '@/views/material/composables/useMaterialRegistrations'
import SupplierGroupCard from '@/views/material/components/SupplierGroupCard.vue'
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
// 供应商块组件：默认展开 · 状态词 · 列轨道对齐
// ============================================================
const GROUP = buildProgressOrderRows([REG_OVERDUE, REG_FRESH], NOW)

function mountGroup(props: Record<string, unknown> = {}) {
  return mount(SupplierGroupCard, {
    props: {
      group: GROUP[0]!.groups[0]!, // 佳宝：逾期 pending 组
      collapsed: false,
      ...props,
    },
  })
}

/** 造一个指定到货量与逾期状态的供应商组 */
function mkGroup(received: number, ordered: number, overdue: boolean) {
  return buildProgressOrderRows([reg({
    purchase_order_no: 'PO-T',
    registration_date: overdue ? '2026-08-01' : '2026-09-01',
    items: [{ id: 1, material_name: '测试料', specification: '', material_category: 'main', ordered_quantity: ordered, received_quantity: received, remaining_quantity: ordered - received, progress: ordered ? Math.round(received / ordered * 100) : 0, unit: 'kg' }],
  })], NOW)[0]!.groups[0]!
}

describe('SupplierGroupCard —— 供应商块', () => {
  it('默认展开：不点击就能看到物料行（病灶①）', () => {
    const w = mountGroup()

    expect(w.findAll('.mr-mat')).toHaveLength(1)
    expect(w.text()).toContain('浓缩苹果汁')
  })

  it('组头显示供应商名 · 已到项数 · 进度条与百分比', () => {
    const w = mountGroup({ group: GROUP[1]!.groups[0] }) // 华源 30%

    expect(w.find('.mr-grp-title').text()).toBe('华源')
    expect(w.find('.mr-grp-count').text()).toContain('0/1 项已到')
    expect(w.find('.mr-grp-pct').text()).toContain('30%')
    expect(w.find('.mr-grp-bar').exists()).toBe(true)
  })

  it('四档状态同时给色与词：未开始 / 进行中 / 已到齐 / 逾期', () => {
    const cases: Array<[number, number, boolean, string, string]> = [
      [0, 100, false, 'st-pending', '未开始'],
      [30, 100, false, 'st-ongoing', '进行中'],
      [100, 100, false, 'st-done', '已到齐'],
      [30, 100, true, 'st-overdue', '逾期'],
    ]
    for (const [received, ordered, overdue, cls, text] of cases) {
      const w = mountGroup({ group: mkGroup(received, ordered, overdue) })
      expect(w.find('.mr-group').classes()).toContain(cls)
      expect(w.find('.mr-chip').text()).toBe(text)
    }
  })

  it('逾期组：物料行带文字徽标（不依赖颜色单独传达）', () => {
    const w = mountGroup()

    expect(w.find('.mr-mat.is-overdue').exists()).toBe(true)
    expect(w.find('.mr-flag').text()).toBe('逾期')
  })

  it('物料行数量千分位 + 单位：1,500 / 5,000 只', () => {
    const w = mountGroup({ group: GROUP[1]!.groups[0] })

    expect(w.find('.mr-mat-qty').text()).toContain('1,500 / 5,000')
    expect(w.find('.mr-mat-qty').text()).toContain('只')
  })

  it('物料条按状态着色：未动琥珀 / 进行中蓝 / 已到齐绿 / 逾期红', () => {
    const fillOf = (received: number, ordered: number, overdue: boolean) =>
      mountGroup({ group: mkGroup(received, ordered, overdue) }).find('.mr-mat-bar i').classes()

    expect(fillOf(0, 100, false)).toContain('fill-zero')
    expect(fillOf(30, 100, false)).toContain('fill-ongoing')
    expect(fillOf(100, 100, false)).toContain('fill-done')
    expect(fillOf(30, 100, true)).toContain('fill-overdue')
  })

  it('点击整行 emit toggle；键盘 Enter / 空格同样 emit（可键盘操作）', async () => {
    const w = mountGroup()

    await w.find('.mr-grp-head').trigger('click')
    await w.find('.mr-grp-head').trigger('keydown.enter')
    await w.find('.mr-grp-head').trigger('keydown.space')

    expect(w.emitted('toggle')).toHaveLength(3)
  })

  it('头部 aria-expanded 跟随收起状态，aria-label 含状态与项数', () => {
    const open = mountGroup()
    expect(open.find('.mr-grp-head').attributes('aria-expanded')).toBe('true')
    expect(open.find('.mr-grp-head').attributes('aria-label')).toContain('逾期')

    const shut = mountGroup({ collapsed: true })
    expect(shut.find('.mr-grp-head').attributes('aria-expanded')).toBe('false')
    expect(shut.find('.mr-grp-head').attributes('aria-label')).toContain('已收起')
  })

  it('collapsed=true 时物料行不渲染', () => {
    expect(mountGroup({ collapsed: true }).find('.mr-mat').exists()).toBe(false)
  })
})

// ============================================================
// ProgressTab：订单卡 · 供应商分组 · 本页筛选 · 分页
// ============================================================
function mountTab(rows: ProgressOrderRow[], over: Record<string, unknown> = {}) {
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
      ...over,
    },
  })
}

/** 同一订单两条登记（佳宝已收齐 + 华源部分到货） */
const MERGED_ORDER = buildProgressOrderRows([
  { ...REG_OVERDUE, purchase_order_no: 'PO-M', supplier_name: '佳宝', registration_date: '2026-09-01', items: REG_OVERDUE.items!.map((i) => ({ ...i, ordered_quantity: 5000, received_quantity: 5000, remaining_quantity: 0, progress: 100 })) },
  { ...REG_FRESH, purchase_order_no: 'PO-M', supplier_name: '华源' },
], NOW)

describe('ProgressTab —— 订单卡与供应商分组', () => {
  it('一行 = 一张订单卡：同单多条登记只出现一张卡', () => {
    const w = mountTab(MERGED_ORDER)

    expect(w.findAll('.mr-order')).toHaveLength(1)
    expect(w.findAll('.mr-group')).toHaveLength(2)
    expect(w.find('.mr-order-no').text()).toBe('PO-M')
  })

  it('订单头摘要：供应商数 · 待收项数 · 逾期项数', () => {
    const w = mountTab(buildProgressOrderRows([REG_OVERDUE], NOW))
    const sums = w.findAll('.mr-sum').map((s) => s.text())

    expect(sums).toContain('1 家供应商')
    expect(sums).toContain('待收 1 项')
    expect(sums).toContain('逾期 1 项')
  })

  it('无逾期订单不渲染逾期摘要（重要异常才着色）', () => {
    const w = mountTab(buildProgressOrderRows([REG_FRESH], NOW))

    expect(w.find('.mr-sum.is-danger').exists()).toBe(false)
  })

  it('供应商块默认展开：挂载即见物料行，无需点击（病灶①）', () => {
    const w = mountTab(buildProgressOrderRows([REG_FRESH], NOW))

    expect(w.find('.mr-mat').exists()).toBe(true)
  })

  it('点供应商行收起后，同组物料行隐藏', async () => {
    const w = mountTab(buildProgressOrderRows([REG_FRESH], NOW))

    await w.find('.mr-grp-head').trigger('click')
    await nextTick()

    expect(w.find('.mr-mat').exists()).toBe(false)
  })

  it('本页筛选「有逾期」只保留存在逾期物料的订单', async () => {
    const w = mountTab(buildProgressOrderRows([REG_OVERDUE, REG_FRESH], NOW))
    expect(w.findAll('.mr-order')).toHaveLength(2)

    await w.findAll('.mr-filter')[1]!.trigger('click')

    expect(w.findAll('.mr-order')).toHaveLength(1)
    expect(w.find('.mr-order-no').text()).toBe('PO-OLD')
  })

  it('筛选无命中时给「本页」口径的空态（不是全局无数据）', async () => {
    const w = mountTab(buildProgressOrderRows([REG_FRESH], NOW))

    await w.findAll('.mr-filter')[1]!.trigger('click')

    expect(w.findAll('.mr-order')).toHaveLength(0)
    expect(w.text()).toContain('本页没有')
  })

  it('showSearchEmpty=true 时渲染"当前页无匹配"空态（搜索仅作用于当前页）', async () => {
    const w = mountTab([])
    await w.setProps({ showSearchEmpty: true })

    expect(w.text()).toContain('当前页无匹配')
  })

  it('无任何数据时给基础空态', () => {
    expect(mountTab([]).text()).toContain('暂无进行中的来料登记')
  })

  it('分页按后端登记总数渲染，翻页按 1 基转 0 基上抛', async () => {
    const w = mountTab(buildProgressOrderRows([REG_FRESH], NOW), { pCount: 42, pPages: 3, pPage: 2 })

    expect(w.find('.ui-pagination').exists()).toBe(true)
    expect(w.text()).toContain('共 42')

    const next = w.findAll('.ui-page-btn')[1]!
    await next.trigger('click')

    expect(w.emitted('page')?.[0]).toEqual([{ page: 2, rows: 20 }])
  })

  it('首次加载渲染骨架屏，不渲染空态', () => {
    const w = mountTab([], { pIsLoading: true, pCount: 0 })

    expect(w.find('.mr-skel').exists()).toBe(true)
    expect(w.find('.mr-empty').exists()).toBe(false)
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

describe('MaterialToolbar —— 单行工具条（病灶④⑤）', () => {
  it('四格 KPI：进行中登记 / 待收货登记 / 逾期物料 / 总到货率', () => {
    const w = mountToolbar()
    const text = w.text()

    expect(text).toContain('进行中登记')
    expect(text).toContain('待收货登记')
    expect(text).toContain('逾期物料')
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
