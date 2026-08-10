/**
 * useSupplierList — 供应商列表数据 Hook
 *
 * 从 PartFormDialog 中提取的供应商数据加载逻辑，消除批量/单行两处重复。
 * 作为模块级单例使用（同一个页面内共享供应商数据）。
 */
import { ref } from 'vue'
import { supplierApi } from '@/api/supplier'
import type { Supplier } from '@/types'

const suppliers = ref<Supplier[]>([])
const loading = ref(false)
const error = ref(false)

export function useSupplierList() {
  async function load(): Promise<void> {
    if (suppliers.value.length > 0) return // 已加载，不重复请求

    loading.value = true
    error.value = false
    try {
      const res = await supplierApi.list({ per_page: 200 })
      suppliers.value = res.suppliers ?? []
    } catch {
      error.value = true
      suppliers.value = []
    } finally {
      loading.value = false
    }
  }

  return { suppliers, loading, error, load }
}
