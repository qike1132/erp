/**
 * 备货计划「工厂维度」的挂载/单元测试。
 *
 * 钉住三件事：
 *   1. useFactorySplit —— 本地按工厂拆分 rows / skuSummary / skuDateIndex / customers；
 *   2. PurchasePlanFactoryFilter —— 选项顺序（无「全部」）、选中态、点击 emit；
 *   3. SkuSummaryTable 工厂列。
 */
import { describe, it, expect } from 'vitest'
import { ref, computed } from 'vue'
import { mount } from '@vue/test-utils'
import { useFactorySplit } from '@/views/purchase-plan/composables/useFactorySplit'
import { orderFactories, factoryTone } from '@/views/purchase-plan/components/factoryMeta'
import PurchasePlanFactoryFilter from '@/views/purchase-plan/components/PurchasePlanFactoryFilter.vue'
import SkuSummaryTable from '@/views/purchase-plan/components/SkuSummaryTable.vue'
import type { Row, SkuRow, SkuDateItem, CustSumItem, FactoryDayAgg } from '@/views/purchase-plan/components/types'

function row(date: string, factories: Row['factories'], over: Partial<Row> = {}): Row {
  return {
    date, _dayNum: Number(date.slice(8)), _weekday: '一',
    customerCount: 1, planCount: 1, totalQty: 0, _isPeak: false,
    _producedCount: 0, _pendingCount: 0, _producedPct: 0, customerNames: [],
    _fullDate: date, factories, ...over,
  }
}

function fac(over: Partial<FactoryDayAgg> = {}): FactoryDayAgg {
  return {
    qty: 0, produced: 0, pct: 0, custN: 0, prodN: 0,
    rowN: 0, completedN: 0, pendingN: 0, custNames: [], ...over,
  }
}

const ROWS: Row[] = [
  row('2026-10-05', {
    '东莞': fac({ qty: 100, produced: 100, pct: 100, custN: 1, prodN: 1, rowN: 1, completedN: 1, custNames: ['客户甲'] }),
    '湖北': fac({ qty: 50, produced: 20, pct: 40, custN: 1, prodN: 1, rowN: 1, completedN: 0, pendingN: 1, custNames: ['客户乙'] }),
  }, { totalQty: 150, customerCount: 2, planCount: 2, _producedPct: 80, _pendingCount: 1, customerNames: ['客户甲', '客户乙'] }),
  row('2026-10-06', {
    '东莞': fac({ qty: 60, custN: 1, prodN: 1, rowN: 1, pendingN: 1, custNames: ['客户甲'] }),
  }, { totalQty: 60, customerCount: 1, planCount: 1, _producedPct: 0, _pendingCount: 1, customerNames: ['客户甲'] }),
]

const SKU: SkuRow[] = [
  { barcode: 'A', product_name: '产品A', plan_qty: 100, produced_qty: 100, remain_qty: 0, customer_name: '客户甲', factory: '东莞', _pct: 100, _odd: false },
  { barcode: 'B', product_name: '产品B', plan_qty: 50, produced_qty: 20, remain_qty: 30, customer_name: '客户甲', factory: '湖北', _pct: 40, _odd: false },
]

const IDX: Record<string, SkuDateItem[]> = {
  '客户甲|产品A': [{ date: '2026-10-05', day: 5, weekday: '一', qty: 100, customer: '客户甲', status: 'completed', factory: '东莞' }],
  '客户甲|产品B': [{ date: '2026-10-05', day: 5, weekday: '一', qty: 50, customer: '客户甲', status: 'partial', factory: '湖北' }],
}

const CUST: CustSumItem[] = [
  {
    customer_id: 1, customer_name: '客户甲', plan_qty: 150, inventory_qty: 0,
    produced_qty: 120, remaining_qty: 30, warning_count: 0,
    factories: {
      '东莞': { plan_qty: 100, inventory_qty: 0, produced_qty: 100, remaining_qty: 0, warning_count: 0 },
      '湖北': { plan_qty: 50, inventory_qty: 0, produced_qty: 20, remaining_qty: 30, warning_count: 0 },
    },
  },
]

function split(factory: string) {
  return useFactorySplit({
    factory: ref(factory),
    rows: computed(() => ROWS),
    skuSummary: computed(() => SKU),
    skuDateIndex: computed(() => IDX),
    customers: computed(() => CUST),
  })
}

