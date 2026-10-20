/**
 * P1-22：外发订单产品筛选必须下沉到服务端。
 *
 * 旧实现只对当前页做客户端过滤，目标产品在其他页时误报「未匹配」。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { nextTick, reactive } from 'vue'

const mocks = vi.hoisted(() => ({
  orders: vi.fn(),
  captured: null as null | Record<string, unknown>,
}))

vi.mock('@/api/outsource', () => ({
  outsourceApi: { orders: mocks.orders },
}))

vi.mock('@tanstack/vue-query', async () => {
  const { ref } = await import('vue')
  return {
    keepPreviousData: () => undefined,
    useQuery: (opts: Record<string, unknown>) => {
      mocks.captured = opts
      return {
        data: ref(undefined),
        isLoading: ref(false),
        isFetching: ref(false),
        refetch: vi.fn(),
      }
    },
  }
})

import { useOutsourceOrders } from '@/views/outsource/composables/useOutsourceOrders'

describe('useOutsourceOrders 产品筛选', () => {
  beforeEach(() => {
    mocks.orders.mockReset()
    mocks.orders.mockResolvedValue({ data: [], total: 0 })
    mocks.captured = null
  })

  it('产品关键字进入服务端参数与 queryKey，并回到第 1 页', async () => {
    const props = reactive({ productFilter: '', customerFilter: '' })
    const state = useOutsourceOrders(props)
    state.page.value = 3

    props.productFilter = '杯'
    await nextTick()

    expect(state.page.value).toBe(1)
    const queryKey = (mocks.captured as { queryKey: unknown[] }).queryKey
    expect((queryKey[2] as { value: string }).value).toBe('杯')

    await (mocks.captured as { queryFn: () => Promise<unknown> }).queryFn()
    expect(mocks.orders).toHaveBeenCalledWith(expect.objectContaining({ product: '杯' }))
  })
})
