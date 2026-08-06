import { ref, reactive } from 'vue'
import { stockApi } from '@/api'
import type { InventoryItem } from '@/types'

/** 库存不足提示弹窗状态与校验逻辑 */
export function useStockWarning() {
  const stockWarningOpen = ref(false)
  const stockWarningData = reactive({
    productName: '',
    country: '',
    availableStock: 0,
    demandQty: 0,
  })

  /**
   * 校验指定国家库存是否满足需求量。
   * 库存不足时弹出提示弹窗并返回 false。
   * 接口异常时 fail-closed（阻止提交），避免校验形同虚设。
   */
  async function checkCountryStock(
    productName: string,
    _productId: string,
    country: string,
    demandQty: number,
  ): Promise<boolean> {
    try {
      const resp = await stockApi.inventory({ product: productName, country })
      // 后端返回 InventoryResponse，库存明细在 data 字段
      const items: InventoryItem[] = resp.data ?? []
      const matched = items.find((item) => {
        const co = item.country_orders ?? {}
        return co[country] !== undefined && Number(co[country]) > 0
      })
      if (!matched) {
        stockWarningData.productName = productName
        stockWarningData.country = country
        stockWarningData.availableStock = 0
        stockWarningData.demandQty = demandQty
        stockWarningOpen.value = true
        return false
      }
      const countryQty = Number(matched.country_orders?.[country] ?? 0)
      if (countryQty < demandQty) {
        stockWarningData.productName = productName
        stockWarningData.country = country
        stockWarningData.availableStock = countryQty
        stockWarningData.demandQty = demandQty
        stockWarningOpen.value = true
        return false
      }
      return true
    } catch {
      // fail-closed: 校验不可用时阻止提交，由用户重试或后端最终兜底
      return false
    }
  }

  return { stockWarningOpen, stockWarningData, checkCountryStock }
}
