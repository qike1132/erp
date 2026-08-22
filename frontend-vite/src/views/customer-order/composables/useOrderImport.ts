/**
 * useOrderImport — Excel 批量导入动作域（批次 2-3 拆分自 useOrderActions）
 *
 * 承载模板下载、文件选择/拖拽、暂存导入。逻辑原样搬移。
 */
import { ref, type Ref, type ComputedRef } from 'vue'
import { get, post } from '@/api/request'
import { showToast } from '@/composables/useToast'
import { getErrorMessage } from '@/types/errors'
import type { StagedItem } from './types'
import { genUid } from './useStagedItems'

/** 暂存订单条目（/staging-orders 返回的原始结构） */
interface StagingOrderItem {
  order_type?: string
  customer: string
  product_id: number
  product_name: string
  quantity: number
  order_date: string
  note: string
  deduct_stock: boolean
  deduct_quantity?: number
  country?: string
}

/** 暂存备货条目（/staging-stockins 返回的原始结构） */
interface StagingStockinItem {
  order_type?: string
  customer: string
  product_id: number
  product_name: string
  quantity: number
  stockin_date: string
  note: string
  country?: string
}

export function useOrderImport(stagedItems: Ref<StagedItem[]>, isOrder: ComputedRef<boolean>) {
  const excelFile = ref<File | null>(null)
  const importing = ref(false)
  const isDragOver = ref(false)
  const excelInputRef = ref<HTMLInputElement | null>(null)

  function handleExcelSelect(e: Event) {
    excelFile.value = (e.target as HTMLInputElement).files?.[0] ?? null
  }
  function onDrop(e: DragEvent) {
    isDragOver.value = false
    const f = e.dataTransfer?.files?.[0]
    if (f) excelFile.value = f
  }
  function downloadTemplate() {
    window.open('/api/v1/batch/download-template', '_blank')
  }

  async function handleImport() {
    if (!excelFile.value) return
    importing.value = true
    try {
      const fd = new FormData()
      fd.append('file', excelFile.value)
      if (isOrder.value) {
        await post('/staging-orders/import', fd)
        showToast('导入成功', 'success')
        const res = await get<{ staging_orders?: StagingOrderItem[]; items?: StagingOrderItem[] }>('/staging-orders')
        const items = res.staging_orders ?? res.items ?? []
        stagedItems.value.push(
          ...items.map((i): StagedItem => ({
            uid: genUid(),
            type: 'order',
            orderType: i.order_type === 'custom' ? 'custom' : 'normal',
            customer: i.customer,
            productId: i.product_id,
            productName: i.product_name,
            quantity: i.quantity,
            date: i.order_date,
            note: i.note,
            deductStock: i.deduct_stock,
            deductQuantity: i.deduct_quantity || 0,
            country: i.country || '',
          })),
        )
      } else {
        await post('/staging-stockins/import', fd)
        showToast('导入成功', 'success')
        const res = await get<{ staging_stockins?: StagingStockinItem[]; items?: StagingStockinItem[] }>('/staging-stockins')
        const items = res.staging_stockins ?? res.items ?? []
        stagedItems.value.push(
          ...items.map((i): StagedItem => ({
            uid: genUid(),
            type: 'stockin',
            orderType: i.order_type === 'custom' ? 'custom' : 'normal',
            customer: i.customer,
            productId: i.product_id,
            productName: i.product_name,
            quantity: i.quantity,
            date: i.stockin_date,
            note: i.note,
            deductStock: false,
            deductQuantity: 0,
            country: i.country || '',
          })),
        )
      }
      excelFile.value = null
    } catch (err: unknown) {
      showToast(getErrorMessage(err, '导入失败'), 'error')
    } finally {
      importing.value = false
    }
  }

  return {
    excelFile,
    importing,
    isDragOver,
    excelInputRef,
    handleExcelSelect,
    onDrop,
    downloadTemplate,
    handleImport,
  }
}
