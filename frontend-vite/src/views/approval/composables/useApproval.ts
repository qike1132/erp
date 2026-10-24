/**
 * useApproval — 审批管理页面业务逻辑
 *
 * 封装审批列表查询、状态/搜索筛选、分页、通过/驳回操作及驳回弹窗状态。
 */
import { ref, computed } from 'vue'
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import { approvalApi } from '@/api'
import { showToast } from '@/composables/useToast'
import { useDebouncedSearch } from '@/composables/useDebouncedSearch'
import type { ApprovalItem } from '@/types'

/** 审批统计卡片数据 */
export interface ApprovalStats {
  pending: number
  approved: number
  rejected: number
  total: number
}


export const APPROVAL_STATUS_OPTIONS: readonly { value: string; label: string }[] = [
  { value: '', label: '全部' },
  { value: 'pending', label: '待审批' },
  { value: 'approved', label: '已通过' },
  { value: 'rejected', label: '已驳回' },
]

/** 提取 axios 错误中的 detail 信息 */
function extractErrMsg(err: unknown): string {
  return (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || '操作失败'
}

export function useApproval() {
  const queryClient = useQueryClient()
  const actionId = ref<number | ''>(0)
  const searchTerm = ref('')
  const statusFilter = ref('')
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

  const { data: result, isLoading } = useQuery({
    queryKey: ['approvals', () => statusFilter.value, () => debouncedSearch.value, () => currentPage.value],
    queryFn: () =>
      approvalApi.list({
        status: statusFilter.value || undefined,
        search: debouncedSearch.value || undefined,
        page: currentPage.value,
        per_page: perPage,
      }),
    staleTime: 30_000,
    gcTime: 60_000,
  })

  const items = computed(() => result.value?.data ?? [])
  const totalItems = computed(() => result.value?.total ?? items.value.length)
  const totalPages = computed(() => Math.max(1, Math.ceil(totalItems.value / perPage)))

  const stats = computed<ApprovalStats | null>(() => {
    const r = result.value
    if (!r) return null
    return {
      pending: r.pending_count ?? 0,
      approved: r.approved_count ?? 0,
      rejected: r.rejected_count ?? 0,
      total: (r.pending_count ?? 0) + (r.approved_count ?? 0) + (r.rejected_count ?? 0),
    }
  })

  function goPage(p: number) {
    currentPage.value = p
  }

  function statusBadgeClass(status: string): string {
    if (status === 'approved') return 'ap-badge-success'
    if (status === 'rejected') return 'ap-badge-danger'
    return 'ap-badge-warning'
  }

  function statusLabel(status: string): string {
    if (status === 'approved') return '已通过'
    if (status === 'rejected') return '已驳回'
    return '待审批'
  }

  async function handleApprove(row: ApprovalItem) {
    actionId.value = row.id
    try {
      await approvalApi.approve(row.id)
      showToast('审批通过', 'success')
      queryClient.invalidateQueries({ queryKey: ['approvals'] })
    } catch (err: unknown) {
      showToast(extractErrMsg(err), 'error')
      queryClient.invalidateQueries({ queryKey: ['approvals'] })
    } finally {
      // AUD-11（2026-10-24 审计）：成功/失败都复位——原先失败路径不复位，
      // 该行按钮永久禁用显示「处理中…」直到刷新（同仓 user/supplier/customer 均正确复位）
      actionId.value = 0
    }
  }

  const rejectDialogVisible = ref(false)
  const rejectReason = ref('')
  const rejectTarget = ref<ApprovalItem | null>(null)
  const rejectSaving = ref(false)

  function openRejectDialog(row: ApprovalItem) {
    rejectTarget.value = row
    rejectReason.value = ''
    rejectDialogVisible.value = true
  }

  async function handleReject() {
    if (!rejectReason.value) {
      showToast('请输入驳回原因', 'warning')
      return
    }
    rejectSaving.value = true
    try {
      if (rejectTarget.value) {
        await approvalApi.reject(rejectTarget.value.id, rejectReason.value)
      }
      showToast('已驳回', 'success')
      rejectDialogVisible.value = false
      queryClient.invalidateQueries({ queryKey: ['approvals'] })
    } catch (err: unknown) {
      showToast(extractErrMsg(err), 'error')
      queryClient.invalidateQueries({ queryKey: ['approvals'] })
    } finally {
      rejectSaving.value = false
    }
  }

  return {
    actionId,
    searchTerm,
    statusFilter,
    currentPage,
    perPage,
    statusOptions: APPROVAL_STATUS_OPTIONS,
    onSearchInput,
    clearSearch,
    isLoading,
    items,
    totalItems,
    totalPages,
    stats,
    goPage,
    statusBadgeClass,
    statusLabel,
    handleApprove,
    rejectDialogVisible,
    rejectReason,
    rejectSaving,
    openRejectDialog,
    handleReject,
  }
}