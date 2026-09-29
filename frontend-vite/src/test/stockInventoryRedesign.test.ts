/**
 * /stock 库存页改版的结构断言（方案 B v5）。
 *
 * 本机开不了浏览器预览，排版靠人眼实测；但「一行工具条 / 客户独立成行 /
 * 5 列口径 / 千分位与空值格式」这些是结构事实，在此固化。
 *
 * 设计要点（与 HTML 对比稿 v5 对齐）：
 *  · 第 1 行 = 标题 · 搜索 · 三格汇总 · 导出 Excel（原先分散在卡片头与过滤栏两处）
 *  · 第 2 行 = 客户筛选 chips（独立成行）
 *  · 表格 5 列：客户 / 产品名称 / 订单数量 / 备货数量 / 总订单
 *  · 汇总与表格口径同名同源：总订单 = 订单数量 + 备货数量
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { nextTick, type Component } from 'vue'
import { mount, type VueWrapper } from '@vue/test-utils'

const mocks = vi.hoisted(() => ({
  exportInventoryMock: vi.fn(),
  refetchMock: vi.fn(),
  queryData: null as unknown as { value: unknown },
}))

vi.mock('@/api', () => ({
  stockApi: {
    inventory: vi.fn(),
    exportInventory: mocks.exportInventoryMock,
  },
}))

vi.mock('@tanstack/vue-query', async () => {
  const { ref: vueRef } = await import('vue')
  const dataRef = vueRef<unknown>(null)
  mocks.queryData = dataRef as { value: unknown }
  return {
    useQuery: () => ({
      data: dataRef,
      isLoading: vueRef(false),
      isFetching: vueRef(false),
      refetch: mocks.refetchMock,
    }),
    keepPreviousData: {},
  }
})

import InventoryStatRow from '@/views/stock/components/InventoryStatRow.vue'
import InventoryToolbar from '@/views/stock/components/InventoryToolbar.vue'
import InventoryCustomerBar from '@/views/stock/components/InventoryCustomerBar.vue'
import InventoryTab from '@/views/stock/InventoryTab.vue'
import UiDataTable from '@/components/ui/UiDataTable.vue'
import type { InventoryItem } from '@/types'
import PrimeVue from 'primevue/config'
import { plushCutePT } from '@/styles/primevue-pt'

const ITEMS: InventoryItem[] = [
  {
    product_id: 1, product_name: 'S925银项链-淡水珍珠款', barcode: '6923748120031', customer: '滨发服饰',
    current_stock: 0, total_stockin: 1200, total_stockout: 860, total_deducted: 0,
    order_quantity: 320, stockin_quantity: 1200, total_stock: 1520, available_stock: 1140,
  },
  {
    product_id: 2, product_name: '儿童保温杯-恐龙款', barcode: '6923748120117', customer: '贝乐教育',
    current_stock: 0, total_stockin: 0, total_stockout: 75, total_deducted: 0,
    // 后端把 0 值序列化成空串——展示层必须容错
    order_quantity: 75, stockin_quantity: '', total_stock: 75, available_stock: -75,
  },
]

const INV_RESPONSE = {
  data: ITEMS,
  total_order_quantity: 3204,
  total_stockin_quantity: 12930,
  total_stock: 16134,
  total_available_stock: 8422,
  all_customers: ['滨发服饰', '贝乐教育'],
  total_items: 43,
  page: 1,
  per_page: 15,
}

function mountStat(over: { orders?: number; stockin?: number } = {}) {
  return mount(InventoryStatRow, { props: { orders: 3204, stockin: 12930, ...over } })
}

function mountToolbar(over: Record<string, unknown> = {}) {
  return mount(InventoryToolbar, {
    props: { search: '', orders: 3204, stockin: 12930, hasData: true, ...over },
  })
}

function mountCustomerBar(over: Record<string, unknown> = {}) {
  return mount(InventoryCustomerBar, {
    props: { customers: ['滨发服饰', '贝乐教育'], selected: '', loading: false, ...over },
  })
}

/**
 * 触发 UiDataTable 的排序事件。
 * UiDataTable 是泛型 SFC：直接传入会让 findComponent 的重载解析失败，
 * 故先擦成 Component 再收窄到「可 $emit」的最小形态——纯测试脚手架的类型适配，不动生产代码。
 */
async function emitSort(w: VueWrapper, field: string, order: number) {
  const table = w.findComponent(UiDataTable as unknown as Component) as unknown as {
    vm: { $emit: (event: string, payload: unknown) => void }
  }
  table.vm.$emit('sort', { field, order })
  await nextTick()
}

