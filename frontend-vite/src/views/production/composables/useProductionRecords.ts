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

export function useProductionRecords(filters: Ref<RecordFilters>) {
  const queryClient = useQueryClient()

  const query = computed(() => buildRecordsQuery(filters.value))

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
