import { computed } from 'vue'
import { useQuery } from '@tanstack/vue-query'
import { caseApi, customerApi } from '@/api'
import type { CaseSearchItem, CustomerOption } from '@/api/case'

/**
 * 皮套录入/筛选共享选项：客户名称下拉 + 产品搜索（名称/69码，附当前库存）。
 * 客户列表 30s 缓存；产品搜索走 /cases/search，由调用方持有结果。
 */
export function useCaseOptions() {
  const { data: customersData } = useQuery({
    queryKey: ['case-customer-names'],
    queryFn: async () => {
      const res = (await customerApi.activeNames()) as unknown as { names?: string[] } & string[]
      return res.names ?? res ?? []
    },
    staleTime: 30_000,
  })

  const customerOptions = computed<CustomerOption[]>(() =>
    (Array.isArray(customersData.value) ? customersData.value : [])
      .map((c: string) => ({ value: c, label: c })),
  )

  /** 产品搜索；空关键词直接返回空数组避免全量拉取 */
  async function searchCaseProducts(query: string): Promise<CaseSearchItem[]> {
    const q = query.trim()
    if (!q) return []
    try {
      return await caseApi.search(q)
    } catch {
      return []
    }
  }

  return { customerOptions, searchCaseProducts }
}
