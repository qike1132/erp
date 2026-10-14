import { computed, ref } from 'vue'
import { auxApi } from '@/api'
import type { Product } from '@/types'

/** 浏览模式一次最多列出多少条（与客户订单页同口径）。 */
const SKU_BROWSE_LIMIT = 200

/** 出货页产品名称字段需要的最小表单形状：客户决定可见 SKU 范围，搜索词决定下拉文案。 */
export interface StockOutProductSearchForm {
  customer: string
  search: string
}

/**
 * 出货页「产品名称」搜索 / 浏览，与客户订单页 useOrderForm 同口径：
 * - 搜索带当前客户 → 只返回该客户可见的 SKU；
 * - 点击输入框（空关键字）→ 列出该客户全部可见 SKU；
 * - 未选客户不发浏览请求，下拉文案区分「请先选客户 / 加载失败 / 该客户暂无产品」。
 */
export function useStockOutProductSearch(form: StockOutProductSearchForm) {
  const productSearchFailed = ref(false)
  const skuListFailed = ref(false)

  async function searchProducts(q: string): Promise<Product[]> {
    if (!q.trim()) return []
    try {
      const data = await auxApi.productSearch(q, { customer: form.customer || undefined })
      productSearchFailed.value = false
      return Array.isArray(data) ? data : []
    } catch {
      productSearchFailed.value = true
      return []
    }
  }

  /** 点击输入框列全量：一次列出当前客户可见的 SKU；未选客户不发请求。 */
  async function fetchSkuList(): Promise<Product[]> {
    if (!form.customer) {
      skuListFailed.value = false
      return []
    }
    try {
      const data = await auxApi.productSearch('', { customer: form.customer, limit: SKU_BROWSE_LIMIT })
      skuListFailed.value = false
      return Array.isArray(data) ? data : []
    } catch {
      skuListFailed.value = true
      return []
    }
  }

  const skuListError = computed(() => {
    if (!form.customer) return '请先选择客户'
    return skuListFailed.value ? '加载失败，请重试' : ''
  })

  const productEmptyText = computed(() => {
    if (form.search.trim()) {
      return productSearchFailed.value ? '搜索失败，请重试' : '无匹配结果'
    }
    return skuListError.value || '该客户暂无可用产品，请到产品页给 SKU 挂上该客户'
  })

  return { searchProducts, fetchSkuList, productEmptyText, skuListError }
}
