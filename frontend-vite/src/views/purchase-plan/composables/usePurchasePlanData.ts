// 每日计划与月度客户汇总的数据查询（6.9+6.10：使用后端聚合接口，消除前端聚合计算）
import { computed, markRaw, type Ref } from 'vue';
import { useQuery, keepPreviousData } from '@tanstack/vue-query';
import { planApi } from '@/api';
import type { Row, SkuRow, SkuDateItem, CustSumItem } from '../components/types';

// 星期缩写（下标与 Date.getDay() 对齐，周日=日）
export const WDS = ['日', '一', '二', '三', '四', '五', '六'];

// 判断单条计划的出货状态：完成 / 部分 / 未出
export function getShipmentStatus(quantity: number, shippedQty: number): string {
  if (shippedQty >= quantity) return 'completed';
  if (shippedQty > 0) return 'partial';
  return 'pending';
}

export function usePurchasePlanData(y: Ref<number>, m: Ref<number>, _viewTab: Ref<'daily' | 'summary'>) {
  // 单次聚合查询替代原 pp-monthly + pp-summary 两个查询
  // 后端完成 rows + sku_summary + sku_date_index + customers 聚合，不传输全量明细
  const { data: d, isLoading, isFetching, isError, refetch } = useQuery({
    queryKey: ['pp-agg', () => y.value, () => m.value],
    queryFn: async () => {
      const res = await planApi.monthlyAggregated({ year: y.value, month: m.value });
      // markRaw 标记跳过响应式代理，零拷贝开销
      return res ? markRaw(res as Record<string, unknown>) : res;
    },
    staleTime: 5 * 60 * 1000,
    gcTime: 30 * 60 * 1000,
    retry: 1,
    retryDelay: 2000,
    placeholderData: keepPreviousData,
  });

  // 直接使用后端聚合数据，无需前端二次聚合
  const rows = computed<Row[]>(() => (d.value?.rows ?? []) as unknown as Row[]);
  const skuSummary = computed<SkuRow[]>(() => (d.value?.sku_summary ?? []) as unknown as SkuRow[]);
  const skuDateIndex = computed<Record<string, SkuDateItem[]>>(() => (d.value?.sku_date_index ?? {}) as unknown as Record<string, SkuDateItem[]>);
  const customers = computed<CustSumItem[]>(() => (d.value?.customers ?? []) as unknown as CustSumItem[]);
  // Z02-R6：后端库存映射降级（查询超时/失败）时值是空映射，页面会把「没货」显示成 0
  const inventoryDegraded = computed(() => d.value?.inventory_degraded === true);

  return { d, isLoading, isFetching, isError, refetch, rows, skuSummary, skuDateIndex, customers, inventoryDegraded };
}
