import { defineStore } from 'pinia'
import { ref, type Ref } from 'vue'
import { productApi, customerApi, supplierApi } from '@/api'
import type { Product, Customer, Supplier } from '@/types'

/**
 * 目录（catalog）store
 *
 * 统一缓存产品 / 客户 / 供应商等基础档案的下拉选择数据，
 * 避免各视图各自请求导致的重复请求与缓存不一致。
 *
 * - TTL 内直接复用缓存；过期或 force 才重新请求
 * - 并发调用共享同一个进行中的 Promise（请求去重）
 * - 组件卸载不清空缓存（跨视图复用是目的），登出时由 auth.logout 调用 clear()
 */

/** 缓存有效期：5 分钟内直接复用 */
const CATALOG_TTL_MS = 5 * 60 * 1000

/** 目录列表请求的分页参数：取大页近似全量，专供下拉选择器使用（非 CRUD 分页列表） */
const CATALOG_PAGE_PARAMS = { page: 1, per_page: 1000 }

/** 客户下拉轻量端点的条目结构（/customers/active-names） */
export interface CustomerNameOption {
  id: number
  name: string
}

/** 单个目录条目：带 TTL 缓存 + 请求去重的最小单元 */
function createCatalogEntry<T>(fetcher: () => Promise<T[]>) {
  const list = ref([]) as Ref<T[]>
  const loading = ref(false)
  /** 最近一次成功加载的时间戳（0 表示尚未加载过） */
  const loadedAt = ref(0)
  /** 进行中的请求 Promise，并发调用共享 */
  let inflight: Promise<T[]> | null = null
  /** 代际标记：clear() 后旧请求的回写被丢弃，防止已清理的缓存被残留响应污染 */
  let generation = 0

  function isFresh(): boolean {
    return loadedAt.value > 0 && Date.now() - loadedAt.value < CATALOG_TTL_MS
  }

  /** 确保目录数据可用：TTL 内直接返回缓存；过期或 force 才发请求 */
  function ensure(force = false): Promise<T[]> {
    if (!force && isFresh()) return Promise.resolve(list.value)
    // 请求去重：已有进行中的请求时直接共享，不重复发起
    if (inflight) return inflight

    const currentGeneration = generation
    loading.value = true
    inflight = fetcher()
      .then((data) => {
        if (currentGeneration === generation) {
          list.value = data
          loadedAt.value = Date.now()
        }
        return data
      })
      .finally(() => {
        if (currentGeneration === generation) {
          loading.value = false
          inflight = null
        }
      })
    return inflight
  }

  /** 清空缓存（登出时调用）；进行中的请求结果将被丢弃 */
  function reset() {
    generation++
    list.value = []
    loading.value = false
    loadedAt.value = 0
    inflight = null
  }

  return { list, loading, ensure, reset }
}

export const useCatalogStore = defineStore('catalog', () => {
  // ===== 产品目录（productApi.list 返回 { items, total }，只缓存列表部分） =====
  const productsEntry = createCatalogEntry<Product>(async () => {
    const res = await productApi.list(CATALOG_PAGE_PARAMS)
    return res.items
  })

  // ===== 客户目录（customerApi.list 返回 { customers, total }，只缓存列表部分） =====
  const customersEntry = createCatalogEntry<Customer>(async () => {
    const res = await customerApi.list(CATALOG_PAGE_PARAMS)
    return res.customers
  })

  // ===== 供应商目录（supplierApi.list 返回 { suppliers, total }，只缓存列表部分） =====
  const suppliersEntry = createCatalogEntry<Supplier>(async () => {
    const res = await supplierApi.list(CATALOG_PAGE_PARAMS)
    return res.suppliers
  })

  // ===== 客户下拉轻量数据（active-names：仅启用客户的 { id, name }） =====
  // 选择器视图（订单录入 / 出库 / 报表筛选 / 搜索栏）实际使用的数据源
  const activeCustomerNamesEntry = createCatalogEntry<CustomerNameOption>(async () => {
    const res = await customerApi.activeNames()
    return Array.isArray(res) ? res : []
  })

  /** 清空全部目录缓存（登出时由 auth store 的 logout 调用） */
  function clear() {
    productsEntry.reset()
    customersEntry.reset()
    suppliersEntry.reset()
    activeCustomerNamesEntry.reset()
  }

  return {
    // 列表（只读 ref，供视图 computed 消费）
    products: productsEntry.list,
    customers: customersEntry.list,
    suppliers: suppliersEntry.list,
    activeCustomerNames: activeCustomerNamesEntry.list,
    // 加载态
    productsLoading: productsEntry.loading,
    customersLoading: customersEntry.loading,
    suppliersLoading: suppliersEntry.loading,
    activeCustomerNamesLoading: activeCustomerNamesEntry.loading,
    // 确保数据可用（TTL 缓存 + 请求去重）
    ensureProducts: productsEntry.ensure,
    ensureCustomers: customersEntry.ensure,
    ensureSuppliers: suppliersEntry.ensure,
    ensureActiveCustomerNames: activeCustomerNamesEntry.ensure,
    // 清理
    clear,
  }
})
