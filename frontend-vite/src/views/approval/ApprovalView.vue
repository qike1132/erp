<template>
  <div class="ap-container">
    <div class="ap-card ap-card-main">
      <!-- 卡片头部 -->
      <div class="ap-card-header">
        <HeaderTabs />
      </div>

      <!-- 统计卡片 -->
      <div v-if="stats" class="ap-stats">
        <div class="ap-stat-card ap-stat-pending">
          <div class="ap-stat-icon"><i class="fas fa-clock" /></div>
          <div class="ap-stat-value">{{ stats.pending ?? 0 }}</div>
          <div class="ap-stat-label">待审批</div>
        </div>
        <div class="ap-stat-card ap-stat-approved">
          <div class="ap-stat-icon"><i class="fas fa-check-circle" /></div>
          <div class="ap-stat-value">{{ stats.approved ?? 0 }}</div>
          <div class="ap-stat-label">已通过</div>
        </div>
        <div class="ap-stat-card ap-stat-rejected">
          <div class="ap-stat-icon"><i class="fas fa-times-circle" /></div>
          <div class="ap-stat-value">{{ stats.rejected ?? 0 }}</div>
          <div class="ap-stat-label">已驳回</div>
        </div>
        <div class="ap-stat-card ap-stat-total">
          <div class="ap-stat-icon"><i class="fas fa-list-check" /></div>
          <div class="ap-stat-value">{{ stats.total ?? 0 }}</div>
          <div class="ap-stat-label">合计</div>
        </div>
      </div>

      <!-- 搜索与筛选 -->
      <div class="ap-filter-bar">
        <div class="ap-search-wrapper">
          <i class="fas fa-search ap-search-icon" />
          <input v-model="searchTerm" class="ap-search-input" placeholder="搜索类型或摘要..." />
        </div>
        <div class="ap-filter-group">
          <button
            v-for="opt in statusOptions"
            :key="opt.value"
            :class="['ap-filter-btn', { active: statusFilter === opt.value }]"
            @click="statusFilter = opt.value"
          >
            {{ opt.label }}
          </button>
        </div>
      </div>

      <!-- 表格 -->
      <div class="ap-table-wrap">
        <div v-if="isLoading" class="ap-empty">
          <i class="fas fa-spinner fa-spin" />
          <span>加载中...</span>
        </div>
        <template v-else-if="filteredList.length === 0">
          <div class="ap-empty">
            <i class="fas fa-clipboard-check" />
            <span>暂无审批记录</span>
          </div>
        </template>
        <table v-else class="ap-table">
          <thead>
            <tr>
              <th>类型</th>
              <th style="text-align: left">订单号</th>
              <th>提交人</th>
              <th>提交时间</th>
              <th>状态</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in filteredList" :key="row.id">
              <td>{{ row.operation_type_display }}</td>
              <td style="text-align: left">{{ row.order_no }}</td>
              <td>{{ row.requester_name }}</td>
              <td>{{ row.request_time }}</td>
              <td>
                <span :class="['ap-badge', statusBadgeClass(row.status)]">
                  {{ statusLabel(row.status) }}
                </span>
              </td>
              <td>
                <template v-if="row.status === 'pending'">
                  <button class="ap-action-btn ap-action-success" :disabled="actionId === row.id" @click="handleApprove(row)">
                    {{ actionId === row.id ? '处理中...' : '通过' }}
                  </button>
                  <button class="ap-action-btn ap-action-danger" @click="openRejectDialog(row)">驳回</button>
                </template>
                <span v-else class="ap-text-muted">已处理</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- 驳回弹窗 -->
    <UiDialog :open="rejectDialogVisible" title="驳回原因" max-width-class="max-w-[400px]" @update:open="rejectDialogVisible = $event">
      <textarea
        v-model="rejectReason"
        rows="3"
        placeholder="请输入驳回原因"
        class="ap-form-textarea"
      />
      <template #footer>
        <button class="ap-action-btn" @click="rejectDialogVisible = false">取消</button>
        <button class="ap-action-btn ap-action-danger" :disabled="rejectSaving" @click="handleReject">
          {{ rejectSaving ? '提交中...' : '确认驳回' }}
        </button>
      </template>
    </UiDialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import { approvalApi } from '@/api'
import UiDialog from '@/components/ui/UiDialog.vue'
import HeaderTabs from '@/layouts/components/HeaderTabs.vue'
import { showToast } from '@/composables/useToast'

interface ApprovalRow {
  id: number
  order_id: number
  order_no: string | null
  requester_id: number
  requester_name: string | null
  operation_type: string
  operation_type_display: string
  operation_data: string | null
  status: string
  status_display: string
  request_time: string | null
  approver_id: number | null
  approver_name: string | null
  approval_time: string | null
  rejection_reason: string | null
  lock_time: string | null
}

interface ApprovalListResult {
  success: boolean
  data: ApprovalRow[]
  pending_count: number
  approved_count: number
  rejected_count: number
}