describe('useFactorySplit', () => {
  it('「全部」原样透传，不改变任何数据', () => {
    const s = split('all')
    expect(s.rows.value).toHaveLength(2)
    expect(s.skuSummary.value).toHaveLength(2)
    expect(s.customers.value[0]!.plan_qty).toBe(150)
    expect(Object.keys(s.skuDateIndex.value)).toHaveLength(2)
  })

  it('按东莞拆分：日历行取该厂桶，SKU/索引/客户同步收敛', () => {
    const s = split('东莞')
    // 两天都有东莞计划
    expect(s.rows.value.map(r => r.date)).toEqual(['2026-10-05', '2026-10-06'])
    // 10-05 的东莞桶：qty 100 / 完成率 100 / 未完成 0（而非整天的 150/80/1）
    const r0 = s.rows.value[0]!
    expect(r0.totalQty).toBe(100)
    expect(r0._producedPct).toBe(100)
    expect(r0._pendingCount).toBe(0)
    expect(r0.customerCount).toBe(1)
    // 客户名收敛到本厂：湖北的「客户乙」不得出现在东莞视图（导出/风险清单/搜索都读它）
    expect(r0.customerNames).toEqual(['客户甲'])
    // SKU 只剩东莞的产品
    expect(s.skuSummary.value.map(x => x.product_name)).toEqual(['产品A'])
    // 索引只剩东莞那个键
    expect(Object.keys(s.skuDateIndex.value)).toEqual(['客户甲|产品A'])
    // 客户取东莞桶
    const c0 = s.customers.value[0]!
    expect(c0.plan_qty).toBe(100)
    expect(c0.produced_qty).toBe(100)
  })

  it('按湖北拆分：只保留有湖北计划的日期', () => {
    const s = split('湖北')
    expect(s.rows.value.map(r => r.date)).toEqual(['2026-10-05'])
    const r0 = s.rows.value[0]!
    expect(r0.totalQty).toBe(50)
    expect(r0._producedPct).toBe(40)
    expect(s.skuSummary.value.map(x => x.product_name)).toEqual(['产品B'])
    expect(s.customers.value[0]!.plan_qty).toBe(50)
  })

  it('选一个当月不存在的工厂：四类出口都为空，不报错', () => {
    const s = split('未标注')
    expect(s.rows.value).toEqual([])
    expect(s.skuSummary.value).toEqual([])
    expect(s.skuDateIndex.value).toEqual({})
    expect(s.customers.value).toEqual([])
  })

  it('工厂计数与总量按当日各厂桶累加', () => {
    const s = split('all')
    expect(s.availableFactories.value.sort()).toEqual(['东莞', '湖北'])
    expect(s.factoryTotals.value).toEqual({ '东莞': 160, '湖北': 50 })
  })
})

describe('factoryMeta', () => {
  it('orderFactories 固定顺序：东莞 → 湖北 → 其余按字典序', () => {
    expect(orderFactories(['未标注', '湖北', '东莞'])).toEqual(['东莞', '湖北', '未标注'])
    expect(orderFactories([])).toEqual([])
  })

  it('factoryTone 映射：东莞 dg / 湖北 hb / 其余（含 undefined）other', () => {
    expect(factoryTone('东莞')).toBe('dg')
    expect(factoryTone('湖北')).toBe('hb')
    expect(factoryTone('未标注')).toBe('other')
    expect(factoryTone(undefined)).toBe('other')
  })
})

describe('PurchasePlanFactoryFilter', () => {
  const mountFilter = (modelValue = '东莞') => mount(PurchasePlanFactoryFilter, {
    props: { modelValue, factories: ['湖北', '东莞'], totals: { '东莞': 160, '湖北': 50 } },
  })

  it('顺序固定为 东莞 → 湖北（无「全部」），且显示各厂计划量', () => {
    const w = mountFilter()
    const tabs = w.findAll('.sp-tab')
    expect(tabs.map(t => t.attributes('data-f'))).toEqual(['东莞', '湖北'])
    expect(w.findAll('.sp-factory-cnt').map(s => s.text())).toEqual(['160', '50'])
  })

  it('选中态跟随 modelValue', () => {
    const w = mountFilter('东莞')
    const active = w.findAll('.sp-tab').filter(t => t.classes().includes('sp-tab-active'))
    expect(active).toHaveLength(1)
    expect(active[0]!.attributes('data-f')).toBe('东莞')
  })

  it('点击某个工厂 emit update:modelValue', async () => {
    const w = mountFilter()
    await w.findAll('.sp-tab')[1]!.trigger('click')
    expect(w.emitted('update:modelValue')?.[0]).toEqual(['湖北'])
  })
})

describe('SkuSummaryTable 工厂列', () => {
  it('表头含「工厂」，每行渲染工厂徽章', () => {
    const w = mount(SkuSummaryTable, {
      props: { rows: SKU, sortField: 'customer', sortDir: 'desc', page: 1, totalPages: 1, totalItems: 2 },
      global: { stubs: { FontAwesomeIcon: { template: '<i />' } } },
    })
    expect(w.find('.sp-sku-table thead').text()).toContain('工厂')
    const badges = w.findAll('.td-factory .sp-fb')
    expect(badges.map(b => b.text())).toEqual(['东莞', '湖北'])
  })
})