function mountTab() {
  mocks.queryData.value = INV_RESPONSE
  // 按生产配置挂载：main.ts 用的是 unstyled + PT，默认模式渲染出的
  // `p-*` 类名在生产里并不存在，断言会建立在假象上（排序图标那次就踩了这个坑）
  return mount(InventoryTab, {
    global: { plugins: [[PrimeVue, { unstyled: true, pt: plushCutePT }]] },
  })
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('InventoryStatRow —— 三格汇总', () => {
  it('只渲染三格：订单数量 / 备货数量 / 总订单', () => {
    const w = mountStat()

    expect(w.findAll('.sk-stat')).toHaveLength(3)
    const text = w.text()
    expect(text).toContain('订单数量')
    expect(text).toContain('备货数量')
    expect(text).toContain('总订单')
  })

  it('删掉了「可用库存」格（改由表格列承载，汇总不再重复播报）', () => {
    expect(mountStat().text()).not.toContain('可用库存')
  })

  it('总订单 = 订单数量 + 备货数量', () => {
    const w = mountStat()

    expect(w.findAll('.sk-stat')[2]?.text()).toContain('16,134')
  })

  it('数值走千分位，几十万量级一眼可辨', () => {
    const w = mountStat()

    expect(w.text()).toContain('3,204')
    expect(w.text()).toContain('12,930')
  })

  it('每格带口径提示，悬停可知数字含义', () => {
    const w = mountStat()
    const stats = w.findAll('.sk-stat')

    expect(stats[0]?.attributes('title')).toBe('未发完的订单数量')
    expect(stats[1]?.attributes('title')).toBe('已入库未消耗')
    expect(stats[2]?.attributes('title')).toBe('订单数量 + 备货数量')
  })
})

describe('InventoryToolbar —— 单行工具条', () => {
  it('渲染页面标题与搜索框（搜索与汇总原先分处两行）', () => {
    const w = mountToolbar()

    expect(w.find('h1').text()).toBe('库存查询')
    expect(w.find('.sk-search-input').attributes('placeholder')).toContain('69 码')
  })

  it('搜索框输入上抛 update:search（受控组件，不自己存状态）', async () => {
    const w = mountToolbar()
    const input = w.find('.sk-search-input')

    await input.setValue('珍珠')

    expect(w.emitted('update:search')?.[0]).toEqual(['珍珠'])
  })

  it('回车触发 search，不依赖查询按钮', async () => {
    const w = mountToolbar({ search: '珍珠' })

    await w.find('.sk-search-input').trigger('keyup.enter')

    expect(w.emitted('search')).toHaveLength(1)
  })

  it('汇总三格就在这一行内（同一容器，不再另起一行）', () => {
    const w = mountToolbar()

    expect(w.findAll('.sk-toolbar > .sk-stat-row .sk-stat')).toHaveLength(3)
  })

  it('导出按钮点击上抛 export', async () => {
    const w = mountToolbar()

    await w.find('.sk-export-btn').trigger('click')

    expect(w.emitted('export')).toHaveLength(1)
  })

  it('没有可导出的数据时不显示导出按钮', () => {
    expect(mountToolbar({ hasData: false }).find('.sk-export-btn').exists()).toBe(false)
  })

  it('没有数据时不显示汇总三格（避免一排 0 噪音）', () => {
    expect(mountToolbar({ hasData: false }).find('.sk-stat-row').exists()).toBe(false)
  })
})

describe('InventoryCustomerBar —— 客户独立成行', () => {
  it('「全部」+ 各客户 chips', () => {
    const w = mountCustomerBar()

    expect(w.findAll('.sk-chip')).toHaveLength(3)
    expect(w.findAll('.sk-chip')[0]?.text()).toBe('全部')
    expect(w.text()).toContain('滨发服饰')
    expect(w.text()).toContain('贝乐教育')
  })

  it('未筛选时「全部」为选中态；筛选后对应客户为选中态', () => {
    expect(mountCustomerBar().findAll('.sk-chip')[0]?.classes()).toContain('active')
    expect(mountCustomerBar({ selected: '贝乐教育' }).findAll('.sk-chip')[2]?.classes()).toContain('active')
  })

  it('点击客户上抛 select', async () => {
    const w = mountCustomerBar()

    await w.findAll('.sk-chip')[1]?.trigger('click')

    expect(w.emitted('select')?.[0]).toEqual(['滨发服饰'])
  })
})

describe('InventoryTab —— 5 列表格与数字格式', () => {
  it('表头是 客户 / 产品名称 / 订单数量 / 备货数量 / 总订单', () => {
    const headers = mountTab().findAll('th').map((th) => th.text().replace(/[▾▼]/g, '').trim())

    expect(headers).toEqual(['客户', '产品名称', '订单数量', '备货数量', '总订单'])
  })

  it('不再有「可用库存」列', () => {
    expect(mountTab().text()).not.toContain('可用库存')
  })

  it('数量走千分位', () => {
    expect(mountTab().text()).toContain('1,200')
  })

  it('空值留白，不显示「—」之类的占位符', () => {
    const cells = mountTab().findAll('tbody tr')[1]?.findAll('td')

    // 第 2 行「儿童保温杯」备货数量为 0（后端序列化成 ''），落在第 4 列
    expect(cells?.[3]?.text()).toBe('')
  })

  it('三个数值列的表头与数据都居中显示', () => {
    const w = mountTab()

    const headers = w.findAll('th')
    for (const i of [2, 3, 4]) {
      expect(headers[i]?.attributes('style')).toContain('center')
    }

    const cells = w.findAll('tbody tr')[0]!.findAll('td')
    for (const i of [2, 3, 4]) {
      expect(cells[i]?.attributes('style')).toContain('center')
    }
  })

  it('总订单列取 total_stock 口径', () => {
    const cells = mountTab().findAll('tbody tr')[0]?.findAll('td')

    expect(cells?.[4]?.text()).toContain('1,520')
  })

  it('三格汇总取服务端合计（订单/备货/总订单）', () => {
    const text = mountTab().text()

    expect(text).toContain('3,204')
    expect(text).toContain('12,930')
    expect(text).toContain('16,134')
  })

  it('总订单列加粗，作为每行的视觉锚点', () => {
    const cells = mountTab().findAll('tbody tr')[0]?.findAll('td')

    expect(cells?.[4]?.find('.sk-num-strong').exists()).toBe(true)
    expect(cells?.[2]?.find('.sk-num-strong').exists()).toBe(false)
  })

  it('五列按比例分配宽度（定宽数值列会让产品名独吞余量、把数字推到最右）', () => {
    const headers = mountTab().findAll('th')

    // 客户 15% / 产品名称 35% / 三个数值列各 16.67%（合计 100%）
    expect(headers[0]?.attributes('style')).toContain('15%')
    expect(headers[1]?.attributes('style')).toContain('35%')
    for (const i of [2, 3, 4]) {
      expect(headers[i]?.attributes('style')).toContain('16.67%')
    }
  })

  it('排序图标的样式钩子在生产模式下存在（unstyled 模式不带 p-* 类名）', () => {
    const w = mountTab()
    const icon = w.find('[data-pc-section="sorticon"]')

    expect(icon.exists()).toBe(true)
    expect(w.find('[data-pc-section="columnheadercontent"]').exists()).toBe(true)
    // 生产模式下图标没有任何 class —— 样式只能靠 data-pc-section 选择器命中
    expect(icon.attributes('class')).toBeUndefined()
  })

  it('行分隔线与去圆角所依赖的选择器在生产模式下存在', () => {
    const w = mountTab()

    // 行样式挂在 tr 本体 = bodyRow（全站 PT 的段名已于 2026-09-29 修正）
    expect(w.find('[data-pc-section="bodyrow"]').exists()).toBe(true)
    expect(w.find('[data-pc-section="bodyrow"]').attributes('class')).toContain('border-b')
    // 抵消 UiDataTable 容器的圆角/边框，靠的就是这个类名
    expect(w.find('.ui-data-table-wrapper').exists()).toBe(true)
  })

  it('表头排序按当前页数值重排（降序把大数排前）', async () => {
    const w = mountTab()

    await emitSort(w, 'total_stock', -1)
    expect(w.findAll('tbody tr')[0]?.text()).toContain('滨发服饰')

    await emitSort(w, 'total_stock', 1)
    expect(w.findAll('tbody tr')[0]?.text()).toContain('贝乐教育')
  })

  it('取消排序（order=0）回到服务端原始顺序', async () => {
    const w = mountTab()

    // 先升序（小单在前，与原始顺序相反），再取消排序——否则「取消」无从体现
    await emitSort(w, 'total_stock', 1)
    expect(w.findAll('tbody tr')[0]?.text()).toContain('贝乐教育')

    await emitSort(w, 'total_stock', 0)
    expect(w.findAll('tbody tr')[0]?.text()).toContain('滨发服饰')
  })

  it('不再显示「当前筛选 N 条」（条数在分页器里已有，重复且占位）', () => {
    // 在集成层断言：真实数据里 total_items = 43，若那行字还在就必然渲染出来。
    // 组件级断言会假绿 —— 不传 total 时 v-if 自然为假，测不出功能是否真被删掉。
    expect(mountTab().text()).not.toContain('当前筛选')
  })

  it('导出按钮在有数据时出现，点击调导出接口', async () => {
    const w = mountTab()

    await w.find('.sk-export-btn').trigger('click')

    expect(mocks.exportInventoryMock).toHaveBeenCalledTimes(1)
  })
})