const queryClient = useQueryClient()
const actionId = ref<number | ''>(0)
const searchTerm = ref('')
const statusFilter = ref('')

const statusOptions = [
  { value: '', label: '全部' },
  { value: 'pending', label: '待审批' },
  { value: 'approved', label: '已通过' },
  { value: 'rejected', label: '已驳回' },
]

const { data: result, isLoading } = useQuery({
  queryKey: ['approvals', statusFilter],
  queryFn: () => approvalApi.list({ status: statusFilter.value || undefined }) as Promise<ApprovalListResult>,
  staleTime: 30_000,
})

const items = computed(() => result.value?.data ?? [])

const stats = computed(() => {
  const r = result.value
  if (!r) return null
  return {
    pending: r.pending_count ?? 0,
    approved: r.approved_count ?? 0,
    rejected: r.rejected_count ?? 0,
    total: (r.pending_count ?? 0) + (r.approved_count ?? 0) + (r.rejected_count ?? 0),
  }
})

const filteredList = computed(() => {
  if (!searchTerm.value) return items.value
  const q = searchTerm.value.toLowerCase()
  return items.value.filter(
    (i) => i.operation_type_display?.toLowerCase().includes(q)
      || i.order_no?.toLowerCase().includes(q)
      || i.requester_name?.toLowerCase().includes(q),
  )
})

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

async function handleApprove(row: ApprovalRow) {
  actionId.value = row.id
  try {
    await approvalApi.approve(row.id)
    showToast('审批通过', 'success')
    queryClient.invalidateQueries({ queryKey: ['approvals'] })
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : '操作失败'
    showToast(msg, 'error')
  } finally {
    actionId.value = 0
  }
}

const rejectDialogVisible = ref(false)
const rejectReason = ref('')
const rejectTarget = ref<ApprovalRow | null>(null)
const rejectSaving = ref(false)

function openRejectDialog(row: ApprovalRow) {
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
    const msg = err instanceof Error ? err.message : '操作失败'
    showToast(msg, 'error')
  } finally {
    rejectSaving.value = false
  }
}
</script>

<style scoped>
/* Container */
.ap-container {
  padding: 8px;
  margin: 0 auto;
  height: 100%;
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
}

/* Card */
.ap-card {
  background: white;
  border-radius: 18px;
  border: 1px solid var(--color-border-light, #e2e8f0);
  box-shadow: 0 1px 3px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.06);
  transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);
  overflow: hidden;
}
.ap-card:hover {
  box-shadow: 0 12px 36px rgba(0,0,0,0.08), 0 48px 144px rgba(0,0,0,0.12);
  transform: translateY(-6px);
}
.ap-card-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

