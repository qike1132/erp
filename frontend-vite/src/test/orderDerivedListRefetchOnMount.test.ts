/**
 * 回归守卫：订单派生列表必须「每次挂载都重取」
 *
 * 缺陷背景（2026-09-30）：在客户订单页删除订单后，/beile-order 与 /outsource 要等约
 * 30 秒才更新（实测「延迟 30 秒才消失」）。
 *
 * 根因（前端）：这些列表查询会被 persistQueryClient 写进 sessionStorage；刷新/重进页面时
 * 恢复的快照自带 dataUpdatedAt，只要距现在不足 staleTime(30s) 就被判为「新鲜」，
 * **挂载时不重新取数**（vue-query 默认 refetchOnMount: true 仅在 stale 时才取）。
 * 页面因此显示删除前的旧列表，直到 30 秒后过期 —— 与实测现象一致。
 *
 * 修复：对这些列表声明 refetchOnMount: 'always'（保留 keepPreviousData 秒开，
 * 后台请求立刻校正）。
 *
 * 本文件两部分：
 *   1) 行为验证（真实 QueryClient + 真实挂载）：证明 bug 机制与修复有效；
 *   2) 源码契约：4 个列表 composable 必须声明该选项，防止被删掉。
 */
import { describe, it, expect, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { VueQueryPlugin, QueryClient, useQuery } from '@tanstack/vue-query'
import { defineComponent, h } from 'vue'

// 源码级断言：用 Vite 的 ?raw 读原文（避免依赖 node:fs 类型）
import beileOrdersSource from '@/views/beile-order/composables/useBeileOrders.ts?raw'
import outsourceOrdersSource from '@/views/outsource/composables/useOutsourceOrders.ts?raw'
import purchaseOrdersSource from '@/views/purchase/composables/usePurchaseOrders.ts?raw'
import unprocessedOrdersSource from '@/views/purchase/composables/useUnprocessedOrders.ts?raw'

function mountProbe(options: Record<string, unknown>) {
  const queryFn = vi.fn(async () => [{ id: 1 }])
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  // 模拟「从 sessionStorage 恢复的新鲜快照」：setQueryData 会把 dataUpdatedAt 置为现在
  client.setQueryData(['probe-list'], [{ id: 1 }])

  const Probe = defineComponent({
    setup() {
      useQuery({ queryKey: ['probe-list'], queryFn, staleTime: 30_000, ...options })
      return () => h('div')
    },
  })

  mount(Probe, { global: { plugins: [[VueQueryPlugin, { queryClient: client }]] } })
  return { queryFn }
}

describe('订单派生列表：挂载即重取（防止恢复旧快照导致的 30s 延迟）', () => {
  it('默认配置：staleTime 内的恢复快照不会重取（这就是延迟 30s 的机制）', async () => {
    const { queryFn } = mountProbe({})
    await flushPromises()
    await flushPromises()
    expect(queryFn).not.toHaveBeenCalled()
  })

  it("声明 refetchOnMount: 'always' 后：挂载立即重取（修复生效）", async () => {
    const { queryFn } = mountProbe({ refetchOnMount: 'always' })
    await flushPromises()
    await flushPromises()
    expect(queryFn).toHaveBeenCalledTimes(1)
  })
})

describe('源码契约：订单派生列表 composable 必须声明「每次显示都取数」三项', () => {
  const SOURCES: Array<[string, string]> = [
    ['贝莱订单 useBeileOrders', beileOrdersSource],
    ['外包订单 useOutsourceOrders', outsourceOrdersSource],
    ['采购订单 usePurchaseOrders', purchaseOrdersSource],
    ['待审核 useUnprocessedOrders', unprocessedOrdersSource],
  ]

  const REQUIRED: Array<[string, string]> = [
    ['staleTime: 0', 'staleTime 非 0 时，持久化快照会被判「新鲜」而跳过重取'],
    ["refetchOnMount: 'always'", '缺少它则刷新/路由进入时不重取'],
    ['refetchOnWindowFocus: true', '缺少它则切回已打开的标签页时不重取（WS 断线即失效）'],
  ]

  for (const [label, source] of SOURCES) {
    for (const [needle, why] of REQUIRED) {
      it(`${label} 声明 ${needle}`, () => {
        expect(
          source.includes(needle),
          `${label} 缺少 ${needle}：${why} → 客户订单删除后本页会延迟约 30s 才更新`,
        ).toBe(true)
      })
    }
  }
})
