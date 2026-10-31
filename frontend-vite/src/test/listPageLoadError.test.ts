/**
 * 列表页「加载失败」与「暂无数据」的分离（2026-10-30 审计 A-M32）
 *
 * 现场：6 个列表页只取 isLoading，请求失败时 data 为空、loading 结束，模板落到
 * 「暂无数据」——5xx 与超时被渲染成「这里真的没有数据」这一业务结论。用户既不会
 * 重试，也不会报障；对批次查询页更是「完成批次」的决策误判（以为这批已经没了）。
 *
 * 两道锁：
 *   1. 运行时：贝乐订单页在 isError=true 时渲染 role=alert 的失败态，重试按钮真的
 *      调用 refetch；（同一份模板结构，其余 5 页由第 2 条结构锁覆盖）
 *   2. 结构：6 个页面的错误分支必须存在、必须带 role=alert 与 refetch，且「暂无」
 *      分支必须是 v-else（与错误态互斥，不能同时出现）。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { ref, nextTick, defineComponent, h } from 'vue'

const mocks = vi.hoisted(() => ({
  beileListMock: vi.fn(),
  refetchMock: vi.fn(),
  isErrorRef: null as unknown as ReturnType<typeof ref<boolean>>,
}))

vi.mock('@/api', () => ({
  orderApi: {
    beileList: mocks.beileListMock,
    confirmBeileOrder: vi.fn(),
    confirmBeileStockin: vi.fn(),
  },
}))

vi.mock('@/api/request', () => ({
  resolveStaticUrl: (url: string | null | undefined) => url ?? '',
}))

vi.mock('@tanstack/vue-query', async () => {
  const { ref } = await import('vue')
  const dataRef = ref<unknown>(null)
  const errorRef = ref(false)
  mocks.isErrorRef = errorRef
  return {
    useQuery: () => ({
      data: dataRef,
      isLoading: ref(false),
      isFetching: ref(false),
      isError: errorRef,
      refetch: mocks.refetchMock,
    }),
    useQueryClient: () => ({ setQueryData: vi.fn() }),
    keepPreviousData: {},
  }
})

vi.mock('vue-router', () => ({ useRoute: () => ({ query: {} }) }))

vi.mock('@/composables/useToast', () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
  showToast: vi.fn(),
}))

vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({ hasPermission: () => true }),
}))

import { mount, flushPromises } from '@vue/test-utils'
import BeileOrderTab from '@/views/beile-order/BeileOrderTab.vue'
import { provideBeileOrders } from '@/views/beile-order/composables/useBeileOrders'

// jsdom 里 clientHeight 恒为 0，虚拟列表不会渲染；列表为空时不影响错误分支，但保持与既有测试一致
Object.defineProperty(HTMLElement.prototype, 'clientHeight', {
  configurable: true,
  get() {
    return 600
  },
})

const stubs = {
  UiSpinner: { template: '<span class="ui-spinner-stub" />' },
  UiPagination: { template: '<div class="ui-pagination-stub" />' },
  UiButton: { template: '<button type="button"><slot /></button>' },
  VirtualList: { props: ['items'], template: '<div class="vl-stub" />' },
}

const TestHost = defineComponent({
  setup() {
    provideBeileOrders()
    return () => h(BeileOrderTab)
  },
})

async function mountTab() {
  const wrapper = mount(TestHost, { global: { stubs } })
  await flushPromises()
  await nextTick()
  return wrapper
}

describe('贝乐订单页：加载失败不再是「暂无订单」', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.isErrorRef.value = false
  })

  it('成功但无数据 → 显示「暂无订单」，不显示告警', async () => {
    const wrapper = await mountTab()

    expect(wrapper.text()).toContain('暂无订单')
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
  })

  it('请求失败 → 显示失败态与重试入口，而不是「暂无订单」', async () => {
    mocks.isErrorRef.value = true
    const wrapper = await mountTab()

    const alert = wrapper.find('[role="alert"]')
    expect(alert.exists()).toBe(true)
    expect(alert.text()).toContain('订单加载失败')
    expect(wrapper.text()).not.toContain('暂无订单')
  })

  it('点击重试调用 refetch', async () => {
    mocks.isErrorRef.value = true
    const wrapper = await mountTab()

    await wrapper.find('[role="alert"] button').trigger('click')

    expect(mocks.refetchMock).toHaveBeenCalledTimes(1)
  })
})

describe('6 个列表页的错误态结构锁', () => {
  const pages = [
    { name: '贝乐订单', file: 'src/views/beile-order/BeileOrderTab.vue', empty: '暂无订单' },
    { name: '外发订单', file: 'src/views/outsource/components/OutsourceOrderTab.vue', empty: '暂无湖北外发订单' },
    { name: '库存', file: 'src/views/stock/InventoryTab.vue', empty: '暂无库存数据' },
    { name: '成品库存', file: 'src/views/finished-stock/FinishedStockView.vue', empty: '暂无成品库存' },
    { name: '退货', file: 'src/views/stock-return/StockReturnView.vue', empty: '暂无退货记录' },
    { name: '批次', file: 'src/views/batch/BatchView.vue', empty: '暂无批次数据' },
  ]

  for (const page of pages) {
    it(`${page.name}：错误分支带 role=alert 与 refetch，「暂无」挂在同一条 v-else 链上`, () => {
      const src = readFileSync(resolve(process.cwd(), page.file), 'utf-8')

      // 错误分支：从 isError 条件起到空态文案之前
      const openIdx = src.search(/v-(?:else-)?if="isError/)
      expect(openIdx, `${page.file} 必须有 isError 驱动的分支`).toBeGreaterThan(-1)
      const emptyAt = src.indexOf(page.empty, openIdx)
      expect(emptyAt, `${page.file} 的空态文案「${page.empty}」应紧随错误分支`).toBeGreaterThan(openIdx)

      const block = src.slice(openIdx, emptyAt)
      expect(block).toContain('role="alert"')
      expect(block).toContain('@click="refetch()"')

      // 互斥：空态所在标签必须是 v-else / v-else-if（同一条链），不能另起 v-if
      const tagStart = src.lastIndexOf('<div', emptyAt)
      expect(tagStart).toBeGreaterThan(openIdx)
      expect(src.slice(tagStart, emptyAt)).toContain('v-else')
    })
  }

  it('4 个 composable 都从 useQuery 取出 isError 并对外暴露', () => {
    const files = [
      'src/views/beile-order/composables/useBeileOrders.ts',
      'src/views/outsource/composables/useOutsourceOrders.ts',
      'src/views/stock-return/composables/useStockReturn.ts',
      'src/views/batch/composables/useBatchQuery.ts',
    ]
    for (const file of files) {
      const src = readFileSync(resolve(process.cwd(), file), 'utf-8')
      // 至少两处：解构取用 + return 暴露
      expect(src.match(/\bisError\b/g)?.length ?? 0, `${file} 应解构并暴露 isError`).toBeGreaterThanOrEqual(2)
    }
  })
})
