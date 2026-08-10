<template>
  <div class="brl-container">
    <div v-if="loading" class="brl-loading">
      <UiSpinner />
    </div>

    <div v-else-if="!records.length" class="brl-empty">
      <FontAwesomeIcon icon="inbox" aria-hidden="true" />
      <p>暂无备份记录</p>
    </div>

    <div v-else class="brl-list">
      <div v-for="r in records" :key="r.id" class="brl-item" :class="`brl-${r.status}`">
        <div class="brl-item-header">
          <div class="brl-item-icon" :class="iconClass(r)">
            <i :class="iconName(r)"  aria-hidden="true" />
          </div>
          <div class="brl-item-info">
            <div class="brl-item-name">
              {{ r.filename || '-' }}
              <span v-if="r.trigger_type === 'auto'" class="brl-auto-badge">自动</span>
            </div>
            <div class="brl-item-meta">
              <span v-if="r.operator"><FontAwesomeIcon icon="user" aria-hidden="true" /> {{ r.operator }}</span>
              <span v-if="r.created_at"><FontAwesomeIcon icon="clock" aria-hidden="true" /> {{ formatDateTime(r.created_at) }}</span>
              <span v-if="r.duration_seconds != null"><FontAwesomeIcon icon="stopwatch" aria-hidden="true" /> {{ r.duration_seconds.toFixed(1) }}s</span>
            </div>
          </div>
          <div class="brl-item-status">
            <span class="brl-status-badge" :class="statusClass(r.status)">
              {{ statusLabel(r.status) }}
            </span>
          </div>
        </div>
        <div class="brl-item-detail">
          <span v-if="r.table_count != null"><FontAwesomeIcon icon="table" aria-hidden="true" /> {{ r.table_count }} 表</span>
          <span v-if="r.total_rows != null"><FontAwesomeIcon icon="list" aria-hidden="true" /> {{ r.total_rows }} 条</span>
          <span v-if="r.size != null"><FontAwesomeIcon icon="weight-hanging" aria-hidden="true" /> {{ formatSize(r.size) }}</span>
          <span v-if="r.remark" class="brl-remark"><FontAwesomeIcon icon="comment" aria-hidden="true" /> {{ r.remark }}</span>
        </div>
        <div v-if="r.error_message" class="brl-error">
          <FontAwesomeIcon icon="exclamation-circle" aria-hidden="true" /> {{ r.error_message }}
        </div>
      </div>
    </div>

    <!-- Pagination -->
    <div v-if="total > pageSize" class="brl-pagination">
      <button
        class="brl-page-btn"
        :disabled="page <= 1"
        @click="$emit('page-change', page - 1)"
       aria-label="上一页">
        <FontAwesomeIcon icon="chevron-left" aria-hidden="true" />
      </button>
      <span class="brl-page-info">{{ page }} / {{ Math.ceil(total / pageSize) }}</span>
      <button
        class="brl-page-btn"
        :disabled="page >= Math.ceil(total / pageSize)"
        @click="$emit('page-change', page + 1)"
      >
        <FontAwesomeIcon icon="chevron-right" aria-hidden="true" />
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { BackupRecord } from '@/types'
import { formatDateTime } from '@/utils/format'

defineProps<{
  records: BackupRecord[]
  total: number
  page: number
  pageSize: number
  loading?: boolean
}>()

defineEmits<{
  (e: 'page-change', page: number): void
}>()

function iconClass(r: BackupRecord) {
  if (r.status === 'failed') return 'brl-icon-error'
  if (r.type === 'incremental') return 'brl-icon-inc'
  return 'brl-icon-full'
}

function iconName(r: BackupRecord) {
  if (r.status === 'failed') return 'fas fa-times-circle'
  if (r.type === 'incremental') return 'fas fa-layer-group'
  if (r.type === 'restore') return 'fas fa-undo-alt'
  return 'fas fa-check-circle'
}

function statusClass(status: string) {
  if (status === 'success') return 'brl-badge-success'
  if (status === 'failed') return 'brl-badge-error'
  return 'brl-badge-running'
}

function statusLabel(status: string) {
  if (status === 'success') return '成功'
  if (status === 'failed') return '失败'
  return '运行中'
}



function formatSize(bytes: number): string {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
}
</script>

<style scoped>
.brl-container {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.brl-loading,
.brl-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 32px 16px;
  color: var(--color-text-muted);
}

.brl-empty i {
  font-size: 24px;
  opacity: 0.5;
}

.brl-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.brl-item {
  border: 1px solid var(--color-border-light);
  border-radius: 12px;
  padding: 12px 14px;
  background: white;
  transition: border-color 0.3s ease, box-shadow 0.3s ease;
}

.brl-item:hover {
  border-color: var(--color-primary-300);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
}

.brl-item.brl-failed {
  border-left: 3px solid var(--color-danger-400);
}

.brl-item-header {
  display: flex;
  align-items: center;
  gap: 10px;
}

.brl-item-icon {
  width: 32px;
  height: 32px;
  border-radius: 9px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  flex-shrink: 0;
}

.brl-icon-full {
  background: linear-gradient(135deg, var(--color-success-100), var(--color-success-200));
  color: var(--color-success-700);
}

.brl-icon-inc {
  background: linear-gradient(135deg, var(--color-primary-100), var(--color-primary-200));
  color: var(--color-primary-700);
}

.brl-icon-error {
  background: linear-gradient(135deg, var(--color-danger-100), var(--color-danger-200));
  color: var(--color-danger-700);
}

.brl-item-info {
  flex: 1;
  min-width: 0;
}

.brl-item-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text);
  display: flex;
  align-items: center;
  gap: 6px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.brl-auto-badge {
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 10px;
  background: var(--color-primary-50);
  color: var(--color-primary-600);
  font-weight: 600;
}

.brl-item-meta {
  display: flex;
  gap: 10px;
  font-size: 11px;
  color: var(--color-text-muted);
  margin-top: 2px;
}

.brl-item-meta i {
  font-size: 10px;
}

.brl-status-badge {
  padding: 3px 10px;
  border-radius: 12px;
  font-size: 11px;
  font-weight: 600;
}

.brl-badge-success {
  background: var(--color-success-50);
  color: var(--color-success-600);
}

.brl-badge-error {
  background: var(--color-danger-50);
  color: var(--color-danger-600);
}

.brl-badge-running {
  background: var(--color-warning-50);
  color: var(--color-warning-600);
}

.brl-item-detail {
  display: flex;
  gap: 12px;
  font-size: 11px;
  color: var(--color-text-secondary);
  margin-top: 6px;
  padding-top: 6px;
  border-top: 1px solid var(--color-border-light);
}

.brl-item-detail i {
  font-size: 10px;
}

.brl-remark {
  color: var(--color-text-muted);
  font-style: italic;
}

.brl-error {
  font-size: 12px;
  color: var(--color-danger-500);
  margin-top: 6px;
  padding-top: 6px;
  border-top: 1px solid var(--color-border-light);
}

.brl-pagination {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 8px 0;
}

.brl-page-btn {
  width: 28px;
  height: 28px;
  border-radius: 8px;
  border: 1px solid var(--color-border-light);
  background: white;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: border-color 0.2s ease, color 0.2s ease;
  font-size: 11px;
  color: var(--color-text-secondary);
}

.brl-page-btn:hover:not(:disabled) {
  border-color: var(--color-primary-400);
  color: var(--color-primary-600);
}

.brl-page-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.brl-page-info {
  font-size: 12px;
  color: var(--color-text-secondary);
}
</style>
