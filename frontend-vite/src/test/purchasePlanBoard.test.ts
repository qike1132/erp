/**
 * 出货计划单视图主体（方案B，2026-11-28 owner 拍板）的挂载测试。
 * 原排产日历/月度汇总两 Tab 合并成一块 Board，这里固化本次重设计的核心诉求：
 * 月历格子带「谁在出货」（客户数·SKU数+占比条）、风险压成一行条、
 * 客户 chips 与 SKU 表并入左列、右列恒为当日明细主区。
 * 用假 Date 钉住「今天」（2026-09-28），否则逾期/临期判定随真实时钟漂移。
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { mount, type VueWrapper } from '@vue/test-utils'
import PurchasePlanBoard from '@/views/purchase-plan/components/PurchasePlanBoard.vue'
import type { CustSumItem, RiskItem, Row, SkuDateItem, SkuRow } from '@/views/purchase-plan/components/types'

const TODAY = '2026-09-28T10:00:00'

function row(date: string, over: Partial<Row> = {}): Row {
  return {
    date,
    _dayNum: Number(date.slice(8)),
    _weekday: '二',
    customerCount: 1,
    planCount: 1,
    totalQty: 0,
    _isPeak: false,
    _producedCount: 0,
    _pendingCount: 0,
    _producedPct: 0,
    customerNames: [],
    _fullDate: date,
    ...over,
  }
}

function item(date: string, qty: number, customer: string, status: string): SkuDateItem {
  return { date, day: Number(date.slice(8)), weekday: '二', qty, customer, status }
}

function cust(name: string, plan: number, id: number): CustSumItem {
  return { customer_id: id, customer_name: name, plan_qty: plan, inventory_qty: 0, produced_qty: 0, remaining_qty: plan, warning_count: 0 }
}

function skuRow(over: Partial<SkuRow> = {}): SkuRow {
  const plan = over.plan_qty ?? 100
  const produced = over.produced_qty ?? 0
  return {
    barcode: '6978946330588',
    product_name: '企鹅',
    plan_qty: plan,
    produced_qty: produced,
    remain_qty: plan - produced,
    customer_name: 'MINISO国际',
    _pct: plan > 0 ? Math.round(produced / plan * 100) : 0,
    _odd: false,
    ...over,
  }
}

// 2026-09 的排产日：02 已完成 / 08 逾期（5 产品 3 客户）/ 29 临期
const ROWS: Row[] = [
  row('2026-09-02', { totalQty: 2666, customerCount: 2, planCount: 3, _producedPct: 100, _producedCount: 3, customerNames: ['MINISO国际'] }),
  row('2026-09-08', {
    totalQty: 5000, customerCount: 3, planCount: 5, _producedPct: 64, _pendingCount: 2,
    customerNames: ['MINISO国际', 'TOP TOY', '网易严选'],
  }),
  row('2026-09-29', { totalQty: 2200, customerCount: 2, planCount: 2, _producedPct: 0, _pendingCount: 2, customerNames: ['MINISO国际'] }),
]

// 09-08 的 5 个产品分属 3 家客户 —— 方案B 的格子元信息应报「3 客户 · 5 SKU」
const SKU_INDEX: Record<string, SkuDateItem[]> = {
  'MINISO国际|企鹅': [item('2026-09-08', 2000, 'MINISO国际', 'pending')],
  'MINISO国际|企鹅企鹅企鹅': [item('2026-09-08', 1500, 'MINISO国际', 'pending')],
  'MINISO国际|变形金刚': [item('2026-09-08', 500, 'MINISO国际', 'completed')],
  'TOP TOY|10寸仓鼠毛绒公仔(粉色)': [item('2026-09-08', 400, 'TOP TOY', 'pending')],
  '网易严选|妹妹二代': [item('2026-09-08', 600, '网易严选', 'pending')],
  'MINISO国际|企鹅(29日)': [item('2026-09-29', 1800, 'MINISO国际', 'pending')],
}

const CUSTOMERS: CustSumItem[] = [
  cust('MINISO国际', 12400, 1),
  cust('TOP TOY', 6400, 2),
]

const RISKS: RiskItem[] = [
  { date: '2026-09-08', qty: 5000, cust: 'MINISO国际', kind: 'overdue', lbl: '延期 20天' },
  { date: '2026-09-29', qty: 2200, cust: 'MINISO国际', kind: 'due', lbl: '临期 1天' },
]

const SKU_ROWS: SkuRow[] = [
  skuRow({ plan_qty: 6000, produced_qty: 3400 }),
  skuRow({ product_name: '变形金刚', plan_qty: 2000, produced_qty: 0, customer_name: 'TOP TOY' }),
]

function mountBoard(over: Record<string, unknown> = {}): VueWrapper {
  return mount(PurchasePlanBoard, {
    props: {
      y: 2026,
      m: 9,
      isLoading: false,
      isError: false,
      isFetching: false,
      rows: ROWS,
      filtered: ROWS,
      skuDateIndex: SKU_INDEX,
      sel: '',
      customers: CUSTOMERS,
      riskItems: RISKS,
      custFilter: '',
      sortedSkuList: SKU_ROWS,
      paginatedSkuList: SKU_ROWS,
      skuPage: 1,
      skuTotalPages: 1,
      skuSortField: 'customer',
      skuSortDir: 'desc',
      ...over,
    },
    global: {
      stubs: {
        FontAwesomeIcon: { template: '<i />' },
        UiSpinner: { template: '<i />' },
        UiPagination: { template: '<div class="stub-pager" />' },
      },
    },
  })
}

const cellOf = (w: VueWrapper, day: number) =>
  w.findAll('.sp-cell').find(c => c.find('.sp-day').text() === String(day))

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'] })
  vi.setSystemTime(new Date(TODAY))
})

afterEach(() => {
  vi.useRealTimers()
})

describe('排产月历：整月一屏', () => {
  it('2026-09 铺出 35 格（5 行），无排产的日期也占位显示', () => {
    const w = mountBoard()
    expect(w.findAll('.sp-cell')).toHaveLength(35)
    expect(w.findAll('.sp-cell-empty')).toHaveLength(32)
  })

  it('格子带当日总量与「谁在出货」元信息：客户数 · 去重 SKU 数 + 客户占比条', () => {
    const cell = cellOf(mountBoard(), 8)
    expect(cell?.classes()).toContain('sp-cell-danger')
    expect(cell?.find('.sp-qty').text()).toContain('5,000')
    expect(cell?.find('.sp-cell-meta').text()).toContain('3 客户')
    expect(cell?.find('.sp-cell-meta').text()).toContain('5 SKU')
    expect(cell?.findAll('.sp-share-bar i')).toHaveLength(3)
  })

  it('逾期/临期/完成三种状态在格子上各有标记', () => {
    const w = mountBoard()
    expect(cellOf(w, 8)?.find('.sp-mark').text()).toBe('延期 20天')
    expect(cellOf(w, 29)?.find('.sp-mark').text()).toBe('临期 1天')
    expect(cellOf(w, 2)?.find('.sp-mark').text()).toBe('✓ 完成')
  })

  it('今天（09-28）带 today 标记', () => {
    const w = mountBoard()
    expect(cellOf(w, 28)?.classes()).toContain('sp-cell-today')
    expect(cellOf(w, 28)?.text()).toContain('今天')
  })
})

describe('排产月历：点击路由', () => {
  it('点有排产的格子 → 上抛选中日期', async () => {
    const w = mountBoard()
    await cellOf(w, 8)?.trigger('click')
    expect(w.emitted('update:sel')).toEqual([['2026-09-08']])
  })

  it('点空白格不产生选中（无排产的日子没有明细可看）', async () => {
    const w = mountBoard()
    await cellOf(w, 9)?.trigger('click')
    expect(w.emitted('update:sel')).toBeUndefined()
  })

  it('再次点选中的那天 → 上抛空串（取消选中）', async () => {
    const w = mountBoard({ sel: '2026-09-08' })
    await cellOf(w, 8)?.trigger('click')
    expect(w.emitted('update:sel')).toEqual([['']])
  })
})

describe('风险条：月历下方一行 chips', () => {
  it('只列逾期与临期两天，含日号/标签/件数', () => {
    const w = mountBoard()
    const chips = w.findAll('.sp-risk-chip')
    expect(chips).toHaveLength(2)
    expect(chips[0]?.text()).toContain('09/08')
    expect(chips[0]?.text()).toContain('延期 20天')
    expect(chips[0]?.text()).toContain('5,000件')
    expect(chips[1]?.text()).toContain('09/29')
    expect(chips[1]?.text()).toContain('临期 1天')
  })

  it('点风险条目 → 上抛选中该日', async () => {
    const w = mountBoard()
    await w.findAll('.sp-risk-chip')[0]?.trigger('click')
    expect(w.emitted('update:sel')).toEqual([['2026-09-08']])
  })

  it('无风险时明确说没事，不渲染 chips', () => {
    const w = mountBoard({ riskItems: [] })
    expect(w.findAll('.sp-risk-chip')).toHaveLength(0)
    expect(w.find('.sp-risk-ok').text()).toContain('本月无逾期与临期')
  })
})

describe('右列：当日明细主区', () => {
  it('未选中时给引导提示（默认今天选中后一般不可见）', () => {
    const w = mountBoard()
    expect(w.find('.sp-rail-empty').exists()).toBe(true)
    expect(w.find('.sp-detail').exists()).toBe(false)
  })

  it('选中某天 → 客户分组明细：组头带小计，产品行带数量与出货状态', () => {
    const w = mountBoard({ sel: '2026-09-08' })
    const groups = w.findAll('.sp-group')
    expect(groups).toHaveLength(3)
    expect(groups[0]?.text()).toContain('MINISO国际')
    expect(groups[0]?.text()).toContain('4,000')
    const rows = w.findAll('.sp-prod-row')
    expect(rows).toHaveLength(5)
    expect(w.find('.sp-detail').text()).toContain('已出清')
    expect(w.find('.sp-detail').text()).toContain('未出')
    expect(w.find('.sp-rail-empty').exists()).toBe(false)
  })
})

describe('左列下部：客户 chips + SKU 月度统计（原「月度汇总」Tab 并入）', () => {
  it('客户 chips：全部带合计，各客户带月计划量', () => {
    const w = mountBoard()
    const chips = w.findAll('.sp-chip')
    expect(chips).toHaveLength(3)
    expect(chips[0]?.text()).toContain('全部')
    expect(chips[0]?.text()).toContain('18,800')
    expect(chips[1]?.text()).toContain('MINISO国际')
    expect(chips[1]?.text()).toContain('12,400')
  })

  it('点客户 chip 上抛筛选；再点一次取消（空串）', async () => {
    const w = mountBoard()
    await w.findAll('.sp-chip')[1]?.trigger('click')
    expect(w.emitted('update:custFilter')).toEqual([['MINISO国际']])
  })

  it('已选中时该 chip 高亮，再点回空串', async () => {
    const w = mountBoard({ custFilter: 'TOP TOY' })
    const chip = w.findAll('.sp-chip')[2]
    expect(chip?.classes()).toContain('sp-chip-active')
    await chip?.trigger('click')
    expect(w.emitted('update:custFilter')).toEqual([['']])
  })

  it('SKU 表渲染传入的分页行，列头含数量分组与进度', () => {
    const w = mountBoard()
    expect(w.findAll('.sp-sku-table tbody tr')).toHaveLength(2)
    expect(w.find('.sp-sku-table thead').text()).toContain('计划数量')
    expect(w.find('.sp-sku-table thead').text()).toContain('待生产')
    expect(w.find('.sp-sku-table thead').text()).toContain('数量（件）')
    expect(w.find('.sp-sku-table tbody').text()).toContain('6,000')
  })

  it('点表头上抛排序，点行上抛明细', async () => {
    const w = mountBoard()
    await w.findAll('.th-sortable')[0]?.trigger('click')
    expect(w.emitted('toggle-sku-sort')).toEqual([['plan']])
    await w.findAll('.sp-sku-table tbody tr')[0]?.trigger('click')
    expect(w.emitted('open-sku-detail')).toHaveLength(1)
  })

  it('导出SKU 按钮上抛 export-sku（SKU 月度统计 CSV 入口随区块走）', async () => {
    const w = mountBoard()
    await w.find('.sp-export-sku').trigger('click')
    expect(w.emitted('export-sku')).toHaveLength(1)
  })
})

describe('状态与搜索', () => {
  it('无排产时显示空态', () => {
    const w = mountBoard({ rows: [], filtered: [] })
    expect(w.text()).toContain('本月暂无出货计划')
    expect(w.find('.sp-cell').exists()).toBe(false)
  })

  it('加载失败给出重试入口并上抛 refetch', async () => {
    const w = mountBoard({ isError: true })
    expect(w.text()).toContain('加载失败')
    await w.find('.sp-retry-btn').trigger('click')
    expect(w.emitted('refetch')).toHaveLength(1)
  })

  it('搜索生效时给命中提示，未命中的格子淡化', () => {
    const w = mountBoard({ filtered: [ROWS[0]] })
    expect(w.find('.sp-search-hint').text()).toContain('搜索命中 1 个排产日')
    expect(cellOf(w, 2)?.classes()).not.toContain('sp-cell-dim')
    expect(cellOf(w, 8)?.classes()).toContain('sp-cell-dim')
    expect(cellOf(w, 29)?.classes()).toContain('sp-cell-dim')
  })
})
