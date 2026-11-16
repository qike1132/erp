/**
 * 批次页翻页触顶必须显式提示（上线前审计 2026-11-16 Low）。
 *
 * 现场：`useBatchQuery.queryFn` 串行翻页到 BATCH_MAX_PAGES（20 页 × 500 行 =
 * 10000 行）就 return，并把 `total` 改成 `all.length`——超过 10000 行的结果被
 * 静默截断，页面看起来「就这么多」，用户拿残缺列表去做「完成批次」决策。
 *
 * 修法：触顶时返回 `truncated: true` 且 `total` 保持后端真实总数，页面渲染
 * 可见提示。本文件锁两条：composable 的标记与真实总数、页面上的提示文案。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { nextTick } from 'vue'
import { mount } from '@vue/test-utils'

const mocks = vi.hoisted(() => ({
  batchListMock: vi.fn(),
  mainData: null as unknown as { value: unknown },
  captured: null as null | Record<string, unknown>,
}))

vi.mock('@/api', () => ({
  batchApi: { list: (params: unknown) => mocks.batchListMock(params) },
  orderBatchApi: { whitelist: vi.fn(async () => ({ customers: ['贝乐'] })) },
  customerApi: { activeNames: vi.fn(async () => []) },
}))

vi.mock('@/composables/useToast', () => ({ showToast: vi.fn() }))

vi.mock('@tanstack/vue-query', async () => {
  const { ref } = await import('vue')
  const mainData = ref<unknown>(null)
  mocks.mainData = mainData as { value: unknown }
  return {
    useQuery: (opts: Record<string, unknown>) => {
      const key = (opts.queryKey as unknown[])?.[0]
      if (key === 'batch-query') {
        mocks.captured = opts
        return {
          data: mainData,
          isLoading: ref(false),
          isFetching: ref(false),
          isError: ref(false),
          refetch: vi.fn(),
        }
      }
      if (key === 'order-batch-whitelist') {
        return { data: ref({ customers: ['贝乐'] }), refetch: vi.fn() }
      }
      return { data: ref([]), refetch: vi.fn() }
    },
    keepPreviousData: {},
  }
})

import BatchView from '@/views/batch/BatchView.vue'
import { useBatchQuery } from '@/views/batch/composables/useBatchQuery'

/** 上限 = 20 页 × 500 行（与 composable 内 BATCH_MAX_PAGES/BATCH_PAGE_SIZE 对齐） */
const MAX_ROWS = 10000

interface TruncatedPayload {
  data: unknown[]
  total: number
  truncated: boolean
}

/** 造一页数据：后端说总共有 total 条，但单页最多 500 条 */
function pageOf(page: number, size = 500) {
  return Array.from({ length: size }, (_, i) => ({
    id: page * 1000 + i,
    order_no: `PO-${page}-${i}`,
    customer: '贝乐',
    order_date: '2026-10-01',
    product_id: 1,
    product_name: '产品X',
    product_barcode: '690',
    quantity: 1,
    deducted_qty: 0,
    shipped_qty: 0,
    status: null,
    computed_status: null,
    batch_no: null,
    batch_completed_at: null,
    is_locked: null,
    record_type: 'order' as const,
  }))
}

/** 跑一次被捕获的 queryFn（键名与生产一致：'batch-query'） */
function runQuery(): Promise<TruncatedPayload> {
  return (mocks.captured!.queryFn as () => Promise<TruncatedPayload>)()
}

describe('批次查询翻页触顶', () => {
  beforeEach(() => {
    mocks.captured = null
    mocks.batchListMock.mockReset()
  })

  it('触顶时 truncated=true，total 不退化成已拉取行数', async () => {
    // 后端恒返回满页且总数远超上限：强制走到 BATCH_MAX_PAGES
    mocks.batchListMock.mockImplementation(async (params: { page: number }) => ({
      success: true,
      total: 99999,
      data: pageOf(params.page),
    }))
    useBatchQuery()

    const res = await runQuery()

    expect(res.truncated).toBe(true)
    expect(res.data).toHaveLength(MAX_ROWS)
    // total 必须是后端真实总数：伪装成 all.length 会把「还有 89999 行没拿到」藏起来
    expect(res.total).toBe(99999)
    expect(mocks.batchListMock).toHaveBeenCalledTimes(20)
  })

  it('未触顶时 truncated=false 且 total 为真实总数', async () => {
    mocks.batchListMock.mockResolvedValue({ success: true, total: 3, data: pageOf(1, 3) })
    useBatchQuery()

    const res = await runQuery()

    expect(res.truncated).toBe(false)
    expect(res.data).toHaveLength(3)
    expect(res.total).toBe(3)
  })

  it('触顶时页面渲染可见提示，用户不会误以为「数据就这么多」', async () => {
    mocks.batchListMock.mockImplementation(async (params: { page: number }) => ({
      success: true,
      total: 99999,
      data: pageOf(params.page),
    }))
    const wrapper = mount(BatchView, {
      global: {
        stubs: {
          UiInput: true,
          UiButton: true,
          UiDialog: true,
          UiSpinner: true,
          BatchGroupList: true,
          BatchWhitelistModal: true,
        },
      },
    })

    mocks.mainData.value = await runQuery()
    await nextTick()

    expect(wrapper.find('.bt-truncated-hint').exists()).toBe(true)
    expect(wrapper.text()).toContain('结果超过 10000 行，已截断，请收窄筛选')
  })

  it('未触顶时不出提示', async () => {
    mocks.batchListMock.mockResolvedValue({ success: true, total: 3, data: pageOf(1, 3) })
    const wrapper = mount(BatchView, {
      global: {
        stubs: {
          UiInput: true,
          UiButton: true,
          UiDialog: true,
          UiSpinner: true,
          BatchGroupList: true,
          BatchWhitelistModal: true,
        },
      },
    })

    mocks.mainData.value = await runQuery()
    await nextTick()

    expect(wrapper.find('.bt-truncated-hint').exists()).toBe(false)
  })
})
