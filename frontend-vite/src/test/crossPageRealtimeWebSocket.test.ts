/**
 * 回归守卫：贝莱订单页与外包订单页必须订阅 WebSocket 实时刷新。
 *
 * 缺陷背景（2026-09-30）：采购页（usePurchaseHandlers）历来有 WebSocket 监听
 * （order_created/updated/deleted → 立即重载），但 /beile-order 与 /outsource
 * 两页从未接过该通道。结果：客户订单删除后，采购页实时消失，而这两页的
 * Vue Query 缓存（staleTime=30s，refetchOnWindowFocus 全局关闭）要等 30s
 * 才过期——「同一标签页内」有 invalidateOrderDerivedQueries 兜底，但
 * **跨标签页/其他用户**的操作只能靠 WS 推送触达。
 *
 * 本文件用源码契约（?raw 读组件原文）锁死：两页都注册了 useWebSocket 且
 * 监听订单事件。组件层接线（HubeiView / OutsourceOrderTab）一旦被移除，
 * 这里立即变红。
 */
import { describe, it, expect } from 'vitest'
// 源码级断言：用 Vite 的 ?raw 读原文，避免依赖 node:fs 类型
import hubeiViewSource from '@/views/hubei/HubeiView.vue?raw'
import outsourceOrderTabSource from '@/views/outsource/components/OutsourceOrderTab.vue?raw'

const PAGES: Array<{ source: string; file: string; page: string }> = [
  { source: hubeiViewSource, file: 'views/hubei/HubeiView.vue', page: '贝莱订单页 /beile-order' },
  { source: outsourceOrderTabSource, file: 'views/outsource/components/OutsourceOrderTab.vue', page: '外包订单页 /outsource' },
]

const ORDER_EVENTS = ['order_created', 'order_updated', 'order_deleted']

describe('关联页面 WebSocket 实时刷新接线', () => {
  for (const { source, file, page } of PAGES) {
    it(`${page}（${file}）订阅 useWebSocket 并监听订单事件`, () => {
      expect(source, `${page} 缺少 useWebSocket 接线`).toContain('useWebSocket(')

      for (const evt of ORDER_EVENTS) {
        expect(
          source.includes(evt),
          `${page} 未监听 ${evt}；移除事件监听会让该页退回 30s 延迟`,
        ).toBe(true)
      }
    })
  }
})
