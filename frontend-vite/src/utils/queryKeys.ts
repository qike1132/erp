/**
 * 查询键常量与失效辅助（纯模块，不实例化 QueryClient）。
 *
 * 单独成文件而非放进 queryClient.ts：queryClient.ts 在模块加载时会构造全局
 * QueryClient 并挂持久化，被组件/composable 引用会把这些副作用一并拖进来
 * （测试中对 @tanstack/vue-query 做部分 mock 时会直接报错）。
 */
import type { QueryClient } from '@tanstack/vue-query'

/**
 * 订单 / 备货 / 出货写入后需要失效的派生查询键。
 *
 * 这些查询的数据都由订单、备货、出货三者聚合而来：库存汇总页（/stock）、
 * 报表流水页（/report）以及三个记录列表。任一写入成功后都必须整体失效，
 * 否则用户在 staleTime 内切过去会看到提交前的旧数据。
 *
 * 集中在此处是为了避免各提交入口各自手写不完整的列表——历史上订单提交入口
 * 就漏了 inventory / report-data，导致「下单成功但库存页、报表页不刷新」。
 */
export const STOCK_DATA_QUERY_KEYS = [
  'orders-list',
  'stockins-list',
  'stockouts-list',
  'inventory',
  'report-data',
] as const

/** 订单 / 备货 / 出货写入成功后，统一失效上述派生查询缓存 */
export function invalidateStockDataQueries(client: QueryClient): void {
  for (const key of STOCK_DATA_QUERY_KEYS) {
    client.invalidateQueries({ queryKey: [key] })
  }
}
