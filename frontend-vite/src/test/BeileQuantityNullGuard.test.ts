import { describe, it, expect, vi } from 'vitest'

// 轻量 mock：本文件只测纯口径函数，mock 掉模块顶层重依赖以保证模块可加载。
vi.mock('@/api', () => ({
  orderApi: { beileList: vi.fn(), confirmBeileOrder: vi.fn(), confirmBeileStockin: vi.fn() },
}))
vi.mock('@tanstack/vue-query', async () => {
  const { ref } = await import('vue')
  return {
    useQuery: () => ({ data: ref(null), isLoading: ref(false), isFetching: ref(false), refetch: vi.fn() }),
    useQueryClient: () => ({ setQueryData: vi.fn() }),
    keepPreviousData: {},
  }
})
vi.mock('vue-router', () => ({ useRoute: () => ({ query: {} }) }))
vi.mock('@/composables/useToast', () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
  showToast: vi.fn(),
}))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: () => true }) }))
vi.mock('@/utils/xls', () => ({ downloadXls: vi.fn() }))
vi.mock('@/utils/print', () => ({ printHtml: vi.fn() }))

import {
  skuOrderQty,
  skuProductionQty,
  skuIsOrdered,
  type BeileOrderRow,
  type SkuQtyFields,
} from '@/views/beile-order/composables/useBeileOrders'

/**
 * D-R2-1 前端 null 守卫回归：后端备货模糊匹配降级后订单级数量为 null，
 * 前端**不得**用 `?? 0` 渲染成 0 / 编造生产数量。
 */
describe('D-R2-1 前端 null 守卫：订单级数量为 null 时不得编造数字', () => {
  // 备货模糊匹配降级：is_ordered=true 但订单级数量为 null，单 SKU 自身 quantity=10000
  const degradedSku = {
    id: 21,
    product_name: '变形金刚',
    quantity: 10000,
    per_sku_source: 'order_level',
    purchase_order_qty: null,
    spare_quantity: null,
  } as unknown as SkuQtyFields

  const degradedRow = {
    id: 21,
    is_ordered: true,
    purchase_order_qty: null,
    spare_quantity: null,
    quantity: 10000,
    items: [degradedSku],
  } as unknown as BeileOrderRow

  it('skuOrderQty：单 SKU + 已下单 + 订单级数量 null → 回退自身 quantity（不得为 0）', () => {
    expect(skuOrderQty(degradedRow, degradedSku)).toBe(10000)
  })

  it('skuProductionQty：单 SKU + 已下单 + 订单级数量 null → null（「—」，不得编造）', () => {
    expect(skuProductionQty(degradedRow, degradedSku)).toBeNull()
  })

  it('对照：订单级数量可得时正常回退订单级值（订单路径行为不变）', () => {
    const okSku = { ...degradedSku, purchase_order_qty: 10000, spare_quantity: 500 } as unknown as SkuQtyFields
    const okRow = {
      id: 21,
      is_ordered: true,
      purchase_order_qty: 10000,
      spare_quantity: 500,
      quantity: 10000,
      items: [okSku],
    } as unknown as BeileOrderRow

    expect(skuOrderQty(okRow, okSku)).toBe(10000)
    expect(skuProductionQty(okRow, okSku)).toBe(10500)
  })
})

/**
 * OBS-1：加粗判定 `skuIsOrdered` 与数量守卫口径对齐 —— 未拿到采购单实际下单量则**不加粗**。
 */
describe('OBS-1 skuIsOrdered 加粗守卫（与数量守卫口径一致）', () => {
  it('is_ordered=true + 单 SKU + order_level + purchase_order_qty=null ⇒ false（回退值不得加粗）', () => {
    const sku = {
      product_name: '变形金刚',
      quantity: 10000,
      per_sku_source: 'order_level',
      purchase_order_qty: null,
      spare_quantity: null,
    } as unknown as SkuQtyFields
    const row = {
      id: 35045,
      is_ordered: true,
      purchase_order_qty: null,
      spare_quantity: null,
      quantity: 10000,
      items: [sku],
    } as unknown as BeileOrderRow
    expect(skuIsOrdered(row, sku)).toBe(false)
  })

  it('对照：is_ordered=true + 单 SKU + purchase_order_qty=10000 ⇒ true（订单级实际下单量）', () => {
    const sku = {
      product_name: 'A',
      quantity: 10000,
      per_sku_source: 'order_level',
      purchase_order_qty: 10000,
      spare_quantity: 500,
    } as unknown as SkuQtyFields
    const row = {
      id: 11,
      is_ordered: true,
      purchase_order_qty: 10000,
      spare_quantity: 500,
      quantity: 10000,
      items: [sku],
    } as unknown as BeileOrderRow
    expect(skuIsOrdered(row, sku)).toBe(true)
  })

  it('对照：per_sku_source=po_sku ⇒ true（真·逐 SKU 快照）', () => {
    const sku = {
      product_name: 'A',
      quantity: 10,
      per_sku_source: 'po_sku',
      purchase_order_qty: 10,
      spare_quantity: 1,
    } as unknown as SkuQtyFields
    const row = {
      id: 11,
      is_ordered: true,
      purchase_order_qty: 10,
      spare_quantity: 1,
      quantity: 10,
      items: [sku],
    } as unknown as BeileOrderRow
    expect(skuIsOrdered(row, sku)).toBe(true)
  })
})