/* Card Header */
.ap-card-header {
  display: flex;
  flex-wrap: nowrap;
  justify-content: space-between;
  align-items: center;
  padding: 10px 24px;
  border-bottom: 1px solid var(--color-border-light, #f1f5f9);
  gap: 12px;
}
.ap-card-header :deep(.ht-bar) {
  width: auto;
  margin: 0;
}
.ap-card-title-group {
  display: flex;
  align-items: center;
  gap: 12px;
}
.ap-card-title-group h3 {
  font-size: 17px;
  font-weight: 700;
  color: var(--color-text);
  margin: 0;
}
.ap-card-title-group small {
  font-size: 12px;
  color: var(--color-text-secondary);
  display: block;
  margin-top: 2px;
}

/* Icon Box */
.ap-icon-box {
  width: 46px;
  height: 46px;
  border-radius: 13px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 19px;
  flex-shrink: 0;
}
.ap-icon-purple {
  background: linear-gradient(135deg, var(--color-purple-100), var(--color-purple-200));
  color: var(--color-purple-800);
}

/* Stats */
.ap-stats {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  padding: 16px 24px;
  border-bottom: 1px solid var(--color-border-light, #f1f5f9);
}
.ap-stat-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  padding: 16px;
  border-radius: 13px;
  transition: all 0.3s ease;
}
.ap-stat-card:hover {
  transform: translateY(-1px);
}
.ap-stat-icon {
  font-size: 18px;
  margin-bottom: 4px;
}
.ap-stat-value {
  font-size: 28px;
  font-weight: 800;
  line-height: 1;
  font-variant-numeric: tabular-nums;
}
.ap-stat-label {
  font-size: 12px;
  color: var(--color-text-secondary);
  margin-top: 2px;
}
.ap-stat-pending {
  background: var(--color-warning-50);
  border: 1px solid var(--color-warning-200);
}
.ap-stat-pending .ap-stat-icon, .ap-stat-pending .ap-stat-value { color: var(--color-warning-600); }
.ap-stat-approved {
  background: var(--color-success-50);
  border: 1px solid var(--color-success-200);
}
.ap-stat-approved .ap-stat-icon, .ap-stat-approved .ap-stat-value { color: var(--color-success-600); }
.ap-stat-rejected {
  background: var(--color-danger-50);
  border: 1px solid var(--color-danger-200);
}
.ap-stat-rejected .ap-stat-icon, .ap-stat-rejected .ap-stat-value { color: var(--color-danger-600); }
.ap-stat-total {
  background: var(--color-primary-50);
  border: 1px solid var(--color-primary-200);
}
.ap-stat-total .ap-stat-icon, .ap-stat-total .ap-stat-value { color: var(--color-primary-600); }

/* Filter Bar */
.ap-filter-bar {
  display: flex;
  gap: 12px;
  padding: 12px 24px;
  border-bottom: 1px solid var(--color-border-light, #f1f5f9);
  align-items: center;
}
.ap-search-wrapper {
  position: relative;
  width: 220px;
  flex-shrink: 0;
}
.ap-search-icon {
  position: absolute;
  left: 14px;
  top: 50%;
  transform: translateY(-50%);
  color: var(--color-text-muted);
  font-size: 12px;
}
.ap-search-input {
  width: 100%;
  padding: 9px 14px 9px 36px;
  border: 2px solid var(--color-border-light, #e2e8f0);
  border-radius: 9px;
  background: white;
  font-size: 13px;
  outline: none;
  transition: all 0.3s ease;
  font-family: inherit;
  color: var(--color-text);
}
.ap-search-input:focus {
  border-color: var(--color-primary-400);
  background: white;
  box-shadow: 0 0 0 4px rgba(0, 148, 191, 0.1);
}
.ap-filter-group {
  display: flex;
  gap: 8px;
}
.ap-filter-btn {
  padding: 7px 14px;
  background: var(--color-surface, #f8fafc);
  border: 2px solid var(--color-border-light, #e2e8f0);
  border-radius: 9px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
  color: var(--color-text-secondary);
}
.ap-filter-btn:hover {
  transform: translateY(-1px);
}
.ap-filter-btn.active {
  background: var(--color-primary-50);
  border-color: var(--color-primary-400);
  color: var(--color-primary-700);
}

/* Table */
.ap-table-wrap {
  flex: 1;
  overflow-y: auto;
  min-height: 0;
}
.ap-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.ap-table thead th {
  padding: 10px 14px;
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  background: var(--color-surface, #f8fafc);
  border-bottom: 2px solid var(--color-border-light, #e2e8f0);
  color: var(--color-text-secondary);
  text-align: center;
}
.ap-table tbody td {
  padding: 10px 14px;
  font-size: 13px;
  border-bottom: 1px solid var(--color-border-light, #f1f5f9);
  text-align: center;
  transition: background 0.2s ease;
  color: var(--color-text);
}
.ap-table tbody tr:hover {
  background: var(--color-primary-50);
}

/* Badge */
.ap-badge {
  display: inline-block;
  padding: 5px 12px;
  border-radius: 16px;
  font-size: 12px;
  font-weight: 600;
}
.ap-badge-success { background: var(--color-success-50); color: var(--color-success-600); }
.ap-badge-danger { background: var(--color-danger-50); color: var(--color-danger-600); }
.ap-badge-warning { background: var(--color-warning-50); color: var(--color-warning-600); }

/* Action Buttons */
.ap-action-btn {
  padding: 5px 12px;
  border: 2px solid var(--color-border-light, #e2e8f0);
  border-radius: 9px;
  background: white;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.3s ease;
  color: var(--color-text-secondary);
  margin-right: 6px;
}
.ap-action-success {
  color: var(--color-success-600);
  border-color: var(--color-success-200);
}
.ap-action-success:hover:not(:disabled) {
  background: var(--color-success-50);
  border-color: var(--color-success-300);
  transform: translateY(-1px);
}
.ap-action-danger {
  color: var(--color-danger-500);
  border-color: var(--color-danger-200);
}
.ap-action-danger:hover:not(:disabled) {
  background: var(--color-danger-50);
  border-color: var(--color-danger-300);
  transform: translateY(-1px);
}
.ap-action-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

/* Text */
.ap-text-muted { color: var(--color-text-muted); }

/* Empty */
.ap-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  padding: 40px 20px;
  color: var(--color-text-muted);
}
.ap-empty i { font-size: 28px; opacity: 0.5; }
.ap-empty span { font-size: 14px; }

/* Form Textarea */
.ap-form-textarea {
  width: 100%;
  padding: 8px 12px;
  border: 2px solid var(--color-border-light, #e2e8f0);
  border-radius: 10px;
  font-size: 14px;
  transition: all 0.3s ease;
  outline: none;
  font-family: inherit;
  color: var(--color-text);
  resize: none;
  background: white;
}
.ap-form-textarea:focus {
  border-color: var(--color-primary-400);
  background: white;
  box-shadow: 0 0 0 4px rgba(0, 148, 191, 0.1);
}
</style>
