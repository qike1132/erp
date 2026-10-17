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
      const uniqueKeys: Record<string, { product_id: string; customer: string; stockouts: StagedStockout[] }> = {}
      const withCustomer = staged.value.filter(stockout => stockout.customer)
      withCustomer.forEach(stockout => {
        const key = `${stockout.product_id}-${stockout.customer}`
        if (!uniqueKeys[key]) uniqueKeys[key] = { product_id: stockout.product_id, customer: stockout.customer, stockouts: [] }
        uniqueKeys[key].stockouts.push(stockout)
      })

      // 预检：并行查询所有分组的可出货量，收集超额组统一展示
      const overLimitGroups: string[] = []
      const precheckTasks = Object.keys(uniqueKeys).map(async (key) => {
        const group = uniqueKeys[key]
        if (!group) return
        const { product_id, customer, stockouts } = group
        try {
          const data = await stockApi.availableShipment(Number(product_id), customer)
          const shipment = data.data
          if (!shipment) return
          const totalQty = stockouts.reduce((sum: number, stockout: StagedStockout) => sum + stockout.quantity, 0)
          if (totalQty > (shipment.available_quantity ?? 0)) {
            overLimitGroups.push(`客户: ${customer} 产品ID: ${product_id} 可出货${shipment.available_quantity ?? 0}`)
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
        batch_no: stockout.batch_no || null,
      }))

      const result = await stockApi.batchSubmitStockouts(stockoutsForApi) as ApiResponse & { results?: Array<{ success: boolean; error?: string }> }

      // 检查单项结果，处理部分成功/全部失败的情况
      const results = result.results ?? []
      const failedItems = results.filter((result: { success: boolean }) => !result.success)
      const successCount = results.length - failedItems.length

      // 按逐条结果只移除已入库行（2026-10-17 审计 F-FE-DESK-CORE-01：
      // 原先部分成功分支不清暂存，重提会把已成功的行再次提交 → 重复出库）。
      // results[idx] 与请求行严格对位（stock_out_service.batch_create_stockouts
      // 的 results 数组按请求下标回填）；对不上时保守不清空。
      const resultsAligned = results.length === staged.value.length
      const remaining = resultsAligned
        ? staged.value.filter((_, idx) => {
            const r = results[idx] as { success: boolean } | undefined
            return !(r && r.success === true)
          })
        : staged.value

      if (resultsAligned && result.success !== false && failedItems.length === 0) {
        // 全部成功
        showToast('出货提交成功', 'success')
        staged.value = []
        onComplete()
      } else if (successCount > 0) {
        // 部分成功：暂存区只留失败行，成功行移除（防重复出库）
        const errorMsgs = failedItems.slice(0, 3).map((result: { error?: string }, index: number) => `第${index + 1}项: ${result.error || '未知错误'}`).join('; ')
        const suffix = failedItems.length > 3 ? `...等共${failedItems.length}项失败` : ''
        if (resultsAligned) {
          staged.value = remaining
          showToast(`部分出货成功(${successCount}/${results.length})，已入库行已从暂存区移除。失败项: ${errorMsgs}${suffix}`, 'warning')
        } else {
          // 结果无法与暂存行对位：保守保留全部，提示人工核对
          showToast(`部分出货成功(${successCount}/${results.length})，但结果与暂存清单无法对齐，暂存区未改动，请刷新后核对库存与流水。失败项: ${errorMsgs}${suffix}`, 'warning')
        }
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
