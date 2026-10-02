import { caseApi } from '@/api'
import { productApi } from '@/api'
import type { Product } from '@/types'
import type { CaseTree } from '@/api/case'

/**
 * 皮套录入/设置共享：产品搜索（名称/69码）+ 取某产品的皮套树（主件 + 配件）。
 */
export function useCaseOptions() {
  /** 产品搜索；空关键词直接返回空数组避免全量拉取 */
  async function searchProducts(query: string): Promise<Product[]> {
    const q = query.trim()
    if (!q) return []
    try {
      return await productApi.search(q)
    } catch {
      return []
    }
  }

  /** 取（不存在则自动创建）某产品的皮套主件 + 配件 */
  async function fetchCaseTree(productId: number): Promise<CaseTree | null> {
    try {
      return await caseApi.forProduct(productId)
    } catch {
      return null
    }
  }

  return { searchProducts, fetchCaseTree }
}
