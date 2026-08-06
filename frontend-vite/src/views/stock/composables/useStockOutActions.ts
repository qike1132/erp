import type { Ref } from 'vue'
import { stockApi } from '@/api'
import { showToast } from '@/composables/useToast'
import type { ApiResponse, StagedStockout } from '@/types'

/**
 * 出货批量提交动作。
 * 将暂存列表分组校验可出货量后批量提交，并根据单项结果处理
 * 全部成功 / 部分成功 / 全部失败 三种场景。
 */
export function useStockOutActions(
  staged: Ref<StagedStockout[]>,
  submitting: Ref<boolean>,
  onComplete: () => void,
) {
  async function submitBatch() {
    if (!staged.value.length) return

    submitting.value = true
    try {
      const uniqueKeys: Record<string, { product_id: string; customer: string; order_type: string; country: string; stockouts: StagedStockout[] }> = {}
      const withCustomer = staged.value.filter(stockout => stockout.customer)
      withCustomer.forEach(stockout => {
        const ot = stockout.order_type || 'regular'
        const key = `${stockout.product_id}-${stockout.customer}-${ot}`
        if (!uniqueKeys[key]) uniqueKeys[key] = { product_id: stockout.product_id, customer: stockout.customer, order_type: ot, country: stockout.country || '', stockouts: [] }
        uniqueKeys[key].stockouts.push(stockout)
      })

      // 预检：并行查询所有分组的可出货量，收集超额组统一展示
      const overLimitGroups: string[] = []
      const precheckTasks = Object.keys(uniqueKeys).map(async (key) => {
        const { product_id, customer, order_type, country, stockouts } = uniqueKeys[key]
        try {
          const ot = order_type !== 'regular' ? order_type : undefined
          const co = order_type === 'custom' && country ? country : undefined
          const data = await stockApi.availableShipment(Number(product_id), customer, ot, co)
          const shipment = data.data
          if (!shipment) return
          const totalQty = stockouts.reduce((sum: number, stockout: StagedStockout) => sum + stockout.quantity, 0)
          if (totalQty > (shipment.available_quantity ?? 0)) {
            const typeLabel = order_type === 'custom' ? `定制${country ? `(${country})` : ''}` : '常规'
            overLimitGroups.push(`客户: ${customer} 产品ID: ${product_id} [${typeLabel}] 可出货${shipment.available_quantity ?? 0}`)
          }
        } catch (err) {
          console.warn(`出货量预检失败: product_id=${product_id}, customer=${customer}`, err)
        }
      })
      await Promise.all(precheckTasks)

      if (overLimitGroups.length > 0) {
        const suffix = overLimitGroups.length > 2 ? `...等共${overLimitGroups.length}组超额` : ''
        showToast(`以下组出货量超过可出货量: ${overLimitGroups.slice(0, 2).join('; ')}${suffix}`, 'error')
        submitting.value = false
        return
      }

      const stockoutsForApi = staged.value.map(stockout => ({
        product_id: Number(stockout.product_id),
        customer: stockout.customer,
        quantity: stockout.quantity,
        stockout_date: stockout.date,
        note: stockout.note,
        order_type: stockout.order_type || 'regular',
        country: stockout.order_type === 'custom' ? (stockout.country || '') : undefined,
      }))

      const result = await stockApi.batchSubmitStockouts(stockoutsForApi) as ApiResponse & { results?: Array<{ success: boolean; error?: string }> }

      // 检查单项结果，处理部分成功/全部失败的情况
      const results = result.results ?? []
      const failedItems = results.filter((result: { success: boolean }) => !result.success)
      const successCount = results.length - failedItems.length

      if (result.success !== false && failedItems.length === 0) {
        // 全部成功
        showToast('出货提交成功', 'success')
        staged.value = []
        onComplete()
      } else if (successCount > 0) {
        // 部分成功
        const errorMsgs = failedItems.slice(0, 3).map((result: { error?: string }, index: number) => `第${index + 1}项: ${result.error || '未知错误'}`).join('; ')
        const suffix = failedItems.length > 3 ? `...等共${failedItems.length}项失败` : ''
        showToast(`部分出货成功(${successCount}/${results.length})，失败项: ${errorMsgs}${suffix}`, 'warning')
        onComplete()
      } else {
        // 全部失败
        const errorMsg = failedItems.length > 0
          ? failedItems.slice(0, 3).map((result: { error?: string }, index: number) => `第${index + 1}项: ${result.error || '未知错误'}`).join('; ')
          : (result as { error?: string }).error || result.message || '提交失败'
        showToast(errorMsg, 'error')
      }
    } catch (err: unknown) {
      const error = err as { response?: { data?: { detail?: string } } }
      showToast(error.response?.data?.detail || '批量提交失败', 'error')
    } finally {
      submitting.value = false
    }
  }

  return { submitBatch }
}
