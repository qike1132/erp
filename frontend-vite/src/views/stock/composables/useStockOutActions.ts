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
    // H6：函数级重入闸——按钮 disabled 挡不住程序化/连点/快捷键重复调用
    if (submitting.value || !staged.value.length) return

    // H6（评审）：提交必须基于**进入函数时的快照**。旧实现在预检 await 之后才读
    // live staged.value，响应后又按当前长度/下标清理——提交期间新增一行会让
    // 长度对不上（成功行残留→重试重复出库），删除+新增同长度时又会按旧下标
    // 误删新行。快照用稳定 id，响应只按「快照中成功的 id」移除。
    const snapshot = staged.value.map(row => ({ ...row }))

    submitting.value = true
    try {
      const uniqueKeys: Record<string, { product_id: string; customer: string; stockouts: StagedStockout[] }> = {}
      const withCustomer = snapshot.filter(stockout => stockout.customer)
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

      const stockoutsForApi = snapshot.map(stockout => ({
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

      // results[idx] 与**快照**严格对位（后端按请求下标回填）。按快照 id 移除成功行，
      // 提交期间新增/编辑的行只会在「它自己也被成功提交」时移除。
      const resultsAligned = results.length === snapshot.length
      // id 是「只删成功行」的唯一依据：撞号会连带删掉同 id 的失败行（用户以为已出库）。
      // 生成器已保证唯一（StockOutTab.nextStagedId），这里再判一次——历史数据或新入口
      // 绕开生成器时，宁可走「保留全部 + 提示核对」，也不按 id 猜着删。
      const idsUnique = new Set(snapshot.map(row => row.id)).size === snapshot.length
      const succeededIds = new Set(
        snapshot.filter((_, idx) => results[idx]?.success === true).map(row => row.id),
      )
      const dropSucceeded = () => {
        // succeededIds 是 submittedIds 的子集；按 id 移除可保证在途新增行不被误删
        staged.value = staged.value.filter(row => !succeededIds.has(row.id))
      }

      if (resultsAligned && result.success !== false && failedItems.length === 0) {
        // 全部成功：只清本次提交过的行（在途新增的行保留）
        dropSucceeded()
        showToast(
          staged.value.length ? '出货提交成功（提交期间新增的行已保留）' : '出货提交成功',
          'success',
        )
        onComplete()
      } else if (successCount > 0) {
        // 部分成功：暂存区只留失败行与在途新增行（防重复出库）
        const errorMsgs = failedItems.slice(0, 3).map((result: { error?: string }, index: number) => `第${index + 1}项: ${result.error || '未知错误'}`).join('; ')
        const suffix = failedItems.length > 3 ? `...等共${failedItems.length}项失败` : ''
        if (resultsAligned && idsUnique) {
          dropSucceeded()
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
