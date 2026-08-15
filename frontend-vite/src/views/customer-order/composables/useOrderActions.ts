import { ref, reactive, computed, type Reactive, type ComputedRef } from 'vue'
import { useQueryClient } from '@tanstack/vue-query'
import { get, post } from '@/api/request'
import { orderApi } from '@/api'
import { showToast } from '@/composables/useToast'
import { useConfirmDialog } from '@/composables/useConfirmDialog'
import { getErrorMessage } from '@/types/errors'
import type { OrderItem } from '@/types'
import type { FormState, StagedItem, AvailableStockinItem } from './types'

/** 生成暂存项唯一标识（使用 crypto.randomUUID 确保无碰撞） */
function genUid(): string {
  return crypto.randomUUID()
}

export function useOrderActions(
  form: Reactive<FormState>,
  isOrder: ComputedRef<boolean>,
  fetchOrders: () => Promise<void>,
) {
  const queryClient = useQueryClient()
  const confirmDialog = useConfirmDialog()

  // ===== Staged items =====
  const stagedItems = ref<StagedItem[]>([])

  async function removeStagedItem(uid: string) {
    const ok = await confirmDialog.confirm('确定删除？', '此操作不可恢复', 'danger')
    if (!ok) return
    // 通过 uid 安全定位，避免异步 confirm 期间索引失效
    const idx = stagedItems.value.findIndex((i) => i.uid === uid)
    if (idx >= 0) stagedItems.value.splice(idx, 1)
  }

  const stagedOrders = computed(() => stagedItems.value.filter((i) => i.type === 'order'))
  const stagedStockins = computed(() => stagedItems.value.filter((i) => i.type === 'stockin'))

  const submitting = ref(false)

  async function submitAll() {
    if (!stagedItems.value.length || submitting.value) return
    submitting.value = true
    try {
      const orderPayload = stagedOrders.value.map((i) => ({
        product_id: i.productId,
        customer: i.customer,
        quantity: i.quantity,
        deduct_stock: i.deductStock || false,
        deduct_quantity: i.deductQuantity || 0,
        note: i.note || '',
        order_date: i.date || '',
        order_type: i.orderType === 'custom' ? 'custom' : 'regular',
        country: i.country || '',
      }))
      const stockinPayload = stagedStockins.value.map((i) => ({
        product_id: i.productId,
        customer: i.customer,
        quantity: i.quantity,
        note: i.note || '',
        stockin_date: i.date || '',
        order_type: i.orderType === 'custom' ? 'custom' : 'regular',
        country: i.country || '',
      }))

      const orderUids = stagedOrders.value.map((i) => i.uid)
      const stockinUids = stagedStockins.value.map((i) => i.uid)

      let orderFailed = false
      let stockinFailed = false
      let orderRes: any = null

      if (orderPayload.length) {
        try {
          orderRes = await post('/aux/batch-submit-orders', { orders: orderPayload })
        } catch (e: unknown) {
          showToast(getErrorMessage(e, '订单提交失败'), 'error')
          orderFailed = true
        }
      }
      if (!orderFailed && stockinPayload.length) {
        try {
          await post('/aux/batch-submit-stockins', { stockins: stockinPayload })
        } catch (e: unknown) {
          showToast(getErrorMessage(e, '备货提交失败'), 'error')
          stockinFailed = true
        }
      }

      // 仅移除成功提交的项，保留失败的项供用户重试
      if (!orderFailed) {
        stagedItems.value = stagedItems.value.filter((i) => !orderUids.includes(i.uid))
      }
      if (!stockinFailed) {
        stagedItems.value = stagedItems.value.filter((i) => !stockinUids.includes(i.uid))
      }

      // 反馈：部分失败时明确告知用户状态
      if (orderFailed && !stockinFailed && stockinPayload.length) {
        showToast('备货已提交成功，但订单提交失败，请重新提交订单', 'warning')
      } else if (!orderFailed && stockinFailed && orderPayload.length) {
        showToast(`订单已提交成功，但备货提交失败，请重新提交备货`, 'warning')
      } else if (!orderFailed && !stockinFailed) {
        if (orderPayload.length && orderRes) {
          const resData: any = orderRes.data ?? orderRes
          const createdCount = resData?.created_count ?? 0
          const skuCount = orderPayload.length
          if (createdCount === 0) {
            // 订单全部失败：提取后端返回的错误详情
            const failedResults = (resData?.results ?? []).filter((r: any) => !r.success)
            const firstError = failedResults[0]?.error || '未知原因'
            showToast(`订单创建失败（0/${skuCount}）：${firstError}`, 'error')
          } else {
            showToast(`提交成功：已创建 ${createdCount} 个主订单（含 ${skuCount} 个 SKU）`, 'success')
          }
        } else {
          showToast('提交成功', 'success')
        }
      }

      if (!orderFailed) queryClient.invalidateQueries({ queryKey: ['orders-list'] })
      if (!stockinFailed) queryClient.invalidateQueries({ queryKey: ['stockins-list'] })
    } finally {
      submitting.value = false
    }
  }

  // ===== Edit staged =====
  const editStagedVisible = ref(false)
  const editStagedIdx = ref(-1)
  const editStagedData = ref<StagedItem | null>(null)
  const editAvailableStock = ref(0)

  function openEditStaged(uid: string) {
    const idx = stagedItems.value.findIndex((i) => i.uid === uid)
    if (idx < 0) return
    editStagedIdx.value = idx
    const data: StagedItem = { ...stagedItems.value[idx]! }
    editStagedData.value = data
    editStagedVisible.value = true
    if (data.type === 'order' && data.productId && data.customer) {
      get('/aux/available-stockins', {
        product_id: data.productId,
        customer: data.customer,
      })
        .then((res: any) => {
          const items: AvailableStockinItem[] = res.stockins ?? res.items ?? res ?? []
          editAvailableStock.value = items.reduce(
            (s: number, i: AvailableStockinItem) => s + (i.available ?? i.quantity - (i.deducted || 0)),
            0,
          )
        })
        .catch(() => {
          editAvailableStock.value = 0
        })
    }
  }
  function saveEditStaged() {
    if (editStagedIdx.value >= 0 && editStagedData.value) {
      if (editStagedData.value.deductQuantity > 0) editStagedData.value.deductStock = true
      stagedItems.value[editStagedIdx.value] = { ...editStagedData.value }
    }
    editStagedVisible.value = false
  }

  // ===== Batch upload =====
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
        const res = await get<{ staging_orders?: unknown[]; items?: unknown[] }>('/staging-orders')
        const items = res.staging_orders ?? res.items ?? []
        stagedItems.value.push(
          ...items.map((i: any): StagedItem => ({
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
        const res = await get<{ staging_stockins?: unknown[]; items?: unknown[] }>('/staging-stockins')
        const items = res.staging_stockins ?? res.items ?? []
        stagedItems.value.push(
          ...items.map((i: any): StagedItem => ({
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

  // ===== Detail dialog & edit order =====
  const detailOpen = ref(false)
  const detailData = ref<any>(null)
  const editForm = reactive({ quantity: 1, deductQuantity: 0, note: '' })
  const availableStockin = ref(0)
  const saving = ref(false)
  /** 标记抵扣更新是否待重试（第一次成功、第二次失败时） */
  const deductRetryPending = ref(false)

  async function openDetail(item: any) {
    try {
      const res = await orderApi.detail(item.id) as OrderItem & { product?: { id?: number }; customer?: string; data?: OrderItem }
      const data = (res.data ?? res) as typeof res
      detailData.value = data
      editForm.quantity = data.quantity || 1
      editForm.deductQuantity = data.deduct_quantity || 0
      editForm.note = data.note || ''
      // 查询可用备货量
      if (data.product?.id && data.customer) {
        try {
          const availRes = await get<{ available_quantity?: number; available?: number; data?: { available_quantity?: number; available?: number } }>('/aux/available-stockins', { product_id: data.product.id, customer: data.customer })
          const availData = availRes.data ?? availRes
          availableStockin.value = (availData.available_quantity ?? availData.available ?? 0) + (data.deduct_quantity || 0)
        } catch {
          availableStockin.value = 0
        }
      } else {
        availableStockin.value = 0
      }
      deductRetryPending.value = false
      detailOpen.value = true
    } catch {
      showToast('获取订单详情失败', 'error')
    }
  }

  async function saveEditOrder() {
    if (!detailData.value || saving.value) return
    saving.value = true
    try {
      const originalDeduct = detailData.value.deduct_quantity || 0

      // 第一步：更新基本信息（数量、备注）
      await orderApi.update(detailData.value.id, {
        quantity: editForm.quantity,
        note: editForm.note,
      })

      // 第二步：更新抵扣数量（若变更）。非原子操作，失败后标记待重试
      if (editForm.deductQuantity !== originalDeduct) {
        try {
          await orderApi.updateDeduct(detailData.value.id, editForm.deductQuantity)
          deductRetryPending.value = false
        } catch (e: unknown) {
          deductRetryPending.value = true
          showToast(
            getErrorMessage(e, '订单信息已保存，但抵扣数量更新失败，请重试抵扣更新'),
            'warning',
          )
          // 仍然刷新列表以反映已保存的数量变更
          queryClient.invalidateQueries({ queryKey: ['orders-list'] })
          queryClient.invalidateQueries({ queryKey: ['inventory'] })
          queryClient.invalidateQueries({ queryKey: ['stockins-list'] })
          queryClient.invalidateQueries({ queryKey: ['stockouts-list'] })
          fetchOrders()
          return
        }
      }

      showToast('保存成功', 'success')
      detailOpen.value = false
      queryClient.invalidateQueries({ queryKey: ['orders-list'] })
      queryClient.invalidateQueries({ queryKey: ['inventory'] })
      queryClient.invalidateQueries({ queryKey: ['stockins-list'] })
      queryClient.invalidateQueries({ queryKey: ['stockouts-list'] })
      fetchOrders()
    } catch (e: unknown) {
      showToast(getErrorMessage(e, '保存失败'), 'error')
    } finally {
      saving.value = false
    }
  }

  /** 重试抵扣数量更新（saveEditOrder 中抵扣更新失败后调用） */
  async function retryDeductUpdate() {
    if (!detailData.value || saving.value) return
    saving.value = true
    try {
      await orderApi.updateDeduct(detailData.value.id, editForm.deductQuantity)
      deductRetryPending.value = false
      showToast('抵扣数量更新成功', 'success')
      detailOpen.value = false
      queryClient.invalidateQueries({ queryKey: ['orders-list'] })
      queryClient.invalidateQueries({ queryKey: ['inventory'] })
      fetchOrders()
    } catch (e: unknown) {
      showToast(getErrorMessage(e, '抵扣更新仍失败，请稍后重试'), 'error')
    } finally {
      saving.value = false
    }
  }

  return {
    stagedItems,
    removeStagedItem,
    stagedOrders,
    stagedStockins,
    submitting,
    submitAll,
    editStagedVisible,
    editStagedIdx,
    editStagedData,
    editAvailableStock,
    openEditStaged,
    saveEditStaged,
    excelFile,
    importing,
    isDragOver,
    excelInputRef,
    handleExcelSelect,
    onDrop,
    downloadTemplate,
    handleImport,
    detailOpen,
    detailData,
    editForm,
    availableStockin,
    saving,
    deductRetryPending,
    openDetail,
    saveEditOrder,
    retryDeductUpdate,
    confirmDialog,
    genUid,
  }
}
