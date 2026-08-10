/**
 * useCustomerList — 客户列表数据 Hook
 *
 * 从 PatternRoomView 提取的客户数据加载逻辑。
 * 三级降级：activeNames → active list → all list → 空数组。
 */
import { ref } from 'vue'
import { customerApi } from '@/api/customer'
import type { Customer } from '@/types'

const customers = ref<Customer[]>([])
const loading = ref(false)

export function useCustomerList() {
  async function load(): Promise<void> {
    if (customers.value.length > 0) return // 已加载

    loading.value = true
    try {
      const names = await customerApi.activeNames()
      if (Array.isArray(names) && names.length > 0) {
        customers.value = names.map((n) => ({ id: n.id, name: n.name } as Customer))
      } else {
        const res = await customerApi.list({ per_page: 1000, status: 'active' })
        customers.value = res.customers ?? []
      }
    } catch {
      try {
        const res = await customerApi.list({ per_page: 1000 })
        customers.value = res.customers ?? []
      } catch {
        customers.value = []
      }
    } finally {
      loading.value = false
    }
  }

  return { customers, loading, load }
}
