/**
 * 明细记录的查询与增删改。
 *
 * queryKey 必须包含**完整筛选条件**（含页码与每页条数）：抽屉的分页/筛选切换
 * 各自是独立缓存条目，否则翻页会命中上一页的缓存。这与后端移动看板那次
 * 「缓存键不含范围 → 跨用户串读」是同一类问题。
 */
import { computed, type Ref } from 'vue'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'

import { dailyProductionApi } from '@/api/production'
import type { RecordFilters } from './recordFilters'
import { buildRecordsQuery } from './recordFilters'

/**
 * @param filters 抽屉的筛选状态。
 * @param baseDate 日期基准（页面选中的 `selectedDate`）。
 *   必须由调用方传入 —— 抽屉的「本月/本周/今日」锚在这天，而不是锚在「今天」：
 *   否则在 12 月 15 日的日报页点部门卡，抽屉查的是当前自然月（审计 #1）。
 *   省略时沿用 `buildRecordsQuery` 的 `new Date()` 默认值，保持既有调用方兼容。
 */
export function useProductionRecords(filters: Ref<RecordFilters>, baseDate?: Ref<string>) {
  const queryClient = useQueryClient()

  // 基准日期也是缓存键的一部分：漏掉它，跨月切换时抽屉会命中上一天的缓存
  const query = computed(() => buildRecordsQuery(filters.value, baseDate?.value))

  const recordsQuery = useQuery({
    queryKey: computed(() => ['daily-production-records', query.value]),
    queryFn: () => dailyProductionApi.records(query.value),
    staleTime: 30_000,
  })

  function invalidateAll() {
    queryClient.invalidateQueries({ queryKey: ['daily-production-records'] })
    queryClient.invalidateQueries({ queryKey: ['daily-production-daily-summary'] })
    queryClient.invalidateQueries({ queryKey: ['daily-production-monthly-summary'] })
    queryClient.invalidateQueries({ queryKey: ['daily-production-trend'] })
  }

  const removeRecord = useMutation({
    mutationFn: (id: number) => dailyProductionApi.deleteRecord(id),
    onSuccess: invalidateAll,
  })

  return { recordsQuery, removeRecord, invalidateAll }
}
