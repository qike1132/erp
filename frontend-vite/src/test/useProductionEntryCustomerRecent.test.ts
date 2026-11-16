/**
 * 审计 #8：右侧「最近客户添加」必须让后端按客户过滤，且截断不得静默。
 *
 * 拦的错：接口没有客户条件时，前端只能拉全库最新 200 行再自己筛 —— 该客户近期
 * 录入被别人的记录挤出这 200 行后，面板静默变空，用户以为「这个客户从没录过」，
 * 于是重复手工录入。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { defineComponent, h, computed } from 'vue'
import { mount } from '@vue/test-utils'

const records = vi.fn()
const productSearch = vi.fn()
const showToast = vi.fn()

vi.mock('@/api', () => ({
  customerApi: { activeNames: async () => [] },
  dailyProductionApi: {
    productInfo: async () => ({ data: { price: 1 } }),
    records: (...a: unknown[]) => records(...a),
    createRecord: async () => ({}),
  },
  productApi: { search: (...a: unknown[]) => productSearch(...a) },
}))

vi.mock('@/composables/useToast', () => ({ showToast: (...a: unknown[]) => showToast(...a) }))

vi.mock('@tanstack/vue-query', () => ({
  useQuery: () => ({ data: { value: [] } }),
  useQueryClient: () => ({ invalidateQueries: vi.fn() }),
}))

import { useProductionEntry } from '@/views/production/composables/useProductionEntry'

function setup() {
  const open = computed({ get: () => true, set: () => {} }) as unknown as Parameters<typeof useProductionEntry>[0]
  const date = computed({ get: () => '2026-10-26', set: () => {} }) as unknown as Parameters<typeof useProductionEntry>[1]

  let result!: ReturnType<typeof useProductionEntry>
  mount(defineComponent({
    setup() {
      result = useProductionEntry(open, date)
      return () => h('div')
    },
  }))
  return result
}

/** 冲掉若干层微任务（不依赖具体实现用了几个 await） */
async function flush(times = 6) {
  for (let i = 0; i < times; i += 1) await Promise.resolve()
}

/**
 * 取「带客户条件的那个请求」的参数。
 * 不能按调用次数取：同一 composable 里 refreshTodayCount 等也会调 records，
 * 按次数断言会在别处改动后假红。
 */
function customerScopedParams(): Record<string, unknown> {
  const call = records.mock.calls.find((args) => {
    const params = args[0] as Record<string, unknown>
    return params && Object.prototype.hasOwnProperty.call(params, 'customer_id')
  })
  expect(call, '没有发出带 customer_id 的请求（缺陷原状：全量拉 200 行再前端筛）').toBeTruthy()
  return call![0] as Record<string, unknown>
}

describe('useProductionEntry 最近客户添加（审计 #8）', () => {
  beforeEach(() => {
    records.mockReset()
    showToast.mockReset()
    records.mockResolvedValue({ data: [], total: 0 })
  })

  it('请求按客户过滤：带 customer_id，per_page 仍是 200', async () => {
    const entry = setup()
    records.mockResolvedValue({
      data: [
        { customer_id: 7, product_id: 9, product_name: '白兔公仔', barcode: '690', quantity: 3 },
      ],
      total: 1,
    })

    entry.selectCustomer(7)
    await flush()

    const params = customerScopedParams()
    expect(params.customer_id).toBe(7)
    expect(params.per_page).toBe(200)
    // 窗口仍以选中日期为终点（近 90 天）
    expect(params.end_date).toBe('2026-10-26')
    expect(params.start_date).toBe('2026-07-28')
    expect(entry.recentTruncated.value).toBe(false)
    expect(entry.customerRecent.value.map((r) => r.product_id)).toEqual([9])
  })

  it('超过 200 行时置截断标记并提示（不静默）', async () => {
    const entry = setup()
    records.mockResolvedValue({
      data: [
        { customer_id: 7, product_id: 9, product_name: '白兔公仔', barcode: '690', quantity: 3 },
      ],
      total: 250,
    })

    entry.selectCustomer(7)
    await flush()

    // 拦的错：只显示 200 行却什么都不说，用户以为列表已经是全集
    expect(entry.recentTruncated.value).toBe(true)
    expect(showToast).toHaveBeenCalled()
    const message = String(showToast.mock.calls[0]?.[0])
    expect(message).toContain('200')
  })

  it('历史行没有 customer_id 时按名字兜底命中，不混入别的客户', async () => {
    const entry = setup()
    records.mockResolvedValue({
      data: [
        { customer_id: null, product_id: 9, product_name: '白兔公仔', barcode: '690', quantity: 3 },
        { customer_id: 8, product_id: 10, product_name: '别人的公仔', barcode: '691', quantity: 3 },
      ],
      total: 2,
    })

    entry.selectCustomer(7)
    await flush()

    expect(entry.customerRecent.value.map((r) => r.product_id)).toEqual([9])
  })
})
