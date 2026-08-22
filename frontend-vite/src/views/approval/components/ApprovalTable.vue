<template>
  <div class="ap-table-wrap">
    <div v-if="isLoading" class="ap-empty">
      <UiSpinner />
    </div>
    <template v-else-if="items.length === 0">
      <div class="ap-empty">
        <FontAwesomeIcon icon="clipboard-check" aria-hidden="true" />
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
        <tr v-for="row in items" :key="row.id">
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
              <button class="ap-action-btn ap-action-success" :disabled="actionId === row.id" :aria-label="actionId === row.id ? '处理中…' : '通过'" @click="emit('approve', row)">
                {{ actionId === row.id ? '处理中…' : '通过' }}
              </button>
              <button class="ap-action-btn ap-action-danger" aria-label="驳回" @click="emit('reject', row)">驳回</button>
            </template>
            <span v-else class="ap-text-muted">已处理</span>
          </td>
        </tr>
      </tbody>
    </table>

    <UiPagination
      v-if="totalItems > perPage"
      :current-page="currentPage"
      :total-pages="totalPages"
      :total-items="totalItems"
      @update:current-page="emit('page', $event)"
    />
  </div>
</template>

<script setup lang="ts">
import type { ApprovalItem } from '@/types'
import UiPagination from '@/components/ui/UiPagination.vue'
import UiSpinner from '@/components/ui/UiSpinner.vue'

defineProps<{
  items: ApprovalItem[]
  isLoading: boolean
  actionId: number | ''
  totalItems: number
  perPage: number
  currentPage: number
  totalPages: number
  statusBadgeClass: (status: string) => string
  statusLabel: (status: string) => string
}>()

const emit = defineEmits<{
  approve: [row: ApprovalItem]
  reject: [row: ApprovalItem]
  page: [page: number]
}>()
</script>

<style scoped>
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
.ap-action-btn {
  padding: 5px 12px;
  border: 2px solid var(--color-border-light, #e2e8f0);
  border-radius: 9px;
  background: white;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.3s ease, border-color 0.3s ease, transform 0.3s ease;
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
.ap-text-muted { color: var(--color-text-muted); }
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
</style>