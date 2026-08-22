import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { defineComponent } from 'vue'

// mock 库存 API，隔离网络层
vi.mock('@/api', () => ({
  stockApi: { inventory: vi.fn() },
}))

import { stockApi } from '@/api'
import { useStockWarning } from '../views/stock/composables/useStockWarning'
import type { InventoryItem } from '@/types'

const Host = defineComponent({
  setup() {
    const warning = useStockWarning()
    return { warning }
  },
  template: '<div />',
})

const mockInventory = vi.mocked(stockApi.inventory)

function createHost() {
  const wrapper = mount(Host)
  return wrapper.vm.warning
}

describe('useStockWarning（库存不足校验，fail-closed）', () => {
  beforeEach(() => {
    mockInventory.mockReset()
  })

  it('库存满足需求量时返回 true 且不弹窗', async () => {
    const w = createHost()
    mockInventory.mockResolvedValue({
      data: [
        { product_name: '面料A', country_orders: { 美国: 100 } },
      ] as unknown as InventoryItem[],
    } as never)

    const ok = await w.checkCountryStock('面料A', '1', '美国', 50)
    expect(ok).toBe(true)
    expect(w.stockWarningOpen.value).toBe(false)
  })

  it('国家无库存记录时弹窗并返回 false', async () => {
    const w = createHost()
    mockInventory.mockResolvedValue({
      data: [{ product_name: '面料A', country_orders: { 日本: 10 } }] as unknown as InventoryItem[],
    } as never)

    const ok = await w.checkCountryStock('面料A', '1', '美国', 50)
    expect(ok).toBe(false)
    expect(w.stockWarningOpen.value).toBe(true)
    expect(w.stockWarningData.country).toBe('美国')
    expect(w.stockWarningData.availableStock).toBe(0)
  })

  it('库存数量不足时弹窗并返回 false，且带出实际可用量', async () => {
    const w = createHost()
    mockInventory.mockResolvedValue({
      data: [
        { product_name: '面料A', country_orders: { 美国: 30 } },
      ] as unknown as InventoryItem[],
    } as never)

    const ok = await w.checkCountryStock('面料A', '1', '美国', 50)
    expect(ok).toBe(false)
    expect(w.stockWarningOpen.value).toBe(true)
    expect(w.stockWarningData.availableStock).toBe(30)
    expect(w.stockWarningData.demandQty).toBe(50)
  })

  it('接口异常时 fail-closed：返回 false 阻止提交', async () => {
    const w = createHost()
    mockInventory.mockRejectedValue(new Error('network down'))

    const ok = await w.checkCountryStock('面料A', '1', '美国', 50)
    expect(ok).toBe(false)
  })
})
