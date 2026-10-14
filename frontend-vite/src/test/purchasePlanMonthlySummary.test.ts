/**
 * 「月度汇总」Tab —— 覆盖这次配套整理：
 * 客户 chips 带计划量、分布面板并入、数字列千分位与配色分级、排序/分页事件仍照常上抛。
 */
import { describe, it, expect } from 'vitest'
import { mount, type VueWrapper } from '@vue/test-utils'
import PurchasePlanMonthlySummary from '@/views/purchase-plan/components/PurchasePlanMonthlySummary.vue'
import type { CustSumItem, SkuRow } from '@/views/purchase-plan/components/types'

function cust(name: string, plan: number, shipped: number, remain: number, id = 1): CustSumItem {
  return { customer_id: id, customer_name: name, plan_qty: plan, inventory_qty: 0, produced_qty: shipped, remaining_qty: remain, warning_count: 0 }
}

function sku(over: Partial<SkuRow> = {}): SkuRow {
  const plan = over.plan_qty ?? 100
  const shipped = over.produced_qty ?? 0
  return {
    barcode: '6978946330588',
    product_name: '企鹅',
    plan_qty: plan,
    produced_qty: shipped,
    remain_qty: plan - shipped,
    customer_name: 'MINISO国际',
    _pct: plan > 0 ? Math.round(shipped / plan * 100) : 0,
    _odd: false,
    ...over,
  }
}

const CUSTOMERS = [
  cust('MINISO国际', 12400, 8000, 4400, 1),
  cust('网易严选', 3316, 3316, 0, 2),
]
const SKUS = [
  sku({ plan_qty: 6000, produced_qty: 3400 }),
  sku({ product_name: '企鹅企鹅企鹅', plan_qty: 1500, produced_qty: 1500 }),
  sku({ product_name: '变形金刚', plan_qty: 2000, produced_qty: 0 }),
]

function mountSummary(over: Record<string, unknown> = {}): VueWrapper {
  return mount(PurchasePlanMonthlySummary, {
    props: {
      loading: false,
      error: false,
      fetching: false,
      hasData: true,
      customers: CUSTOMERS,
      factory: '东莞',
      custFilter: '',
      sortedSkuList: SKUS,
      paginatedSkuList: SKUS,
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

describe('PurchasePlanMonthlySummary 客户 chips', () => {
  it('chips 带上各客户计划量，全部 = 合计', () => {
    const w = mountSummary()
    const chips = w.findAll('.sp-chip')
    expect(chips).toHaveLength(3)
    expect(chips[0]?.text()).toContain('全部')
    expect(chips[0]?.text()).toContain('15,716')
    expect(chips[1]?.text()).toContain('MINISO国际')
    expect(chips[1]?.text()).toContain('12,400')
    expect(chips[2]?.text()).toContain('3,316')
  })

  it('点某客户 chip 上抛筛选；再点一次取消（空串）', async () => {
    const w = mountSummary()
    await w.findAll('.sp-chip')[1]?.trigger('click')
    expect(w.emitted('update:custFilter')).toEqual([['MINISO国际']])
  })

  it('已选中时该 chip 高亮，再点回空串', async () => {
    const w = mountSummary({ custFilter: '网易严选' })
    const chip = w.findAll('.sp-chip')[2]
    expect(chip?.classes()).toContain('sp-chip-active')
    await chip?.trigger('click')
    expect(w.emitted('update:custFilter')).toEqual([['']])
  })
})

describe('PurchasePlanMonthlySummary 按工厂汇总卡片', () => {
  it('任意工厂 Tab 下都渲染按工厂汇总卡片', () => {
    expect(mountSummary({ factory: '东莞' }).find('.sp-fsum').exists()).toBe(true)
    expect(mountSummary({ factory: '湖北' }).find('.sp-fsum').exists()).toBe(true)
  })
})

describe('PurchasePlanMonthlySummary 表格与面板', () => {
  it('渲染传入的分页行，列头含进度', () => {
    const w = mountSummary()
    expect(w.findAll('.sp-sku-table tbody tr')).toHaveLength(3)
    expect(w.find('.sp-sku-table thead').text()).toContain('计划数量')
    expect(w.find('.sp-sku-table thead').text()).toContain('待生产')
    expect(w.find('.sp-sku-table thead').text()).toContain('进度')
  })

  it('表头有「数量（件）」分组层', () => {
    const w = mountSummary()
    expect(w.find('.sp-sku-table thead').text()).toContain('数量（件）')
  })

  it('数字列头右对齐（.th-num 共 3 个）', () => {
    const w = mountSummary()
    expect(w.findAll('.sp-sku-table .th-num')).toHaveLength(3)
  })

  it('数字列走千分位', () => {
    expect(mountSummary().find('.sp-sku-table tbody').text()).toContain('6,000')
  })

  it('已生产配色分级：0 红 / 产满 绿 / 部分 琥珀', () => {
    const w = mountSummary()
    const rows = w.findAll('.sp-sku-table tbody tr')
    expect(rows[0]?.findAll('.td-num')[1]?.classes()).toContain('td-part')
    expect(rows[1]?.findAll('.td-num')[1]?.classes()).toContain('td-done')
    expect(rows[2]?.findAll('.td-num')[1]?.classes()).toContain('td-zero')
  })

  it('点表头上抛排序，点行上抛明细', async () => {
    const w = mountSummary()
    await w.findAll('.th-sortable')[0]?.trigger('click')
    expect(w.emitted('toggle-sku-sort')).toEqual([['plan']])
    await w.findAll('.sp-sku-table tbody tr')[0]?.trigger('click')
    expect(w.emitted('open-sku-detail')).toHaveLength(1)
  })

  it('客户出货分布面板随 Tab 一起渲染（原在日 Tab 右栏）', () => {
    const w = mountSummary()
    expect(w.find('.sp-dist').exists()).toBe(true)
    expect(w.findAll('.sp-dist-row')).toHaveLength(2)
  })

  it('无数据时显示空态，不出表格', () => {
    const w = mountSummary({ hasData: false })
    expect(w.text()).toContain('本月暂无数据')
    expect(w.find('.sp-sku-table').exists()).toBe(false)
  })

  it('加载失败时给出重试入口并上抛 refetch', async () => {
    const w = mountSummary({ error: true })
    expect(w.text()).toContain('加载失败')
    await w.find('.sp-retry-btn').trigger('click')
    expect(w.emitted('refetch')).toHaveLength(1)
  })
})
