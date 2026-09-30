/**
 * 近 N 日趋势数据。区间按「今天往前推 N-1 天」到「今天」计算，
 * 因此天然可跨月 —— 这正是新增 /trend 接口的原因（monthly-summary 只服务单月）。
 */
import { computed, type Ref } from 'vue'
import { useQuery } from '@tanstack/vue-query'

import { dailyProductionApi } from '@/api/production'
import { trendRange } from './productionDate'

export function useProductionTrend(days: Ref<number>) {
  const range = computed(() => trendRange(days.value))

  const trendQuery = useQuery({
    queryKey: computed(() => ['daily-production-trend', range.value.start_date, range.value.end_date]),
    queryFn: () => dailyProductionApi.trend(range.value),
    staleTime: 60_000,
  })

  return { trendQuery }
}
