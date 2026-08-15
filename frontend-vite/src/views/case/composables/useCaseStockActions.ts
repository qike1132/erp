import { ref, reactive, type Ref } from 'vue'
import { useQueryClient } from '@tanstack/vue-query'
import { caseApi } from '@/api'
import { showToast } from '@/composables/useToast'
import { useConfirmDialog } from '@/composables/useConfirmDialog'
import { getErrorMessage } from '@/types/errors'

type StockMode = 'stockin' | 'stockout'

export function useCaseStockActions(
  mode: Ref<StockMode>,
  staged: Ref<any[]>,
  currentStock: Ref<number>,
) {
  const queryClient = useQueryClient()
  const confirmDialog = useConfirmDialog()

  // ===== Batch submit =====
  const submitting = ref(false)

  async function submitBatch() {
    submitting.value = true
    try {
      const result =
        mode.value === 'stockin'
          ? await caseApi.batchStockin({
              stockins: staged.value.map((stock) => ({
                productId: stock.productId,
                customer: stock.customer,
                quantity: stock.quantity,
                stockinDate: stock.date,
                note: stock.note,
              })),
            })
          : await caseApi.batchStockout({
              stockouts: staged.value.map((stock) => ({
                productId: stock.productId,
                customer: stock.customer,
                quantity: stock.quantity,
                stockout_date: stock.date,
                note: stock.note,
              })),
            })

      const res = result as { failed?: Array<{ index: number; error: string }>; results?: Array<{ success?: boolean; error?: string }> }
      let failedList: Array<{ index: number; error: string }> = []
      if (mode.value === 'stockin') {
        failedList = res?.failed ?? []
      } else {
        // 出库接口返回 results 列表，需按 success 字段反算失败项
        const results: Array<{ success?: boolean; error?: string }> = res?.results ?? []
        failedList = results
          .map((r, i) => (r.success ? null : { index: i, error: r.error || '出库失败' }))
          .filter((item): item is { index: number; error: string } => item !== null)
      }
      if (failedList.length > 0) {
        const failedIndices = new Set(failedList.map((f) => f.index))
        staged.value = staged.value.filter((_, i) => failedIndices.has(i))
        showToast(
          `${mode.value === 'stockin' ? '入库' : '出库'}部分失败：${failedList.map((f) => f.error).join('；')}`,
          'error',
        )
      } else {
        showToast(mode.value === 'stockin' ? '入库成功' : '出库成功', 'success')
        staged.value = []
        currentStock.value = 0
      }
      queryClient.invalidateQueries({ queryKey: ['case-stockins'] })
      queryClient.invalidateQueries({ queryKey: ['case-stockouts'] })
    } catch (err: unknown) {
      showToast(getErrorMessage(err, mode.value === 'stockin' ? '入库失败' : '出库失败'), 'error')
    } finally {
      submitting.value = false
    }
  }

  // ===== Batch import/export =====
  const showBatchUpload = ref(false)
  const excelFile = ref<File | null>(null)
  const importing = ref(false)
  const templateDownloading = ref(false)

  function onExcelFileChange(files: FileList) {
    const file = files[0]
    if (!file) return
    if (!(file.name.endsWith('.xlsx') || file.name.endsWith('.xls'))) {
      showToast('请上传 Excel 文件（.xlsx 或 .xls）', 'error')
      return
    }
    if (file.size > 10 * 1024 * 1024) {
      showToast(`文件大小不能超过 10MB，当前文件 ${(file.size / 1024 / 1024).toFixed(1)}MB`, 'error')
      return
    }
    excelFile.value = file
  }

  async function handleDownloadTemplate() {
    templateDownloading.value = true
    try {
      await caseApi.downloadTemplate(mode.value === 'stockin' ? '皮套入库模板.xlsx' : '皮套出库模板.xlsx')
    } catch {
      showToast('下载失败', 'error')
    } finally {
      templateDownloading.value = false
    }
  }

  async function handleImportExcel() {
    if (!excelFile.value) return
    importing.value = true
    try {
      const formData = new FormData()
      formData.append('file', excelFile.value)
      const res = (await (mode.value === 'stockin' ? caseApi.importStockins(formData) : caseApi.importStockouts(formData))) as { success: boolean; imported?: number; message?: string }
      if (res.success) {
        showToast(`成功导入 ${res.imported} 条记录`, 'success')
        excelFile.value = null
        queryClient.invalidateQueries({ queryKey: mode.value === 'stockin' ? ['case-stockins'] : ['case-stockouts'] })
      } else {
        showToast(res.message || '导入失败', 'error')
      }
    } catch (err: unknown) {
      showToast(getErrorMessage(err, '导入失败'), 'error')
    } finally {
      importing.value = false
    }
  }

  // ===== Delete record =====
  const actionId = ref<number | ''>(0)

  async function handleDelete(type: StockMode, row: any) {
    if (!(await confirmDialog.confirm(`确定要删除这条${type === 'stockin' ? '入库' : '出库'}记录吗？`))) return
    actionId.value = row.id
    try {
      await (type === 'stockin' ? caseApi.deleteStockin(row.id) : caseApi.deleteStockout(row.id))
      showToast('删除成功', 'success')
      queryClient.invalidateQueries({ queryKey: [type === 'stockin' ? 'case-stockins' : 'case-stockouts'] })
    } catch (err: unknown) {
      showToast(getErrorMessage(err, '删除失败'), 'error')
    } finally {
      actionId.value = 0
    }
  }

  // ===== Edit record =====
  const editDialogOpen = ref(false)
  const editMode = ref<StockMode>('stockin')
  const editForm = reactive({ id: 0, customer: '', date: '', productName: '', quantity: 1, note: '' })

  function openEditModal(type: StockMode, row: any) {
    editMode.value = type
    editForm.id = row.id
    editForm.customer = row.customer || ''
    editForm.date = type === 'stockin' ? row.stockin_date || '' : row.stockout_date || ''
    editForm.productName = row.case_name || ''
    editForm.quantity = row.quantity || 1
    editForm.note = row.note || ''
    editDialogOpen.value = true
    const detailPromise = type === 'stockin' ? caseApi.getStockin(row.id) : caseApi.getStockout(row.id)
    detailPromise
      .then((data: any) => {
        editForm.customer = data.customer || ''
        editForm.date = type === 'stockin' ? data.stockin_date || '' : data.stockout_date || ''
        editForm.productName = data.case_name || ''
        editForm.quantity = data.quantity || 1
        editForm.note = data.note || ''
      })
      .catch(() => {})
  }

  async function saveEdit() {
    try {
      const payload: Record<string, any> = {
        customer: editForm.customer,
        quantity: editForm.quantity,
        note: editForm.note,
      }
      if (editMode.value === 'stockin') payload.stockin_date = editForm.date
      else payload.stockout_date = editForm.date
      await (editMode.value === 'stockin' ? caseApi.updateStockin(editForm.id, payload) : caseApi.updateStockout(editForm.id, payload))
      showToast('更新成功', 'success')
      editDialogOpen.value = false
      queryClient.invalidateQueries({ queryKey: [editMode.value === 'stockin' ? 'case-stockins' : 'case-stockouts'] })
    } catch (err: unknown) {
      showToast(getErrorMessage(err, '更新失败'), 'error')
    }
  }

  return {
    confirmDialog,
    submitting,
    submitBatch,
    showBatchUpload,
    excelFile,
    importing,
    templateDownloading,
    onExcelFileChange,
    handleDownloadTemplate,
    handleImportExcel,
    actionId,
    handleDelete,
    editDialogOpen,
    editMode,
    editForm,
    openEditModal,
    saveEdit,
  }
}
