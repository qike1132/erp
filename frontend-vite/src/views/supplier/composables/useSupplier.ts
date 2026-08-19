/**
 * useSupplier — 供应商管理页面业务逻辑
 *
 * 封装供应商列表查询（服务端分页+搜索防抖）、
 * 新增/编辑表单状态、增删改与启用/停用切换（带确认对话框）。
 */
import { ref, reactive, computed } from 'vue'
import { useQuery, useQueryClient, keepPreviousData } from '@tanstack/vue-query'
import { supplierApi } from '@/api'
import { showToast } from '@/composables/useToast'
import { useDebouncedSearch } from '@/composables/useDebouncedSearch'
import { useConfirmDialog } from '@/composables/useConfirmDialog'
import type { Supplier } from '@/types'

/** 供应商表单数据（编辑模式含 id） */
export interface SupplierFormData {
  id: number
  name: string
  contact_person: string
  phone: string
  address: string
  remark: string
}

function extractErrorMessage(err: unknown, fallback: string): string {
  const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
  return detail || fallback
}

function validateSupplierForm(name: string, phone: string): string | null {
  if (!name?.trim()) return '供应商名称不能为空'
  if (phone && !/^[\d\-+\s()]{6,20}$/.test(phone)) return '联系电话格式不正确'
  return null
}

export function useSupplier() {
  const actionId = ref<number | ''>(0)
  const queryClient = useQueryClient()
  const confirmDialog = useConfirmDialog()

  const searchTerm = ref('')
  const currentPage = ref(1)
  const perPage = 20

  const { debounceSearch } = useDebouncedSearch()
  const debouncedSearch = ref('')

  function onSearchInput() {
    debounceSearch(() => {
      debouncedSearch.value = searchTerm.value
      currentPage.value = 1
    })
  }

  function clearSearch() {
    searchTerm.value = ''
    debouncedSearch.value = ''
    currentPage.value = 1
  }

  const { data: result, isLoading, isFetching } = useQuery({
    queryKey: ['suppliers-list', () => debouncedSearch.value, () => currentPage.value],
    queryFn: () => supplierApi.list({ per_page: perPage, page: currentPage.value, search: debouncedSearch.value || undefined }),
    staleTime: 30_000,
    gcTime: 60_000,
    placeholderData: keepPreviousData,
  })

  const suppliers = computed<Supplier[]>(() => result.value?.suppliers ?? [])
  const totalItems = computed(() => result.value?.total ?? suppliers.value.length)
  const totalPages = computed(() => Math.max(1, Math.ceil(totalItems.value / perPage)))

  function goPage(p: number) {
    currentPage.value = p
  }

  const formOpen = ref(false)
  const submitting = ref(false)
  const form = reactive<SupplierFormData>({ id: 0, name: '', contact_person: '', phone: '', address: '', remark: '' })

  async function handleAdd() {
    const error = validateSupplierForm(form.name, form.phone)
    if (error) {
      showToast(error, 'warning')
      return
    }
    submitting.value = true
    try {
      await supplierApi.create(form)
      showToast('添加成功', 'success')
      Object.assign(form, { name: '', contact_person: '', phone: '', address: '', remark: '' })
      formOpen.value = false
      queryClient.invalidateQueries({ queryKey: ['suppliers-list'] })
    } catch (err: unknown) {
      showToast(extractErrorMessage(err, '添加失败'), 'error')
    } finally {
      submitting.value = false
    }
  }

  async function handleDelete(row: Supplier) {
    if (!(await confirmDialog.confirm(`确定要删除供应商"${row.name}"吗？如果该供应商已关联BOM或采购订单，将无法删除。`))) return
    actionId.value = row.id
    try {
      await supplierApi.delete(row.id)
      showToast('删除成功', 'success')
      queryClient.invalidateQueries({ queryKey: ['suppliers-list'] })
    } catch (err: unknown) {
      showToast(extractErrorMessage(err, '删除失败'), 'error')
    } finally {
      actionId.value = 0
    }
  }

  async function handleToggle(row: Supplier) {
    const target = row.status ? '禁用' : '启用'
    if (!(await confirmDialog.confirm(`确定要${target}供应商"${row.name}"吗？`))) return
    actionId.value = row.id
    try {
      await supplierApi.toggleStatus(row.id)
      showToast(`${target}成功`, 'success')
      queryClient.invalidateQueries({ queryKey: ['suppliers-list'] })
    } catch (err: unknown) {
      showToast(extractErrorMessage(err, `${target}失败`), 'error')
    } finally {
      actionId.value = 0
    }
  }

  const editDialogVisible = ref(false)
  const editSubmitting = ref(false)
  const editForm = reactive<SupplierFormData>({ id: 0, name: '', contact_person: '', phone: '', address: '', remark: '' })

  function openEditDialog(row: Supplier) {
    Object.assign(editForm, {
      id: row.id,
      name: row.name,
      contact_person: row.contact_person || '',
      phone: row.phone || '',
      address: row.address || '',
      remark: row.remark || '',
    })
    editDialogVisible.value = true
  }

  async function handleEdit() {
    const error = validateSupplierForm(editForm.name, editForm.phone)
    if (error) {
      showToast(error, 'warning')
      return
    }
    editSubmitting.value = true
    try {
      await supplierApi.update(editForm.id, editForm)
      showToast('保存成功', 'success')
      editDialogVisible.value = false
      queryClient.invalidateQueries({ queryKey: ['suppliers-list'] })
    } catch (err: unknown) {
      showToast(extractErrorMessage(err, '保存失败'), 'error')
    } finally {
      editSubmitting.value = false
    }
  }

  return {
    actionId,
    confirmDialog,
    searchTerm,
    currentPage,
    perPage,
    onSearchInput,
    clearSearch,
    isLoading,
    isFetching,
    suppliers,
    totalItems,
    totalPages,
    goPage,
    formOpen,
    submitting,
    form,
    handleAdd,
    handleDelete,
    handleToggle,
    editDialogVisible,
    editSubmitting,
    editForm,
    openEditDialog,
    handleEdit,
  }
}