/**
 * 排产日历月视图的挂载测试 —— 把这次重设计的四条诉求写成断言。
 *
 * 本机开不了浏览器预览，布局靠人眼验；但「整月一屏 / 明细不截断 / 右栏双态 / 点击路由」
 * 这几条是结构断言，可在此固化。用假 Date 钉住「今天」（2026-09-28），
 * 否则逾期/临期的判定会随真实时钟漂移。
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { mount, type VueWrapper } from '@vue/test-utils'
import PurchasePlanDailyTab from '@/views/purchase-plan/components/PurchasePlanDailyTab.vue'
import type { Row, SkuDateItem } from '@/views/purchase-plan/components/types'

const TODAY = '2026-09-28T10:00:00'

function row(date: string, over: Partial<Row> = {}): Row {
  return {
    date,
    _dayNum: Number(date.slice(8)),
    _weekday: '一',
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

// 2026-09 的排产日：02 已完成 / 08 逾期（5 产品 3 客户）/ 29 临期
const ROWS: Row[] = [
  row('2026-09-02', { totalQty: 2666, customerCount: 2, planCount: 3, _producedPct: 100, _producedCount: 3, customerNames: ['MINISO国际'] }),
  row('2026-09-08', {
    totalQty: 5000, customerCount: 3, planCount: 5, _producedPct: 64, _pendingCount: 2,
    customerNames: ['MINISO国际', 'TOP TOY', '网易严选'],
  }),
  row('2026-09-29', { totalQty: 2200, customerCount: 2, planCount: 2, _producedPct: 0, _pendingCount: 2, customerNames: ['MINISO国际'] }),
]

// 09-08 的 5 个产品分属 3 家客户 —— 旧的卡片版按「4 行产品预算」会把第 5 个折叠掉
const SKU_INDEX: Record<string, SkuDateItem[]> = {
  'MINISO国际|企鹅': [item('2026-09-08', 2000, 'MINISO国际', 'pending')],
  'MINISO国际|企鹅企鹅企鹅': [item('2026-09-08', 1500, 'MINISO国际', 'pending')],
  'MINISO国际|变形金刚': [item('2026-09-08', 500, 'MINISO国际', 'completed')],
  'TOP TOY|10寸仓鼠毛绒公仔(粉色)': [item('2026-09-08', 400, 'TOP TOY', 'pending')],
  '网易严选|妹妹二代': [item('2026-09-08', 600, '网易严选', 'pending')],
  'MINISO国际|企鹅(29日)': [item('2026-09-29', 1800, 'MINISO国际', 'pending')],
}

function mountTab(over: { sel?: string } = {}): VueWrapper {
  return mount(PurchasePlanDailyTab, {
    props: {
      y: 2026,
      m: 9,
      isLoading: false,
      isError: false,
      isFetching: false,
      rows: ROWS,
      filtered: ROWS,
      skuDateIndex: SKU_INDEX,
      sel: over.sel ?? '',
      factory: '东莞',
    },
    global: {
      stubs: {
        FontAwesomeIcon: { template: '<i />' },
        UiSpinner: { template: '<i />' },
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

describe('排产日历：整月一屏', () => {
  it('2026-09 铺出 35 格（5 行），无排产的日期也占位显示', () => {
    const w = mountTab()
    expect(w.findAll('.sp-cell')).toHaveLength(35)
    // 3 个排产日 → 其余 32 格是「当月无排产」的空白格，不是被省略掉
    expect(w.findAll('.sp-cell-empty')).toHaveLength(32)
  })

  it('有排产的格子只显示当日总量，不再有客户/产品数元信息与进度条', () => {
    const cell = cellOf(mountTab(), 8)
    expect(cell?.classes()).toContain('sp-cell-danger')
    expect(cell?.find('.sp-qty').text()).toContain('5,000')
    expect(cell?.find('.sp-cell-meta').exists()).toBe(false)
    expect(cell?.find('.sp-bar').exists()).toBe(false)
  })

  it('逾期/临期/完成三种状态在格子上各有标记', () => {
    const w = mountTab()
    expect(cellOf(w, 8)?.find('.sp-mark').text()).toBe('延期 20天')
    expect(cellOf(w, 29)?.find('.sp-mark').text()).toBe('临期 1天')
    expect(cellOf(w, 2)?.find('.sp-mark').text()).toBe('✓ 完成')
  })

  it('今天（09-28）带 today 标记', () => {
    const w = mountTab()
    expect(cellOf(w, 28)?.classes()).toContain('sp-cell-today')
    expect(cellOf(w, 28)?.text()).toContain('今天')
  })
})

describe('排产日历：点击路由', () => {
  it('点有排产的格子 → 上抛选中日期', async () => {
    const w = mountTab()
    await cellOf(w, 8)?.trigger('click')
    expect(w.emitted('update:sel')).toEqual([['2026-09-08']])
  })

  it('点空白格不产生选中（无排产的日子没有明细可看）', async () => {
    const w = mountTab()
    await cellOf(w, 9)?.trigger('click')
    expect(w.emitted('update:sel')).toBeUndefined()
  })

  it('再次点选中的那天 → 上抛空串（取消选中）', async () => {
    const w = mountTab({ sel: '2026-09-08' })
    await cellOf(w, 8)?.trigger('click')
    expect(w.emitted('update:sel')).toEqual([['']])
  })
})

describe('右栏双态：风险清单 ⇄ 当日明细', () => {
  it('未选中时显示风险清单，只列逾期与临期两天', () => {
    const w = mountTab()
    expect(w.find('.sp-risk-list').exists()).toBe(true)
    expect(w.find('.sp-detail').exists()).toBe(false)
    const rows = w.findAll('.sp-risk-row')
    expect(rows).toHaveLength(2)
    expect(rows[0]?.text()).toContain('09/08')
    expect(rows[0]?.text()).toContain('延期 20天')
    expect(rows[1]?.text()).toContain('临期 1天')
  })

  it('选中某天时右栏切换为当日明细，并给回风险清单的入口', () => {
    const w = mountTab({ sel: '2026-09-08' })
    expect(w.find('.sp-detail').exists()).toBe(true)
    expect(w.find('.sp-risk-list').exists()).toBe(false)
    expect(w.find('.sp-rail-clear').text()).toBe('返回风险清单')
  })

  it('当日明细列出全部 5 个产品、3 家客户 —— 不截断', () => {
    const w = mountTab({ sel: '2026-09-08' })
    expect(w.findAll('.sp-prod-row')).toHaveLength(5)
    expect(w.findAll('.sp-group')).toHaveLength(3)
    expect(w.find('.sp-detail-meta').text()).toContain('5,000')
    expect(w.find('.sp-detail-meta').text()).toContain('3 家客户')
    expect(w.find('.sp-detail-meta').text()).toContain('5 个产品')
  })

  it('产品行带该客户该产品当日的出货状态', () => {
    const w = mountTab({ sel: '2026-09-08' })
    const texts = w.findAll('.sp-prod-row').map(r => r.text())
    expect(texts.some(t => t.includes('变形金刚') && t.includes('已生产'))).toBe(true)
    expect(texts.some(t => t.includes('企鹅企鹅企鹅') && t.includes('待生产'))).toBe(true)
  })

  it('点风险清单里的一天 → 上抛该日期', async () => {
    const w = mountTab()
    await w.findAll('.sp-risk-row')[1]?.trigger('click')
    expect(w.emitted('update:sel')).toEqual([['2026-09-29']])
  })
})
