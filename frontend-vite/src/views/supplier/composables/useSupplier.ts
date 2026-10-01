/**
 * useSupplier — 供应商管理页面业务逻辑
 *
 * 封装供应商列表查询（服务端分页+搜索防抖）、
 * 新增/编辑表单状态、增删改与启用/停用切换（带确认对话框）。
 */
import { ref, reactive, computed } from 'vue'
import { useQuery, keepPreviousData } from '@tanstack/vue-query'
import { supplierApi } from '@/api'
import { showToast } from '@/composables/useToast'
import { useApiMutation } from '@/composables/useApiMutation'
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

function validateSupplierForm(name: string, phone: string): string | null {
  if (!name?.trim()) return '供应商名称不能为空'
  if (phone && !/^[\d\-+\s()]{6,20}$/.test(phone)) return '联系电话格式不正确'
  return null
}

export function useSupplier() {
  const actionId = ref<number | ''>(0)
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
  const form = reactive<SupplierFormData>({ id: 0, name: '', contact_person: '', phone: '', address: '', remark: '' })

  const addMutation = useApiMutation((data: SupplierFormData) => supplierApi.create(data), {
    invalidateKeys: ['suppliers-list'],
    successMsg: '添加成功',
    errorMsg: '添加失败',
  })

  async function handleAdd() {
    const error = validateSupplierForm(form.name, form.phone)
    if (error) {
      showToast(error, 'warning')
      return
    }
    const created = await addMutation.run(form)
    if (created !== undefined) {
      Object.assign(form, { name: '', contact_person: '', phone: '', address: '', remark: '' })
      formOpen.value = false
    }
  }

  const deleteMutation = useApiMutation((id: number) => supplierApi.delete(id), {
    invalidateKeys: ['suppliers-list'],
    successMsg: '删除成功',
    errorMsg: '删除失败',
  })

  async function handleDelete(row: Supplier) {
    if (!(await confirmDialog.confirm(`确定要删除供应商"${row.name}"吗？如果该供应商已关联BOM或采购订单，将无法删除。`))) return
    actionId.value = row.id
    await deleteMutation.run(row.id)
    actionId.value = 0
  }

  const toggleMutation = useApiMutation(
    async (row: Supplier) => {
      await supplierApi.toggleStatus(row.id)
      return row.status ? '禁用' : '启用'
    },
    {
      invalidateKeys: ['suppliers-list'],
      errorMsg: (row: Supplier) => `${row.status ? '禁用' : '启用'}失败`,
      onSuccess: (target) => showToast(`${target}成功`, 'success'),
    },
  )

  async function handleToggle(row: Supplier) {
    const target = row.status ? '禁用' : '启用'
    if (!(await confirmDialog.confirm(`确定要${target}供应商"${row.name}"吗？`))) return
    actionId.value = row.id
    await toggleMutation.run(row)
    actionId.value = 0
  }

  const editDialogVisible = ref(false)
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

  const editMutation = useApiMutation(
    (data: SupplierFormData) => supplierApi.update(data.id, data),
    {
      invalidateKeys: ['suppliers-list'],
      successMsg: '保存成功',
      errorMsg: '保存失败',
      onSuccess: () => {
        editDialogVisible.value = false
      },
    },
  )

  async function handleEdit() {
    const error = validateSupplierForm(editForm.name, editForm.phone)
    if (error) {
      showToast(error, 'warning')
      return
    }
    await editMutation.run(editForm)
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
    submitting: addMutation.isSaving,
    form,
    handleAdd,
    handleDelete,
    handleToggle,
    editDialogVisible,
    editSubmitting: editMutation.isSaving,
    editForm,
    openEditDialog,
    handleEdit,
  }
}