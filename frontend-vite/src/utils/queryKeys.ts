/**
 * 查询键常量与失效辅助（纯模块，不实例化 QueryClient）。
 *
 * 单独成文件而非放进 queryClient.ts：queryClient.ts 在模块加载时会构造全局
 * QueryClient 并挂持久化，被组件/composable 引用会把这些副作用一并拖进来
 * （测试中对 @tanstack/vue-query 做部分 mock 时会直接报错）。
 */
import type { QueryClient } from '@tanstack/vue-query'

/**
 * 订单 / 备货 / 出货写入后需要失效的全部派生查询键。
 *
 * 分两类，都必须在写入成功后整体失效：
 *
 * 1) 库存与报表域（/stock、/report、三个记录列表）——由订单/备货/出货聚合而来。
 * 2) 关联页面（贝莱订单 / 外包订单 / 采购）——客户订单的删除、改数量、改抵扣、
 *    批量提交都会改变这三个页面的数据。
 *
 * 为什么必须「整体」失效：这些 query 会被 persistQueryClient 持久化到
 * sessionStorage，只失效一部分时，用户切过去会命中被恢复的旧快照、
 * **根本不发请求**，页面停留在写入前的旧数据。
 *
 * 集中在此处是为了避免各提交入口各自手写不完整的列表——历史上订单提交入口
 * 就漏了 inventory / report-data，导致「下单成功但库存页、报表页不刷新」；
 * 2026-09-30 又漏了 beile-orders / outsource-orders / purchase-*，
 * 导致「客户订单删除或改数量后，贝莱/外包/采购页面不刷新」。
 *
 * 关联页面自身另有兜底：这些列表声明了 staleTime 0 / refetchOnMount 'always' /
 * refetchOnWindowFocus（见各 use*Orders），显示即重取，不单靠本失效或 WebSocket 推送。
 */
export const ORDER_DERIVED_QUERY_KEYS = [
  // —— 库存 / 报表域 ——
  'orders-list',
  'stockins-list',
  'stockouts-list',
  'inventory',
  'report-data',
  // —— 关联页面 ——
  'beile-orders',            // /beile-order 贝莱（湖北）订单
  'outsource-orders',        // /outsource 外包订单
  'purchase-orders-list',    // /purchase 采购订单
  'unprocessed-orders',      // /purchase 待审核订单
  'completed-orders-list',   // /purchase 已完成订单
] as const

/** 订单 / 备货 / 出货写入成功后，统一失效上述派生查询缓存 */
export function invalidateOrderDerivedQueries(client: QueryClient): void {
  for (const key of ORDER_DERIVED_QUERY_KEYS) {
    client.invalidateQueries({ queryKey: [key] })
  }
}
