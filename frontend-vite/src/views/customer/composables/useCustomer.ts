/**
 * useCustomer — 客户管理页面业务逻辑
 *
 * 封装客户列表查询（服务端分页+搜索+状态筛选）、
 * 新增/编辑表单状态、增删改 mutations、启用/停用与删除确认。
 */
import { ref, reactive, computed } from 'vue'
import { useQuery, keepPreviousData } from '@tanstack/vue-query'
import { showToast } from '@/composables/useToast'
import { customerApi } from '@/api'
import { useApiMutation } from '@/composables/useApiMutation'
import { useDebouncedSearch } from '@/composables/useDebouncedSearch'
import { useConfirmDialog } from '@/composables/useConfirmDialog'
import type { Customer } from '@/types'
import { PHONE_RE, PHONE_INVALID_MSG } from '@/utils/validators' // L-16（2026-11-21 审计）：手机号正则提为共享常量，删除与 useSupplier 的重复

/** 客户表单数据 */
export interface CustomerFormData {
  id: number
  name: string
  contact: string
  phone: string
  address: string
  note: string
}

export function useCustomer() {
  const searchTerm = ref('')
  const currentPage = ref(1)
  const perPage = 15

  const { debounceSearch } = useDebouncedSearch()
  const debouncedSearch = ref('')

  function onSearchInput() {
    debounceSearch(() => {
      debouncedSearch.value = searchTerm.value
      currentPage.value = 1
    })
  }

  // L-14 / N-35（2026-11-21 审计）：删除死状态 statusFilter——
  // 页面无任何状态筛选 UI（CustomerView 未解构），恒为 'all' 的 ref 只会在
  // queryKey 里制造假依赖、白白干扰缓存命中。
  const { data: result, isLoading, isFetching } = useQuery({
    queryKey: ['customers-list', () => debouncedSearch.value, () => currentPage.value],
    queryFn: () =>
      customerApi.list({
        per_page: perPage,
        page: currentPage.value,
        search: debouncedSearch.value || undefined,
      }),
    staleTime: 30_000,
    gcTime: 60_000,
    placeholderData: keepPreviousData,
  })

  const customers = computed<Customer[]>(() => {
    const raw = result.value?.customers ?? []
    return raw.map((c: Customer) => ({ ...c, status: c.status === true || String(c.status) === 'active' }))
  })

  const totalItems = computed(() => result.value?.total ?? customers.value.length)
  const totalPages = computed(() => Math.ceil(totalItems.value / perPage) || 1)

  const formVisible = ref(false)
  const formMode = ref<'add' | 'edit'>('add')
  const submitting = ref(false)
  const form = reactive<CustomerFormData>({ id: 0, name: '', contact: '', phone: '', address: '', note: '' })

  function resetForm() {
    Object.assign(form, { id: 0, name: '', contact: '', phone: '', address: '', note: '' })
  }

  function openForm(mode: 'add' | 'edit', row?: Customer) {
    formMode.value = mode
    if (mode === 'edit' && row) {
      Object.assign(form, {
        id: row.id,
        name: row.name,
        contact: row.contact || '',
        phone: row.phone || '',
        address: row.address || '',
        note: row.note || '',
      })
    } else {
      resetForm()
    }
    formVisible.value = true
  }

  const addMutation = useApiMutation((data: CustomerFormData) => customerApi.create(data), {
    invalidateKeys: ['customers-list'],
    successMsg: '客户创建成功',
  })

  const editMutation = useApiMutation((data: CustomerFormData) => customerApi.update(data.id, data), {
    invalidateKeys: ['customers-list'],
    successMsg: '修改已保存',
  })

  const toggleMutation = useApiMutation((id: number) => customerApi.toggleStatus(id), {
    invalidateKeys: ['customers-list'],
  })

  const deleteMutation = useApiMutation((id: number) => customerApi.delete(id), {
    invalidateKeys: ['customers-list'],
    successMsg: '客户已删除',
  })

  const confirmDialog = useConfirmDialog()

  async function handleSubmit() {
    if (!form.name?.trim()) {
      showToast('客户名称不能为空', 'warning')
      return
    }
    if (form.phone && !PHONE_RE.test(form.phone)) {
      showToast(PHONE_INVALID_MSG, 'warning')
      return
    }
    submitting.value = true
    try {
      if (formMode.value === 'add') await addMutation.mutate(form)
      else await editMutation.mutate(form)
      formVisible.value = false
    } catch {
      /* useApiMutation already shows error */
    } finally {
      submitting.value = false
    }
  }

  const actionId = ref<number | null>(null)

  async function handleToggle(row: Customer) {
    const action = row.status ? '禁用' : '启用'
    if (!(await confirmDialog.confirm(`确定要${action}客户「${row.name}」吗？`))) return
    actionId.value = row.id
    try {
      await toggleMutation.mutate(row.id)
    } finally {
      actionId.value = null
    }
  }

  async function handleDelete(row: Customer) {
    if (!(await confirmDialog.confirm(`删除客户「${row.name}」后不可恢复，确认继续？`))) return
    actionId.value = row.id
    try {
      await deleteMutation.mutate(row.id)
    } finally {
      actionId.value = null
    }
  }

  return {
    searchTerm,
    currentPage,
    perPage,
    onSearchInput,
    isLoading,
    isFetching,
    customers,
    totalItems,
    totalPages,
    formVisible,
    formMode,
    submitting,
    form,
    openForm,
    handleSubmit,
    actionId,
    handleToggle,
    handleDelete,
    confirmDialog,
  }
}